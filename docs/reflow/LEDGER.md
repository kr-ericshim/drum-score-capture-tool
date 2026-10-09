# 2C-L: minimal display-member to delivered-PDF ledger

Worker W-E, 2026-10-08, with audit-5 fixes by X4. Implements STRATEGY checkpoint
#2's adjusted minimal ledger. **Both export gates and pre-prune persistence are
now wired. Raw inventory/representation producer hooks remain pending** (list
below); existing jobs without obligations are unassessed and require review.

## Audit 5 integration (X4, 2026-10-08)

- **Finding 5:** inventory is the union of *all* raw photometric foreground,
  independent of usable/occluded masks. Clear foreground and unwitnessed
  foreground have disjoint hypothesis ownership. A blank eligible observation
  never deletes ink offered by an unusable/occluded observation. No clear witness
  means `ambiguous`, with raw evidence retained; even preserving it needs review.
  Candidate boxes omitting it increment `raw_foreground_uninventoried_px`.
- **Finding 6:** `_execute_reflow_job` and `_review_export_reflow` both call
  `_verify_reflow_ledger` immediately after `verify_composed_export`, before
  staged install. `verify_delivered_ledger` reads `record['ledger']` if present,
  otherwise `ledger_path`, otherwise `<reflow workspace>/ledger.json`, and calls
  `verify_pdf` on the staged PDF's actual embedded pages. No PDF means review;
  no persisted items/displays means `assessment='unassessed'`,
  `status='review_required'`, reason `LEDGER_UNASSESSED`. It never reconstructs
  obligations from cleaned strips or an `exact_reconstruction` flag.
- Proven ledger failure blocks install with `LEDGER_VERIFICATION_FAILED`. Initial
  jobs retain systems/evidence and enter ERROR (`reflow_state='ledger_failed'`);
  synchronous and background review exports remain allowed for that error.
  Failed rebuilds retain the previous installed files and result. Small mismatch
  crops/report survive staged cleanup in `ledger_last_attempt.json`.
- `ledger.json` and `ledger_report.json` accompany each successful staged export.
  The job's embedded `reflow.ledger_verification` is the installed result's report;
  `ledger_last_attempt.json` is explicitly the latest attempted verification,
  which can differ after a failed rebuild. API `review_required` and
  `review_reasons` are updated for initial/rebuild results and rebuild responses.
  New reasons carry `{code, text}` with Korean/English fallback copy accepted by
  the renderer; internal `reflow.review_reasons` remains a code list.
- **Finding 7:** `OVERLAY_UNRECOVERED` and `OVERLAY_COVERS_NOTATION` block a clean
  completion claim. Nonzero strip `unrecovered_columns` also supplies the former.
  Selection/reordering and PDF rebuilds cannot clear these reasons; only new
  positive recovery evidence upstream may remove them. `prune_frames` persists
  obligations and copies disposition artifacts into `ledger_evidence/` before
  deleting raw frames. For unresolved overlays it keeps the raw frame directory
  and writes `overlay_review_evidence.json`; `frames_pruned` correctly stays false.
  This can keep more disk data than ordinary pruning, deliberately preserving
  existing observations rather than generating a new decode.

`test_audit5_ledger_gate.py` probes obscured-only ink with a clear blank,
candidate omission, real embedded-JPEG PDF pass/loss, artifact retention across
pruning, static coloured rectangles over a staff, both API gate paths,
transactional failed rebuilds, and overlay reasons surviving selection/rebuild.
The old cursor control now retains unwitnessed raw cursor hypotheses as explicit
alternatives and returns review required; the recovered notation itself is still
checked. Declaring all of those hypotheses `cursor_recovery` would assert clear
support for pixels that only occur in the obscured member.

