"""The only module that changes a machine.

The shape is observe -> plan -> apply -> verify, and the middle step is pure on
purpose: the whole decision table can be driven row by row without a box in
sight, which is the only way the interesting refusals are provable at all.

Three things this module never does. It never derives state from the
declaration: ``present``, ``running`` and every digest come from the live
object. It never reports success without a verify that passed at that live
object. And it never elevates: a step that needs root is printed for a human,
because escalating silently on a box carrying live services is not on the table.
"""

from __future__ import annotations

import dataclasses
import datetime
import posixpath
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from engine import config as config_mod
from engine import errors
from engine import exec as exec_mod
from engine import lock as lock_mod
from engine import model
from engine import probe as probe_mod
from engine import stamp as stamp_mod
from engine.backends import get_backend
from engine.backends.base import RenderedFile, digest_of

#: The suffix a replaced file is kept under, inside the same owned directory, so
#: a failed verify can put the previous unit back.
PREVIOUS_SUFFIX = ".prev"


@dataclass(frozen=True)
class Observation:
    """What the machine says. Never what the declaration says."""

    reachable: bool = True
    present: bool = False
    #: None where the live source does not answer the question. `False` would
    #: be a claim nobody made.
    enabled: bool = True
    running: bool = False
    persistently_disabled: bool = False
    file_digests: dict = field(default_factory=dict)
    stamp: object = None
    marker_id: str = None
    marker_digest: str = None
    #: The rendered form of what is actually on disk, when it could be read.
    live_files: tuple = ()
    error: str = ""


@dataclass(frozen=True)
class Plan:
    """What would happen, decided without touching anything."""

    action: str          # create | replace | noop | refuse | manual
    reason_code: str
    steps: tuple = ()
    warnings: tuple = ()


@dataclass(frozen=True)
class Outcome:
    """What did happen, and whether the live object confirmed it."""

    action: str
    verified: bool = False
    evidence: str = ""
    findings: tuple = ()


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _backend_of(artifact):
    return get_backend(artifact.runtime)


def _steps_of(artifact, method: str, host, *, lenient: bool, **kwargs) -> tuple:
    """Ask the backend for a step plan. The backend owns every unit vocabulary."""
    fn = getattr(_backend_of(artifact), method, None)
    if fn is None:
        return ()
    if not lenient:
        return tuple(fn(artifact, host, **kwargs))
    try:                       # a preview may be asked for before a host is known
        return tuple(fn(artifact, host, **kwargs))
    except Exception:          # noqa: BLE001 - a preview never fails the caller
        return ()


def _manual_steps(artifact) -> tuple:
    """What a human has to do when the skill may plan but never install."""
    steps = []
    for f in artifact.files:
        steps.append(model.Step(
            argv=("/bin/sh", "-c",
                  f"# by hand, with elevation: place {f.path} with mode {f.mode:o}"),
            purpose=f"place {f.path} by hand",
            requires_elevation=True,
        ))
    steps.append(model.Step(
        argv=("/bin/sh", "-c", f"# by hand, with elevation: activate {artifact.unit_ref}"),
        purpose=f"activate {artifact.unit_ref} by hand",
        requires_elevation=True,
    ))
    return tuple(steps)


def _needs_elevation(artifact, steps) -> bool:
    declared = getattr(_backend_of(artifact), "requires_elevation", None)
    if declared is not None:
        return bool(declared)
    return any(getattr(s, "requires_elevation", False) for s in steps)


def _files_match(artifact, obs: Observation) -> bool:
    """Is every rendered file byte identical to what lies on the machine."""
    for f in artifact.files:
        if obs.file_digests.get(str(f.path)) != digest_of([f]):
            return False
    return True


def _config_for(root):
    """The configuration of the repository being operated on, when there is one."""
    if root is None:
        return None
    try:
        return config_mod.load_config(Path(root))
    except Exception:              # noqa: BLE001 - a missing config is not fatal here
        return None


