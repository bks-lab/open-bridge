"""Bridge-Agent runtime — the generic, instance-agnostic core.

A Bridge-Agent is a persistent, addressable entity that fronts one persona to
the outside world over the A2A protocol (Agent2Agent). This package is the
reusable engine; a concrete agent lives in ``agents/<name>/`` and supplies only
its declarative config (``agent.yaml``), persona (``system-prompt.md``) and any
instance-specific tools.

Ported from the proven ``claude -p`` + ``a2a-sdk`` backend; kept free of any
organization-specific content so it can ship as the CORE template.
"""
