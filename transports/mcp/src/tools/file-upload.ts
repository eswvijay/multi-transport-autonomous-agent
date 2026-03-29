import { z } from 'zod';
import { readFile, stat } from 'node:fs/promises';
import { basename } from 'node:path';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { randomUUID } from 'node:crypto';
import type { Tool } from '../types.js';
import { log, errorResponse } from '../utils.js';

const BUCKET = process.env.ATTACHMENT_BUCKET ?? 'agent-attachments';
const MAX_SIZE = 100 * 1024 * 1024;
const s3 = new S3Client({ region: process.env.AWS_REGION ?? 'us-west-2' });

export const fileUploadTool: Tool<{ file_path: z.ZodString; ticket_id: z.ZodOptional<z.ZodString> }> = {
  name: 'upload-file',
  description: 'Upload a local file to S3 for ticket attachment or agent analysis.',
  paramSchema: {
    file_path: z.string().describe('Absolute path to file'),
    ticket_id: z.string().optional().describe('Ticket ID to attach to'),
  },
  cb: async ({ file_path, ticket_id }) => {
    const filename = basename(file_path);
    log('upload-file', 'info', 'Upload requested', { filename, ticket_id });

    const fileStat = await stat(file_path).catch(() => null);
    if (!fileStat) return errorResponse('upload', new Error(`File not found: ${file_path}`));
    if (fileStat.size > MAX_SIZE) return errorResponse('upload', new Error(`File too large: ${(fileStat.size / 1024 / 1024).toFixed(1)}MB`));

    try {
      const bytes = await readFile(file_path);
      const s3Key = `uploads/${randomUUID().slice(0, 8)}/${filename}`;
      await s3.send(new PutObjectCommand({ Bucket: BUCKET, Key: s3Key, Body: bytes }));
      log('upload-file', 'info', 'Uploaded', { s3Key, bytes: fileStat.size });

      return { content: [{ type: 'text' as const, text: JSON.stringify({ status: 'uploaded', s3Key, filename, sizeBytes: fileStat.size, ticketId: ticket_id ?? null }, null, 2) }] };
    } catch (error) {
      return errorResponse('uploading file', error);
    }
  },
};
