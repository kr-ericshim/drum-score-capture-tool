# Rebuild a rejected jump seam

Design only, `feature/clean-reflow`, 2026-10-10. Read HANDOFF's first join-check block, DECISIONS “Jump-view seam resolution”, and JUMP_FREEZE.
`jump` = `backend/app/pipeline/reflow_jump.py`; `pipeline` = `backend/app/pipeline/reflow_pipeline.py`.
Other pipeline modules use that directory; anchors give function names and current line numbers.
Measurements use `backend/jobs/b7424442-7836-425b-9fcf-875fb88bd2f6` (abbreviated **J**).

## 1. What review export reuses and recomputes

`backend/app/schemas.py:JobReviewExportRequest` (259) has selection/order, formats, staff-size and
measure-reflow fields, no seam rejection field; unknown fields are forbidden.
`backend/app/main.py:_review_export` (995) dispatches to `_review_export_reflow` (2475).
`start_review_export` (1026) validates with `_reflow_export_inputs` (2428), starts one background
task per job, and rejects concurrent exports. Both routes ultimately use the same compose path.

| Existing input | Current use during a jump review export |
| --- | --- |
| `job.json`, `result.reflow.systems` | JobStore supplies strip paths/metadata, current selection/order, header and revision; `_reflow_export_inputs` resolves paths against this list. |
| `reflow/strips/` | Existing cleaned panorama PNGs and selected alternates are the source images for composition; no jump panorama is rebuilt. |
| `reflow/manifest.json` | `reflow_measure.load_context` (80) loads observation geometry for barline support. Normal jump composition does not load frame PNGs. |
| `reflow/occurrences.json` | The same context loader reads occurrence metadata; `reflow_boundaries.member_regions` (885) maps jump-member barlines using strip offsets. |
| `reflow/jump.json` | `reflow_line_review.load_line_review` (208) reads it after export to describe seams. It does not change strip pixels. |
| `reflow/tracking.json` | That review loader reads episode times; seam `t_a`/`t_b` can supply times if tracking is absent. Tracking does not rerun. |
| `reflow/ledger_chains.json` | `reflow_pipeline._compose_ledger_inputs` (1696) reads display-to-strip chains for the export sink. |

`reflow_pipeline.compose_systems` (1758) reruns dependency resolution, SAFE measure-boundary
analysis, line/page planning, optional automatic sizing, and rendering. With measure reflow off
or unavailable it composes whole systems. A separate existing dependency-recovery path,
`regenerate_uncut_strip` (120), may read occurrences/manifest and decode source frames for a
missing page-strip preview tail; it is not a jump-seam rebuild operation.

`main._review_export_reflow` writes staged PNG/JPG/PDF, runs `export.verify_composed_export`,
`_verify_reflow_ledger` (2044), and staged/installed byte binding, then installs files and updates
job metadata. It regenerates `line_review`; metadata failure rolls back the export.
Sampling, region detection, episode tracking, seam registration/resolution, jump stitching,
chunk cutting, minority auditing and leftover coverage do **not** rerun. Coverage is reused.
Original analysis: `reflow_pipeline.analyse_source` (214–428).

## 2. What is missing, and what this finished job keeps

Changing a seam's JSON status cannot recover discarded overlap pixels. `jump.build_panorama`
(1428) gives each column one display owner; `build_jump_systems` (2011–2330) finishes/trims that
panorama and writes chunks. The saved strip cannot reproduce the full original episode crops.
For J, ep-0003 owns native columns `[120,1401)` and ep-0004 `[120,1418)` of 1470 columns, as
measured from `systems[0].strip.jump.owners`. Their discarded edge columns are needed again.

Inputs for a faithful rebuild of the affected run are:

- Full ROI/work-size composites for every display in each resulting chain, not just the two
  adjacent displays; `build_panorama` needs the entire chain. Adjacent rejections can isolate
  a single display. Preserve the original run's full ordered display membership.
- Per-display `covered` column masks, original panel boundary/config, and the slot's fixed-pixel
  mask. `register_seams` (584) computes these; `analyse_source` later drops `_composites`,
  `_covered`, `_fixed`, and `jump.write_json` (2809) excludes underscore fields from persistence.
