from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

ToolFunc = Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolFunc] = {}

    def register(self, name: str, func: ToolFunc) -> None:
        self._tools[name] = func
        logger.info("Registered tool: %s", name)

    def get(self, name: str) -> ToolFunc | None:
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def invoke(self, name: str, **kwargs: Any) -> Any:
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        return tool(**kwargs)

    @property
    def all_tools(self) -> list[ToolFunc]:
        return list(self._tools.values())
