# Final Production Checklist

Use this checklist immediately before cutting a public release for Drum Sheet Capture.

## Release Gate

- [ ] Release scope is frozen for this version.
- [ ] Version is updated in `desktop/package.json` and both root version fields of `desktop/package-lock.json`.
- [ ] `node desktop/scripts/check-release-version.js` passes; the intended tag exactly matches the version.
- [ ] `docs/release/release-notes-vX.Y.Z.md` exists and describes the new version.
- [ ] Backend app version matches `desktop/package.json`.
- [ ] README files still match the actual product behavior and supported platforms.
- [ ] Public release target is still limited to Windows `x64` and macOS `arm64`.
- [ ] Team accepts the current unsigned release policy and resulting trust warnings.

## Automated Checks

- [ ] `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`
- [ ] `backend/.venv/bin/pip install -r backend/requirements-build.txt`
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
- [ ] Confirm packaged runtime smoke starts the backend executable from `dist/`, reads `/runtime`, extracts a preview frame from a synthetic score video, and completes PNG/PDF export.
- [ ] Treat `test:desktop-smoke` as a no-GUI Electron startup contract only; full packaged app behavior still requires the manual smoke test below.

## Manual Smoke Test

- [ ] Fresh install on macOS from the generated DMG.
- [ ] Fresh install on Windows from the generated installer.
- [ ] App launches without backend connection failure.
- [ ] Local video import works.
- [ ] YouTube URL import works.
- [ ] Preview frame loads.
- [ ] Score region can be selected and adjusted.
- [ ] The selected score-area preview appears before export.
- [ ] Full run completes without user-facing errors.
- [ ] Export works for PNG.
- [ ] Export works for JPG.
- [ ] Export works for PDF.
- [ ] Exported files open correctly outside the app.
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

- [ ] macOS build is currently unsigned, so Gatekeeper warnings are expected.
- [ ] Release notes or install docs include the exact `xattr -dr com.apple.quarantine ...` command for the app and DMG paths.
- [ ] macOS Intel or universal builds are not part of the default release target unless explicitly added.
- [ ] Auto-update is not part of the current release checklist unless updater support is intentionally introduced.

## Version Decision Rule

- [ ] Use `1.0.0` only if this release is intended to be the first stable public baseline, the workflow is stable, and the manual smoke tests pass on target platforms.
- [ ] Use the next patch or minor version instead if you still expect release-process churn, platform-policy changes, or one more round of post-release fixes.
- [ ] Never overwrite an existing release tag for a new public build; cut a new version.
