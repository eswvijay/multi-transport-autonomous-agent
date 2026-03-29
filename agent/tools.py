from __future__ import annotations

from strands import tool


@tool
def health_check() -> str:
    """Verify agent connectivity and tool execution capability."""
    return "Agent operational — all systems healthy"


BUILTIN_TOOLS = [health_check]
