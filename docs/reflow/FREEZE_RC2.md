# Freeze record: checkpoint6-rc2

Written 2026-10-11 after the rc1 holdout fixes, the join check and the join rebuild. It was updated the same day after
Pro checkpoint #6 ([PRO_REPLY_RC2.md](PRO_REPLY_RC2.md)) and its five pre-freeze items. Same structure as
[FREEZE_RC1.md](FREEZE_RC1.md). The rubric additions and the fixed holdout protocol are at the end.

## Build

- Git: code = 06d15c0 "Refuse vertical-scroll videos and record the short plan" on `feature/clean-reflow` (the
  pre-freeze commit b44a0a2 plus the vertical-scroll refusal). Regression code manifest `47cc444f8c0439cb`
  (b44a0a2 was `38d4cb69597f1939`).
- 06d15c0 checks (2026-10-11): backend suite 1409 OK (12 skipped); regression `eval_v1/vscroll_refuse_dashboard`
  (17 videos) has every page pixel-identical to `prefreeze_dashboard`; `pack:release` plus both packaged smokes OK;
  the packaged app stops the Shorts probe `5pe5bLexYN4` with `UNSUPPORTED_LAYOUT` ("vertical_scroll 0.0-28.0s"), but only
  after 153 s, because the refusal comes after sampling and tracking.
- Packaged build: macOS arm64, `npm --prefix desktop run pack:release` from that working tree (unpacked app, 460 MB).
  Backend executable `drumsheet-backend` SHA-256 19f15af1c9a6e05a52696ae692e088aadeed9d996c8641b7999e61bb3d4efa70 (06d15c0).
  The b44a0a2 build was b2818271…; the first rc2 build (da3bdfa) was 7875e144…;
  bundled ffmpeg 8.1.2 (pinned media bundle `media-tools-850fac73bcaa288a6a92`, darwin-arm64 sha 486cbff7…).
  Test machine: 18 GiB, M-series, AC power.
- Runtime (source backend): Python 3.13.4, numpy 2.5.3, OpenCV 4.13.0; Electron 44.5.1; app 0.2.1.
  `backend/requirements.txt` sha256 prefix 7c9a959d294fab31, `desktop/package-lock.json` 7f1dfc9e13a7f5b4 (both unchanged since rc1).
- Windows and 8 GB machines: not qualified.

## Changes since rc1 (all after the rc1 holdouts were opened)

