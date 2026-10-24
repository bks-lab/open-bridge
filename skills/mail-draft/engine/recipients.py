"""Who a draft goes to, resolved from identity/mandants/.

A recipient on the command line is one of:

    anna@example.com        an address, used as written
    mandant:team            every person of that mandant who has an email
    mandant:team#leads      only the persons the mandant's `groups: {leads: [...]}` lists
    team/anna               one person of one mandant
    anna                    a person id, when exactly one mandant has it,
                            else a person's `nicknames` entry, when exactly one person has it

A resolved person brings what the draft needs to address them: the display
name (for the greeting), the language and the form of address from the
person's `defaults`, and any `mail_profile` set on the person or the mandant.
Mandants carry PII, so they are USER files; this module only reads them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, load_yaml

ADDRESS = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


class RecipientError(ConfigError):
    pass


@dataclass
class Recipient:
    address: str
    name: str = ""
    person_id: str = ""
    mandant_id: str = ""
    mandant_name: str = ""
    mandant_type: str = ""
    tags: list[str] = field(default_factory=list)
    language: str = ""
    address_form: str = ""
    profile: str = ""            # person's mail_profile
    mandant_profile: str = ""    # mandant's mail_profile

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else ""

    @property
    def last_name(self) -> str:
        return self.name.split()[-1] if len(self.name.split()) > 1 else ""

    def label(self) -> str:
        return f"{self.name} <{self.address}>" if self.name else self.address


def _mandants(root: Path) -> dict[str, dict]:
    d = root / "identity" / "mandants"
    out: dict[str, dict] = {}
    if d.is_dir():
        for path in sorted(d.glob("*.yaml")):
            if not path.name.startswith("_"):
                out[path.stem] = load_yaml(path)
    return out


def _person(mid: str, m: dict, p: dict) -> Recipient | None:
    channels = p.get("channels") or {}
    address = channels.get("email")
    if not address:
        return None
    defaults = p.get("defaults") or {}
    return Recipient(
        address=str(address), name=str(p.get("display_name") or ""), person_id=str(p.get("id") or ""),
        mandant_id=mid, mandant_name=str(m.get("display_name") or mid), mandant_type=str(m.get("type") or ""),
        tags=[str(t) for t in (m.get("tags") or [])],
        language=str(defaults.get("language") or m.get("language") or ""),
        address_form=str(defaults.get("address_form") or m.get("address_form") or ""),
        profile=str(p.get("mail_profile") or ""), mandant_profile=str(m.get("mail_profile") or ""),
    )


def group_problems(mid: str, m: dict) -> list[str]:
    """What is wrong with a mandant's `groups:` block, one line per problem.

    A group is a named list of person ids. A member that is no person of the
    mandant is an error, never skipped: a typo would otherwise leave someone
    off the list without a word.
    """
    groups = m.get("groups") or {}
    if not isinstance(groups, dict):
        return [f"mandant '{mid}': groups must map a group name to a list of person ids"]
    ids = {str(p.get("id")) for p in m.get("persons") or []}
    out = []
    for name, members in groups.items():
        if not isinstance(members, list) or not members:
            out.append(f"mandant '{mid}': group '{name}' must list at least one person id")
            continue
        missing = [str(x) for x in members if str(x) not in ids]
        if missing:
            out.append(f"mandant '{mid}': group '{name}' names {', '.join(repr(x) for x in missing)}, "
                       f"which is no person of this mandant")
    return out


def group_members(mid: str, m: dict, group: str) -> list[dict]:
    """The persons of one group, in the group's order."""
    groups = m.get("groups") or {}
    if not isinstance(groups, dict) or group not in groups:
        known = ", ".join(sorted(groups)) if isinstance(groups, dict) and groups else "none"
        raise RecipientError(f"mandant '{mid}' has no group '{group}' (defined: {known})")
    problems = [p for p in group_problems(mid, {**m, "groups": {group: groups[group]}})]
    if problems:
        raise RecipientError(problems[0])
    by_id = {str(p.get("id")): p for p in m.get("persons") or []}
    return [by_id[str(x)] for x in groups[group]]


def resolve(root: Path, tokens: list[str]) -> list[Recipient]:
    """Every token to one or more recipients, in order, without duplicates."""
    mandants = None
    out: list[Recipient] = []
    seen: set[str] = set()

    def add(r: Recipient):
        key = r.address.lower()
        if key not in seen:
            seen.add(key)
            out.append(r)

    for raw in tokens:
        for token in [t.strip() for t in re.split(r"[,;]", raw) if t.strip()]:
            if "@" in token:
                if not ADDRESS.match(token):
                    raise RecipientError(f"'{token}' is not an email address")
                add(_known(root, token) or Recipient(address=token))
                continue
            if mandants is None:
                mandants = _mandants(root)
            if token.startswith("mandant:"):
                mid, _, group = token.split(":", 1)[1].partition("#")
                if mid not in mandants:
                    raise RecipientError(f"mandant '{mid}' is not defined in identity/mandants/")
                persons = group_members(mid, mandants[mid], group) if group else mandants[mid].get("persons") or []
                people = [r for r in (_person(mid, mandants[mid], p) for p in persons) if r]
                if not people:
                    what = f"group '{group}' of mandant '{mid}'" if group else f"mandant '{mid}'"
                    raise RecipientError(f"{what} has no person with an email")
                for r in people:
                    add(r)
                continue
            if "/" in token:
                mid, pid = token.split("/", 1)
                m = mandants.get(mid)
                if m is None:
                    raise RecipientError(f"mandant '{mid}' is not defined in identity/mandants/")
                match = [p for p in m.get("persons") or [] if str(p.get("id")) == pid]
                if not match:
                    raise RecipientError(f"'{token}': mandant '{mid}' has no person '{pid}'")
                r = _person(mid, m, match[0])
                if r is None:
                    raise RecipientError(f"'{token}' has no email channel")
                add(r)
                continue
            hits = [(mid, m, p) for mid, m in mandants.items() for p in m.get("persons") or []
                    if str(p.get("id")) == token]
            if not hits:
                # A nickname only when no person carries the token as an id:
                # an id is exact, a nickname is a convenience and never shadows one.
                hits = [(mid, m, p) for mid, m in mandants.items() for p in m.get("persons") or []
                        if token.lower() in {str(n).lower() for n in (p.get("nicknames") or [])}]
            if not hits:
                raise RecipientError(f"'{token}' is neither an address nor a person in identity/mandants/")
            if len(hits) > 1:
                where = ", ".join(f"{mid}/{token}" for mid, _, _ in hits)
                raise RecipientError(f"'{token}' is in more than one mandant, name one: {where}")
            r = _person(*hits[0])
            if r is None:
                raise RecipientError(f"'{token}' has no email channel")
            add(r)
    return out


def _known(root: Path, address: str) -> Recipient | None:
    """An address that belongs to a known person still brings their name and defaults."""
    for mid, m in _mandants(root).items():
        for p in m.get("persons") or []:
            channels = p.get("channels") or {}
            if address.lower() in {str(channels.get(k, "")).lower() for k in ("email", "email_alt")}:
                r = _person(mid, m, p)
                if r:
                    r.address = address
                    return r
    return None
