# Jump-view thresholds: freeze note (milestone 1, 2026-10-07)

- **Frozen:** 2026-10-07 02:47 KST, before the held-out video was run.
- **Config hash:** `b3c5a3707f2eef02` (`reflow_jump.config_hash()`, `reflow_jump-1`). Every `reflow/jump.json` records the config and this hash.
- **Code at the freeze:** `reflow_jump.py` sha256 `c2c38138…`, ground-truth tool `jump_gt.py` sha256 `80478a2e…` (full hashes and the config in `~/Documents/drum-score-corpus/reflow/jump_m1/freeze.json`).
- **Tuned on:** `_7gPeY5Lcrk` (the app job) and qA-M_f0DMjw only.
- **Held out:** Pxt93gz8jas. It is run once with these values and reported as it comes out. No retuning afterwards.

## Verification thresholds

- **Residual:** at most 25. The residual is the mean tolerant |A−B| over inked overlap pixels, with staff-line rows left out.
- **Ratio:** at least 2. The ratio is (second-best + 2) / (best + 2); the floor of 2 stops two near-perfect offsets from counting as "far apart".
- **Overlap:** at least 2.2 staff spaces outside the panel.
- **Ink:** at least 4 staff spaces² of inked overlap.
- **Panel:** columns with fixed ink or faded contrast at the left edge, plus a 0.8-staff-space margin. Screen-fixed pixels anywhere are left out.
- **Run:** at least 3 consecutive verified jumps. A jump is at least 15% of the content width, each display dwells at least 1 s, and the transition takes at most 1.5 s.

# Freeze note (milestone 2, 2026-10-07)

- **Frozen:** 2026-10-07 04:02 KST, before Pxt93gz8jas and the negative videos were run with this code.
- **Config hash:** `2e5887c559828797` (`reflow_jump-2`). The full config, the code hashes and the ground-truth tool hash are in `~/Documents/drum-score-corpus/reflow/jump_m2/freeze.json`.
- **Tuned on:** `_7gPeY5Lcrk` and qA-M_f0DMjw only.
- **Not a clean held-out:** Pxt93gz8jas was seen in milestone 1. It is run once with these values and reported as it comes out.
- **No unseen jump-view video exists** in `videos/` or `videos_transparent/`: the transparent set and the other bottom-bar videos switch whole systems (checked on the survey contact sheets). waMCMJD7bQk and xft2krEJNBE (smooth scroll) are run as negatives; rsUfI3EKAj4 must stay `UNSUPPORTED_LAYOUT`.

## Seam resolution (new in this freeze)

- **Typical jump:** median of the slot's verified jumps; at least 5 of them, robust spread (MAD) at most half the tolerance. Tolerance: 3% of the display width.
- **Cursor prior:** fitted lines over the last / first 1.5 s of the cursor track, compared at the mid-transition moment. Used only when its 90th-percentile error on the slot's verified jumps is at most 5% of the width; tolerance 10% of the width.
- **Measure numbers:** read by tesseract over barlines (3 agreeing reads); a candidate must put B's numbers on the same numbers in A.
- **Panorama:** cut at least 1 staff space inside the overlap, at the least-difference column (centre pull 0.25 × median difference). Chunks at most 650 staff spaces, at least 60, cut 0.4–1.0 staff space right of a barline in a column clear over the full height.
