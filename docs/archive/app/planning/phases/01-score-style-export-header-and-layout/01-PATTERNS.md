# Phase 01: Score-Style Export Header And Layout - Pattern Map

**Mapped:** 2026-04-19  
**Files analyzed:** 16  
**Analogs found:** 16 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `desktop/renderer-v2/src/app/session/selectors.js` | state owner | transform | `desktop/renderer-v2/src/app/session/selectors.js` | exact |
| `desktop/renderer-v2/src/app/App.js` | controller | event-driven | `desktop/renderer-v2/src/app/App.js` | exact |
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | screen | event-driven | `desktop/renderer-v2/src/features/export/ExportScreen.js` | exact |
| `desktop/renderer-v2/src/lib/i18n.js` | copy registry | transform | `desktop/renderer-v2/src/lib/i18n.js` | exact |
| `desktop/renderer-v2/src/styles/layout.css` | layout | visual contract | `desktop/renderer-v2/src/styles/layout.css` | exact |
| `desktop/renderer-v2/src/styles/components.css` | component styling | visual contract | `desktop/renderer-v2/src/styles/components.css` | exact |
| `desktop/renderer-v2/src/tests/export-screen.test.js` | render test | transform | `desktop/renderer-v2/src/tests/export-screen.test.js` | exact |
| `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` | runtime-flow test | event-driven | `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` | exact |
| `desktop/renderer-v2/src/tests/session-selectors.test.js` | selector test | transform | `desktop/renderer-v2/src/tests/session-selectors.test.js` | exact |
| `desktop/renderer-v2/src/tests/export-header-modal.test.js` | modal regression test | event-driven | `desktop/renderer-v2/src/tests/export-screen.test.js` | family-match |
| `backend/app/schemas.py` | schema boundary | validation | `backend/app/schemas.py` | exact |
| `backend/app/main.py` | API/controller seam | request-response | `backend/app/main.py` | exact |
| `backend/app/pipeline/export.py` | export compositor | transform | `backend/app/pipeline/export.py` | exact |
| `backend/tests/test_job_api_contract.py` | API contract test | request-response | `backend/tests/test_job_api_contract.py` | exact |
| `backend/tests/test_review_export.py` | staged review-export test | request-response | `backend/tests/test_review_export.py` | exact |
| `backend/tests/test_review_export_refinalization.py` | export pipeline parity test | transform | `backend/tests/test_review_export_refinalization.py` | exact |
| `backend/tests/test_export_document_header.py` | document-header compositor test | transform | `backend/tests/test_review_export_refinalization.py` | family-match |

## Pattern Assignments

### Renderer State And Action Ownership

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/app/session/selectors.js` | itself | Export-facing state is already centralized under `exportConfig`; Phase 1 should extend that tree instead of inventing DOM-local metadata state. |
| `desktop/renderer-v2/src/app/App.js` | itself | `buildJobPayload()` and `runExport()` are the only trustworthy bridge from renderer state to backend jobs. |
| `desktop/renderer-v2/src/tests/session-selectors.test.js` | itself | Selector/state regressions are already protected here and should absorb the new metadata defaults and reset behavior. |
| `desktop/renderer-v2/src/tests/app-runtime-flows.test.js` | itself | Existing runtime tests already prove payload timing, stale-state clearing, and export start semantics. |

**Canonical session shape seam** from `desktop/renderer-v2/src/app/session/selectors.js`:

```js
export function createInitialSessionState() {
  return {
    ...
    exportConfig: {
      formats: DEFAULT_FORMATS.slice(),
      outputDir: "",
      pageFillMode: "performance",
      layoutHint: "auto",
      jobId: "",
      runStatus: "idle",
      progress: 0,
      currentStep: "",
      message: "",
      pdfPath: "",
      error: "",
    },
    ...
  };
}
```

**Canonical export payload seam** from `desktop/renderer-v2/src/app/App.js`:

```js
function buildJobPayload(state) {
  const roi = state.roi.appliedRect;
  const layoutHint = inferLayoutHintFromRoi(roi);
  return {
    source_type: "file",
    file_path: state.source.filePath,
    options: {
      ...
      export: {
        formats: state.exportConfig.formats.slice(),
        include_raw_frames: false,
        page_fill_mode: "performance",
      },
    },
  };
}

