# Audit for Step 2B: occurrence identity and primary/preview roles (2026-10-07)

Read-only audit (worker W5) of validation videos SZwTzT3co_M and Fzc0z6xhJOw, current working tree. Analysis outputs and evidence crops e01–e10 were in the session scratchpad (`scratchpad/w5/`), not kept in the repo. Line numbers are from the tree at audit time; recheck before patching.

## 1. SZwT 26 → 26 → 30: one written system placed twice

- The line m.26–29 is on screen once, 55.7–62.2 s. No repeat signs, nothing in between, the playhead moves forward across the split (0.076→0.634 in ep-0007, 0.674→0.937 in ep-0008). Between 60.0 and 60.5 s the only pixel difference is the moving cursor.
- Output: sys-008 (55.767–60.0 s) and sys-009 (60.5–62.133 s), differing only in the frozen cursor. The baseline flagged the pair as a non-blocking `duplicate_suggestions` entry.
- **Same cause, worse effect: line m.54–55 is missing.** On screen 101.1–104.3 s, split into ep-0017/18/19 (1.13, 1.37, 0.27 s); each is under `MIN_OCCURRENCE_SEC = 1.5`, so all were excluded. A count check cannot see either error: +1 duplicate and −1 lost cancel.

## 2. Root cause

1. `page_diff._remove_staff_lines` (page_diff.py ~445–466) removes a row only when its ink density ≥ max(0.2, P97·0.45). The top staff line (0.30–0.335 vs threshold 0.337) survives as short dashes whose ends move with small gray drift. That gives 3–4 thin "minor" change boxes on the staff row → ≥ 3 minor blobs → `different / many_small_changes` (page_diff.py ~130, 306–309).
2. `system_tracking` maps "different" to "changed" (~131–156) and compares each frame with the episode's first observation (~332), so drift accumulates over a 4–6 s display and closes the episode as `content_change` (~343–356). Every false split in SZwT has this signature; one pair is pixel-identical.
3. `build_occurrences` (reflow_occurrences.py ~300–361) never rejoins them in a single-slot bottom bar (`steady` is empty). Then `duration ≥ 1.5 s and n_obs ≥ 3` (~385) places both long parts and drops short parts.

Not the cause: the Next inset (no inset notation enters the ROI), the cursor (masked), a revisit.

Fzc0 has the same false-split mechanism but only cuts 0.1–0.4 s tails, so no visible duplicate or loss. Dev GT videos (01Mr, Q8, S1nl, aOED, bF69) are 1:1 in the baseline; the tracker was not rerun there.

GT "revisit" = the same location shown again after other locations or a whole-view jump (e.g. aOED after D.S. al Coda). SZwT's pair is not one.

## 3. Proposed general fix (occurrence identity)

Principle: a display ends only on evidence of leaving the written line; a revisit needs evidence of leaving and coming back.

- **A. Comparison:** staff-line rendering drift is never content. Drop thin change components (height ≤ ~0.25 gap) within ±1 px of a staff row (use the tracker's `staff_y`, or detect the five lines per band instead of a global P97 threshold). Count a minor blob only when present in one state and absent in the other after dilation.
- **B. Occurrence-level join (safety net):** join consecutive same-slot episodes when the boundary is `content_change`, the gap ≤ one sample interval + 0.5 s, no view transition or playhead reset, the playhead continues (`b.x_first ≥ a.x_last − 0.05`), and `_same_whole_display` (reflow_occurrences.py ~586) passes with staff rows masked. If notation really differs, make them a content family (one placed, others alternates). Join before the 1.5 s cut. Without playhead readings, join only on pixel sameness including measure numbers and record `joined_without_motion_evidence`.
- **C. GT-free self-checks:** `adjacent_duplicate` (should be 0), `score_time_uncovered` seconds (SZwT baseline: 101.1–104.3 s), a separate revisit count.
- Acceptance: obs-270/286 and obs-464/474 become `same`; ep-0025|0026 stays `changed`; Q8 identical rows across page curls still split. Compare per-slot matches, not totals.
- Risks: consecutive identical lines without measure numbers; a real small mark on a staff line hidden by the looser diff.

## 4. Primary vs preview roles

- The Next inset is fixed at x ≈ 1356–1919; its pink frame (y ≈ 786–811) enters the ROI (SZwT crop rows 0–13, Fzc0 rows 0–41). **No preview notation enters the ROI** (0 dark ink in the inset columns during score intervals).
- `_overlay_columns` (overlay_composite.py ~20–28) masks whole columns, so x 1356–1919 is masked in every member; with all members covered the strip keeps the reference pixels (reflow_strips.py ~384–391): 529–535 unrecovered columns on all 37 SZwT strips, 487–552 on Fzc0.
  - The pink band stays in every strip.
  - The blue cursor is frozen in those columns (all 559 cursor-blue columns are at x ≥ 1356).
  - **Gray block:** the pixel reference is the member with the fewest masked columns (reflow_strips.py ~355); for SZwT sys-001 that is a fade-in frame at 14.267 s (mean gray 102 vs 220). Same in Fzc0 sys-001 (9.13 s).
  - Audit note: `reference_obs_id` is the geometry member (reflow_strips.py ~818), not the pixel reference (`reference_index`).
- Cursor: translucent box ≈ 3 gaps wide stepping with the beat; each column is clean in most of a display's 20–35 members.
- Magenta band: static, no clean observation underneath. SZwT notation tops at rows 15–18 (band 0–13, no overlap); Fzc0 band reaches row 41 and sys-001's notation top is row 35 (possible overlap).
- Static blue "page" icon at each line end (x ≈ 1820–1845): also an overlay column; role undecided.

## 5. Proposed general recovery

1. Region roles per job: an area whose pixels stay identical across displays with different notation is screen-fixed (extend `screen_fixed_spots` to areas): frame/band, preview interior, or moving overlay. Frame and preview pixels never enter the primary representation.
2. 2-D masks instead of whole columns: band rows (dilated 2 px) and the cursor box; cursor pixels from the median of members where the cursor is elsewhere.
3. Trim or paper-fill the band only where no notation component touches it in any member; otherwise review-required (`OVERLAY_COVERS_NOTATION`). Never erase.
4. Exclude fade/transition frames (paper ≥ ~10 levels below the display median) from the reference and the median.
5. Acceptance: band-related unrecovered columns 0, cursor-blue columns 0, no gray block, pixels under the former mask equal to the members' median; ≤ 10 crops for the user's yes/no.

Risks: tinted fringes at mask edges; median needs < 0.5 px alignment and enough clean members; the screen-fixed detector could take a static score element for chrome (keep dark ink); Fzc0 band overlap needs the touch test.

## User spot check (2026-10-07)

Three before/after crops (SZwT sys-001 gray block, SZwT sys-022 cursor, Fzc0 sys-001 gray block): the user confirmed the gray block, pink band and cursor are gone and the notation is intact. Known leftovers not covered by the check: a dark gray vertical bar at the strip's right edge, and faint dotted remains of the blue "page" editor icon (Step 3 marker cleanup).
