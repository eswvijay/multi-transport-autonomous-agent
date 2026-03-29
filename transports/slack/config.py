from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlackBotConfig:
    bot_token: str = field(default_factory=lambda: os.environ.get("SLACK_BOT_TOKEN", ""))
    bot_user_ids: frozenset[str] = field(default_factory=lambda: frozenset(os.environ.get("BOT_USER_IDS", "").split(",")))
    session_table_name: str = field(default_factory=lambda: os.environ.get("SESSION_TABLE", "agent-slack-sessions"))
    attachment_temp_bucket: str = field(default_factory=lambda: os.environ.get("ATTACHMENT_BUCKET", ""))
    runtime_arn: str = field(default_factory=lambda: os.environ.get("RUNTIME_ARN", ""))
    account_id: str = field(default_factory=lambda: os.environ.get("ACCOUNT_ID", ""))
    region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-west-2"))
    service: str = "bedrock-agentcore"
    total_timeout_seconds: int = 600

    @property
    def host(self) -> str:
        return f"{self.service}.{self.region}.amazonaws.com"

    @property
    def runtime_id(self) -> str:
        parts = self.runtime_arn.split("/")
        return parts[-1] if parts else ""


_config: SlackBotConfig | None = None


def get_config() -> SlackBotConfig:
    global _config
    if _config is None:
        _config = SlackBotConfig()
    return _config
