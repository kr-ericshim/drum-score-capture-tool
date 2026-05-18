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

- Release trigger: tag push matching `v*`
- Version source of truth: `desktop/package.json`
- Public targets:
  - Windows `x64` NSIS installer
  - macOS `arm64` DMG
- Default release policy: unsigned
- Initial language policy:
  - saved `drum-sheet-language` wins
  - otherwise `ko*` system locales start in Korean
  - all other locales start in English

## Pre-Release Checklist

1. Update `desktop/package.json` version
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

The authoritative CI definition is `.github/workflows/ci.yml`. Do not keep a copied YAML block in this runbook; it drifts too easily. Before tagging a release, confirm the workflow still runs the backend suite, `verify:renderer-v2`, and desktop node tests on both `macos-14` and `windows-latest`.

## Release Workflow

The committed `.github/workflows/release.yml` should continue to match this content:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            artifact_glob: dist/*.exe
          - os: macos-14
            artifact_glob: dist/*.dmg

    runs-on: ${{ matrix.os }}

    env:
      DRUMSHEET_ENABLE_SIGNING: "false"
      CSC_IDENTITY_AUTO_DISCOVERY: "false"

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: desktop/package-lock.json

      - name: Install backend build dependencies
        shell: bash
        run: |
          python -m pip install --upgrade pip setuptools wheel
          python -m pip install -r backend/requirements-build.txt

      - name: Run backend test suite
        shell: bash
        env:
          PYTHONPATH: backend
        run: python -m unittest discover -s backend/tests -p 'test_*.py'

      - name: Build frozen backend runtime
        shell: bash
        run: |
          python backend/scripts/build_frozen_backend.py
          if [ "$RUNNER_OS" = "Windows" ]; then
            test -f backend/runtime/drumsheet-backend/drumsheet-backend.exe
          else
            test -f backend/runtime/drumsheet-backend/drumsheet-backend
          fi

      - name: Smoke test frozen backend
        shell: bash
        run: |
          mkdir -p "$RUNNER_TEMP/drumsheet-jobs"
          if [ "$RUNNER_OS" = "Windows" ]; then
            BACKEND_BIN="backend/runtime/drumsheet-backend/drumsheet-backend.exe"
          else
            BACKEND_BIN="backend/runtime/drumsheet-backend/drumsheet-backend"
          fi
          DRUMSHEET_PORT=8123 DRUMSHEET_JOBS_DIR="$RUNNER_TEMP/drumsheet-jobs" "$BACKEND_BIN" > "$RUNNER_TEMP/drumsheet-backend.log" 2>&1 &
          BACKEND_PID=$!
          trap 'kill $BACKEND_PID >/dev/null 2>&1 || true' EXIT
          for _ in $(seq 1 18); do
            sleep 5
            if curl -sf http://127.0.0.1:8123/health >/dev/null; then
              exit 0
            fi
          done
          cat "$RUNNER_TEMP/drumsheet-backend.log"
          exit 1

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

      - name: Smoke test desktop startup contract
        working-directory: desktop
        shell: bash
        run: npm run test:desktop-smoke

      - name: Verify renderer-v2
        working-directory: desktop
        shell: bash
        run: npm run verify:renderer-v2

      - name: Run desktop node tests
        working-directory: desktop
        shell: bash
        run: npm run test:desktop-node

      - name: Build release artifacts
        working-directory: desktop
        run: npm run dist:release

      - name: Smoke test packaged Electron app
        working-directory: desktop
        run: npm run smoke:packaged-electron

      - name: Smoke test packaged backend runtime
        working-directory: desktop
        run: npm run smoke:packaged-runtime

      - name: Upload release assets
        uses: softprops/action-gh-release@v2
        with:
          files: |
            ${{ matrix.artifact_glob }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

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

Packaged behavior is gated in two layers: `npm run smoke:packaged-electron` starts the generated Electron app and waits for its backend to expose `/health` and `/runtime`; `npm run smoke:packaged-runtime` starts the backend executable from the generated `dist/` payload, reads `/runtime`, and extracts a preview frame from a generated local video.

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
