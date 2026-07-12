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
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=skills,
    )
