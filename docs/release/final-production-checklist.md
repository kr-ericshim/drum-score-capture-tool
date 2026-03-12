# Final Production Checklist

Use this checklist immediately before cutting a public release for Drum Sheet Capture.

## Release Gate

- [ ] Release scope is frozen for this version.
- [ ] Version is updated in `desktop/package.json`.
- [ ] Backend app version matches `desktop/package.json`.
- [ ] README files still match the actual product behavior and supported platforms.
- [ ] Public release target is still limited to Windows `x64` and macOS `arm64`.
- [ ] Team accepts the current unsigned release policy and resulting trust warnings.

## Automated Checks

- [ ] `PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_sheet_finalize.py`
- [ ] `PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_roi_health.py`
- [ ] `cd desktop && npm ci`
- [ ] `cd desktop && npm run check:renderer-syntax`
- [ ] `cd desktop && npm run check:locale-init`
- [ ] `cd desktop && npm run pack:release`
- [ ] If GitHub release assets will be generated locally, also run `cd desktop && npm run dist:release`
- [ ] Confirm packaged artifact validation passes at the end of the build logs.

## Manual Smoke Test

- [ ] Fresh install on macOS from the generated DMG.
- [ ] Fresh install on Windows from the generated installer.
- [ ] App launches without backend connection failure.
- [ ] Local video import works.
- [ ] YouTube URL import works.
- [ ] Preview frame loads.
- [ ] ROI can be selected and adjusted.
- [ ] ROI health diagnostics appear and are understandable.
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
- [ ] macOS artifact exists in `dist/` as a DMG.
- [ ] Windows artifact exists in `dist/` as an installer.
- [ ] `dist/latest-mac.yml` or `dist/latest.yml` exists when using `dist:release`.
- [ ] Packaged backend version matches source version.
- [ ] Packaged backend still includes the expected YouTube download strategy and ffmpeg handoff checks.

## Release Operations

- [ ] Commit the version bump and release note changes.
- [ ] Push the release commit.
- [ ] Create a new tag `vX.Y.Z`.
- [ ] Push the new tag.
- [ ] Confirm GitHub Actions release workflow starts from the tag push.
- [ ] Confirm release assets are uploaded for both public targets.
- [ ] Verify the GitHub release notes describe user-visible changes and known limitations.

## Known Limitations To State Publicly

- [ ] macOS build is currently unsigned, so Gatekeeper warnings are expected.
- [ ] macOS Intel or universal builds are not part of the default release target unless explicitly added.
- [ ] Auto-update is not part of the current release checklist unless updater support is intentionally introduced.

## Version Decision Rule

- [ ] Use `1.0.0` only if this release is intended to be the first stable public baseline, the workflow is stable, and the manual smoke tests pass on target platforms.
- [ ] Use `0.1.22` or `0.2.0` instead if you still expect release-process churn, platform-policy changes, or one more round of post-release fixes.
- [ ] Never overwrite the existing `v0.1.21` tag for a new public build; cut a new version.
