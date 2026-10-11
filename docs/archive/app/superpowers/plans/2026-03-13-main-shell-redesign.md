# Main Shell Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the desktop renderer shell to follow the approved mockup-inspired frame while preserving existing source, ROI, export, review, and support behaviors.

**Architecture:** Keep the current Electron renderer state/event logic mostly intact and reshape the shell through targeted HTML/CSS changes plus minimal step-navigation updates in `app.js`. Introduce a review step in the step rail, collapse the old right rail into a stage toolbar under the active workspace, and preserve all existing IDs used by workflow code.

**Tech Stack:** Electron renderer HTML/CSS/vanilla JS, existing renderer syntax checks, custom Node verification script

---

## Chunk 1: Guardrails and Shell Skeleton

### Task 1: Add failing shell verification

**Files:**
- Create: `desktop/scripts/check-shell-redesign.js`

- [ ] **Step 1: Write the failing test**
- [ ] **Step 2: Run `node desktop/scripts/check-shell-redesign.js` and confirm it fails because the new shell markers do not exist yet**
- [ ] **Step 3: Keep the test file as the shell regression check for this redesign**

### Task 2: Restructure the renderer HTML shell

**Files:**
- Modify: `desktop/renderer/index.html`

- [ ] **Step 1: Replace the current hero/sidebar-oriented shell with the approved frame**
- [ ] **Step 2: Keep all existing workflow IDs that power source, ROI, export, result, status drawer, and support sheet logic**
- [ ] **Step 3: Introduce review-step markup and a stage toolbar container below the active workspace**

## Chunk 2: Visual System and Layout

### Task 3: Re-theme the renderer without AI-dashboard styling

**Files:**
- Modify: `desktop/renderer/style.css`

- [ ] **Step 1: Replace the current glossy gradients and oversized hero treatment with a restrained desktop-tool token system**
- [ ] **Step 2: Build the new shell layout: compact header, left step rail, single active workspace, stage toolbar, bottom status drawer**
- [ ] **Step 3: Add responsive rules for 1100px+ desktop widths while keeping ROI dominant**

## Chunk 3: Behavior Wiring

### Task 4: Extend step navigation for the review workspace

**Files:**
- Modify: `desktop/renderer/app.js`

- [ ] **Step 1: Add review-step helpers without breaking the existing source/ROI/export completion logic**
- [ ] **Step 2: Update header and step-rail rendering so active view and progress state remain clear**
- [ ] **Step 3: Keep support sheet, CTA, result review, and status drawer behavior intact after the shell move**

## Chunk 4: Verification

### Task 5: Run renderer verification

**Files:**
- Verify: `desktop/renderer/index.html`
- Verify: `desktop/renderer/style.css`
- Verify: `desktop/renderer/app.js`
- Verify: `desktop/scripts/check-shell-redesign.js`

- [ ] **Step 1: Run `node desktop/scripts/check-shell-redesign.js`**
- [ ] **Step 2: Run `cd desktop && npm run check:renderer-syntax`**
- [ ] **Step 3: Report actual results with evidence only**
