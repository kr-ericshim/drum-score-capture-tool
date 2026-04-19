# Archive Library Design

Date: 2026-04-19

## Goal

Add a lightweight archive library to `renderer-v2` so the user can reopen previously completed score outputs without leaving the app.

The archive is not a version-history feature. It is a fast shortcut to the latest valid final PDF for each source.

## Approved Constraints

- The archive entry point lives in the top bar and is always visible in every step.
- The archive list is sorted by most recent completed work first.
- The archive item detail stays minimal:
  - display name
  - completed date
  - open PDF
  - open folder
- The archive should not keep multiple historical versions for the same source.
- If the user re-exports the same source, the archive should behave like an overwrite and point to the latest final PDF only.
- The archive should only show sources that currently have a final PDF.
- Display naming rules are:
  - YouTube: original video title
  - local file: original filename stem

## Current State

- `renderer-v2` already has persistent workflow state for source, ROI, export, and review.
- The current top bar has locale controls and runtime status only.
- The current review step already supports `open-output-pdf` and `open-output-dir`.
- The backend persists each export job under `backend/jobs/<job_id>/job.json`.
- The existing `/library/local-media` endpoint is a source registry, not an archive API.
- `/library/local-media` merges items by `source_path`, which collapses repeated work into one source entry.
- YouTube preparation currently promotes the downloaded file basename into `source.displayName`, so user-facing names can degrade into cache-style filenames.
- Export jobs always run with `source_type: "file"` after YouTube preparation, which means the original normalized YouTube URL is no longer present in the final export payload by default.

## Problem

The app can open the current export result, but it does not provide a durable, clean way to reopen prior final score outputs.

Two concrete product gaps exist:

1. There is no archive-oriented UI surface for reopening finished PDFs.
2. The current naming contract is wrong for prepared YouTube sources because the user sees the cached download filename rather than the original video title.

## Decision

Add a dedicated archive-library flow rather than trying to reuse the existing source registry UI or data contract as-is.

The system will treat the archive as a per-source latest-final-output index:

- one archive row per source
- latest successful final PDF wins
- no historical version list

The existing source registry remains focused on loading source media. The archive becomes a separate, output-oriented surface.

## Options Considered

### Option 1: Reuse `/library/local-media` and show it as the archive

Rejected. That endpoint is source-centric, merges by local file path only, and cannot safely preserve YouTube identity after file-backed export.

### Option 2: Add a dedicated archive-library API and UI while keeping the current job storage

Approved. This preserves the existing job persistence model, keeps scope tight, and avoids a new database or archive index.

### Option 3: Add full result versioning with multiple historical outputs per source

Rejected. The approved user behavior is overwrite-like rather than history-oriented.

## Product Contract

### What the archive is

- A quick-access library of the latest final PDF per source
- Always reachable from the top bar
- Read-only from the archive surface

### What the archive is not

- Not a source registry
- Not a recovery tool for resuming past workflow state
- Not a version history of every export
- Not a thumbnail browser

## Source Identity Contract

To support stable overwrite semantics, the archive must group jobs by a durable source identity that survives file-backed YouTube export.

### Source identity rules

- Local file source key: resolved source file path
- YouTube source key: normalized YouTube URL

### Source kind

- `file`
- `youtube`

### Display name rules

- Local file display name: filename stem from the selected source path
- YouTube display name: original video title returned by the YouTube metadata/download path

### Why this matters

The current export pipeline always sends `source_type: "file"` after YouTube preparation. Without a separate source-identity payload, the backend can no longer know that two cached files came from the same YouTube URL.

## Architecture

### Backend

Keep the existing job persistence model but add a dedicated archive endpoint and explicit source identity metadata for export jobs.

Additions:

- `GET /library/archive`
  - returns archive rows sorted by latest completed final PDF first
  - returns one row per source key
  - excludes items whose final PDF is missing

The existing `/library/local-media` endpoint stays unchanged in product meaning and remains source-registry only.

### Renderer

Add an always-visible top-bar archive button that opens a single modal shell.

That modal shell supports two internal views:

- archive list
- archive detail

This avoids nested modal behavior while still feeling like detail is opened inside the archive.

