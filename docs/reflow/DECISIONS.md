# Clean reflow: decisions

Design reference: [DESIGN_astra.md](DESIGN_astra.md) (GPT-6 Astra, 2026-10-06). This file records what the user decided and the defaults in force; it overrides the design where they differ.

## Decided by the user (2026-10-06)

- The app's default and only final output is the clean reflowed chart (cleaned source images laid out on A4). OMR re-engraving is shelved; no raw-stitch alternative output.
- No footer text, no link-to-source feature.
- No human timing studies in any evaluation.
- Horizontal-scroll videos are out of scope (not a later phase): uncommon in the Korean hobbyist YouTube videos the app targets, which usually switch/turn systems. The app shows an explicit unsupported state for them. Corpus videos treated as horizontal: qA-M_f0DMjw, rsUfI3EKAj4, Pxt93gz8jas, waMCMJD7bQk, xft2krEJNBE.
- Implementation by one Claude Opus agent (not Codex); GPT-6 Astra reviews results and audits the process against the assigned task list.

## Reference look (user's teacher PDF, `/Users/ericshim/Downloads/뉴진스-GODS.pdf.pdf`)

Measured from the PDF (A4 595x842 pt, 2 pages):
- Title centred on page 1, credits right-aligned beneath; tempo mark above the first system. (Corrected 2026-10-06 after Astra measured the PDF.)
- About 4 measures per line (a preference, not universal), 8 lines per page, lines justified to the same right edge; reference staff gap ≈1.6 mm (product default stays 1.5 mm).
- Section labels (I, A, B, C, Br, O) are small outlined boxes above where the section starts; usually at a line start, but `Br` appears mid-line, so a section does not always force a new line.
- Lyrics are kept under the staves.
- Page number at the bottom left from page 2 (page 1 unnumbered). This replaces the design's "upper outer margin" default.

## Defaults in force (from the design; change only on user request)

