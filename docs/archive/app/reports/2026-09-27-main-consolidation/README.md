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

## Hosted verification and measured reuse

- [Media tools build and publish](https://github.com/kr-ericshim/drum-score-capture-tool/actions/runs/36312512954): both native bundles validated and published as [media-tools-850fac73bcaa288a6a92](https://github.com/kr-ericshim/drum-score-capture-tool/releases/tag/media-tools-850fac73bcaa288a6a92). This is a prerelease build dependency, not the latest app release.
- [Application preflight](https://github.com/kr-ericshim/drum-score-capture-tool/actions/runs/36313453310): Windows x64 and macOS arm64 installer generation, packaged Electron smoke and packaged backend runtime smoke all passed. Publication skipped, as intended for a manual preflight.
- [Final source CI](https://github.com/kr-ericshim/drum-score-capture-tool/actions/runs/36313453173): both platforms passed.

| Platform | Earlier completed cold preflight job | Bundle-reuse preflight job | Restore and validate bundle |
| --- | --- | --- | --- |
| Windows | 19m07s | 3m36s | 2s |
| macOS | 5m30s | 1m56s | 1s |

Earlier baseline: [36310028278](https://github.com/kr-ericshim/drum-score-capture-tool/actions/runs/36310028278). Times are job `completedAt - startedAt`, excluding queue time. The platforms run in parallel. This is one observed preflight per configuration, with recovered UI/docs in the newer source, not a controlled multi-run benchmark or guarantee of future latency. Tests were retained; media compilation and Windows compiler installation moved to the separate tool workflow.

The checked-in lock pins both archive hashes. A local macOS download/restore/runtime validation also passed. Hosted synthetic smoke checks do not establish fresh-machine installation, signing acceptance, real-video/YouTube behavior or interactive native dialogs. Public app release v0.1.33 remains unchanged; recovered UI changes are in main for a subsequent app release.