X4 final verification: full backend **929 tests in 630.113 s: 4 failures,
1 error**; no green full-suite claim. All remaining cases are outside X4's files:
`test_reflow_integration_wf` raw self-check mock rejects `raw_member_window`;
`test_reflow_jump_coverage` complete-coverage fixture expects clean DONE despite
missing ledger/PDF assessment (owner request below);
`test_reflow_jump_preservation` expects a stationary speck to be `screen_fixed`,
but obtains 3 unmatched items; `test_reflow_visibility_marks` fade and
misregistered cases expect no `UNCERTAIN_MARK_KEPT`, but receive it. Owners must
check retained evidence and policy before changing those last three expectations.
The obsolete X4-owned clean-complete assertions were updated and passed on this
final sweep. Targeted suites: audit probes 8/8, ledger 37/37, initial/review export
46/46, explicit mode/review response 4/4. Renderer `verify:renderer-v2` passed
(332 renderer tests plus its build/static checks); 12 direct localization checks
passed for the six new/updated reasons in Korean and English. No interactive
desktop recovery flow, packaged macOS/Windows flow, fresh dev video source-to-PDF
run, corpus benchmark or holdout was exercised. Producer hooks and the renderer
recovery/dedup requests below remain open.

The unit of evidence is a foreground hypothesis with raw observation crops,
timestamps and coordinates, intended written occurrence, transforms and output
multiplicity. It is not a component id, strip count, `covered` flag or
`exact_reconstruction` assertion. Those pipeline flags are never consulted.

## Public API

All images are BGR uint8 or grayscale. Coordinates are half-open pixel boxes;
page indices and copy indices start at zero. Matrices map source pixel centres
to destination pixel centres. JSON evidence uses embedded lossless PNGs and
SHA-256 over decoded shape, dtype and pixels.

- `record_obligations(source_video=..., display_id=..., occurrence_id=...,
  members=..., expected_multiplicity=1, candidates=None) -> ledger_dict`:
  snapshots the raw members **before** median composition, cleaning, duration
  filtering, overlap ownership, row trimming or finishing. Returns `displays`,
  `items`, empty `representations`, `dispositions`, `generated_origins`.
- `measure_placement_transform(placement, native_scale=1.) -> stage_dict`:
  read-only adapter for existing measure placement records. Uses source columns,
  row crops, removed columns, insertion offsets and placement. Never reads
  reconstruction/eligibility flags. Refuses records whose column map cannot be
  reconstructed. Inserted columns require generated-origin evidence separately.
- `project_item(item, transforms) -> (contrast, hypothesis, page_origin)`:
  affine and piecewise cut/join/displacement maps. A supplied piecewise map
  dropping or double-owning foreground fails. A missing/unsupported chain is
  unassessed, hence review required.
- `extract_pdf_pages(path) -> list[{image, dpi, jpeg_sha256, pixels_sha256,
  page_index}]`: uses the already installed Pillow PDF parser to follow page-tree
  order and read each actual JPEG stream. Supports only the exporter's one
  full-page RGB JPEG XObject at 300 dpi. Rejects extra drawing commands, multiple
  images, alpha/masks, rotated/cropped pages and other layouts. No rasteriser or
  new dependency; no 600 dpi upsampling.
- `verify_pages(ledger, pages) -> report`: core checker for decoded delivered
  images. `verify_pdf(ledger, pdf_path) -> report`: production entry point,
  retaining delivered PDF and JPEG/pixel hashes.
- `pack_crop`, `unpack_crop`, `pixels_hash`, `write_ledger`: JSON persistence and
  evidence integrity helpers. No automatic writes during verification.

Merge independent display ledgers by concatenating the five list fields above.
Keep item/display ids unique. Preserve pre-filter inventory even for excluded
displays. The source video path identifies provenance; this version does not
decode it or build a second registration chain from original video frames.

## Evidence contract

Each `members` entry must supply `id`, source `timestamp`, unmodified native ROI
`image`, `roi_origin`, `registration_shift=[dx,dy]`, and
`registration_uncertainty` in native pixels. Supply native `usable` and
`occluded` boolean arrays; absence defaults to usable/unoccluded, **not** a
license to use a destructive chrome/cleanup mask. Optional `source_to_native`
records the existing ROI rectification/work-scale matrix; `polarity` is
`light` or `dark`. Unknown ROI/registration metadata prevents a pass.

Discovery uses raw member photometric contrast (paper P90 for light, P10 for
dark; contrast >=12/255), including thin and gray foreground. Clearly visible
member evidence is unioned, not majority-voted. All-obscured raw foreground
remains ambiguous. Each connected hypothesis is tiled to at most 64 px with
small context, with **no minimum-area or duration deletion**. Optional candidate
boxes must cover all discovered raw foreground; uncovered pixels explicitly
force `RAW_FOREGROUND_INVENTORY_INCOMPLETE` review.

