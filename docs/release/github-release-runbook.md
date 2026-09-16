# GitHub Release Runbook

## Overview

This repository now keeps the GitHub workflow files in-tree.

The workflow YAML below must stay aligned with:

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `desktop/scripts/run-builder.js`
- `desktop/scripts/validate-packaged-release.js`
- `desktop/scripts/smoke-packaged-electron.js`
- `desktop/scripts/smoke-packaged-runtime.js`

## Release Defaults

- Public release trigger: tag push matching `v*`
- Preflight trigger: push a `codex/release-*` branch, or manually dispatch the workflow. Preflight builds both installers and stores Actions artifacts without publishing a release.
- Publishing is a separate job that waits for both platform builds and their packaged smoke tests to succeed.
- Version source of truth: `desktop/package.json`
- Public targets:
  - Windows `x64` NSIS installer
  - macOS `arm64` DMG
- Default release policy: unsigned
- Packaging configuration: `desktop/electron-builder.config.js` only; `desktop/package.json` contains application metadata and commands.
- `release` resolves to the `compact` profile. Development virtualenvs, backend tests, jobs, and renderer tests are excluded.
- `dist:release` builds the frozen backend once, packages it, and validates the resulting payload. CI then runs both smoke checks against that same packaged runtime; do not add a separate preliminary backend build.
- Successful `pack` and `dist` validation writes `dist/package-size-<platform>.json` with installed app/component sizes and, for `dist`, compressed installer sizes. Values are logical file bytes excluding symlinks, not allocated disk blocks.
- Initial language policy:
  - saved `drum-sheet-language` wins
  - otherwise `ko*` system locales start in Korean
  - all other locales start in English

## Pre-Release Checklist

1. Update `desktop/package.json`, both version fields in `desktop/package-lock.json`, and the FastAPI version in `backend/app/main.py`; add `docs/release/release-notes-vX.Y.Z.md`. Run `node desktop/scripts/check-release-version.js`. Tag builds reject an exact tag/version mismatch before installing dependencies.
2. Review `README.md`, `README.ko.md`, `README.en.md`
3. Run local checks

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
backend/.venv/bin/pip install -r backend/requirements-build.txt

cd desktop
npm ci
npm run test:desktop-smoke
npm run verify:renderer-v2
npm run test:desktop-node
npm run test:packaged-release
npm run dist:release
npm run smoke:packaged-electron
npm run smoke:packaged-runtime
```

4. Commit the release changes
5. Push the branch
6. Create tag `vX.Y.Z`
7. Push the tag

```bash
git tag v0.1.0
git push origin v0.1.0
```

## GitHub Secrets

### Required For Current Unsigned Release Path

- no extra signing secret required
- built-in `GITHUB_TOKEN` is enough

### Reserved For Future Signing Work

- macOS signing and notarization credentials
- Windows code-signing certificate credentials

## CI Workflow

The authoritative CI definition is `.github/workflows/ci.yml`. Do not keep a copied YAML block in this runbook; it drifts too easily. Before tagging a release, confirm the workflow still runs the backend suite, `verify:renderer-v2`, and desktop node tests on both `macos-15` and `windows-latest`.

## Release Workflow

The authoritative release workflow is `.github/workflows/release.yml`. Do not keep a copied YAML block in this runbook; it drifts too easily. Before tagging a release, confirm the workflow still:

- runs on `windows-latest` and `macos-15`
- installs backend build dependencies and runs the backend unittest suite
- builds the frozen backend runtime
- runs desktop smoke, renderer-v2, and desktop node checks
- runs `npm run dist:release`
- runs packaged Electron and packaged runtime smoke tests
- verifies non-empty, versioned installers and stores them as Actions artifacts
- publishes both installers and the matching release notes only after both matrix jobs pass, and only for a version tag push
- preserves package size reports as separate Actions artifacts

## Locale Bootstrap Verification

The workflow runs `npm run verify:renderer-v2`, which includes `desktop/scripts/check-locale-init.js`.

It verifies:

- `index.html` bootstrap reads `drum-sheet-language`
- stored locale wins over system locale
- `ko*` resolves to `ko`
- everything else resolves to `en`
- renderer `i18n.js` applies the same policy

## Packaged Backend Source-Text Checks

`desktop/scripts/validate-packaged-release.js` still checks a few packaged backend source markers because current release packages intentionally ship the backend source tree next to the frozen runtime. Treat these as source-package compatibility and stale-copy checks only.

Packaged behavior is gated in two layers: `npm run smoke:packaged-electron` starts the generated Electron app and waits for its backend to expose `/health` and `/runtime`; `npm run smoke:packaged-runtime` starts the backend executable from the generated `dist/` payload, reads `/runtime`, extracts a preview frame from a generated synthetic score video, and runs a capture job through PNG/PDF export with file-signature checks. This is a synthetic local-file test, not YouTube coverage or visual validation of musical notation.

## Unsigned Release Notes

- current production release is intentionally unsigned
- this avoids accidental local certificate auto-discovery
- macOS arm64 builds can still be produced in this mode, but Gatekeeper or trust warnings should be expected until signing and notarization are introduced
- Windows x64 installers can still be produced in this mode, but SmartScreen or publisher trust warnings should be expected until Windows code signing is introduced
- public install docs must include the exact `xattr` command below
- if a user reports that macOS blocked the DMG or app, document this workaround:

```bash
xattr -dr com.apple.quarantine "/Applications/Drum Sheet Capture.app"
```

- if the DMG itself is blocked before opening, the same command can be run on the downloaded DMG path first
- if signing is introduced later:
  - set `DRUMSHEET_ENABLE_SIGNING=true`
  - provide the necessary platform certificates and secrets
  - revise both the builder config and the release workflow

## Deferred Follow-Ups

- icon refinement or replacement
- Windows code signing
- macOS signing and notarization
- Intel macOS or universal builds
