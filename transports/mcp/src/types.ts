import type { ZodRawShape } from 'zod';
import type { ToolCallback } from '@modelcontextprotocol/sdk/server/mcp.js';

export interface Tool<Args extends ZodRawShape> {
  name: string;
  description: string;
  paramSchema: Args;
  cb: ToolCallback<Args>;
}