def _probe_plan(w, artifact, host, root):
    """(spec, step): what answers for this workload, and how it is asked.

    Resolution goes through ``probe.resolve_probe``, which is the same order
    reconcile uses: the declared probe, else a check reference, else the
    backend's own. Two modules answering a different question about the same
    workload is how a repository ends up disagreeing with its own machine.
    """
    try:
        spec = probe_mod.resolve_probe(w, host, artifact, Path(root) if root else Path("."),
                                       _config_for(root))
    except Exception as exc:       # noqa: BLE001 - an unresolvable probe is unknown
        return probe_mod.ProbeSpec(command="", source="unresolved",
                                   reason=f"the probe could not be resolved: {exc}"), None

    if spec.source == "backend-default" or not (spec.command or "").strip():
        backend = _backend_of(artifact) if artifact is not None else None
        step = _read_only(backend.default_probe(artifact, host)) if backend else None
        return spec, step

    # A declared or referenced probe is a user authored shell string, so it runs
    # as the one explicit shell in this skill: bounded, own session, killed as a
    # group.
    return spec, model.Step(
        argv=("/bin/sh", "-c", spec.command),
        purpose=f"ask the live source about {w.id}",
        expect_rc=(),
    )


def _read_only(step):
    """The same step, but judged by us instead of raised on."""
    return dataclasses.replace(step, expect_rc=())


def _declaration_path(root, w) -> Path:
    """Where the declaration lives in the repository being operated on."""
    if root is None:
        return Path(w.source_path)
    cfg = config_mod.load_config(Path(root))
    path = Path(root) / cfg.dir / f"{w.id}.yaml"
    if not path.exists():
        raise errors.DeclarationError(
            source=str(path), workload=w.id,
            message=f"no declaration for {w.id} under {cfg.dir}, so nothing may be written back")
    return path


def _state_key_for(w, artifact) -> str:
    """The state key of the unit this artifact IS, ASKED not rebuilt.

    The artifact carries it, set once at render time from the declaration and
    the appointment. Taking it apart from the label here again would be a
    second derivation of the same name, and a second derivation drifting from
    the first is the exact defect this round came out of. The fallback is the
    declaration id, which is what every artifact rendered before this field
    existed means.
    """
    return str(getattr(artifact, "state_key", "") or w.id)


# ── observe ──────────────────────────────────────────────────────────────────

def observe(w, host, artifact, ctx, *, timeout_sec, runner=None) -> Observation:
    """Read the live object, its files and its ownership record. Read only.

    Everything about the unit comes back through the backend's own
    ``inspect_steps`` / ``parse_inspection`` seam. No service-manager output
    format is parsed in this module: a fifth backend would otherwise need an
    edit here, and the one place that reads a format would drift from the place
    that writes it.

    The persistent off-list is a SECOND read, because the per-unit call does not
    carry it. A backend that cannot answer leaves it ``None``, and ``None`` is
    not ``False``: not knowing whether something was switched off deliberately
    must never read as permission to switch it on.
    """
    runner = runner or exec_mod.step_runner
    backend = _backend_of(artifact)

    try:
        outs = [runner(_read_only(step), host, timeout_sec=timeout_sec)
                for step in backend.inspect_steps(artifact, host)]
    except errors.StepTimeout as expired:
        return Observation(reachable=False, error=str(expired))

    unit = backend.parse_inspection(tuple(outs), artifact.unit_ref) if outs else None
    present = unit is not None

    try:
        disabled = _persistently_disabled(backend, artifact, host,
                                          runner=runner, timeout_sec=timeout_sec)
    except errors.StepTimeout as expired:
        return Observation(reachable=False, error=str(expired))

    digests = {}
    live_files = []
    for f in artifact.files:
        content = _read_file(runner, host, str(f.path), timeout_sec=timeout_sec)
        if content is None:
            digests[str(f.path)] = None
            continue
        live = RenderedFile(path=f.path, mode=f.mode, content=content)
        live_files.append(live)
        digests[str(f.path)] = digest_of([live])

    return Observation(
        reachable=True,
        present=present,
        enabled=(getattr(unit, "enabled", None) if present else False),
        running=bool(present and getattr(unit, "running", None)),
        persistently_disabled=disabled,
        file_digests=digests,
        stamp=stamp_mod.read_stamp(host, ctx.stamp_dir,
                                   _state_key_for(w, artifact),
                                   timeout_sec=timeout_sec, runner=runner),
        marker_id=getattr(unit, "marker_id", None),
        marker_digest=getattr(unit, "marker_digest", None),
        live_files=tuple(live_files),
    )