For each hypothesis:

- An observation is eligible only when the whole hypothesis is usable and
  unoccluded. Obscured observations leave the denominator.
- Consecutive near-identical member frames with equal visibility count once:
  mean absolute BGR difference <=1 and <=0.1% channels differ by >8. This is
  computed once per display. A supporting observation must show the whole
  hypothesis above raw contrast 12; majority staff pixels cannot certify a
  minority attached dot as repeated evidence.
- Supporting counted observations separated by >=1 second form independent
  groups. Support >=80% of eligible counted observations in >=3 such groups is
  `protected`. Clear evidence with weaker support is `credible-few` and still
  requires preservation or a visible unresolved alternative. No clear support
  is `ambiguous`; preservation alone does not turn it into a pass.
- Each item retains source video, display/occurrence id, display bbox,
  foreground hypothesis, max-clear-member contrast (preserves minority ink),
  expected multiplicity, raw/native crop hashes and PNGs, observation times,
  native bbox, native usable/occlusion masks and observation-to-display map.
- Registration uncertainty >0.5 native px forces review. V1 applies this even
  to large hypotheses because a tiny dot may be connected to a large staff.

This is conservative image evidence, not symbolic identification of notes.
Static achromatic editor icons and uncertain dark backgrounds can therefore
require review. The numeric image thresholds are first-version engineering
settings verified by synthetic controls, not fitted/calibrated corpus claims.

## Transform and representation contract

One representation entry per item per expected written copy:

```python
{"item_id": item["id"], "occurrence_id": item["occurrence_id"],
 "copy_index": 0, "page_index": 0,
 "transforms": [
   {"stage": "display_to_strip", "kind": "affine", "matrix": M_crop},
   {"stage": "strip_to_line", "kind": "piecewise", "pieces": [
      {"src_bbox": [x0,y0,x1,y1], "matrix": M_piece}, ...]},
   {"stage": "line_to_page", "kind": "affine", "matrix": M_uniform_page}
 ]}
```

Order is required, including identity stages. Ordinary whole-system strips use
an identity `strip_to_line`. A piecewise stage optionally includes `pre_matrix`
for strip-native -> resampled-strip coordinates. The measure adapter supplies
uniform scale with the pixel-centre offset `(scale-1)/2`, then groups retained
source/output columns into contiguous translation pieces. Domains are the
resampled columns/row bands already recorded by `reflow_measure`.

`line_to_page` must be a positive uniform scale plus placement (0.002 scale
rounding tolerance). PDF extraction checks that page -> PDF is the same-size
full-page image placement; no implicit PDF resize is accepted. Keep page/line
identity, occurrence, overlap equivalence and retained owner alongside maps.

Forward checks search only +/-1 output pixel, not elsewhere on the page.
Foreground must retain local contrast (>=max(8,45% expected)), eroded core
coverage >=95%, per-component shape coverage >=80%, and each significant 3x3
neighbourhood >=80%. A negative ring rejects surplus darkness like a staff
substituted for a dot. The local test prevents a dot loss being diluted by a
long connected staff component. Native transform deletion is an independent
failure even when output counts or reconstruction flags claim success.

Reverse checks derive delivered-page foreground independently: contrast >=24
against delivered white paper, outside a 2 px halo around verified source or
generated pixels is a failure, with small mismatch crops. This scans the
**whole delivered page**, including outside line placements, so stale/duplicate
content is not hidden by a declared music-region bbox. Foreground weaker than
24 is a current reverse-check sensitivity limit (source obligations down to
12 are still checked forward). One actual output pixel cannot satisfy distinct
occurrence/copy tokens. Genuine repeated displays have separate occurrences
and separate actual footprints.

V1 bounds each projected patch to 1024 px. Evidence split across different
pages/lines must be partitioned into disjoint raw hypotheses before assigning
representations, with union coverage retained; do not increment multiplicity
for fragmentation. A spanning item or insufficient move/clef map remains
review required, never implicitly discarded.

## Dispositions and generated origins

Category names, `verified: true`, count balance and clean masks are insufficient.

