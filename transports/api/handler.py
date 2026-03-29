from __future__ import annotations

import json
import logging
from typing import Any

from agent.agent import invoke_agent

logger = logging.getLogger(__name__)


async def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    body = json.loads(event.get("body", "{}")) if isinstance(event.get("body"), str) else event.get("body", {})

    message = body.get("message", "")
    user_id = body.get("user_id", "api-user")
    session_id = body.get("session_id")

    if not message:
        return {"statusCode": 400, "body": json.dumps({"error": "message is required"})}

    try:
        chunks: list[str] = []
        async for event_data in invoke_agent(message, user_id, session_id):
            data = event_data.get("data")
            if isinstance(data, str):
                chunks.append(data)

        response_text = "".join(chunks) or "No response generated."
        return {
            "statusCode": 200,
            "body": json.dumps({"response": response_text, "user_id": user_id}),
            "headers": {"Content-Type": "application/json"},
        }
    except Exception as e:
        logger.exception("API handler error")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
