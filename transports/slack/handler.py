from __future__ import annotations

import json
import re

from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

from transports.slack.runtime_client import invoke_runtime
from transports.slack.config import get_config
from transports.slack.session_store import get_session, put_session
from transports.slack.slack_client import download_slack_files, post_chunked_reply, resolve_user_alias

import logging

logger = logging.getLogger(__name__)

BOT_MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>")


def strip_bot_mentions(text: str) -> str:
    return BOT_MENTION_PATTERN.sub("", text).strip()


def extract_event_data(event: dict) -> dict:
    records = event.get("Records", [])
    body = json.loads(records[0]["body"])
    return body.get("event", body)


def handler(event: dict, context: LambdaContext) -> None:
    config = get_config()
    event_data = extract_event_data(event)

    channel_id = event_data.get("channel", "")
    user_id = event_data.get("user", "")
    raw_text = event_data.get("text", "")
    thread_ts = event_data.get("thread_ts", event_data.get("ts", ""))

    if user_id in config.bot_user_ids:
        logger.info("Ignoring bot message from %s", user_id)
        return

    text = strip_bot_mentions(raw_text)

    files = event_data.get("files", [])
    if files:
        file_contents = download_slack_files(files, bucket=config.attachment_temp_bucket)
        text = (text + "\n\n" + "\n\n".join(file_contents)) if text else "\n\n".join(file_contents)
        logger.info("Attached %d files to prompt", len(file_contents))

    if not text:
        logger.info("Empty message after stripping mentions")
        return

    alias, first_name = resolve_user_alias(user_id, config.bot_token)
    logger.info("Processing message from %s (%s) in channel %s", alias, first_name, channel_id)

    existing_session = get_session(config.session_table_name, channel_id, thread_ts)

    try:
        result = invoke_runtime(config, text, alias, existing_session)
    except RuntimeError:
        logger.exception("Agent invocation failed for %s", alias)
        post_chunked_reply(config, channel_id, thread_ts, f"Sorry {first_name}, I encountered an error. Please try again.")
        return

    put_session(config.session_table_name, channel_id, thread_ts, result["session_id"])
    post_chunked_reply(config, channel_id, thread_ts, result["response"])
    logger.info("Reply sent for %s session=%s", alias, result["session_id"])
