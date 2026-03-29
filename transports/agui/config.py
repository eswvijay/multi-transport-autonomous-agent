from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from ag_ui.core import RunAgentInput

StatePayload = dict[str, Any]


@dataclass
class ToolCallContext:
    input_data: RunAgentInput
    tool_name: str
    tool_use_id: str
    tool_input: Any
    args_str: str


@dataclass
class ToolResultContext(ToolCallContext):
    result_data: Any = None
    message_id: str = ""


@dataclass
class PredictStateMapping:
    state_key: str
    tool: str
    tool_argument: str

    def to_payload(self) -> dict[str, str]:
        return {"state_key": self.state_key, "tool": self.tool, "tool_argument": self.tool_argument}


@dataclass
class ToolBehavior:
    skip_messages_snapshot: bool = False
    continue_after_frontend_call: bool = False
    stop_streaming_after_result: bool = False
    predict_state: list[PredictStateMapping] | None = None
    args_streamer: Callable[[ToolCallContext], AsyncIterator[str]] | None = None
    state_from_args: Callable[[ToolCallContext], Awaitable[StatePayload | None] | StatePayload | None] | None = None
    state_from_result: Callable[[ToolResultContext], Awaitable[StatePayload | None] | StatePayload | None] | None = None


@dataclass
class AgUiAgentConfig:
    tool_behaviors: dict[str, ToolBehavior] = field(default_factory=dict)
    state_context_builder: Callable[[RunAgentInput, str], str] | None = None


async def maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def normalize_predict_state(value: list[PredictStateMapping] | None) -> list[PredictStateMapping]:
    return list(value) if value else []
