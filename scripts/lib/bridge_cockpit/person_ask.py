# SPDX-License-Identifier: MIT
"""A person's question: a short read-only session on a key of its own, in a folder that holds their files only.

The owner's quick questions (quick.py) run in the Bridge and may read all of it, on whatever login the machine has. A
person gets none of that. Before each question the files of their workspaces are copied into <state>/people/<name>/room,
chosen by the same rule as their files tab (access.records), so what is not theirs is not there to be read. Links are
not followed and nothing in the folder points back. The session runs in that folder with Read, Grep and Glob, without
settings, and Claude Code refuses a path outside its folder by itself (proved with a planted word, docs/bridge-cockpit.md).

A workspace may add more under `sources.documents`: folders and named files of the Bridge (lib/document_paths.py says
which may be named). A folder is copied to a mirror under <state>/documents by a thread of its own, a question never
waits for it, and the room links what the mirror holds. PDFs come along, and with `pdftotext` or pypdf on the machine a
`.pdf.txt` beside each, so Grep finds their words; a scan without text stays readable by Read alone. Only reading:
nothing here writes to a source, and what a file refers to is never resolved.

How it signs in is `cockpit.served.ask.auth`. `login` (the default) uses the Claude login of the user the service runs
as: a subscription login is meant for its holder alone, so this is for the owner trying it out, and everyone else needs
access of their own. `key` runs on the named key and on nothing else: the run gets a configuration folder of its own and
loses every other way to sign in (Runner.run_person), so a key that fails is an error, never a subscription.

It follows the workspace: only a workspace at `boundary.level: room` feeds the folder, and the question is off for a
person who has none. `wall` promises the operating system's sandbox, which is not built, so it opens nothing either.

A person sends a plain question, nothing else: the words the page shows as context and the owner's other kinds of
question are refused. What is in a file is data: the system text says so, and with read tools only a file has nothing to
act through. Chats are kept per person, a session id never reaches a page, and a day has its limit.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import glob
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import quick
from .actions_base import ActionError
from .config import parse_keychain_ref
from .text import TABLES

MODELS = ("haiku", "sonnet")
TEXT_MAX = 4000
KEEP_CONVS = 20
FILE_MAX = 30 * 1024 * 1024
ROOM_MAX = 512 * 1024 * 1024
FILES_MAX = 4000
MIRROR_MAX = 8 * 1024 * 1024 * 1024
MIRROR_EVERY_S = 600
PDF_TIMEOUT_S = 60
SUFFIXES = frozenset({".md", ".txt", ".yaml", ".yml", ".csv", ".pdf"})
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}\Z")
ASK_FIELDS = frozenset({"kind", "args", "via", "conv"})


@dataclasses.dataclass(frozen=True)
class Settings:
    auth: str = "login"             # login: the service user's Claude login; key: key_ref or key_env and nothing else
    key_ref: str | None = None      # keychain://<service>/<account>
    key_env: str | None = None      # the name of an environment variable
    claude: str | None = None       # the absolute path of the CLI where a service's PATH does not find it
    model: str = "haiku"
    daily_questions: int = 30       # per person


def settings_problem(block: Any) -> str | None:
    if not isinstance(block, dict):
        return "must be a mapping"
    other = set(block) - {f.name for f in dataclasses.fields(Settings)}
    if other:
        return f"takes no {sorted(other)[0]}"
    auth, ref, env = block.get("auth", "login"), block.get("key_ref"), block.get("key_env")
    if auth not in ("login", "key"):
        return "auth must be login or key"
    if auth == "login" and (ref or env):
        return "takes a key only with auth: key"
    if auth == "key" and bool(ref) == bool(env):
        return "takes key_ref or key_env, exactly one" if ref else "with auth: key needs a key: key_ref or key_env"
    path = block.get("claude")
    if path is not None and not (isinstance(path, str) and path.startswith("/") and ".." not in path.split("/")):
        return "claude must be an absolute path"
    if ref and parse_keychain_ref(ref) is None:
        return "key_ref must be keychain://<service>/<account>"
    if env and not (isinstance(env, str) and ENV_RE.match(env)):
        return "key_env must name an environment variable"
    if block.get("model", "haiku") not in MODELS:
        return f"model must be one of {', '.join(MODELS)}"
    count = block.get("daily_questions", 30)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1000:
        return "daily_questions must be 1 to 1000"
    return None


def pdf_words(source: Path, target: Path, cache: Path) -> None:
    """The words of a PDF as a file beside its copy, kept by content stamp. No tool or no words: nothing."""
    info = source.stat()
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = hashlib.sha256(f"{source}|{info.st_size}|{info.st_mtime_ns}".encode("utf-8")).hexdigest()[:32]
    kept, none = cache / f"{stamp}.txt", cache / f"{stamp}.none"
    if not kept.exists() and not none.exists():
        spare = cache / f"{stamp}.{secrets.token_hex(4)}.tmp"
        tool = shutil.which("pdftotext") or ("/opt/homebrew/bin/pdftotext" if os.path.exists("/opt/homebrew/bin/pdftotext") else None)
        try:
            if tool:
                subprocess.run([tool, "-layout", "-enc", "UTF-8", str(source), str(spare)], capture_output=True,
                               timeout=PDF_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False)
            else:
                import pypdf   # noqa: PLC0415 - optional, the Read tool still reads a PDF without it
                spare.write_text("\n".join(p.extract_text() or "" for p in pypdf.PdfReader(str(source)).pages), encoding="utf-8")
        except Exception:  # noqa: BLE001 - a PDF that cannot be read is one PDF without words
            pass
        if spare.exists() and spare.stat().st_size and spare.read_text(encoding="utf-8", errors="replace").strip():
            os.replace(spare, kept)
        else:
            spare.unlink(missing_ok=True)
            none.touch()
    if kept.exists():
        shutil.copyfile(kept, target)


def copy_files(source: Path, target: Path, budget: list[int], cache: Path) -> None:
    """The documents of one record, links left out, each kept inside the record"""
    base = source.resolve()
    for folder, dirs, names in os.walk(source, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(folder) / d).is_symlink())
        for name in sorted(names):
            path = Path(folder) / name
            if name.startswith(".") or path.is_symlink() or path.suffix.lower() not in SUFFIXES:
                continue
            real, size = path.resolve(), path.stat().st_size
            if base not in real.parents or size > FILE_MAX or size > budget[0] or budget[1] <= 0:
                continue
            place = target / path.relative_to(source)
            place.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(path, place, follow_symlinks=False)
            if path.suffix.lower() == ".pdf":
                pdf_words(path, place.with_name(f"{place.name}.txt"), cache)
            budget[0] -= size
            budget[1] -= 1


class Documents:
    """The folders of sources.documents, mirrored by a thread of its own and at most every MIRROR_EVERY_S"""

    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.last: dict[str, float] = {}

    @property
    def base(self) -> Path:
        return self.app.state_dir / "documents"

    def mirror_of(self, folder: str) -> Path:
        return self.base / hashlib.sha256(folder.encode("utf-8")).hexdigest()[:24]

    def refresh(self, folders: list[str]) -> None:
        due = [f for f in folders if time.monotonic() - self.last.get(f, -MIRROR_EVERY_S) >= MIRROR_EVERY_S]
        with self.lock:
            if not due or (self.thread and self.thread.is_alive()):
                return
            self.last.update({f: time.monotonic() for f in due})
            self.thread = threading.Thread(target=self.sync, args=(due,), daemon=True)
            self.thread.start()

    def wait(self) -> None:
        if self.thread:
            self.thread.join(30)

    def sync(self, folders: list[str]) -> None:
        for folder in folders:
            try:
                self.mirror(folder)
            except Exception as exc:  # noqa: BLE001 - the last good mirror stands
                self.app.log_error(f"documents: {type(exc).__name__}")

    def mirror(self, folder: str) -> None:
        """Copies what changed, drops what left. Links are not followed, a file stays inside its folder."""
        source, target = Path(folder), self.mirror_of(folder)
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        wanted: set[Path] = set()
        left = MIRROR_MAX
        for place, dirs, names in os.walk(source, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(place) / d).is_symlink())
            for name in sorted(names):
                path = Path(place) / name
                if name.startswith(".") or path.is_symlink() or path.suffix.lower() not in SUFFIXES:
                    continue
                info = path.stat()
                if source not in path.resolve().parents or info.st_size > FILE_MAX or info.st_size > left:
                    continue
                left -= info.st_size
                copy = target / path.relative_to(source)
                wanted.add(copy)
                if copy.suffix.lower() == ".pdf":
                    wanted.add(copy.with_name(f"{copy.name}.txt"))
                seen = copy.exists() and copy.stat().st_size == info.st_size and copy.stat().st_mtime_ns >= info.st_mtime_ns
                if not seen:
                    copy.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    spare = copy.with_name(f".{secrets.token_hex(4)}.tmp")
                    shutil.copyfile(path, spare, follow_symlinks=False)
                    os.replace(spare, copy)
                if copy.suffix.lower() == ".pdf":
                    pdf_words(path, copy.with_name(f"{copy.name}.txt"), self.base.parent / "pdf-words")
        for place, _, names in os.walk(target):
            for name in names:
                if Path(place) / name not in wanted:
                    (Path(place) / name).unlink(missing_ok=True)

    def link(self, folder: str, into: Path) -> None:
        """Into a person's room as plain files of the same disk: no link that points anywhere, no second copy"""
        mirror = self.mirror_of(folder)
        for place, _, names in os.walk(mirror):
            for name in names:
                path = Path(place) / name
                if name.endswith(".tmp"):
                    continue
                goal = into / path.relative_to(mirror)
                goal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.link(path, goal)


