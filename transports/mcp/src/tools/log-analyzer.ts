import { readFileSync } from 'fs';
import { z } from 'zod';
import type { Tool } from '../types.js';

const CRASH = [/FATAL EXCEPTION|AndroidRuntime.*FATAL/i, /Process.*crashed|died.*fore|died.*back/i, /SIGABRT|SIGSEGV|SIGKILL|SIGTERM|SIGBUS/i, /TypeError:|ReferenceError:|SyntaxError:|RangeError:/i, /Uncaught.*Error|Unhandled.*Error|Fatal.*Error/i, /Process.*terminated|Process.*killed/i, /Forcefully terminating process.*AppNotResponding/i, /KeplerScriptThreadMonitor.*Requesting application termination/i, /Thread.*detected to be unresponsive.*invoking.*expiry/i];
const ANR = [/ANR in|Application Not Responding|Input dispatching timed out/i, /watchdog.*timeout|watchdog.*expired/i, /main thread.*blocked|ui thread.*blocked/i, /deadlock.*detected|thread.*deadlock/i, /thread-monitor.*detected to be unresponsive/i];
const NETWORK = [/network.*error|connection.*failed|socket.*error|dns.*error/i, /http.*error|ssl.*error|certificate.*error|handshake.*failed/i, /connection.*timeout|network.*timeout/i];
const DRM = [/drm.*error|license.*error|widevine.*error|playready.*error/i, /drm.*license.*expired|license.*renewal.*failed/i];
const PERF = [/timeout|slow|lag|delay|memory.*low|gc.*pause/i, /buffer.*underrun|frame.*drop|skip.*frame|jank/i, /commitTime.*ms|layoutTime.*ms|mountTime.*ms/i];
const VIDEO = [/video.*error|playback.*error|media.*error|decoder.*error/i, /exoplayer.*error|mediaplayer.*error|codec.*error/i, /mpb_drm|w3cmedia|mse_eme|mpbbackend/i];
const CONCURRENCY = [/race.*condition|concurrent.*modification|synchronization.*error/i, /thread.*pool.*exhausted|executor.*rejected|task.*queue.*full/i, /semaphore.*timeout|barrier.*timeout|latch.*timeout/i, /priority.*inversion|thread.*starvation/i];
const MEMORY_THRESHOLD = [/memory usage:\s*\d+MB/i, /memory.*threshold.*exceeded/i, /terminating.*memory.*exceeds/i, /resmgr-monitor-memory/i];
const CROSS_APP_CRASH = [/Deregistering application.*after crash/i, /Process.*crashed with signal/i, /stem.*was killed.*SIGKILL/i];
const EPG = [/channel.*not.*found|invalid.*channel.*id|channel.*unavailable/i, /epg.*service.*error|epg.*sync.*failed|guide.*service.*error/i, /epg.*timeout|epg.*server.*error/i, /deeplink.*parse.*error|invalid.*deeplink.*format/i, /epgSyncTask/i];
const UI_LOADING = [/ui.*loading|loading.*ui|splash.*screen|initialization|startup|bootstrap/i, /render|component.*load|activity.*start|fragment.*load/i, /onCreate|onResume|onStart|onPause|onStop|onDestroy/i, /MountingManager|SurfaceTelemetryLogger|mutations|transactions/i];
const PLATFORM_ACCESS = [/FrameProtocolAccessControl.*NOT owned/i, /isAppAuthorizedToRegister.*not authorized/i, /ExternalCapabilityManager.*not signed/i, /capability.*denied|signature.*verification.*failed/i];
const LOW_RESOURCE = [/LowResourceKiller.*warning/i, /memory.*high.*pressure/i, /memory.*pressure.*warning|low.*memory.*warning/i, /process.*will.*be.*killed|killing.*process.*due.*to.*low.*memory/i, /oom.*killer.*candidate|out.*of.*memory.*killer/i];

