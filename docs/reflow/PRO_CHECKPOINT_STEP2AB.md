# ChatGPT Pro checkpoint after STRATEGY Step 2A + 2B (2026-10-07)

- Relayed by the user, with the attachments in `~/Documents/drum-score-corpus/advice_pack_3/`.
- Treat the reply as advice to check against code and the dashboard, not as orders. Record what is adopted in STRATEGY.md before Step 2C starts.

## Attachments

| file | what it is |
|---|---|
| `00_round_summary.md` | what changed, each of your exit conditions → status, audit process, residual limits |
| `00_strategy_current.md` | STRATEGY.md now (incl. how your last reply was weighed and the revised Step 2) |
| `01_dashboard_baseline_v2_recomputed.md` | the Step 1 baseline re-measured under metric definitions v2 (0/12) |
| `02_dashboard_step2_final.md` | the same 12 videos on the current code |
| `03_audit_identity_overlay.md` | source audit of SZwT 26 → 26 → 30 and of the "Next" inset / cursor / band |
| `04_decisions_step2A.md` | the product rules written for 2A |
| `05_contact_sheet_page1_all_videos.jpg` | page 1 of every output, current code |
| `06_SZwT_p1_before_after.jpg` | SZwT page 1, baseline vs now |
| `07_Fzc0_now_passes_p1.jpg` | was "done" with 0 pages; now 1.4 mm auto, 3 pages |
| `08_Z4eb_jump_dense_chops_p1.jpg` | jump video, now complete; short and uneven lines (2C problem) |
| `09_bF69_inner_edge_p1.jpg` | lines stop 18.7 mm inside the margin (planned, not rendered) |
| `10_overlay_recovery_before_after_user_confirmed.jpg` | 3 crops the user confirmed |
| `11_incomplete_chart_on_paper_synthetic.jpg` | how an incomplete chart is marked on paper (synthetic data) |
| `12_SHvfn_jump_tier3_p1.jpg` | jump video lines that reach the edge only through 4× gaps |
| `14_aOED_lyrics_clipped_bottom.png` | lyrics cut at the bottom (pre-existing) |
| `15_aOED_source_frames_bottom_edge.jpg` | raw source frames: the video itself cuts the lyrics at y = 1080 |

## Prompt

```text
Checkpoint review #2 for the drum-score-video → clean A4 PDF app (raster capture, cleaned source images reflowed onto A4). Last time you reordered Step 2 into 2A (safety, truthful completion, coverage), 2B (primary score clean), 2C (bounded optimizer), and set exit conditions. 2A and 2B are done; 2C has NOT started. Attached: 00_round_summary.md (each of your exit conditions → status), the current strategy, dashboards before (v2 re-measure of the old outputs) and now, the source audit, and images.

RESULTS (dashboard v2, 12 non-holdout videos; holdout still sealed):
- Before (old outputs, v2 metrics): dev 0/6, validation 0/6 pass the automatic screening.
- Now: dev 0/6, validation 1/6 (Fzc0). But the leading failure moved: GTOc is correctly refused (UNSUPPORTED_SOURCE), Fzc0 renders (1.4 mm auto, was 0 pages), both jump videos complete with 0 leftover intervals, non-SAFE breaks 0 everywhere, the SZwT duplicate is gone and its silently dropped line is back, the gray block / pink band / cursor are gone (user-confirmed crops). Remaining failures are now mostly LAYOUT (lines end 1.6–18.7 mm inside the margin with no recorded reason; or reach the edge only via wide/extreme caps: z up to 7.9, relative gap change up to 3.0 = 4× width) and suspected colored remnants (aOED 23 components, SZwT ~30 = the static MuseScore "page/break" icon at each line end, bF69).
- See 02_dashboard_step2_final.md "Key measures" for per-video deficits, z, tiers.

PROCESS ISSUE WE WANT YOUR VIEW ON:
Every change set was audited by an independent model that builds synthetic counterexamples through the real tracker → occurrences → strip code. Four rounds: 18 findings, 16 of them silent-loss paths (e.g. gray measure numbers erased before the identity comparison so two numbered lines merged; a dot under a static band hidden by whole-column accounting; 1-px strokes paper-filled; jump coverage certifying excluded displays; panorama ownership discarding a dot present only in the non-owning display's overlap; dark-paper finishing whitening gray-120 dynamics). All fixed with regression tests; real-video outputs were unchanged by them, except one fix that regressed a dev video (26 → 43 placed) and was caught by the dashboard. Each round finds new paths in a different module. We are considering replacing local patches with ONE end-to-end invariant: a source-to-output ink ledger — every component that persists in a majority of a display's observations (after removing positively identified scaffold/chrome/cursor) must be found in the exported page at its registered position, or be listed in a visible review item / alternate. Accounting would run on the final rendered pages, independent of each module's own bookkeeping.

QUESTIONS:
1. Ledger: is an end-to-end source-to-output component ledger the right structural answer to the recurring silent-loss findings? How would you define "persistent component", the registration chain (observation → display composite → strip → page placement incl. scaling), the matching tolerance, and what counts as an acceptable explanation (staff scaffold, chrome, cursor, preview inset, overlap duplicate)? Should it gate export (fail/review) or only flag? Should it come before 2C, or run alongside? How do we keep it from becoming another module with its own holes (what minimal independent design)?
2. 2C caps: with fixed directional gap caps, most line-switch charts cannot reach the margin: barline corridors give ~1.4% of line width, inner note gaps (≥ 0.6 staff gap) add a little; lines need 4–9% (S1nl 6.0 mm, aOED/SZwT 7.4 mm, bF69 18.7 mm short on a 180 mm music width). The user wants every line full and also disliked visibly wide gaps. Give concrete numbers: per-gap max expansion/contraction (in staff gaps or % of natural), whether inner note gaps may carry more than barline corridors, and the document objective weights (short-line cost vs distortion vs staff-size cost vs pages). When the target is unreachable at 1.5 mm, should the objective prefer a smaller staff size (floor 1.2 mm) that lets lines regroup, or accept a declared inner edge with a recorded reason? How should "N measures per line" preference (teacher layout ≈ 4) interact?
3. Dense jump-view chops (SHvfn, Z4eb, _7g): today they reach the edge only via the old tier-3 spread (gaps up to 4×). Under bounded caps they will become short lines or smaller sizes. What is the acceptable outcome for 1–2 dense measures per line: ragged with reason, smaller size, or a per-chart compact profile?
4. Frozen-input optimizer experiment: what small predeclared comparison would you run (parameter grid, which videos as frozen strips, metrics and pass rule) so we stop tuning at the right point?
5. Remnants and Step 3: the remaining suspected remnants are mostly a static editor icon (MuseScore page/system-break marker) touching notation at line ends, and thin colored separators. Is it right to leave them to Step 3 "editor-marker cleanup", or should they block 2C?
6. Scope before holdout: our draft supported class = opaque paper (light, dark, dark translucent plate) videos of the three channels with line-switch, page-turn or jump view; refused = notation composited over live video, horizontal smooth scroll. Acceptance = dashboard v2 "acceptable" + the ledger (if adopted). Anything to change before we freeze it?
7. Any red flags in the attached results or process (e.g. the automatic screening proxy, the 0.5 mm full-line tolerance measured on page images, known residual limits listed in 00_round_summary.md; the aOED lyrics are cut by the source video itself — how should such source-cut lines be presented)?

Be critical and concrete. Say plainly if the plan should change before 2C.
```
