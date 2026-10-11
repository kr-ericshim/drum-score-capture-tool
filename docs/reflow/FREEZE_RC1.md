> **rc2로 대체됨.** 현재 빌드는 [FREEZE_RC2.md](FREEZE_RC2.md)다. FREEZE_RC2가 이 파일의 "Rules and defaults in force"와 "Grading" 절을 참조하므로 그 두 절만 유효하다. 나머지는 기록이다.

# Freeze record: checkpoint5-rc1

Written 2026-10-10 after Pro checkpoint #5 (STRATEGY.md "Step 2D checkpoint #5"). This file fixes what the
holdout run tests, how it is graded, and what may change afterwards. Fill the open fields before the run.

## Build

- Git commit: the commit that adds this file (branch `feature/clean-reflow`); working tree clean.
- Packaged build: macOS arm64, `npm --prefix desktop run pack` (unpacked app, signature verified, 457.7 MiB) from commit 8a1125f.
  Backend executable `drumsheet-backend` SHA-256 38fa792c66ff1e9eaf718a530be0b233be6404685161fbafd4eb2b343c6a2457;
  bundled ffmpeg 8.1.2. Test machine: 18 GiB, M-series, AC power (4 strip threads).
- Windows and 8 GB machines: not qualified for this pilot.
- Runtime (source backend): Python 3.13.4, numpy 2.5.3, OpenCV 4.13.0, system ffmpeg 7.1.1 (the packaged app bundles its own
  ffmpeg; record its version from the build), Electron 44.5.1, app 0.2.1.
  `backend/requirements.txt` sha256 prefix 7c9a959d294fab31, `desktop/package-lock.json` 7f1dfc9e13a7f5b4.

## Packaged checks (2026-10-10, packaged backend over HTTP, the app's own entry point)

- 01Mr: done in 161 s (source backend 169 s), peak RSS 3.4 GB; music pixels identical to the source run (title
  antialiasing differs). aOED: done in 88 s, 3 pages, 8 `REPLAY_CANDIDATE` systems, the candidate reason is the first
  shown; recompose without them → 2 pages + PDF. Cancel during 01Mr: cancelled in 2.0 s, no PDF.
- Not checked: the GUI itself on this build (the renderer suite is unchanged this round), Windows, 8 GB machines.
  `smoke:packaged-runtime` fails on its 2-s synthetic clip (`NO_SCORE_SYSTEMS`: too short for the current
  pipeline); the real-video runs above replace it for this freeze.

## Rules and defaults in force

