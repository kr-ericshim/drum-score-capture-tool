---
phase: 01
slug: score-style-export-header-and-layout
status: approved
shadcn_initialized: false
preset: none
created: 2026-04-19
reviewed_at: 2026-04-19
---

# Phase 01 — UI Design Contract

> Visual and interaction contract for the export-time score metadata flow. This locks how renderer-v2 adds a document-info modal without collapsing the existing export screen into a long form.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none |
| Preset | not applicable |
| Component library | none — dependency-free renderer-v2 HTML/CSS/ES modules |
| Icon library | none for new Phase 1 controls — text-first actions only |
| Font | `Pretendard`, `SUIT`, `Noto Sans KR`, `Apple SD Gothic Neo`, `Segoe UI`, sans-serif |

---

## Information Hierarchy

| Layer | Contract |
|-------|----------|
| Layer 1 | Export screen still reads as `preflight + dominant preview stage`. The right preview workbench remains the first thing the eye lands on. |
| Layer 2 | Left configuration stack stays compact: format, processing profile, output directory, and one primary action only. No always-visible metadata form is allowed here. |
| Layer 3 | If PDF is selected, the primary action opens a centered document-info modal. The modal becomes the temporary focal surface, but the export workbench remains visible behind a dark scrim. |
| Layer 4 | Inside the modal, title is the top anchor, performer/BPM/date are supporting metadata rows, and memo is the only long-form field. |

Above-the-fold rules:

- The export screen must not gain a second permanent column, accordion, or settings slab for metadata.
- The right preview stage must stay visually heavier than the left stack on desktop.
- The modal must feel like a `score document sheet`, not like a generic app settings dialog.
- Blank metadata lines are not previewed as placeholders or empty rails.
- The modal is only a confirmation surface for document identity; it is not a second export wizard.

---

## Visual Contract

Primary focal points:

- **Default export screen:** the right preview workbench with the ROI-derived page artifact.
- **Modal-open state:** a paper-toned centered card on top of the dark workstation shell.

Visual rules:

- The modal card uses the existing paper surface token family, not another glossy or SaaS card treatment.
- The modal heading area should borrow real score cues: centered title rhythm, restrained divider lines, and quiet metadata rows.
- No icon-only controls in the modal. Every action is text-labeled.
- Do not add chips, pills, or decorative badges to explain the metadata fields.
- The preview workbench behind the modal remains legible enough to preserve context, but it is visually demoted by a dark scrim.

Document-style header preview rules:

- The modal may include a small static specimen or layout hint for the score-style header, but it must stay subordinate to the form.
- The final PDF header style is centered-title-first, with secondary metadata aligned beneath or around it in a restrained score-like composition.
- The score-like styling is typographic, not ornamental. No fake manuscript textures, flourish icons, or theatrical frames.

---

## Interaction Contract

| Area | Contract |
|------|----------|
| Entry trigger | If selected formats include `pdf`, the export primary CTA opens the document-info modal. If the selection is PNG-only, export starts directly and the modal is skipped. |
| Focus | Modal opens with the title field focused. Focus is trapped until the user confirms or exits intentionally. |
| Exit | Closing a clean modal returns immediately to export. Closing a dirty modal requires explicit confirmation before discarding input. |
| Requiredness | Title is required because it anchors the score-style layout. Performer, BPM, date, and memo are optional. |
| Defaults | Title defaults from source filename. Date defaults to today. Performer, BPM, and memo start empty. |
| Optional fields | Optional fields may be cleared completely. Cleared fields do not leave empty rows in the PDF header. |
| BPM input | BPM accepts digits only. The UI may show `BPM` as a suffix/label, but not as freeform body copy inside the field value. |
| Memo | Memo is a short note field, not a long document editor. Limit visible height to a compact 2-line field on desktop before expansion or wrap. |
| Confirmation | Confirming the modal writes the normalized metadata into export state, then starts the existing export job creation flow. |
| Progress handoff | Once export starts, the modal disappears and the existing export screen regains focus with normal progress behavior. |

PNG-only fallback:

- The export screen should not force the user through a document-info step if PDF is not part of the requested output.
- If the user deselects PDF, any passive helper copy about document metadata should demote itself or disappear.

Dirty-close confirmation:

- Dirty means any user-edited value differs from the current initialized defaults.
- The discard confirmation is a lightweight confirmation row or small alert surface, not a second modal stacked on top of the first one.

---

## Component Contract