| Area | Change | Commit |
|---|---|---|
| Jump seams | `reflow_jump-4`: a seam whose overlap is sparse (rest bars, < 4 gap² ink) may be resolved; typical-jump window offers low-ink offsets (≥ 1.5 gap², residual ≤ 25, ≥ 4× better than any other window minimum) that need typical jump + cursor prior (or numbers). Fixes RnY5's doubled rests and Z4eb's doubled rests/short line. | 58f968e |
| Strips | Gray measure numbers crossing the strip's left/right edge widen the box (`edge_number_extent`). Fixes TeoV 17/29/33/47/51/63/67 and Fzc 81/13. | 58f968e |
| Strips | Overlay masks: pixels covered in every member are not counted unrecovered where members agree (10–90 % spread ≤ 30) and no solid tinted area survives an opening. 0MiL 20/20 → 0/20 flagged lines. | 58f968e |
| Review | Reasons ordered by notation impact (`JUMP_SEAM_UNVERIFIED` first; cosmetic/source notes last); job-level reasons too. | 58f968e |
| Review | Join check: one card per inferred/unverified jump seam with the printed line, an orange marker and a ±5 s source clip; answers "문제없어요" / "마디가 겹치거나 빠졌어요". | 0eedfa1 |
| Review | Join rebuild: a "bad" answer + "PDF 다시 만들기" re-cuts that run with the seam treated as unverified (both views kept, overlap trimmed only by the saved panel edge). Frames are recovered from the source by one batch decode. New revision directory; the previous files stay on any failure; refusals SEAM_REPAIR_SOURCE_UNAVAILABLE / _SELECTION / _INCOMPATIBLE, STALE_REVISION, SEAM_UNKNOWN. | 6e0c110, da3bdfa |
| Review | "전체 포함" ticks only main lines (other moments, short displays and exclusion candidates keep their tick); focus and locale fixes; preview URLs carry the revision. | 6e0c110 |
| Release | Packaged runtime smoke runs a real clean-reflow capture (12 s, 3 pages, 6 systems). | 812d9b2 |
| Lines | Pre-freeze (Pro #6 item 1): a line whose overhang ink (a "Fine" box) would cross the page margin at the chosen edge is not justified there (ragged `OVERHANG_AT_MARGIN`). `reflow_lines-5`, `reflow_measure-3`. TeoV now gets measure reflow: 3 pages, 28 lines, 1.45 mm. It was a whole-systems fallback (`MEASURE_PLAN_ERROR`, LayoutConflictError line-013) in rc1 and in the first rc2 record. | (pre-freeze) |
| Jump seams | Pre-freeze (item 4a), `reflow_jump-5`: a low-ink offset must also beat every other forward offset with overlap by 4×, over the whole feasible range and at ± one or two local bar widths. Otherwise the seam stays unverified (`low_ink_rival`); agreeing measure numbers bypass the check. Cost: RnY5 ep-0007→0008 is unverified again, so rest bars 42–43 print twice and the PDF marks them. Z4eb 0016→0017 still resolves. | (pre-freeze) |
| Strips | Pre-freeze (item 4b): a steady pixel covered in every member is exempt only when it looks like the strip's own print: near-paper (chroma ≤ 48), neutral ink, or a 0.08-gap fringe of it. A static gray bar or a thin colored cursor over notes keeps `OVERLAY_UNRECOVERED`; 0MiL stays at 0. | (pre-freeze) |
| PDF | Pre-freeze (item 2): every join where both views are kept (unverified, or rejected by the user) gets a ⇄ mark in the margin beside both lines and a note at the bottom of the page: "앱이 화면 연결을 확정하지 못해 앞뒤 화면을 모두 담았습니다. 표시된 곳에서 마디가 겹칠 수 있습니다." The source-clipping header has no line count. | (pre-freeze) |
| Review | Pre-freeze (item 2): the join check adds a "판단하기 어려워요" answer, which leaves the place unchecked with a note. A rebuilt join is tagged "연결 미확정 · 양쪽 화면 보존" in warning color, not green. | (pre-freeze) |

Version strings not bumped for the strip changes (`reflow_strips-1` is informational only; no cache keys use it).

## Rules and defaults in force

As in FREEZE_RC1 "Rules and defaults in force", except: jump `reflow_jump-4` (sparse overlaps), jump preservation
`jump_preservation-6`, coverage `jump_coverage-5`, review reason order by impact, join check on, join rebuild on.
Unchanged: `reflow_boundaries-5`, `reflow_measure-2`, `reflow_occurrences-2`, replay = candidates only, dark background off,
preview-tail speck rule, strip threads min(4, cpu−1, (RAM_GiB−4)//3), dev ledger off, staff size auto 1.5 mm floor 1.2 mm.

## Checks at freeze

- Pre-freeze build:
  - Backend suite 1409 OK (12 skipped); renderer verify 355 OK; desktop node 94 OK; packaged runtime and Electron smokes pass.
  - Regression `eval_v1/prefreeze_dashboard` (17 videos, manifest `38d4cb69597f1939`) against `rc2check_dashboard`:
    12 videos pixel-identical. Three differ as intended: TeoV (measure reflow), RnY5 (the 0007→0008 join is kept as both
    views, with ⇄ marks and the note), and aOED (header wording only). GTOc and 4M0X are refused.
  - Packaged backend, RnY5 (`eval_v1/seamcheck_prefreeze`): first export marks the unverified join. Rejecting
    0013→0014 rebuilds revision 2 in 66 s with both joins marked, and a cancelled second rebuild keeps revision 2 and the
    PDF. Peak RSS 2.5 GB.
  - The packaged renderer files for the join check (ReviewScreen, reviewController, i18n, CSS) are byte-identical to the
    source. The "hard to tell" button was not clicked in the packaged GUI.
- First rc2 record (da3bdfa): backend 1394 OK; renderer verify 355 OK; desktop node 94 OK; packaged smokes pass.
- Regression `eval_v1/rc2check_dashboard` (17 videos, one code manifest `fc3b09bb8779f0f3`): 11 dev + Z4eb + RnY5
  pixel-identical to the post-fix baselines (rc1fix / seamfix); 0MiL, Dr5j: title glyphs only; TeoV: measure numbers whole;
  4M0X refused in 9 s.
- Join rebuild: J (dev Electron), RnY5 via API (source and packaged backend) and in the packaged GUI: revision +1 in 61–68 s,
  coverage complete, "양쪽 모두 남김", overlap measures printed twice, nothing lost.
- Packaged GUI (scratch profile + jobs dir, driven over CDP): RnY5 job 1 min 47 s; .mkv clip plays; untick → rebuild 13 s;
  cancel keeps selection and previous PDF. Packaged backend peak RSS 2.1 GB (RnY5).
- Not checked: Windows, the dmg installer, 8 GB machines, a second person grading.

## Baseline grades at freeze (first export, FREEZE_RC1 rubric; all 17 are opened, none is fresh)

| Video | Grade | Notes |
|---|---|---|
| S1 | Clean | |
| 01Mr | Clean | |
| Q8 | Clean | simile lines kept (correct) |
| w7mK | Clean | |
| Fzc | Clean (was usable) | 81 and 13 now whole |
| 0MiL | Clean | holdout rc1; no measure numbers; lyrics run on across joins |
| Dr5j | Clean | holdout rc1; 1–139 continuous |
| TeoV | Clean (was usable) | holdout rc1; clipped gray numbers fixed. The rc2 export was a **whole-systems fallback** (`MEASURE_PLAN_ERROR`), Clean as a fallback, not a measure-reflow success. Measure reflow works after the pre-freeze fix. |
| aOED | **Unusable** (first export; Pro #6) | D.S. al Coda and the replayed section printed, so the reader must skip music (8 lines `REPLAY_CANDIDATE`). Assisted untick → 2 pages, Usable. Lyric bottoms clipped in the source. |
| bF69 | Usable with flaws | gray footage smear above lines (cleanup off); blob under "Bridge 1" |
| _7gP | Usable with flaws | dense, ragged lines; two forced breaks at 1.3 mm |
| SZwT | Usable with flaws | blue player icons touch beams |
| SHvfn | Usable with flaws | gray return icons touch beams |
| Z4eb | Usable with flaws, source limitation | faded "#75 + track name" label, ghost clef; bass beams clipped by the video frame; short line and doubled rests fixed |
| RnY5 | **Not usable, conservative** (Pro #6 rule) | holdout rc1; doubled rests fixed; full read 2026-10-11: every bar present once and in order. Bass tuplet numerals are clipped by the video frame itself; on the page-2 grooves 3 vs 5 cannot be told from the PDF alone. Tempo mark clipped; "†" note under the clipped lines. |
| GTOc | Unsupported | refused in 7 s |
| 4M0X | Unsupported | holdout rc1; refused in 9 s |

m_YP (holdout rc1) has no score in the video and is dropped from the set.
Tally 17 (after Pro #6): clean 8, usable with flaws 5, unusable 2 (aOED first export, RnY5), unsupported 2 → usable 13/17.
Was 15/17 before Pro #6. Single reviewer (the lead), not blind.

## Known flaws carried into the next holdouts

- A join kept as both views (unverified, or rejected by the user) prints the overlap twice by design; the PDF marks it with ⇄
  and a note. A faint panel-label fragment ("#42 鼓组") can remain at the line start after it (RnY5).
- Sparse-overlap seams resolve only when no other forward offset, including one or two bars off, matches comparably
  (`reflow_jump-5`). RnY5 0007→0008 is correct by eye but now stays unverified.
- Join check covers inferred/unverified seams only (RnY5: 3 of 21); a wrong "verified" seam is not shown to the user.
- The join clip box is black until played.
- Source-clipping disclosure prints a "†" note under every affected line, which costs vertical space; the header has no count.
- A layout conflict at render time still falls back to whole systems without trying a smaller staff size.
- A static solid gray icon over notes is not in the overlay mask at all, so it gets no warning (Pro #6 item 4b case, same
  before and after 58f968e). Static dark-gray marks count as ink and very pale pastel lines as paper.
- Replay candidates are not auto-excluded; dark-theme footage smear is not cleaned; player icons over notation are kept.

## Next holdout protocol (fixed after Pro checkpoint #6, see [PRO_REPLY_RC2.md](PRO_REPLY_RC2.md))

1. **Scope, declared before selection.** Supported: page-turn views, jump views, and the scroll kinds this build supports
   No scroll kinds: continuous horizontal scroll (`UNSUPPORTED_HORIZONTAL_SCROLL`) and, from 2026-10-11, vertical scroll
   (`UNSUPPORTED_VERTICAL_SCROLL`, user decision after the `5pe5bLexYN4` probe) are refused. The 2 scroll slots in item 2
   become page-turn / jump slots, and a vertical-scroll Shorts joins the refusal tests (see HANDOFF short plan).
   Mac arm64 only, packaged app.
2. **Set: 8 supported + 2 refusal tests, kept apart.** Supported: 3 page-turn, 2 scroll, 3 jump; at most 2 per channel,
   at least 4 channels, at least one channel or display style not in the dev set. Refusal tests: 1 live-overlay video,
   1 video without a score.
3. **Selection.** Write the channel candidate lists first. Shuffle each list with a recorded seed. For each candidate look
   at 15 s at 10 %, 50 % and 90 % only, and record score present / plate / motion kind / mixed display. Take candidates in
   order until the quotas are met. Never exclude a supported video for gray numbers, lyrics, density, a cursor, clipping or a
   messy background. Hash the list and seal it. Anything found after sealing stays in the denominator.
4. **Run.** Packaged app of this build, normal setup (auto ROI suggestion, auto label region), one run per video. Keep the
   first PDF and the diagnostics read-only.
5. **Grading: single grader, two passes** (procedure in PRO_REPLY_RC2 "Grading procedure").
   - Pass 1 as a user, in random chart order: provisional grade and worst page/line. Then the assistance budget: at most
     5 min active, at most 1 rebuild (join check, unticks). The assisted grade is recorded separately.
   - Pass 2 after a break: walk the source timeline and check every seam, verified ones included.
   - A loss found later lowers the final grade. Unaudited parts are reported as "not audited".
6. **Rubric** (FREEZE_RC1 grades, with these rules):
   - A chart with a known repeated or skipped passage the reader must work around is **Unusable**. This includes a printed
     D.S. replay and a kept-both-views join, even if the user accepts it.
   - A detail clipped in the source counts only if it is still unambiguous from the PDF alone.
   - A clean whole-systems fallback may be graded Clean, but it is reported as a fallback, not as a measure-reflow success.
7. **Record per video:**
   - The FREEZE_RC1 fields.
   - Seams by status.
   - Join cards shown, review time, clip replays, "hard to tell" answers.
   - Wrong joins found on cards, defects at unshown verified seams, duplicates or losses left after a repair.
8. **Ship bar (8 supported):**
   - Usable ≥ 7/8 and clean ≥ 6/8.
   - Unusable + failed + refused + unresolved fidelity ≤ 1.
   - Observed silent fidelity defects = 0.
   - Refusal tests 2/2.
   - Packaged create/review/save/cancel/restore works on the stated Mac.
   - Supported and refusal results are reported separately, never as "9 of 10".
