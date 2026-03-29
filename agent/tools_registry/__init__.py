from agent.tools_registry.registry import ToolRegistry
from agent.tools_registry.kb_query import query_knowledge_base
from agent.tools_registry.jira_ops import create_jira_issue, search_jira
from agent.tools_registry.forum import get_forum_topic, search_forum_topics, get_forum_stats
from agent.tools_registry.vision import analyze_media

ALL_AGENT_TOOLS = [
    query_knowledge_base,
    create_jira_issue,
    search_jira,
    get_forum_topic,
    search_forum_topics,
    get_forum_stats,
    analyze_media,
]
