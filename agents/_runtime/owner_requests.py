"""Peer requests: something to be DONE, decided by the owner or by a rule the owner set.

The executor hands a message here when its metadata carries
``bridge_request: {"kind": "request", "subject": "..."}`` (or ``{"kind": "policy"}``)
and the instance has ``requests:`` on. The model never sees a request:

1. the ledger records it
2. a rule for this peer and subject decides it, deny before allow, or else the owner
   is asked through the same approval command answers use (``"kind": "request"``)
3. a rule the owner set while deciding is stored and announced to the peer
4. on a yes the owner's execute command runs with the request; without one, the
   peer is told the owner carries it out
5. every step lands in the ledger

``kind: policy`` returns the rules and history that concern the asking peer, without
owner or model. Rules and ledger: ``_runtime/policy.py``.
"""
from __future__ import annotations

import asyncio
import json
import logging

from a2a.helpers import new_text_part
from a2a.server.tasks import TaskUpdater
from a2a.types import TaskState

from .approval import Decision
from .policy import PolicyError, RequestsConfig, policy_for, valid_peer_subject

logger = logging.getLogger(__name__)

REQUEST_MESSAGES = {
    "request_needs_peer": "Requests need an authenticated peer.",
    "request_waiting": "Your request is with the owner.",
    "request_handed": "The owner approved this and carries it out.",
    "request_done": "Done.",
    "request_rejected": "The owner declined this request.",
    "request_no_decision": "The owner did not decide; nothing was done.",
    "request_failed": "Carrying it out failed: {text}",
    "rule_allow": "Rule {rule} allows this without asking the owner.",
    "rule_deny": "Rule {rule} declines this.",
    "rule_added": "The owner made this a standing rule: {rule} ({effect} {subject}).",
    "rule_no_subject": ("The owner wanted a standing rule for this, but your request had no "
                        "subject, so none was set. Send a subject next time."),
    "owner_note": "Note from the owner: {text}",
    "request_bad_subject": ("Subject refused: letters, digits and . _ : @ / - only, no "
                            "spaces or wildcards, at most 200 characters."),
    "request_too_many": "You have {n} requests open with the owner already; wait for a decision.",
    "rule_contradicts": ("The owner's rule contradicts the decision (allow with a no, or deny "
                         "with a yes); nothing was done."),
    "rule_not_stored": "The owner set a rule, but it could not be stored: {error}",
}

_GRACE_SEC = 30.0
# Requests one peer may have waiting on the owner at once; more are refused, so a
# peer cannot flood the owner's channel or the host with approver processes.
MAX_OPEN_PER_PEER = 3


