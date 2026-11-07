"""Peer authentication for a Bridge-Agent that answers other Bridges only.

Declared in ``agent.yaml``::

    trust: peer
    auth:
      mode: bearer                       # none (default) | bearer | derived
      peers:
        - id: alice                      # shows up in logs as the caller
          token_env: AGENT_PEER_TOKEN_ALICE   # the token itself lives in the environment
          tailscale_login: alice@example.org  # optional: bind the token to a network identity

**Derived mode** accepts any peer an upstream relay vouches for, without listing it
here::

    auth:
      mode: derived
      secret_env: AGENT_PEER_SECRET      # one shared secret, at least 32 characters
      sender_header: X-A2A-Sender        # optional, this is the default
      peers: open                        # any well-formed id; or a list of ids

The relay sends ``X-A2A-Sender: <id>`` and ``Authorization: Bearer <token>`` with
``token = HMAC-SHA256(secret, "a2a-local-bearer/v1/" + id)`` (hex). The id must be a
plain DNS-label-like id (``PEER_ID_RE``); a missing header, a bad id, a token that
does not match, or an id outside the list is refused. The id then is the
authenticated user, exactly like a bearer peer, so per-peer memory, folders and logs
work unchanged. Whoever holds the secret can speak as any id: it belongs to the
relay alone, never to a peer.

One seam, one decision: :class:`PeerAuthBackend` turns a request into a peer or
refuses it, and nothing else in the runtime knows how. Swapping bearer tokens for
OIDC later changes this module, not the server, the executor or the card shape.

Fail closed everywhere. A block the runtime cannot honour (unknown mode, no peer, a
missing or weak token or secret, a raw token or secret written into the file) stops
the agent from starting; it never degrades into an open endpoint. Neither the secret
nor any token is ever logged.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass, field

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

_VALID_MODES = frozenset({"none", "bearer", "derived"})
MIN_TOKEN_CHARS = 32
MIN_SECRET_CHARS = 32

# Derived mode: the relay names the caller in this header and signs the name.
DEFAULT_SENDER_HEADER = "X-A2A-Sender"
DERIVED_TOKEN_CONTEXT = "a2a-local-bearer/v1/"
PEER_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Set by ``tailscale serve`` for requests from a tailnet (or shared-in) user. Only
# trustworthy because the agent binds to loopback behind that proxy, and even then
# only together with the token: any local process could set it.
TAILSCALE_LOGIN_HEADER = "tailscale-user-login"


@dataclass(frozen=True)
class Peer:
    id: str
    token: str
    tailscale_login: str | None = None

    def __repr__(self) -> str:  # never print the token
        return f"Peer(id={self.id!r}, tailscale_login={self.tailscale_login!r})"


@dataclass(frozen=True)
class AuthConfig:
    mode: str = "none"
    peers: tuple[Peer, ...] = ()
    # derived mode only
    secret: str = field(default="", repr=False)
    sender_header: str = DEFAULT_SENDER_HEADER
    open_peers: bool = False
    allowed: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.mode != "none"

    @property
    def peer_ids(self) -> tuple[str, ...] | None:
        """The ids known at startup; None when any vouched-for id may call."""
        if self.mode == "derived":
            return None if self.open_peers else self.allowed
        return tuple(p.id for p in self.peers)


def derive_token(secret: str, peer_id: str) -> str:
    """The bearer token the relay sends for ``peer_id`` under ``secret``."""
    return hmac.new(
        secret.encode(), (DERIVED_TOKEN_CONTEXT + peer_id).encode(), hashlib.sha256
    ).hexdigest()


def parse_auth(instance: str, spec: dict | None) -> AuthConfig:
    """Resolve the ``auth:`` block of ``agent.yaml``; raise on anything unsafe."""
    if not spec:
        return AuthConfig()
    mode = str(spec.get("mode", "none")).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"agent '{instance}': unknown auth.mode {mode!r} (none | bearer | derived)")
    if mode == "none":
        return AuthConfig()
    if mode == "derived":
        return _parse_derived(instance, spec)

    peers: list[Peer] = []
    for raw in spec.get("peers") or []:
        peer_id = str(raw.get("id") or "").strip()
        if not peer_id:
            raise ValueError(f"agent '{instance}': auth peer without id")
        if "token" in raw:
            raise ValueError(
                f"agent '{instance}': peer '{peer_id}' has a raw token in agent.yaml; "
                "put it in the environment and name it with token_env"
            )
        env_name = str(raw.get("token_env") or "").strip()
        token = os.getenv(env_name, "") if env_name else ""
        if not token:
            raise ValueError(
                f"agent '{instance}': peer '{peer_id}' has no token (token_env {env_name!r} unset)"
            )
        if len(token) < MIN_TOKEN_CHARS:
            raise ValueError(
                f"agent '{instance}': token for peer '{peer_id}' is shorter than "
                f"{MIN_TOKEN_CHARS} characters"
            )
        login = str(raw.get("tailscale_login") or "").strip() or None
        peers.append(Peer(id=peer_id, token=token, tailscale_login=login))

    if not peers:
        raise ValueError(f"agent '{instance}': auth.mode bearer needs at least one peer")
    return AuthConfig(mode=mode, peers=tuple(peers))


def _parse_derived(instance: str, spec: dict) -> AuthConfig:
    where = f"agent '{instance}': auth.mode derived"
    if "secret" in spec:
        raise ValueError(
            f"{where} has a raw secret in agent.yaml; put it in the environment and "
            "name it with secret_env"
        )
    env_name = str(spec.get("secret_env") or "").strip()
    if not env_name:
        raise ValueError(f"{where} needs secret_env (the variable holding the shared secret)")
    secret = os.getenv(env_name, "")
    if not secret:
        raise ValueError(f"{where}: no secret (secret_env {env_name!r} unset)")
    if len(secret) < MIN_SECRET_CHARS:
        raise ValueError(f"{where}: the secret is shorter than {MIN_SECRET_CHARS} characters")

    header = spec.get("sender_header", DEFAULT_SENDER_HEADER)
    if not isinstance(header, str) or not header.strip():
        raise ValueError(f"{where}: sender_header must name a header")

    raw = spec.get("peers")
    if raw == "open":
        return AuthConfig(mode="derived", secret=secret, sender_header=header.strip(),
                          open_peers=True)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{where}: peers must be \"open\" or a non-empty list of ids")
    bad = [p for p in raw if not isinstance(p, str) or not PEER_ID_RE.fullmatch(p)]
    if bad:
        raise ValueError(f"{where}: peer {bad[0]!r} is not a plain id (a-z, 0-9, -)")
    return AuthConfig(mode="derived", secret=secret, sender_header=header.strip(),
                      allowed=tuple(dict.fromkeys(raw)))


class IdentityMismatch(AuthenticationError):
    """The token is valid, but it arrived from the wrong network identity."""


class PeerAuthBackend(AuthenticationBackend):
    """Map ``Authorization: Bearer <token>`` to a known peer, or refuse.

    No header → anonymous (the card and /health stay reachable; the JSON-RPC route
    is guarded separately). A header that does not resolve to a peer is an error,
    never a silent downgrade to anonymous.
    """

    def __init__(self, auth: AuthConfig):
        if auth.mode == "derived" and len(auth.secret) < MIN_SECRET_CHARS:
            # parse_auth already refuses this; a hand-built config must not either.
            raise ValueError("derived auth without a usable secret")
        self._auth = auth
        self._peers = auth.peers

    async def authenticate(self, conn: HTTPConnection):
        header = conn.headers.get("authorization")
        if header is None:
            return None
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("malformed authorization")
        if self._auth.mode == "derived":
            return self._derived(conn, token)

        match = None
        for peer in self._peers:  # compare against every peer, no early exit
            if hmac.compare_digest(peer.token.encode(), token.encode()):
                match = peer
        if match is None:
            raise AuthenticationError("unknown token")

        if match.tailscale_login:
            seen = (conn.headers.get(TAILSCALE_LOGIN_HEADER) or "").strip().lower()
            if seen != match.tailscale_login.lower():
                logger.warning(
                    "peer_auth: token of %s from wrong identity %r", match.id, seen or None
                )
                raise IdentityMismatch("identity mismatch")

        return AuthCredentials(["peer"]), SimpleUser(match.id)

    def _derived(self, conn: HTTPConnection, token: str):
        auth = self._auth
        sender = conn.headers.get(auth.sender_header)
        if sender is None:
            raise AuthenticationError("sender required")
        sender = sender.strip()
        if not PEER_ID_RE.fullmatch(sender):
            raise AuthenticationError("bad sender")
        # Compare first, decide after: the answer for a listed and an unlisted id
        # costs the same.
        valid = hmac.compare_digest(derive_token(auth.secret, sender).encode(), token.encode())
        if not valid:
            raise AuthenticationError("unknown token")
        if not auth.open_peers and sender not in auth.allowed:
            logger.warning("peer_auth: %r is not on the peer list", sender)
            raise AuthenticationError("peer not allowed")
        return AuthCredentials(["peer"]), SimpleUser(sender)


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized", "detail": detail},
        status_code=401,
        headers={"WWW-Authenticate": 'Bearer realm="bridge-agent"'},
    )


def on_auth_error(_conn: HTTPConnection, exc: Exception) -> JSONResponse:
    if isinstance(exc, IdentityMismatch):
        return JSONResponse({"error": "forbidden", "detail": str(exc)}, status_code=403)
    logger.warning("peer_auth: refused (%s)", exc)
    return _unauthorized(str(exc))


def require_peer(endpoint):
    """Wrap a route endpoint so only an authenticated peer reaches it."""

    async def guarded(request):
        user = request.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            return _unauthorized("token required")
        return await endpoint(request)

    return guarded
