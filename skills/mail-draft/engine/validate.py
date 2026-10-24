"""Check every mail footer and profile, and every reference between them.

The schema says what a file may hold. The references are what breaks a draft
at the moment somebody needs it: a profile naming a footer that was renamed, a
footer naming a persona that does not exist, a mandant pointing at a profile
nobody wrote, two profiles both claiming to be the default. All of those are
checked here, so they fail in CI instead of in front of a recipient.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import footer as footer_mod
from . import profiles, recipients
from .config import ConfigError, load_yaml

SCHEMAS = {
    "footer": ("identity/mail-footers/_schema.yaml", "identity/mail-footers"),
    "profile": ("workflow/mail-profiles/_schema.yaml", "workflow/mail-profiles"),
}


def _plain(value):
    """YAML turns `2026-08-14` into a date; the schema speaks JSON, where it is a string."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def schema_errors(root: Path, kind: str, data: dict) -> list[str]:
    schema_path, _ = SCHEMAS[kind]
    data = _plain(data)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        # Without jsonschema the structural minimum still holds.
        missing = [k for k in ("schema_version", "scope", "id") if k not in data]
        return [f"missing {', '.join(missing)}"] if missing else []
    # The instance's own copy first (an overlay may tighten it), else the one
    # that shipped with this skill.
    path = root / schema_path
    if not path.is_file():
        path = Path(__file__).resolve().parents[3] / schema_path
    schema = load_yaml(path)
    validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(top)"
        out.append(f"{where}: {err.message}")
    return out


def run(root: Path) -> list[str]:
    problems: list[str] = []
    footers = footer_mod.available(root)
    profs = profiles.available(root)

    for fid, data in footers.items():
        rel = f"identity/mail-footers/{fid}.yaml"
        problems += [f"{rel}: {e}" for e in schema_errors(root, "footer", data)]
        if data.get("id") and data["id"] != fid:
            problems.append(f"{rel}: id '{data['id']}' does not match the filename")
        if data.get("scope") == "core":
            problems.append(f"{rel}: a footer carries contact data and is never scope core")
        try:
            footer_mod.load(root, fid, files=footers)
            for lang in (data.get("variants") or {}):
                footer_mod.load(root, fid, language=lang, files=footers)
        except ConfigError as err:
            problems.append(f"{rel}: {err}")

    for pid, data in profs.items():
        rel = f"workflow/mail-profiles/{pid}.yaml"
        problems += [f"{rel}: {e}" for e in schema_errors(root, "profile", data)]
        if data.get("id") and data["id"] != pid:
            problems.append(f"{rel}: id '{data['id']}' does not match the filename")
        try:
            merged = profiles.resolve(profs, pid)
        except ConfigError as err:
            problems.append(f"{rel}: {err}")
            continue
        fid = merged.get("footer")
        if fid and fid not in footers:
            problems.append(f"{rel}: footer '{fid}' is not in identity/mail-footers/")
        persona = merged.get("persona_ref")
        if persona and not (root / "identity" / "personas" / f"{persona}.yaml").is_file():
            problems.append(f"{rel}: persona_ref '{persona}' is not in identity/personas/")

    claims: dict[tuple[str, str], list[str]] = {}
    for pid, data in profs.items():
        for kind, values in ((data.get("applies_to") or {}).items()):
            for v in values or []:
                claims.setdefault((kind, str(v)), []).append(pid)
    for (kind, value), pids in sorted(claims.items()):
        if len(pids) > 1:
            problems.append(f"workflow/mail-profiles: {kind} '{value}' is claimed by {', '.join(pids)}; "
                            f"only the first by name would ever be used")

    defaults = [pid for pid, data in profs.items() if data.get("default")]
    if len(defaults) > 1:
        problems.append(f"workflow/mail-profiles: more than one default profile ({', '.join(defaults)})")

    mdir = root / "identity" / "mandants"
    if mdir.is_dir():
        for path in sorted(mdir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            m = load_yaml(path)
            problems += [f"identity/mandants/{path.name}: {e}" for e in recipients.group_problems(path.stem, m)]
            refs = [("mandant", m.get("mail_profile"))]
            refs += [(f"person {p.get('id')}", p.get("mail_profile")) for p in m.get("persons") or []]
            for who, ref in refs:
                if ref and ref not in profs:
                    problems.append(f"identity/mandants/{path.name}: {who} names mail_profile '{ref}', "
                                    f"which is not in workflow/mail-profiles/")
    return problems