const FOREGROUND = /makeinteractivecomponent|fps=|render resources:|deeplink/i;
const BACKGROUND = /bglaunchservice|background service|service onstart|sync task/i;

const LOG_ANDROID = /^(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+([VDIWEF])\s*\/?([\w./]+).*?:\s*(.*)$/;
const LOG_LOGCAT = /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3})\s+\d+\s+\d+\s+([VDIWEF])\s+([\w./]+)\s*:\s*(.*)$/;

interface ParsedLine { timestamp: string; level: string; tag: string; message: string; raw: string; lineNum: number }
interface AppStats {
  pkg: string; crashes: ParsedLine[]; anrs: ParsedLine[]; errors: ParsedLine[];
  network: ParsedLine[]; drm: ParsedLine[]; perf: ParsedLine[]; video: ParsedLine[];
  concurrency: ParsedLine[]; memoryThreshold: ParsedLine[]; crossAppCrash: ParsedLine[];
  epg: ParsedLine[]; uiLoading: ParsedLine[]; platformAccess: ParsedLine[];
  lowResource: ParsedLine[];
  total: number; first: string; last: string; wasForeground: boolean; wasBackground: boolean;
}

const parse = (line: string, n: number): ParsedLine | null => {
  let m = LOG_ANDROID.exec(line);
  if (m) return { timestamp: m[1], level: m[2], tag: m[3], message: m[4], raw: line, lineNum: n };
  m = LOG_LOGCAT.exec(line);
  if (m) return { timestamp: m[1], level: m[2], tag: m[3], message: m[4], raw: line, lineNum: n };
  return null;
};

const matchesAny = (msg: string, patterns: RegExp[]) => patterns.some(p => p.test(msg));

const categorize = (p: ParsedLine, app: AppStats) => {
  const m = p.message;
  if (FOREGROUND.test(m)) app.wasForeground = true;
  if (BACKGROUND.test(m)) app.wasBackground = true;

  const buckets: [RegExp[], ParsedLine[]][] = [
    [CRASH, app.crashes], [ANR, app.anrs], [DRM, app.drm], [NETWORK, app.network],
    [EPG, app.epg], [VIDEO, app.video], [CONCURRENCY, app.concurrency],
    [MEMORY_THRESHOLD, app.memoryThreshold], [CROSS_APP_CRASH, app.crossAppCrash],
    [PLATFORM_ACCESS, app.platformAccess], [LOW_RESOURCE, app.lowResource],
    [PERF, app.perf], [UI_LOADING, app.uiLoading],
  ];
  for (const [patterns, bucket] of buckets) { if (matchesAny(m, patterns)) { bucket.push(p); return; } }
  if (p.level === 'E' || p.level === 'F') app.errors.push(p);
};

const emptyStats = (pkg: string, ts: string): AppStats => ({
  pkg, crashes: [], anrs: [], errors: [], network: [], drm: [], perf: [], video: [],
  concurrency: [], memoryThreshold: [], crossAppCrash: [], epg: [], uiLoading: [],
  platformAccess: [], lowResource: [],
  total: 0, first: ts, last: ts, wasForeground: false, wasBackground: false,
});

const analyze = (content: string, targets: string[], quick: boolean): Record<string, AppStats> => {
  const stats: Record<string, AppStats> = {};
  content.split('\n').forEach((raw, i) => {
    if (quick && i % 3 !== 0) return;
    const p = parse(raw, i + 1);
    if (!p) return;
    const pkg = targets.find(t => raw.includes(t)) ?? raw.match(/\b(com\.[a-zA-Z0-9_.]{3,})/)?.[1];
    if (!pkg) return;
    stats[pkg] ??= emptyStats(pkg, p.timestamp);
    const app = stats[pkg];
    app.total++; app.last = p.timestamp;
    categorize(p, app);
  });
  return stats;
};

