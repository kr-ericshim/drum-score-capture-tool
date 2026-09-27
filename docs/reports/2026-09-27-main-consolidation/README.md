# Main consolidation — 2026-09-27

## Recovered work

The original checkout was on `redesign/floating-dock` at `ac11c2f`, with uncommitted work. The released v0.1.33 and remote main were at `ea380ae`. Cache maintenance API routes were already in v0.1.33, but the Archive storage UI, event wiring, translations and tests were only in the original working tree. The Floating Dock layout and Korean README improvements were also uncommitted.

Recovered these source changes onto the current release base. Preserved the chosen Floating Dock design and moved the design brief to `docs/DESIGN.md`. Updated guide navigation and sample screenshots. During visual verification, the source error overlapped the floating diagnostics bar; moved it inside the scrollable import panel beside the failing input.

The original tracked changes and all nonignored untracked files (233 paths) were saved to a local tar archive, with a SHA-256 manifest, binary patch and Git bundle before branch cleanup. Historical screenshots, scratch media and reports not needed by the application remain recoverable from that backup; they were not indiscriminately committed into main. Ignored source videos, jobs and local runtime files were not removed.

## Verification

- Renderer verification: 238 renderer tests plus entry/workflow checks, 46 module parse checks and locale initialization passed.
- Desktop Node tests: 56 passed.
- Media bundle validation: 9 tests passed (both platforms, corruption, wrong recipe/repository/asset, missing source/license, duplicate/traversal/link entries).
- Browser fixture: four screens at 1440×960 and 1120×840 in Korean and English; no document overflow. See `browser-checks.json` and adjacent screenshots.
- Cache cancel sent no request; confirmation sent one mocked request and reset session state; active work disabled clearing. These checks ran in each size/language combination. No real cache or user file was deleted.
- Keyboard Tab had a visible outline inside Archive; Escape closed it and returned focus to its opener.
- Source and export error states inspected. Source error placement repaired and rechecked at both desktop sizes.

`preview.html` runs the actual renderer with injected sample metadata/API/desktop bridge. Serve repository root on `127.0.0.1:8879` to use it. These checks do not prove packaged native dialogs, real YouTube import or installed Windows/macOS UI behavior. Hosted package/build results are recorded separately after completion.
