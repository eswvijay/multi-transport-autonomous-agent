from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentConfig:
    model_id: str = field(default_factory=lambda: os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6"))
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-west-2"))
    host: str = field(default_factory=lambda: os.environ.get("AGENT_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.environ.get("AGENT_PORT", "8080")))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("MAX_TOKENS", "64000")))
    runtime_arn: str = field(default_factory=lambda: os.environ.get("RUNTIME_ARN", ""))
    runtime_region: str = field(default_factory=lambda: os.environ.get("RUNTIME_REGION", "us-west-2"))
    runtime_host: str = field(default_factory=lambda: f"bedrock-agentcore.{os.environ.get('RUNTIME_REGION', 'us-west-2')}.amazonaws.com")

    @property
    def runtime_id(self) -> str:
        segment = self.runtime_arn.split("/")
        return segment[-1] if segment else ""
