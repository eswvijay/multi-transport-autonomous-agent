from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from strands import Agent
from strands.models import BedrockModel
from strands_tools import calculator, http_request

from agent.config import AgentConfig
from agent.gateway import GatewayToolPool
from agent.memory import create_memory_config, SessionManagerWithGuardrails
from agent.security import build_system_prompt, generate_random_token, sanitize_input, wrap_untrusted_input
from agent.session import build_runtime_session_id, parse_runtime_session_id
from agent.tools import BUILTIN_TOOLS
from agent.tools_registry import ALL_AGENT_TOOLS

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 15

gateway_pool = GatewayToolPool()

_global_agent: Agent | None = None
_global_session: str | None = None
_security_token: str | None = None
_system_prompt: str | None = None


def _ensure_security() -> tuple[str, str]:
    global _security_token, _system_prompt
    if _security_token is None:
        _security_token = generate_random_token()
        _system_prompt = build_system_prompt(_security_token)
    return _security_token, _system_prompt  # type: ignore[return-value]


_ensure_security()


async def stream_with_heartbeat(source: AsyncIterator[dict], interval: float = HEARTBEAT_INTERVAL_SECONDS) -> AsyncIterator[dict]:
    source_iter = source.__aiter__()
    exhausted = False
    while not exhausted:
        try:
            event = await asyncio.wait_for(source_iter.__anext__(), timeout=interval)
            yield event
        except asyncio.TimeoutError:
            yield {"heartbeat": True}
            logger.debug("Heartbeat — stream idle for %ss", interval)
        except StopAsyncIteration:
            exhausted = True


def ensure_agent(runtime_session_id: str) -> Agent:
    global _global_agent, _global_session

    if _global_agent is not None:
        if runtime_session_id != _global_session:
            raise ValueError("Container pinned to different session — start a new container or reuse existing session")
        return _global_agent

    token, system_prompt = _ensure_security()
    if not system_prompt:
        raise RuntimeError("Security initialization failed")

    actor_id, session_id = parse_runtime_session_id(runtime_session_id)

    memory_config, memory_region = create_memory_config(actor_id, session_id)
    session_manager = SessionManagerWithGuardrails(
        agentcore_memory_config=memory_config,
        region_name=memory_region,
    )

    config = AgentConfig()
    model = BedrockModel(
        model_id=config.model_id,
        max_tokens=config.max_tokens,
        additional_request_fields={
            "anthropic_beta": ["context-1m-2025-08-07", "output-128k-2025-02-19"],
        },
    )

    agent_tools = [http_request, calculator, *BUILTIN_TOOLS, *ALL_AGENT_TOOLS, *gateway_pool.tools()]

    _global_agent = Agent(
        system_prompt=system_prompt,
        model=model,
        session_manager=session_manager,
        tools=agent_tools,
        callback_handler=None,
    )
    _global_session = runtime_session_id
    return _global_agent


async def invoke_agent(message: str, user_id: str, session_id: str | None = None) -> AsyncIterator[dict]:
    effective_session = session_id or f"session-{user_id}-{id(message)}"
    runtime_sid = build_runtime_session_id(user_id, effective_session)
    agent = ensure_agent(runtime_sid)

    token, _ = _ensure_security()
    sanitized = sanitize_input(message)
    wrapped = wrap_untrusted_input(sanitized, token)

    async for event in stream_with_heartbeat(agent.stream_async(wrapped)):
        yield event


def entrypoint(payload: dict, context: Any = None) -> AsyncIterator[dict]:
    user_message = (payload.get("prompt") or "").strip()
    if not user_message:
        raise ValueError("prompt is required")

    runtime_session_id = getattr(context, "session_id", None) if context else None
    if not runtime_session_id:
        raise ValueError("runtimeSessionId required from runtime context")

    agent = ensure_agent(runtime_session_id)

    token, _ = _ensure_security()
    sanitized = sanitize_input(user_message)
    wrapped = wrap_untrusted_input(sanitized, token)

    return stream_with_heartbeat(agent.stream_async(wrapped))