- Original observation crops for `audit_jump_minority` (1253), alternate construction in
  `_strip_minority` (1279), and source clipping. Composites sampled from at most nine members
  in J cannot replace the all-observation minority check (`audit_display_minority`, 1230).
- Job-wide chrome samples (`reflow_strips.job_screen_chrome`, 2131; up to 32 score observations).
  Recreating the slot fixed mask can additionally require confirmed displays outside this run.
  Retain those dependencies or cache the original masks; do not silently change the sample set.
- Fresh occurrence/system records, owners/member offsets, preservation findings, alternates,
  ledger chains, coverage and line-review mapping. Old coordinates become stale after splitting.

Important correction to the obstacle: the source-decoding fallback already exists.
`observations.load_observation_image` (678), through `system_tracking.manifest_image_loader`
(939), reads the PNG first, otherwise calls `iter_frames_at` (199) and `crop_observation` (102)
using the saved PTS, applied ROI and crop size. What is absent is a jump rebuild orchestrator,
batched recovery and persistent user overrides, rather than all ability to recover pixels.
The fallback currently opens/sequentially decodes from the video start for each missing image.

J's `job.json` is done, reflow revision 4 (review-export revision 3), with one selected primary
strip, its bundled alternate excluded, 16 printed lines, and two resolved seams on page 1,
lines 4 and 5: `seam-ep-0003-ep-0004`, `seam-ep-0004-ep-0005`. `jump.json` records 19 displays,
16 verified seams and one run, 0.007–95.507 s; config `reflow_jump-4`, `69bcc239ec48df9b`.

| Measurement, logical bytes (`Path.stat`), excluding directory allocation | Value |
| --- | --- |
| Retained observation PNGs | 721 files; 80,771,585 B = 77.030 MiB |
| Observations belonging to this run | 427 files; 78,959,575 B = 75.302 MiB |
| All strips, alternates and evidence patches | 41 files; 4,134,922 B = 3.943 MiB |
| Primary strip | 24,447 × 170 px; 2,848,085 B |
| Export workspace | 12 files; 12,189,517 B = 11.625 MiB |
| Persisted episode composites / `ledger_evidence` / `ledger_base.json` | None / absent / absent (`dev_ledger: false`) |
| Reconstructed composites, encoded in memory with default OpenCV PNG settings | 19 × 1470 × 254 BGR pixels; 3,399,835 B = 3.242 MiB |
| Packed covered masks / slot fixed mask, before container overhead | 3,496 B / 46,673 B |

J is an **exception to normal frame pruning**: `frames_pruned: false`, with
`overlay_review_evidence.json` and `OVERLAY_UNRECOVERED`. `reflow_pipeline.prune_frames` (1579)
retains frames for unresolved overlay reasons, development `REFLOW_KEEP_FRAMES`, or failed
development-ledger evidence retention; otherwise it removes `manifest/frames` after suggestions
(`main._finish_reflow_suggestions`, 2405). Finished normal jobs retain metadata and strips;
raw frames/composites are not guaranteed. Small `strips/evidence` patches are not full displays.

Read-only `python -I -B` measurements: source exists (57,662,545 B); SHA-256 matches the manifest.
One `iter_frames_at` batch for all 427 run observations, crop and stored-PNG comparison took
3.528 s: **427/427 pixel-identical, PTS differences zero**. All 32 chrome samples lie in this run.
Composite recreation plus in-memory PNG encoding took 6.895 s; subsequent minority auditing
took 9.092 s (15 events); chrome sampling took 0.099 s, using the same cached loader.
Stored `jump.json.seconds` is 10.48 s for original jump analysis, not panorama construction.
The latest export task took 17.415 s; `ledger_last_attempt.json` records B 6.424 s, C 3.768 s,
gate 10.492 s. Logs lack separate stitching/cleaning durations; these measurements establish
neither total repaired-export time nor another machine's speed.

## 3. Options and shared behavior

