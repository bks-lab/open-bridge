"""Typed error taxonomy (SPEC ERR-1..4).

Stable machine-checkable string codes; errors are *returned* in tool result
envelopes at the MCP boundary, never raised across it. Messages must never
contain credential values.
"""

from __future__ import annotations

from typing import ClassVar, TypedDict


class ErrorInfo(TypedDict):
    code: str
    message: str
    retry_after_s: float | None


class GatewayError(Exception):
    """Base for all typed gateway failures. ``code`` is a stable machine string."""

    code: ClassVar[str] = "gateway_error"

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s

    def to_info(self) -> ErrorInfo:
        return {
            "code": self.code,
            "message": str(self),
            "retry_after_s": self.retry_after_s,
        }


class UnknownBridgeError(GatewayError):
    code = "unknown_bridge"


class TierDeniedError(GatewayError):
    code = "tier_denied"


class UnauthorizedError(GatewayError):
    code = "unauthorized"


class BridgeBusyError(GatewayError):
    code = "busy"


class BridgeTimeoutError(GatewayError):
    code = "timeout"


class BridgeUnreachableError(GatewayError):
    code = "unreachable"


class UpstreamError(GatewayError):
    code = "upstream_error"


class RegistryError(ValueError):
    """Startup-time config/schema violation — never crosses the MCP boundary."""
