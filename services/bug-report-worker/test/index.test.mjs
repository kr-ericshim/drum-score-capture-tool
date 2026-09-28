import test from "node:test";
import assert from "node:assert/strict";
import worker, { buildEmail, parseReport } from "../src/index.js";

const env = { RESEND_API_KEY: "re_test", REPORT_TO: "owner@example.com", REPORT_FROM: "App <onboarding@resend.dev>" };

function request(body, headers = {}) {
  return new Request("https://relay.example/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Drum-Sheet-Client": "desktop", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

function withResend(status, run) {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push({ url, body: JSON.parse(init.body) }); return new Response("{}", { status }); };
  return run(calls).finally(() => { globalThis.fetch = original; });
}

test("a valid report is emailed with attachments and reply-to", () => withResend(200, async (calls) => {
  const response = await worker.fetch(request({
    appVersion: "0.1.35", platform: "darwin arm64", locale: "ko", description: "페이지가 빠집니다\n두 번째 줄",
    steps: "1. 캡처", email: "user@example.com", diagnostics: "로그 ".repeat(20000), screenshot: "aGVsbG8=",
  }), env);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  const mail = calls[0].body;
  assert.equal(mail.subject, "[문제 보고] 페이지가 빠집니다 · v0.1.35");
  assert.match(mail.html, /src="cid:screenshot"/);
  assert.match(mail.html, /macOS arm64/);
  assert.match(mail.text, /마지막 부분/);
  assert.ok(mail.html.length < 20000, "a long log is cut in the body; the whole log is attached");
  assert.deepEqual(mail.to, ["owner@example.com"]);
  assert.equal(mail.reply_to, "user@example.com");
  assert.deepEqual(mail.attachments.map(a => a.filename), ["diagnostics.txt", "screenshot.jpg"]);
  assert.equal(Buffer.from(mail.attachments[0].content, "base64").toString("utf8"), "로그 ".repeat(20000).trim().slice(0, 30000));
}));

test("requests without the app header, body, or configuration are refused", () => withResend(200, async (calls) => {
  assert.equal((await worker.fetch(request({ description: "x" }, { "X-Drum-Sheet-Client": "" }), env)).status, 403);
  assert.equal((await worker.fetch(request("not json"), env)).status, 400);
  assert.equal((await worker.fetch(request({ description: "   " }), env)).status, 400);
  assert.equal((await worker.fetch(request({ description: "x" }), { ...env, REPORT_TO: "" })).status, 503);
  assert.equal((await worker.fetch(new Request("https://relay.example/reports"), env)).status, 405);
  assert.equal((await worker.fetch(new Request("https://relay.example/"), env)).status, 404);
  assert.equal(calls.length, 0);
}));

test("rate limit and delivery failures are reported", async () => {
  const limited = { ...env, REPORT_LIMITER: { limit: async () => ({ success: false }) } };
  assert.equal((await worker.fetch(request({ description: "x" }), limited)).status, 429);
  await withResend(500, async () => {
    const original = console.error;
    console.error = () => {};
    try { assert.equal((await worker.fetch(request({ description: "x" }), env)).status, 502); } finally { console.error = original; }
  });
});

test("malformed optional fields are dropped instead of forwarded", () => {
  const report = parseReport({ description: "x", email: "not-an-email", screenshot: "<script>", locale: "fr" });
  assert.equal(report.email, "");
  assert.equal(report.screenshot, "");
  assert.equal(report.locale, "ko");
  const mail = buildEmail(report, env);
  assert.equal("reply_to" in mail, false);
  assert.equal("attachments" in mail, false);
  assert.doesNotMatch(mail.html, /cid:screenshot/);
});

test("user text is escaped in the HTML body", () => {
  const mail = buildEmail(parseReport({ description: "<img src=x onerror=alert(1)> & more", email: "a\"b@example.com" }), env);
  assert.doesNotMatch(mail.html, /<img src=x/);
  assert.match(mail.html, /&lt;img src=x onerror=alert\(1\)&gt; &amp; more/);
});