class PersonAsk:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.Lock()
        self.documents = Documents(app)

    @property
    def settings(self) -> Settings | None:
        return getattr(self.app.cfg, "served_ask", None)

    def folder(self, person: str) -> Path:
        return self.app.state_dir / "people" / person

    # ------------------------------------------------------------ the key

    def key(self) -> str | None:
        """The key, read for each use and handed to the run only"""
        got = self.settings
        if got is None:
            return None
        if got.key_env:
            return (os.environ.get(got.key_env) or "").strip() or None
        found = parse_keychain_ref(got.key_ref)
        if found is None:
            return None
        try:
            res = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", found[0], "-a", found[1], "-w"],
                                 capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return (res.stdout.strip() or None) if res.returncode == 0 else None

    def available(self, person: str) -> bool:
        got = self.settings
        return bool(got and self.app.runner.person_claude and (got.auth == "login" or self.key())
                    and self.app.access.ask_scope(person))

    # ------------------------------------------------------------ the kept chats

    def path(self, person: str) -> Path:
        return self.folder(person) / "chats.json"

    def read(self, person: str) -> dict:
        try:
            data = json.loads(self.path(person).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return data if isinstance(data, dict) and isinstance(data.get("convs"), list) else {"convs": []}

    def write(self, person: str, data: dict) -> None:
        path = self.path(person)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        spare = path.with_name(f"chats.{secrets.token_hex(4)}.tmp")
        spare.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.chmod(spare, 0o600)
        os.replace(spare, path)

    def today(self) -> str:
        return dt.datetime.fromtimestamp(self.app.clock() / 1000).date().isoformat()

    def left(self, data: dict) -> int:
        used = data.get("used", 0) if data.get("day") == self.today() else 0
        return max(0, (self.settings.daily_questions if self.settings else 0) - used)

    def state(self, person: str) -> dict:
        with self.lock:
            data = self.read(person)
        convs = [{"id": c["id"], "running": bool(c.get("running")),
                  "turns": [{k: t.get(k) for k in ("q", "a", "error", "at_ms")} for t in c.get("turns", [])]}
                 for c in data["convs"]]
        open_now = self.available(person)
        if open_now:      # the page is open: the first question should find the folders mirrored
            self.documents.refresh([d for d in self.app.access.documents(person) if d.startswith("/")])
        return {"available": open_now, "left": self.left(data), "convs": convs}

    # ------------------------------------------------------------ the folder

    def room(self, person: str) -> Path:
        """Made anew for each question from what the person may see now, swapped in whole: a file that left their
        workspaces is gone, a changed one is fresh"""
        folder = self.folder(person)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        fresh, room = folder / f"room.{secrets.token_hex(4)}", folder / "room"
        fresh.mkdir(mode=0o700)
        budget, taken = [ROOM_MAX, FILES_MAX], set()
        root = self.app.root.resolve()
        scope = self.app.access.ask_scope(person)
        for record in self.app.access.records(person)["records"]:
            if str(record.get("area") or "").strip().lower() not in scope:
                continue
            source = (root / record["path"]).resolve()
            source = source.parent if source.is_file() else source
            if root not in source.parents or not source.is_dir():
                continue
            name = record["slug"]
            if name in taken:
                name = f"{name}-{source.parent.name}"
            taken.add(name)
            copy_files(source, fresh / name, budget, self.app.state_dir / "pdf-words")
        self.add_documents(person, fresh, budget)
        old = folder / f"room.{secrets.token_hex(4)}.old"
        if room.exists():
            room.rename(old)
        fresh.rename(room)
        shutil.rmtree(old, ignore_errors=True)
        return room

    def add_documents(self, person: str, room: Path, budget: list[int]) -> None:
        root, taken = self.app.root.resolve(), set()
        for item in self.app.access.documents(person):
            if item.startswith("/"):
                name = Path(item).name
                while name in taken:
                    name += "-2"
                taken.add(name)
                self.documents.link(item, room / "documents" / name)
                continue
            for found in sorted(glob.glob(glob.escape(str(root)) + "/" + item)):
                path = Path(found)
                if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
                    continue
                if path.suffix.lower() not in SUFFIXES or path.stat().st_size > min(FILE_MAX, budget[0]):
                    continue
                place = room / "documents" / "bridge" / path.relative_to(root)
                place.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(path, place, follow_symlinks=False)
                budget[0] -= path.stat().st_size

    # ------------------------------------------------------------ a question

    def refuse(self, field: str, message: str) -> ActionError:
        return ActionError(400, "invalid_argument", message, field)

    def ask(self, person: str, body: dict) -> tuple[int, dict]:
        extra = set(body) - ASK_FIELDS
        if extra:
            raise self.refuse(sorted(extra)[0][:40], "a person's question takes only its text")
        args = body.get("args")
        if body.get("kind") != "free" or body.get("via") != "quick":
            raise self.refuse("kind", "a person asks plain questions")
        if not isinstance(args, dict) or set(args) != {"text"} or not isinstance(args["text"], str):
            raise self.refuse("args", "a person's question takes only its text")
        text = args["text"].strip()
        if not text or len(text) > TEXT_MAX:
            raise self.refuse("text", f"1 to {TEXT_MAX} characters")
        conv = body.get("conv")
        if conv is not None and (not isinstance(conv, str) or not quick.CONV_RE.match(conv)):
            raise self.refuse("conv", "not a conversation id")
        if not self.available(person):
            raise ActionError(403, "ask_off", "questions are not set up for this person", None)
        now = int(self.app.clock())
        with self.lock:
            data = self.read(person)
            if any(c.get("running") for c in data["convs"]):
                raise ActionError(409, "not_applicable", "the last question is still running", None)
            if self.left(data) <= 0:
                raise ActionError(429, "daily_limit", "the questions of today are used up", None)
            chat = next((c for c in data["convs"] if c["id"] == conv), None)
            if conv is not None and chat is None:
                raise ActionError(409, "stale_row", "the conversation is gone", "conv")
            if chat is None:
                chat = {"id": f"q{secrets.token_hex(5)}", "session": None, "turns": []}
                data["convs"].insert(0, chat)
            used = data.get("used", 0) if data.get("day") == self.today() else 0
            data.update(day=self.today(), used=used + 1)
            chat["running"] = True
            chat["turns"].append({"q": text, "a": None, "error": None, "at_ms": now})
            data["convs"] = data["convs"][:KEEP_CONVS]
            self.write(person, data)
        conv_id, session = chat["id"], chat.get("session")
        self.documents.refresh([d for d in self.app.access.documents(person) if d.startswith("/")])
        self.app.actions.audit_line("ask", "free", via="person", conv=conv_id, model=self.settings.model, chars=len(text))
        threading.Thread(target=self.run, args=(person, conv_id, text, session), daemon=True).start()
        self.push(person)
        return 202, {"ok": True, "conv": conv_id}

    def system(self, person: str) -> str:
        language = self.app.cfg.language if self.app.cfg.language in TABLES else "en"
        return TABLES[language]["person_ask_system"].format(who=person, today=self.today())

    def run(self, person: str, conv: str, text: str, session: str | None) -> None:
        answer, failed = None, None
        try:
            room = self.room(person)
            model = self.settings.model
            argv = quick.build_argv(self.app.runner.person_claude, model, text, self.system(person), session)
            key, config = None, None
            if self.settings.auth == "key":
                key, config = self.key(), self.folder(person) / "claude"
                if not key:
                    raise RuntimeError("no key")
                config.mkdir(exist_ok=True, mode=0o700)
            done = self.app.runner.run_person(argv, quick.QUICK_TIMEOUT, room, key, config)
            parsed = quick.parse_answer(done.out)
            if parsed and not parsed["error"] and done.ok:
                answer = parsed
            else:
                failed = "failed"
        except Exception:  # noqa: BLE001 - the page gets a word, never a path or the reason
            failed = "failed"
        with self.lock:
            data = self.read(person)
            chat = next((c for c in data["convs"] if c["id"] == conv), None)
            if chat is not None:
                chat["running"] = False
                turn = chat["turns"][-1]
                if answer:
                    turn["a"] = answer["text"]
                    chat["session"] = answer["session"] or chat.get("session")
                    chat["total_usd"] = answer["total_usd"]
                else:
                    turn["error"] = failed
                self.write(person, data)
        self.push(person)

    def push(self, person: str) -> None:
        self.app.hub.to_viewer(person, "person_ask", self.state(person))
