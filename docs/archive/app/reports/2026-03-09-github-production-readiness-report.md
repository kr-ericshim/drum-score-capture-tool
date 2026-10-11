# GitHub Production Readiness Report

Date: 2026-03-09

## Executive Summary

This repository is close to public release readiness, but it was still missing the pieces required for repeatable GitHub production releases.

Before this batch:

- standalone `release` packaging already existed
- Korean and English user guides already existed
- backend pagination and ROI health tests already existed
- local macOS `pack:release` packaging could generate a DMG

The missing production layer was release operations:

- no `LICENSE`
- no public package metadata for Electron release output
- no GitHub release runbook
- no copy-paste ready workflow definitions for CI and release
- no explicit unsigned-by-default policy
- no documented system-language bootstrap policy

This batch closes those gaps inside the repository, while intentionally keeping actual `.github/workflows/*.yml` creation outside the repo because workflow commits are blocked by current permission constraints.

## Verified Current State

### Packaging

- Public build profile: `desktop npm run dist:release`
- Packaging profile maps `release -> compact`
- Standalone Python runtime is still bundled
- Local `npm run pack:release` on macOS arm64 started successfully and produced:
  - `dist/Drum Sheet Capture-0.1.0-arm64.dmg`
  - `dist/Drum Sheet Capture-0.1.0-arm64.dmg.blockmap`

### Verified Issues Found During Inspection

- `desktop/package.json` emitted `description is missed` and `author is missed`
- no production icon was configured during the initial inspection, so packaging fell back to the default Electron icon
- local macOS environment auto-discovered an Apple signing identity and started signing
- after forcing unsigned mode, macOS arm64 packaging skipped signing explicitly and still produced artifacts, but build logs warn that arm64 normally expects signing
- repository had no `.github/workflows`
- repository had no root `LICENSE`
- backend `.venv` did not include `pytest`, so the reproducible test path is direct `unittest` execution

### Validation Completed

- `PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_sheet_finalize.py`
- `PYTHONPATH=backend backend/.venv/bin/python backend/tests/test_roi_health.py`
- renderer/module syntax checks through `node --check`

## Changes Completed In This Batch

### Release Metadata And Policy

- Added MIT `LICENSE`
- Added public package metadata in `desktop/package.json`
  - `description`
  - `author`
  - `license`
  - `repository`
  - `homepage`
  - `bugs`
- Added desktop validation scripts:
  - `npm run check:renderer-syntax`
  - `npm run check:locale-init`

### Packaging Hardening

- Production release target scope is now explicitly:
  - Windows `x64` NSIS installer
  - macOS `arm64` DMG
- Linux public release target was removed from packaging config
- Release builds are now unsigned by default
  - `DRUMSHEET_ENABLE_SIGNING=false` is the default behavior
  - `CSC_IDENTITY_AUTO_DISCOVERY=false` is forced unless signing is explicitly enabled
- macOS signing is skipped by default through builder config unless signing is intentionally enabled later

### Locale Policy

- Production default language policy is now formally documented:
  - saved `drum-sheet-language` takes precedence
  - if no saved value exists, detect system locale
  - `ko*` starts in Korean
  - everything else starts in English
- Added a static verification script that checks bootstrap and renderer locale initialization policy alignment

### Release Documentation

- Added a GitHub production release runbook
- Included complete, copy-paste ready `ci.yml` and `release.yml` definitions inside the runbook
- Kept workflow files out of `.github/workflows/` to respect current permission constraints

## Deferred Items

These are intentionally not solved in this batch.

### App Icon

- A temporary production icon is now wired for packaging
- Current builder resources include:
  - `desktop/build/icon.icns`
  - `desktop/build/icon.ico`
  - `desktop/build/icon.png`
- The icon should still be treated as a replaceable v1 asset
- Deferred follow-up is now icon refinement, not icon wiring

### Code Signing And Notarization

- Unsigned release is the current production default
- macOS arm64 unsigned artifacts are buildable, but users should expect stricter platform trust warnings until signing and notarization are added
- Deferred follow-up work:
  - Windows code signing
  - macOS signing
  - macOS notarization
  - secret management for certificates

### Broader macOS Distribution

- Current official GitHub release target is Apple Silicon only
- Intel macOS support and universal builds are deferred

## GitHub Release Operating Model

- Release trigger: Git tag push matching `v*`
- Version source of truth: `desktop/package.json`
- GitHub workflow files are not committed in this batch
- The user should create them directly in GitHub web UI using the YAML from `docs/release/github-release-runbook.md`

## Required GitHub Secrets And Envs

### Required Now

- No extra signing secret is required for the unsigned release path
- `GITHUB_TOKEN` is sufficient for release upload inside GitHub Actions

### Reserved For Future Signing Work

- macOS signing/notarization secrets
- Windows signing certificate secrets

## Acceptance Checklist

- MIT license exists at repo root
- package metadata warnings for `description` and `author` are removed
- release build defaults to unsigned packaging
- public release targets are Windows `x64` and macOS `arm64`
- locale bootstrap policy is documented and statically verifiable
- runbook contains full workflow YAML that can be pasted into GitHub web UI
