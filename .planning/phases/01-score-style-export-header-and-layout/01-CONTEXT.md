# Phase 1: Score-Style Export Header And Layout - Context

**Gathered:** 2026-04-19
**Status:** Ready for planning

<domain>
## Phase Boundary

이 phase는 기존 export 흐름을 유지한 채, export 직전에 문서 메타데이터를 받고 PDF 첫 페이지 상단이 실제 악보처럼 읽히는 헤더 레이아웃을 추가하는 작업이다. 계정, 클라우드, 템플릿 시스템, 별도 편집기 같은 새 capability를 여는 단계가 아니라, 현재 `capture -> export` 결과물을 `문서형 악보 output`으로 끌어올리는 단계다.

</domain>

<decisions>
## Implementation Decisions

### Header Field Scope
- **D-01:** v1 헤더 항목은 `제목, 연주자, BPM, 날짜, 메모`만 지원한다.
- **D-02:** `composer, arranger, key` 같은 추가 필드는 Phase 1 범위에서 제외한다.

### Header Presentation
- **D-03:** PDF 헤더는 `정통 악보형`으로 간다. 중앙 큰 제목을 기준으로 그 아래/주변에 핵심 메타정보가 정돈되게 배치한다.
- **D-04:** 결과물은 단순 문서 정보표보다 `흔한 악보처럼 보이는 첫인상`을 우선한다.

### Export Input Flow
- **D-05:** 메타데이터 입력은 export 화면 내부의 상시 폼이 아니라 `export 직전 모달`에서 받는다.
- **D-06:** 기존 export 화면의 `preflight + dominant preview` 성격은 유지해야 하며, 메타데이터 입력 때문에 export 화면이 긴 설정 폼처럼 바뀌면 안 된다.

### PDF Placement Rules
- **D-07:** 메타데이터 헤더는 `첫 페이지 상단만` 들어간다. 모든 페이지 반복 헤더나 별도 표지는 Phase 1 범위가 아니다.
- **D-08:** 첫 페이지에서는 헤더가 눈에 띄도록 `조금 더 큰 타이틀 영역`을 써도 된다.
- **D-09:** 첫 페이지의 헤더 공간은 악보 내용을 덮는 오버레이가 아니라, 상단에서 실제 레이아웃 공간을 차지하는 방식이어야 한다.

### Defaults And Empty-State Behavior
- **D-10:** 빈 항목은 자리만 남기지 말고 `해당 줄 자체를 숨긴다`.
- **D-11:** export 모달이 열릴 때 `제목은 영상 파일명 기반`, `날짜는 오늘 날짜`로 자동 채운다.
- **D-12:** BPM과 메모는 사용자가 직접 채우는 optional 입력으로 시작한다.

### the agent's Discretion
- 정확한 타이포 스케일, 정렬 단위, 선/구분선 사용 여부
- 메모 필드의 라벨 문구와 placeholder
- BPM 입력 형식의 세부 UX(숫자만, `BPM` suffix 노출 방식)
- 메타데이터 모달의 validation microcopy와 confirm/cancel wording

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and product contract
- `.planning/ROADMAP.md` — Phase 1 goal, requirements mapping, and success criteria for score-style export header work
- `.planning/PROJECT.md` — product direction, local-first constraint, target user, and release-quality framing
- `.planning/REQUIREMENTS.md` — `EXP-01` to `EXP-04` definitions and the release scope boundary

### Renderer workflow and visual constraints
- `docs/superpowers/specs/2026-03-15-core-workflow-uiux-redesign-design.md` — Export step must remain a preflight screen, not a settings dump or generic form flow
- `docs/superpowers/specs/2026-03-15-renderer-v2-stitch-fidelity-spec.md` — Export screen composition contract: left config stack + dominant right preview stage
- `docs/superpowers/uiux/design-system/drum-sheet-capture/pages/renderer-v2.md` — renderer-v2 override: workstation direction, no SaaS card drift, stage-first layout rules

### Export screen source-of-truth artifacts
- `stitch_exports/3388746007378073625/export-configuration/screen.html` — export composition reference for panel hierarchy and preview dominance
- `stitch_exports/3388746007378073625/export-configuration/screenshot.png` — visual reference for export screen balance and density

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `desktop/renderer-v2/src/features/export/ExportScreen.js`: current `build...Model` + `render...` pattern for the export screen, including the existing left config stack and right preview workbench
- `desktop/renderer-v2/src/app/session/selectors.js`: canonical initial session shape; `exportConfig` is the natural place to hang export-form state or launch metadata flow
- `desktop/renderer-v2/src/app/App.js`: `buildJobPayload()` and `runExport()` are the existing bridge between renderer state and backend export job creation
- `backend/app/schemas.py`: `ExportOptions` is the backend contract seam for adding document-metadata payload fields
- `backend/app/pipeline/export.py`: current PDF/image export entrypoint; this is where document metadata must be reflected into actual PDF output
- `backend/app/pipeline/sheet_finalize.py`: existing page framing and margin logic; Phase 1 should build on this rather than re-invent page sizing from scratch
- `desktop/renderer-v2/src/tests/export-screen.test.js`: existing export-screen regression tests that can be extended for modal trigger/state/output expectations

### Established Patterns
- Renderer-v2 is state-first: UI enable/disable and summaries are derived from one session tree, not from ad-hoc DOM state
- Renderer-v2 screens use dependency-free HTML/CSS/ES module rendering with dense workstation composition, not framework components or generic modal libraries
- Backend export logic already treats PDF generation as a final composed artifact assembled from finalized page images
- Existing product direction explicitly rejects turning export into a long generic form page

### Integration Points
- Add export-side metadata state to the renderer-v2 session model and wire it through `desktop/renderer-v2/src/app/App.js`
- Extend API payload assembly in `desktop/renderer-v2/src/app/App.js` and backend request parsing in `backend/app/schemas.py`
- Reflect metadata into first-page composition inside `backend/app/pipeline/export.py`, using page framing behavior from `backend/app/pipeline/sheet_finalize.py`
- Preserve screen-level visual contract in `desktop/renderer-v2/src/features/export/ExportScreen.js` and related styles/tests

</code_context>

<specifics>
## Specific Ideas

- User wants the result to feel like `흔한 악보들처럼`, not like a plain capture bundle.
- The motivating complaint was that the current PDF feels like `그냥 음표 캡쳐본만 들어가니까 좀 별로`.
- The first page is allowed to spend a bit more vertical space on the title/header band if that makes the document feel more like a real score.

</specifics>

<deferred>
## Deferred Ideas

### Future Export Depth
- Support for richer metadata such as composer, arranger, key, and custom field definitions — defer to later export-flexibility work
- Multiple score-header templates or visual themes — already deferred in project-level v2 scope

None beyond the items above — discussion stayed within Phase 1 scope.

</deferred>

---

*Phase: 01-score-style-export-header-and-layout*
*Context gathered: 2026-04-19*
