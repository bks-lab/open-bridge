"""Peer authentication for a Bridge-Agent that answers other Bridges only.

Declared in ``agent.yaml``::

    trust: peer
    auth:
      mode: bearer                       # none (default) | bearer
      connector_token_env: AGENT_CONNECTOR_TOKEN  # optional: one token for the local connector
      peers:
        - id: axel                       # shows up in logs as the caller
          token_env: AGENT_PEER_TOKEN_AXEL   # the token itself lives in the environment
          tailscale_login: axel@example.org  # optional: bind the token to a network identity

**Connector token.** With ``connector_token_env`` one shared token proves "the call
comes from the local A2A connector"; the connector then names the asker in the
``X-A2A-Sender`` header. The header is read only after the token matched, must be a
plain id (:data:`~_runtime.access.TOPIC_RE`, so it can never be a path), and a valid
token without a usable header is a 401, never anonymous. Because anyone holding the
token can then claim any sender, it is accepted only when the agent binds to
loopback (:func:`check_connector_loopback`); there is no switch to lift that.
``peers`` may be empty in that case; peer tokens and ``tailscale_login`` keep
working beside it.

One seam, one decision: :class:`PeerAuthBackend` turns a request into a peer or
refuses it, and nothing else in the runtime knows how. Swapping bearer tokens for
OIDC later changes this module, not the server, the executor or the card shape.

Fail closed everywhere. A block the runtime cannot honour (unknown mode, no peer, a
missing or weak token, a raw token written into the file) stops the agent from
starting; it never degrades into an open endpoint.
"""
from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field

from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from .access import TOPIC_RE

logger = logging.getLogger(__name__)

_VALID_MODES = frozenset({"none", "bearer"})
MIN_TOKEN_CHARS = 32
SENDER_HEADER = "x-a2a-sender"
# The only binds the connector token may live on. Deliberately not "localhost": a name
# resolves to whatever the resolver says.
CONNECTOR_HOSTS = frozenset({"127.0.0.1", "::1"})

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
    connector_token: str | None = field(default=None, repr=False)  # never print the token

    @property
    def enabled(self) -> bool:
        return self.mode != "none"


def parse_auth(instance: str, spec: dict | None) -> AuthConfig:
    """Resolve the ``auth:`` block of ``agent.yaml``; raise on anything unsafe."""
    if not spec:
        return AuthConfig()
    mode = str(spec.get("mode", "none")).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"agent '{instance}': unknown auth.mode {mode!r} (none | bearer)")
    if mode == "none":
        return AuthConfig()

    if "connector_token" in spec:
        raise ValueError(
            f"agent '{instance}': a raw connector_token in agent.yaml; "
            "put it in the environment and name it with connector_token_env"
        )
    connector_token = None
    connector_env = str(spec.get("connector_token_env") or "").strip()
    if connector_env:
        connector_token = os.getenv(connector_env, "")
        if not connector_token:
            raise ValueError(
                f"agent '{instance}': no connector token (connector_token_env {connector_env!r} unset)"
            )
        if len(connector_token) < MIN_TOKEN_CHARS:
            raise ValueError(
                f"agent '{instance}': the connector token is shorter than {MIN_TOKEN_CHARS} characters"
            )

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

    if connector_token and any(hmac.compare_digest(p.token.encode(), connector_token.encode()) for p in peers):
        raise ValueError(
            f"agent '{instance}': the connector token equals a peer token; "
            "they must differ, or that peer could name any sender"
        )
    if not peers and not connector_token:
        raise ValueError(
            f"agent '{instance}': auth.mode bearer needs at least one peer or a connector_token_env"
        )
    return AuthConfig(mode=mode, peers=tuple(peers), connector_token=connector_token)


def check_connector_loopback(instance: str, auth: AuthConfig, host: str) -> None:
    """Refuse a connector token on any bind but loopback; it names senders unchecked."""
    if auth.connector_token and host not in CONNECTOR_HOSTS:
        raise ValueError(
            f"agent '{instance}': connector_token_env needs the agent to bind to loopback "
            f"(127.0.0.1 or ::1), got host {host!r}. Anyone holding the connector token can "
            "name any sender; use per-peer tokens for a reachable agent."
        )


class IdentityMismatch(AuthenticationError):
    """The token is valid, but it arrived from the wrong network identity."""


class PeerAuthBackend(AuthenticationBackend):
    """Map ``Authorization: Bearer <token>`` to a known peer, or refuse.

    No header → anonymous (the card and /health stay reachable; the JSON-RPC route
    is guarded separately). A header that does not resolve to a peer is an error,
    never a silent downgrade to anonymous.
    """

    def __init__(self, auth: AuthConfig):
        self._peers = auth.peers
        self._connector = auth.connector_token

    async def authenticate(self, conn: HTTPConnection):
        header = conn.headers.get("authorization")
        if header is None:
            return None
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token:
            raise AuthenticationError("malformed authorization")

        match = None
        for peer in self._peers:  # compare against every peer, no early exit
            if hmac.compare_digest(peer.token.encode(), token.encode()):
                match = peer
        is_connector = bool(self._connector) and hmac.compare_digest(
            self._connector.encode(), token.encode()
        )
        if match is None and not is_connector:
            raise AuthenticationError("unknown token")

        if match is None:
            # The header counts only now, behind a valid connector token.
            sender = (conn.headers.get(SENDER_HEADER) or "").strip()
            if not TOPIC_RE.match(sender):
                logger.warning("peer_auth: connector token without a usable sender")
                raise AuthenticationError("sender required")
            return AuthCredentials(["peer"]), SimpleUser(sender)

        if match.tailscale_login:
            seen = (conn.headers.get(TAILSCALE_LOGIN_HEADER) or "").strip().lower()
            if seen != match.tailscale_login.lower():
                logger.warning(
                    "peer_auth: token of %s from wrong identity %r", match.id, seen or None
                )
                raise IdentityMismatch("identity mismatch")

        return AuthCredentials(["peer"]), SimpleUser(match.id)


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
