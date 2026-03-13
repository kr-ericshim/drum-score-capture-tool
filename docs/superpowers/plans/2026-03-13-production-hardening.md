# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop release self-contained, restart-tolerant, and lightly protected without increasing runtime complexity or release size unnecessarily.

**Architecture:** Keep the existing Electron + local FastAPI shape, but harden the contract around it. Packaged apps launch a frozen backend only, backend access is guarded by a lightweight session token, and job metadata persists to disk so restart behavior is predictable.

**Tech Stack:** Electron, Node.js, FastAPI, Pydantic, Python `unittest`, Node `node:test`, electron-builder, PyInstaller

---

## Chunk 1: Standalone Runtime

### Task 1: Enforce packaged runtime presence

**Files:**
- Modify: `desktop/scripts/run-builder.js`
- Modify: `desktop/scripts/validate-packaged-release.js`
- Modify: `desktop/main.js`
- Test: `desktop/tests/validate-packaged-release.test.mjs`

- [ ] **Step 1: Write the failing desktop validation tests**
- [ ] **Step 2: Run the desktop validation tests and confirm they fail**
- [ ] **Step 3: Update builder flow to build the frozen backend before release packaging**
- [ ] **Step 4: Update packaged release validation to require frozen runtime and reject packaged `.venv`**
- [ ] **Step 5: Update packaged app launch logic to require frozen backend in packaged mode**
- [ ] **Step 6: Re-run targeted desktop tests and confirm they pass**

### Task 2: Verify frozen backend build path

**Files:**
- Modify: `backend/scripts/build_frozen_backend.py`
- Test: `backend/tests/test_frozen_runtime_contract.py`

- [ ] **Step 1: Write failing backend tests for runtime contract expectations**
- [ ] **Step 2: Run the backend tests and confirm they fail**
- [ ] **Step 3: Adjust frozen backend build script so release packaging can rely on the expected runtime location**
- [ ] **Step 4: Re-run targeted backend tests and confirm they pass**

## Chunk 2: Lightweight Backend Protection

### Task 3: Add session-token request protection

**Files:**
- Modify: `desktop/preload.js`
- Modify: `desktop/renderer/modules/job-api.js`
- Modify: `backend/app/main.py`
- Test: `desktop/tests/job-api-auth.test.mjs`
- Test: `backend/tests/test_api_auth.py`

- [ ] **Step 1: Write failing renderer and backend auth tests**
- [ ] **Step 2: Run those tests and confirm they fail**
- [ ] **Step 3: Generate and pass a session token from Electron to backend**
- [ ] **Step 4: Attach auth headers in renderer API helpers**
- [ ] **Step 5: Add lightweight backend middleware and protected file-serving route**
- [ ] **Step 6: Re-run targeted auth tests and confirm they pass**

### Task 4: Tighten lightweight input validation

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_auth.py`
- Test: `backend/tests/test_source_validation.py`

- [ ] **Step 1: Write failing tests for invalid URL/path handling**
- [ ] **Step 2: Run those tests and confirm they fail**
- [ ] **Step 3: Add lightweight path normalization and allowed-video-host validation**
- [ ] **Step 4: Re-run targeted validation tests and confirm they pass**

## Chunk 3: Job Persistence

### Task 5: Persist and recover job metadata

**Files:**
- Modify: `backend/app/job_store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_job_store_persistence.py`

- [ ] **Step 1: Write failing persistence and recovery tests**
- [ ] **Step 2: Run those tests and confirm they fail**
- [ ] **Step 3: Persist `job.json` on create/log/state updates and reload jobs on startup**
- [ ] **Step 4: Mark interrupted queued/running jobs as recovered errors during reload**
- [ ] **Step 5: Re-run targeted persistence tests and confirm they pass**

## Chunk 4: Release Gate And Docs

### Task 6: Align release docs and workflows with the real contract

**Files:**
- Modify: `README.md`
- Modify: `README.ko.md`
- Modify: `README.en.md`
- Modify: `docs/release/final-production-checklist.md`
- Modify: `docs/release/github-release-runbook.md`
- Modify: `.github/workflows/release.yml`

- [ ] **Step 1: Update docs to state the frozen-backend standalone contract and required `xattr` guidance**
- [ ] **Step 2: Update release workflow to preserve the lightweight validation path**
- [ ] **Step 3: Review docs and workflow together for contradiction removal**

## Chunk 5: Verification

### Task 7: Run the lightweight release gate

**Files:**
- No code changes expected

- [ ] **Step 1: Run `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`**
- [ ] **Step 2: Run `node --test tests/*.test.mjs` from `desktop/`**
- [ ] **Step 3: Run `npm run check:renderer-syntax`**
- [ ] **Step 4: Run `npm run check:locale-init`**
- [ ] **Step 5: Run `npm run pack:release`**
- [ ] **Step 6: Run `npm run dist:release`**
