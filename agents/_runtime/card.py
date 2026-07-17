"""Build an A2A ``AgentCard`` from a Bridge-Agent's declarative config.

a2a-sdk 1.x types are protobuf, snake_case; the single ``url`` field became
``supported_interfaces`` (a list of ``AgentInterface``). The card is the agent's
honest self-description — only advertise skills the prompt + tools implement.
"""
from __future__ import annotations

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
)
from a2a.utils import TransportProtocol
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

from .config import AgentConfig


def build_agent_card(cfg: AgentConfig) -> AgentCard:
    skills = [
        AgentSkill(
            id=s["id"],
            name=s.get("name", s["id"]),
            description=s.get("description", ""),
            tags=s.get("tags", []),
            input_modes=s.get("input_modes", ["text"]),
            output_modes=s.get("output_modes", ["text"]),
            examples=s.get("examples", []),
        )
        for s in cfg.skills
    ]

    provider = None
    if cfg.provider:
        provider = AgentProvider(
            organization=cfg.provider.get("organization", ""),
            url=cfg.provider.get("url", ""),
        )

    return AgentCard(
        name=cfg.name,
        description=cfg.description,
        version=cfg.version,
        provider=provider,
        documentation_url=cfg.documentation_url,
        icon_url=cfg.icon_url,
        supported_interfaces=[
            AgentInterface(
                url=f"{cfg.public_url}/",
                protocol_binding=TransportProtocol.JSONRPC,
                # Say which A2A version this interface speaks. Not optional in practice:
                # with it absent the SDK's v0_3-compat layer serves the whole card in the
                # LEGACY dialect (top-level ``protocolVersion: "0.3"`` + ``preferredTransport``),
                # so every agent built on this runtime advertised 0.3 while running a v1.0
                # SDK. A client reading the v1.0 location then sees no version at all —
                # which is how one upgraded peer silently dropped out of a live mesh.
                # The server keeps enable_v0_3_compat=True, so 0.3 clients still work.
                protocol_version=PROTOCOL_VERSION_CURRENT,
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
    )
