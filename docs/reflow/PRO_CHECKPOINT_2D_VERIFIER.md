# ChatGPT Pro checkpoint: delivered-PDF verifier design (Step 2D)

Attach: `~/Documents/drum-score-corpus/reflow/spotcheck_2d1/check_10.png` (10 items the verifier flagged; left = source video frame, right = delivered result. NOTE: the white vertical breaks in tiles 6 and 8 are an artifact of our review-crop builder, not of the PDF).

```
You are reviewing the design of a verification gate in a desktop app. Please answer the numbered questions at the end. Be concrete; I will implement your recommendation.

PRODUCT
A local app captures drum scores already shown in YouTube videos (score images on screen, sometimes with a playback cursor/overlay) and lays the cleaned source images out on A4 PDF pages (no OMR; we reuse the pixels). Pipeline: sample ROI frames → track displays → per system, composite a clean "strip" PNG from many frames (median-like, cursor removal) → layout: either whole systems, or the DEFAULT "measure mode" that cuts strips at SAFE barline boundaries, removes some columns (spread/scaffold columns, clef/lead-in at joins), resamples each piece (cubic or area, scale ~0.8–1.3) and joins ~4 measures per line → render pages → JPEG inside a PDF (one DCT image per page).

RELEASE GATE (agreed earlier)
Every raw foreground hypothesis seen in the video must be proven delivered on the PDF, or carry a typed, evidence-backed disposition (cursor recovered underneath, duplicate display, non-score material, source-limited, unresolved → review). The verifier must be independent of the production masks (never trust "cleaned" masks), do two-way accounting (source→output and output→source, incl. duplicates), and run on the staged deliverable in both export paths. "Clean" only if no fail and no review_required.

WHAT WE BUILT (v2)
Hook 0 inventories every sampled ROI frame. Each producer records "items" = raw foreground hypotheses per display (connected/tiled components incl. antialiased fringe), with evidence views per observation. Transform chain per item: display→strip (affine) → strip→line (affine or piecewise, with recorded resize spec) → line→page (scale). The verifier projects each item's raw contrast through the chain, predicts JPEG, and matches it on the decoded PDF page; evidence qualification requires whole-hypothesis support across observations.

MEASUREMENTS ON TWO REAL DEV VIDEOS (S1: 564 observations, 2 pages; 01Mr: 619 observations)
- v2 pixel-level: S1 18,601 flagged entries (5,784 source mismatch, 5,107 ambiguous evidence, 5,101 registration unresolved, ...), 191 s, delivered ledger 44 MB. 01Mr 20,734 entries, 1,301 s, 104 MB.
- Human spot check of 10 random flagged items (attached): NOTHING missing; output mildly softened by resampling/JPEG but fully legible. Causes measured: fringe pixels (source contrast 12–57 on a 0–255 contrast scale; real notation 249–253) drop below the delivered contrast floor after resampling/JPEG; whole-hypothesis support (0 supporters of 48 eligible observations even at contrast 253); replica-edge kernel ownership; staff-scaffold provenance.
- v3 attempt, mark-level: marks = 8-connected clear ink (contrast ≥ 64), core = 1-px eroded; per-line registration (±3 px search, >1 px → PLACEMENT_MISMATCH); per mark ±1 px residual, cover ≥ 0.90 and IoU ≥ 0.6. Result: S1 760 entries / 48 s; 01Mr ~2,500 / 770 s. BUT two safety regressions appeared: tampered embedded evidence passes, and an erased dot attached to a long staff line passes (its loss is diluted inside the large connected staff mark). Many remaining 01Mr findings are replica/copy bookkeeping (309 "patch reused") and placement registration (275).

ALTERNATIVE I AM CONSIDERING (staged verification)
Loss can only be introduced at three operations, so verify each where it is simplest:
 A. source → strip (native scale, no resampling): every clear mark seen in ≥2 eligible raw observations of the display must appear in the strip PNG (mark-level, ±1 px after registration); one-observation marks → minority/alternate flow; cursor-recovery rule unchanged. Output→source: every clear strip mark must have raw support.
 B. strip → line (measure mode): pure bookkeeping on the recorded column map; any removed column containing clear strip ink must be justified (generated scaffold re-insertion, clef replica) or becomes review_required; duplicates/replicas counted.
 C. line/placement → delivered PDF page: independently re-render the expected page from the strip PNGs + recorded placements/resize specs (simple cv2 code, not the production renderer), JPEG-encode with the PDF's own quantisation, and compare to the decoded staged PDF at mark level (both directions: missing marks, extra marks, placement offsets). Plus the existing PDF format contract.
The composition A∘B∘C gives source→PDF accounting without projecting raw fringe through resampling+JPEG.

QUESTIONS
1. Is the staged design (A/B/C) an acceptable replacement for end-to-end raw→PDF projection under the gate above? What could it miss that end-to-end catches (e.g. a renderer that draws strip content in the wrong place consistently with a wrong recorded placement)? How would you close that hole cheaply?
2. Mark definition: how to define marks so a small mark attached to a long staff line (dot on a line, stem touching a beam) is not diluted, without per-pixel fringe matching? (e.g. subtract a fitted staff-line model first; local window coverage instead of component-level coverage; skeleton/ endpoint checks?) Recommend one.
3. Thresholds: C_clear = 64 contrast, cover ≥ 0.90, IoU ≥ 0.6, ±1 px residual, line offset ≤ 1 px. Are these sane for legibility-preserving checks on 1.2–2.0 mm staff spacing at ~150–200 dpi output? How would you set them without tuning to the two videos?
4. Evidence qualification: replace whole-hypothesis support with "mark core visible in ≥2 eligible observations". Any failure mode with moving cursors or partial occlusion we should guard?
5. Performance budget: what is a realistic target per job (≈3,000 observations, ~150 displays, ~15,000 marks) and which representation keeps the ledger under ~20 MB?
6. Anything in the gate itself you would now relax or tighten given that the human check found zero real loss among flagged items?
```
