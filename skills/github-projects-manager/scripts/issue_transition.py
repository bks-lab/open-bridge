#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""One GitHub issue to its board's review or done state: the write path behind the cockpit's issue card.

The board comes from workflow/projects/<slug>.yaml (`project.tracker: github`, `project.org`, `project.number`): the
issue's live project items are matched against those files, never guessed. The states come from the file's
`governance:` block, `review_states[0]` for review and `done_states[0]` for done, and the field from
`board.status_field` (default Status). The rules of references/governance.md hold:

- moving into review posts the review comment first (K3), from `governance.review_comment_template` where the board
  has one (`{{new_state}}`, `{{date}}`, `{{reason}}`; a text the template does not place goes below it), else the
  default of governance.md;
- review needs a reason, it becomes the review comment;
- done passes through review first on every board that has review states and the item is not in review yet (K1
  holds at every level, whatever `rules` names), one comment covering both, named after the board that passes
  through; done from review comments only when there is a text or a board names `comment_on_status_change`; an
  issue declined on a board (a done state other than the first) closes as not planned;
- done is a person's call (K1, `done_only_by_user`): this script decides nothing, it runs on a person's click;
- the issue closes only after every board was read back at its target, and the close is read back too. A run
  that stops after a first write answers `partial`.

  issue_transition.py --root <bridge> plan   <owner/repo#n>      what the boards say now, writes nothing
  issue_transition.py --root <bridge> review <owner/repo#n> [--text T | --text-file F]
  issue_transition.py --root <bridge> done   <owner/repo#n> [--text T | --text-file F]

Prints one JSON object. Exit 0 when it holds (or there was nothing to do), 1 refused or failed (`error`, `detail`),
2 usage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REF_RE = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([0-9]+)$")
GH_TIMEOUT = 60
DEFAULT_REVIEW = "## Review\n\n**Status**: {state}\n{reason}\n*Set to {state} on {date} from the cockpit.*\n"
DEFAULT_DONE = "## Done\n\n{reason}\n*Set to {state} on {date} from the cockpit.*\n"


def default_run(argv: list[str], timeout: float = GH_TIMEOUT, input: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 1, "", str(exc))


def _strings(value) -> list[str]:
    return [str(v) for v in value if isinstance(v, (str, int))] if isinstance(value, list) else []


