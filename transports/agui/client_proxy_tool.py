from __future__ import annotations

import logging
from typing import Any

from ag_ui.core import Tool as AgUiTool
from strands.tools.registry import ToolRegistry
from strands.tools.tools import PythonAgentTool
from strands.types.tools import ToolResult, ToolSpec, ToolUse

logger = logging.getLogger(__name__)

_PROXY_MARKER = "_agui_proxy"


def create_proxy_tool(ag_ui_tool: AgUiTool) -> PythonAgentTool:
    name = ag_ui_tool.name if isinstance(ag_ui_tool, AgUiTool) else ag_ui_tool.get("name", "")
    description = ag_ui_tool.description if isinstance(ag_ui_tool, AgUiTool) else ag_ui_tool.get("description", "")
    parameters = ag_ui_tool.parameters if isinstance(ag_ui_tool, AgUiTool) else ag_ui_tool.get("parameters", {})

    tool_spec: ToolSpec = {"name": name, "description": description, "inputSchema": {"json": parameters or {}}}

    def _proxy_func(tool_use: ToolUse, **_kwargs: Any) -> ToolResult:
        return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": "Forwarded to client"}]}

    _proxy_func.__name__ = name

    tool = PythonAgentTool(tool_name=name, tool_spec=tool_spec, tool_func=_proxy_func)
    tool.mark_dynamic()
    setattr(tool, _PROXY_MARKER, True)
    return tool


def _is_proxy(tool: Any) -> bool:
    return getattr(tool, _PROXY_MARKER, False) is True


def sync_proxy_tools(tool_registry: ToolRegistry, ag_ui_tools: list[AgUiTool], tracked_names: set[str]) -> set[str]:
    desired = {(t.name if isinstance(t, AgUiTool) else t.get("name", "")) for t in ag_ui_tools} - {""}

    for name in tracked_names - desired:
        existing = tool_registry.registry.get(name)
        if existing is not None and _is_proxy(existing):
            del tool_registry.registry[name]
            tool_registry.dynamic_tools.pop(name, None)

    current: set[str] = set()
    for t in ag_ui_tools:
        n = t.name if isinstance(t, AgUiTool) else t.get("name", "")
        if not n:
            continue
        existing = tool_registry.registry.get(n)
        if existing is not None and not _is_proxy(existing):
            continue
        tool_registry.register_tool(create_proxy_tool(t))
        current.add(n)

    return current
