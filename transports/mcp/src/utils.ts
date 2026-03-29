export function errorResponse(context: string, error: unknown) {
  const msg = error instanceof Error ? error.message : String(error);
  const isAuth = ['credentials', 'expired', 'security token', 'authorize', '401', '403'].some(k => msg.includes(k));
  return {
    content: [{ type: 'text' as const, text: isAuth ? `Auth error (${context}): check credentials.\n${msg}` : `Error ${context}: ${msg}` }],
    isError: true,
  };
}

export function log(tool: string, level: 'info' | 'warn' | 'error', message: string, data?: Record<string, unknown>) {
  const line = `[${new Date().toISOString()}] [mcp:${tool}] [${level.toUpperCase()}] ${message}${data ? ` ${JSON.stringify(data)}` : ''}`;
  console.error(line);
}