def _persistently_disabled(backend, artifact, host, *, runner, timeout_sec):
    """True, False, or None when the off-list could not be read at all."""
    steps = tuple(getattr(backend, "disabled_list_steps", lambda a, h: ())(artifact, host))
    if not steps:
        return None
    outs = []
    for step in steps:
        if getattr(step, "requires_elevation", False):
            # No sudo, ever. An unread off-list stays unknown.
            return None
        try:
            outs.append(runner(_read_only(step), host, timeout_sec=timeout_sec))
        except errors.StepFailed:
            return None
    return backend.parse_disabled(tuple(outs), artifact.unit_ref)


def _read_file(runner, host, path: str, *, timeout_sec):
    step = model.Step(
        argv=("/bin/sh", "-c", f"cat {exec_mod.sh_quote(path)} 2>/dev/null"),
        purpose=f"read {path} as it is on the machine",
        expect_rc=(),
    )
    try:
        done = runner(step, host, timeout_sec=timeout_sec)
    except errors.StepTimeout:
        return None
    return done.stdout if done.rc == 0 else None


# ── plan (pure) ──────────────────────────────────────────────────────────────

def plan(w, artifact, obs: Observation, *, force=False, accept_degraded=False,
         enable=False, host=None) -> Plan:
    """Decide, without touching anything, what provisioning this would mean."""
    warnings = []

    if not w.is_bridge_owned:
        return Plan("refuse", "not-owned", (),
                    (f"{w.id} is owned by {w.placement.owner}, so it is documented, never touched",))
    if w.is_retired:
        return Plan("refuse", "retired-declaration", (),
                    (f"{w.id} is retired, and a start would undo the reason it was stopped",))
    if artifact is None:
        return Plan("refuse", "not-provisionable", (),
                    (f"{w.id} has no artifact, so there is nothing to place",))

    # Rule 1, on the LAYER THAT ACTS. `validate` is the invariant gate, and until
    # now only the `validate` command ever called it: provision rendered and
    # placed whatever load_declaration accepted, and load_declaration checks
    # types and enums, never cross field rules. A declaration missing
    # execution.timeout_sec therefore became a run with NO DEADLINE on a
    # machine, and nothing anywhere said so. It cannot even be caught downstream:
    # `required_guarantees` derives the deadline demand FROM timeout_sec, so a
    # missing deadline demands nothing, the wrapper supplies no guard script and
    # the unmet set is empty. With the default isolation the process-group demand
    # happened to catch it; with `isolation: process` it fell straight through.
    #
    # Before the reachability check on purpose: an invalid declaration is invalid
    # whatever any machine answers, and this keeps the refusal provable without
    # a box.
    invalid = model.validate(w.raw or {}, source=str(w.source_path or w.id))
    if invalid:
        return Plan("refuse", "invalid-declaration", (),
                    tuple(f"{w.id} does not pass the invariant gate: {f.detail}"
                          for f in invalid))

    if not obs.reachable:
        return Plan("refuse", "host-unreachable", (),
                    ("the host did not answer, and not knowing what is there is not "
                     "the same as nothing being there",))
    if obs.persistently_disabled is True and not enable:
        return Plan("refuse", "disabled-refused", (),
                    (f"{artifact.unit_ref} sits in the persistent disabled list; "
                     "re-enabling it is a deliberate act",))
    if obs.marker_id and obs.marker_id != w.id:
        return Plan("refuse", "collision-foreign-workload", (),
                    (f"{artifact.unit_ref} carries the marker of {obs.marker_id}",))

    anything_there = obs.present or any(v is not None for v in obs.file_digests.values())
    files_match = _files_match(artifact, obs)

    if obs.stamp is None:
        if obs.marker_id == w.id:
            # The marker carries the DECLARATION digest, never the artifact
            # digest: it sits inside the rendered file, and a value cannot
            # contain its own hash. Comparing it against artifact.digest made
            # this branch unreachable, so a unit that was provably ours but had
            # lost its stamp was booted out and rewritten instead of adopted.
            if obs.marker_digest == model.declaration_digest(w) and files_match:
                return Plan("refuse", "marker-without-stamp", (),
                            (f"{artifact.unit_ref} is ours by its marker but carries no "
                             "ownership record; adopt it instead of provisioning over it",))
            action = "replace"
        elif anything_there:
            return Plan("refuse", "collision-unstamped", (),
                        (f"{artifact.unit_ref} exists with neither an ownership record nor a "
                         "marker, so it belongs to somebody else",))
        else:
            action = "create"
    elif obs.stamp.artifact_digest != artifact.digest:
        action = "replace"
    elif files_match:
        return Plan("noop", "already-in-sync", (), tuple(warnings))
    elif force:
        action = "replace"
        warnings.append("forced over a file that was edited since it was stamped")
    else:
        return Plan("refuse", "foreign-edit", (),
                    (f"a file of {w.id} changed since it was stamped; --force overwrites it",))

    unmet = (frozenset(model.required_guarantees(w))
             - frozenset(artifact.guarantees_native)
             - frozenset(artifact.guarantees_wrapped))
    if unmet:
        told = ", ".join(sorted(g.value for g in unmet))
        warnings.append(f"{artifact.runtime} cannot carry {told} for {w.id}")

    steps = _steps_of(artifact, "install_steps" if action == "create" else "replace_steps",
                      host, lenient=True)
    if _needs_elevation(artifact, steps):
        # Before the guarantee refusal, deliberately: an elevated run is one the
        # skill will not touch at all, so what is left is a plan for a human, and
        # a shortfall belongs in that printout rather than in a refusal of
        # something nobody was going to do here.
        return Plan("manual", "elevation-required", steps or _manual_steps(artifact),
                    tuple(warnings) + ("no sudo, ever: run the printed steps by hand, then "
                                       "provision again to verify",))
    if unmet and not accept_degraded:
        return Plan("refuse", "degraded-backend", (), tuple(warnings))

    reason = "nothing-provisioned" if action == "create" else "artifact-drift"
    return Plan(action, reason, steps, tuple(warnings))


