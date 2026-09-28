const os = require('node:os');

// Set to the deployed relay (services/bug-report-worker) URL. Empty means the
// dialog offers the GitHub issue page instead of sending from the app.
const BUG_REPORT_ENDPOINT = 'https://drum-sheet-bug-report.me-18f.workers.dev/reports';

const ISSUE_URL = 'https://github.com/kr-ericshim/drum-score-capture-tool/issues/new';
const LIMITS = { description: 5000, steps: 5000, email: 254, diagnostics: 30000, screenshotBytes: 3 * 1024 * 1024 };
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function resolveBugReportEndpoint(env = process.env) {
  const value = String(env.DRUMSHEET_BUG_REPORT_URL || BUG_REPORT_ENDPOINT).trim();
  if (!value) return '';
  try {
    const url = new URL(value);
    // Reports leave the machine only over TLS; plain http is allowed for a local relay during development.
    if (url.protocol === 'https:' || (url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname))) return url.toString();
  } catch (_) { /* not a URL */ }
  return '';
}

function cleanText(value, limit) {
  return String(value ?? '').replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').trim().slice(0, limit);
}

// Returns the payload to send, or { error } naming the field the user has to fix.
function buildBugReportPayload(input, prepared = {}, meta = {}) {
  const description = cleanText(input?.description, LIMITS.description);
  if (!description) return { error: 'description' };
  const email = cleanText(input?.email, LIMITS.email);
  if (email && !EMAIL_PATTERN.test(email)) return { error: 'email' };
  const screenshot = input?.includeScreenshot && Buffer.isBuffer(prepared.screenshot) && prepared.screenshot.length <= LIMITS.screenshotBytes
    ? prepared.screenshot.toString('base64')
    : '';
  return {
    payload: {
      appVersion: String(meta.version || ''),
      platform: `${process.platform} ${process.arch}; OS ${os.release()}`,
      locale: meta.locale === 'en' ? 'en' : 'ko',
      description,
      steps: cleanText(input?.steps, LIMITS.steps),
      email,
      // The diagnostics are the text the user reviewed in the dialog, not a fresh read.
      diagnostics: input?.includeDiagnostics ? cleanText(prepared.diagnostics, LIMITS.diagnostics) : '',
      screenshot,
    },
  };
}

async function sendBugReport(payload, { endpoint, fetchImpl, timeoutMs = 20000 }) {
  if (!endpoint) return { status: 'error', reason: 'not-configured' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Drum-Sheet-Client': 'desktop' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (response.ok) return { status: 'sent' };
    if (response.status === 429) return { status: 'error', reason: 'rate-limited' };
    return { status: 'error', reason: response.status >= 500 ? 'server' : 'rejected' };
  } catch (_) {
    return { status: 'error', reason: 'network' };
  } finally {
    clearTimeout(timer);
  }
}

// Fallback when the relay is unset or unreachable. GitHub issues are public, so the
// reply address stays out; the diagnostics go through the clipboard (a URL is too short).
function buildIssueUrl(input, meta = {}) {
  const description = cleanText(input?.description, 1500);
  const steps = cleanText(input?.steps, 1500);
  const body = [
    '### What happened', description, '',
    '### Steps to reproduce', steps, '',
    `Drum Sheet Capture ${meta.version || ''} · ${process.platform} ${process.arch}; OS ${os.release()}`,
    ...(input?.includeDiagnostics ? ['', '### Diagnostics', '<!-- The diagnostics were copied to the clipboard. Paste them here. -->'] : []),
  ].join('\n');
  const url = new URL(ISSUE_URL);
  const title = description.split('\n')[0].slice(0, 80);
  if (title) url.searchParams.set('title', title);
  url.searchParams.set('body', body);
  return url.toString();
}

module.exports = { LIMITS, resolveBugReportEndpoint, buildBugReportPayload, sendBugReport, buildIssueUrl };