async function runExport() {
  const state = store.getState();
  ...
  const jobId = await runtimeApi.createJob(buildJobPayload(state));
}
```

**Pattern rule:** put normalized document metadata under `state.exportConfig` and only hand it to the backend through `buildJobPayload(state)`. Do not create a second ad-hoc payload object at click time.

### Export Screen Composition And Copy

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `desktop/renderer-v2/src/features/export/ExportScreen.js` | itself | The export view already follows the required `preflight + dominant preview` contract. |
| `desktop/renderer-v2/src/lib/i18n.js` | itself | All labels and helper copy already flow through translation keys, so Phase 1 modal text must land here. |
| `desktop/renderer-v2/src/styles/layout.css` | itself | Desktop/mobile layout rules for the export workbench already live here. |
| `desktop/renderer-v2/src/styles/components.css` | itself | Export surface styling, panel styling, and paper-tone surface tokens are already defined here. |
| `desktop/renderer-v2/src/tests/export-screen.test.js` | itself | Screen-level render assertions already lock the export workbench against drift into fake controls or generic forms. |
| `desktop/renderer-v2/src/tests/export-header-modal.test.js` | `desktop/renderer-v2/src/tests/export-screen.test.js` | New modal tests should keep the same direct `node:test` string-assert style. |

**Canonical export screen pattern** from `desktop/renderer-v2/src/features/export/ExportScreen.js`:

```js
return `
  <section class="screen screen-export" ...>
    <header class="screen-headline screen-headline-export">
      ...
      <div class="screen-inline-actions">
        <button class="button button-primary" data-action="run-export" ...>${model.primaryActionLabel}</button>
      </div>
    </header>
    <div class="export-workbench">
      <div class="export-config-stack" data-stitch-region="export-config">...</div>
      <section class="export-preview-workbench" data-stitch-region="export-preview">...</section>
    </div>
  </section>
`;
```

**Canonical export layout pattern** from `desktop/renderer-v2/src/styles/layout.css`:

```css
.export-workbench {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  gap: 24px;
  padding: 22px 24px 24px;
  min-height: 0;
  overflow-y: auto;
}

@media (max-width: 1100px) {
  .export-workbench {
    grid-template-columns: 1fr;
  }
}
```

**Canonical paper token** from `desktop/renderer-v2/src/styles/tokens.css`:

```css
:root {
  --surface-paper: #f7f4ec;
  --accent: #ecb613;
  --danger: #d28d87;
}
```

**Pattern rule:** add the document-info modal as an overlay on top of this workbench. Do not convert the left stack into a permanent metadata form and do not move the primary preview out of the right stage.

### Backend Export Contract And Review Reuse

**Apply to**

| File | Analog | Why this is the copy source |
|------|--------|-----------------------------|
| `backend/app/schemas.py` | itself | Export options already have the only sanctioned validation seam. |
| `backend/app/main.py` | itself | `_run_job()` and `review_export()` are the two export entrypoints that must stay aligned. |
| `backend/app/pipeline/export.py` | itself | The repo already has one PDF composition path; header rendering should extend it, not bypass it. |
| `backend/tests/test_job_api_contract.py` | itself | Backend contract validation is already enforced here. |
| `backend/tests/test_review_export.py` | itself | Review-export reuse and staged workspace behavior are already protected here. |
| `backend/tests/test_review_export_refinalization.py` | itself | Existing tests already prove export-selected-pages parity and preview-image behavior. |
| `backend/tests/test_export_document_header.py` | `backend/tests/test_review_export_refinalization.py` | New PDF header tests should reuse the same image-fixture generation style. |

**Canonical schema seam** from `backend/app/schemas.py`:

```python
class ExportOptions(BaseModel):
    formats: List[Literal["png", "jpg", "jpeg", "pdf"]] = Field(default_factory=lambda: ["png", "pdf"])
    output_dir: Optional[str] = None
    include_raw_frames: bool = False
    page_fill_mode: PageFillMode = "performance"
```

**Canonical review-export reuse seam** from `backend/app/main.py`:

```python
if isinstance(job.options, dict):
    export_opts = job.options.get("export")
    if isinstance(export_opts, dict):
        candidate_formats = export_opts.get("formats")
        ...
        candidate_page_fill_mode = str(export_opts.get("page_fill_mode") or "").strip().lower()
        ...

export_result = export_selected_pages(
    page_paths=page_paths,
    formats=[str(value) for value in requested_formats],
    page_fill_mode=configured_page_fill_mode,
    workspace=staged_export_workspace,
    logger=lambda msg: _append(job_id, msg),
)
```

**Canonical PDF composition seam** from `backend/app/pipeline/export.py`:

```python
finalized_pages = _finalize_export_pages(source_images, page_fill_mode=page_fill_mode)
...
if wants_pdf:
    pdf_path = workspace / "sheet_export.pdf"
    pil_images = [_prepare_pdf_image(img) for img in pdf_images]
    first, *rest = pil_images
    first.save(pdf_path, "PDF", save_all=True, append_images=rest, ...)
```

**Pattern rule:** store `document_header` in `job.options["export"]`, thread it into both export entrypoints, and compose the PDF header from one shared helper before `_prepare_pdf_image(...)`.

### Test Extension Style

**Renderer test idiom** from `desktop/renderer-v2/src/tests/export-screen.test.js`:

```js
test("export primary action is disabled when no formats are selected", () => {
  const state = createInitialSessionState();
  ...
  const markup = renderExportScreen(state);
  assert.match(markup, /data-action="run-export"[^>]*disabled/);
});
```

**Runtime-flow test idiom** from `desktop/renderer-v2/src/tests/app-runtime-flows.test.js`:

```js
await root.dispatchAction("run-export");
await flush();
assert.equal(createJobCalls, 0);
assert.match(app.debug.getState().exportConfig.error, /형식|format/i);
```

**Backend unittest idiom** from `backend/tests/test_review_export.py`:

```python
with (
    patch("app.main.job_store", store),
    patch("app.main.export_selected_pages") as export_selected_pages,
):
    response = review_export(...)

export_selected_pages.assert_called_once()
self.assertEqual(response.images, [...])
```

**Pattern rule:** keep tests focused and seam-specific. Renderer tests should continue using `node:test` plus direct string/state assertions; backend tests should continue using `unittest`, temp dirs, and patch-based seam isolation.