# ── apply ────────────────────────────────────────────────────────────────────

def apply(plan_obj: Plan, w, host, artifact, ctx, *, dry_run, timeout_sec,
          runner=None, root=None) -> Outcome:
    """Carry out a plan under a lock, then prove the result at the live object."""
    runner = runner or exec_mod.step_runner

    if plan_obj.action == "refuse":
        raise errors.Refused(code=plan_obj.reason_code, workload=w.id,
                             reason="; ".join(plan_obj.warnings))
    if dry_run:
        return Outcome(plan_obj.action, False, "",
                       ("dry run, nothing was touched",) + tuple(plan_obj.warnings))
    if plan_obj.action == "manual":
        return Outcome("manual", False, "",
                       ("elevation required, so the steps were printed instead of run",)
                       + tuple(plan_obj.warnings))

    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()
    with guard:
        findings = list(plan_obj.warnings)

        if plan_obj.action != "noop":
            for unit_path in _guarded_paths(artifact):
                symlink_guard(unit_path, host, timeout_sec=timeout_sec, runner=runner)

            if plan_obj.action == "replace":
                _keep_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)

            steps = tuple(plan_obj.steps) or _steps_of(
                artifact, "install_steps" if plan_obj.action == "create" else "replace_steps",
                host, lenient=False)
            try:
                for step in steps:
                    runner(step, host, timeout_sec=timeout_sec)
            except (errors.StepFailed, errors.StepTimeout) as failed:
                # A replace that stops halfway has usually already unloaded the
                # running unit. Stopping there leaves the service down until a
                # human notices, which is what happened on a real machine when a
                # bootstrap failed right after the bootout. Bring the previous
                # unit back first, then report the failure.
                if plan_obj.action != "replace":
                    raise
                notes = _roll_back(artifact, host, runner=runner, timeout_sec=timeout_sec)
                told = "; ".join([str(failed),
                                  "the previous files were put back and loaded again"]
                                 + notes)
                raise type(failed)(told, **getattr(failed, "fields", {})) from failed

            stamp_mod.write_stamp(
                _stamp_for(w, host, artifact, adopted=False, root=root), host, ctx,
                timeout_sec=timeout_sec, runner=runner)

        verified, evidence, trouble = _verified(w, host, artifact, ctx,
                                                timeout_sec=timeout_sec, runner=runner,
                                                root=root)
        findings.extend(trouble)

        if plan_obj.action == "replace":
            if verified:
                # The copy existed for exactly this decision. Keeping it past the
                # decision is litter, and litter that is a full copy of a unit
                # file is worse than litter.
                _drop_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)
            else:
                findings.extend(_roll_back(artifact, host, runner=runner,
                                           timeout_sec=timeout_sec))
                findings.append("the verify did not pass, so the previous files were "
                                "restored and loaded again")

        return Outcome(plan_obj.action, verified, evidence, tuple(findings))