**Shared proposal:** add optional `rejected_seam_ids` (full desired set) and `base_revision` to
`JobReviewExportRequest`. Omission retains committed overrides; an explicit empty set restores
original seam decisions. Validate job/run ownership, duplicate IDs, supported statuses and stale
revision before queuing. Keep algorithmic evidence immutable and record `user_rejected` separately.
V1 accepts resolved/unverified seams; already-unverified rejection is idempotent, with no pixel rebuild.

In `jump.seam_offset` (988) and `_link_dx` (2332), rejection must win before verified/resolved
offsets. Recompute `panorama_chains` and effective summaries from the original run membership;
do not rerun `classify_runs`/`resolve_seam`, which could remove an end/secondary run or undo the
user choice. Every other seam keeps its recorded decision. Rebuild all changed runs once.
`build_jump_systems` must preserve original run indices when filtering runs, instead of
renumbering a selected run as run 1; rebuild singleton chains and clef copies normally.

The repair uses both complete sides, so overlap measures may repeat. It cannot restore notation
that the video never showed. Seam location on an old printed line is irrelevant: regenerate
chains and page layout, whether the seam was inside a line, at its end, or across pages.
In `reflow_measure.build_atoms` (507; join checks at 626), add an explicit chain-break barrier:
no cross-chain join/trimming at rejected or unverified boundaries, even if the edge is a barline.
Current join checks use geometry and do not consult `unverified_seam_before/after`.

**A. Retain episode composites and a complete audit bundle at analysis time.**
Change `pipeline.analyse_source` before dropping arrays and `jump.register_seams`/`write_json`
to persist lossless composites, masks, member/provenance data and format/version hashes.
Refactor `build_jump_systems`/`_strip_minority` to reuse persisted minority support, alternate
pixels, chrome and clipping evidence without a raw loader; retain dev-ledger evidence if enabled.
Measured composite/mask storage has a 3.29 MiB lower bound for J, plus unmeasured audit/alternate
dependencies (or another 75.302 MiB to retain run crops). Persisting the complete cache adds
unmeasured write time; rebuilding avoids composite/audit work. Source moves need not block it.
Missing/stale cache must fail; `load=None` flags `JUMP_MINORITY_UNCHECKED` without manufacturing
alternates. A bare composite cache is insufficient.
User sees “Both views kept; measures may repeat”; a cache failure preserves the previous PDF.

**B. Recover the affected run's observation crops from the source at rebuild time.**
Add cancellable batch recovery in `observations.py` using saved PTS/ROI/work size; connect proposed `pipeline.rebuild_jump_runs` to the export task.
Reuse retained PNGs, recover missing observations in one ordered decode, then use
`display_record`, fixed/chrome masks and the existing audited strip builder. Include slot/chrome
dependencies above. Do not use the current one-video-open-per-missing-PNG fallback in a loop.
No permanent raw-image cache is required. J's 3.528 s recovery/comparison and 6.895/9.092 s
composite/audit measurements cover only those steps, excluding panorama/alternate writes/export.
Holding J's 427 BGR crops is about 456.14 MiB; use the existing 768 MiB loader budget or bounded
temporary storage (75.302 MiB PNG payload using original encoding as the sizing reference).
When decoding is needed, verify source hash and frame timing/shape; missing/replaced/incompatible
sources stop repair. Complete retained crops can work offline after baseline validation.
A relocated identical source requires explicit relinking; never auto-fetch another download.
User sees progress/cancel, or “Source unavailable; previous PDF kept.” Common gates still apply.

**C. Keep raw observation crops required by jump rebuilds at job time.**
Record run/slot/chrome dependencies in `pipeline.analyse_source`; retain their PNGs in
`pipeline.prune_frames`, with capability/version/hashes. Reuse the current audited builder/loader.
J costs 75.302 MiB retained (chrome picks included), versus 77.030 MiB for all observations;
other jobs may need extra slot/chrome crops. PNGs already exist, so extra creation time is
metadata/hash work; no pruning-time benchmark was run.
Rebuild still pays composite/audit/stitch/export time, but avoids source recovery and works if
the source moves. Cache deletion/corruption or incompatible processing versions can still fail.
User sees B's result; source is needed only for the clip. This simple source-independent option
uses materially more permanent disk than A's composite pixels alone.

