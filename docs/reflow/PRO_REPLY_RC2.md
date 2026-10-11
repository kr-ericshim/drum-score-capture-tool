# Pro checkpoint #6 reply (2026-10-11): summary and decisions

Reply to [PRO_CHECKPOINT_RC2.md](../archive/reflow/PRO_CHECKPOINT_RC2.md), relayed by the user. Summary in our words; verified items marked.

## Verdict

Hold the rc2 freeze. Spend at most one day (6–8 h) on five items, then freeze and run a new sealed holdout of
**8 supported inputs + 2 separate refusal tests**. If an item is not solved in time, freeze with that feature restricted
conservatively; never tune thresholds while looking at opened holdouts.

## Pre-freeze items (time boxes)

1. **TeoV fallback** (60–90 min). Its metrics say `fallback_whole_systems / MEASURE_PLAN_ERROR`, 0 lines measured; a clean
   fallback may be graded Clean but is not a measure-reflow success. *Verified:* same in the rc1 holdout run (missed by us).
   Detail: `LayoutConflictError` at 1.5 mm — line-013 has a placement outside the printable area; the whole-systems path then
   reduced the staff to 1.45 mm. The measure path does not step the size down before giving up.
2. **Rejected-join disclosure** (60–90 min). App and PDF must both say "both views kept, join unconfirmed, measures may
   repeat" (not "fixed"; not green). PDF: a small margin mark/bracket at the two affected boundaries + a short note, distinct
   from the "†" source-clipping mark. Fix the clipped-line count in the header ("4 lines" → "3 lines" after a rebuild; the
   count is of strips, not printed lines): drop the number.
3. **Full read of the repaired charts** (60–90 min): RnY5 and J after rejection re-flow the whole document; read all of it,
   not only the join. Also confirm the existing tests cover: two repairs → cleanup/app restart → ordinary export → `[]`
   restores; and that revisions referencing earlier revisions' strips survive pruning.
4. **Narrow counterexamples** (90–120 min): (a) low-ink seams: the "≥ 4× better" test runs only inside the typical-jump
   window and is `inf` when nothing else is in it; add a rejection check over the wider feasible forward range (incl.
   one-bar-off alternatives); a comparable alternative keeps the seam unverified. Test: repeated rests where the true jump is
   one bar off typical; a correct unique case; cursor prior vs numbers/adjacent views conflict. (b) overlay relaxation: a
   static gray icon over notes and a thin static colored cursor across a stem must keep their warning; the 0MiL lyric fringe
   may drop it.
5. **Rubric, denominators, assistance budget, final build hash; packaged check of the changed features** (45–60 min).

Not blocking: black clip before play; repeated "†" notes (but fix the count); font glyph differences; Windows/8 GB (state
the scope); dmg (check install + first run before giving it to users).

## Holdout design

- 8 supported: 3 page-turn, 2 scroll (only the scroll kinds this version declares supported), 3 jump. ≤ 2 per channel,
  ≥ 4 channels, at least one channel or display style not in the dev set. Refusal tests separately: 1 live-overlay, 1 no-score.
- Selection: fix the scope and rules first; shuffle each channel's candidates with a recorded seed; look at 15 s at 10 %,
  50 %, 90 %; record only score present / plate / motion kind / mixed display; take in order until quotas are met; hash and seal.
  Never exclude a supported video for gray numbers, lyrics, density, cursor, clipping or a messy background. Anything found
  after sealing stays in the denominator. m_YP stays in the rc1 record (do not rewrite history).
- Ship bar (8): usable ≥ 7/8, clean ≥ 6/8, unusable + failed + refused + unresolved fidelity ≤ 1, observed silent fidelity
  defects 0, refusal tests 2/2, packaged create/review/save/cancel/restore on the stated Mac. Report supported and refusal
  results separately, never as "9 of 10". Record review burden and assisted results separately.

## Join check and rebuild

- Keep asking users only about inferred/unverified seams; graders check **every** seam, verified included.
- Add "hard to tell" (or allow no answer; never default to Fine). Optional later: zoom of 1–2 bars around the join, stills
  before/after, extend range, loop/slow. "Does bar X follow Y" only when numbers are clear.
- Record per video: seams by status, cards shown, review time/replays/extensions/"hard to tell", wrong joins found on cards,
  defects at unshown verified seams, duplicates/losses left after repair.
- Rebuild keeps both views = a conservative preservation copy, not a fix. Do not auto-apply the next-best offset now.
  A chart with a known repeated measure stays **Unusable** under the rubric even if the user accepts it.

## Grades

- Clean 8 kept visually (TeoV as a fallback layout). **aOED first export → Unusable** (D.S. al Coda plus the replayed section
  printed; the reader must skip music); assisted untick may be Usable. Usable becomes 14/17.
- RnY5 Usable only if the clipped bass tuplets read unambiguously from the PDF alone; undecided.
- Investigate, not ignore: Fzc `coverage unresolved` + `adjacent_duplicate 1` near 171.27 s; Q8 unresolved coverage items;
  RnY5 `UNSUPPORTED_HORIZONTAL_SCROLL` 110.5–130.5 s; `MINORITY_CONTENT_DROPPED` with alternates on several charts.

## After the holdout (default order; new fidelity defects first)

Replay grouping (auto-exclude only with same-notation-position evidence) → player icons (recover from clean observations,
no inpainting) → sampling/tracking speed → auto ROI (promote if setups fail) → faded jump labels → dark smear → Windows.
Do not: broad D.S./D.C. auto delete, reclassify ambiguity to cut warnings, sample fewer frames for speed, inpaint icons,
build a new optimizer/verifier before the holdout, ship Windows before the Mac pilot passes.

## Grading procedure (one person)

Pass 1 as a user: packaged app, normal setup, keep the first PDF and diagnostics read-only, random chart order, provisional
grade + worst page/line, then use the join check and selection (budget 5 min active, 1 rebuild) before any source study.
Pass 2 after a break: walk the source timeline (30–45 min per video), every seam incl. verified, measure order, repeats,
forced breaks/trims/tails/alternates/replays, ghost notes/accents/beams/tuplets/labels/lyrics; one dense page at real A4 size.
A later-found loss lowers the final grade; unaudited parts are "not audited". State "single grader, two passes".

## Item 3 result: full read of the repaired RnY5 (2026-10-11)

Read the rebuilt PDF (`eval_v1/seamcheck_rny5`, revision-2, 2 pages, 18 lines) bar by bar against one frame per source view
(22 views, labels #4 … #101, plus the final view at 172.8 s). All bars are present once and in order from bar 1 to the final
bar. The only exception is the rejected join (ep-0006 → ep-0007): the start of the bar at the join prints at the end of
page 1 line 5 and again in full at the start of line 6. This is the "both views kept" case the app now discloses. The
other 20 joins, verified or resolved, show no duplicated or missing bar. Note: this join was correct before the test
rejection, so the rebuild made the chart worse, as designed.

Clipped bass tuplet numerals: the source video itself cuts them off at the frame edge, and the PDF matches the source.
In the bar-8 type (three 4-note groups) the visible upper part reads as "3". In the page-2 groove bars it is only a
fragment, and 3 vs 5 cannot be told apart from the PDF alone. Under Pro's rule this is not unambiguous, so **RnY5 is graded
conservatively as not Usable** (usable 13/17, pending the FREEZE_RC2 update). It goes in the record as an input limit, not
a capture defect.

Not done: J's repaired chart, which is not in this rebuild set. The app-restart path is covered only by the existing
persist/restore unit tests, not by a packaged run.
