> **보관 문서 (기록용, 지시 아님).** 이 파일의 계획·"Next"·규칙 제안은 따르지 않는다. 현재 기준은 [HANDOFF.md](../../reflow/HANDOFF.md)다.

# Holdout run: checkpoint5-rc1 (2026-10-10)

Frozen build per [FREEZE_RC1.md](../../reflow/FREEZE_RC1.md): commit 3de6ff2 (code = 8a1125f), packaged macOS backend
(`drumsheet-backend` 38fa792c…), driven over HTTP like the app, auto ROI and auto label region, one run per video.
Outputs: `~/Documents/drum-score-corpus/eval_v1/holdout_rc1/`. Graded first export, Pro rubric, by the lead (single
reviewer; not blind).

## Result: the ship bar is NOT met

| Video | Channel | Outcome | Time / peak RSS | Grade | Fidelity |
|---|---|---|---|---|---|
| 0MiL (Post Malone – Circles) | atthedrum | done, 2 pages | 130 s / 3.4 GB | **Clean** | No measure numbers; lyrics run on across every line join and page; no loss observed |
| Dr5j (QWER – 눈물참기 HARD) | 열드럼 | done, 3 pages | 133 s / 2.4 GB | **Clean** | Measure numbers 1–139 continuous; faint pink whitespace bands only |
| TeoV (Day6 – Welcome to the show) | 열드럼 | done, 3 pages | 105 s / 2.3 GB | **Usable with flaws** | Numbers 1–107 continuous, but gray measure numbers clipped at the left edge: 63 reads "53", 67 reads "57" (also 29, 33, 51 cut) |
| RnY5 (Delinquents) | 鼓譜 Drumtabs | done, 2 pages | 96 s / 2.2 GB | **Unusable** | Jump view: at the one still-unverified seam (ep-0007→ep-0008, 66.7 s) measures 42–43 (two rest bars) are printed twice (p1 line 7: five rests after the fill instead of three). `JUMP_SEAM_UNVERIFIED` is recorded but the review shows another reason first, so the user is not told. Also: faded "#42 鼓组" label + ghost 4/4, a green cursor notehead, bass tuplet marks clipped by the video frame (disclosed) |
| 4M0X (RESCENE – Pretty Girl) | atthedrum | refused in 9 s | – | **Unsupported (correct refusal)** | Notation drawn over live footage with no plate (`composited_live`, 24/24 frames) |
| m_YP (Cruel Summer) | 鼓譜 Drumtabs | no ROI suggested | – | **No score in the video** | Every frame (sampled every 8 s) is live drumming only; the channel ships the score as a PDF. Selection error (holdouts were chosen from metadata). The app's auto ROI found nothing (correct) |

Tally over 6: clean 2, usable 3 (clean + usable with flaws), unusable 1, refused/no score 2.
Bar (≥ 5/6 usable, ≥ 4/6 clean, zero silent fidelity defect, ≤ 1 honest failure): **fails on every count.**
Even excluding m_YP as an invalid input: usable 3/5, clean 2/5, one near-silent duplication.

## What the holdouts taught

1. **Jump-view seams are still a fidelity risk.** An unverified seam keeps both sides; when the two views overlap,
   measures repeat. The flag exists but is buried. At minimum the review must show seam/fidelity reasons before
   cosmetic ones; better, resolve the overlap (the repeated bars are pixel-identical rest bars plus the view label).
2. **Gray measure numbers are clipped at strip edges** (Fzc 81, TeoV 29/33/51/63/67): the strip envelope does not
   count gray ink, so the box can cut a number in half and change what it reads. Systematic, not a one-off.
3. **Review reasons hide what matters.** Only the first reason is shown; OVERLAY_UNRECOVERED was listed on all 20
   0MiL systems (a page that is clean) while RnY5's seam warning was hidden.
4. **Source mix.** 2 of 6 sealed videos cannot work by design (live overlay, no score at all). Holdout/user video
   selection must look at a frame, not only the title.
5. Speed and memory were fine: 96–133 s per job, ≤ 3.4 GB.

## Status

checkpoint5-rc1 is not shipped. These six videos are now opened (regression set, no longer fresh). The next candidate
needs a new sealed set (selection by one frame per video, balanced across channels per the user) after the fixes.