- Order = the order the video shows the systems (decided by Claude on 2026-10-06 after the user found the choice too complex; user may revisit). When the video goes back to an earlier system (repeat/D.S.), it is placed again; nothing is dropped. **Exception (2026-10-09, Pro checkpoint #4 option iii):** an established replay block — at least 3 consecutive systems whose whole cleaned strips (notes, measure numbers, text) match one unique earlier consecutive block in the same order — is left unchecked by default (`REPLAY_COLLAPSED`, `exclusions.replay_blocks`; `reflow_occurrences.collapse_replay_blocks`). Its strips stay in review and can be ticked back in. Single, two-line, ambiguous or out-of-order matches stay placed. The D.S./coda signs themselves are not detected; they stay in the kept earlier systems. Other likely repeats are offered as a one-click "remove duplicate" suggestion, never a blocking question. Export is not blocked by identity questions.
- Two pages is a soft target; never shrink below the chosen staff size or drop systems to reach it.
- Lines justified only within safe slack; otherwise a recorded ragged line. No glyph stretching.
- All score text is preserved (section labels, tempo, lyrics).
- Low source resolution: warning plus actual-size check; no invented detail.

## Audit fixes in force (round 2, 2026-10-06)

- Short displays (< 1.5 s or < 3 observations) are hidden only with pixel evidence that a kept display shows the same content (same image, or every column block of its notation/text drawn by one neighbouring kept display) or that it holds nothing beyond staff lines. A view transition alone is not evidence. First and terminal displays are never hidden. Every other short display is listed in review, unchecked, with its own strip. The result reports `reflow.exclusions`.
- Tracker continuity joins only verified links (preview row promoted to the active row, or a row moving with its page by one shared offset) that are one-to-one; competing or unverified matches stay separate systems and become "looks similar" notes.
- A preview tail (start of the next system at a row's right end) is cut only when the next occurrence is verified to start with it; the strip record maps the cut columns to the destination system. Otherwise it is kept and flagged `PREVIEW_TAIL_UNVERIFIED`.
- ~~The staff size is never reduced automatically.~~ Superseded by "Automatic staff size" and "Step 2A" below. A strip that does not fit A4 at the chosen size is a layout conflict shown in review; the user excludes it or chooses "use N mm for this document" (the largest size that fits, never below 1.0 mm). Invalid plans are refused before rendering.
- The job is marked done as soon as the chart is written. "Looks similar" suggestions (whole cleaned display incl. measure numbers and lyrics must match) and the outside-label check run afterwards with a time budget and can be cancelled; they never change the chart.
- Review wording: "looks similar" / "비슷해 보임", not "duplicate" or "repeat"; compare is the primary action.
- Section labels drawn outside the score region: an optional label area (suggested as an editable draft, applied only by the user). Label patches are the source image (never retyped), attached to their occurrence and placed above it where the label text changes (section start); repeats are kept on record. Without a label area, a detected outside label is reported as `LABELS_OUTSIDE_ROI`.
- The raw-stitch output is not selectable over the API; review-export of a pre-reflow job returns `LEGACY_JOB` and leaves its files as they are.
- An unsaved review order and selection are saved with the job id and revision and restored only onto that revision.

## Audit fixes in force (round 3, 2026-10-06)

- Hiding a short display needs every non-staff ink component of its sampled windows (any size, a 1-px dot included, after colored overlay columns are masked) to be drawn by one kept display around it. A tracker "small change" (page_diff `ambiguous`) is never sameness for hiding or for joining two displays. "Nothing beyond staff lines" means no non-staff ink component at all.
- A preview-tail cut is made in an empty column of the staff break, only toward the next included system, and only when every pixel it removes (the full strip height of the cut columns) is drawn at the destination and the destination's strip box holds that ink. The uncut strip is kept.
- Dependencies are re-validated on every compose (job and every review export): a cut tail goes back on its strip when its destination is no longer the next placed system; a section label goes above the first placed system of its section in the final order; a section with no placed system is reported (`labels_unplaced`, `SECTION_LABEL_NOT_PLACED`), never dropped silently.
- Several short transition displays are one collapsed "Transition fragments (N)" / "짧은 전환 화면 (N)" group in review; each keeps its own checkbox.
- The post-done steps (strip loading, "looks similar", frame decoding and samples of the outside-label check) check the cancel flag and the deadline between items. A step stopped by the budget publishes what it has, flagged in `suggestions_incomplete`; an outside-label check that did not finish stays `not_checked` with `check: "incomplete"`.

## Audit fixes in force (round 4, 2026-10-06)

- Content shown in only some observations of one display is never dropped silently. It may leave the composite only when it is explained as a playback overlay: colored ink, the playhead the observation's overlay detector found, page_diff's overlay mask of that member, or a cursor track (tall thin strokes at three or more positions). Every other ink component (as dark as the score's ink, not colored, at least 3 px and 2 px in each direction, not on video seen through a translucent band) shown by two or more consecutive observations is minority content (`minority_content.py`). Limits: a mark drawn over moving video behind a translucent band, or lighter than the score's ink, is not judged.
- A stable change (minority content from the display's first observation, or up to its last: notation added or removed) splits the display in the tracker (`content_step`); both states are separate displays in video order (a part shorter than a short display is listed unchecked like any short display).
- Content shown and then gone again keeps the majority composite. The system gets `MINORITY_CONTENT_DROPPED` (component boxes, times, observation ids) and one alternate strip per run of observations that shows it ("other moment", the overlay-free composite of that run, uncut). The alternate is listed unchecked right after its system and can be placed instead of it or with it; several alternates are one collapsed "Other moments (N)" / "다른 순간 (N)" group in review.
- A restored preview tail needs the uncut strip. When that file is missing, unreadable, of another size or of other pixels than recorded (`uncut_pixels_sha256`), it is rebuilt from the job's observations (stored frames, else decoded again from the source) and written only when its pixels match the recorded hash. Otherwise the composition stops: the job ends with `UNCUT_STRIP_UNAVAILABLE`, a review export answers 409 `UNCUT_STRIP_UNAVAILABLE` (KO/EN) and the previous export and result stay as they were. A cut strip is never placed when its destination is not the next placed system.

## Audit fixes in force (round 5, 2026-10-06)

- One written system is never placed twice. The parts of a display split at content steps share a family (`content_family` in tracking.json). One part is placed: the kept display that shows the most of the steps' ink (a mark added for good places the later state, one removed for good the earlier); a tie goes to the later state. Every other part is listed unchecked right after it as `sys-NNN-altK` (`MINORITY_ALTERNATE` + `CONTENT_STEP_STATE`, "another state of the line above"), in the "Other moments (N)" / "다른 순간 (N)" group, and can be placed instead of it or with it. Its preview tail is never cut. A family with no part long enough to place stays as listed short displays.
- A content step splits a display only when the new (or old) state lasts like a confirmed display: at least 3 observations over at least 0.5 s. A shorter run at a display's edge, where another display takes over (not the first or terminal display), is the hand-over (page curl, cross-fade): kept on record in the strip record (`minority_content.edge_transitions`), not flagged. Limit: a mark that appears only in the last half second before the next display, or only in the first half second of a display, is not flagged.
- A speck of minority content (at most a quarter of a staff gap squared, at most 0.75 gap wide and tall) at one screen position (within half a gap) in three or more displays belongs to the screen (video seen through a translucent band, a player UI), not to the score: no split, no flag, no alternate; kept on record (`screen_fixed_minority` in tracking.json, `minority_content.screen_fixed` per strip). Limit: a real speck-sized mark shown for a moment at one screen place in three displays is not flagged.
- Alternates are numbered per placed system: an alternate of a content-step state is another moment of the placed system.


## Boundary labelling rules (decided by Claude, 2026-10-06; the user may revisit)

These rules sharpen the packet instructions in `tools/reflow_boundary_review` for the independent-model labels of `freeze_v1`.

- **Lyrics:** a lyric word may be broken at a barline when no glyph, hyphen or extender touches the cut. The source's own barline already separates the syllables, and Korean lyrics are routinely broken at line ends.
- **Blank space:** a cut in blank leading space after a barline counts as next to that barline, at any distance. There must be only paper and staff lines between the barline and the cut. Any symbol between them, a whole rest or simile mark included, puts the cut inside the measure.
- **Barlines:** any barline pixel darker than the paper on the cut, anti-aliased edges included, makes the cut unsafe.
  - An ordinary barline and an end-repeat go with the left piece.
  - A start-repeat goes with the right piece.
- **Clef and signatures:** a cut that separates a clef or time signature from its first measure is unsafe.
- **Video behind the score:** imagery behind the score (photo, banner, background streak) is not score content and does not make a cut unsafe.

## Measure reflow milestone 2 defaults (decided by Claude, 2026-10-06; behind `JobOptions.measure_reflow`, off by default)

- **Classifier tuning (dev split only):** repeat dots are whole non-staff components (at most 0.7 gap) in both middle staff spaces, one above the other. A single such dot on the seam side is `POSSIBLE_REPEAT_DOT` (UNKNOWN). Ink cut off by the strip's top or bottom edge vetoes a seam within 1 gap when it is glyph-sized (at most 2 gaps wide), within 2 gaps otherwise. Repeat boundaries stay LOCKED.
- **Prefixes:** only a verified percussion clef is replicated at a new line start: exactly two isolated bars, nothing else starting in the clef zone, a clear run after it. Time signatures are never replicated. A source-system start keeps its own prefix and starts a line. A prefix-free system may join the previous line only when that line ends at a barline with no overhanging ink.
- **Justified edge:** the slots (inter-measure corridors, at most min(1.2 gap, half the corridor)) cannot carry the dev lines to the page margin: about 1.4% is available and 7–10% is needed. So the document gets one common right edge, the widest edge that the lines can reach. The edge is chosen among the page width and the widths that 4-measure lines can reach, at the lowest DP cost. The cost adds 20 × (1 − edge/page width)² per line, plus 5 when a full-length last line misses the edge. The block of lines is centred between the margins.
- **Overhang:** ink past the final barline (a "Fine" box) stays outside the justified width. The barlines align, and the overhang must still fit the page.
- **Fallback:** when no measure plan can be made (an unreadable record, a label collision, no feasible breaks), the whole systems are composed as before, and `plan.measure_reflow.status` is `fallback_whole_systems` with the reason.

## Joining systems (decided by the user, 2026-10-06)

- When a source system continues mid-line, its leading repeated drum clef may be removed.
- The removal must be clean: the clef must be an isolated patch, and after removal only paper and staff lines may remain. Otherwise there is no join and the line is kept as it is.
- Time signatures, tempo marks and section labels are never removed. A new line keeps its clef.
- **Four measures per line is a soft preference, not a target.** The aim is lines that fill the page width reasonably, with no forced 4-measure packing. In the user's words, no need to be obsessive about it.

## Joining systems: implementation defaults (decided by Claude, 2026-10-06; behind `JobOptions.measure_reflow`, off by default)

- **Clef removal** (`reflow_units.declef_patch`): only a verified clef-only patch (`clef_patch`). Refused when prefix ink starts within 2 gaps after the clef (a time signature, also when its digits merge through the middle line; a start repeat; any glyph-high ink wholly inside the staff), when the clef's 2-px fringe touches other ink, when the staff reference column next to the clef is not exactly five staff lines on paper, or when residue darker than paper remains. The clef and its fringe are replaced by that reference column. Every changed pixel lies in the clef mask; every changed non-staff pixel belongs to the clef. The resampled strip may differ only where the clef reaches. Each removal is listed in `audit.clef_removals` and as a `remove_clef` scaffold operation.
- **Joined measure start:** after the removed clef, lead columns that no ink reaches are dropped (leftmost first), so the gap from the previous barline to the first ink matches the strip's own median barline-to-ink gap (clamped to 0.8–2 gaps). The previous system's clear columns after its final barline are dropped too. That lead is a justification slot.
- **Frame edge:** a strip's first or last column that is a faint full-height line (the video frame edge, 8+ gray levels darker than paper outside ink) is set to paper on its unprotected pixels in measure mode, also in a clef replica. Otherwise it shows mid-line as a faint barline extension.
- **Line costs:** count penalty 4·(n−4)², or half that on the barline estimate when a count is unknown. Underfill 300·max(0, 0.85 − content/page width)², half for the last line. A non-final ragged line costs 3 + 100·(unreached/edge)². A line starting inside a source system costs 3; each joined system costs 1. A line never runs past the justified edge.
- **Justified edge:** one common edge, as before. It is chosen among the page width, a 1% grid from 75% of the page width up, and the widths reachable by preferred or well-filled lines. With the 8%/3% caps and uneven measure widths, many joined lines stay ragged; each is recorded. (Caps, ragged costs and the edge cost are superseded by "Spread justification" below.)

## Spread justification (requested by the user, 2026-10-06; behind `JobOptions.measure_reflow`, off by default)

- **Why:** the user disliked both ragged right edges and a few visibly wide gaps. This changes the brief's 8%/3% per-line default.
- **Where whitespace goes:** the extra width of a line is spread over many small insertions, proportionally to each gap's natural width, like proportional engraving spacing. Gaps are the barline corridors, the join leads and every eligible gap between note/rest columns inside the measures (`reflow_measure.spread_gaps`).
- **Eligible columns:** the ink of the column (output scale, darker than gray 200) is exactly the same on the 2 px to each side. So nothing starts, ends or changes thickness there: noteheads, stems, flags, dots, text glyphs, slurs and ties are never touched.
  - A column with non-staff ink is used only when that ink is a level beam (or bracket line) that continues unchanged on both sides until a stem-like vertical run (at least 1.5 staff gaps) crosses it, within 4 gaps. Each band of that ink is at most 0.9 gap thick and the crossing run is longer than the bands plus 1 gap, so a solid streak or smear is never extended.
  - Gaps narrower than 0.6 staff gap (counting the 2 px margins) are left alone: notehead to dot, grace notes, letter spacing.
  - No spread gap touches a unit's ends or lies in the first 6 gaps of a system start (its printed prefix).
  - Expansion repeats the gap's middle column; contraction removes columns of the gap's own eligible run. Each operation is in `audit.scaffold_operations` (`insert_spread_columns` / `remove_spread_columns`, rechecked `eligible`); each placement lists `inserted_offsets` and `removed_cols_out`, and `reconstruct_atom` removes the inserted columns to give back the resampled strip's columns.
- **Caps per gap (`reflow_lines`):** a gap grows by at most max(35% of its natural width, 0.6 staff gap). It keeps at least max(85% of its natural width, 0.5 staff gap).
- **Caps per line:** expansion at most 15% of the natural width (was 8%), contraction at most 5% (was 3%).
- **Line breaking (Knuth-Plass style):**
  - Each line costs 200 × (per-gap stretch ratio)², where the ratio is the line's delta over the natural width of the gaps that can take it. Minimising the sum balances the lines, so they need similar stretch.
  - The other terms stay: the mild 4-measure preference, the 85% fill reward and the split/join costs.
  - A non-final ragged line costs 60 + 300 × (unreached part / edge)², up from 3 + 100 ×.
  - At a section end the flat part is 15 instead of 60. A section end is a double barline or repeat, a labelled next section, or a next system that cannot join (its own prefix, e.g. a new time signature). The reason is recorded as `SECTION_END`.
  - The last line may stay short (`FINAL_LINE`).
- **Edge choice:** `EDGE_COST` is now 100 per line × (1 − edge/page width)², up from 2. The edge stays near the margin unless that forces many ragged or stretched lines.

## Fill every line (requested by the user, 2026-10-06; behind `JobOptions.measure_reflow`, off by default)

- **Why:** the user preferred spread justification (m5) and asked that every line reach the right edge. This rule replaces the short-line exemptions of "Spread justification": a section end, the last line and lines before a system that cannot join no longer get a cheap ragged line.
- **Section starts:** a section start does not force a line break. A joinable system continues mid-line and keeps its label above its first measure (as `Br` in the teacher PDF). Printed double barlines stay where they are. A system that cannot join still starts a line: its own time signature, or a clef that cannot be removed cleanly. The joined-system rule (clean clef removal) and SAFE-only splits are unchanged.
- **Order of remedies, per line:**
  1. **Break choice.** The balanced DP looks for breaks where every line reaches the edge within the normal caps: 35% / 0.6 staff gap per gap, 15% per line.
  2. **Wider caps, for that line only.** If the normal caps cannot reach the edge, one gap may grow by up to max(60% of its natural width, 1.0 staff gap) and the line by up to 25%. The growth is spread proportionally over all eligible gaps. Such a line costs 25 extra. It is recorded as `justify_tier: 2`, and each of its slots as `cap_tier: 2`. Contraction caps are unchanged.
  3. **Final-line rebalancing.** A very short last line cannot reach the edge within 25%, so the DP moves measures from the lines before it. It does this only at legal line starts: a SAFE cut with a verified clef replica, or a system start.
  4. **Recorded ragged line.** A line stays ragged only when no choice of breaks lets it reach the edge. It keeps its natural width and gets a reason:
     - `LOCKED_SPAN`: unsplittable content with too little whitespace (a locked group, a whole system, or one long measure such as a multi-measure rest).
     - `SEGMENT_TOO_SHORT`: everything between two forced breaks is shorter than one line can stretch.
     - `INSUFFICIENT_SLACK`: no break choice works.
     - The record also carries `final_line`, the segment and what forces the next break.
- **Costs:** a ragged line costs 5000, plus 1000 × (unfilled page line width / page line width)², plus 500 when it is not the last line. The final line and section ends get no discount. No glyph is stretched, no content is lost, and the ledger stays exact.
- **Edge choice:**
  - Ragged lines count in full, so the edge goes where the fewest lines stay short. Each line on the wider caps adds 100, so the edge is not widened by stretching every line.
  - The edge stays at or above 85% of the page line width. A narrower edge is used only when, at every wider edge, more than half the lines would be ragged. Example: every line is a whole system far narrower than the page.
  - One or two unsplittable lines never pull the whole block inward. Without this rule, Q8 went to a 67% block of 46 lines.
- **Line height:** each unit occupies only its own rows on a line: its ink and the staff, plus the strip's own paper padding above its highest ink and below its lowest. A measure without the system's tallest mark therefore does not make every line it shares that tall. Rows left off must hold no non-staff ink in the unit's columns, or the plan is refused (`ROW_CROP_WOULD_DROP_INK`). `rows_src_out` records them for the pixel ledger. Without this, filled 01Mr lines grew 73 px in total and the chart went from 1 to 2 pages.

## Measure reflow MVP (decided by the user, 2026-10-06)

- Ship measure reflow as an MVP and wire it into the app now. The user will use the app on real videos and find improvements from that; the full milestone 3 work (revisioned locks, undo, conflict UI) waits until then.
- **Defaults (Claude's choice):**
  - Measure reflow is ON by default for new jobs.
  - A visible toggle turns it off; off gives the whole-system layout.
  - Any planner failure falls back to whole systems and is recorded.

## Every line full (requested by the user, 2026-10-07; measure reflow, on by default)

- **Why:** on a real video (유우리 - 베텔기우스, lyrics under the staff, section boxes such as [C] above it) the PDF had six half-empty lines (45–59% of the width) between full ones, which the user found worse than either. "Clean" means the teacher PDF: every line runs to the right edge with no empty space, the last line included. The idea of falling back to the source layout for a local stretch was dropped (source lines are not full either). This replaces the ragged-line exemptions of "Fill every line".
- **Cause found on that video:** every source system is 2160 px at 1.5 mm, 1.6% wider than the 2126 px page line. Three systems (lyric-heavy, few eligible gaps) could not contract by 34 px within the 85% gap floor, so each was split into two short pieces. A fourth system (sys-017) could not join because the bottom edge of its [C] box dipped 1–3 px into the padded staff band over the clef (`CLEF_PATCH_CONTAMINATED`).
- **Order of remedies for a line that would be short:**
  1. **Joins**, with the clef rule below.
  2. **Rebalancing** with the neighbouring lines at SAFE cuts (4+2 → 3+3), the last line too.
  3. **Tighter gaps for a system slightly wider than the edge** (tier 2 contraction): a spread gap keeps at least max(60% of its natural width, 0.4 staff gap); barline corridors keep their clear-column limit; the line limit stays 5%. The source system then stays one line instead of two short pieces.
  4. **Tier-3 even spread** (last resort): every eligible gap of that line grows by the same fraction of its natural width, beyond the wider caps, at most 3× its natural width (`TIER3_MAX_GAP_RATIO`); no per-line limit; glyphs are never scaled; a join lead can only give back the columns it dropped. Recorded as `justify_tier: 3`, `cap_tier: 3`, and in `justification.lines_tier3_spread`. Costs 125 + the stretch term in the DP, so joins and rebalancing win whenever they work.
  5. **Recorded short line** only when even that cannot fill it (e.g. a single unsplittable unit far too short, such as Q8's opening multi-rest system). It keeps its natural width and its reason.
- **Clef next to text (user feedback 2026-10-07):** ink wholly above the top staff line or below the bottom one (a section box, "h.h open", a lyric) that stays at least 4 px clear of the clef's own pixels no longer blocks a clef replica or removal. It stays in place and moves with its measure; the replica leaves it out. Ink touching the clef, or anything inside the staff, still blocks. Only the clef's own pixels are removed; all pixel checks are unchanged. A box found this way is listed in `kept_outside_staff_boxes`.
- **Edge choice:** each line that needs the tier-3 spread at a candidate edge adds 2000, so the edge goes where the fewest lines need it. A narrower block is not chosen just to make one or two lines cheaper to stretch.
- **Audit:** `audit.join_refusals` lists every system that could not continue mid-line, with `system_id`, `reason` (e.g. `TIME_SIGNATURE`, `CLEF_PATCH_CONTAMINATED`, `PREVIOUS_SYSTEM_NOT_ENDING_AT_BARLINE`) and the offending component boxes when known. `justification.lines_below_98pct` and `min_fill` give the fill per document.

## Jump-view seam resolution (decided by Claude, 2026-10-07; the user may revisit)

- **Candidates:** an ambiguous seam (periodic content, `ambiguous_offset` its only failure) is resolved only from its plausible offsets. Plausible means every registration candidate, plus every local minimum in the typical-jump window, with residual ≤ 25 and enough overlap and ink.
- **Constraints**, each applied only where it can speak:
  1. A forward jump (≥ 15% of the content width).
  2. The slot's typical jump: the median of ≥ 5 verified jumps ± 3% of the display width, used only when their spread is small.
  3. The cursor prior, fitted at the mid-transition moment. Used only when it predicts the slot's verified jumps within 5% of the width (p90); tolerance 10%.
  4. Measure numbers over barlines (tesseract, when installed): B's numbers must land on the same numbers in A.
- **Resolved** only when exactly one offset passes every applicable constraint, at least one constraint besides "forward" applied, and B is not the slot's last display (that display may be clamped at the score end). A constraint that rejects every offset the others accept is a contradiction: the seam stays unverified.
- **Recorded:** every seam records the evidence used (`resolution.evidence`) and why it stayed unverified.
- **Sparse overlaps (reflow_jump-4, 2026-10-10, after the rc1 holdouts):** a seam whose registration failed only on `residual_high`, `ambiguous_offset` and/or `overlap_blank` may be resolved too (never `overlap_narrow`, `no_candidate` or a row change). Inside the typical-jump window, an offset with ink ≥ 1.5 staff spaces² (normally 4) is plausible when its residual is ≤ 25 and it is ≥ 4× better ((r₂ + 2) / (r + 2)) than every other minimum of the window. Such a seam, or such an offset, needs two constraints besides "forward": the typical jump plus an agreeing usable cursor prior or measure numbers. Recorded as `low_ink_window` in `resolution.evidence`. Target: overlaps of rest bars (RnY5 ep-0007→0008 printed bars 42–43 twice). Risk: a one-bar shift matches rest bars just as well and is excluded only by the window (± 3% of width; RnY5's wrong offset was exactly one bar, 73 px, outside it), so this path is safe only while the slot's typical jump is tight.
- **At an unverified seam:** both sides are kept, the strips next to it get `JUMP_SEAM_UNVERIFIED`, and nothing is merged.
- **Panorama:** every column comes from one display. A display's panel columns are used only where nothing else shows them. Long panoramas are cut just right of a barline, in a column clear over the full height.
- **Line starts:** the run's first verified clef is copied in front of later strips, and removed again when a strip continues mid-line. Without one, lines start bare.
- **Jump strips only:**
  - A measure number over a barline labels the measure to its right. The cut stays after the number (the number usually overlaps the barline's columns, so no straight cut separates them). When a line starts at that barline, the number moves to the start of that line, above the staff, at its own height or raised by up to 2 staff gaps to clear the first notes. Its old pixels become paper. Each move is recorded in `audit.moved_measure_numbers`, and so is the reason when a number stays (e.g. `NO_ROOM_AT_LINE_START`). (Corrected 2026-10-07: the earlier rule "goes with the left unit" left the number at the end of the previous line on qA-M_f0DMjw.)
  - ~~A span wider than the page line may be cut at a barline that only a line, slur or text crosses (`OVERSIZE_SPAN`, recorded).~~ Reverted in Step 2A: such a span is one oversize unit.
  - A single measure wider than the line gets its own line at a smaller scale (`oversize_units`, recorded).
  - Page strips keep the layout-conflict rule.

## Automatic staff size for dense charts (decided by the user, 2026-10-07)

- When measure layout cannot fill every line at the chosen staff size, typically with dense measures, the staff size may be reduced automatically, down to 1.2 mm and never below.
- **Choosing the size:** use the largest size, on a 0.05 mm grid, that fills every line. If no size fills every line, use the size with the fewest short lines, and the larger one on a tie.
- **Unchanged:** charts that already fill every line at the chosen size.
- **Trigger (Claude, 2026-10-07):** the search runs only for a dense chart, meaning at least 2 short lines and at least 5% of all lines short. A single unavoidable short line never shrinks the whole chart. Example: Q8's opening multi-measure rest keeps Q8 at 1.5 mm.
- **Recording:** the size actually used is recorded and shown.
- **Supersedes:** for measure-mode charts, this replaces the earlier rule "the staff size is never reduced automatically". The layout-conflict rule for whole-system mode still applies.
- **Implementation (Claude, 2026-10-07):**
  - A short line is a recorded short line (`ragged_exceptions`), whatever its reason. The chosen size counts as a candidate, so a smaller size is used only when it has strictly fewer short lines.
  - The search plans lines only (units and breaks, no rendering) at each size, largest first, and stops at the first size that fills every line. The chart is rendered once. Strip analyses are reused across sizes.
  - Recorded in `plan.staff_size` and `result.measure_reflow.staff_size`: `staff_gap_mm` (used), `staff_gap_mm_requested`, `auto_reduced`, `reason` (`DENSE_LINES_NOT_FULL`, `LINES_FULL`, `NO_SMALLER_SIZE_HELPS`, `AT_MINIMUM`, `AUTO_OFF`), and the sizes tried with their short-line counts.
  - The review screen shows "빽빽한 악보라 크기를 N mm로 줄였어요" / "Dense score: staff size reduced to N mm".
  - **Review export:** a size the user chose there (other than the job's size, e.g. "use 1.2 mm for this document") is used as it is, with no search, and is kept for later rebuilds (`reflow.staff_gap_mm_explicit`). Choosing the job's size again ("back to 1.5 mm") allows the search again. A document saved before this flag with a size other than the job's counts as an explicit choice.


## Step 2A safety and completion rules (2026-10-07, STRATEGY Step 2)

- **Cuts:** only SAFE boundaries are line breaks. `OVERSIZE_SPAN` is reverted; a LOCKED (except a verified preview tail) or UNKNOWN cut makes the document invalid (`reflow_units.validate_document`).
- **Size when nothing fits:** measure mode with no feasible line breaks at the requested size uses the largest feasible size on the 0.05 mm grid (`UNITS_DO_NOT_FIT`), then the usual dense search. Whole-system mode uses the largest size at which every system fits (`WHOLE_SYSTEMS_DO_NOT_FIT`). Floor 1.2 mm; below it the job ends as `LAYOUT_CONFLICT` (status error, review export still allowed to resolve it). A user-chosen size is never changed. Recorded in `plan.staff_size`.
- **Done means a real chart:** a job or review export is done only with a valid placement plan, at least one page, no empty page, and rendered/PDF page counts equal to the plan (`export.verify_composed_export`). Otherwise `INVALID_PLACEMENT_PLAN`, `EMPTY_EXPORT`, `PAGE_COUNT_MISMATCH` or `PDF_UNREADABLE`, and a review export keeps the previous files.
- **Source class:** `source_class.py` samples the ROI before analysis: opaque light paper, opaque dark paper (incl. a dark translucent plate), or notation composited over live video (refused, `UNSUPPORTED_SOURCE`, evidence in `result.source_class`). Fewer than 4 frames with staves → `unknown`, not refused. Thresholds were set on dev videos and the 12 transparent corpus videos only.
- **Size mode:** `JobOptions.staff_gap_mm_explicit` decides. When omitted, a size is explicit only if `staff_gap_mm` is sent and differs from the product default 1.5 mm (the desktop app sends no size, so automatic sizing stays on by default). An explicit size is never reduced; if it does not fit, the job ends as `LAYOUT_CONFLICT`. Rebuilds keep the mode.
- **Unresolved ranges on paper:** if the page-1 notice would exceed 3 lines, it becomes a summary ("N 구간… 전체 목록은 악보 끝에") and the full list is an appendix after the last line (it counts in the page plan; an appendix-only page is allowed only after the last score page).

## Step 2C rules (2026-10-08, after Pro checkpoint #2)

- **Written chart:** the output is the sequence of displayed written occurrences in video order. One display seen in several observations is placed once; a display that is left and shown again later is placed again. GT counts follow the same rule.
- **Translucent dark plates** (video visible through the paper) are not in the clean-complete class: the result is conditional and needs review until gray foreground there is preserved or resolved.
- **No silent erase of uncertain ink:** a thin or gray mark seen in only some observations is kept or listed for review; it is never paper-filled without evidence.
- **Source-cut content:** content cut by the video frame itself keeps its visible part and carries `SOURCE_CLIPPED` (local mark "† 원본 영상에서 잘림" + page-1 summary). It is source-limited, not a conversion loss.
- **Size mode:** the UI sends the mode with the size; an explicit 1.5 mm is locked like any other explicit size.
- **Line width:** no centring of a short block; the missing width is target − (right − left). Larger staff sizes up to 1.60 mm are searched as well as smaller ones. Final line: same rule as other lines.

## Step 2D rules (2026-10-08, after Pro checkpoint #3)

- **Short lines:** no fixed fee per short line; shortness cost φ(u) = 20u² + 200u⁴ of the missing staff width. Every line (final included) must be ≥ 85% of the staff target for an automatically usable layout; below that the result is a review draft. Reasons do not waive it.
- **Staff target and overhang:** staff spans 15–195 mm; identified external marks (measure numbers, brackets) may hang into 12–198 mm. The staff start sits at 15 mm. Clefs and notes stay inside the staff span. No empty staff lines are added.
- **Size floor:** 1.20 mm is absolute for primary content, also in fallbacks. No per-group size changes. 1.50–1.60 mm preferred; below 1.40 mm is declared compact.
- **Over-wide unsplittable groups:** review or refusal until a positively identified structural operation (first candidate: hairpin continuation) exists.
- **Cursor recovery:** underlay is recovered only from two agreeing unoccluded observations at different cursor positions with ≤ 0.5 native px residual registration; only the recovered part is discharged.
- **Translucent plates:** review-only.
- **Validation set:** monitored, not one-shot; the holdout is the one-shot test.

## Staged delivered verification (2026-10-09, after the Pro verifier checkpoint)

Context: the v2 raw-fringe projection verifier flagged ~18–20k entries per real dev video (S1, 01Mr); the user's 10-item spot check found nothing missing (mild softening only; memory "legibility-not-pixel-exact"). The v3 mark-level attempt reduced findings but let an erased staff-attached dot and tampered evidence pass. Pro reply: `PRO_CHECKPOINT_2D_VERIFIER.md` (prompt) — adopted with its additions.

- **Lossless PDF.** Pages are already 300 dpi (2480×3508) and near-gray (max chroma ≤ 11). One page image per PDF page, FlateDecode, 8-bit DeviceGray when the page's max chroma ≤ 24, else DeviceRGB. Measured: lossless gray is about half the size of the JPEG q92 pages (0.32–0.50 MB vs 0.72–1.05 MB). JPG files stay a user-selectable derived format; the PDF and PNG are the verified deliverables.
- **Staged verification replaces raw→PDF projection:** A (observations → strip, native), B (strip → layout plan, bookkeeping + independent plan validator), C (independent expected page render → staged PDF, lossless so near-exact). Plus integrity binding: evidence is fetched from or checked against the Hook-0 commitment; A/B/C results are bound to the strip, plan and staged-PDF digests; the installed artifact is the one checked.
- **Local obligations, not components.** Preservation is tested on overlapping 3×3 windows at fixed coordinates after one transform decision per line; no per-mark ±1 px search; no component-level coverage/IoU gate. Connected components are only for grouping findings.
- **Feature survival.** A qualified strip feature whose contribution disappears in the approved render (e.g. area shrink) is an output-fidelity review item, never "preserved because the output matches the expectation".
- **Weak features.** Strong seed contrast ≥ 64; credible isolated/persistent weak features 16–63 keep their own path (not fringe). Fringe attenuation is `RENDER_EQUIVALENT` only when explained by the approved transform and attached to a preserved feature.
- **Support states.** Each local feature: supports / uninformative / contradicts per observation; ≥ 2 distinct-visibility supporters qualify it; remaining observations are still scanned for novel or contradicting evidence.
- **Ownership vs. kernel vs. replica.** Kernel reads at boundaries are not duplicate content; replicas (clef, regenerated scaffold) need a declared role and an exact 2-D footprint; removal exceptions cover only the supported scaffold footprint, never a whole column.
- **Tolerances from fixtures, not videos.** ε_p for C = max benign residual on the frozen motif suite + 2, valid only if every declared destructive mutation stays detected; frozen before rerunning dev videos. Report: precision of blocking findings, mutation sensitivity, false-blocking rate per job.
- **Staff seams** are a separate presentation check (continuity metric), not a missing-notation code.
- **Budgets (targets, to validate):** A 60–90 s, B 1–3 s, C ≤ 2 s/page, total ≈ 120 s (investigate > 180 s), ≤ 512 MB extra; timeout → verification incomplete (never clean). Ledger metadata target 5–8 MB; evidence bytes reported separately; never drop evidence to meet a size target.
- **Where verification runs (user, 2026-10-09: jobs must stay fast on users' laptops).** Full A+B+C is the development/corpus gate run on every pipeline change. In the app, B + C (seconds) always run on the staged deliverable before install. A runs either only on regions the pipeline already marks as risky (overlay/cursor, minority content, low support), or after the files are shown, in the background, adding review items when done. The user never waits for full A. The job time target is ≤ 2–3 min for a 3-minute video on a typical laptop. Today 01Mr analysis alone takes ~7.5 min (cleaning ~4.5 min), so after 2D the pipeline itself needs a speed pass.
- **User-visible findings (2026-10-09).** "확인 항목" in the app lists only codes whose real-video findings were shown to be real defects: `DELIVERED_FEATURE_MISSING`, `PLACEMENT_MISMATCH`, `STAFF_SEAM`, `ARTIFACT_MISMATCH`, `EVIDENCE_INTEGRITY`, `VERIFICATION_UNASSESSED` (`reflow_pipeline.USER_VISIBLE_CODES`). A spot check of 18 S1/01Mr findings (3 per code) of `OUTPUT_FIDELITY`, `REMOVED_FEATURE`, `DUPLICATED_CONTENT`, `PLAN_INVALID` and `DELIVERED_EXTRA_INK` found no real defect. These five stay in `verify_dev_findings.json` and `ledger_summary.dev_issue_counts` for development. A code joins the visible set only after a spot check on real videos shows its findings are real.
