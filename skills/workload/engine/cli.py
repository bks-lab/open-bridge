"""The command line: argument parsing, a dispatch table, and the exit map.

Pure wiring on purpose. Anything that decides something belongs in a module,
where it can be tested without a process. The exit map is the one piece of
policy here, and it lives on the exception classes rather than in a chain of
comparisons:

    0  clean
    1  findings, or applied but unverified
    2  usage, configuration or declaration error
    3  refused by a guard
    4  unreachable, or a deadline expired

The 4 exists so an expired deadline can never be mistaken for a clean run.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import backends, config, errors, hosts, model, report


def exit_code_for(obj) -> int:
    """Process exit code for a report or an error."""
    if isinstance(obj, BaseException):
        return int(getattr(obj, "exit_code", 2))
    code = getattr(obj, "exit_code", None)
    return int(code) if code is not None else 0


def _module(name: str):
    """Import an engine module on use, so the command line stays importable."""
    return importlib.import_module(f".{name}", __package__)


def _bridge(args):
    """Root and configuration, and the backends built from THAT configuration.

    The `configure` call is the point of this function beyond the two lines
    above it. `backends.configure(cfg)` rebuilds every backend from the live
    configuration and existed with NO CALLER anywhere in the skill until
    2026-08-25: the registry held the instances from `build(None)`, so an
    instance that set `workloads.label_prefix` in its config got the built-in
    default anyway. No error, no warning, no trace in the report.

    Here and not per command, because every subcommand comes through this
    function; wiring it twelve times is twelve chances to forget it once.
    """
    root = Path(args.root).resolve() if args.root else config.find_repo_root()
    cfg = config.load_config(root)
    config.require_enabled(cfg)
    backends.configure(cfg)
    return root, cfg


def _one(root, cfg, workload_id: str):
    for workload in model.load_all(root, cfg):
        if workload.id == workload_id:
            return workload, hosts.resolve_host(workload.placement.host, root)
    raise errors.DeclarationError(f"no declaration with id {workload_id!r} under {cfg.dir}",
                                  source=str(root))


def _context(host, cfg, timeout_sec: int):
    return _module("exec").probe_context(host, cfg, timeout_sec=timeout_sec)


def _keep(workload, args) -> bool:
    if workload.is_retired and not getattr(args, "retired", False):
        return False
    for attribute, value in (("host", workload.placement.host),
                             ("kind", workload.placement.kind),
                             ("runtime", workload.placement.runtime),
                             ("owner", workload.placement.owner),
                             ("scope", workload.scope)):
        if getattr(args, attribute, None) not in (None, value):
            return False
    return True


def _row(workload) -> dict:
    return {"id": workload.id, "title": workload.display_title,
            "host": workload.placement.host, "kind": workload.placement.kind,
            "runtime": workload.placement.runtime, "owner": workload.placement.owner,
            "provisioned_at": workload.placement.provisioned_at,
            "retired": workload.is_retired}


def cmd_list(args) -> int:
    """Declarations only. This command never asks a machine anything."""
    root, cfg = _bridge(args)
    rows = [_row(w) for w in model.load_all(root, cfg) if _keep(w, args)]
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    print(f"{len(rows)} declaration(s) in {cfg.dir}, read from the declarations alone: "
          f"nothing was probed, so this is intent and not state")
    for row in rows:
        print(f"  {row['id']:<28} {row['kind']:<9} {row['runtime']:<14} "
              f"{row['owner']:<7} {row['host']}{'  (retired)' if row['retired'] else ''}")
    return 0


def _preflight_header(workload, host) -> str:
    """A clean line has to say what it covered.

    Without this the first line of `provision` was a bare "clean", and it stayed
    that way while the run below it went on to report that it had NOT been
    verified. The reader takes the first line for the verdict, so the first line
    has to name its own subject.
    """
    return f"preflight for {workload.id} on {host.slug}, before anything was touched"


def cmd_show(args) -> int:
    root, cfg = _bridge(args)
    workload, host = _one(root, cfg, args.id)
    render = _module("render")
    print(json.dumps(_row(workload), indent=2, ensure_ascii=False))
    for line in model.rights_summary(workload.raw):
        print(line)
    print(f"platform {host.platform}, backend support: {hosts.supports(host, workload.placement.runtime)}")
    print(f"required guarantees: "
          f"{', '.join(sorted(g.value for g in model.required_guarantees(workload))) or 'none'}")
    findings = render.preflight(workload, host)
    print(report.render_table(report.Report(
        findings=findings, header=_preflight_header(workload, host))))
    if args.render:
        print(render.render(workload, host, _context(host, cfg, args.timeout)))
    return report.Report(findings=findings).exit_code


def cmd_validate(args) -> int:
    """Both gates, one report, one exit code.

    The second gate used to print its verdicts after the report had already
    been rendered and then throw them away. Three things followed from that one
    root: a declaration the schema REFUSED exited 0; an absent validator, which
    is the normal case on a fresh clone, exited 0 as well, so `--strict` was a
    switch with no effect; and the clean line stood two rows above the refusal,
    which is the line a human reads first.
    """
    root, cfg = _bridge(args)
    alle = model.load_all(root, cfg)
    chosen = [w for w in alle if not args.id or w.id in args.id]
    findings = []
    for workload in chosen:
        findings.extend(model.validate(workload.raw, source=Path(workload.source_path).name))
    # Over ALL declarations, never only the chosen ones: a collision is a
    # property of the set, and `--id one` must not be able to hide the fact
    # that two others resolve to the same unit.
    findings.extend(_label_collisions(alle))
    # Per declaration, so over the chosen ones: unlike a collision, a promise
    # without a floor is a property of one declaration and its own script.
    findings.extend(_hollow_failure_promises(chosen, root))
    # Same reason as the line above: it reads files, so it cannot live in the
    # pure gate. A reference nobody resolves is a run that reports to nobody
    # while its declaration still names somebody.
    findings.extend(_module("recipients").findings_for(chosen, root))
    if args.strict:
        findings.extend(_second_gate(root, cfg, chosen))
    rep = report.Report(findings=findings, header=_validate_header(len(chosen), args.strict))
    print(report.render_table(rep))
    return rep.exit_code


def _label_collisions(workloads) -> list:
    """Two declarations must not resolve to one unit name.

    Possible since `placement.label_prefix` exists: prefix `a.b` with id `c`
    and prefix `a` with id `b` and an appointment named `c` both produce
    `a.b.c`. Whichever loses is INVISIBLE rather than wrong, because the second
    one would silently claim the first one's unit, its ownership stamp and its
    trace, and reconcile would then report one of them as in sync against the
    other's evidence.

    The names are ASKED of the backend, never rebuilt here. A second derivation
    of a name is how a migrated run was once filed as foreign software.
    """
    from engine import backends as backends_mod
    from engine.backends import base as base_mod

    seen: dict = {}
    findings = []
    for workload in workloads:
        try:
            backend = backends_mod.get_backend(workload.placement.runtime)
        except Exception:
            continue  # an unknown runtime is refused elsewhere, with its own message
        for appointment in (base_mod.appointments_of(workload) or (None,)):
            try:
                name = backend.unit_name(workload, appointment)
            except Exception:
                continue
            if not name:
                continue  # manual/external/cron give a run no name on the machine
            first = seen.get(name)
            if first is not None and first != workload.id:
                findings.append(model.collision_finding(
                    source=Path(workload.source_path).name,
                    key_path="placement.label_prefix",
                    detail=(f"{workload.id!r} and {first!r} both resolve to the "
                            f"unit {name!r}"),
                    hint=("give one of them a different id or label_prefix; the "
                          "second would claim the first one's unit, stamp and trace")))
            seen.setdefault(name, workload.id)
    return findings


def _hollow_failure_promises(workloads, root) -> list:
    """A declaration may not promise a failure its script can never report.

    The chain is short and every link of it was measured on this instance. The
    wrapper exits non-zero, the guard writes `verdict=failed`, `reconcile
    --notify` turns that into `last_run_failed`, and a message reaches a human.
    A script whose last line is a bare `exit 0` breaks the FIRST link, and
    everything after it then works perfectly on an input that never arrives.
    Between 2026-08-24 and 2026-08-26 that produced 441 traces reading
    `verdict=ok` and not one non-zero exit, across three runs that could not
    have reported a failure at all. Two of them even carried a written reason
    for it, and the reason confused retrying with reporting.

    It lives here rather than in `model.validate` because it needs the
    repository root, which that gate has never had and should not get: it is
    asked by `provision` as well, and a gate that reads files needs a
    reachability and a deadline that a pure invariant check does not.

    FOUR SILENCES, each deliberate:

    - No `failure` in `notify_on`: nothing was promised, so nothing is hollow.
    - No path inside this repository: the declaration may name a program, or a
      script on another machine whose home is not this one. `relative_to`
      answers that, never a prefix comparison, and a path outside stays silent
      instead of being guessed at.
    - The file is not there: that is a different fact and deserves its own
      sentence, not this one. Saying it here would report an absence as a
      violation on every machine that keeps the file elsewhere.
    - The bytes do not decode: a binary has no last line, and reading one for
      a pattern yields noise.
    """
    findings = []
    for workload in workloads:
        response = getattr(workload, "response", None)
        if "failure" not in (getattr(response, "notify_on", None) or ()):
            continue
        script = _script_inside(workload, root)
        if script is None:
            continue
        try:
            text = script.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        reason = _no_floor(script, text)
        if reason is None:
            continue
        findings.append(model.script_finding(
            source=Path(workload.source_path).name,
            key_path="response.notify_on",
            detail=f"{workload.id!r} asks to be told about a failure, but {reason}",
            hint=("end the script with the return value it computed, for "
                  "example `exit \"$RC\"`; a job that should not be retried "
                  "still has to be able to say that it failed")))
    return findings


def _no_floor(script, text):
    """Which of the three shapes this script has, as a sentence, or None.

    THREE rules and not one widened one. They were measured against the four
    real repairs of one day and against a corpus of 85 shell scripts: each
    broken version is caught by exactly one of them, each repaired version by
    none, and the two added here have no hit in the corpus at all. A rule that
    guesses is worse here than a rule that is silent, because its answer
    arrives while somebody is deciding whether to trust a report.

    ONE sentence per script, never three. A script can satisfy two of these at
    once, and two lines for one defect read as two defects. The order is the
    order of certainty: the last line of a file is the plainest fact, an EXIT
    trap is the next, and the reachability of an exit is the one that
    approximates control flow by position in a file.
    """
    if model.ends_in_bare_exit_zero(text):
        return (f"{script.name!r} ends in a bare `exit 0`, so it returns zero "
                "however the run went")
    if model.an_exit_trap_overwrites_the_status(text):
        return (f"in {script.name!r} the handler of an EXIT trap ends in "
                "`exit 0`, which runs over the top of whatever the last line "
                "returned")
    if model.computes_a_status_it_can_never_return(text):
        return (f"{script.name!r} catches a return value and then has no exit "
                "left that could carry it")
    return None


def _script_inside(workload, root):
    """The first argument of the command that is a readable file in this repo.

    Never `command[0]`: every real declaration here reads
    `["/bin/bash", "<path>"]`, so the interpreter sits at index 0 and the
    script one further along. Never a position either, because a command may
    carry flags: what is looked for is a path that lies inside this repository
    and exists, and the first such argument is the script.
    """
    execution = getattr(workload, "execution", None)
    for argument in (getattr(execution, "command", None) or ()):
        try:
            candidate = Path(str(argument))
            resolved = candidate.resolve()
            resolved.relative_to(Path(root).resolve())
        except (ValueError, OSError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _validate_header(count: int, strict: bool) -> str:
    """What was ASKED for. What happened is what the findings under it say."""
    if not count:
        return ("0 declarations checked: nothing matched, so this says nothing "
                "about any machine")
    gate = ", then put to the schema gate" if strict else ""
    return f"{count} declaration(s) checked against the invariants{gate}"


def _second_gate(root, cfg, chosen) -> list:
    """The independent validator, as findings. Its absence is one of them.

    The absent answer stops the loop: there is one PATH and one schema file, so
    the second declaration cannot answer differently, and repeating it per
    declaration would bury the one sentence that matters under a column of
    copies. Both absences stop it -- the missing tool and the missing contract.
    """
    schema = Path(root) / cfg.dir / "_schema.yaml"
    findings = []
    for workload in chosen:
        verdict = model.validate_with_schema(Path(workload.source_path), schema,
                                             _module("exec").run_argv)
        finding = report.finding_for_schema_verdict(
            workload.id, verdict, source=Path(workload.source_path).name)
        findings.extend([finding] if finding is not None else [])
        if verdict.verdict in ("schema_validator_absent", "schema_missing"):
            break
    return findings


def cmd_declare(args) -> int:
    root, cfg = _bridge(args)
    target = root / cfg.dir / f"{args.id}.yaml"
    if target.exists() and not args.force:
        raise errors.DeclarationError(f"{target} exists already, pass --force to overwrite",
                                      source=str(target))
    text = model.scaffold(args.id, root=root, kind=args.kind, runtime=args.runtime, host=args.host,
                          title=args.title, purpose=args.purpose,
                          command=args.command or None, timeout_sec=args.timeout_sec)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}, now fill in every <placeholder> and run: workload validate {args.id}")
    return 0


def cmd_render(args) -> int:
    root, cfg = _bridge(args)
    workload, host = _one(root, cfg, args.id)
    render = _module("render")
    context = _module("backends.base").RenderContext(
        uid=args.uid, home=args.home, stamp_dir=cfg.stamp_dir,
        dispatcher_registry=cfg.dispatcher_registry, host_timezone=None) \
        if args.offline else _context(host, cfg, args.timeout)
    for artifact in render.render_all(workload, host, context):
        for rendered in artifact.files:
            print(f"# ---- {rendered.path}\n{rendered.content}")
    return 0


def cmd_provision(args) -> int:
    root, cfg = _bridge(args)
    workload, host = _one(root, cfg, args.id)
    findings = _module("render").preflight(workload, host)
    print(report.render_table(report.Report(findings=findings,
                                            header=_preflight_header(workload, host))))
    if any(f.severity is model.Severity.high for f in findings):
        return 3
    if not args.yes:
        print(f"nothing was touched. Rerun with --yes to provision {workload.id} "
              f"on {host.slug}.")
        return 0
    return _run_provision(args, cfg, root, workload, host)


def _run_provision(args, cfg, root, workload, host) -> int:
    """One declaration, every unit it needs, each observed and verified on its own.

    A run with several appointments is several units on the machine, and a
    partial result has to stay visible: provisioning the morning unit and
    failing on the midday one is not a success, and a single verified flag for
    the pair would report it as one.
    """
    provision, render = _module("provision"), _module("render")
    context = _context(host, cfg, args.timeout)
    artifacts = render.render_all(workload, host, context)
    verified = True
    for artifact in artifacts:
        if len(artifacts) > 1:
            print(f"\n── {artifact.unit_ref}")
        observation = provision.observe(workload, host, artifact, context,
                                        timeout_sec=args.timeout)
        plan = provision.plan(workload, artifact, observation,
                              force=args.force, accept_degraded=args.accept_degraded,
                              enable=args.enable, host=host)
        print(f"plan: {plan.action} ({plan.reason_code})")
        outcome = provision.apply(plan, workload, host, artifact, context,
                                  dry_run=args.dry_run,
                                  timeout_sec=args.timeout, root=root)
        # `Outcome.findings` are sentences, not findings, and handing them over
        # raw raised AttributeError out of `by_severity`: a traceback where the
        # contract promises a report and exit 1.
        print(report.render_table(report.Report(
            findings=report.notes(outcome.findings, workload_id=workload.id),
            header=f"{plan.action}: "
                   f"{'verified at the live object' if outcome.verified else 'NOT verified'}")))
        verified = verified and outcome.verified
    return 0 if verified else 1


def cmd_adopt(args) -> int:
    root, cfg = _bridge(args)
    workload, host = _one(root, cfg, args.id)
    provision, render = _module("provision"), _module("render")
    context = _context(host, cfg, args.timeout)
    verified = True
    for artifact in render.render_all(workload, host, context):
        outcome = provision.adopt(workload, host, artifact, context,
                                  timeout_sec=args.timeout, dry_run=not args.yes,
                                  root=root)
        print(_outcome_report(outcome, workload, host, "adopt"))
        verified = verified and outcome.verified
    return 0 if verified else 1


def _declared_probes(root, cfg, args) -> tuple:
    """Ids of the chosen declarations that named a health question themselves.

    Either half counts: `reconcile.probe` writes the question out, `check_ref`
    points at one in the check registry. A declaration with neither is not
    asking for a reading, so skipping it takes nothing away.
    """
    chosen = set(args.id or ())
    hosts = set(args.host or ())
    named = []
    for w in model.load_all(root, cfg):
        if chosen and w.id not in chosen:
            continue
        if hosts and getattr(w.placement, "host", None) not in hosts:
            continue
        rec = getattr(w, "reconcile", None)
        if rec is None:
            continue
        if (getattr(rec, "probe", None) or "").strip() or (getattr(rec, "check_ref", None) or "").strip():
            named.append(w.id)
    return tuple(named)


def cmd_reconcile(args) -> int:
    root, cfg = _bridge(args)
    reconcile = _module("reconcile")
    # BEFORE the first reading, because a refusal under a finished report reads
    # as a remark about it.
    #
    # `--notify` says: wake somebody when this is broken. `--no-probe` says: do
    # not ask whether it is. Together they are the same shape as a wrapper that
    # ends in a bare `exit 0`: every link after the first works faultlessly on
    # an input that never comes. Measured on a live machine on 2026-08-26, the
    # half-hourly refresher carried both, so the verdict a declaration paid for
    # with its own probe reached a page and nothing else.
    #
    # Only a contradiction where something declared a probe. Where nothing did,
    # `--no-probe` skips a reading that was never going to happen, and a rule
    # about nothing teaches the reader that the pair is forbidden until the day
    # a probe appears.
    if getattr(args, "notify", False) and getattr(args, "no_probe", False):
        named = _declared_probes(root, cfg, args)
        if named:
            raise errors.AlarmWithoutMeasurement(
                f"--notify asks to be told when a run is broken, --no-probe refuses to "
                f"ask whether it is, and {', '.join(named)} declared that question. "
                f"Drop --no-probe, or drop --notify and let the reading stay a look.")
    rep = reconcile.run(root, cfg, hosts=args.host or None, ids=args.id or None,
                        probe=not args.no_probe, timeout_sec=args.timeout)
    print(report.render_json(rep) if args.json
          else report.render_table(rep, verbose=args.verbose))
    if args.propose_inventory:
        print(_module("inventory").proposed_patch(rep.findings))
    if getattr(args, "notify", False):
        # Off by default, and the state file is not touched without the flag:
        # an investigating run from another machine would otherwise meet an
        # empty state and silently reset the dampening of an alarm that was
        # already confirmed. Looking and might-beep are two commands.
        from datetime import datetime, timezone
        notify = _module("notify")
        said = notify.dispatch(
            rep, model.load_all(root, cfg),
            state_path=root / ".bridge" / "notify-state.json",
            now=datetime.now(timezone.utc), cfg=cfg, sender=None)
        # with --json the report on stdout stays one JSON document; the summary goes to stderr
        print(f"notify: {said.sent} message(s) out, {said.suppressed} held back"
              + (f" ({said.note})" if said.note else ""), file=sys.stderr if args.json else sys.stdout)
    # The exit code stays reconcile's own. Whether anybody was told is not a
    # statement about whether anything is broken.
    return rep.exit_code


def cmd_view(args) -> int:
    """Render the declared runs as one page. Writes a file, touches no machine
    beyond the same read `reconcile` does.

    The default destination is inside `.bridge/`, which the repository ignores,
    and that is deliberate rather than tidy: a rendered page bakes host names,
    unit labels and paths, so it is instance data that must never travel with a
    commit.
    """
    # `_bridge` is called for the root and for the side effect its own
    # docstring names: it rebuilds the backends from the live configuration.
    # The configuration itself is read again inside `_page`, which is where
    # the page is rendered and therefore where its furniture is resolved.
    root, _ = _bridge(args)
    if getattr(args, "json", False):
        # The same reconcile and the same data stages as the page, as one JSON
        # document on stdout for a reader that draws its own. Nothing is
        # written to disk, so the caller decides where it lands; the honest
        # sentence goes to stderr, where it cannot corrupt the document.
        rep, document = _page(args, as_data=True)
        json.dump(document, sys.stdout, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write("\n")
        print(rep.header, file=sys.stderr)
        return rep.exit_code
    rep, page = _page(args)
    out = Path(args.out) if args.out else root / ".bridge" / "workloads.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}")
    print(rep.header)
    return rep.exit_code


def _page(args, *, as_data: bool = False):
    """Reconcile, then render. One place, so `view` and `publish` cannot drift
    into showing different pages for the same repository.

    `as_data` returns the page's content as a document instead of markup,
    out of the same reconcile and the same workloads, so `view --json` cannot
    drift from the page either."""
    root, cfg = _bridge(args)
    reconcile, view = _module("reconcile"), _module("view")
    rep = reconcile.run(root, cfg, hosts=args.host or None, ids=args.id or None,
                        probe=not args.no_probe, timeout_sec=args.timeout)
    workloads = [w for w in model.load_all(root, cfg)
                 if not args.id or w.id in set(args.id)]
    if as_data:
        return rep, view.data(rep, workloads, generated_at=args.now,
                              hosts=tuple(args.host or ()),
                              machine_units=view_machine_units(cfg))
    # Which machines were asked travels with the page: a declaration placed on
    # one that was not asked is silent for a knowable reason, and the page has
    # to say which rather than report an unexplained gap.
    return rep, view.render(rep, workloads, generated_at=args.now,
                            stale_after_min=getattr(args, "stale_after_min", None),
                            hosts=tuple(args.host or ()),
                            poll_sec=getattr(args, "poll_sec", None),
                            links=view_links(cfg),
                            panels=view_panels(cfg),
                            overview_label=view_overview_label(cfg),
                            machine_units=view_machine_units(cfg),
                            group_by=getattr(args, "group_by", "band"))


#: Where the neighbour links live in the bridge configuration.
#:
#: Not a field on `config.Config`: everything there is an engine-wide knob that
#: several commands reach for, and this is one surface's furniture that only
#: `view` and `publish` ever ask about. It is read from the file `config`
#: already resolved, named by `cfg.source`, so there is one path and one
#: spelling of the key rather than a second opinion about where the
#: configuration lives.
VIEW_LINKS_KEY = f"{config.CONFIG_KEY}.view.links"
VIEW_PANELS_KEY = VIEW_LINKS_KEY.replace("links", "panels")


def view_links(cfg) -> tuple:
    """Neighbour pages named in `workloads.view.links`, as (label, href) pairs.

    None at all is the normal case and never an error: a Bridge with a single
    page has no neighbours, and a bar invented for it would point at pages that
    do not exist. This skill is core, so the targets can only come from
    configuration; a host name or a path in this file would be one instance's
    data shipped to every other.

    A MALFORMED entry is a different thing and is refused by name. A link
    quietly dropped is a link nobody misses until the page it pointed at is the
    one somebody needed.
    """
    return _view_entries(cfg, "links", VIEW_LINKS_KEY)


def _view_entries(cfg, name: str, key: str) -> tuple:
    """One reader for both `view.links` and `view.panels`.

    They have the same shape and the same refusal, so they have one
    implementation: two copies of a validator drift the day one of them learns
    something, and the one that did not learn it is the one nobody tests.
    """
    import yaml

    path = Path(getattr(cfg, "source", "") or "")
    if not path.name or not path.exists():
        return ()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = (loaded.get(config.CONFIG_KEY) or {}) if isinstance(loaded, dict) else {}
    section = (block.get("view") or {}) if isinstance(block, dict) else {}
    raw = (section.get(name) or ()) if isinstance(section, dict) else ()
    if not isinstance(raw, (list, tuple)):
        raise errors.ConfigError(
            f"{path}: {key}: expected a list of entries, each with a "
            "label and an href", source=str(path))
    out = []
    for index, entry in enumerate(raw):
        label = entry.get("label") if isinstance(entry, dict) else None
        href = entry.get("href") if isinstance(entry, dict) else None
        if not label or not href:
            raise errors.ConfigError(
                f"{path}: {key}[{index}] needs both a label and an "
                "href. Half an entry cannot be drawn, and drawing nothing "
                "instead would hide the mistake behind a bar that merely looks "
                "short.", source=str(path))
        out.append((str(label), str(href)))
    return tuple(out)


def view_machine_units(cfg) -> tuple:
    """Which of the machine's undeclared units to LIST rather than count.

    Label prefixes, out of configuration and never out of this file: which
    units on a machine belong to its owner and which to the operating system
    is an instance's answer, and a prefix list baked in here would be one
    bridge's inventory shipped to every other.
    """
    import yaml

    path = Path(getattr(cfg, "source", "") or "")
    if not path.name or not path.exists():
        return ()
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = (loaded.get(config.CONFIG_KEY) or {}) if isinstance(loaded, dict) else {}
    section = (block.get("view") or {}) if isinstance(block, dict) else {}
    raw = (section.get("machine_units") or ()) if isinstance(section, dict) else ()
    if not isinstance(raw, (list, tuple)):
        raise errors.ConfigError(
            f"{path}: {config.CONFIG_KEY}.view.machine_units: expected a list "
            "of label prefixes", source=str(path))
    return tuple(str(p).strip() for p in raw if str(p).strip())


def view_overview_label(cfg) -> str:
    """What to call the first tab, the one the shell supplies itself.

    Every other tab is named by the entry that asked for it, so without this
    the bar would carry exactly one word out of this file, in this file's
    language, next to labels in the reader's. Absent or empty means the
    default, which is the honest answer for a bridge that never set one.
    """
    import yaml

    path = Path(getattr(cfg, "source", "") or "")
    if not path.name or not path.exists():
        return ""
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    block = (loaded.get(config.CONFIG_KEY) or {}) if isinstance(loaded, dict) else {}
    section = (block.get("view") or {}) if isinstance(block, dict) else {}
    label = section.get("overview_label") if isinstance(section, dict) else None
    return str(label).strip() if label else ""


def view_panels(cfg) -> tuple:
    """Neighbour pages FRAMED rather than linked, same shape as `view_links`.

    Why a second key and not a flag on the first: a link and a frame make
    different promises. A link says a page exists somewhere; a frame puts it in
    front of the reader, costs a request, and takes vertical room. Which of the
    two a neighbour deserves is a judgement about that neighbour, so it is
    written down per entry instead of inferred.

    What a frame does NOT do is adopt anything. Nothing is parsed out of the
    framed page and no figure of it is repeated as a number of ours; the reader
    sees the neighbour's own rendering under the neighbour's own moment. That is
    the line this skill holds, and adjacency was never the part that broke it.
    """
    return _view_entries(cfg, "panels", VIEW_PANELS_KEY)


def cmd_publish(args) -> int:
    """Render the page and put it where a browser reaches it.

    Dry by default. The exit code is about the publishing, never about the
    findings: a page reporting a broken workload published perfectly well, and
    collapsing the two would make a red run indistinguishable from a red page.
    """
    root, cfg = _bridge(args)
    publish = _module("publish")
    rep, page = _page(args)

    # Read and refused, if it has to be, before a machine is contacted: a
    # missing or untransportable attachment discovered halfway through leaves a
    # directory somebody then has to reason about.
    attachments = publish.load_attachments(args.attach or ())
    host = hosts.resolve_host(args.to, root)
    # The home comes off the machine, the same way the uid for a launchd domain
    # does. Every path here travels inside a quoted shell word, so a `~` in the
    # destination is a directory name and not a home directory, and the account
    # running this command is not evidence about the account on that one.
    context = _context(host, cfg, args.timeout)
    outcome = publish.publish(page, host, dest=args.dest, page_name=args.page_name,
                              attachments=attachments,
                              url=args.url, home=context.home, timeout_sec=args.timeout,
                              dry_run=not args.yes)
    print(rep.header)
    print(_publish_report(outcome, url=args.url, wrote=args.yes))
    # `complete` and not `ok`: the page is the subject of the publish and an
    # attachment that failed does not invalidate it, but a run asked for three
    # files that delivered two did not do what it was asked either.
    return 0 if (outcome.complete and (args.yes or not outcome.delivered)) else 1


def _publish_report(outcome, *, url, wrote: bool) -> str:
    """The two facts, and in a dry run the proofs that are armed.

    The last part is not decoration: `delivered` and `reachable` both read
    "not asked" after a dry run, because it reaches neither. A forgotten
    `--url` and an armed one therefore print identically, and a missing
    reachability check would be discovered by the run that was meant to take it.
    """
    lines = [outcome.evidence]
    if outcome.steps and not wrote:
        lines.extend(f"  would {step.purpose}" for step in outcome.steps)
        if url:
            lines.append(f"  would fetch {url} and compare it with those bytes")
    lines.append(f"delivered: {outcome.delivered}")
    lines.append("reachable: " + ("not asked" if outcome.reachable is None
                                  else str(outcome.reachable)))
    # Each attachment on a line of its own. A count would let a run in which
    # the stylesheet failed and the data file arrived read the same as its
    # mirror image, and the two need different repairs.
    for item in outcome.attachments:
        lines.append(f"attached {item.name}: "
                     + ("delivered" if item.delivered
                        else f"NOT delivered, {item.evidence}"))
    if outcome.leftovers:
        named = ", ".join(outcome.leftovers[:8])
        more = (f" and {len(outcome.leftovers) - 8} more"
                if len(outcome.leftovers) > 8 else "")
        lines.append(
            f"left behind: {len(outcome.leftovers)} file(s) in that directory "
            f"that this publish does not deliver ({named}{more}). Nothing here "
            "removes a file, so they are older than this page and the server "
            "goes on handing them out; delete them by hand if they are stale.")
    return "\n".join(lines)


def cmd_retire(args) -> int:
    root, cfg = _bridge(args)
    workload, host = _one(root, cfg, args.id)
    provision, render = _module("provision"), _module("render")
    context = _context(host, cfg, args.timeout)
    # Every unit, because a run stopped by half is still running. Retiring the
    # morning appointment and leaving the midday one loaded would read as done
    # and keep sending.
    # The declaration is written ONCE, after the loop, and only when every
    # unit went down. Writing it per unit was the defect: the first
    # appointment wrote the `retired:` block and the second was refused
    # against it, so five of six units stayed loaded while the file already
    # claimed retired.
    verified = True
    stopped = False
    for artifact in render.render_all(workload, host, context):
        # Both halves of the bolt, read from the argv a human typed. `--dry-run`
        # was declared here and then thrown away one line down:
        # `dry_run=not args.yes` turned `retire --yes --dry-run` into a real
        # stop. `confirmed` is the other half and is never derived from the
        # first; `root` is what puts the run under the workload lock and writes
        # the declaration back in the right repository.
        outcome = provision.retire(workload, host, artifact, context, args.reason,
                                   superseded_by=args.superseded_by,
                                   keep_artifact=args.keep_artifact,
                                   dry_run=args.dry_run, confirmed=args.yes,
                                   timeout_sec=args.timeout, root=root,
                                   write_declaration=False)
        print(_outcome_report(outcome, workload, host, "retire"))
        verified = verified and outcome.verified
        stopped = True

    # Only now, and only when nothing is left standing. A run stopped by half
    # is still running, and a declaration that claims otherwise is worse than
    # one that says nothing: the next reader stops looking.
    if stopped and verified and not args.dry_run:
        provision.finish_retirement(workload, args.reason, root=root,
                                    superseded_by=args.superseded_by)
    return 0 if verified else 1


def _outcome_report(outcome, workload, host, verb: str) -> str:
    """What a run that CHANGED something answers, in the one report shape.

    `retire` and `adopt` printed two fields of the outcome and dropped its
    sentences, and those sentences are the whole content of the answer: "dry
    run, nothing was stopped" is what makes a preview a preview. Without them
    `retire --dry-run` said `verified=False` and left a human to guess between
    refused, failed and previewed -- the same defect `provision` carried, one
    command further along.
    """
    return report.render_table(report.Report(
        findings=report.notes(outcome.findings, workload_id=workload.id),
        header=f"{verb} {workload.id} on {host.slug}: "
               f"{'verified at the live object' if outcome.verified else 'NOT verified'}"))


COMMANDS = {
    "list": cmd_list,
    "show": cmd_show,
    "validate": cmd_validate,
    "declare": cmd_declare,
    "render": cmd_render,
    "provision": cmd_provision,
    "adopt": cmd_adopt,
    "reconcile": cmd_reconcile,
    "view": cmd_view,
    "publish": cmd_publish,
    "retire": cmd_retire,
}


def _parser() -> argparse.ArgumentParser:
    # `__doc__` is None under `python -OO`, which strips docstrings out of the
    # module. Nothing is measured here and nothing was read off a disk: this
    # is this file's own header, so the fallback is a constant rather than
    # the reported absence a missing MEASUREMENT would have to be.
    parser = argparse.ArgumentParser(
        prog="workload", description=(__doc__ or "workload").splitlines()[0])
    parser.add_argument("--root", help="repository root, discovered when omitted")
    parser.add_argument("--timeout", type=int, default=60, help="deadline per outbound call")
    # NOT dest="command": `declare` takes a `--command` of its own, and argparse
    # writes both into the same namespace attribute. The subcommand was therefore
    # overwritten by the argv list, and `workload declare <id> --command ...`
    # ended in `TypeError: cannot use 'list' as a dict key` out of the dispatch
    # table below -- while the same command WITHOUT --command left the attribute
    # at None and printed the top level help, as though no subcommand had been
    # typed. The one documented way to write a new declaration was unreachable in
    # both shapes.
    sub = parser.add_subparsers(dest="subcommand")
    _add_read_commands(sub)
    _add_write_commands(sub)
    return parser


def _add_read_commands(sub) -> None:
    listing = sub.add_parser("list", help="declared workloads, without touching a machine")
    for name in ("host", "kind", "runtime", "owner", "scope"):
        listing.add_argument(f"--{name}")
    listing.add_argument("--retired", action="store_true")
    listing.add_argument("--json", action="store_true")
    show = sub.add_parser("show", help="one declaration, resolved")
    show.add_argument("id")
    show.add_argument("--render", action="store_true")
    show.add_argument("--json", action="store_true")
    validate = sub.add_parser("validate", help="the invariant gate")
    validate.add_argument("id", nargs="*")
    validate.add_argument("--all", action="store_true")
    validate.add_argument("--strict", action="store_true")
    _add_reconcile_command(sub)


def _add_reconcile_command(sub) -> None:
    parser = sub.add_parser("reconcile", help="compare declaration, machine and inventory")
    parser.add_argument("--notify", action="store_true",
                        help="also send what the declarations asked to be told about, "
                             "through the one notification path. Off by default: a "
                             "command somebody types to LOOK must not page anyone, and "
                             "without this flag the dampening state is not touched either")
    parser.add_argument("id", nargs="*")
    parser.add_argument("--host", action="append")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-probe", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--propose-inventory", action="store_true")
    parser.add_argument("--json", action="store_true")

    page = sub.add_parser("view", help="render the declared runs as one HTML page")
    page.add_argument("id", nargs="*")
    page.add_argument("--host", action="append")
    page.add_argument("--no-probe", action="store_true")
    page.add_argument("--out", help="destination; default .bridge/workloads.html, "
                                    "which the repository ignores because a "
                                    "rendered page bakes host names and paths")
    page.add_argument("--poll-sec", dest="poll_sec", type=int,
                     help="seconds between the page asking whether a newer copy exists. "
                          "Without it the page still ages honestly, it just never "
                          "refreshes itself. A reader with the tab open sees the "
                          "new numbers instead of a frozen one")
    page.add_argument("--group-by", dest="group_by", default="band",
                     choices=["band", "system"],
                     help="which question the table is sectioned by. `band` (the "
                          "default) groups by WHEN a run fires and draws exactly "
                          "the page this drew before the second axis existed; "
                          "`system` groups by WHAT it is a part of, out of the "
                          "declarations' own `system:` field. A run that names no "
                          "system lands under a heading that says so rather than "
                          "being folded in with the ones that stand alone on purpose")
    page.add_argument("--json", action="store_true",
                      help="print the page's content as one JSON document on "
                           "stdout instead of writing the HTML. Same reconcile, "
                           "same data stages; --out is ignored")
    page.add_argument("--now", required=True,
                      help="the timestamp printed on the page. Required and not "
                           "defaulted: the renderer reads no clock, so the same "
                           "inputs render the same bytes and a diff means something")


    out = sub.add_parser("publish", help="render the page and put it where a browser reaches it")
    out.add_argument("id", nargs="*")
    out.add_argument("--host", action="append",
                     help="limit which hosts are reconciled, the same filter view takes")
    out.add_argument("--no-probe", action="store_true")
    out.add_argument("--to", required=True, help="machine to deliver to, a slug under infra/remotes/")
    out.add_argument("--dest", required=True,
                     help="directory on that machine. It must be empty, absent, or "
                          "already carry this skill's marker: a served directory "
                          "usually belongs to a puller or another view, and writing "
                          "into it loses one of the two without a word")
    out.add_argument("--page-name", dest="page_name", default="index.html")
    out.add_argument("--attach", action="append", metavar="PATH",
                     help="one more file to deliver into the same directory, "
                          "beside the page. Repeatable. Each one is written "
                          "byte for byte, read back and compared exactly like "
                          "the page, reported on a line of its own, and named "
                          "in the directory's marker, so a later publish can "
                          "still tell this skill's output from a stranger's")
    out.add_argument("--url", help="the URL that directory is served at. Given one, the "
                                   "page is fetched back and compared, which is the only "
                                   "way to tell a delivered file from a served one")
    out.add_argument("--now", required=True, help="the timestamp printed on the page")
    out.add_argument("--stale-after-min", dest="stale_after_min", type=int,
                     help="minutes after which the page tells its reader it is out of "
                          "date. Set it to twice the refresh interval: one missed "
                          "refresh is a hiccup, two is an outage")
    out.add_argument("--poll-sec", dest="poll_sec", type=int,
                     help="seconds between the page asking whether a newer copy exists. "
                          "Without it the page still ages honestly, it just never "
                          "refreshes itself. A reader with the tab open sees the "
                          "new numbers instead of a frozen one")
    out.add_argument("--group-by", dest="group_by", default="band",
                     choices=["band", "system"],
                     help="which question the table is sectioned by. `band` (the "
                          "default) groups by WHEN a run fires and draws exactly "
                          "the page this drew before the second axis existed; "
                          "`system` groups by WHAT it is a part of, out of the "
                          "declarations' own `system:` field. A run that names no "
                          "system lands under a heading that says so rather than "
                          "being folded in with the ones that stand alone on purpose")
    out.add_argument("--yes", action="store_true",
                     help="actually write. Without it nothing is written and the steps "
                          "are printed")


def _add_write_commands(sub) -> None:
    declare = sub.add_parser("declare", help="scaffold a new declaration")
    declare.add_argument("id")
    for name in ("kind", "runtime", "host", "title", "purpose"):
        declare.add_argument(f"--{name}")
    declare.add_argument("--timeout-sec", type=int, dest="timeout_sec")
    declare.add_argument("--command", nargs="*")
    declare.add_argument("--force", action="store_true")
    render = sub.add_parser("render", help="the exact bytes, written nowhere")
    render.add_argument("id")
    render.add_argument("--offline", action="store_true")
    render.add_argument("--uid", default="")
    render.add_argument("--home", default="")
    _add_machine_commands(sub)


def _add_machine_commands(sub) -> None:
    provision = sub.add_parser("provision", help="create or replace, then verify")
    provision.add_argument("id")
    for flag in ("--dry-run", "--yes", "--force", "--accept-degraded", "--enable"):
        provision.add_argument(flag, action="store_true")
    adopt = sub.add_parser("adopt", help="take ownership of a unit made by hand")
    adopt.add_argument("id")
    adopt.add_argument("--yes", action="store_true")
    retire = sub.add_parser("retire", help="disable with a reason, never a rename")
    retire.add_argument("id")
    retire.add_argument("--reason", required=True)
    retire.add_argument("--superseded-by", dest="superseded_by")
    retire.add_argument("--keep-artifact", action="store_true")
    retire.add_argument("--yes", action="store_true")
    retire.add_argument("--dry-run", action="store_true")


def main(argv=None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = COMMANDS.get(args.subcommand)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except errors.WorkloadError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return exit_code_for(exc)


if __name__ == "__main__":
    raise SystemExit(main())
