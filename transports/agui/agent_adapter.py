from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncIterator

from strands import Agent as StrandsAgent

from ag_ui.core import (
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from transports.agui.config import AgUiAgentConfig, ToolCallContext, ToolResultContext, maybe_await, normalize_predict_state
from transports.agui.client_proxy_tool import sync_proxy_tools

logger = logging.getLogger(__name__)


class AgUiAgentAdapter:
    def __init__(self, agent: StrandsAgent, name: str, description: str = "", config: AgUiAgentConfig | None = None):
        self._model = agent.model
        self._system_prompt = agent.system_prompt
        self._tools = list(agent.tool_registry.registry.values()) if hasattr(agent, "tool_registry") else []
        self._agent_kwargs = {"record_direct_tool_call": getattr(agent, "record_direct_tool_call", True)}

        self.name = name
        self.description = description
        self.config = config or AgUiAgentConfig()
        self._agents_by_thread: dict[str, StrandsAgent] = {}
        self._proxy_tools_by_thread: dict[str, set[str]] = {}

    async def run(self, input_data: RunAgentInput) -> AsyncIterator[Any]:
        thread_id = input_data.thread_id or "default"
        if thread_id not in self._agents_by_thread:
            self._agents_by_thread[thread_id] = StrandsAgent(
                model=self._model,
                system_prompt=self._system_prompt,
                tools=self._tools,
                **self._agent_kwargs,
            )
        strands_agent = self._agents_by_thread[thread_id]

        if input_data.tools:
            proxy_names = sync_proxy_tools(
                strands_agent.tool_registry, input_data.tools, self._proxy_tools_by_thread.get(thread_id, set())
            )
            self._proxy_tools_by_thread[thread_id] = proxy_names

        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input_data.thread_id, run_id=input_data.run_id)

        try:
            if hasattr(input_data, "state") and input_data.state is not None:
                state_snapshot = {k: v for k, v in input_data.state.items() if k != "messages"}
                yield StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=state_snapshot)

            frontend_tool_names = {
                (t.get("name") if isinstance(t, dict) else getattr(t, "name", None))
                for t in (input_data.tools or [])
            } - {None}

            user_message = "Hello"
            for msg in reversed(input_data.messages):
                if msg.role in ("user", "tool") and msg.content:
                    user_message = msg.content
                    break

            if self.config.state_context_builder:
                try:
                    user_message = self.config.state_context_builder(input_data, user_message)
                except Exception as e:
                    logger.warning(f"State context builder failed: {e}")

            message_id = str(uuid.uuid4())
            message_started = False
            tool_calls_seen: dict[str, dict] = {}

            agent_stream = strands_agent.stream_async(user_message)
            try:
              async for event in agent_stream:
                if event.get("init_event_loop") or event.get("start_event_loop"):
                    continue
                if event.get("complete") or event.get("force_stop"):
                    break

                if "data" in event and event["data"]:
                    if not message_started:
                        yield TextMessageStartEvent(type=EventType.TEXT_MESSAGE_START, message_id=message_id, role="assistant")
                        message_started = True
                    yield TextMessageContentEvent(type=EventType.TEXT_MESSAGE_CONTENT, message_id=message_id, delta=str(event["data"]))

                elif "current_tool_use" in event and event["current_tool_use"]:
                    tool_use = event["current_tool_use"]
                    tool_name = tool_use.get("name")
                    tool_use_id = tool_use.get("toolUseId") or str(uuid.uuid4())
                    tool_input = tool_use.get("input", {})
                    args_str = json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)

                    if tool_name and tool_use_id not in tool_calls_seen:
                        tool_calls_seen[tool_use_id] = {"name": tool_name, "args": args_str, "input": tool_input, "emitted": False}

                elif "event" in event and isinstance(event.get("event"), dict):
                    inner = event["event"]
                    if "contentBlockStop" in inner:
                        for tid, tdata in tool_calls_seen.items():
                            if tdata.get("emitted"):
                                continue
                            tdata["emitted"] = True
                            yield ToolCallStartEvent(type=EventType.TOOL_CALL_START, tool_call_id=tid, tool_call_name=tdata["name"], parent_message_id=message_id)
                            yield ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS, tool_call_id=tid, delta=tdata["args"])
                            yield ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tid)

                            if tdata["name"] in frontend_tool_names:
                                break

                elif "message" in event and event["message"].get("role") == "user":
                    for item in event["message"].get("content", []):
                        if not isinstance(item, dict) or "toolResult" not in item:
                            continue
                        result = item["toolResult"]
                        result_id = result.get("toolUseId")
                        content_parts = result.get("content", [])
                        result_text = next((c["text"] for c in content_parts if isinstance(c, dict) and "text" in c), None)
                        if result_id and result_text:
                            yield ToolCallResultEvent(type=EventType.TOOL_CALL_RESULT, tool_call_id=result_id, message_id=message_id, content=result_text)

            finally:
                try:
                    await agent_stream.aclose()
                except (GeneratorExit, ValueError, RuntimeError, StopAsyncIteration):
                    pass
                except Exception as close_err:
                    logger.warning(f"Error closing agent stream: {close_err}")

            if message_started:
                yield TextMessageEndEvent(type=EventType.TEXT_MESSAGE_END, message_id=message_id)

            yield RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=input_data.thread_id, run_id=input_data.run_id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code="AGENT_ERROR")
