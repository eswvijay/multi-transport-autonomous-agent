from __future__ import annotations

import logging
import os
import re
from typing import Any

import boto3
from slack_sdk import WebClient

from transports.slack.config import SlackBotConfig

logger = logging.getLogger(__name__)

SLACK_MESSAGE_LIMIT = 4000

_web_client: WebClient | None = None


def _get_client(config: SlackBotConfig) -> WebClient:
    global _web_client
    if _web_client is None:
        _web_client = WebClient(token=config.bot_token)
    return _web_client


def resolve_user_alias(user_id: str, bot_token: str = "") -> tuple[str, str]:
    token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
    try:
        client = WebClient(token=token)
        response = client.users_info(user=user_id)
        profile = response["user"]["profile"]
        return profile.get("display_name") or response["user"]["name"], profile.get("first_name", "there")
    except Exception:
        return user_id, "there"


def post_chunked_reply(config: SlackBotConfig, channel_id: str, thread_ts: str, text: str) -> None:
    client = _get_client(config)
    chunks = [text[i:i + SLACK_MESSAGE_LIMIT] for i in range(0, len(text), SLACK_MESSAGE_LIMIT)]
    for chunk in chunks:
        client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=chunk)


def download_slack_files(files: list[dict[str, Any]], bucket: str) -> list[str]:
    if not bucket:
        return []

    s3 = boto3.client("s3")
    contents: list[str] = []

    for file_info in files:
        url = file_info.get("url_private_download") or file_info.get("url_private")
        if not url:
            continue

        filename = file_info.get("name", "unknown")
        mimetype = file_info.get("mimetype", "")

        try:
            import urllib.request
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as response:
                data = response.read()

            s3_key = f"slack-uploads/{file_info.get('id', 'unknown')}/{filename}"
            s3.put_object(Bucket=bucket, Key=s3_key, Body=data)
            contents.append(f"[Uploaded file: {filename} ({mimetype}) → s3://{bucket}/{s3_key}]")
        except Exception as e:
            logger.warning("File download failed for %s: %s", filename, e)

    return contents
