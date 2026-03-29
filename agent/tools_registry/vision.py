from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path

import boto3
from strands import tool

logger = logging.getLogger(__name__)

bedrock_client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2"))
s3_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))

VISION_MODEL = os.environ.get("VISION_MODEL", "us.anthropic.claude-sonnet-4-20250514-v1:0")
SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_SIZE = 20 * 1024 * 1024


def _load_image(source: str) -> tuple[str, str]:
    if source.startswith("s3://"):
        parts = source[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
        content_type = obj.get("ContentType", "image/png")
        media_type = content_type.split(";")[0]
        return base64.b64encode(data).decode("utf-8"), media_type

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {source}")
    if path.stat().st_size > MAX_IMAGE_SIZE:
        raise ValueError(f"Image too large: {path.stat().st_size / 1024 / 1024:.1f}MB (max 20MB)")
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {path.suffix}")

    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    return base64.b64encode(path.read_bytes()).decode("utf-8"), media_types.get(path.suffix.lower(), "image/png")


@tool
def analyze_media(image_source: str, analysis_prompt: str = "Describe what you see in this image in detail.") -> str:
    """Analyze an image using Vision AI (Claude Sonnet with vision capabilities).

    Args:
        image_source: Path to local file or S3 URI (s3://bucket/key)
        analysis_prompt: What to analyze about the image

    Returns:
        AI-generated analysis of the image content
    """
    try:
        image_b64, media_type = _load_image(image_source)

        response = bedrock_client.invoke_model(
            modelId=VISION_MODEL,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                            {"type": "text", "text": analysis_prompt},
                        ],
                    }
                ],
            }),
        )

        result = json.loads(response["body"].read())
        text_blocks = [block["text"] for block in result.get("content", []) if block.get("type") == "text"]
        return "\n".join(text_blocks) or "No analysis generated."

    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        logger.error("Vision analysis failed: %s", e)
        return f"Vision analysis failed: {e}"