| Component | Contract |
|-----------|----------|
| `ExportScreen` | Preserves the existing two-region workbench. It may add one compact helper note about PDF document info, but cannot become a stacked metadata form. |
| `ExportPrimaryAction` | Single dominant action in the header zone. Label is PDF-aware. Behavior changes with format selection, but layout position does not. |
| `ExportMetadataModal` | Centered paper-toned card, width-constrained, full keyboard focus handling, dimmed shell background, and strong visual separation from the workbench. |
| `ExportMetadataForm` | Title row spans full width first. Desktop metadata rows use a compact grid. Memo spans full width at the bottom. |
| `ExportMetadataHint` | One muted helper sentence explains that metadata applies to the PDF first page only. It does not compete with field labels. |
| `ExportPreviewWorkbench` | Remains unchanged in structural weight. While modal is open it is visually demoted, not removed. |

Field layout contract:

- Row 1: `제목` full width
- Row 2: `연주자` and `BPM`
- Row 3: `날짜`
- Row 4: `메모` full width

Mobile collapse:

- Below tablet width, rows 2 and 3 collapse into a single-column stack.
- CTA row may stack vertically on narrow screens, but confirm must remain first.

---

## Spacing Scale

Declared values (must be multiples of 4):

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Divider offsets, inline field hints |
| sm | 8px | Tight field gaps, helper-copy separation |
| md | 16px | Default field spacing, button gaps |
| lg | 24px | Modal body padding, module separation |
| xl | 32px | Screen-level workbench gaps, modal header breathing room |
| 2xl | 48px | Primary section break inside the modal or between screen bands |
| 3xl | 64px | Rare desktop-only breathing room around the centered paper card |

Exceptions: none

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.5 |
| Label | 11px | 700 | 1.35 |
| Heading | 22px | 700 | 1.2 |
| Display | 32px | 700 | 1.1 |

Typography rules:

- Export screen headline remains in the existing heading scale; it must not become a marketing hero.
- The modal title field preview and final PDF title logic are allowed to use the display role, but only inside the document-info surface or generated document.
- Metadata labels stay small, uppercase or condensed where appropriate, and visually quieter than entered values.
- Memo/helper copy always stays in body scale, never in label scale.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | #13110d | App background, stage surround, shell chrome |
| Secondary (30%) | #1b1811 | Panels, left config modules, scrim-adjacent surfaces |
| Accent (10%) | #ecb613 | Active step, selected export format, primary CTA, modal confirm CTA, focus ring |
| Destructive | #d28d87 | Dirty-close discard confirmation, destructive validation or irreversible dismiss paths only |

Accent reserved for:

- active `03` export step state
- selected format segment
- one primary CTA at a time
- modal confirm CTA
- focus-visible ring
- progress strip active fill

Document surface exception:

- `#f7f4ec` is allowed only for the paper-toned document-info modal body and any miniature header specimen shown inside it.
- This paper surface is not an accent and must not spread to the full export screen.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Primary CTA (PDF selected) | 문서 정보 입력 |
| Primary CTA (PNG only) | 출력 생성 시작 |
| Modal confirm CTA | PDF 생성 시작 |
| Modal secondary CTA | export 화면으로 돌아가기 |
| Empty state heading | 출력 형식을 먼저 선택하세요 |
| Empty state body | PDF 또는 PNG를 켜면 바로 결과를 만들 수 있습니다. PDF를 포함하면 다음 단계에서 문서 정보를 입력합니다. |
| Error state | 문서 정보를 다시 확인하세요. 제목은 비워둘 수 없고 BPM은 숫자만 입력합니다. |
| Destructive confirmation | 입력 닫기: `입력한 문서 정보를 버리고 export 화면으로 돌아갑니다.` / confirm `버리고 돌아가기` / cancel `계속 입력` |

Default field labels:

- `제목`
- `연주자`
- `BPM`
- `날짜`
- `메모`

Helper and placeholder copy:

- modal helper: `PDF 첫 페이지 상단에만 반영됩니다.`
- title placeholder/fallback hint: `영상 파일명에서 자동 채움`
- performer placeholder: `예: Eric Shim`
- memo placeholder: `예: half-time feel, 4-count intro`

Tone rules:

- All copy must sound like a production tool for an individual player, not a publishing suite and not a marketing app.
- Empty/error states always end with the next step the user can actually take.
- Button labels must describe the resulting action, not a vague UI event.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| none | none | not required |

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS
- [x] Dimension 2 Visuals: PASS
- [x] Dimension 3 Color: PASS
- [x] Dimension 4 Typography: PASS
- [x] Dimension 5 Spacing: PASS
- [x] Dimension 6 Registry Safety: PASS

**Approval:** approved after local contract verification on 2026-04-19
