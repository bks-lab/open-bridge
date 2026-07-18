"""Starlette-based A2A server for a Bridge-Agent (a2a-sdk 1.x).

a2a-sdk 1.x has no ``A2AStarletteApplication`` wrapper; we compose the JSON-RPC +
agent-card routes into a plain Starlette app. Two separate things, easy to conflate:
``enable_v0_3_compat=True`` covers the JSON-RPC **wire** (0.3 method names), never the
card. The **card** is served at the modern ``/.well-known/agent-card.json`` and at the
legacy ``/.well-known/agent.json`` — the latter a path alias for clients that only know
the old URL, serving the identical v1.0 bytes, not the 0.3 discovery dialect.

Generic: ``build_app(cfg)`` wires runner → executor → routes for any instance.
"""
from __future__ import annotations

import json
import logging

import click
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.agent_card_routes import create_agent_card_routes
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.utils import DEFAULT_RPC_URL

from .card import build_agent_card
from .config import AgentConfig, load_agent_config
from .executor import ClaudeAgentExecutor
from .runner import SubprocessClaudeRunner

logger = logging.getLogger(__name__)

LEGACY_AGENT_CARD_PATH = "/.well-known/agent.json"

# a2a-sdk 1.x serialises every A2AError as the generic JSON-RPC InternalError
# (-32603), dropping the A2A-specific code the spec defines. Map them back.
_A2A_ERROR_CODE_BY_MESSAGE = {
    "Task not found": -32001,
    "Task cannot be canceled": -32002,
    "Push Notification is not supported": -32003,
    "This operation is not supported": -32004,
    "Incompatible content types": -32005,
}


def _restore_a2a_error_code(payload: dict) -> bool:
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict) and err.get("code") == -32603:
        code = _A2A_ERROR_CODE_BY_MESSAGE.get(err.get("message"))
        if code is not None:
            err["code"] = code
            return True
    return False


def _with_spec_error_codes(route: Route) -> Route:
    """Wrap a JSON-RPC route so buffered error responses carry A2A-spec codes."""
    original = route.endpoint

    async def endpoint(request):
        response = await original(request)
        body = getattr(response, "body", None)
        if not body or b'"error"' not in body:
            return response
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            return response
        if _restore_a2a_error_code(payload):
            return JSONResponse(payload, status_code=response.status_code)
        return response

    return Route(route.path, endpoint, methods=list(route.methods or ["POST"]))


def build_app(cfg: AgentConfig) -> Starlette:
    """Wire executor → request handler → routes → Starlette app for ``cfg``."""
    runner = SubprocessClaudeRunner(
        binary=cfg.binary,
        model=cfg.model,
        system_prompt=cfg.system_prompt,
        working_dir=cfg.working_dir,
        extra_read_dirs=cfg.extra_read_dirs,
        timeout=cfg.timeout,
        allowed_tools=cfg.allowed_tools,
        timeout_message=cfg.messages.get(
            "timeout", "The request could not be processed in time. Please try again."
        ),
        empty_message=cfg.messages.get("empty_model", "No answer received from the model."),
        spawn_error_message=cfg.messages.get(
            "spawn_error", "The agent is briefly overloaded. Please try again in a moment."
        ),
    )
    executor = ClaudeAgentExecutor(
        runner=runner,
        max_turns=cfg.max_turns,
        max_concurrency=cfg.max_concurrency,
        max_input_chars=cfg.max_input_chars,
        max_contexts=cfg.max_contexts,
        messages=cfg.messages,
    )
    agent_card = build_agent_card(cfg)

    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    async def health_endpoint(_request):
        return JSONResponse({"status": "ok", "agent": cfg.instance})

    routes = [
        *(
            _with_spec_error_codes(r)
            for r in create_jsonrpc_routes(
                request_handler, DEFAULT_RPC_URL, enable_v0_3_compat=True
            )
        ),
        *create_agent_card_routes(agent_card),  # /.well-known/agent-card.json
        *create_agent_card_routes(agent_card, card_url=LEGACY_AGENT_CARD_PATH),
        Route("/health", health_endpoint, methods=["GET"]),
    ]

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=cfg.cors_origins,
                allow_credentials=False,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type"],
            )
        ],
    )


@click.command()
@click.option("--agent", "instance", required=True, help="Instance name (folder under agents/)")
@click.option("--host", default=None, help="Bind host (overrides agent.yaml / AGENT_HOST)")
@click.option("--port", default=None, type=int, help="Bind port (overrides agent.yaml / AGENT_PORT)")
@click.option("--model", default=None, help="claude model alias (overrides agent.yaml)")
def main(instance: str, host: str | None, port: int | None, model: str | None) -> None:
    """Run a Bridge-Agent — claude -p backend, A2A protocol (a2a-sdk 1.x)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_agent_config(instance)
    if host:
        cfg.host = host
    if port:
        cfg.port = port
    if model:
        cfg.model = model

    app = build_app(cfg)
    logger.info(
        "Starting Bridge-Agent '%s' (%s) on %s:%d — public=%s cwd=%s",
        cfg.instance, cfg.name, cfg.host, cfg.port, cfg.public_url, cfg.working_dir,
    )
    logger.info("CORS origins: %s", cfg.cors_origins)
    print(f"Bridge-Agent '{cfg.instance}' starting at http://{cfg.host}:{cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
