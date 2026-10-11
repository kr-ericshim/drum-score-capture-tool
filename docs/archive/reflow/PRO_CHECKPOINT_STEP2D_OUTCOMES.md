> **보관 문서 (기록용, 지시 아님).** 이 파일의 계획·"Next"·규칙 제안은 따르지 않는다. 현재 기준은 [HANDOFF.md](../../reflow/HANDOFF.md)다.

# ChatGPT Pro checkpoint: product outcomes after Step 2D-1 (2026-10-09)

Attach the 8 images in `~/Documents/drum-score-corpus/advice_pack_5/` (01 to 08). Captions in 02 are Korean: rows are S1 (clean), SHvfn (gaps), aOED (repeated bars), bF69 (gray smudges), Z4eb (leftover screen text); left = Oct 7 build, right = today.

```
You are advising on the next steps of a desktop app. Answer the numbered questions at the end. Be concrete and rank options; I will act on your recommendation.

PRODUCT
A local Electron + Python app turns drum scores that are already shown in YouTube videos into printable A4 PDFs. No OMR and no transcription: we reuse the source pixels. The user picks a region, the app samples frames, tracks each displayed system (page views, scrolling or jumping views, cursors and overlays), builds one cleaned "strip" image per system from many frames (median-like composite, cursor/overlay removal), lays strips out on A4 (default "measure mode": cut at safe barlines, ~4 measures per line), and writes a lossless PDF.

WHERE WE ARE
- Over the last week we built a large safety/verification layer: a source-to-PDF ledger, a per-member "minority content" check (ink seen in only some frames must not be silently dropped), staged checks (strip, plan, page), and a review panel. The user said the work drifted ("too many guardrails"), so verification is now frozen. We now steer by three product outcomes: usable charts from the 12 non-holdout videos, job time on a normal laptop, and looks.
- Code: about 27k lines of backend pipeline, 1231 backend tests and 344 UI tests pass. 6 holdout videos are still sealed.

RESULTS ON THE 12 NON-HOLDOUT VIDEOS (I looked at every page myself)
- Clean and usable: 6/12 (S1, 01Mr, w7mK, Fzc, Q8X, SZwT; SZwT has tiny leftover overlay icons at some line ends).
- Usable with flaws: 3
  - aOED: bars 13 to 44 appear twice. The video plays the D.S. al Coda repeat, and the app captures the replayed section as new content (it also did this on Oct 7).
  - bF69: a gray smudge (a translucent progress/lyric bar) above every line, and a black blob next to one section label.
  - Z4eb: a screen label ("#75 鼓组") left inside a line; some lines are oddly short (1 to 3 bars) where systems were split.
- Not usable: 2. _7gP (68 unresolved time intervals) and SHvfn (18) are both scrolling/jumping "jump view" sources: fast cursor-driven displays where coverage of parts of the song could not be proven, so the PDF has gaps and a notice listing them.
- 1 unsupported by design: GTOc (notation drawn over live video).
- The dashboard's strict automatic "usable" metric says 0/12, so it is not useful as a product measure; the 6/12 above is my visual count.

SPEED (M-series MacBook, otherwise idle; 3-minute video = 01Mr)
- Before the verification work (Oct 7): 01Mr job 156 s, of which strip cleaning 22 s. S1: 79 s, cleaning 19 s.
- Today after two fixes (dev ledger made opt-in; a frame cache that was thrashing): 01Mr 277 s, cleaning 132 s. S1 119 s, cleaning 54 s. Output is pixel-identical to before those fixes.
- Profile of 01Mr cleaning (1,700 member frames across 17 systems): phaseCorrelate 31 s (2 calls per member, full-resolution ~1588x1000 crops), PNG decode 25 s (now once per member), percentile histograms 19 s (about 8 polarity/percentile passes per member), plus overlay masks, cursor/transition evidence and connected components. The cost comes from the per-member minority check, which now examines every member frame of every system at full resolution (the Oct 7 build checked every second member and ran the overlay mask only when unexplained ink was found).
- Target: a 3-minute video in 2 to 3 minutes total.

REVIEW ITEMS
The in-app review panel ("check items") would show 295 items for S1 and 1,286 for 01Mr. Their precision is not established, and a spot check earlier found no real loss among flagged items. Showing all of them would flood the user.

QUESTIONS
1. Priority: given 6 clean, 3 flawed and 2 unusable, plus the speed gap, what should the next two weeks focus on, in order? Options: (a) speed back to 2 to 3 minutes; (b) jump-view coverage gaps (_7gP, SHvfn); (c) repeat detection (D.S./D.C. replays captured twice); (d) overlay remnants (translucent bars, screen labels, icons); (e) anything else. Say what you would explicitly NOT do.
2. Speed without silent loss: the per-member minority check exists so that ink visible in only a few frames is not dropped. How would you cut its cost by ~4x while keeping that guarantee? Ideas I am weighing: check only members whose content changed (cheap downscaled diff against the previous checked member, reuse its result otherwise); register at half resolution and refine only when the shift is near the rejection threshold; cap witnesses per system as the composite does (15); compute polarity/percentile once per frame. Which do you trust, which is unsafe, and is there a better standard technique?
3. Repeats: when a video replays a D.S./D.C. section, should the PDF (i) keep the replay as captured, (ii) drop the replay when it matches already-captured bars and rely on the written D.S./Coda signs, or (iii) drop it only when the source shows a written repeat sign? How would you detect "this display is a replay of earlier content" robustly from pixels (the frames are near-identical to earlier ones, sometimes with a different cursor position)?
4. Overlay remnants: for translucent bars and small UI labels that sit between staves (not on notation), what is a simple, safe removal rule that will not erase real markings such as dynamics, section labels or lyrics?
5. Review items: what is a cheap way to decide which finding codes are precise enough to show in the app (the rest stay in a developer report)? How many items per job is acceptable for a user?
6. Holdout: the 6 sealed videos are meant to be opened once at the end. Given the above, what should be true before we open them, and what pass rate would you call "ready to ship to a few users"?
```