| Rule | Version / setting |
|---|---|
| Boundaries | `reflow_boundaries-5` (frame-edge veto waived only with verified `frame_edges`) |
| Measure layout | `reflow_measure-2` (staff floor 1.2 mm; forced break only at barlines crossed by a thin stroke with positive geometry; else `LINE_BELOW_MIN_SIZE`) |
| Occurrences | `reflow_occurrences-2` (false-split joins need whole-span identity; a failed check binds later rules) |
| Replay | candidates only (`REPLAY_CANDIDATE`, first reason in review); `REFLOW_REPLAY_AUTO_EXCLUDE` unset |
| Dark background | off (`REFLOW_DARK_BG_CLEANUP` unset) |
| Preview-tail specks | components ≤ max(2 px, 0.012·gap²) do not block a verified cut |
| Strip threads | unknown RAM → 1; else min(4, cpu−1, (RAM_GiB−4)//3); `REFLOW_STRIP_THREADS` unset |
| Dev ledger | off (`REFLOW_DEV_LEDGER` unset) |
| Review panel | `APP_REVIEW_CODES` empty; per-system reasons shown (first match) |
| Staff size | automatic, requested 1.5 mm, never below 1.2 mm |

## Grading (one rubric, applied to the first export)

| Class | Definition |
|---|---|
| Clean | Readable at A4; every line ≥ 1.2 mm staff gap; notation, labels and available lyrics clear; no extra musical fragment, no damaging clipping, no overlay touching notation. Small isolated remnants in whitespace, short lines and a light last page are allowed. |
| Usable with flaws | The drummer can read and follow the chart without reconstructing or skipping musical events. Uneven widths, background remnants, non-obscuring overlay marks, disclosed source clipping allowed. |
| Unusable | Missing, duplicated or reordered music; a fragment the reader must know to skip; a line below the floor; ambiguity that needs guessing. |
| Unsupported | The source belongs to a class excluded before testing (live notation drawn over video with no plate) and the app refuses it with the right reason. Counts in the denominator. |

Separate verdicts per video: **fidelity** (not audited / no loss observed in the audit / unresolved / defect),
**source limitation** (none / clipped / obscured), **job outcome** (completed / review required / refused / failed).
The first-export grade is primary; an assisted grade (e.g. after unticking replay candidates) is recorded separately.

## Holdout protocol

1. Holdouts: 0MiL, 4M0X, Dr5j, TeoV, m_YP, RnY5 (sealed; chosen from metadata only).
2. Packaged app, normal setup (auto ROI suggestion, then the user's normal ROI/label choice), one run per video.
3. Keep the first export and its diagnostics unchanged; grade before any assisted change.
4. Per video record: identity (video hash, duration, resolution, codec, build hash, RAM, workers), setup (ROI, label
   region, manual choices), outcome and status text, pages, grade with the worst page/line, fidelity audit, stage times,
   peak memory, review items (count, which, decisions), incomplete intervals, replay candidates, forced breaks, assistance.
5. Fidelity audit (≈ 30–45 min per video): walk the source timeline and give every newly shown system a destination in
   the PDF (or a stated reason: replay candidate, unsupported interval); check measure numbers where printed; inspect
   every transformation that can drop or move content (replay candidates, preview-tail cuts, minority alternates, forced
   breaks, frame-edge waivers). No new verifier.
6. Grade in random chart order with file names hidden where practical; second pass against the source after a break.

**Ship to a few users** when: ≥ 5/6 usable, ≥ 4/6 clean, zero observed silent fidelity defects, ≤ 1 honestly reported
failure (a refusal counts), packaged workflow, cancel and memory acceptable on the qualified Mac. Otherwise another round.

## After the holdouts are opened

| Change | Treatment |
|---|---|
| Report typo / transcription fix | Allowed, original kept |
| Crash or packaging fix | New candidate; the frozen run's failure stays recorded |
| Any threshold, default, sampling, seam, layout or cleaning change | New candidate and a new evaluation; opened holdouts are no longer fresh |
| New "unsupported" category | Cannot excuse a holdout failure retroactively |

## Non-holdout baseline at freeze (first export, Pro rubric)

Dashboards `eval_v1/step2d2_dashboard` (8 unchanged videos) and `eval_v1/step2d3_dashboard` (aOED, bF69, _7gP, Fzc on
commit 71e36fb; the freeze commit only adds version strings and this file).

| Video | Grade | Notes |
|---|---|---|
| S1 | Clean | |
| 01Mr | Clean | |
| Q8 | Clean | simile lines kept (correct) |
| w7mK | Clean | |
| Fzc | Usable with flaws | 77–80 restored (was a silent loss); measure number 81 half clipped by the strip box (gray number not counted as envelope ink) |
| aOED | Usable with flaws, source limitation | D.S. replay printed again (8 lines flagged `REPLAY_CANDIDATE`; assisted: untick → 2 pages); lyric bottoms clipped in source |
| bF69 | Usable with flaws | bar 42 duplicate fixed; gray footage smear above lines (cleanup off); blob under "Bridge 1" |
| _7gP | Usable with flaws | two lines forced-broken at crescendo barlines, now 1.3 mm; dense, ragged lines |
| SZwT | Usable with flaws | blue player icons touch beams |
| SHvfn | Usable with flaws | gray return icons touch beams |
| Z4eb | Usable with flaws, source limitation | faded "#75 + track name" label and ghost clef; bass beams clipped by the video frame |
| GTOc | Unsupported | refused in 7 s |

Tally: clean 4, usable with flaws 7, unusable 0, unsupported 1 → usable 11/12. Fidelity: Fzc audited at 73–85 only;
the others not audited beyond page inspection.

## Known flaws carried into the holdouts

- Gray measure numbers can be clipped at a strip's left/right edge (Fzc 81).
- Forced breaks trust a pixel-geometry stroke test; a beam drawn as disconnected fragments could pass (STRATEGY note).
- Replay candidates are not auto-excluded: D.S./D.C. charts print the replayed lines until the user unticks them.
- Dark-theme footage smear (bF69) is not cleaned.
