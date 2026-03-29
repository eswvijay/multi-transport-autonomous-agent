from __future__ import annotations

import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)

MEMORY_TABLE = os.environ.get("MEMORY_TABLE", "agent-memory")
MAX_HISTORY_LENGTH = 50
GUARDRAIL_MAX_INPUT_LENGTH = 100_000
GUARDRAIL_FORBIDDEN_PATTERNS = ["<script", "javascript:", "data:text/html"]


class AgentCoreMemoryConfig:
    def __init__(self, actor_id: str, session_id: str):
        self.actor_id = actor_id
        self.session_id = session_id
        self.region = os.environ.get("MEMORY_REGION", os.environ.get("AWS_REGION", "us-west-2"))


def create_memory_config(actor_id: str, session_id: str) -> tuple[AgentCoreMemoryConfig, str]:
    config = AgentCoreMemoryConfig(actor_id, session_id)
    return config, config.region


class SessionManagerWithGuardrails:
    def __init__(self, agentcore_memory_config: AgentCoreMemoryConfig, region_name: str):
        self._config = agentcore_memory_config
        self._region = region_name
        self._dynamodb = boto3.resource("dynamodb", region_name=region_name)
        self._table = self._dynamodb.Table(MEMORY_TABLE)
        self._session_id = f"{agentcore_memory_config.actor_id}___{agentcore_memory_config.session_id}"

    def read_session(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return self.load_history()

    def write_session(self, session_id: str | None = None, messages: list[dict[str, Any]] | None = None) -> None:
        self.save_history(messages or [])

    def apply_guardrails(self, message: str) -> str:
        if len(message) > GUARDRAIL_MAX_INPUT_LENGTH:
            logger.warning("Input exceeds max length (%d > %d), truncating", len(message), GUARDRAIL_MAX_INPUT_LENGTH)
            message = message[:GUARDRAIL_MAX_INPUT_LENGTH]

        message_lower = message.lower()
        for pattern in GUARDRAIL_FORBIDDEN_PATTERNS:
            if pattern in message_lower:
                logger.warning("Forbidden pattern detected: %s", pattern)
                message = message.replace(pattern, "[REDACTED]")

        return message

    def load_history(self) -> list[dict[str, Any]]:
        try:
            response = self._table.get_item(
                Key={"actor_id": self._config.actor_id, "session_id": self._config.session_id}
            )
            item = response.get("Item")
            return item.get("history", []) if item else []
        except Exception as e:
            logger.warning("Failed to load history: %s", e)
            return []

    def save_history(self, history: list[dict[str, Any]]) -> None:
        trimmed = history[-MAX_HISTORY_LENGTH:]
        try:
            self._table.put_item(
                Item={
                    "actor_id": self._config.actor_id,
                    "session_id": self._config.session_id,
                    "history": trimmed,
                }
            )
        except Exception as e:
            logger.error("Failed to save history: %s", e)