def _guarded_paths(artifact) -> tuple:
    """One file per distinct directory: the guard asks about the directory."""
    seen = {}
    for f in artifact.files:
        directory = posixpath.dirname(str(f.path))
        seen.setdefault(directory, str(f.path))
    return tuple(seen.values())


def _keep_previous(artifact, host, *, runner, timeout_sec) -> None:
    for f in artifact.files:
        path = exec_mod.sh_quote(str(f.path))
        runner(model.Step(
            argv=("/bin/sh", "-c",
                  f"[ -f {path} ] && cp {path} {path}{PREVIOUS_SUFFIX} || true"),
            purpose=f"keep the previous {f.path} beside the new one",
        ), host, timeout_sec=timeout_sec)


def _drop_previous(artifact, host, *, runner, timeout_sec) -> None:
    """Remove the rollback copies. Called once they can no longer be needed.

    A `.prev` has exactly one job, and it ends the moment the new unit verifies
    or the workload is retired. Nothing removed it, so a replace left one behind
    every time and a RETIRED workload left a complete copy of its own unit file
    on the machine: unstamped, unlisted, claimed by nobody, and carrying
    whatever the old argv and environment carried. Found on a real machine after
    three probes were retired, and on a second one beside it.

    `rm -f`, so a run where no copy was ever made is not an error.
    """
    for f in artifact.files:
        path = exec_mod.sh_quote(str(f.path) + PREVIOUS_SUFFIX)
        runner(model.Step(
            argv=("/bin/sh", "-c", f"rm -f {path}"),
            purpose=f"drop the rollback copy of {f.path}",
        ), host, timeout_sec=timeout_sec)


def _restore_previous(artifact, host, *, runner, timeout_sec) -> None:
    for f in artifact.files:
        path = exec_mod.sh_quote(str(f.path))
        runner(model.Step(
            argv=("/bin/sh", "-c",
                  f"[ -f {path}{PREVIOUS_SUFFIX} ] && mv {path}{PREVIOUS_SUFFIX} {path} || true"),
            purpose=f"restore the previous {f.path}",
        ), host, timeout_sec=timeout_sec)


def _reload_steps(artifact, host) -> tuple:
    """The backend's replace plan without its writes: unload, wait, load.

    Used after `_restore_previous`, when the files on the machine are already
    the old ones again and only the loaded unit still has to follow them.
    """
    paths = {str(f.path) for f in artifact.files}

    def writes(step) -> bool:
        purpose = step.purpose or ""
        return any(purpose == f"write {p}" or purpose.startswith(f"write {p}, part ")
                   for p in paths)

    steps = _steps_of(artifact, "replace_steps", host, lenient=True)
    return tuple(s for s in steps if not writes(s))


def _roll_back(artifact, host, *, runner, timeout_sec) -> list:
    """Put the previous files back AND load them. Returns what went wrong, if anything.

    Restoring the file alone is half a rollback: the service manager still
    holds the new unit until something unloads it and loads the old bytes.
    """
    _restore_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)
    for step in _reload_steps(artifact, host):
        try:
            runner(step, host, timeout_sec=timeout_sec)
        except (errors.StepFailed, errors.StepTimeout) as again:
            return [f"loading the previous unit failed too, needs a hand: {again}"]
    return []


def _declaration_ref(w, root) -> str:
    """How the stamp names the declaration: repository relative, never absolute.

    An absolute path carries the operator's account name onto the machine, and
    the stamp is meant to carry an id and two digests, nothing about a person.
    """
    source = Path(w.source_path)
    if root is not None:
        try:
            return str(source.relative_to(Path(root)))
        except ValueError:
            pass
    return source.name


