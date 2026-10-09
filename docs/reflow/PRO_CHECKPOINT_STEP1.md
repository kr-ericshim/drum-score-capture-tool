# ChatGPT Pro checkpoint after STRATEGY Step 1 (2026-10-07)

- Sent by the user, with the attachments in `~/Documents/drum-score-corpus/advice_pack_2/`.
- Pro's reply arrives at the start of the next session. Treat it as advice to check against the code and the dashboard, not as orders.
- Record what is adopted in STRATEGY.md.

## Prompt as sent

```text
This is a checkpoint review for the drum-score-video → clean A4 PDF app you advised earlier (your recommendation: keep raster capture/rendering; safety as a hard constraint; one bounded layout optimizer instead of escalation tiers; evaluation base first; overlay remnants as a separate defect class; background jobs; one structural repair at a time; sealed holdout). Attached "00_strategy_we_adopted.md" is how we encoded your advice. Please review progress and tell us whether our Step 2 priorities are right before we start.

STEP 1 DONE:
- Evaluation set eval_v1: 12 new videos from the user's real channels (atthedrum, 열드럼/Yeol's Drum, 鼓譜 Drumtabs jump-view chops). Split by video: 6 validation, 6 sealed holdout (chosen from metadata/thumbnails only; tooling refuses to run them). Mix per split: atthedrum line-switch ×1, atthedrum transparent overlay ×1, Yeol's Drum line-switch with "Next" preview inset ×2, Drumtabs jump view ×2.
- Dashboard (per video): outcome; reconstruction vs GT where available; cut safety (line breaks at non-SAFE boundaries); preservation (pixel ledger); overlay remnants (off-palette colored components); occupancy from page images (<90%, <60%, right-edge error); gap strain mean/P95/max; staff mm; pages; time/memory/temp disk.
- Rebuild/export is now a background task with progress and cancel (fixes the 30 s timeout).

BASELINE (attached 00_dashboard.md, contact sheet 01, examples 02–06). 12 non-holdout videos (6 old dev + 6 validation); only 3/12 pass the automatic "acceptable" check.
Failure classes we see:
1. Both new jump-view videos are rejected as UNSUPPORTED_LAYOUT: seams were found (49+1 verified/resolved, 15+10), but short leftover intervals classified as horizontal scroll make the whole job refuse.
2. One Yeol's Drum video ends "done" with 0 pages: its systems are wider than the page at 1.5 mm (fits at ~1.38–1.4 mm), measure plan unavailable → layout conflict without a visible failure.
3. Transparent-overlay video (white notation over live video, attachment 03) is processed as if supported; output prints over video. It should be an explicit unsupported/separate-adapter case.
4. Overlay remnants: blue cursor + magenta band under every line in a Yeol's Drum video (attachment 02), the "Next" preview inset leaking into the score region; smaller remnants in 3 older videos.
5. Layout: some charts stop 6–8 mm short of the right margin (common edge inside margin); one jump chart still breaks at 3 LOCKED/UNKNOWN boundaries (an old OVERSIZE_SPAN rule we decided to revert) and stretches gaps up to 3×; one chart needed up to 2.8× spread.

PROPOSED STEP 2 (our draft order):
a. Correctness/scope gates first: no "done with 0 pages" (fail visibly or fall back to whole systems at a fitting size); transparent overlay → explicit unsupported (until a separate adapter exists); jump view: classify per interval and support the jump intervals instead of refusing the whole job when small leftovers exist (leftovers reported, never silently dropped).
b. Revert OVERSIZE_SPAN; replace the justification tiers and the shrink trigger with your bounded min/preferred/max width model + one distortion cost + document objective (staff size chosen by objective, fine steps); short lines get recorded reasons.
c. Overlay-remnant cleanup (cursor/band/inset) as its own work item with the dashboard metric as acceptance.
d. Then Step 3 (hairpins, system-start clef, MuseScore marker cleanup, title/header).

QUESTIONS:
1. Is this the right Step 2 order given the baseline? Would you move overlay cleanup or the scope gates ahead of the optimizer, or split Step 2 differently?
2. Are our dashboard metrics and the "acceptable" definition sound? What's missing or misleading (e.g., occupancy measured on page images, palette-based remnant detector)?
3. For the "common right edge inside the margin" result: should lines justify to the page margin, or is a consistent inner edge acceptable? How to decide within the bounded model?
4. For jump videos with leftover horizontal-scroll intervals: is "support jump intervals, report leftovers" the right fail-closed behavior, or should such videos be refused until smooth scroll is supported?
5. Any red flags in our process so far (eval-set construction, holdout sealing, metrics) before we invest in the optimizer?

Be critical and concrete. Say plainly if priorities should change.
```
