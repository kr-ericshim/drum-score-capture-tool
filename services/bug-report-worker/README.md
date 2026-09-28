# Problem report relay

A Cloudflare Worker that receives reports from the app's **문제 보고 / Report a problem** dialog and emails them to the maintainer via [Resend](https://resend.com). The Resend key and the recipient address live only in this Worker; the app knows only the Worker URL.

```
App dialog ──POST /reports──▶ Worker (validation, 5 per minute per IP) ──▶ Resend ──▶ maintainer inbox
```

Until the Worker URL is set in the app, the dialog opens a pre-filled GitHub issue instead of sending.

## What a report contains

- Description (required), steps to reproduce (optional)
- App version, OS, and language
- Reply email (optional; used as the reply-to address)
- Diagnostics (checkbox, on by default; the same redacted log as **진단 로그 복사**) → `diagnostics.txt` attachment
- App screenshot (checkbox, off by default; a JPEG of the window taken just before the dialog opened) → `screenshot.jpg` attachment

Videos, capture images, and generated files are never sent.

## Setup (once)

1. Create a [Resend](https://resend.com) account and an API key with **Sending access** only.
   - `REPORT_FROM` in `wrangler.toml` must use a domain verified in Resend (currently `mail.teamit.ericshim.me`). With `onboarding@resend.dev` instead, mail can only go to the Resend account's own address.
2. Create a Cloudflare account, then from this directory:

```bash
npx wrangler login
npx wrangler secret put RESEND_API_KEY
npx wrangler secret put REPORT_TO
npx wrangler deploy
```

   Enter the Resend account's email address for `REPORT_TO`.
3. Put the URL that `deploy` prints, with `/reports` appended, into `BUG_REPORT_ENDPOINT` in `desktop/bug-report.js`, and ship it in the next release:

```js
const BUG_REPORT_ENDPOINT = 'https://drum-sheet-bug-report.<account>.workers.dev/reports';
```

   For development, set `DRUMSHEET_BUG_REPORT_URL` instead of editing the code.

## Local check

```bash
npm test                      # Worker unit tests (Node 18+)
npx wrangler dev              # http://127.0.0.1:8787
DRUMSHEET_BUG_REPORT_URL=http://127.0.0.1:8787/reports npm --prefix ../../desktop start
```

For `wrangler dev`, put the secrets in `.dev.vars` (`RESEND_API_KEY=...`, `REPORT_TO=...`). Do not commit that file.

## Limits

- 5 reports per minute per IP address (Workers Rate Limiting)
- Request body 6 MB, description and steps 5,000 characters each, diagnostics 30,000 characters
- Requests without the `X-Drum-Sheet-Client: desktop` header are refused. This header is not a secret; it only filters out random requests. For stronger protection, add Cloudflare Turnstile or similar.
- Resend free plan: 100 emails per day
