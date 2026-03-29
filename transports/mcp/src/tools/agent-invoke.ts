import { z } from 'zod';
import https from 'node:https';
import { SignatureV4 } from '@smithy/signature-v4';
import { HttpRequest } from '@smithy/protocol-http';
import { Sha256 } from '@aws-crypto/sha256-js';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import type { Tool } from '../types.js';
import { log } from '../utils.js';

const RUNTIME_ARN = process.env.RUNTIME_ARN ?? '';
const REGION = process.env.RUNTIME_REGION ?? 'us-west-2';
const HOST = `bedrock-agentcore.${REGION}.amazonaws.com`;
const INACTIVITY_TIMEOUT_MS = 120_000;
const TOTAL_TIMEOUT_MS = 600_000;

const RUNTIME_ID = RUNTIME_ARN.split('/').pop() ?? '';

const WRITE_PATTERNS: RegExp[] = [
  /\byes\b.*\bcreate\b/i, /\bcreate\b.*\b(ticket|issue)\b/i,
  /\bupdate\b.*\b(ticket|issue)\b/i, /\bresolve\b.*\b(ticket|issue)\b/i,
  /\bclose\b.*\b(ticket|issue)\b/i, /\badd\s+comment\b/i,
];

export const detectWriteIntent = (msg: string): boolean => WRITE_PATTERNS.some(p => p.test(msg));

const parseSSE = (body: string): string =>
  body.split('\n')
    .filter(l => l.startsWith('data: '))
    .map(l => { try { return JSON.parse(l.slice(6))?.event?.contentBlockDelta?.delta?.text; } catch { return null; } })
    .filter((t): t is string => typeof t === 'string')
    .join('');

const buildSessionId = (userId: string, sessionId?: string): string => {
  const s = sessionId ?? `mcp-session-${Date.now()}`;
  const candidate = `${userId}___${s}`;
  return candidate.length >= 33 ? candidate : `${userId}___sessionid-${s}`;
};

async function invokeRuntime(message: string, userId: string, sessionId?: string): Promise<{ response: string; sessionId: string }> {
  const runtimeSessionId = buildSessionId(userId, sessionId);
  const payload = JSON.stringify({ prompt: message });

  const httpRequest = new HttpRequest({
    method: 'POST', hostname: HOST, path: `/runtimes/${RUNTIME_ID}/invocations`,
    query: { qualifier: 'DEFAULT' },
    headers: { 'Content-Type': 'application/octet-stream', Host: HOST, 'x-amzn-bedrock-agentcore-runtime-session-id': runtimeSessionId },
    body: payload,
  });

  const signer = new SignatureV4({ service: 'bedrock-agentcore', region: REGION, credentials: defaultProvider({ ignoreCache: true }), sha256: Sha256 });
  const signed = await signer.sign(httpRequest);
  const fullPath = signed.query ? `${signed.path}?${Object.entries(signed.query).map(([k, v]) => `${encodeURIComponent(String(k))}=${encodeURIComponent(String(v))}`).join('&')}` : signed.path;

  return new Promise((resolve, reject) => {
    const req = https.request({ hostname: HOST, path: fullPath, method: 'POST', headers: signed.headers as Record<string, string> }, (res) => {
      let body = '';
      const timer = setTimeout(() => { req.destroy(); reject(new Error(`Total timeout ${TOTAL_TIMEOUT_MS / 1000}s`)); }, TOTAL_TIMEOUT_MS);
      res.on('data', (c: Buffer) => { body += c.toString(); });
      res.on('end', () => { clearTimeout(timer); res.statusCode !== 200 ? reject(new Error(`${res.statusCode}: ${body.slice(0, 500)}`)) : resolve({ response: parseSSE(body) || 'No response.', sessionId: runtimeSessionId.split('___').pop()! }); });
    });
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

export const agentInvokeTool: Tool<{ message: z.ZodString; session_id: z.ZodOptional<z.ZodString>; confirm_write: z.ZodOptional<z.ZodBoolean> }> = {
  name: 'ask-agent',
  description: 'Ask the autonomous agent a question using internal knowledge bases. Supports multi-turn via session_id. Set confirm_write=true for write operations after user approval.',
  paramSchema: {
    message: z.string().describe('Your question'),
    session_id: z.string().optional().describe('Session ID for follow-ups'),
    confirm_write: z.boolean().optional().describe('Required for write ops after user approval'),
  },
  cb: async ({ message, session_id, confirm_write }) => {
    if (detectWriteIntent(message) && confirm_write !== true) {
      return { content: [{ type: 'text' as const, text: 'BLOCKED: Write intent detected. Present action to user and retry with confirm_write=true after approval.' }], isError: true };
    }
    const userId = process.env.USER ?? 'mcp-user';
    log('ask-agent', 'info', 'Invoking', { userId, hasSession: !!session_id });
    try {
      const result = await invokeRuntime(message, userId, session_id);
      return { content: [{ type: 'text' as const, text: JSON.stringify({ response: result.response, sessionId: result.sessionId, provider: 'agentcore-direct' }, null, 2) }] };
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      log('ask-agent', 'error', 'Failed', { error: msg });
      return { content: [{ type: 'text' as const, text: `Error: ${msg}` }], isError: true };
    }
  },
};
