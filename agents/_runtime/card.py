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
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils import TransportProtocol
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT

from .config import AgentConfig


# Added to the card when ``requests:`` is on (see _runtime/policy.py). Send with
# message metadata ``bridge_request: {"kind": "request", "subject": "..."}`` or
# ``{"kind": "policy"}``.
REQUEST_SKILLS = (
    ("owner_request", "Ask the owner to do something",
     "A request goes to the owner, not to the model. The owner decides, or a rule the owner "
     "set does. Metadata bridge_request {kind: request, subject: <short key>}."),
    ("owner_policy", "Read the rules and history that concern you",
     "Returns the owner's rules for your peer id and your recorded requests. "
     "Metadata bridge_request {kind: policy}."),
)


def _token_description(cfg) -> str:
    if cfg.auth.connector_token:
        text = (
            "Token of the local A2A connector of this Bridge; the connector names the "
            "asker in the X-A2A-Sender header."
        )
        if cfg.auth.peers:
            text += " Direct callers use the per-peer token issued by the operator of this Bridge."
        return text
    return "Per-peer token issued by the operator of this Bridge."


def build_agent_card(cfg: AgentConfig) -> AgentCard:
    skills = [
        AgentSkill(
            id=s["id"],
            name=s.get("name", s["id"]),
            description=s.get("description", "").strip(),
            tags=s.get("tags", []),
            input_modes=s.get("input_modes", ["text"]),
            output_modes=s.get("output_modes", ["text"]),
            examples=s.get("examples", []),
        )
        for s in cfg.skills
    ]
    if cfg.requests.enabled:
        declared = {s.id for s in skills}
        for sid, name, desc in REQUEST_SKILLS:
            if sid not in declared:
                skills.append(AgentSkill(id=sid, name=name, description=desc, tags=["peer"],
                                         input_modes=["text"], output_modes=["text"]))

    provider = None
    if cfg.provider:
        provider = AgentProvider(
            organization=cfg.provider.get("organization", ""),
            url=cfg.provider.get("url", ""),
        )

    # Say what a caller needs before it asks. Only when auth is on: an open agent
    # declaring a scheme it does not enforce would be the dishonest direction.
    security_schemes = {}
    security_requirements = []
    if cfg.auth.enabled:
        security_schemes["bearer"] = SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="Bearer",
                description=_token_description(cfg),
            )
        )
        security_requirements.append(SecurityRequirement(schemes={"bearer": StringList()}))

    return AgentCard(
        name=cfg.name,
        # A folded YAML block (``description: >``) leaves a trailing newline; the
        # card is public self-description, so serve the text without it.
        description=cfg.description.strip(),
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
        security_schemes=security_schemes,
        security_requirements=security_requirements,
    )