- `cursor_recovery`: clear observation id + its raw patch hash; that observation
  must be eligible and supporting. Normal actual-page checks still run.
- `overlap_duplicate`: `retained_item_id` and
  `equivalence="same_written_occurrence"`. V1 requires equal display bboxes and
  the same occurrence. It applies the **non-owner's** foreground at the actual
  retained owner's footprint. An owner without the non-owner's dot fails.
  Different coordinate frames require an explicit raw equivalence map before
  use; V1 refuses them rather than treating the owner's mask as truth.
- `staff_scaffold`: explicit `staff_rows_display`, retained source item and its
  `retained_staff_rows_display`. Raw foreground must be horizontal (at least
  eight columns) and every foreground pixel within 0.6 px of a supplied staff
  row. A connected dot cannot be excused. Replacement pixels still get checked;
  different-coordinate scaffold relocation needs an additional map and review.
- `unresolved_alternative`: `review_artifact` PNG path and `observation_id`.
  The actual artifact must decode to the raw crop hash, not a blank placeholder.
  Always review required. The lead must expose it in the review result and keep
  it outside staged/pruned paths; existence here does not prove UI visibility.
- `chrome`, `preview_inset`, `structural_replacement`: explicit exclusion-mask
  evidence is inspected against the independent raw foreground hypothesis.
  A mask touching it fails. This minimal version cannot prove the remaining
  semantic case; it stays review required. Preserve or show an unresolved raw
  alternative instead of approving an unsupported removal.

`generated_origins` require page index, origin and hashed image template.
Scaffold generation also requires a raw `source_item_id`, source/local staff
rows and geometry containing only staff. Header/page-number/review-notice
templates require `generator` and nonempty `inputs`, and may not overlap
accounted source music. Actual JPEG pixels must match each template locally.
This verifies concrete declared origins; it does not authenticate arbitrary
caller-supplied generator names. No generic generated music bbox is accepted.

Outcome: `fail` for demonstrated loss, multiplicity conflict, double-use,
invalid exemption or unexplained output; `review_required` for unknown
registration, ambiguity, raw alternatives, missing evidence or unsupported
contracts; `pass` only for fully assessed evidence in this photometric scope.
Reports retain raw and delivered mismatch PNGs (delivered crops capped at
96 px). A pass is not packaged-platform or human musical-fidelity evidence.

## Remaining producer hook requests for the lead

Line numbers are a 2026-10-08 concurrent-tree snapshot. Function and adjacent
statement anchors are authoritative if another worker moves lines.

1. **Pre-duration display inventory:** in
   `reflow_occurrences.build_occurrences`, after the `candidates.append(...)`
   group-construction loop and **before** `occ = [c for c in candidates ...]`
   (line 831), snapshot every candidate's unmodified display members with
   `record_obligations`. Use a stable `root`/ordered-return occurrence key;
   record the later root -> final system/occurrence id remap explicitly.
   Include candidates later considered covered, short, preview or excluded.
   Use `load(obs_by[observation_id])`, not `rep_window`/cleaned comparison
   images. Native row/display windows and their crop translations must cover
   the raw row; unresolved row ownership is an explicit alternative. Never
   recapture only included systems from `build_strips`.

2. **Observation registration/visibility:** in
   `reflow_strips.compose_members` (line 434), preserve raw `images` and keys
   after `masks = [...]` (451); after the phase-correlation/`usable` loop and
   before `stack = np.stack(...)` (495), call `record_obligations(...)` or
   enrich the pre-duration inventory with **all offered** members. Pass
   source video, stable display/occurrence key, keys' observation timestamps,
   raw images, ROI/crop origin, actual per-member shifts + uncertainty, native
   usable/occluded masks and existing source-to-native transform. Do not pass
   `usable`-filtered stack, `out`, `chrome`, `notation`, fade-filled pixels or
   restored/cleaned output as raw truth. Shifts are presently used to select
   members rather than to warp them: supply the transform actually applied
   (zero when none) and record residual alignment as uncertainty. The scalar
   `max_rel_shift_px` is not an uncertainty per member. `build_strip` (1597)
   must pass context into this hook and keep ledger coordinates ahead of
   envelope/row/preview/finish crop transforms, not fabricate them afterwards.

