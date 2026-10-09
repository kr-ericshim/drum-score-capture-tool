# Jump-view support: plan (Fable, 2026-10-07)

**Status:** approved by the user on 2026-10-07. Milestone 1 done. Milestone 2 done (2026-10-07), with seam resolution pulled forward from milestone 4 and the KO/EN review warning from milestone 3: jump-view runs now become panorama strips and go through the measure layout (HANDOFF "Jump view, milestone 2"). Lines on `_7gPeY5Lcrk` held one measure each at 1.5 mm; since 2026-10-07 the automatic staff size (DECISIONS "Automatic staff size for dense charts") lays it out at 1.3 mm, two measures per line (HANDOFF "Automatic staff size").

## Generality rule (user, 2026-10-07)

The logic must not be tuned to one video.

- **Development videos:** `_7gPeY5Lcrk` (app job) and qA-M_f0DMjw.
- **Held-out check:** Pxt93gz8jas (no panel, 2-frame eased jump). It is run once, after the thresholds are frozen.
- **Pass:** all three show 0 lost and 0 duplicated measures.
- **Target architecture:** one measure stream for every video type (page/line switch, jump view, later smooth scroll), followed by a single layout step.

A jump-view video shows one continuous score line. Every few seconds the view jumps right by about 1.7 measures, and consecutive views overlap.

- **Example video:** `_7gPeY5Lcrk`. Today it is rejected as `UNSUPPORTED_LAYOUT`.
- **Probe results:** `scratchpad/jumpplan/probe*.txt` (session scratchpad).

## Feasibility: feasible, fail-closed

- **Displays:** the tracker already gives one episode per stable display. There are 72 episodes; jumps take 0.1 s, with no motion inside an episode.
- **Seams:** found by searching for the horizontal offset of the overlap. 69 of 71 consecutive seams verified.
  - Typical residual is 8–16 against a threshold of 25. The second-best match is at least 2× worse.
  - The 2 unverified seams are periodic content, where two different offsets both fit.
- **Measures:** about 1130 px wide, so the measure that straddles a jump must be stitched through the overlap.
- **Detectors:** `sd.find_barlines` is correct on this video. The cursor is coloured and is removed by `compose_members`.
- **Measure numbers:** `#N` sits in a translucent left panel, at x < ~110 px.
- **Corpus:**
  - qA-M_f0DMjw and Pxt93gz8jas are jump-type.
  - rsUfI3EKAj4 and waMCMJD7bQk are smooth scroll and stay unsupported.
  - xft2krEJNBE shows no horizontal motion; re-check it as a page video.

## Approach

New module `backend/app/pipeline/reflow_jump.py`:

- **`register_seams`:** builds an overlay-free composite per episode and excludes the left panel.
  - A seam is verified when the residual is ≤ 25, the ratio to the second-best match is ≥ 2, and the overlap minus the panel is ≥ 40 px.
  - The cursor-motion prior is used only as a sanity flag.
- **`classify_runs`:** marks a run of ≥ 3 consecutive verified seams as `jump_view`. Smooth scroll stays `UNSUPPORTED_LAYOUT`.
  - It is attempted only when `classify_layout` reports horizontal motion, or when ≥ 30% of pairs correlate. Other videos are not touched.
- **`build_chains`:** builds a panorama per chain of verified seams.
  - A per-column owner map keeps each measure exactly once.
  - The seam is cut at the column of minimal difference.
  - Chains longer than 40k px are split at a clear barline.
- **Fail-closed:** at an unverified seam, both partial measures are kept and flagged `JUMP_SEAM_UNVERIFIED`. Nothing is dropped or merged.
- **After that, the existing path:** `reflow_units` → SAFE seams → `reflow_lines` / `reflow_measure`.

## Integration points

- **`reflow_pipeline.analyse_source`:** after `build_episodes`, run the jump module. `build_occurrences` skips jump-view episodes, and the jump systems are added in video order.
- **`reflow_jump.write_strips`:** writes strips with the same record keys as `build_strip`, plus a `jump` section.
- **`reflow_boundaries.member_regions`:** shifts each member's barlines by its display offset.
- **Records:** `reflow/jump.json`, `layout_intervals` kind `jump_view`, and `result.reflow.jump_view`.
- **Review:** a `JUMP_SEAM_UNVERIFIED` warning in KO and EN.

## Verification

- **Ground-truth tool** (`~/Documents/drum-score-corpus/reflow/tools/jump_gt.py`): tesseract reads the `#N` numbers in the panel.
  - At every verified seam, the jump in `#N` must equal the number of full barlines crossed. Any mismatch means a lost or duplicated measure.
  - The owner map must cover every column.
- **Synthetic tests** (`test_reflow_jump.py`):
  - a 12-bar strip windowed by jumps, with the panel and a cursor;
  - periodic bars, giving an unverified seam with both parts kept;
  - smooth scroll staying unsupported;
  - a page switch getting no `jump_view`.
- **Suites and corpus:** the three suites. The 5 vertical corpus videos must stay byte-identical to `measure_m7`, and rsUfI3EKAj4 must stay unsupported.

## Milestones

1. **Seam registration, `jump.json` and the GT tool; no output change.** Show the user the seam table and a contact sheet.
2. **Panorama strips, integration and fail-closed flags.** Show the user this video's PDF, the OCR measure check and the corpus identity check.
3. **Review warning and i18n, plus qA and Pxt as extra evidence; update the docs.**
4. **Optional:** OCR in the app to resolve periodic seams; smooth scroll through the same panorama.

## Risks

- **Measure width (found in milestone 2):** `_7gPeY5Lcrk` measures are 55–105% of the page line at 1.5 mm, so most lines hold one measure and 24 of 76 lines stay short. At 1.2 mm the same video gives 53 lines, 48 full.

- Periodic seams stay flagged.
- The panel edge may bleed through (add a +15 px margin).
- A clef replica may fail next to the "7" signature, so lines would start bare.
- Jobs take about 2 minutes longer.
- Long chains need memory, so they are split into chunks.

## Default chosen

Measure numbers in the panel are dropped together with the panel. The chart prints no synthesized measure numbers, in line with "never retype source text". The user may revisit this.
