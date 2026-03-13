# Production Hardening Design

Date: 2026-03-13

## Goal

Close the current production blockers without introducing heavy runtime costs, large new dependencies, or significant installer size growth.

## Constraints

- macOS distribution remains unsigned by design.
- macOS install guidance must continue to rely on `xattr -dr com.apple.quarantine ...`.
- The app is a local desktop tool, so security hardening should stay lightweight.
- Release artifact size matters. Prefer replacing runtime duplication over adding new bundled layers.
- Avoid major architecture changes such as replacing the HTTP backend with IPC-only transport.

## Scope

### 1. Standalone Runtime Contract

`dist:release` and `pack:release` must produce a self-contained packaged app.

Design decisions:

- Release packaging builds the frozen backend runtime before Electron packaging.
- Packaged apps must launch only the frozen backend runtime in packaged mode.
- Development mode keeps the current Python fallback path.
- Release validation must fail if the packaged app contains source-only backend files but no frozen runtime, or if a packaged `.venv` is present.

This keeps runtime behavior explicit while reducing release size by avoiding a bundled virtualenv.

### 2. Lightweight Local Backend Protection

The localhost backend stays in place, but it should behave like an app-private channel rather than an open local web API.

Design decisions:

- Electron generates a random session token per app launch and passes it to the backend through env vars.
- Renderer-side backend calls attach the token through the existing API helper layer.
- Backend middleware rejects protected requests when the token is missing or mismatched.
- `/health` remains open so packaged startup probing stays simple.
- Job file downloads move behind a protected route rather than an unguarded `StaticFiles` mount.
- CORS becomes minimal instead of `*`.
- Input validation remains lightweight: path normalization, URL scheme checks, and a small allowlist for YouTube-style hosts. No heavy scanning or sandboxing.

This is intentionally not enterprise-grade auth. It is a low-cost barrier against drive-by browser access to localhost.

### 3. Job Persistence

Job state should survive restarts well enough for users to inspect prior results.

Design decisions:

- Each job persists to `artifact_dir/job.json`.
- `JobStore` reloads persisted jobs on startup.
- Jobs that were `queued` or `running` during shutdown are restored as `error` with a restart-recovery marker rather than resumed.
- Existing in-memory access patterns remain in place; persistence is an implementation detail under the store.

This avoids adding SQLite or another runtime dependency while preserving user-visible continuity.

### 4. Release Gate And Docs Alignment

Release docs, workflows, and validation scripts should describe the same contract.

Design decisions:

- Public release contract is: frozen backend required, packaged mode has no Python fallback, unsigned macOS builds require `xattr` guidance.
- Checklists must explicitly require that release notes or install docs include the `xattr` command.
- Workflows should run the same lightweight validation the local release path runs.
- No new GUI E2E stack is added in this batch.

## Testing Strategy

- Add unit tests for job persistence and restart recovery.
- Add desktop tests for authenticated request helpers.
- Keep existing lightweight gates:
  - `python -m unittest discover`
  - `node --test`
  - `npm run check:*`
  - `npm run pack:release`
- Re-run `npm run dist:release` to confirm release metadata and runtime validation succeed.

## Non-Goals

- No signing or notarization work.
- No auto-update introduction.
- No full IPC rewrite.
- No heavy integrity/provenance system.
- No HAT runtime redesign in this batch.
