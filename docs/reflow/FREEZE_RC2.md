# Freeze record: checkpoint6-rc2

Written 2026-10-11 after the rc1 holdout fixes, the join check and the join rebuild. Same structure as
[FREEZE_RC1.md](FREEZE_RC1.md); the rubric and the change rules are carried over unchanged. The holdout protocol below is
a draft until the Pro checkpoint ([PRO_CHECKPOINT_RC2.md](PRO_CHECKPOINT_RC2.md)) is answered; fix it before the run.

## Build

- Git: code = da3bdfa (branch `feature/clean-reflow`); 812d9b2 only changes the packaged smoke script and docs; the freeze
  commit adds this file and the Pro prompt.
- Packaged build: macOS arm64, `npm --prefix desktop run pack:release` from da3bdfa (unpacked app, signatures verified,
  457.1 MiB). Backend executable `drumsheet-backend` SHA-256 7875e1443aa4e6ce5d001828d3dbd3278e16ee6c00d2ec0b8ef30dbf0572533f;
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

Version strings not bumped for the strip changes (`reflow_strips-1` is informational only; no cache keys use it).

## Rules and defaults in force

As in FREEZE_RC1 "Rules and defaults in force", except: jump `reflow_jump-4` (sparse overlaps), jump preservation
`jump_preservation-6`, coverage `jump_coverage-5`, review reason order by impact, join check on, join rebuild on.
Unchanged: `reflow_boundaries-5`, `reflow_measure-2`, `reflow_occurrences-2`, replay = candidates only, dark background off,
preview-tail speck rule, strip threads min(4, cpu−1, (RAM_GiB−4)//3), dev ledger off, staff size auto 1.5 mm floor 1.2 mm.

## Checks at freeze

- Backend suite 1394 OK (12 skipped); renderer verify 355 OK; desktop node 94 OK; packaged smokes pass.
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
| TeoV | Clean (was usable) | holdout rc1; clipped gray numbers fixed; light last page |
| aOED | Usable with flaws, source limitation | D.S. replay printed (8 lines `REPLAY_CANDIDATE`; assisted untick → 2 pages); lyric bottoms clipped in source |
| bF69 | Usable with flaws | gray footage smear above lines (cleanup off); blob under "Bridge 1" |
| _7gP | Usable with flaws | dense, ragged lines; two forced breaks at 1.3 mm |
| SZwT | Usable with flaws | blue player icons touch beams |
| SHvfn | Usable with flaws | gray return icons touch beams |
| Z4eb | Usable with flaws, source limitation | faded "#75 + track name" label, ghost clef; bass beams clipped by the video frame; short line and doubled rests fixed |
| RnY5 | Usable with flaws, source limitation (was unusable) | holdout rc1; doubled rests fixed; tempo mark and bass tuplets clipped by the frame; "† 원본 영상에서 잘림" under every one of 17 lines |
| GTOc | Unsupported | refused in 7 s |
| 4M0X | Unsupported | holdout rc1; refused in 9 s |

m_YP (holdout rc1) has no score in the video and is dropped from the set.
Tally 17: clean 8, usable with flaws 7, unusable 0, unsupported 2 → usable 15/17. Single reviewer (the lead), not blind.

## Known flaws carried into the next holdouts

- A user-rejected join prints the overlap twice by design (both views kept); a faint panel-label fragment ("鼓") can remain at
  the repaired line start.
- The sparse-overlap seam rule excludes a one-bar shift only by the ±3 % typical-jump window.
- Join check covers inferred/unverified seams only (RnY5: 3 of 21); a wrong "verified" seam is not shown to the user.
- The join clip box is black until played.
- Source-clipping disclosure prints a "†" note under every affected line (RnY5: all 17), which costs vertical space.
- Replay candidates are not auto-excluded; dark-theme footage smear is not cleaned; player icons over notation are kept.

## Next holdout protocol (draft, pending the Pro reply)

1. New sealed set, chosen before any run: for each candidate video look at one mid-video frame only to confirm a plate
   score is shown (reject live-overlay and no-score videos before sealing); balance channels (≤ 2 per channel); include
   page views, scroll and jump views. Size and composition per the Pro answer.
2. Packaged app (this build), normal setup (auto ROI suggestion, auto label region), one run per video; first export kept.
3. Grade the first export with the FREEZE_RC1 rubric; record the per-video fields of FREEZE_RC1 "Holdout protocol" 4 and
   the join-check items shown (count, which); an assisted grade (unticks, join rejections) is recorded separately.
4. Fidelity audit as FREEZE_RC1 step 5, plus every join the app inferred.
5. Ship bar: as FREEZE_RC1 (≥ 5/6 usable, ≥ 4/6 clean, zero silent fidelity defects, ≤ 1 honest failure), scaled to the set
   size, unless the Pro reply changes it.
