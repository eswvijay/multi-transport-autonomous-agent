from __future__ import annotations

import importlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

GATEWAY_MODULES_ENV = "GATEWAY_TOOL_MODULES"


class GatewayToolPool:
    def __init__(self):
        self._tools: list[Any] = []
        self._load_from_env()

    def _load_from_env(self) -> None:
        module_paths = os.environ.get(GATEWAY_MODULES_ENV, "")
        if not module_paths:
            return

        for module_path in module_paths.split(","):
            module_path = module_path.strip()
            if not module_path:
                continue
            try:
                mod = importlib.import_module(module_path)
                exported_tools = getattr(mod, "tools", getattr(mod, "TOOLS", []))
                self._tools.extend(exported_tools)
                logger.info("Loaded %d tools from gateway module: %s", len(exported_tools), module_path)
            except ImportError as e:
                logger.warning("Failed to load gateway module %s: %s", module_path, e)

    def register(self, tool: Any) -> None:
        self._tools.append(tool)

    def tools(self) -> list[Any]:
        return list(self._tools)
