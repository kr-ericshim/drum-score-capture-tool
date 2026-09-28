// Relays problem reports from the desktop app to the maintainer's inbox via Resend.
// The Resend key stays here; the app only knows this Worker's URL.

const LIMITS = { body: 6 * 1024 * 1024, description: 5000, steps: 5000, email: 254, diagnostics: 30000, screenshot: 4.2 * 1024 * 1024 };
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function text(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

export function parseReport(raw) {
  if (!raw || typeof raw !== "object") return null;
  const description = text(raw.description, LIMITS.description);
  if (!description) return null;
  const email = text(raw.email, LIMITS.email);
  const screenshot = typeof raw.screenshot === "string" && raw.screenshot.length <= LIMITS.screenshot && BASE64_PATTERN.test(raw.screenshot)
    ? raw.screenshot
    : "";
  return {
    appVersion: text(raw.appVersion, 40),
    platform: text(raw.platform, 120),
    locale: raw.locale === "en" ? "en" : "ko",
    description,
    steps: text(raw.steps, LIMITS.steps),
    // A malformed address is dropped rather than rejecting the whole report.
    email: EMAIL_PATTERN.test(email) ? email : "",
    diagnostics: text(raw.diagnostics, LIMITS.diagnostics),
    screenshot,
  };
}

function utf8Base64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  // Chunked so a long Korean log does not exceed the argument limit of fromCharCode.
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function describePlatform(platform) {
  const [os = "", arch = ""] = platform.split(/[\s;]+/);
  const name = { darwin: "macOS", win32: "Windows", linux: "Linux" }[os] || os;
  return name ? `${name} ${arch}`.trim() : "";
}

function receivedAt(now) {
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(now) + " KST";
}

// Enough of the log to triage from a phone; the whole log is attached.
function logTail(diagnostics, lines = 20, chars = 2500) {
  const all = diagnostics.split("\n");
  const text = all.slice(-lines).join("\n");
  return { text: text.length > chars ? `…${text.slice(-chars)}` : text, truncated: all.length > lines || text.length > chars };
}

const FONT = "-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Segoe UI',sans-serif";
const MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace";

function htmlSection(title, body) {
  return `<tr><td style="padding:20px 28px 0">
    <div style="font-size:12px;font-weight:600;letter-spacing:.02em;color:#6b7280;margin:0 0 8px">${escapeHtml(title)}</div>
    ${body}
  </td></tr>`;
}

function htmlText(value, placeholder) {
  return value
    ? `<div style="font-size:15px;line-height:1.65;color:#111827;white-space:pre-wrap;word-break:keep-all;overflow-wrap:anywhere">${escapeHtml(value)}</div>`
    : `<div style="font-size:14px;color:#9ca3af">${escapeHtml(placeholder)}</div>`;
}

function buildHtml(report, meta) {
  const rows = [
    ["버전", report.appVersion || "알 수 없음"],
    ["환경", describePlatform(report.platform) || "알 수 없음"],
    ["앱 언어", report.locale === "en" ? "English" : "한국어"],
    ["회신", report.email || "요청 안 함"],
    ["받은 시각", meta.receivedAt],
  ].map(([label, value]) => `<tr>
      <td style="padding:5px 0;width:84px;font-size:13px;color:#6b7280;vertical-align:top">${escapeHtml(label)}</td>
      <td style="padding:5px 0;font-size:13px;color:#111827;overflow-wrap:anywhere">${label === "회신" && report.email
        ? `<a href="mailto:${escapeHtml(report.email)}" style="color:#2563eb;text-decoration:none">${escapeHtml(report.email)}</a>`
        : escapeHtml(value)}</td>
    </tr>`).join("");
  const tail = report.diagnostics ? logTail(report.diagnostics) : null;
  const attachments = [
    report.diagnostics ? "diagnostics.txt" : "",
    report.screenshot ? "screenshot.jpg" : "",
  ].filter(Boolean);
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(meta.subject)}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 12px;font-family:${FONT}">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
  <tr><td style="padding:22px 28px 18px;border-bottom:1px solid #e5e7eb">
    <div style="font-size:12px;font-weight:600;color:#2563eb;margin:0 0 6px">Drum Sheet Capture · 문제 보고</div>
    <div style="font-size:19px;font-weight:700;line-height:1.4;color:#111827;word-break:keep-all;overflow-wrap:anywhere">${escapeHtml(meta.title)}</div>
  </td></tr>
  <tr><td style="padding:14px 28px 4px;background:#f9fafb;border-bottom:1px solid #e5e7eb">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">${rows}</table>
  </td></tr>
  ${htmlSection("무슨 일이 있었나요", htmlText(report.description))}
  ${htmlSection("다시 일어나게 하는 방법", htmlText(report.steps, "적지 않음"))}
  ${report.screenshot ? htmlSection("앱 화면", `<img src="cid:screenshot" alt="앱 화면 스크린샷" style="display:block;max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:8px">`) : ""}
  ${tail ? htmlSection(tail.truncated ? "진단 로그 (마지막 부분 · 전체는 첨부)" : "진단 로그",
    `<pre style="margin:0;padding:12px 14px;background:#f3f4f6;border-radius:8px;font-family:${MONO};font-size:12px;line-height:1.55;color:#374151;white-space:pre-wrap;overflow-wrap:anywhere">${escapeHtml(tail.text)}</pre>`) : ""}
  <tr><td style="padding:20px 28px 22px">
    <div style="border-top:1px solid #e5e7eb;padding-top:14px;font-size:12px;line-height:1.6;color:#9ca3af">
      첨부: ${escapeHtml(attachments.length ? attachments.join(", ") : "없음")}<br>
      ${report.email ? "이 메일에 답장하면 보고한 사용자에게 전달됩니다." : "사용자가 회신 주소를 남기지 않았습니다."}
    </div>
  </td></tr>
</table>
</td></tr>
</table>
</body></html>`;
}

export function buildEmail(report, env, now = new Date()) {
  const title = report.description.split("\n")[0].slice(0, 80);
  const subject = `[문제 보고] ${title}${report.appVersion ? ` · v${report.appVersion}` : ""}`;
  const meta = { title, subject, receivedAt: receivedAt(now) };
  const tail = report.diagnostics ? logTail(report.diagnostics) : null;
  const text = [
    `Drum Sheet Capture 문제 보고`,
    "",
    `버전: ${report.appVersion || "알 수 없음"}`,
    `환경: ${describePlatform(report.platform) || "알 수 없음"}`,
    `앱 언어: ${report.locale === "en" ? "English" : "한국어"}`,
    `회신: ${report.email || "요청 안 함"}`,
    `받은 시각: ${meta.receivedAt}`,
    "",
    "■ 무슨 일이 있었나요",
    report.description,
    "",
    "■ 다시 일어나게 하는 방법",
    report.steps || "적지 않음",
    ...(tail ? ["", tail.truncated ? "■ 진단 로그 (마지막 부분, 전체는 첨부)" : "■ 진단 로그", tail.text] : []),
  ].join("\n");
  const attachments = [];
  if (report.diagnostics) {
    attachments.push({ filename: "diagnostics.txt", content: utf8Base64(report.diagnostics), content_type: "text/plain; charset=utf-8" });
  }
  if (report.screenshot) {
    attachments.push({ filename: "screenshot.jpg", content: report.screenshot, content_type: "image/jpeg", content_id: "screenshot" });
  }
  return {
    from: env.REPORT_FROM,
    to: [env.REPORT_TO],
    subject,
    html: buildHtml(report, meta),
    text,
    ...(report.email ? { reply_to: report.email } : {}),
    ...(attachments.length ? { attachments } : {}),
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/reports") return json(404, { error: "not-found" });
    if (request.method !== "POST") return json(405, { error: "method" });
    // Not a secret; it only turns away requests that did not come from the app.
    if (request.headers.get("X-Drum-Sheet-Client") !== "desktop") return json(403, { error: "client" });
    if (!env.RESEND_API_KEY || !env.REPORT_TO) return json(503, { error: "not-configured" });
    if (Number(request.headers.get("Content-Length") || 0) > LIMITS.body) return json(413, { error: "too-large" });

    if (env.REPORT_LIMITER) {
      const key = request.headers.get("CF-Connecting-IP") || "unknown";
      const { success } = await env.REPORT_LIMITER.limit({ key });
      if (!success) return json(429, { error: "rate-limited" });
    }

    let raw;
    try {
      const body = await request.text();
      if (body.length > LIMITS.body) return json(413, { error: "too-large" });
      raw = JSON.parse(body);
    } catch (_) {
      return json(400, { error: "invalid" });
    }
    const report = parseReport(raw);
    if (!report) return json(400, { error: "invalid" });

    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(buildEmail(report, env)),
    });
    if (!response.ok) {
      console.error("resend failed", response.status, await response.text());
      return json(502, { error: "delivery" });
    }
    return json(200, { ok: true });
  },
};
