from __future__ import annotations

import json
import logging
import os

import boto3
from strands import tool

logger = logging.getLogger(__name__)

KB_MAP = {
    "primary": os.environ.get("PRIMARY_KB_ID", ""),
    "secondary": os.environ.get("SECONDARY_KB_ID", ""),
    "docs": os.environ.get("DOCS_KB_ID", ""),
    "code": os.environ.get("CODE_KB_ID", ""),
}

kb_client = boto3.client("bedrock-agent-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2"))


@tool
def query_knowledge_base(query: str, kb_names: list[str] | None = None) -> str:
    """Search documentation knowledge bases for relevant information.

    Args:
        query: Search query text
        kb_names: Which KBs to search (primary, secondary, docs, code). Defaults to all.

    Returns:
        JSON with relevant documentation excerpts and scores
    """
    targets = kb_names or list(KB_MAP.keys())
    results = []

    for kb_name in targets:
        kb_id = KB_MAP.get(kb_name, "")
        if not kb_id:
            continue
        try:
            response = kb_client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}},
            )
            for r in response.get("retrievalResults", []):
                score = r.get("score", 0)
                if score > 0.5:
                    results.append({
                        "source": kb_name,
                        "score": score,
                        "content": r.get("content", {}).get("text", "")[:500],
                    })
        except Exception as e:
            logger.error("KB query failed for %s: %s", kb_name, e)

    return json.dumps(results, indent=2) if results else "No relevant documentation found."