def _stamp_for(w, host, artifact, *, adopted: bool, artifact_digest=None,
               root=None) -> stamp_mod.Stamp:
    return stamp_mod.Stamp(
        stamp_version=model.STAMP_VERSION,
        workload_id=w.id,
        state_key=_state_key_for(w, artifact),
        host=host.slug,
        declaration=_declaration_ref(w, root),
        declaration_digest=model.declaration_digest(w),
        artifact_digest=artifact_digest or artifact.digest,
        runtime=artifact.runtime,
        unit_ref=artifact.unit_ref,
        files=tuple(str(f.path) for f in artifact.files),
        provisioned_at=_now(),
        adopted=adopted,
        retired=None,
        interpreter=w.placement.interpreter,
    )


def ask_live_source(w, host, artifact, *, timeout_sec, runner, root=None):
    """Run the workload's probe and JUDGE it. Returns (verdict, evidence, why).

    The judgement is ``probe.evaluate``, so what counts as healthy is the
    declaration's own ``expect`` and not a return code. A probe can exit 0 while
    saying, in as many words, that the thing is not running: reading the code
    instead of the answer is how a stopped run got reported as verified.

    A probe nobody can evaluate (an unresolved placeholder, an expect written as
    prose) is ``unknown``. So is an expired deadline. Neither is ever a pass.
    """
    spec, step = _probe_plan(w, artifact, host, root)
    ok, reason = probe_mod.is_evaluatable(spec)
    if not ok or step is None:
        return probe_mod.Verdict.unknown, "", (reason or "no probe could be resolved")
    try:
        done = runner(step, host, timeout_sec=timeout_sec)
    except errors.StepTimeout as expired:
        return probe_mod.Verdict.unknown, "", f"the probe did not answer in time: {expired}"
    except errors.StepFailed as failed:
        return probe_mod.Verdict.unknown, "", f"the probe call failed: {failed}"
    body = (done.stdout or "").strip()
    evidence = body.splitlines()[0] if body else ""
    return probe_mod.evaluate(spec, done), evidence, ""


def _verified(w, host, artifact, ctx, *, timeout_sec, runner, root=None):
    """Ask the live object. Anything but a passing probe is unverified."""
    verdict, evidence, why = ask_live_source(w, host, artifact, timeout_sec=timeout_sec,
                                             runner=runner, root=root)
    if verdict is probe_mod.Verdict.pass_:
        return True, evidence, []
    if verdict is probe_mod.Verdict.unknown:
        return False, evidence, [f"the run could not be verified: {why or 'unknown'}"]
    return False, evidence, ["the live source did not confirm the run, so this is unverified"]


def verify(w, host, artifact, ctx, *, timeout_sec, runner=None, root=None):
    """Ask the declared probe, else the backend's own. Never an assumption."""
    runner = runner or exec_mod.step_runner
    spec, step = _probe_plan(w, artifact, host, root)
    if step is None:
        raise errors.Refused(code="probe-unresolved", workload=w.id,
                             message=f"no probe could be resolved for {w.id}: {spec.reason}")
    return runner(step, host, timeout_sec=timeout_sec)


# ── adopt ────────────────────────────────────────────────────────────────────

