# GitHub Release Runbook

## Overview

This repository now keeps the GitHub workflow files in-tree.

The workflow YAML below must stay aligned with:

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `desktop/scripts/run-builder.js`
- `desktop/scripts/validate-packaged-release.js`

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
npm run check:renderer-syntax
npm run check:locale-init
node --test tests/*.test.mjs
npm run pack:release
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

The committed `.github/workflows/ci.yml` should continue to match this content:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  validate:
    runs-on: macos-14

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

      - name: Install backend dependencies
        run: python -m pip install -r backend/requirements.txt

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

      - name: Run backend pagination tests
        run: PYTHONPATH=backend python backend/tests/test_sheet_finalize.py

      - name: Run backend ROI health tests
        run: PYTHONPATH=backend python backend/tests/test_roi_health.py

      - name: Check renderer syntax
        working-directory: desktop
        run: npm run check:renderer-syntax

      - name: Check locale bootstrap policy
        working-directory: desktop
        run: npm run check:locale-init

      - name: Verify release docs exist
        run: |
          test -f LICENSE
          test -f README.md
          test -f README.en.md
          test -f README.ko.md
          test -f docs/reports/2026-03-09-github-production-readiness-report.md
          test -f docs/release/github-release-runbook.md
```

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
        run: PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_*.py'

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

      - name: Check renderer syntax
        working-directory: desktop
        shell: bash
        run: npm run check:renderer-syntax

      - name: Run desktop node tests
        working-directory: desktop
        shell: bash
        run: node --test tests/*.test.mjs

      - name: Verify locale bootstrap policy
        working-directory: desktop
        run: npm run check:locale-init

      - name: Build release artifacts
        working-directory: desktop
        run: npm run dist:release

      - name: Upload release assets
        uses: softprops/action-gh-release@v2
        with:
          files: |
            ${{ matrix.artifact_glob }}
            dist/*.blockmap
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Locale Bootstrap Verification

The workflow checks `desktop/scripts/check-locale-init.js`.

It verifies:

- `index.html` bootstrap reads `drum-sheet-language`
- stored locale wins over system locale
- `ko*` resolves to `ko`
- everything else resolves to `en`
- renderer `i18n.js` applies the same policy

## Unsigned Release Notes

- current production release is intentionally unsigned
- this avoids accidental local certificate auto-discovery
- macOS arm64 builds can still be produced in this mode, but Gatekeeper or trust warnings should be expected until signing and notarization are introduced
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