const summarizeCrash = (line: ParsedLine): string => {
  const msg = line.message.toLowerCase();
  if (/nullpointerexception/.test(msg)) return 'NullPointerException — object not initialized';
  if (/outofmemoryerror/.test(msg)) return 'OutOfMemoryError — heap exhausted';
  if (/sigabrt|abort/.test(msg)) return 'SIGABRT — process abort / assertion failure';
  if (/sigsegv|segfault/.test(msg)) return 'SIGSEGV — invalid memory access';
  if (/sigkill/.test(msg)) return 'SIGKILL — forcibly killed by OS (likely OOM)';
  if (/typeerror:/.test(msg)) return 'TypeError — incorrect JS type usage';
  if (/died.*fore|died.*back/.test(msg)) return 'Process death — app terminated unexpectedly';
  if (/fatal exception/.test(msg)) return 'Fatal exception — unhandled error';
  if (/appnotresponding|forcefully terminating/.test(msg)) return 'ANR-crash — system killed unresponsive app';
  if (/threadmonitor.*termination|keplerscriptthread/.test(msg)) return 'Thread monitor termination — critical thread unresponsive';
  return 'Unknown crash cause';
};

const formatSection = (title: string, items: ParsedLine[], max: number): string[] => {
  if (!items.length) return [];
  const out = ['', `   ${title}:`];
  items.slice(-max).forEach(i => out.push(`      [${i.timestamp}] L#${i.lineNum}: ${i.message.slice(0, 120)}`));
  if (items.length > max) out.push(`      ... and ${items.length - max} more`);
  return out;
};

const buildReport = (stats: Record<string, AppStats>, file: string, mode: string): string => {
  const apps = Object.values(stats).sort((a, b) => b.crashes.length - a.crashes.length);
  const totalCrashes = apps.reduce((s, a) => s + a.crashes.length, 0);
  const totalAnrs = apps.reduce((s, a) => s + a.anrs.length, 0);

  const out = [
    '='.repeat(80), 'DEVICE LOG ANALYSIS REPORT', '='.repeat(80),
    `File: ${file}`, `Mode: ${mode}`, `Apps: ${apps.length}`, '',
    'STATISTICS:', `   Crashes: ${totalCrashes}`, `   ANRs: ${totalAnrs}`,
    `   Apps with issues: ${apps.filter(a => a.crashes.length + a.anrs.length + a.network.length > 0).length}`, '',
  ];

  apps.forEach(a => {
    const issues = [
      a.crashes.length && `${a.crashes.length} crashes`, a.anrs.length && `${a.anrs.length} ANRs`,
      a.errors.length && `${a.errors.length} errors`, a.network.length && `${a.network.length} network`,
      a.drm.length && `${a.drm.length} DRM`, a.perf.length && `${a.perf.length} perf`,
      a.epg.length && `${a.epg.length} EPG`, a.uiLoading.length && `${a.uiLoading.length} UI`,
      a.video.length && `${a.video.length} video`, a.concurrency.length && `${a.concurrency.length} concurrency`,
      a.memoryThreshold.length && `${a.memoryThreshold.length} memory`, a.crossAppCrash.length && `${a.crossAppCrash.length} cross-app`,
      a.platformAccess.length && `${a.platformAccess.length} platform-access`, a.lowResource.length && `${a.lowResource.length} low-resource`,
    ].filter(Boolean);
    if (!issues.length && a.total < 5) return;

    out.push('-'.repeat(80), `APP: ${a.pkg}`, `   Entries: ${a.total} | Active: ${a.first} → ${a.last}`);
    const status: string[] = [];
    if (a.wasForeground) status.push('Foreground');
    if (a.wasBackground) status.push('Background');
    if (status.length) out.push(`   Status: ${status.join(' | ')}`);
    if (issues.length) out.push(`   Issues: ${issues.join(' | ')}`);

    if (a.crashes.length) {
      out.push('', '   CRASH ANALYSIS:');
      a.crashes.slice(-3).forEach(c => {
        out.push(`      [${c.timestamp}] L#${c.lineNum}: ${summarizeCrash(c)}`);
        out.push(`      > ${c.message.slice(0, 120)}`);
      });
      if (a.crashes.length > 3) out.push(`      ... and ${a.crashes.length - 3} more`);
    }

    out.push(...formatSection('ANR EVENTS', a.anrs, 2));
    out.push(...formatSection('DRM/LICENSE ISSUES', a.drm, 2));
    out.push(...formatSection('NETWORK ISSUES', a.network, 2));
    out.push(...formatSection('EPG/DEEPLINK ISSUES', a.epg, 2));
    out.push(...formatSection('UI LOADING ISSUES', a.uiLoading, 2));
    out.push(...formatSection('PLATFORM ACCESS ISSUES', a.platformAccess, 2));
    out.push(...formatSection('LOW RESOURCE WARNINGS', a.lowResource, 2));
    out.push(...formatSection('CONCURRENCY/THREADING', a.concurrency, 2));
    out.push(...formatSection('MEMORY THRESHOLD', a.memoryThreshold, 2));
    out.push(...formatSection('CROSS-APP CRASHES', a.crossAppCrash, 2));
    out.push('');
  });

  out.push('='.repeat(80), 'RECOMMENDATIONS:');
  const priority = apps.filter(a => a.crashes.length > 0).slice(0, 3);
  if (priority.length) {
    out.push('   [CRITICAL] Priority apps:');
    priority.forEach(a => {
      const causes = [...new Set(a.crashes.map(summarizeCrash))];
      out.push(`      - ${a.pkg} (${a.crashes.length} crashes)`, `        Root causes: ${causes.slice(0, 2).join(', ')}`);
    });
  }
  if (apps.some(a => a.network.length > 3)) out.push('   [HIGH] Network: implement retry with exponential backoff');
  if (apps.some(a => a.drm.length > 0)) out.push('   [MEDIUM] DRM: check license server connectivity');
  if (apps.some(a => a.epg.length > 0)) out.push('   [MEDIUM] EPG: validate channel/program IDs');
  if (apps.some(a => a.platformAccess.length > 0)) out.push('   [HIGH] Platform access violations: review app signing');
  if (apps.some(a => a.lowResource.length > 0)) out.push('   [HIGH] Low resource warnings: optimize memory usage');
  if (apps.some(a => a.concurrency.length > 0)) out.push('   [HIGH] Concurrency issues: review synchronization');
  out.push('='.repeat(80));
  return out.join('\n');
};

