# GitHub Release Runbook

## Overview

This repository does not commit GitHub workflow files directly in the current batch.

Reason:

- workflow push permissions are currently blocked
- the YAML below is the source of truth for manual GitHub web entry

Create these files manually in GitHub:

1. `.github/workflows/ci.yml`
2. `.github/workflows/release.yml`

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
PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_sheet_finalize.py
PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_roi_health.py

cd desktop
npm ci
npm run check:renderer-syntax
npm run check:locale-init
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

Create `.github/workflows/ci.yml` with this content:

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

Create `.github/workflows/release.yml` with this content:

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

      - name: Install backend dependencies
        run: python -m pip install -r backend/requirements.txt

      - name: Install desktop dependencies
        working-directory: desktop
        run: npm ci

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
- if signing is introduced later:
  - set `DRUMSHEET_ENABLE_SIGNING=true`
  - provide the necessary platform certificates and secrets
  - revise both the builder config and the release workflow

## Deferred Follow-Ups

- icon refinement or replacement
- Windows code signing
- macOS signing and notarization
- Intel macOS or universal builds