**Gates, for every option:** rerun owner-map completeness and `panorama_preservation`, preserve
minority/overlap alternates, source-clipping and finishing findings, and recompute
`leftover_gate`/`account_coverage` against new included systems. Coverage/preservation findings
are review/incomplete results, not proof of a lost-free repair. Preserve existing SAFE-boundary,
dependency and layout rules. Rebuild `ledger_chains.json`; for dev-ledger jobs also rebuild
producer dispositions/base evidence rather than reuse old overlap equivalences.
Run `verify_composed_export`, the PDF contract, and staged/installed digests unchanged.
`verify_light_deliverable` (1365) runs B/C as non-blocking review findings; A/raw-source support
is unassessed in normal app jobs. B/C pass cannot prove source notation preservation; missing
prerequisites stop before installation.

## 4. Recommendation, implementation order, tests and real-job verification

Recommend **B first**, using retained frames when available, with C as a later retention policy:
it supports old jobs, reuses audited algorithms, and J's batch recovered every crop exactly.
A needs a new audit-cache interface; C needs a storage decision. Keep seam thresholds unchanged; avoid repeated OCR and cleaned-panorama patches.

One worker can implement these ordered increments, each with focused unittest coverage:

1. In `schemas.JobReviewExportRequest`, `main._reflow_export_inputs` and `start_review_export`,
   validate overrides/base revision; persist successful overrides in `result.reflow`, with an
   immutable original-analysis pointer. Revalidate revision under the export lock before work.
2. Add rejection precedence to `jump.seam_offset`, `_link_dx` and effective status/summary
   helpers; rebuild panorama chains without reclassification. Add run filtering that retains
   original indices. Add the measure-chain barrier in `reflow_measure.build_atoms`.
3. Add bounded batch recovery in `observations.py` and `pipeline.rebuild_jump_runs`. Recreate
   required composites/masks with saved config, never resample/retrack/re-register. First prove
   an unchanged-seam reconstruction matches recorded primary strip pixel hashes; incompatible
   reconstruction stops rather than quietly changing unrelated decisions. Then build rejected
   strips, occurrences, alternates, ledger chains and coverage with current audited producers.
4. Integrate with `main._review_export_reflow` using a deep candidate record and an unpublished
   revision workspace containing new strips and jump/occurrence/chain metadata. Reference
   immutable manifest/tracking and unaffected strips. Map selection by original run lineage,
   not reused chunk IDs. V1 changes a run only when all its primary chunks are selected,
   contiguous and chronological, with its alternates unselected; otherwise return an actionable
   409 before work. Insert every new primary chunk at that run's old position; keep unrelated
   order/selection. Do not silently select regenerated alternates. Preserve their evidence.
   Pass fresh measure context and workspace metadata to line review. Verify/install export,
   then publish the revision pointer/result. Cancel/error/metadata rollback keeps old pointers,
   strips, overrides and PDF; discard unpublished revisions, never overwriting original artifacts.
5. Extend `reflow_line_review._build` (101) to emit boundary seams from
   `unverified_seam_before/after`, with both printed endpoints. Today it emits stitch cuts only,
   so a split seam would disappear. Keep the same seam ID, original clip time and rejection
   reason; deduplicate across lines/pages, with effective status unverified.
6. Wire `reviewController`'s `review-seam-answer`, `App.js` rebuild (2606), and
   `lib/api.js:reviewExportBody` (331). Merge pending bad answers with committed overrides;
   ordinary later exports retain them. Update selectors, `lineCheck.seamChecks`,
   `ReviewScreen.renderSeamCheck` and KO/EN copy for two boundary endpoints and pending/applied
   repair. Show “Both views kept; measures may repeat”; preserve pending answers on failure
   and restore focus to the same seam after success.

