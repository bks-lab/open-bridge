"""bridge-gateway — thin, stateless MCP→A2A gateway.

MCP clients (Claude, ChatGPT Dev Mode, Gemini) call three tools; the gateway
translates them onto the A2A wire of registered bridge agents. Pure translation
layer: no model, no reasoning, no persistent state. See SPEC.md.
"""