## Data Model

### Renderer session additions

Extend `source` state so it can preserve archive identity across YouTube preparation:

- `archiveSourceKind`
- `archiveSourceKey`
- `archiveDisplayName`

Rules:

- For local file selection:
  - `archiveSourceKind = "file"`
  - `archiveSourceKey = resolved file path`
  - `archiveDisplayName = filename stem`
- For completed YouTube preparation:
  - `archiveSourceKind = "youtube"`
  - `archiveSourceKey = normalized youtube URL`
  - `archiveDisplayName = original video title`

The existing `source.filePath` still remains the canonical file path for ROI/export runtime work.

### Prepare-job response additions

Successful YouTube prepare results should include:

- `video_path`
- `video_url`
- `from_cache`
- `video_title`
- `source_key`

`source_key` is the normalized YouTube URL.

### Export job payload additions

Because export now runs file-backed even for prepared YouTube sources, the renderer must send archive identity metadata explicitly with the export request.

Approved shape:

- `source_identity.kind`
- `source_identity.key`
- `source_identity.display_name`

This should travel alongside the existing export job payload and be persisted with the job record.

### Job persistence additions

Each final export job should persist:

- `source_identity.kind`
- `source_identity.key`
- `source_identity.display_name`
- `completed_at`

The final result should continue to persist:

- `pdf`
- `output_dir`
- `review_export` when present

### Archive row shape

Each archive item should contain:

- `source_key`
- `source_kind`
- `display_name`
- `completed_at`
- `pdf_path`
- `output_dir`

## Final PDF Resolution Rules

The archive must resolve the final PDF for a source using these rules:

1. Start from completed export jobs only.
2. Group rows by `source_identity.key`.
3. For each group, pick the newest valid final output.
4. If `review_export` produced a replacement PDF, treat that PDF as the final output.
5. If the resolved final PDF file no longer exists, exclude that source from the archive.

This intentionally produces overwrite-like behavior rather than historical version stacking.

## UX Contract

### Top bar

- Add a `보관함` / `Archive` button in the top-bar tools area.
- The button is visible in every step.
- Opening the archive must not reset the current workflow state.

### Archive modal shell

The archive uses a single modal shell with internal view switching:

- list view
- detail view

This is preferred over true modal-on-modal stacking for focus management and predictable close behavior.

### List view

The list view shows:

- display name
- completed date

Behavior:

- sorted newest first
- one row per source
- clicking a row enters detail view

### Detail view

The detail view shows:

- display name
- completed date
- `Open PDF`
- `Open Folder`
- `Back`

No thumbnails, page previews, or version controls are included in this iteration.

### Modal close behavior

- `ESC` closes the archive
- backdrop click closes the archive
- close button closes the archive
- closing the archive returns the user to the same workflow step they were on before opening it

## Error Handling

### Empty state

If there are no valid archive rows:

- show a short empty-state message only
- do not over-design the CTA

Approved copy:

- `아직 저장된 최종 PDF가 없습니다.`

### Missing file state

If the detail row exists but one path is missing:

- missing `pdf_path` disables `Open PDF`
- missing `output_dir` disables `Open Folder`

If both are missing, that row should not appear in the archive list.

### Archive load failure

If the archive request fails:

- keep the modal open
- show a short failure message
- provide a retry action

## Testing

### Backend

- archive grouping keeps only the latest final PDF per local file path
- archive grouping keeps only the latest final PDF per normalized YouTube URL
- review-export PDF replaces the base export PDF as the final archive target
- rows with missing final PDF are excluded
- YouTube rows use original video title, not cached basename

### Renderer

- top bar shows archive button in every step
- archive modal opens without mutating current workflow step
- list view sorts newest first
- detail view shows only the approved fields/actions
- `Open PDF` and `Open Folder` reuse existing path-opening behavior
- missing-path disabled states are correct
- empty-state and load-failure states render correctly

## Implementation Notes

- Do not redefine the meaning of the existing source registry.
- Do not add version history to this feature.
- Do not use cached download filenames as user-facing archive names for YouTube sources.
- Keep the archive visually light. It should feel like a utility panel, not a second app inside the workflow.
