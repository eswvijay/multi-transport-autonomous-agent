from __future__ import annotations

import logging
import time

import boto3

logger = logging.getLogger(__name__)

_dynamodb = boto3.resource("dynamodb")
SESSION_TTL_SECONDS = 86400


def get_session(table_name: str, channel_id: str, thread_ts: str) -> str | None:
    table = _dynamodb.Table(table_name)
    try:
        response = table.get_item(Key={"channel_id": channel_id, "thread_ts": thread_ts})
        item = response.get("Item")
        return item["session_id"] if item else None
    except Exception as e:
        logger.warning("Session lookup failed: %s", e)
        return None


def put_session(table_name: str, channel_id: str, thread_ts: str, session_id: str) -> None:
    table = _dynamodb.Table(table_name)
    try:
        table.put_item(
            Item={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "session_id": session_id,
                "ttl": int(time.time()) + SESSION_TTL_SECONDS,
            }
        )
    except Exception as e:
        logger.error("Session save failed: %s", e)