export const logAnalyzerTool: Tool<{
  log_file_path: z.ZodString;
  mode: z.ZodOptional<z.ZodEnum<['quick', 'detailed']>>;
  target_apps: z.ZodOptional<z.ZodString>;
}> = {
  name: 'analyze-log',
  description: 'Analyze device log file for crashes, ANRs, performance issues, network errors, DRM problems, EPG/deeplink failures, UI loading, platform access violations, low resource warnings, concurrency issues, memory thresholds, and cross-app crashes.',
  paramSchema: {
    log_file_path: z.string().describe('Absolute path to log file'),
    mode: z.enum(['quick', 'detailed']).optional().describe('"quick" processes every 3rd line. "detailed" processes all (default).'),
    target_apps: z.string().optional().describe('Comma-separated app package names to focus on'),
  },
  cb: async ({ log_file_path, mode = 'detailed', target_apps }: { log_file_path: string; mode?: 'quick' | 'detailed'; target_apps?: string }) => {
    try {
      const content = readFileSync(log_file_path, 'utf8');
      const apps = target_apps?.split(',').map((s: string) => s.trim()).filter(Boolean) ?? [];
      const quick = mode === 'quick';
      const stats = analyze(content, apps, quick);
      return { content: [{ type: 'text' as const, text: buildReport(stats, log_file_path, quick ? 'Quick Analysis' : 'Detailed Analysis') }] };
    } catch { return { content: [{ type: 'text' as const, text: `Log file not found: ${log_file_path}` }], isError: true }; }
  },
};
