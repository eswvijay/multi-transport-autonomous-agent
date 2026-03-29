from __future__ import annotations

import json
import logging
import ssl
import urllib.request
import urllib.error

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session

from transports.slack.config import SlackBotConfig

logger = logging.getLogger(__name__)

MIN_SESSION_ID_LENGTH = 33


def build_runtime_session_id(alias: str, session_id: str) -> str:
    candidate = f"{alias}___{session_id}"
    return candidate if len(candidate) >= MIN_SESSION_ID_LENGTH else f"{alias}___sessionid-{session_id}"


def extract_session_id(runtime_session_id: str) -> str:
    idx = runtime_session_id.rfind("___")
    return runtime_session_id[idx + 3:] if idx != -1 else runtime_session_id


def parse_sse_response(body: str) -> str:
    parts: list[str] = []
    for line in body.split("\n"):
        if not line.startswith("data: "):
            continue
        raw = line[6:].strip()
        if not raw or raw.startswith('"'):
            continue
        try:
            parsed = json.loads(raw)
            text = parsed.get("event", {}).get("contentBlockDelta", {}).get("delta", {}).get("text")
            if isinstance(text, str):
                parts.append(text)
        except (json.JSONDecodeError, AttributeError):
            continue
    return "".join(parts)


def invoke_runtime(config: SlackBotConfig, message: str, alias: str, session_id: str | None) -> dict[str, str]:
    effective_session = session_id or f"slack-{alias}-{id(message)}"
    runtime_session_id = build_runtime_session_id(alias, effective_session)

    payload = json.dumps({"prompt": message}).encode("utf-8")
    path = f"/runtimes/{config.runtime_id}/invocations"
    query = f"qualifier=DEFAULT&accountId={config.account_id}"
    url = f"https://{config.host}{path}?{query}"

    headers = {
        "Content-Type": "application/octet-stream",
        "Host": config.host,
        "x-amzn-bedrock-agentcore-runtime-session-id": runtime_session_id,
    }

    aws_request = AWSRequest(method="POST", url=url, data=payload, headers=headers)
    credentials = Session().get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, config.service, config.region).add_auth(aws_request)

    req = urllib.request.Request(url=url, data=payload, headers=dict(aws_request.headers), method="POST")
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=config.total_timeout_seconds, context=ctx) as resp:
            chunks: list[str] = []
            while True:
                try:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    chunks.append(chunk.decode("utf-8", errors="replace"))
                except Exception as read_exc:
                    from http.client import IncompleteRead
                    if isinstance(read_exc, IncompleteRead) and read_exc.partial:
                        logger.warning("IncompleteRead — using partial data (%d bytes)", len(read_exc.partial))
                        chunks.append(read_exc.partial.decode("utf-8", errors="replace"))
                    break
            body = "".join(chunks)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Runtime returned {exc.code}: {error_body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Runtime connection error: {exc.reason}") from exc

    text = parse_sse_response(body)
    return {"response": text or "No response generated.", "session_id": extract_session_id(runtime_session_id)}