def adopt(w, host, artifact, ctx, *, timeout_sec, dry_run, runner=None, root=None) -> Outcome:
    """Take ownership of something that already exists, without touching it.

    Nothing is rewritten and nothing is restarted: only the ownership record is
    written, carrying the digest of what is ACTUALLY there. Afterwards reconcile
    compares against that, so a hand made unit becomes owned without a second of
    downtime.
    """
    runner = runner or exec_mod.step_runner
    obs = observe(w, host, artifact, ctx, timeout_sec=timeout_sec, runner=runner)
    if not obs.reachable or not obs.present:
        # The way out belongs IN the message. The most common reason nothing
        # is found here is not a missing unit but a unit under a different
        # name: `adopt` takes over what was made by hand, and a hand made unit
        # almost never carries this instance's prefix. A reader who does not
        # know that reads "nothing found" as "does not exist" and puts a second
        # unit next to the first.
        raise errors.NothingToAdopt(
            workload=w.id, unit=artifact.unit_ref,
            message=(f"nothing live matches {artifact.unit_ref}. If the unit "
                     f"exists under a different name, declare its prefix in "
                     f"placement.label_prefix; the declaration id stays the "
                     f"tail of the name"))
    if dry_run:
        return Outcome("adopted", False, "", ("dry run, nothing was recorded",))

    # Under the same lock as apply: adopt writes the ownership record, and two
    # sessions writing one record for the same id is the collision the lock is
    # there for.
    #
    # The stamp carries the digest of what is THERE, even when that is fewer
    # files than the render (a hand made unit has no guard script). Falling back
    # to the rendered digest claimed the bridge's own version was on the
    # machine, and the next provision then refused with foreign-edit over a file
    # nobody had touched. An empty set hashes to a value no render has.
    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()
    with guard:
        live_digest = digest_of(list(obs.live_files))
        stamp_mod.write_stamp(
            _stamp_for(w, host, artifact, adopted=True, artifact_digest=live_digest, root=root),
            host, ctx, timeout_sec=timeout_sec, runner=runner)
    return Outcome("adopted", True, live_digest,
                   (f"{artifact.unit_ref} was adopted as it stands, nothing was restarted",))


# ── retire ───────────────────────────────────────────────────────────────────

def may_stop(*, dry_run, confirmed) -> tuple:
    """(may it run, why not). The bolt in front of the only destructive command.

    Two signals, and NEITHER is the other's negation. That is the whole point.
    A caller that owns one boolean and derives the other from it has exactly one
    place to get it wrong, and the command it gets wrong is the one that stops a
    running service. `cli.cmd_retire` did precisely that: it declared --dry-run,
    then computed `dry_run=not args.yes` and never read `args.dry_run`, so
    `retire --yes --dry-run` booted the unit out, disabled it, deleted the guard
    script and wrote `retired:` into the declaration. Exit code 0, no hint.

    So the decision is taken HERE and it is fail closed on both axes: an explicit
    dry run never stops anything, and neither does a run nobody confirmed.
    ``confirmed=None`` means the caller said nothing, and saying nothing is not
    saying yes. The same reasoning the persistent off-list gets in `observe`.
    """
    if dry_run:
        return False, "dry run, nothing was stopped"
    if confirmed is not True:
        return False, ("this retirement carries no confirmation, and an "
                       "unconfirmed stop is not a stop")
    return True, ""


