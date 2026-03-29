from __future__ import annotations

import json
import logging
import os

import requests
from strands import tool

logger = logging.getLogger(__name__)

FORUM_BASE = os.environ.get("FORUM_API_BASE", "https://community.example.com")
FORUM_API_KEY = os.environ.get("FORUM_API_KEY", "")


def _forum_headers() -> dict[str, str]:
    return {"Api-Key": FORUM_API_KEY, "Api-Username": "system", "Content-Type": "application/json"}


@tool
def get_forum_topic(topic_id: int) -> str:
    """Get detailed information about a specific forum topic.

    Args:
        topic_id: Numeric ID of the forum topic

    Returns:
        JSON with topic title, posts, creation date, and reply count
    """
    try:
        response = requests.get(f"{FORUM_BASE}/t/{topic_id}.json", headers=_forum_headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        posts = [
            {"author": p.get("username", ""), "content": p.get("cooked", "")[:500], "created": p.get("created_at", "")}
            for p in data.get("post_stream", {}).get("posts", [])[:10]
        ]
        return json.dumps({
            "id": data.get("id"),
            "title": data.get("title", ""),
            "created": data.get("created_at", ""),
            "replies": data.get("reply_count", 0),
            "views": data.get("views", 0),
            "posts": posts,
        }, indent=2)
    except Exception as e:
        return f"Forum topic fetch failed: {e}"


@tool
def search_forum_topics(query: str, category_id: int | None = None) -> str:
    """Search forum topics by keyword.

    Args:
        query: Search query
        category_id: Optional category ID to filter by

    Returns:
        JSON with matching topics
    """
    try:
        params = {"q": query}
        if category_id:
            params["category_id"] = str(category_id)
        response = requests.get(f"{FORUM_BASE}/search.json", params=params, headers=_forum_headers(), timeout=15)
        response.raise_for_status()
        data = response.json()
        topics = [
            {"id": t.get("id"), "title": t.get("title", ""), "slug": t.get("slug", ""), "views": t.get("views", 0)}
            for t in data.get("topics", [])[:15]
        ]
        return json.dumps({"query": query, "count": len(topics), "topics": topics}, indent=2)
    except Exception as e:
        return f"Forum search failed: {e}"


@tool
def get_forum_stats() -> str:
    """Get overall forum statistics including user count, topic count, and post count.

    Returns:
        JSON with forum-wide statistics
    """
    try:
        response = requests.get(f"{FORUM_BASE}/about.json", headers=_forum_headers(), timeout=15)
        response.raise_for_status()
        data = response.json().get("about", {}).get("stats", {})
        return json.dumps({
            "topics": data.get("topic_count", 0),
            "posts": data.get("post_count", 0),
            "users": data.get("user_count", 0),
            "active_users_7d": data.get("active_users_7_days", 0),
        }, indent=2)
    except Exception as e:
        return f"Forum stats failed: {e}"
