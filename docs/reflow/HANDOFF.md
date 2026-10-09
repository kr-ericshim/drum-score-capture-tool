# Clean reflow: handoff (2026-10-06)

State of the clean-reflow work for a new session. Read this first, then [DECISIONS.md](DECISIONS.md).

## Start here (2026-10-09 night: speed done, replay collapse in)

**Done this session (uncommitted until the user says so):**
- **Strip cleaning in threads.** `build_strips` runs `build_strip` for up to N systems at once and consumes results in system order (`reflow_strips._strip_threads`: min(4, cpu−1, RAM_GiB // 4); env `REFLOW_STRIP_THREADS`, 1 = old sequential path). Loader `manifest_image_loader` is thread-safe (lock + per-id decode event). Strips harness (01Mr): 1 thread 76 s / 2.1 GiB, 2: 41 s / 2.7, 4: 29 s / 3.8, 6: 25 s, 10: 22 s / 4.8 → 4 is the knee. Records and every strip PNG byte-identical (S1, 01Mr; 1 vs 4 vs 10 threads).
- **Job times over HTTP (battery):** 01Mr 213 → 173 s (target ≤ 180 ✓), S1 95 → 76 s, w7mK 319 → 167 s, aOED 152 → 88 s, Q8 839 → 498 s (old Q8/aOED/w7mK numbers are from the morning dashboard, before the earlier strip fixes too). Peak RSS +~1–1.5 GB (01Mr 3.8 GB, Q8 4.5 GB). 01Mr/S1 pages pixel-identical to the pre-thread baseline.
- **Replay collapse (Pro #4 option iii).** `reflow_occurrences.collapse_replay_blocks`, called in `reflow_pipeline` after the coverage gate and label acquisition: ≥3 consecutive systems whose whole cleaned strips match (strict: piece ≥ max(4 px, 0.04·gap²)) a unique earlier consecutive block, each line distinctive (matches exactly one earlier line), different page views, B starts after A ended, no acquired label on B. Collapsed systems: `included=False`, `REPLAY_COLLAPSED`, `replay_of`, `exclusions.replay_blocks`; alternates still listed; user can tick them back. aOED: sys-016..023 → 004..011 collapsed (3 → 2 pages). Q8: first version wrongly collapsed simile lines 069/073/077; with the distinctiveness rule nothing collapses (each matched 2–3 earlier lines). Others: no revisits. DECISIONS.md updated.
- Codex adversarial review: threading clean; replay findings (simultaneous rows, labels, alternates, small dots, lazy loading) fixed in the second round; the 1,000-strip memory case judged moot (strips are decoded lazily now).
- Merged tree: full suite 1287 OK (12 skipped). Final HTTP check after merge: aOED 2 pages (8 collapsed), Q8 4 pages (none collapsed), unchanged otherwise.

**Next:** overlay remnants + packing (_7gP squeezed unit, Z4eb short lines, bF69 smudges), then re-run the 12-video dashboard on one manifest and recount (clean / usable).

## Start here (2026-10-09 evening, after Pro checkpoint #4) — superseded

**Plan in force:** STRATEGY.md "Step 2D checkpoint #4: Pro reply weighed". User principle (memory notes-over-cosmetics): keep notation near the staff (notes, accents, lyrics) at ~99.99%; tolerate leftover noise; cosmetic remnants never mark a chart incomplete. Noise that overlaps or imitates notation, and duplicated measures, still count as defects.

**Done today (all committed on feature/clean-reflow, not pushed; last 0e48c67):**
- Review panel shows only `APP_REVIEW_CODES` (empty) → no review flood; endpoint takes `codes=`.
- Jump-view false incompleteness fixed: a faded panel label glyph (架子鼓) was flagged as lost notation. Pixel-level recurrence mask exemption `panel_label_recurring` (jump_preservation-6). SHvfn 18→0 and _7gP 68→0 unresolved; music was always delivered. SHvfn now 3 pages at 1.4 mm (was 1.2 mm). _7gP still has squeezed lines (p1 lines 1–2, p3 line 1): one 4,300 px layout unit forced into one line — layout/packing issue, not coverage.
- Strip cleaning: 01Mr ~140 s → 73 s, job ~283 s → 222 s; S1 job 124 → 99 s. Pages, strips, records, review findings identical. Full suite 1245 OK.
- Visual count now: clean 7/12 (+SHvfn), usable with flaws 4 (aOED, bF69, Z4eb, _7gP), unsupported 1 (GTOc). Not yet re-run as one dashboard.

**Next:**
1. Speed, last step: the speed worker measured 4 threads over strip registration, frame decoding and eligible overlay masks (scratch copy only) at 01Mr 52 s vs 74 s with identical records/PNGs; threading the per-member normalize/clean/inventory too should approach 40 s. Approved direction (lead): bounded threads (min(4, cpu−1)), deterministic order, same equivalence check. Then 01Mr total should be ≈ 180 s.
2. Repeats (aOED D.S. replay), then overlay remnants + packing (_7gP squeezed unit, Z4eb short lines).
3. Re-run the 12-video dashboard on one manifest and recount.

## Start here (2026-10-09, Step 2D-1 wrapped up; verification frozen) — superseded

**Read in this order:** DECISIONS.md "Staged delivered verification (2026-10-09)" incl. "Where verification runs"; LEDGER_2D_INTERFACE.md §10 and §12; this block.

**State (2026-10-09):**
- **Direction change (user):** stop growing the verification system ("너무 산으로 / 가드레일 안에 갇혀"). Steer by product outcomes: usable charts out of the dev set, job time on a normal laptop, looks. Memory: avoid-guardrail-spiral, legibility-not-pixel-exact.
- **Built in 2D-1:** source-to-PDF ledger (inventory hook 0, producer hooks, dispositions); lossless PDF (Flate gray/RGB, ~half the old JPEG size); staged checks `reflow_verify_common/strip(A)/plan(B)/page(C)`; in-app gate = PDF contract + byte binding (blocking), B + C (non-blocking review items, ~3–4 s/job); A + old raw verifier are dev-only (`backend/tools/verify_job.py`); review-hypotheses API + renderer panel ("확인 항목").
- **Real e2e (HTTP, `~/Documents/drum-score-corpus/reflow/e2e_2d1b`):** S1 done in 153 s, 01Mr done in 479 s, both with PDFs; gate 3–4 s. Review items S1 295 (OUTPUT_FIDELITY), 01Mr 1,286 (REMOVED_FEATURE 308, DUPLICATED_CONTENT 226, PLAN_INVALID 100, OUTPUT_FIDELITY 612, DELIVERED_EXTRA_INK 40) — precision NOT established; most are probably noise.
- Full backend suite 1218 OK (12 retired-verifier tests skipped with reason). Renderer verify 344 OK. The review panel was not yet inspected visually at 1440×960 / 1120×840.
- Nothing committed (commit only when the user says so).

**Afternoon update (2026-10-09, new session):**
- Dashboard v3 finished. SHvfn and Z4eb failed in composing: `reflow_render._font_cmaps` read a cmap format 14 subtable as an empty table and `_cmap_has_glyph` raised `struct.error` on titles with hanzi (鼓譜). Fixed (skip non-4/12/13 formats, malformed table = not covered) + regression test in `test_source_clipped_render.py`.
- Fzc's 8,875 s is invalid: the lid was closed 11:00–13:20 (pmset log). Its output is fine.
- Speed-fix patch applied to the real tree. Full suite 1229 OK (12 skipped).
- Reran SHvfn, Z4eb, S1, 01Mr into `step2d1_dashboard` with `--only` (on battery power; note when comparing times).
- Times after the speed fix (battery, otherwise idle): S1 125 s (was 153), 01Mr 342 s (was 479). The strips stage is still the problem: S1 58 s vs 19 s on Oct 7, 01Mr 199 s vs 22 s. Other stages match Oct 7, so this is the strips code, not the battery.
- Visual count (all pages viewed; the dashboard's strict `usable` is 0/12 and not useful): clean 6/12 (S1, 01Mr, w7mK, Fzc, Q8X, SZwT with tiny blue overlay icons at line ends); usable with flaws 3 (aOED repeats bars 13–44 after D.S. al Coda — also on Oct 7; bF69 gray smudges over every line + black blob at Bridge; Z4eb leftover "#75 鼓组" UI text and odd short lines); not usable 2 (_7gP 68 gaps, SHvfn 18 gaps); GTOc unsupported by design. Sheet: `eval_v1/step2d1_dashboard/compare_1007_vs_1009.jpg`.
- Suggested next: strips speed regression first, then D.S. repeat duplication and overlay remnants (bF69/Z4eb/SZwT).
- Committed (5 commits, not pushed): pipeline, app, tools, docs, then a speed/robustness commit. Pre-commit review by 4 Opus-medium readers; fixes applied.
- Strip cleaning profile (01Mr): frame cache thrash fixed (LRU 768 MB) → cleaning 199 → 132 s, job 342 → 277 s, S1 119 s; output pixel-identical. Remaining cost is the per-member minority check (phaseCorrelate 31 s, percentile 19 s, PNG decode 25 s).
- Waiting on Pro: `PRO_CHECKPOINT_STEP2D_OUTCOMES.md` with `~/Documents/drum-score-corpus/advice_pack_5/`. Weigh the reply before choosing the next work.

**In flight (2026-10-09 morning):**
- Dashboard v3 run into `~/Documents/drum-score-corpus/eval_v1/step2d1_dashboard` (12 videos; log in the session scratchpad `logs/dash_2d1.log`). If it was interrupted, rerun the missing ids with `--only`.
- Speed fix (dev ledger collection off by default: `JobOptions.dev_ledger`, `REFLOW_DEV_LEDGER=1`) is done in a scratch copy and NOT yet merged. The patch is saved at `~/Documents/drum-score-corpus/eval_v1/speedfix_2d1.patch`. Apply it after the dashboard finishes, rerun the full suite, then re-time S1/01Mr on an idle machine. The Oct 7 r4 strips stage was 19 s; pre-2D code measured under load today was 61 s, so compare on an idle machine.

**Next (agreed direction):**
1. Small: show in the app only finding codes with demonstrated precision; keep the rest in the dev report (the counts above would otherwise flood "확인 항목").
2. Product: rerun the 12-video dev dashboard, count usable charts (baseline 3/12), spot-check visually.
3. Speed: 01Mr 479 s → target 2–3 min for a 3-minute video (cleaning is ~4.5 min of it).

## Start here (2026-10-08, Step 2D not started) — superseded

**Read in this order:**
1. [STRATEGY.md](STRATEGY.md): its last two sections, "Step 2C checkpoint #3: Pro reply weighed" and "Step 2D plan (in force…)". These hold the plan in force.
2. [DECISIONS.md](DECISIONS.md) "Step 2D rules".
3. "Update 2026-10-08" at the end of this file: what the 2C round built and what is still open.

**State:**
- Steps 1, 2A, 2B and the 2C round are done. Pro checkpoint #3 has been weighed. Step 2C is **not** closed: B2 is not promoted and legacy stays the default.
- **Next: Step 2D item 1** (ledger integration and review access). Its exit check: release contract items 1–7 are demonstrated, and at least one real opaque dev video (01Mr or S1nl) passes end to end with a clean result.
- Workers: Codex `gpt-6.1-sol` at high via `codex-backend`, on disjoint files. Audits run at xhigh. Use one integration owner and one build manifest per phase. Codex cannot write to `~/Documents/drum-score-corpus`, so stage files in the scratchpad and copy them over.
- Before Step 3, prepare a Pro checkpoint prompt with attachments.
- The working rules in the block below still apply.

## Start here (2026-10-07, STRATEGY Step 2 in progress) — superseded

**Read in this order:**
1. [STRATEGY.md](STRATEGY.md): the plan in force. Its last two sections ("Step 1 checkpoint: Pro reply weighed", "Step 2 (revised, in force)") hold the current Step 2 plan and exit check.
2. This block.
3. [DECISIONS.md](DECISIONS.md) for the rules still in force.

**State:**
- Step 1 done. The Pro checkpoint reply was weighed and Step 2 reordered: 2A safety and coverage → 2B primary score clean → 2C bounded optimizer.
- **2A and 2B done (2026-10-07).** See STRATEGY.md "Step 2A + 2B status". Dashboard `eval_v1/step2_r4_dashboard`. Audit doc `AUDIT_2B_identity_overlay.md`.
- **Waiting on:** the Pro reply to `PRO_CHECKPOINT_STEP2AB.md` (pack `~/Documents/drum-score-corpus/advice_pack_3/`). Weigh it, update STRATEGY.md, then start 2C.
- Measuring tip: workers that must not disturb a running dashboard work in a scratch copy of `backend/` and are merged after the run (check the real tree's file hashes first).
- After 2C, prepare the Pro checkpoint prompt and attachments before Step 3.

**How the user wants to work now** (replaces older lists where they differ):
- Reply in short, plain Korean. Make technical choices yourself; at most one question, only when needed.
- Commit, push or download only when the user says so.
- Worker subagents: Opus at medium reasoning, in parallel on disjoint files. The project agent `.claude/agents/reflow-worker.md` (opus, effort medium) loads in a new session; in the session that created it, workers ran as the `webgpt-impl` type (same model/effort) with its WebGPT instructions overridden in the brief.
- Audits: Codex `gpt-6.1-sol` at xhigh (`codex-reviewer` / `codex-second-opinion`). Audits check files, runs and logs against the assigned task list.
- Measure every change with the dashboard on dev + validation. The holdout stays sealed until Step 4.
- No per-video patches. No human timing studies. Spot checks: at most 10 doubtful items, one yes/no.
- When a round ends, stop leftover background agents and processes.
- Before each STRATEGY step, prepare a ChatGPT Pro checkpoint prompt with attachments and wait for the reply.

## Start here (2026-10-07, end of STRATEGY Step 1) — superseded


**Read in this order:**
1. [STRATEGY.md](STRATEGY.md): the plan in force, adopted from the ChatGPT Pro review. It overrides the per-video patching of earlier rounds.
2. This block.
3. [PRO_CHECKPOINT_STEP1.md](PRO_CHECKPOINT_STEP1.md): what was sent to Pro for the Step 1 checkpoint.
4. [DECISIONS.md](DECISIONS.md) for the rules still in force.

The sections further down are the history of earlier rounds. Their "Open items" and "Next" lists are **stale**.

**State:**
- Step 1 is done:
  - 1a: evaluation set `eval_v1`.
  - 1b: dashboard and baseline.
  - 1c: review export as a background task.
- The Step 1 checkpoint prompt and its attachments (`~/Documents/drum-score-corpus/advice_pack_2/`) went to ChatGPT Pro. The next session starts with Pro's full reply.
- **Step 2 has not started.** Weigh the Pro reply first: it is advice to check, not orders. Then update the Step 2 plan in STRATEGY.md and start.
- **Baseline:** 3 of 12 charts are acceptable (S1nl, 01Mr, w7mK). The failure classes are listed under "Evaluation set and baseline" at the end of this file and in `eval_v1/baseline_dashboard/dashboard.md`.
- **Draft Step 2 order** (as sent to Pro; change it if the reply says so):
  - a. Scope and correctness gates:
    - No "done" with 0 pages.
    - The transparent overlay is reported as unsupported.
    - Jump view handles each interval separately and reports the leftovers, instead of refusing the whole job.
  - b. Revert `OVERSIZE_SPAN`. Replace the justification tiers and the shrink trigger with the bounded min/preferred/max width model, one distortion cost and the document objective.
  - c. Clean up overlay remnants (cursor, band, "Next" inset). The dashboard remnant metric is the acceptance check.
  - d. Step 3 (hairpins, system-start clef, MuseScore "↵" markers, title/header).
- **Freeze:** add no new per-video layout exceptions. Measure every change with the dashboard on dev + validation. The holdout stays sealed until Step 4.
- **Code:**
  - Everything after commit `6b65c6a` is uncommitted on `feature/clean-reflow`.
  - Last suites: backend 601 OK, renderer verify 313, desktop-node 94.
  - The user must restart the app to pick up the background export.

**How the user wants to work now** (this replaces the older list below where they differ):
- Reply in short, plain Korean. Make technical choices yourself, and ask at most one question, only when needed.
- Commit, push or download only when the user says so.
- No human timing studies.
- Spot checks: show at most 10 doubtful tiles and ask one yes/no question.
- Worker subagents run on Opus at medium reasoning, in parallel when the work splits into disjoint files. No Codex for implementation.
- Audits use a Fable subagent. Audits check the actual files, runs and logs against the assigned task list.
- When a round ends, stop leftover background agents and processes.
- Before each STRATEGY step, prepare a ChatGPT Pro checkpoint prompt with attachments, and wait for the reply.
- Avoid per-video patches. Every change must be general and must show on the dashboard.


## Goal

The app captures drum scores already shown in YouTube videos. Its only final output is a clean chart: cleaned source score images laid out on A4. Look target: the user's teacher PDF, `/Users/ericshim/Downloads/뉴진스-GODS.pdf.pdf`, with about 4 measures per line, justified lines, a title header and page numbers. OMR re-engraving (Audiveris → MuseScore) was tried and shelved: 9 of 24 measures came out correct. The pilot is in `~/Documents/drum-score-corpus/pilot/reengrave-v1/`.

## Where things are

- **Branch:** `feature/clean-reflow`. Commit `6b65c6a` holds the overlay-removal and paper-flattening work. Everything after it is **uncommitted**: about 52 changed or new files in `backend/app/pipeline/`, `backend/tests/`, `desktop/renderer-v2/src/` and `docs/`. Commit or push only when the user asks.
- **Design and decisions:**
  - [DESIGN_astra.md](DESIGN_astra.md): the original design. Its order and identity parts are superseded.
  - [DECISIONS.md](DECISIONS.md): user decisions and the audit fixes in force, rounds 2–5. It overrides the design.
  - [MEASURE_BRIEF_astra_raw.txt](MEASURE_BRIEF_astra_raw.txt): the brief for the next phase (measure-level reflow). Ignore the `[codex]` progress lines in it.
- **Pipeline code:**
  - Main flow: `backend/app/pipeline/reflow_pipeline.py`, `reflow_occurrences.py` and `reflow_strips.py`.
  - Layout and output: `reflow_layout.py`, `reflow_render.py` and `reflow_labels.py`.
  - Detection and tracking: `minority_content.py`, `system_tracking.py`, `system_detect.py`, `observations.py` and `notation_envelope.py`.
  - Not on the export path: `score_assembly.py`.
  - API: `main.py` (`_execute_reflow_job`, review export) and `export.export_composed_pages`.
- **Corpus:** `~/Documents/drum-score-corpus/`.
  - `videos/`: 18 videos. `rois.json` honours `kind` before `layout`.
  - `reflow/gt/<video>/gt_v2.json`: Claude-drafted ground truth, frozen in `gt/freeze_v2.json`. Do not edit it.
  - `reflow/tools/`: `eval_e2e.py` (v3) and `run_e2e.py`.
  - End-to-end runs: `reflow/e2e`, then `e2e_r2` … `e2e_r5`. Never overwrite an earlier run.
- **Transparent-overlay scores** (white notation drawn over live video): the extractor is in `~/Documents/drum-score-corpus/transparent/` (`extract.py`, `README.md`). It ran on 12 atthedrum videos and is not in the app yet.

## Latest results (e2e_r5, same ROIs, evaluator v3)

| Video | Systems placed / GT | Order |
|---|---|---|
| S1nlqQdnUks (10cm) | 18/18 | exact |
| aOED5zskhGk (울어라 열풍아) | 25/25, all 8 D.S. returns kept | exact |
| bF69tpnUk5w (Ophelia, dark) | 26/26 | exact |
| Q8XtphO6Xz0 (page turns) | 46/46 | exact |
| 01MrRtwZgoE | see `e2e_r5/tables.md` | |

- rsUfI3EKAj4 (horizontal scroll) ends in `UNSUPPORTED_LAYOUT`.
- Mark-preservation numbers are in `e2e_r5/tables.md`.

## Open items, in order

1. **Unfinished fix round 4b.** It fixed over-splitting from the minority-content step: aOED had one system placed twice, bF69 had 39 short fragments. The agent was stopped while rerunning the backend suite and never wrote its report.
   - Rerun the suites (commands below) and read the round-5 section of DECISIONS.md and the diff to see what changed.
   - Keep the earlier regressions green: the 32-frame clip with a radius-2 black dot in 8 consecutive frames must stay preserved or flagged, and the fail-closed tests for a missing uncut strip must pass.
2. **Job time went up.**
   - Total: S1nl 74 → 106 s, bF69 190 → 320 s, Q8 393 → 606 s (r3 → r5).
   - Check whether evaluation was running in parallel with the jobs. If not, profile `minority_content.py` and fix the slowdown.
3. **Audit with a Fable subagent.** The user asked for Fable instead of Astra for this audit.
   - It must check each assigned item against files, runs and logs, not only the report, because Opus implementer agents have skipped steps before.
   - It ends with GO or NOT YET for measure-level reflow.
4. **Measure-level reflow**, per MEASURE_BRIEF.
   - Boundaries are classified SAFE, LOCKED or UNKNOWN. Cut only at SAFE boundaries; otherwise keep the whole system.
   - Four measures per line is a preference.
   - Justification may only change whitespace: at most 8% expansion and 3% contraction, and glyphs are never stretched.
   - Section labels go in outlined boxes above the section start.
   - User locks are kept between sessions.
   - Boundary adjudication: an independent model (not the implementer) labels the candidates. The user only spot-checks a few dozen hard cases on one image.
5. **Transparent-overlay sources:** integrate the extractor as a separate acquisition and cleanup adapter (see the brief and `transparent/README.md`).
6. **Smaller items:**
   - Retry the download of `1Z-eXstSSI0`, which failed earlier because the disk was full.
   - Later, add Korean-channel videos to the corpus. Ask before downloading.

## How the user wants to work

- Reply in Korean, short and plain. Decide technical defaults yourself; ask at most one simple question. Long option lists overwhelm the user.
- Implementation goes to **one Claude Opus subagent** (high effort), never Codex. Each round is audited:
  - Astra (`codex-astra`) now runs at medium effort by default.
  - For the next audit, use Fable.
  - Every audit checks the process against the assigned task list.
- No human timing studies, ever.
- Horizontal-scroll videos are out of scope.
- Always ask before downloads and installs. Disk was nearly full once; check `df -h /System/Volumes/Data`, keep artifacts lean, and decode frames in memory.
- Stop leftover background agents and processes when a round ends. An old agent kept running and could have touched the same files.

## Verification commands (repo root)

```bash
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s backend/tests -p 'test_*.py'
npm --prefix desktop run verify:renderer-v2
npm --prefix desktop run test:desktop-node
```

Last known good: backend 392 OK (before round 4b), renderer 285, desktop-node 93.

## Session 2026-10-06 (evening): state after this round

- **Round 4b:** verified complete. The 4b agent finished its code before e2e_r5 and only its report was missing.
- **Job time:**
  - **Cause:** the r4→r5 growth came from macOS Low Power Mode on battery. Nothing ran in parallel. The r3→r4 growth was real minority-content cost.
  - **Speed patch:** `~/Documents/drum-score-corpus/reflow/patches/speed_fix_2026-10-06.patch` (moved out of the repo), applied.
  - **e2e_r6** (AC power, same ROIs as r5): S1nl 61 s, aOED 77, bF69 183, Q8 386, 01Mr 157. Strip PNGs, occurrences.json and tracking.json are identical to r5, except one Q8 episode `role`.
  - **That role difference:** set order broke a 1:1 tie at random. The tie now goes to `unknown`, with a test.
- **Fable audit:** conditional GO for measure milestones 0–1. Its must-fix items are done:
  - The content family is re-keyed at view transitions.
  - Seven new round-5 path tests.
  - Anchor cache release.
  - The `percentile_u8` ndim guard.
  - `run_e2e.py` now writes a code manifest.
  - Two bugs found while testing were fixed: the order of a placed later state, and alternate numbering order.
- **Measure milestones 0–1 are done (not on the export path yet):**
  - New code: `reflow_boundaries.py`, `reflow_units.py`, `reflow_accounting.py` and `tools/reflow_boundary_review/`.
  - Freeze: `~/Documents/drum-score-corpus/reflow/boundaries/freeze_v1/`, with 400 candidates and frozen m1 predictions.
  - **Labels:** `labels/labels_claude-opus.json`, frozen.
    - Eight independent Opus labellers did the first pass.
    - Two reconciliation labellers relabelled 92 items under the rules in DECISIONS.md "Boundary labelling rules". 23 labels changed.
    - Result: 200 SAFE / 200 UNSAFE.
  - **m1 score** (`score_m1_vs_claude-opus.json`):
    - 112 cuts accepted, 0 of them unsafe. 16/16 injected negatives were rejected, and accounting is exact.
    - Coverage is 56% overall (the gate is 60%) and 51% held out. bF69 is at 18%; the suspect is false repeat-dot detection on the dark theme.
    - Held-out verified accepted cuts: 59 of the 100 needed, so `INSUFFICIENT_EVIDENCE`.
  - **User spot-check:** the user looked over `hardcases/contact_sheet_v1.png` (36 tiles) and found it acceptable overall. They gave no verdicts per tile and find answering every tile too much. Treat the labels as accepted with no user overrides. Next time, show a few tiles with a yes/no question instead.
- **Next:**
  2. Tune on the dev split only. Held-out labels are known to the orchestrator, so a fresh held-out tranche is needed before claiming the gates.
  3. Milestone 2: prefixes, `reflow_lines.py` DP and slots at 8%/3%, section anchors, the pixel ledger, and pipeline integration after dependency resolution.

## Measure milestone 2 + fixes (2026-10-06, night)

- **Milestone 2 is built:** `reflow_lines.py`, `reflow_measure.py` and `tools/reflow_boundary_review/render_measure.py`. Option `JobOptions.measure_reflow` is off by default; with it off, output is byte-identical.
- **Classifier `reflow_boundaries-3`:**
  - Tuned on the dev split only. Dev: 77 accepted, 0 unsafe, coverage 90.6%.
  - Held-out m2 (orchestrator-scored): 90 accepted, 0 unsafe, 78% coverage. Below the 100 needed → INSUFFICIENT_EVIDENCE; a fresh tranche is needed.
- **Fable audit:** GO for milestone 3; NOT YET for making measure mode the default. Its fixes are done:
  - freeze_log events; a dev-only label file read by `dev_eval.py`.
  - `BARLINE_GROUP_ATTACHED_INK` → UNKNOWN.
  - A real repeat-sign video, gpYDVEsuXio in `e2e_rep1`: every repeat is LOCKED or has no seam. Fixtures were added.
  - A preview tail now hangs past the justified edge.
  - Suite: 500 OK.
- **Main finding:** on all 5 videos (`measure_m2/`, `measure_m3/`) every output line is exactly one source system.
  - Cause: every source system starts with a clef, and the brief's initial rule keeps a system start that has a printed prefix as a line start. It never deletes a clef to improve packing.
  - Effect: 3-measure sources (01Mr, Q8) stay 3 per line, and the block fills only 63–67% of the page width.
  - Measure reflow only helps if joining is allowed: drop the repeated drum clef at the start of a system that continues mid-line. Asked the user (2026-10-06).
- **Other open issues:**
  - gpYDVEsuXio ends `LAYOUT_CONFLICT` at 1.5 mm (fits 1.31 mm).
  - Strip artifacts: bF69 streaks, specks and a blob; Q8 player-UI specks.
  - 01Mr has a courtesy 4/4 after the final barline.

## Joins (2026-10-06, late)

- **Clean clef removal:** `reflow_units.declef_patch`. Line planner rewards about 85% fill. Suite: 510 OK.
- **Results:** `measure_m4/`
  - 01Mr: 17 → 14 lines, mostly 4 measures per line.
  - Q8: 46 → 38 lines, mostly 5 measures per line.
  - S1nl, aOED, bF69: unchanged. They already fill the width, and bF69's clefs fail the contamination check.
  - All 43 joins were inspected by eye: clean.
- **Open:**
  - Right edges are ragged in joined videos: 8 of 14 lines in 01Mr and 6 of 38 in Q8 reach the common edge. The 8% whitespace cap stops the rest.
  - The Q8 tempo mark now sits mid-line.
  - Strip artifacts remain.
  - The measure mode option is still off by default.
- **Asked the user:** keep the right edges ragged, or allow more whitespace stretch?

## Spread justification (2026-10-06, night)

- **Spread justification:** whitespace now goes into every eligible gap between note/rest columns as well as the barline corridors. Columns qualify only when their ink is unchanged for ±2 px: staff lines, and level beams that reach a stem on both sides. Per-gap caps and 15%/5% line limits apply, with Knuth-Plass-style balanced breaking (see DECISIONS "Spread justification"). New test file `test_reflow_spread.py`. Suite: 524 OK.
- **Results:** in `measure_m5/`. Lines justified, m4 → m5:
  - 01Mr: 8/14 → 8/12
  - Q8: 6/38 → 32/36
  - S1nl, aOED, bF69: still all justified
- **Remaining ragged lines** come from measure geometry. In 01Mr, 4-measure lines are 83% of the edge and 5-measure lines are 104%, so no single edge fits both within 15%/5%. The other ragged lines sit at section ends, the multi-rest first line of Q8, or the last line.
- Side-by-side for the user: `measure_m5/compare_01Mr_p1.png`.

## Fill every line (2026-10-06, late night)

- **User feedback:** prefers m5 (spread) to m4 (ragged), and wants every line filled to the right edge.
- **Rule:** DECISIONS "Fill every line".
  - Section starts no longer force a break.
  - The order of remedies is: break choice, then wider caps for that line (60% / 1.0 gap per gap, 25% per line), then rebalancing the final line, then a recorded ragged line.
  - The edge stays at or above 85% of the page width.
  - Lines are only as tall as their own units' rows.
- **Code:**
  - `reflow_lines-3`.
  - `reflow_measure`: `max_expand_wide` on gaps and slots, per-unit `rows_out`, row crop at render.
  - New `test_reflow_fill.py`. Suite: 533 OK.
- **Results** in `measure_m6/`. Lines justified, m5 → m6:
  - 01Mr: 8/12 → 12/12, 1 page. 8 lines use the wider caps; max per-gap growth 0.45.
  - Q8: 32/36 → 31/33, 4 → 3 pages. 2 lines use the wider caps; max growth 0.31.
  - S1nl 18/18, aOED 25/25, bF69 26/26: same breaks as m5.
- **Still ragged (Q8, unavoidable, `LOCKED_SPAN`):**
  - The opening multi-rest system: one atom, 1417 px, about 17 px of whitespace.
  - The final 12-bar rest: 1080 px. The 2/4 system before it must start a line, and that segment is too long for one line and too short for two.
- **Side-by-side images:** `measure_m6/compare_01Mr_p1.png` and `compare_Q8_p1.png`.
- **Known, not new:**
  - Q8 blue player-UI specks under the final line.
  - aOED line 11 has lyrics cut by the source strip.
  - In 01Mr's last line, measures 52–53 are sparse in the source and are stretched next to a dense measure 51.

## MVP wired into the app (2026-10-07)

- **Measure reflow is ON by default for new jobs.**
  - Jobs saved before the option existed read as off.
  - The toggle "악보 배치 / Score layout" is on the export screen and on the review screen (left panel).
  - A review export can override the job's choice.
  - `result["measure_reflow"]` records the mode: `measure_lines` / `fallback_whole_systems` + reason / `off`. A fallback shows a warning on the review screen.
- **Rendering (`measure_m6` rules):** joins with clean clef removal, spread justification, every line filled, and section starts may fall mid-line.
- **Suites:** backend 546, renderer 296, desktop-node 93.
- **`e2e_mvp1` (01Mr):** the job PDF is identical to `measure_m6`, and the review export works on, off and default.
- **Not verified:** the Electron window itself (headless Chrome fixture only), a real fallback, and packaged builds.
- **Next:** the user tries the app (`npm --prefix desktop start`) on real videos and reports issues.
- **Known issues:**
  - bF69 clefs are contaminated, so it gets no joins.
  - Strip artifacts.
  - 01Mr's last line has uneven spacing.
  - Two Q8 lines stay short (LOCKED_SPAN).
  - Fresh held-out tranche still needed for the safety evidence (90/100).

## Every line full (2026-10-07)

- **User report:** 베텔기우스 job `34ad6b5e…` had six lines at 45–59% fill. Causes and rule: DECISIONS "Every line full".
- **Code:** `reflow_lines-4` (tier 2 contraction, tier-3 even spread, `EDGE_TIER3_COST`); `reflow_units.clef_patch`/`declef_patch` keep ink outside the staff lines; `reflow_measure` records `audit.join_refusals`. New tests in `test_reflow_full_lines.py`; affected tests updated.
- **User's video (rendered in a scratch dir, job untouched):** 21 lines/3 pages → 18 lines/2 pages, every line at 100%. Every source system stays whole; three of them use the tighter gaps.
- **Corpus `measure_m7/`:** 01Mr, S1nl, aOED and bF69 are identical to m6. Q8: edge 2032 → 2041. The final segment's short line is now a tier-3 line (925 px stretched to the edge, gaps up to 3.8×) instead of a ragged 1080 px line. Only the opening multi-rest stays short (`LOCKED_SPAN`).
- **Still open:** bF69 clefs are a single merged component next to a system bracket, so `CLEF_PATCH_CONTAMINATED` there is genuine and it still gets no joins. The edge of S1nl, aOED and bF69 is 87–94% of the page (a centred block), unchanged.

## Real-use fixes (2026-10-07, early morning)

- **User's first real video** (ZMbgR3pR0xU, 유우리 – 베텔기우스, 4K AV1): the output had half-empty lines.
  - **Cause:** the source systems were 1.6% wider than the page line. Lyric-heavy systems could not shrink that much, so they were split.
  - **Fix:** a tighter-gap tier, the safe clef-removal relaxation (ink wholly above or below the staff), `audit.join_refusals`, and the "Every line full" rule in DECISIONS.md.
  - **Result:** 18/18 lines full, 2 pages (was 21 lines, 3 pages). Side-by-side images are in the session scratchpad.
  - **Corpus (`measure_m7`):** only Q8's opening multi-rest line is short.
- **4K speed:**
  - When the staff space is over 28 px, crops are scaled to 20 px (`observations.py`, recorded as `work_scale`).
  - YouTube downloads are capped at 1440p, preferring VP9/H.264 over AV1.
  - Result: 4K job 236 → 145 s in-process. S1nl is identical to e2e_r6.
- **Suites:** backend 554 OK (rerun after both agents finished).
- **Next:**
  - Lines on S1nl, aOED and bF69 end at a common edge at 87–94% of the page width, not at the page margin. The user wants every line to run to the margin, like the teacher PDF.
  - The second full decode in the fine pass is still there.
  - The app must be restarted to pick up these fixes.

## Jump view, milestone 1 (2026-10-07)

- **Code:** `reflow_jump.py` (seam registration, panel and screen-fixed pixels, `classify_runs`, `reflow/jump.json`). `analyse_source` writes `jump.json` after tracking. Nothing reads the file yet, and a failure there never changes the job. Tests: `test_reflow_jump.py`. Suite: 563 OK.
- **Thresholds frozen** before the held-out run: config hash `b3c5a3707f2eef02` (`JUMP_FREEZE.md`, `jump_m1/freeze.json`).
- **Ground truth:** `reflow/tools/jump_gt.py`.
  - It reads `#N` panel labels with digit templates, so a digit partly hidden by notation is only read from its visible pixels.
  - It also reads the numbers over barlines, and checks that barlines in the overlap agree.
- **Results** (`jump_m1/<video>/seams.png`, `seams.json`, `gt.json`):
  - **_7gPeY5Lcrk:** 69/71 seams verified. 65 of the 69 are checked against the numbers, with 0 lost and 0 duplicated measures.
  - **qA-M_f0DMjw:** 26/36 verified, all 26 pass. The 10 unverified seams are repeated grooves; in 7 of them the pixel-best offset was wrong.
  - **Pxt93gz8jas (held out):** 20/33 verified. It prints no measure numbers, so only the barline check applies: 19 agree, 1 has no barline in the overlap.
- **Next (milestone 2):** panorama strips over verified chains, keeping both sides at an unverified seam with `JUMP_SEAM_UNVERIFIED`. Repeated-groove seams are frequent (10/36 and 13/33), so resolving them (OCR, or the cursor) matters more than planned.

## Jump view, milestone 2 (2026-10-07)

- **Code:**
  - `reflow_jump-2`: seam resolution (`resolve_seam`, `slot_evidence`, `prior_fit_dx`, `numbers_check`), panorama strips (`panorama_chains`, `build_panorama`, `chunk_cuts`, `build_jump_systems`), `remaining_unsupported`.
  - `reflow_pipeline.analyse_source`: jump-view runs become strips `jmp-RR-NNN` (layout `jump_view`) in video order; `result.reflow.jump_view`; smooth scroll stays `UNSUPPORTED_LAYOUT` with the same message.
  - `reflow_occurrences.build_occurrences(exclude_episode_ids=...)`; `reflow_boundaries.member_regions` shifts each member by its display offset.
  - Jump strips only: measure numbers over a barline are skipped when the seam is proposed; a span wider than the page line is split at a barline that only a line, slur or text crosses (`OVERSIZE_SPAN`); a single measure wider than the line gets its own line at a smaller scale (`oversize_units`); without a verified clef to copy, lines start bare.
  - `main.py`: KO/EN warning for `JUMP_SEAM_UNVERIFIED`.
  - Tests: 9 new in `test_reflow_jump.py`. Backend 572 OK, renderer 302 OK, desktop-node 93 OK.
- **Frozen** before the post-freeze runs: config hash `2e5887c559828797` (JUMP_FREEZE.md, `jump_m2/freeze.json`).
- **Seams** (`jump_m2/<video>/jump.json`, `seam_gt.json`):
  - `_7gPeY5Lcrk`: 69 verified + 2 resolved (typical jump + cursor prior), 0 left. Ground truth: 25 direct + 41 span checks pass. One span (#54→#62, across the resolved seam 42→43) counts 9 barlines for 8 numbers; the extra "barline" is the 3/4 time signature (looked at by hand: 8 barlines).
  - qA-M_f0DMjw: 26 verified + 10 resolved (typical jump; 4 also confirmed by measure numbers), 0 left. Ground truth: 36/36 seams pass, 0 lost, 0 duplicated. On the final strips, 88 of 97 numbers read follow one sequence 2…107 with no duplicate; the other 9 are one-digit fragments of the expected number (OCR).
  - Pxt93gz8jas (seen in milestone 1, not a clean held-out): 20 verified + 13 resolved (typical jump), 0 left. It prints no numbers, so there is no measure ground truth; barlines in the overlap agree on 10 of the 13 resolved seams (3 have none).
  - No unseen jump-view video exists in the corpus. Negatives after the freeze: waMCMJD7bQk, xft2krEJNBE and rsUfI3EKAj4 stay `UNSUPPORTED_LAYOUT` with no jump run.
- **Outputs** (app backend over HTTP, `jump_m2/<video>/job_export/`):
  - `_7gPeY5Lcrk`: 14 strips, 6 pages, 76 lines, 52 full, 24 short (`LOCKED_SPAN`). The measures are 55–105% of the page line at 1.5 mm, so 71 lines hold one measure. At 1.2 mm: 3 pages, 53 lines, 48 full. Job 186 s (was rejected after about 145 s).
  - qA-M_f0DMjw: 3 strips, 2 pages, 25 lines, all full, 4–6 measures per line.
  - Pxt93gz8jas: 5 strips, 2 pages, 27 lines, all full.
- **Seen on the pages:** stitches are not visible; there are no panel remnants. Clefs start every line on `_7gPeY5Lcrk`. qA and Pxt lines start bare: qA's clef sits next to "drm.", so it cannot be copied, and Pxt shows no clef at all.
- **Known defects:**
  - Cursor colour left on notes the cursor covers in every frame of a display (`OVERLAY_UNRECOVERED`): `_7g` first note, blue; qA measures 4 and 107, yellow.
  - The left frame edge of the first `_7g` display shows as a thin line.
  - qA measure numbers sit at the end of the previous line when a line breaks at them.
- **Regression:** the 5 vertical corpus videos re-rendered from `e2e_r6` records are byte-identical to `measure_m7` (PNG). S1nl end to end through `analyse_source` is pixel-identical too.
- **Next:**
  - Ask the user: a smaller staff size for wide jump-view measures? 1.2 mm gives two measures per line on `_7g`.
  - Cursor colour on notes that every frame covers.

## Automatic staff size and line-start measure numbers (2026-10-07)

- **Rules:** DECISIONS "Automatic staff size for dense charts" (with its implementation notes) and the corrected jump-strip number rule.
- **Code:**
  - `reflow_measure.compose(auto_staff_size=)`: `_plan_at` (units and line breaks only), `staff_size_candidates`, `choose_staff_size`, one `_render`; `plan.staff_size`. `build_atoms(doc_cache=)` and `reflow_units.build_document(analysis_cache=)` reuse strip analyses and frame-edge cleanups across sizes.
  - `reflow_pipeline.compose_systems(auto_staff_size=)`. `main.py`: on for the job's compose; in review export only while the document keeps the job's size (`reflow.staff_gap_mm_explicit`); `result.measure_reflow.staff_size`.
  - Renderer: `deriveReflowInfo().autoStaff`, review note `review.staffSizeAutoReduced` (KO/EN).
  - Jump strips: `number_over_barline` and `_move_line_start_numbers`; `audit.moved_measure_numbers`.
  - Tests: `test_reflow_staff_size.py` (15), `test_reflow_jump_numbers.py` (3), renderer note test. Backend 590 OK, renderer verify OK (297), desktop-node 93 OK.
- **Jump videos** (app backend over HTTP, `jump_m3/<video>/job_export/`):
  - `_7gPeY5Lcrk`: 1.3 mm (short lines at 1.5 / 1.45 / 1.4 / 1.35 / 1.3 / 1.25 / 1.2: 24 / 11 / 14 / 15 / 5 / 5 / 5). 4 pages, 56 lines, 51 full (was 6 pages, 76 lines, 52 full). The 5 short lines are single measures next to a forced break. Compose 34 s (job 216 s).
  - qA-M_f0DMjw and Pxt93gz8jas: full at 1.5 mm, unchanged size. qA: 23 of 24 line-start numbers moved; "100" stays at its line end (`NO_ROOM_AT_LINE_START`).
- **Vertical corpus** (from `e2e_r6` records, `jump_m3/vertical_check/identity.txt`): 01Mr, S1nl, aOED and bF69 are byte-identical to `measure_m7`. Q8 changes: its opening multi-rest line was short at 1.5 mm, and 1.2 mm fills every line, so Q8 is now 2 pages, 25 lines, all full (was 3 pages, 33 lines, 1 short).
- **Not exercised:** the packaged app and the review screen in a live window (only renderer tests).

## Review export as a background task (STRATEGY 1c, 2026-10-07)

- **API:**
  - `POST /jobs/{id}/review-export` checks the request at once (404, job still running, `LEGACY_JOB`, selection, formats), then answers **202** with a task: `task_id`, `revision` (the next revision), `state` (queued/running/done/failed/cancelled), `stage` (planning, sizing, rendering, writing), `progress`.
  - Poll with `GET /jobs/{id}/review-export/{task_id}`; `GET /jobs/{id}/review-export` returns the latest task, or 404. Cancel with `POST .../{task_id}/cancel` (POST because CORS allows only GET and POST).
  - When it finishes, `result` holds the payload the synchronous call returned, plus `revision`. On failure, `error_code` keeps the existing codes (`UNCUT_STRIP_UNAVAILABLE`, `LAYOUT_CONFLICT`, `INVALID_REQUEST`, `EXPORT_FAILED`), with `error` (the detail) and `error_status`.
  - One export per job at a time: a second request gets **409 `EXPORT_IN_PROGRESS`**, and the running task is not superseded. A capture crop on the same job gets the same 409.
  - Running exports count as active work for update-lock, clear-cache and `/maintenance/activity` (`active_exports`).
- **Code:**
  - `backend/app/export_tasks.py`: the task store, mirrored to `<job>/review_export_task.json`. A file left queued or running without a live task reads as failed `EXPORT_INTERRUPTED` after a restart.
  - `process_control.report_progress` / `progress_scope`: a cancel check plus a progress callback, called from `compose_systems`, `reflow_measure.compose` (per staff-size candidate) and `export_composed_pages` (per page).
  - The last cancel point comes before the staged folder is installed, so a cancel or failure keeps the previous export and result.
  - `main.review_export` remains as a synchronous callable for tests and tools; it has no HTTP route.
- **Renderer:**
  - `api.reviewExport` starts the task and polls it (500 ms, then up to 2 s; up to 5 dropped polls are retried) with the normal 30 s request timeout. `REVIEW_EXPORT_TIMEOUT_MS` is removed; the preload `timeoutMs` support stays.
  - The review toolbar shows stage · percent with a meter and a Cancel button, in KO and EN; keyboard focus moves between Rebuild and Cancel.
  - A reload, or an `EXPORT_IN_PROGRESS` answer, follows the running task.
  - After a cancel, the selection is still marked unapplied and a notice says the previous files are kept.
- **Corpus tool:** `run_e2e.py` polls on 202 and still accepts 200 from an older backend. It logs `review_export.task`.
- **Suites:** backend 601 OK (10 new in `test_review_export_tasks.py`); renderer verify OK (313); desktop-node 94 OK.
- **E2E** (`reflow/e2e_jobs1/S1nlqQdnUks`, ROI from e2e_r5): the review export completed through polling in 3.1 s (queued → planning → rendering → writing), revision 2.
- **Screens:** fixture screenshots at 1440×960 and 1120×840 (KO and EN, running and cancelling) are in the session scratchpad `export_jobs/`. The live Electron window was not exercised.
- **The app must be restarted** (backend and renderer) to pick this up.

## Evaluation set and baseline (STRATEGY 1a/1b, 2026-10-07)

- **Set:** `~/Documents/drum-score-corpus/eval_v1/` holds `manifest.json` (frozen), `README.md` (split, rules and rerun command) and `videos/` (12 videos, about 0.9 GB, at most 1440p).
  - 6 validation videos: w7mK, GTOc, SZwT, Fzc0, SHvfn, Z4eb.
  - 6 sealed holdout videos: 0MiL, 4M0X, Dr5j, TeoV, m_YP, RnY5. `dashboard.py` refuses a spec with a holdout entry.
- **Dashboard:**
  - Tool: `~/Documents/drum-score-corpus/reflow/tools/dashboard.py`.
  - Spec: `eval_v1/baseline_spec.json` (6 dev videos with the e2e_r6 ROIs, plus the 6 validation videos with the unchanged auto-ROI).
  - Output in `eval_v1/baseline_dashboard/`: `dashboard.md` and `.json`, `contact_sheet.jpg`, and per-video metrics and run logs. Metric definitions are at the end of `dashboard.md`.
- **Baseline:** 3 of 12 acceptable (S1nl, 01Mr, w7mK). Failure classes:
  1. **Jump view (SHvfn, Z4eb):** `UNSUPPORTED_LAYOUT`. Seams were found, but short leftover stretches were classified as horizontal scroll, so the whole job was refused.
  2. **Fzc0:** "done" with 0 pages. At 1.5 mm its systems are wider than the page (they fit at about 1.38–1.4 mm), the measure plan is invalid, and the result is a layout conflict that is not shown as a failure.
  3. **GTOc:** a transparent overlay (white notation over live video) is processed as if supported. 13 of 13 lines show the video behind the score. It should be reported as unsupported.
  4. **Overlay remnants:**
     - SZwT: a blue cursor and a magenta band under every line, and the "Next" inset leaks in (90 components).
     - aOED: 23 components. bF69: 8. Q8 and `_7g`: a few each.
  5. **Layout:**
     - bF69 lines stop at 87% (25 of 26 under 90%).
     - S1nl, aOED and SZwT end 6–8 mm inside the right margin.
     - `_7g`: 3 breaks at non-SAFE boundaries (`OVERSIZE_SPAN`, to be reverted). Gap strain up to 3.0×, 1.3 mm automatic size.
     - Q8: spread up to 2.79×.
- **Pro checkpoint pack:** `~/Documents/drum-score-corpus/advice_pack_2/` (dashboard, strategy, contact sheet, examples 02–06). The prompt is in [PRO_CHECKPOINT_STEP1.md](PRO_CHECKPOINT_STEP1.md).


## Update 2026-10-08 (Step 2C round, waiting on Pro checkpoint #3)

- Workers now run on Codex `gpt-6.1-sol` at **high** via `codex-backend` (user asked; Claude tokens are short). Audits stay xhigh. Codex's sandbox cannot write to `~/Documents/drum-score-corpus`; workers stage under the session scratchpad and the lead copies.
- Done this round: dashboard v3 (`reflow/tools/dashboard.py`, re-measure in `eval_v1/step2_r4_dashboard_v3`); visibility gaps (per-system uncertain-mark bundles, SOURCE_CLIPPED, translucent plate → review_required, explicit size mode, CJK header font); `reflow_ledger.py` + export gate in both paths (no producer hooks yet → every real job is `LEDGER_UNASSESSED` / review_required); bounded optimizer `reflow_optimize.py` (policy B2 best on dev, NOT the default; legacy stays default); audit round 5 (7 HIGH silent-loss findings) fixed.
- Open: 01Mr half-empty line under B2; _7g over-wide LOCKED groups (no plan); review burden exploded after "never delete a hypothesis" (Q8 1,899 uncertain events, SAFE 114→78; _7g 248 unmatched, 14/14 flagged); ledger producer hooks 1–5 (`LEDGER.md` ~line 346); validation seen 3× (protocol deviation).
- Pro prompt: `PRO_CHECKPOINT_STEP2C.md`, attachments `~/Documents/drum-score-corpus/advice_pack_4/`. Optimizer experiment outputs: `~/Documents/drum-score-corpus/eval_v1/step2c_opt/` (REPORT_v2.md, 2.4 GB).

- 2026-10-08 later: Pro checkpoint #3 reply weighed → STRATEGY "Step 2C checkpoint #3" and "Step 2D plan (in force…; work not started)"; rules in DECISIONS "Step 2D rules". Next session starts at Step 2D item 1 (ledger integration).
