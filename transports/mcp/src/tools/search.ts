import { z } from 'zod';
import type { Tool } from '../types.js';

const JIRA_API_BASE = process.env.JIRA_API_BASE ?? 'https://jira.example.com/rest/api/2';

export const jiraSearchTool: Tool<{ jql: z.ZodString; limit: z.ZodOptional<z.ZodNumber> }> = {
  name: 'jira-search',
  description: 'Search Jira issues using JQL. Returns matching issues with key, summary, status, assignee.',
  paramSchema: {
    jql: z.string().describe('JQL query'),
    limit: z.number().optional().describe('Max results (default 20)'),
  },
  cb: async ({ jql, limit = 20 }) => {
    try {
      const response = await fetch(`${JIRA_API_BASE}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${process.env.JIRA_TOKEN ?? ''}` },
        body: JSON.stringify({ jql, maxResults: limit }),
      });
      if (!response.ok) throw new Error(`Jira API ${response.status}`);
      const data = await response.json() as { issues?: unknown[]; total?: number };
      return { content: [{ type: 'text' as const, text: JSON.stringify({ total: data.total ?? 0, returned: (data.issues ?? []).length, issues: data.issues ?? [] }, null, 2) }] };
    } catch (error) {
      return { content: [{ type: 'text' as const, text: `Jira search error: ${error instanceof Error ? error.message : error}` }], isError: true };
    }
  },
};