Add backend tests in `test_reflow_jump.py` (or `test_reflow_seam_reject.py`): resolved rejection,
unchanged neighbours, already-unverified/idempotent requests, adjacent rejections yielding
three chains including a singleton, run ends/secondary runs, and unchanged baseline pixels.
Reuse `test_reflow_jump_minority.py`/`test_reflow_jump_preservation.py` fixtures to assert hidden
overlap ink and minority alternates survive. Test raw-cache and batched-source parity, missing
source, wrong hash, timing/shape mismatch, decode cancellation, and multi-run index retention.
Extend `test_reflow_review_export.py`/`test_review_export_tasks.py` for stale/unknown IDs, selection
restrictions, persistent overrides, cancellation and rollback on write/contract/digest/metadata errors.
Extend `test_reflow_line_review.py` for boundary endpoints at line/page ends;
measure tests must assert no cross-break trimming/joining and preservation of both edge windows.

Real-job acceptance after implementation: copy J to an isolated `/private/tmp` fixture and
remap all absolute strip/workspace/source paths; use an isolated JobStore, never the live J.
Keep baseline bytes and render revision 4 unchanged first. Reject 0003→0004 alone, then both
resolved seams: expect chains 0000–0003 / 0004–0018, then 0000–0003 / 0004 / 0005–0018.
Confirm recovered edge columns, singleton content, warnings, alternate evidence, new coordinates
and boundary cards/clip times; compare the source manually for dropped notation. Repeat with
fixture frame PNGs absent (source present), then source absent with frames absent: successful
repair followed by explicit failure with unchanged previous files/metadata. Repeat ordinary
export to prove overrides persist; inject cancel and failed installation. Record full elapsed
time, peak memory/disk, page count, preservation/coverage findings and B/C results separately.
`backend/tools/verify_job.py` needs `ledger_base.json` for A; J lacks it. Test A on a separate
dev-ledger fixture and report that distinction. This design performed no repaired export.

After focused modules, run `PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'`.
UI wiring also requires `npm --prefix desktop run verify:renderer-v2`, KO/EN, keyboard focus,
pending/error/loading states, and inspection at 1440×960 and 1120×840. Source-app checks do not
certify packaged macOS/Windows operation. No implementation tests were run for this document.

## 5. Product-owner questions

- Is v1's whole-run restriction acceptable, including refusal when an alternate is selected, or must arbitrary chunk/alternate selection migrate automatically at launch?
- Must repair work after source deletion/moves without relinking? If yes, choose retention budget/lifetime (C) or fund the composite/audit bundle (A).
- Should repaired-boundary warnings appear in the PDF or only in review? `main._compose_header` (2130) handles incomplete/source-clipped markers, not this choice.
- Should users restore original inferred joins after repair, and how should that control differ from answering “ok” on the duplicated-but-preserved output?
- For missing sources, offer explicit same-file relinking in review, or direct users to rerun capture? Hash/PTS validation remains required either way.

## Implemented

Backend increments 1–5, option B: committed full-set overrides and revision/whole-run validation;
rejection-first offsets, retained run indices and measure-chain barriers; cancellable single-pass
crop recovery with retained-PNG reuse; unchanged-primary pixel-hash gate; unpublished revision
workspaces, fresh audited producers/ledger chains/coverage and transactional export rollback;
both review boundary endpoints with original seam IDs and jump times. Original algorithmic
evidence and thresholds remain unchanged. Explicit `[]` restores original decisions.
Repair findings stay in review; original missing-interval PDF notices are retained without new
repair notices. Dev-ledger repairs replace affected producer evidence and overlap dispositions.
Acceptance artifacts and logs: `/private/tmp/seam_reject_check/` (isolated copy, never the live job).
Renderer increment 6 and packaged-platform checks belong to the parallel UI work.
Backend validation: 19 added tests; full discovery 1,385 OK (12 skipped). Real-job baseline
pages pixel-identical; one/both rejections and missing-frame source recovery completed with
two pages; missing-source, decode-cancel and installation-failure checks kept previous artifacts.
Coverage/B/C remain review findings; the separate dev-ledger A fixture is review-required,
not a source-to-PDF preservation certificate.
