from __future__ import annotations

import json
import logging
import os

import requests
from strands import tool

logger = logging.getLogger(__name__)

JIRA_BASE = os.environ.get("JIRA_API_BASE", "https://jira.example.com/rest/api/2")
JIRA_TOKEN = os.environ.get("JIRA_TOKEN", "")


def _jira_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {JIRA_TOKEN}", "Content-Type": "application/json"}


@tool
def search_jira(jql: str, max_results: int = 20) -> str:
    """Search Jira issues using JQL query.

    Args:
        jql: JQL query string
        max_results: Maximum results to return

    Returns:
        JSON with matching issues
    """
    try:
        response = requests.post(
            f"{JIRA_BASE}/search",
            json={"jql": jql, "maxResults": max_results},
            headers=_jira_headers(),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        issues = [
            {
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"].get("status", {}).get("name", ""),
                "priority": i["fields"].get("priority", {}).get("name", ""),
                "assignee": (i["fields"].get("assignee") or {}).get("displayName", "Unassigned"),
            }
            for i in data.get("issues", [])
        ]
        return json.dumps({"total": data.get("total", 0), "issues": issues}, indent=2)
    except Exception as e:
        return f"Jira search failed: {e}"


@tool
def create_jira_issue(project: str, summary: str, description: str, issue_type: str = "Bug", priority: str = "Medium") -> str:
    """Create a new Jira issue.

    Args:
        project: Project key (e.g., PROJ)
        summary: Issue title
        description: Detailed description
        issue_type: Type of issue (Bug, Task, Story)
        priority: Priority level (Critical, High, Medium, Low)

    Returns:
        JSON with created issue key and URL
    """
    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
    }
    try:
        response = requests.post(f"{JIRA_BASE}/issue", json=payload, headers=_jira_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        return json.dumps({"key": data["key"], "id": data["id"], "url": f"{JIRA_BASE.replace('/rest/api/2', '')}/browse/{data['key']}"})
    except Exception as e:
        return f"Jira create failed: {e}"