def retire(w, host, artifact, ctx, reason, *, superseded_by=None, keep_artifact=False,
           dry_run=False, confirmed=None, timeout_sec, runner=None, root=None,
           write_declaration=True) -> Outcome:
    """Stop it for good: bootout, then a PERSISTENT disable carrying the reason.

    The order is asserted, and it matters. Only the persistent disable survives a
    reboot, the reason is what a renamed file would have lost, and the
    declaration is written last so the repository can never claim retired while
    the machine still runs it.

    ``write_declaration`` exists because this function is called once per UNIT
    while the declaration belongs to the whole run. With more than one
    appointment the first call wrote the `retired:` block and the second was
    refused by `AlreadyRetired` against the file the first had just written, so
    one unit stopped and the rest stayed loaded, and the failure arrived AFTER
    the repository already said retired. A caller iterating units passes
    ``False`` here and writes the block itself once every unit is proven
    stopped, via :func:`finish_retirement`. The default stays ``True`` so a
    single-unit caller keeps the guarantee named above without knowing about
    any of this.

    ``confirmed`` is the affirmative half of the bolt in :func:`may_stop` and has
    no default worth the name: without an explicit ``True`` this call is refused
    rather than run.
    """
    if len((reason or "").strip()) < 8:
        raise errors.ReasonTooShort(reason=reason, workload=w.id)
    runner = runner or exec_mod.step_runner

    may, why = may_stop(dry_run=dry_run, confirmed=confirmed)
    if not may:
        if dry_run:
            return Outcome("retire", False, "", (why,))
        # Raised, not returned. A caller that prints two fields of the Outcome
        # and nothing else would swallow this, and being silently ignored is the
        # failure mode this bolt exists for.
        raise errors.Refused(
            code="unconfirmed-stop", workload=w.id, unit=artifact.unit_ref,
            message=f"nothing was stopped: {why}. Confirm the retirement of "
                    f"{w.id} explicitly, or ask for a dry run")

    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()
    with guard:
        for step in _steps_of(artifact, "disable_steps", host, lenient=False, reason=reason):
            runner(step, host, timeout_sec=timeout_sec)

        # The stop gate, and it is the declaration's own probe judged by its own
        # expect. A probe that still PASSES means the thing still answers the way
        # a healthy one does, so it did not stop. An UNKNOWN answer is not proof
        # of a stop either, and both stop here: the declaration is written last
        # precisely so the repository can never claim retired while the machine
        # still serves.
        verdict, evidence, why = ask_live_source(w, host, artifact, timeout_sec=timeout_sec,
                                                 runner=runner, root=root)
        if verdict is probe_mod.Verdict.pass_:
            raise errors.Refused(
                code="still-running", workload=w.id, unit=artifact.unit_ref,
                message=f"{artifact.unit_ref} still answers as healthy after the disable "
                        f"({evidence or 'no output'}), so nothing was written back")
        if verdict is not probe_mod.Verdict.fail:
            raise errors.Refused(
                code="stop-unproven", workload=w.id, unit=artifact.unit_ref,
                message=f"the stop of {artifact.unit_ref} could not be proven "
                        f"({why or 'unknown'}), and an unproven stop is not a stop")

        at = _now()
        if write_declaration:
            model.write_retired(_declaration_path(root, w), at, reason, superseded_by)

        existing = stamp_mod.read_stamp(host, ctx.stamp_dir,
                                        _state_key_for(w, artifact),
                                        timeout_sec=timeout_sec, runner=runner)
        if existing is not None:
            stamp_mod.mark_retired(existing, host, ctx, at=at, reason=reason,
                                   superseded_by=superseded_by,
                                   timeout_sec=timeout_sec, runner=runner)

        findings = [f"{artifact.unit_ref} was disabled persistently, reason recorded"]
        if not keep_artifact:
            for step in _steps_of(artifact, "uninstall_steps", host, lenient=False):
                runner(step, host, timeout_sec=timeout_sec)
            # The backends remove what the artifact declares. The rollback copies
            # are made HERE and are unknown to them, so they are swept here too.
            _drop_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)
            findings.append("the artifact files and their rollback copies were "
                            "removed, never renamed")
    return Outcome("retire", True, at, tuple(findings))


def finish_retirement(w, reason, *, root, superseded_by=None, at=None) -> str:
    """Write the `retired:` block once, after every unit is proven stopped.

    The counterpart to ``retire(..., write_declaration=False)``. It is a
    separate call rather than a flag on the last unit because "last" is an
    order, not a proof: if the first unit refuses to stop and the last one
    obeys, a flag on the last would write `retired:` over a run that is still
    serving. The caller decides when EVERY unit is down, and only then asks for
    this.

    `AlreadyRetired` still fires from here, which is the point of keeping the
    guard: retiring a run a human already retired stays an error.
    """
    at = at or _now()
    model.write_retired(_declaration_path(root, w), at, reason, superseded_by)
    return at


# ── the symlink guard ────────────────────────────────────────────────────────

def symlink_guard(path: str, host, *, timeout_sec, runner=None) -> None:
    """Refuse a unit path that is not its own physical path.

    A service manager refuses to bootstrap a symlinked unit path, and a launch
    directory that is a link into a synced folder is a real configuration.
    Resolved with ``cd`` plus ``pwd -P`` because BSD ``readlink -f`` is not
    universal.
    """
    runner = runner or exec_mod.step_runner
    directory = posixpath.dirname(str(path)) or str(path)
    step = model.Step(
        argv=("/bin/sh", "-c", f"cd {exec_mod.sh_quote(directory)} 2>/dev/null && pwd -P"),
        purpose=f"resolve {directory} physically",
        expect_rc=(),
    )
    done = runner(step, host, timeout_sec=timeout_sec)
    resolved = (done.stdout or "").strip()
    if resolved and resolved != directory:
        raise errors.SymlinkedUnitPath(path=str(path), resolved=resolved)