def load_boards(root: Path) -> list[dict]:
    """The GitHub boards of workflow/projects/ (discovery: every <slug>.yaml, `_` files reserved)"""
    out = []
    for path in sorted((Path(root) / "workflow" / "projects").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        project: dict = data.get("project") if isinstance(data.get("project"), dict) else {}
        owner = project.get("org") or project.get("owner")
        if project.get("tracker") != "github" or not owner or not isinstance(project.get("number"), int):
            continue
        gov: dict = data.get("governance") if isinstance(data.get("governance"), dict) else {}
        board: dict = data.get("board") if isinstance(data.get("board"), dict) else {}
        ident: dict = data.get("identity") if isinstance(data.get("identity"), dict) else {}
        out.append({"slug": path.stem, "title": ident.get("display_name") or path.stem, "owner": str(owner),
                    "number": project["number"], "status_field": str(board.get("status_field") or "Status"),
                    "review_states": _strings(gov.get("review_states")), "done_states": _strings(gov.get("done_states")),
                    "rules": _strings(gov.get("rules")),
                    "template": gov.get("review_comment_template") if isinstance(gov.get("review_comment_template"), str) else None})
    return out


def parse_ref(ref: str) -> tuple[str, str, int]:
    m = REF_RE.match(str(ref or ""))
    if not m:
        raise ValueError(f"not owner/repo#number: {ref!r}")
    return m.group(1), m.group(2), int(m.group(3))


def live(ref: str, run=None) -> dict:
    """The issue as GitHub has it now: its type, state, url and, per project item, the owner, number, title and the
    value of every single-select field. Raises RuntimeError when GitHub does not answer"""
    run = run or default_run
    owner, name, number = parse_ref(ref)
    values = ("fieldValues(first: 30) { nodes { ... on ProjectV2ItemFieldSingleSelectValue { name "
              "field { ... on ProjectV2SingleSelectField { name } } } } }")
    query = (f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ "
             f"issueOrPullRequest(number: {number}) {{ __typename "
             f"... on Issue {{ state url title updatedAt projectItems(first: 20) {{ nodes {{ "
             f"project {{ number title owner {{ ... on Organization {{ login }} ... on User {{ login }} }} }} {values} }} }} }} "
             f"... on PullRequest {{ state url title }} }} }} }}")
    done = run(["gh", "api", "graphql", "-f", f"query={query}"], timeout=GH_TIMEOUT)
    try:
        node = json.loads(done.stdout or "{}")["data"]["repository"]["issueOrPullRequest"]
    except (ValueError, KeyError, TypeError):
        node = None
    if done.returncode != 0 or not isinstance(node, dict):
        raise RuntimeError((done.stderr or done.stdout or "GitHub did not answer").strip()[:300])
    items = []
    for n in ((node.get("projectItems") or {}).get("nodes") or []):
        project = (n or {}).get("project") or {}
        fields = {}
        for v in ((n.get("fieldValues") or {}).get("nodes") or []):
            if isinstance(v, dict) and v.get("name") is not None and (v.get("field") or {}).get("name"):
                fields[v["field"]["name"]] = v["name"]
        items.append({"owner": ((project.get("owner") or {}).get("login") or ""), "number": project.get("number"),
                      "title": project.get("title") or "", "fields": fields})
    return {"type": "pr" if node.get("__typename") == "PullRequest" else "issue", "state": node.get("state"),
            "url": node.get("url"), "title": node.get("title"), "updated": node.get("updatedAt"), "items": items}


def _match(boards: list[dict], issue: dict) -> tuple[list[tuple[dict, str | None]], list[dict]]:
    by = {(b["owner"].lower(), b["number"]): b for b in boards}
    hit, miss = [], []
    for item in issue["items"]:
        b = by.get((item["owner"].lower(), item["number"]))
        if b:
            hit.append((b, item["fields"].get(b["status_field"])))
        else:
            miss.append({"owner": item["owner"], "number": item["number"], "title": item["title"]})
    return hit, miss


def plan(root: Path, ref: str, run=None) -> dict:
    """What the issue's boards say now and which states a click would set; writes nothing"""
    issue = live(ref, run)
    hit, miss = _match(load_boards(root), issue)
    boards = [{"slug": b["slug"], "title": b["title"], "owner": b["owner"], "number": b["number"], "status": status,
               "review_state": (b["review_states"] or [None])[0], "done_state": (b["done_states"] or [None])[0],
               "in_review": status in b["review_states"], "in_done": status in b["done_states"], "rules": b["rules"]}
              for b, status in hit]
    return {"ok": True, "ref": ref, "type": issue["type"], "state": issue["state"], "url": issue["url"],
            "title": issue["title"], "updated": issue["updated"], "boards": boards, "unmatched": miss}


def comment_body(board: dict, kind: str, state: str, text: str, today: str) -> str:
    """The comment of a transition: the board's review template where it has one, else the default of governance.md"""
    text = text.strip()
    if board.get("template"):
        body = board["template"].replace("{{new_state}}", state).replace("{{date}}", today)
        if "{{reason}}" in body:
            return body.replace("{{reason}}", text)
        return body.rstrip("\n") + (f"\n\n{text}\n" if text else "\n")
    reason = f"**Reason**: {text}\n" if kind == "review" and text else f"{text}\n" if text else ""
    return (DEFAULT_REVIEW if kind == "review" else DEFAULT_DONE).format(state=state, reason=reason, date=today)


def transition(root: Path, ref: str, to: str, text: str = "", run=None, today: str | None = None) -> dict:
    """Moves the issue on every matching board to `to` (review or done), closes it on done; see the module doc"""
    run = run or default_run
    owner, name, number = parse_ref(ref)
    today = today or dt.date.today().isoformat()
    steps: list[dict] = []

    def out(ok: bool, **extra) -> dict:
        return {"ok": ok, "ref": ref, "to": to, "steps": steps, **extra}

    try:
        issue = live(ref, run)
    except RuntimeError as exc:
        return out(False, error="github", detail=str(exc))
    if issue["type"] != "issue":
        return out(False, error="not_an_issue", detail="a pull request is merged, not closed here")
    hit, _ = _match(load_boards(root), issue)
    if not hit:
        return out(False, error="no_board", detail="the issue is on no board of workflow/projects/")
    if to == "review" and any(not b["review_states"] for b, _ in hit):
        return out(False, error="no_review_state", detail="a board of this issue has no governance.review_states")
    if to == "done" and any(not b["done_states"] for b, _ in hit):
        return out(False, error="no_done_state", detail="a board of this issue has no governance.done_states")
    if to == "done" and any("done_requires_review" in b["rules"] and not b["review_states"] for b, _ in hit):
        return out(False, error="no_review_state", detail="a board wants review before done and names no review state")
    if to == "review" and any(s in b["done_states"] for b, s in hit):
        return out(False, error="already_done", detail="a board has the issue in a done state")
    if to == "review" and not text.strip():
        return out(False, error="missing_reason", detail="the review comment needs a reason (governance K3)")

    # the moves per board: [(board, from, [states to set in order])]. K1 at every level: a board with review states
    # passes through review before done, whatever its rules list names
    moves = []
    for b, status in hit:
        if to == "review":
            seq = [] if status in b["review_states"] else [b["review_states"][0]]
        else:
            seq = [] if status in b["done_states"] else (
                [b["review_states"][0]] if b["review_states"] and status not in b["review_states"] else []) + [b["done_states"][0]]
        moves.append((b, status, seq))
    # the board whose review step the comment names; none where a board holds its review state already (a run that
    # stopped part way posted the comment then)
    passing = next((b for b, _, seq in moves if b["review_states"] and seq and seq[0] == b["review_states"][0]), None)
    if passing and any(st in b["review_states"] for b, st, _ in moves):
        passing = None

    def write(argv: list[str], what: dict, body: str | None = None) -> str | None:
        done = run(argv, timeout=GH_TIMEOUT, input=body)
        steps.append({**what, "ok": done.returncode == 0})
        return None if done.returncode == 0 else (done.stderr or done.stdout or "failed").strip()[:300]

    def failed(detail: str) -> dict:
        return out(False, error="write_failed" if not any(x["ok"] for x in steps) else "partial", detail=detail)

    url = issue["url"]
    # one comment: the review comment where something passes through review, else on done a text or a board's rule
    if passing:
        body = comment_body(passing, "review", passing["review_states"][0], text, today)
        if err := write(["gh", "issue", "comment", str(number), "--repo", f"{owner}/{name}", "--body-file", "-"],
                        {"do": "comment", "kind": "review"}, body):
            return failed(err)
    elif to == "done" and any(seq for _, _, seq in moves) and (text.strip() or any("comment_on_status_change" in b["rules"] for b, _, _ in moves)):
        b0 = next(b for b, _, seq in moves if seq)
        if err := write(["gh", "issue", "comment", str(number), "--repo", f"{owner}/{name}", "--body-file", "-"],
                        {"do": "comment", "kind": "done"}, comment_body(b0, "done", b0["done_states"][0], text, today)):
            return failed(err)
    for b, _, seq in moves:
        for state in seq:
            if err := write(["gh", "project", "item-edit", str(b["number"]), "--owner", b["owner"], "--url", url,
                             "--field", b["status_field"], "--value", state], {"do": "status", "board": b["slug"], "value": state}):
                return failed(err)

    def readback() -> tuple[list[dict], bool] | str:
        try:
            after = live(ref, run)
        except RuntimeError as exc:
            return str(exc)
        now = dict(((b["slug"], st) for b, st in _match(load_boards(root), after)[0]))
        return ([{"slug": b["slug"], "from": status, "to": seq[-1] if seq else status, "now": now.get(b["slug"])}
                 for b, status, seq in moves], after["state"] == "CLOSED")

    # every board read back at its target before the issue closes: a board that did not follow keeps it open
    got = readback()
    if isinstance(got, str):
        return out(False, error="readback", detail=got)
    boards, closed = got
    if not all(x["now"] == x["to"] for x in boards):
        return out(False, error="readback", detail="GitHub does not show what was written", boards=boards, closed=closed)
    if to == "done" and issue["state"] == "OPEN":
        # declined on a board (a done state other than the first): closed as not planned, never as completed
        declined = any(x["now"] in b["done_states"][1:] for (b, _, _), x in zip(moves, boards))
        if err := write(["gh", "issue", "close", str(number), "--repo", f"{owner}/{name}", "--reason",
                         "not planned" if declined else "completed"], {"do": "close"}):
            return failed(err)
        got = readback()
        if isinstance(got, str):
            return out(False, error="readback", detail=got)
        boards, closed = got
        if not closed:
            return out(False, error="readback", detail="GitHub does not show the issue closed", boards=boards, closed=closed)
    return out(True, boards=boards, closed=closed)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Move a GitHub issue to its board's review or done state.")
    p.add_argument("--root", default=".", help="the Bridge root (holds workflow/projects/)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="what the boards say now, writes nothing").add_argument("ref")
    for cmd in ("review", "done"):
        s = sub.add_parser(cmd, help=f"set the {cmd} state (a person's click)")
        s.add_argument("ref")
        s.add_argument("--text", default="", help="the reason, inline")
        s.add_argument("--text-file", help="the reason, as a file (UTF-8)")
    args = p.parse_args(argv)
    root = Path(args.root)
    try:
        if args.cmd == "plan":
            result = plan(root, args.ref, run=default_run)
        else:
            text = Path(args.text_file).read_text(encoding="utf-8") if args.text_file else args.text
            result = transition(root, args.ref, args.cmd, text, run=default_run)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": "invalid_argument", "detail": str(exc)}, ensure_ascii=False))
        return 2
    except (RuntimeError, OSError) as exc:
        print(json.dumps({"ok": False, "error": "github", "detail": str(exc)[:300]}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