3. **Jump display inventory and owners:** in
   `reflow_jump.display_record` (165), after raw `pairs`/`keys` construction
   and before `rs.compose_members(...)` (175), record all episode raw members
   (including those omitted by `_evenly`, or retain explicit unsampled
   evidence). Reuse the observation hook above; do not ledger `comp` alone.
   In `build_panorama` (1260), immediately before copying each owner's columns
   into `pano`, persist native display -> panorama offsets, `pano_cols`, cuts,
   equivalent written occurrence and retained owner. Every discarded overlap
   item must point to its actual retained raw region. Different panorama
   coordinates need an explicit equivalence transform or unresolved review.
   Record subsequent trimming/finishing crop offsets, including jump finishing.

4. **Piecewise measure map:** in `reflow_measure.render_lines` (816), at
   `placements.append(...)` (966/989), persist each strip's actual native
   scale, source column index map (including `declef` variants), row crop,
   placement, inserted/removed columns and occurrence id. Preserve `idx`
   from `_spread_columns` (760) when the existing compressed placement record
   cannot reconstruct it. After `ledger = {...}` (1019), read the placements
   through `measure_placement_transform(placement, native_scale=st['scale'])`.
   Keep source moves (numbers, labels, clefs) as explicit separate maps or
   unresolved alternatives. Use no `nonstaff_out`/`exact_reconstruction` flag
   as ledger truth. Removed notation cannot disappear by deleting its map.

5. **Line/page and generated origin maps:** in `reflow_measure._render`
   (1252), after `rr.render_pages(plan, images, ...)` and page placement
   attachment, bind each representation to its actual `line_id`, page index,
   placement and uniform scale. Whole-system fallback in
   `reflow_pipeline.compose_systems` (643) similarly needs native strip crop,
   chosen variant, `strip_offset_px`, label offset and page placement. In
   `reflow_render.render_pages` (463), capture small independent templates and
   generator inputs immediately when drawing header, labels, page numbers,
   review/source-clipped notices or staff insertions. Keep these templates
   separate from music pixels; do not take an arbitrary final page crop and
   call it a generated origin.

6. **Delivered export gate, both paths (DONE by X4):** after
   `verify_composed_export(...)` and before `_install_staged_export_workspace`,
   both paths call `_verify_reflow_ledger`. This consumes the persisted producer
   ledger; representation assembly remains hooks 4–5 above. Results and rebuild
   responses expose review status/reasons; ledger failures block install with a
   specific recoverable error. See the audit integration section above.

7. **Persistence before pruning (DONE by X4):** in `reflow_pipeline.prune_frames` (556),
   and any job cleanup, keep the small pre-cleanup ledger and raw alternatives
   before raw observation frames are removed. Retain source PTS, transforms,
   hashes and unresolved records across review exports. Raw video/captures are
   immutable. Alternative artifact paths must survive staged installation.

Hooks **1–5 remain unwired**: pre-duration occurrence inventory; all offered raw
composition members and per-member visibility/registration; jump display inventory
and overlap-owner equivalence; exact piecewise measure maps (including moves and
removed/inserted columns); line/page transforms and independent generated templates
for both measure and whole-system paths. Producers should merge ledgers using the
five list fields, keep unique ids, and persist the combined record under the
`ledger`/`ledger_path` contract above. Do not replace earlier pre-filter obligations
with an inventory of only the selected final systems. Selection exclusions need
explicit evidence-backed dispositions/maps. Actual raw alternative UI exposure
remains producer/review integration work: a persisted artifact alone is not proof
that a user can inspect it in the review screen.

### Requests outside X4 ownership

- `desktop/renderer-v2/src/app/session/selectors.js`, `isReviewableRun`: also
  permit `runStatus='error'`, `errorCode='LEDGER_VERIFICATION_FAILED'`,
  `review.reflow.state='ledger_failed'`. The current predicate only permits DONE
  or LAYOUT_CONFLICT, so API recovery is available but the desktop review route
  still needs this change. In `App.js`, extend the terminal-error recovery/resume
  branch adjacent to the LAYOUT_CONFLICT check to the same ledger failure state.
  Add renderer recovery tests. X4 did not edit renderer source.
