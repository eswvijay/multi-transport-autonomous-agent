from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

MIN_SESSION_ID_LENGTH = 33


class SessionManager(Protocol):
    def get_session(self, actor_id: str, session_id: str) -> dict: ...
    def save_session(self, actor_id: str, session_id: str, data: dict) -> None: ...


def build_runtime_session_id(actor_id: str, session_id: str) -> str:
    candidate = f"{actor_id}___{session_id}"
    return candidate if len(candidate) >= MIN_SESSION_ID_LENGTH else f"{actor_id}___sessionid-{session_id}"


def extract_session_id(runtime_session_id: str) -> str:
    separator = runtime_session_id.rfind("___")
    return runtime_session_id[separator + 3:] if separator != -1 else runtime_session_id


def parse_runtime_session_id(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or "___" not in raw:
        raise ValueError("runtimeSessionId must be '<actorId>___<sessionId>'")
    actor_id, session_id = raw.split("___", 1)
    actor_id, session_id = actor_id.strip(), session_id.strip()
    if not actor_id or not session_id:
        raise ValueError("Both actorId and sessionId must be non-empty")
    return actor_id, session_id