class OwnerRequests:
    """Runs one peer request or policy read to its end on ``updater``."""

    def __init__(self, cfg: RequestsConfig, approver, messages: dict | None = None):
        self._cfg = cfg
        self._approver = approver
        self._policy = policy_for(cfg)
        self._msg = {**REQUEST_MESSAGES, **(messages or {})}
        self._open: dict[str, int] = {}

    async def handle(self, updater: TaskUpdater, *, kind: str, subject: str, text: str,
                     peer: str | None, task_id: str, context_id: str) -> None:
        if not peer:
            await updater.reject(message=self._say(updater, self._msg["request_needs_peer"]))
            return
        if kind == "policy":
            view = self._policy.view_for(peer)
            await updater.add_artifact([new_text_part(view)], name="policy")
            await updater.complete(message=self._say(updater, view))
            return

        if subject and not valid_peer_subject(subject):
            self._policy.record("refused", peer=peer, task_id=task_id, reason="bad subject",
                                subject=subject[:200])
            await updater.reject(message=self._say(updater, self._msg["request_bad_subject"]))
            return
        if self._open.get(peer, 0) >= MAX_OPEN_PER_PEER:
            self._policy.record("refused", peer=peer, task_id=task_id, subject=subject,
                                reason="too many open requests")
            await updater.reject(message=self._say(
                updater, self._msg["request_too_many"].format(n=self._open[peer])))
            return
        self._open[peer] = self._open.get(peer, 0) + 1
        try:
            await self._decide_and_do(updater, subject=subject, text=text, peer=peer,
                                      task_id=task_id, context_id=context_id)
        except asyncio.CancelledError:
            self._policy.record("cancelled", peer=peer, task_id=task_id, subject=subject)
            raise
        finally:
            self._open[peer] -= 1
            if not self._open[peer]:
                del self._open[peer]

    async def _decide_and_do(self, updater: TaskUpdater, *, subject: str, text: str, peer: str,
                             task_id: str, context_id: str) -> None:
        pol = self._policy
        pol.record("requested", peer=peer, task_id=task_id, context_id=context_id,
                   subject=subject, request=text)
        rule = pol.match(peer, subject)
        notes: list[str] = []
        if rule is not None:
            decided_by = f"rule:{rule.id}"
            verdict = "approve" if rule.effect == "allow" else "reject"
            pol.record("decided", peer=peer, task_id=task_id, subject=subject,
                       verdict=verdict, by=decided_by)
            key = "rule_allow" if rule.effect == "allow" else "rule_deny"
            notes.append(self._msg[key].format(rule=rule.id)
                         + (f" ({rule.note})" if rule.note else ""))
            owner_note = ""
            rule_id = rule.id
        else:
            await updater.update_status(TaskState.TASK_STATE_WORKING,
                                        message=self._say(updater, self._msg["request_waiting"]))
            decision = await self._approver({
                "kind": "request",
                "task_id": task_id,
                "context_id": context_id,
                "peer": peer,
                "subject": subject,
                "question": text,
                # For an approver that only knows answers: what it shows the owner.
                "answer": (f"REQUEST from {peer} (subject: {subject or 'none'}):\n{text}\n\n"
                           "Approve to have it done. You may add a rule so this peer gets "
                           "the same without asking, or never."),
            })
            # An approver that only knows answers "edits" to write a reply, often a
            # refusal; for a request that is never a yes.
            verdict = "reject" if decision.verdict == "edit" else decision.verdict
            decided_by = "owner"
            owner_note = decision.text
            rule_id = None
            wanted = {"approve": "allow", "reject": "deny"}.get(verdict)
            if decision.rule and decision.verdict != "edit" and decision.rule.get("effect") != wanted:
                pol.record("decided", peer=peer, task_id=task_id, subject=subject,
                           verdict="none", by=decided_by, reason="rule contradicts decision")
                await updater.reject(message=self._say(updater, self._msg["rule_contradicts"]))
                return
            pol.record("decided", peer=peer, task_id=task_id, subject=subject,
                       verdict=verdict, by=decided_by, note=owner_note or None)
            if verdict in ("approve", "reject") and decision.rule and decision.verdict != "edit":
                rule_id = self._add_rule(decision, peer, subject, task_id, notes)
            if owner_note:
                notes.append(self._msg["owner_note"].format(text=owner_note))
            if verdict == "timeout":
                # The owner never decided: the request lapsed, nobody refused it.
                await updater.cancel(message=self._say(updater, self._msg["request_no_decision"]))
                return
            if verdict not in ("approve", "reject"):
                await updater.reject(message=self._say(updater, self._msg["request_no_decision"]))
                return

        if verdict == "reject":
            await updater.reject(message=self._say(
                updater, "\n".join([self._msg["request_rejected"], *notes])))
            return

        if not self._cfg.execute_command:
            pol.record("handed_to_owner", peer=peer, task_id=task_id, subject=subject,
                       by=decided_by)
            await self._finish(updater, "\n".join([self._msg["request_handed"], *notes]))
            return

        status, result = await self._execute({
            "task_id": task_id, "context_id": context_id, "peer": peer, "subject": subject,
            "request": text, "decided_by": decided_by, "rule_id": rule_id,
            "owner_note": owner_note,
        })
        pol.record("executed", peer=peer, task_id=task_id, subject=subject, status=status,
                   result=result[:500])
        if status != "done":
            await updater.failed(message=self._say(updater, "\n".join(
                [self._msg["request_failed"].format(text=result or "no result"), *notes])))
            return
        await self._finish(updater, "\n".join([result or self._msg["request_done"], *notes]))

    # ------------------------------------------------------------------

    def _add_rule(self, decision: Decision, peer: str, subject: str, task_id: str,
                  notes: list[str]) -> str | None:
        spec = decision.rule or {}
        rule_subject = spec.get("subject") or subject
        if not rule_subject:
            self._policy.record("rule_skipped", peer=peer, task_id=task_id,
                                reason="no subject", by="owner")
            notes.append(self._msg["rule_no_subject"])
            return None
        try:
            rule = self._policy.add_rule(peer=peer, subject=rule_subject, effect=spec["effect"],
                                         note=spec.get("note", ""), by="owner",
                                         source_task=task_id, expires=spec.get("expires"))
        except (PolicyError, ValueError) as exc:
            logger.error("requests: rule not stored: %s", exc)
            self._policy.record("rule_failed", peer=peer, task_id=task_id, by="owner",
                                reason=str(exc)[:300])
            notes.append(self._msg["rule_not_stored"].format(error=exc))
            return None
        notes.append(self._msg["rule_added"].format(rule=rule.id, effect=rule.effect,
                                                    subject=rule.subject)
                     + (f" ({rule.note})" if rule.note else ""))
        return rule.id

    async def _execute(self, payload: dict) -> tuple[str, str]:
        """Run the owner's execute command; ``("done"|"failed", text)``, never raises."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._cfg.execute_command,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            logger.exception("requests: cannot start the execute command")
            return "failed", f"cannot start: {exc}"
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                timeout=self._cfg.execute_timeout_sec + _GRACE_SEC,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return "failed", "timed out"
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode != 0:
            logger.warning("requests: execute exited %s: %s", proc.returncode,
                           err.decode("utf-8", "replace").strip()[:300])
            return "failed", f"exit {proc.returncode}"
        try:
            data = json.loads(out.decode("utf-8").strip().splitlines()[-1])
        except (ValueError, IndexError, UnicodeDecodeError):
            return "failed", "no JSON result"
        status = str(data.get("status", "")).lower()
        text = str(data.get("text") or "").strip()
        return ("done" if status == "done" else "failed"), text

    async def _finish(self, updater: TaskUpdater, text: str) -> None:
        await updater.add_artifact([new_text_part(text)], name="result")
        await updater.complete(message=self._say(updater, text))

    @staticmethod
    def _say(updater: TaskUpdater, text: str):
        return updater.new_agent_message([new_text_part(text)])


def request_of(metadata) -> tuple[str, str]:
    """``(kind, subject)`` from ``bridge_request`` metadata; ``("", "")`` when absent."""
    if not metadata:
        return "", ""
    try:
        if isinstance(metadata, dict):
            md = metadata
        else:
            from google.protobuf.json_format import MessageToDict
            md = MessageToDict(metadata)
        br = md.get("bridge_request")
    except Exception:  # noqa: BLE001 — absent or malformed metadata is a plain question
        return "", ""
    if not isinstance(br, dict):
        return "", ""
    kind = str(br.get("kind") or "").strip().lower()
    if kind not in ("request", "policy"):
        return "", ""
    subject = str(br.get("subject") or "").strip()[:200]
    return kind, subject