- In the same `selectors.js`, `deriveReviewRequired` currently deduplicates by
  `reason.code + reason.text`. The public `{code,text}` fallback and internal
  code-only record have different text and can render twice. Deduplicate by code
  (falling back to text for uncoded reasons), preserving the public structured
  explanation first. Test a public `LEDGER_UNASSESSED` object plus the matching
  internal code string: one localized explanation must remain.
- `backend/tests/test_reflow_jump_coverage.py`,
  `IncompleteJobTests.test_complete_coverage_is_done`: complete jump coverage is
  separate from source-to-PDF assessment. Its PNG-only fixture has no obligations:
  expect `reflow_state='review_required'`, `review_required=True`, and
  `LEDGER_UNASSESSED` (with `{code,text}` reason support), while retaining
  `JobStatus.DONE` and the complete coverage checks. Do not bypass the ledger
  gate to make this legacy clean-complete assertion pass.

## Historical verification and first real run (W-E, before X4 integration)

Targeted command (set `TMPDIR` to W-E scratch for restricted work):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_reflow_ledger*.py' -v
```

37 tests passed. Requested mutations: missing dot, removed gray dynamic,
excluded display falsely certified covered, equal-count duplicate/loss,
false chrome over notation and overlap owner without the non-owner dot.
Controls: uniform enlargement, uniform shrink through a delivered JPEG PDF,
cursor recovery, genuine repeat occurrences and JPEG round-trip. Additional
guards cover connected staff/dot dilution, nearby staff substitution, minority
gray evidence, source/output double-use, stale output, group/denominator rules,
missing registration/evidence, explicit alternatives, scaffold geometry,
piecewise omission, adapter insufficiency, crop tampering, malformed PDF,
unknown transform with preserved ink and PDF page order. Unknown maps leave
unexplained output on the affected page unassessed rather than manufacturing
a proven stale-content failure; independent known losses still fail.

Full backend sweep of the concurrently edited tree: **826 tests in 515.811 s,
5 failures**. This sweep collected the earlier 34 ledger tests; final W-E
source/tests were separately rerun with all 37 passing. The five failing tests
are outside W-E ownership and were not changed here:

- `test_minority_content.ExplainedOverlayTest.test_a_single_differing_frame_is_not_minority_content`
- `test_minority_content.Round5Test.test_short_run_at_a_hand_over_is_on_record_not_flagged`
- `test_reflow_jump_coverage.CoverageTests.test_staff_line_remnants_and_speckles_in_uncovered_columns_are_explained`
- `test_reflow_jump_minority.JumpMinorityTests.test_a_short_run_at_an_established_hand_over_stays_on_record`
- `test_round6_fixes.Round5PathsTest.test_short_run_at_the_start_of_a_later_display_is_on_record_not_flagged`

Four failures expect no minority issues but receive
`MINORITY_CONTENT_DROPPED`/`UNCERTAIN_MARK_KEPT`; one expects complete jump
coverage but receives incomplete staff-remnant coverage. This is not a green
full-suite claim or proof that those failures are transient. Full log:
`we/backend_suite.log`; targeted log: `we/ledger_tests.log` in the scratchpad.

Read-only dev smoke: `eval_v1/step2_r4_dashboard/01MrRtwZgoE` contains a finished
PDF. Its embedded page was extracted at **2480 x 3508, 300 dpi**. Verification
with no fabricated obligations returned **review_required**, code
`PRE_CLEANUP_OBLIGATIONS_MISSING`, 0 checked items / 1 checked page. The saved
result reports `frames_pruned: true`; the snapshot actually lacks
`manifest.json` and a pre-cleanup ledger. The real placement record retains
columns, rows, insertion offsets and removed columns, but no raw-member
obligations. SHA-256 of PDF/result/plan stayed unchanged. Smoke report is in
the W-E scratchpad at `we/dev_pdf_smoke.json`.

Consequently **no full real source-to-output pass is claimed**. First full run
needs hooks 1-7 on a fresh dev job: complete pre-filter raw member inventory,
per-observation visibility/registration uncertainty, occurrence/overlap owner
maps, native scale and piecewise cuts/moves, generated templates and preserved
raw review artifacts. It should then verify the actual staged/delivered PDF
and preserve small mismatch crops. No holdout was opened, no video decoded or
downloaded, and no existing job was rerun or changed by W-E.
