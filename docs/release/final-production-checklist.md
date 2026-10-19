# Final Production Checklist

Use this checklist immediately before cutting a public release for Drum Sheet Capture.

## Release Gate

- [ ] Release scope is frozen for this version.
- [ ] Version is updated in `desktop/package.json` and both root version fields of `desktop/package-lock.json`.
- [ ] `node desktop/scripts/check-release-version.js` passes; the intended tag exactly matches the version.
- [ ] `docs/release/release-notes-vX.Y.Z.md` exists, describes the new version, and carries the minimum-OS marker on its first line (currently `<!-- minimum-os: darwin=13.0 -->`).
- [ ] Backend app version matches `desktop/package.json`.
- [ ] README files still match the actual product behavior and supported platforms.
- [ ] Public release target is still limited to Windows `x64` and macOS `arm64`.
- [ ] Team accepts macOS ad-hoc signing without notarization, unsigned Windows installers, and first-launch trust warnings.

## Automated Checks

- [ ] `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`
- [ ] Build dependencies match the lock: `uv pip sync --python backend/.venv-build/bin/python backend/requirements-build.lock` (or `pip install -r backend/requirements-build.lock` in the build environment)
- [ ] `cd desktop && npm ci`
- [ ] `cd desktop && npm run test:desktop-smoke`
- [ ] `cd desktop && npm run test:desktop-node`
- [ ] `cd desktop && npm run test:packaged-release`
- [ ] `cd desktop && npm run verify:renderer-v2`
- [ ] Optional preflight only: `cd desktop && npm run pack:release`
- [ ] After `pack:release` or `dist:release`: `cd desktop && npm run smoke:packaged-electron`
- [ ] After `pack:release` or `dist:release`: `cd desktop && npm run smoke:packaged-runtime`
- [ ] Required for any public installer build: `cd desktop && npm run dist:release`
- [ ] Treat `pack:release` as unpacked-app validation only; it does not prove DMG/installer generation.
- [ ] Confirm packaged artifact validation passes at the end of the build logs, including frozen backend runtime plus bundled `ffmpeg`/`ffprobe` detection.
- [ ] Confirm packaged Electron smoke starts the generated app and reaches `/health` plus `/runtime`.
- [ ] Confirm packaged runtime smoke starts the backend executable from `dist/`, reads `/runtime`, extracts a preview frame from a synthetic score video, and completes a clean reflow PNG/PDF export.
- [ ] On macOS, confirm the build log shows `[verify-macos-signature]` lines for the app and, after `dist:release`, the DMG. To re-check by hand: `node desktop/scripts/verify-macos-signature.js <app|dmg>`.
- [ ] Treat `test:desktop-smoke` as a no-GUI Electron startup contract only; full packaged app behavior still requires the manual smoke test below.

## Manual Smoke Test

- [ ] Fresh install on macOS from the generated DMG.
- [ ] Fresh install on Windows from the generated installer.
- [ ] App launches without backend connection failure.
- [ ] Local video import works.
- [ ] YouTube URL import works.
- [ ] Preview frame loads.
- [ ] Score region suggestion appears as a draft, can be adjusted, and is applied only by **Apply region**.
- [ ] **Make PDF** on a supported one-line video completes without user-facing errors, and review lists its score lines.
- [ ] Review: include/exclude and reorder a line, then **Rebuild PDF**; the PDF reflects it.
- [ ] **Edit title** rebuilds the PDF with the new title without capturing again.
- [ ] **Rebuild as original screens** works on a one-line video.
- [ ] An unsupported video (translucent plate or scrolling) shows the not-supported message instead of a PDF.
- [ ] PNG and JPG (under More options) export the same pages.
- [ ] **Save PDF as…** saves a copy; exported files open correctly outside the app.
- [ ] Korean bootstrap works for `ko*` locale or saved Korean preference.
- [ ] English bootstrap works for non-`ko*` locale or saved English preference.
- [ ] Relaunch preserves saved language setting.

## Packaging Review

- [ ] Artifact names contain the intended version.
- [ ] If `pack:release` was used as preflight, only expect unpacked packaged-app output (for example `.app` or `win-unpacked`).
- [ ] macOS installer artifact exists in `dist/` as a DMG after `dist:release`.
- [ ] Windows installer artifact exists in `dist/` as an installer after `dist:release`.
- [ ] Packaged app includes `backend/runtime/drumsheet-backend/...` plus bundled `backend/bin/ffmpeg` and `backend/bin/ffprobe`, and does not include a packaged `.venv`.
- [ ] Packaged backend version matches source version.
- [ ] Packaged backend source-text compatibility checks match the current backend YouTube strategy markers; backend tests, frozen-runtime smoke, and packaged-runtime smoke remain the behavior gates.

## Release Operations

- [ ] Commit the version bump and release note changes.
- [ ] Push the release commit.
- [ ] Create a new tag `vX.Y.Z`.
- [ ] Push the new tag.
- [ ] Confirm GitHub Actions release workflow starts from the tag push.
- [ ] Confirm both platform build jobs and packaged smoke checks pass before the separate publish job starts.
- [ ] Confirm release assets are uploaded for both public targets.
- [ ] For a `codex/release-*` branch or manual preflight, confirm installers are stored as Actions artifacts and the publish job is skipped.
- [ ] Verify the GitHub release notes describe user-visible changes and known limitations.

## Known Limitations To State Publicly

- [ ] macOS app and DMG-contained app pass strict signature verification; Gatekeeper warnings remain expected without notarization.
- [ ] Install docs describe Open Anyway first and the scoped app quarantine fallback.
- [ ] macOS Intel or universal builds are not part of the default release target unless explicitly added.
- [ ] In-app update (since v0.1.35): an installed previous version offers this release, downloads it, and installs after **Restart to install**. Release notes state the minimum OS for users who cannot update.

## Version Decision Rule

- [ ] Use `1.0.0` only if this release is intended to be the first stable public baseline, the workflow is stable, and the manual smoke tests pass on target platforms.
- [ ] Use the next patch or minor version instead if you still expect release-process churn, platform-policy changes, or one more round of post-release fixes.
- [ ] Never overwrite an existing release tag for a new public build; cut a new version.
