import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { agentInvokeTool } from './tools/agent-invoke.js';
import { jiraSearchTool } from './tools/search.js';
import { logAnalyzerTool } from './tools/log-analyzer.js';
import { fileUploadTool } from './tools/file-upload.js';

export const server = new McpServer(
  { name: 'agent-mcp-server', version: '1.0.0' },
  {
    capabilities: { tools: {}, prompts: {} },
    instructions:
      'Multi-transport autonomous agent MCP interface. Provides tools for AI agent invocation, Jira search, device log analysis, and file upload.\n\n' +
      'WRITE SAFETY: ask-agent can perform write operations. You MUST present intended actions to the user and get explicit approval before setting confirm_write=true.',
  },
);

const tools = [agentInvokeTool, jiraSearchTool, logAnalyzerTool, fileUploadTool];
tools.forEach((t) => server.tool(t.name, t.description, t.paramSchema, t.cb));
