> **보관 문서 (기록용, 지시 아님).** 이 파일의 계획·"Next"·규칙 제안은 따르지 않는다. 현재 기준은 [HANDOFF.md](../../reflow/HANDOFF.md)다.

GPT-6 Astra (high) output below. The Codex progress-log lines are omitted. Full raw output is at /Users/ericshim/.claude/projects/-Users-ericshim-Documents-myproject-score-capture-program/240f329b-792c-4dd3-8865-beb8900be428/tool-results/bqwg2148v.txt

# Diagnosis and top recommendation

**INFERRED — Recommendation:** Build a **location-aware, evidence-preserving assembler first**, then a conservative image reflow engine. Make `clean_reflow` the only final-output contract. Its two permitted layout units are:

1. Safely segmented measure groups.
2. Cleaned, complete system strips when segmentation is unsafe.

Neither unit is a raw screenshot fallback. Both pass through normalization, page composition, and output validation. If system identity, order, or completeness remains unresolved, produce an editable preview and a review requirement, not a falsely successful final chart.

**Label convention:** `VERIFIED` means checked in the current files or by read-only computation during this inspection. `INFERRED` covers proposed behavior, engineering judgments, initial thresholds, and transfers from external research. **Every proposed numerical threshold below is an initial implementation value, not a calibrated corpus result.** Labels on tables and code blocks apply to their entire contents.

Paths below use:
- `R` = `/Users/ericshim/Documents/myproject/score_capture_program`
- `C` = `/Users/ericshim/Documents/drum-score-corpus`

## Root cause of the assembly failure

| Status | Finding and consequence |
|---|---|
| **VERIFIED** | `assemble.py` treats a single-system capture as already deduplicated upstream. It appends matching systems from different source paths; the single-system skip requires the **same source path**. This cannot resolve actual revisits. [C/tools/assemble.py:99–114] |
| **VERIFIED** | Multi-system assembly chooses the longest prefix matching the accumulated song's suffix. It has no score-location identifier, timestamp, traversal model, or nonlocal repeat resolution. [C/tools/assemble.py:115–129] |
| **VERIFIED** | `same_system()` uses bar positions and a thresholded signature normalized to an 8-pixel staff gap. It compares only the shared minimum image extent and permits a 6% tolerant ink mismatch. The signature covers a limited vertical band rather than the full content envelope. [C/tools/assemble.py:68–92] |
| **INFERRED** | These rules conflate **appearance equality** with **location identity**. Repeated grooves can falsely establish overlap; actual revisits outside the suffix can be appended again. Lost text, numbers, partial crops, and tolerant signatures further reduce distinguishing information. This is a modeling defect, not primarily a threshold-tuning problem. |
| **VERIFIED** | Current backend dedupe is deliberately more cautious: playhead resets become ambiguous, persistent returns are kept for review, and direct-duplicate observation groups are reported. However, the recent-frame cache is only eight entries, and a pending return at video end is discarded as flicker. [R/backend/app/pipeline/stitch.py:206–349] |
| **INFERRED** | Reuse that implementation as local observation evidence. Do not make its retained-capture list the irreversible input to song reconstruction. A later location-aware stage needs access to all observations, including excluded and terminal-transition candidates. |

## Ranked ways forward

**INFERRED — Ranking by expected payoff versus effort:**

| Rank | Approach | Expected payoff | Effort / principal risk |
|---|---|---|---|
| **1** | Temporal display-episode tracking + layout geometry + explicit score-location graph + unresolved-case review | Addresses both false merges and retained duplicates; reusable across layouts | Medium–high. Some inputs are fundamentally unidentifiable |
| **2** | Conservative episode extraction + user-assisted system ordering/duplicate resolution + cleaned-strip pagination | Earliest dependable product increment; supplies correction tools required by approach 1 | Medium. More unresolved decisions remain manual |
| **3** | Source-local printed-number/text-patch identity matching | Strong supplementary evidence where distinctive labels survive | Medium. Absent labels, numbering restarts, tiny digits, and repeated section labels limit coverage |
| **4** | Tune global image-similarity dedupe | May improve selected examples | Low initial effort, poor structural payoff; cannot distinguish identical but distinct locations |
| **Deferred** | Translation mosaics for horizontal scrolling | Necessary for the two explicitly marked strip-scroll sources | Medium–high; cumulative drift and periodic patterns require separate validation |

**INFERRED — First experiment:** Implement only a read-only assembly evaluator, observation manifest, and episode tracker. Start with the 16 sources not marked horizontal-scroll. Compare:
- Existing `assemble.py`.
- Episode tracking with **no nonlocal automatic merges**.
- Episode tracking plus geometry/identifier/context evidence.

Label location transitions and repeat candidates, not notes. Success means **zero observed false automatic location merges**, zero silently lost labeled systems, and a material reduction in duplicate/unresolved decisions versus the conservative baseline. Use **>=80% automatic resolution of adjudicable identity decisions** as an initial usefulness target; separately report genuinely unidentifiable cases. Do not begin aggressive measure reflow to compensate for an incorrect sequence.

**INFERRED — Where I disagree with the framing:**
- "As written versus traversal" is not always recoverable from video. A video may display a pre-expanded arrangement, omit unplayed endings, or reuse an identical graphic for different written locations. The defensible target is **the source's written locations to the extent recoverable**, with explicit unresolved relationships.
- Exact pixel identity, timestamps, and a playhead reset together can still describe either a repeat or a different identical system. No weighting formula can manufacture missing information.
- Image reflow as the sole output is a coherent product decision. **Guaranteed two-page, four-measures-per-line, equal-width, engraving-quality output for every source is not.** Preserve content and legibility before those aesthetic targets.
- "Only cleaned reflow is final" must permit a blocked export. Otherwise it pressures the implementation to hide incomplete acquisition or invent certainty.

---

# 1. Output model: written locations, observations, and traversal

## Canonical interpretation

**INFERRED — Adopt `source_written` as the only output-order policy.**

A score location represents a distinct place in the **displayed written arrangement**, not a unique musical pattern. Preserve printed repeat signs, endings, section labels, and measure numbers as image content. Do not invent repeat signs to compress repeated grooves.

Keep these entities separate:

| Entity | Meaning | Identity |
|---|---|---|
| `Observation` | One sampled frame and one detected system region | Source + presentation timestamp + region |
| `DisplayEpisode` | A continuous interval during which a screen slot shows the same location | Temporal segment, independent of later identity resolution |
| `ScoreLocation` | One distinct written system or anchored system fragment | Assigned ID; never an image hash |
| `TraversalOccurrence` | One visit to a score location during playback | Episode/visit ID; several occurrences may reference one location |
| `WrittenOrderEdge` | Evidence that location A precedes B in the written arrangement | Geometry, printed numbering, confirmed context, or user decision |

**INFERRED — Preview systems need special handling:** A visible lower row may be a preview of the next system, not a performed occurrence. Record it as an observation of a location with `role="preview"`. Do not count every displayed row as a traversal visit.

**VERIFIED — Existing code already recognizes the ambiguity:** A playhead moving backward by at least `0.3` of frame width is a reset signal, and the documentation explicitly allows either a repeat or an identical next page. [R/backend/app/pipeline/page_diff.py:135–148]

## Evidence and decision rule

**INFERRED — Use hard contradictions and independently sourced evidence families. Do not sum several correlated pixel similarities as independent votes.**

Let `g` be median staff gap and `W` the system width.

| Evidence family | Initial qualification | What it can establish |
|---|---|---|
| **Geometry `G`** | Continuous page/scroll transform; >=12 nonstaff feature inliers, inlier ratio >=0.75, median residual <=0.15g; support spans >=50% of system width | Same physical location across overlapping views |
| **Identifier `I`** | Full printed-number/text patch matches across >=3 observations; normalized correlation >=0.97, runner-up margin >=0.05; patch is distinctive within the source | Candidate location identity; numerical order only if value is known |
| **Appearance `A`** | Complete envelope compared at compatible scale; no unexplained content-bearing component mismatch | Compatibility, never unique location identity alone |
| **Context `C`** | At least two neighboring location relationships already independently anchored | Disambiguation of a repeated-looking system |
| **Motion `M`** | Same slot, temporal continuity, no transition; playhead advance or reset recorded separately | Episode continuity and possible visit boundaries |
| **User `U`** | Explicit "same written location," "different location," or order edit | Authoritative relationship for that document |

**INFERRED — Contradictions:**
- Two systems occupy different coordinates in the same verified page map.
- Reliable printed location identifiers differ within the same numbering scope.
- A persistent content difference survives overlay masking in at least two observations.
- A merge would collapse two simultaneously visible distinct locations.
- A merge would violate a confirmed written-order constraint.

A content difference at the same page coordinate may indicate a changed score state rather than a new location. Preserve both variants and require review; never median them together.

**INFERRED — Decision procedure:**

```text
for each new system observation:
    attach to an existing display episode only if
        same screen slot + stable registration + no persistent content change
    otherwise:
        create a new episode

for each episode E:
    nominate candidate locations using geometry, identifiers, and appearance
    retain NEW_LOCATION and UNRESOLVED as explicit alternatives

    if user decision exists:
        apply it
    elif hard contradiction exists:
        reject that candidate merge
    elif continuous geometry identifies an existing coordinate and A is compatible:
        attach E to that location
    elif nonlocal revisit is proposed:
        accept only with:
            I + independently anchored C + compatible A
            OR a verified page-map identity + matching system coordinate
        otherwise mark POSSIBLE_REVISIT
    elif new page coordinate or reliable different identifier is established:
        create a distinct location
    else:
        keep a provisional distinct location and raise IDENTITY_UNRESOLVED
```

**INFERRED — For multiple competing candidates:** Use an evidence ranking score only to order review suggestions:

`score = 6G + 4I + 3C + A + M`

Automatic selection additionally requires the logical gates above, a score of at least `8`, and a margin of at least `3` over the runner-up. These numbers are not probabilities. Geometry and context derived from the same unconfirmed match must not be counted twice.

**INFERRED — Printed-number matching without OCR:**
- Crop number-like clusters above/left of the staff and preserve their complete bounding boxes.
- Cluster normalized patches by visual equality.
- Store `number_patch_id`; leave `number_value=null`.
- Equality can support a revisit. It cannot tell whether "17" precedes "21."
- A source-local digit-template recognizer that outputs integers is still character recognition, even without an OCR dependency. Defer it; allow an optional user-entered number when useful.
- Numbering restarts require a `numbering_scope_id`; do not treat a bare number as globally unique.

**INFERRED — Written order:** Construct a partial-order graph from page geometry, continuous scroll coordinates, known numeric anchors, and user decisions. A temporal transition can nominate a forward edge, but must not override a detected revisit. Resolve cycles as conflicts. Use temporal order only for provisional preview placement and mark it unresolved.

**INFERRED — Research transfer:** Shan and Tsai separate local alignment from segment-level jump handling. That supports this two-level architecture, but their piano/audio results do not validate drum-video assembly or the thresholds above. [Improved Handling of Repeats and Jumps in Audio-Sheet Image Synchronization](https://arxiv.org/abs/2007.14580)

---

# 2. Per-layout assembly and uncertainty UI

**VERIFIED — Corpus inventory:** Read-only inspection found 18 MP4s, 18 ROI entries, and 18 run entries. `layout` contains 13 `bottom_bar` and 5 `full_scroll` values; two of those 13 also have `kind="horizontal_scroll"`. The harness must honor `kind` before `layout`. Those two are `qA-M_f0DMjw` and `rsUfI3EKAj4`. [C/rois.json:290–356]

**VERIFIED — Current corpus runner ignores that distinction:** It passes `entry["layout"]` to detection and stitching, without consulting `kind`. [C/tools/job_stage.py:21–26]

## Assembly algorithms

**INFERRED — Shared acquisition/tracking defaults:**
- Coarse scan at **2 Hz**, analysis width <=960 pixels.
- Resample **±1 second at 8 Hz** around apparent changes, resets, or ambiguous registration.
- Confirm a stable episode using >=3 observations spanning >=0.5 seconds.
- Preserve short and terminal episodes as `SHORT_EPISODE`; do not automatically discard them.
- Use source-resolution crops for content verification and final imagery.
- Classify layout per interval, because a video may change presentation style.

| Layout | Algorithm | Failure handling |
|---|---|---|
| **Bottom bar, one/two rows** | Detect staff rows and track each screen slot independently. Segment episodes when stable notation changes, a row shifts, or a playhead resets. For two-row displays, distinguish active and preview rows; match promotion of the preview row using full envelope and slot transition. Resolve nonlocal revisits using section 1. | Reset without identity evidence -> `POSSIBLE_REVISIT`. Identical neighboring grooves remain separate provisional locations. A disappearing preview does not prove omission or performance. |
| **Full page/page turn** | Group stable page episodes. Register page content excluding overlays and transition animation. Build a page-coordinate map; location key is `(page_map_id, system_bbox_in_page)`. Sort complete systems top-to-bottom, with explicit column detection if needed. Recognize revisited pages through full-page context, not one row. | Page identity ambiguity -> compare page neighborhoods. Cut without overlap/numbering -> `ORDER_UNRESOLVED`. Never combine two different rows because their grooves match. |
| **Continuous vertical scroll** | Estimate frame-to-frame translation using nonstaff content. Accumulate a document-coordinate transform. Associate systems by coordinate overlap and appearance. Prefer the best complete observation; mosaic only if no observation contains the entire envelope. Re-anchor every 10 accepted transitions or whenever loop-closure evidence appears. | Translation residual >0.15g, overlap <25%, or multiple comparable correlation peaks -> stop the chain and resample. Unresolved discontinuity starts a new map fragment with an uncertain join. |
| **Horizontal scroll — deferred** | Same coordinate-map approach along x. Require >=30% overlap, consistent direction, and at least two nonperiodic anchors. Preserve partial measures until both boundaries are observed. Segment the completed mosaic afterward. | Periodic groove aliases or drift -> unresolved mosaic join. Until supported, show `UNSUPPORTED_HORIZONTAL_SCROLL`; do not run bottom-bar dedupe and claim a completed chart. |

**INFERRED — Registration safeguards:** Use staff lines to estimate scale and orientation, but exclude them from the decisive translation score: periodic horizontal lines alone provide weak vertical-position evidence. Require nonstaff support from multiple spatial regions. Prefer translation; if scale changes by >2% or rotation by >0.3 degrees, start a new acquisition segment and explicitly register it rather than accumulating the old transform.

## Review systems, not screenshots

**VERIFIED — Existing review supports similar-capture explanations and comparison, while controller history stores selection and crop state. These are useful interaction foundations, but the current history shape does not contain system order or identity decisions.** [R/desktop/renderer-v2/src/features/review/ReviewScreen.js:61–76], [reviewController.js:12–15]

**INFERRED — Preserve Floating Dock Canvas and introduce two review views:**
- **Pages:** composed A4 preview, the primary artifact.
- **Systems:** ordered strip thumbnails, inclusion checkbox, location label, issue indicator, and drag handle.
- Selecting a system highlights its placement on the page.
- An identity issue opens the two cleaned systems with neighboring systems above/below. Actions: **Same written location / Different locations / Decide later**.
- Add **Move up/down**, drag reorder, **Split system**, **Join fragments**, **Choose clearer observation**, and undo/redo.
- Local observation previews/timecodes are internal evidence controls. Add no link-to-source feature.

**INFERRED — Initial dimensions:** Keep the existing dock; use a 280-pixel system panel with 12-pixel internal spacing. At 1120x840, show issue details in an overlay panel rather than a permanent third column. Reuse existing semantic colors and controls.

**INFERRED — State-to-action contract:**

| State | User-facing message/action | Final export |
|---|---|---|
| `RESOLVED` | Normal system | Allowed |
| `POSSIBLE_REVISIT` / `IDENTITY_UNRESOLVED` | "반복 표시인지 다른 줄인지 확인 / Check repeat or separate system" | Blocked until resolved |
| `ORDER_UNRESOLVED` | Show uncertain join and move controls | Blocked |
| `ENVELOPE_CLIPPED` | "악보 위아래가 잘렸습니다 / Notation is clipped"; propose new ROI draft | Blocked for affected included content |
| `OVERLAY_UNRECOVERED` | Show affected area and alternate observations | Blocked if notation is obscured |
| `SEGMENTATION_LOCKED` | "이 줄은 통째로 배치 / Keep this system together" | Allowed as cleaned strip |
| `LOW_SOURCE_RESOLUTION` | Show actual-size detail preview | Allowed after explicit acknowledgment |
| `NON_SCORE_UNCERTAIN` | Restore/exclude control | Requires a decision if exclusion creates a sequence gap |
| `UNSUPPORTED_LAYOUT` | Name unsupported interval | No misleading whole-song final output |

**INFERRED — UI domain:** The organizing concepts are staff, system, measure, printed location, repeat visit, and paper page. The distinctive interaction is selecting a system and seeing both its page placement and the observations supporting it. Keep white paper, black notation, neutral canvas, blue selection, and amber uncertainty; avoid screenshot galleries with equal-weight cards and unexplained confidence badges.

---

# 3. Acquisition fixes: complete envelopes and clean observations

## Full notation envelope

**VERIFIED — Current automatic ROI padding is fixed at 4.5 staff gaps above and below detected staff clusters.** [R/backend/app/pipeline/auto_roi_detector.py:176–182]

**VERIFIED — Current ROI-health sampling checks three nearby times, `0`, `+0.8`, and `+1.6` seconds relative to the requested time. Its edge warning uses aggregate edge-band density. This does not inspect the entire source's notation envelope.** [R/backend/app/pipeline/roi_health.py:56–63], [roi_health.py:140–146]

**VERIFIED — The pilot manifest records two manually reacquired systems and app-only eligibility of 15/24 measures. I also viewed the 10cm existing crop and taller reacquired strip: the existing crop is tight against the open-hi-hat circles and cuts through the lower lyric region. The manifest's numerical eligibility statement is a stored pilot assessment, not a newly repeated audit of all 24 measures.** [C/pilot/reengrave-v1/config/manifest.sentinel-v1.json:60–63], [same file:198–204]

**INFERRED — Implement `notation_envelope.py`:**
1. Detect staff geometry in the **full source frame**, not only the already-clipped crop.
2. Initially inspect up to 12 evenly distributed source times; during acquisition, inspect every new stable episode.
3. Search around each staff from `top-8g` to `bottom+8g`, bounded by neighboring staff regions and the score panel.
4. Build connected-component and text-line candidates on an analysis-only staff-suppressed mask.
5. Attach nearby marks and horizontal text groups to the appropriate staff; retain ambiguous between-staff annotations with a shared-span constraint.
6. Compute the union of stable notation/text envelopes and add **0.75g** top/bottom safety padding and **0.5g** side padding.
7. Any content-bearing component touching within **0.25g** of an applied crop edge triggers a clipping warning. Do not use aggregate density as the sole test; a small circle can be important.
8. Where text/mark ownership is unclear, preserve more image content and flag the ambiguity. "Intro," rehearsal boxes, dynamics, and lyrics are not automatically disposable background.

**INFERRED — ROI state contract:** Return the larger envelope as a suggestion with `source_revision`, `roi_revision`, sampled times, and highlighted clipping evidence. Apply only through the existing explicit ROI action. A later discovery may propose another draft and pause finalization; it must not silently expand the applied capture boundary.

**VERIFIED — This respects current behavior:** Rectification treats the visible ROI as the capture boundary, and the renderer refuses to replace a draft edited while automatic detection was running. [R/backend/app/pipeline/rectify.py:39–49], [R/desktop/renderer-v2/src/app/App.js:1639–1649]

## Best frame and overlay removal

**VERIFIED — Existing compositor limitations matter:**
- It runs for bottom-bar/page-turn layouts.
- It uses up to 15 accepted members.
- It rejects displacement >=0.5 pixels rather than warping members.
- Its mask targets bright colored overlays.
- Columns covered in every observation fall back to the median of all observations.

These are checked implementation facts, not evidence that all dark playheads or highlights are removed. [R/backend/app/pipeline/overlay_composite.py:14–28], [overlay_composite.py:60–108]

**INFERRED — Extend, rather than replace, that work:**
- Compose **within a resolved episode/location region**, not across merely similar systems.
- Prefer a single complete, unobscured, sharp observation when available.
- Rank valid observations lexicographically: complete envelope -> least unresolved overlay -> stable alignment -> sharpness. Sharpness must not outweigh clipping.
- For composites, select observations across playhead-position bins, not just time, to maximize uncovered notation.
- Require >=3 unmasked observations per composited notation region for automatic acceptance. With only one/two clean observations, use the best observed pixels and surface reduced evidence.
- Replace the "all covered -> ordinary median" success path with an **unrecoverable coverage mask**. It may create a preview, but cannot certify cleaned notation.
- Detect dark playheads through temporal movement and transient tall strokes; a static dark stem/barline is not an overlay merely because of its shape.
- For scrolling, register into system coordinates first. Require residual <=0.15g, reject mismatched components, and resample each source only once into the final system raster.
- Never fill permanently hidden notation by generative inference or unconditional whitening.

**VERIFIED — Paper flattening already uses a smooth background estimate, targets paper level 250, and attempts to retain gray ink contrast. It skips dark/unsuitable inputs below a paper-level threshold of 170.** [R/backend/app/pipeline/paper_tone.py:14–60]

**INFERRED — Cleanup validation:** Normalize dark polarity only inside a confirmed score region, then reuse paper flattening. Protect the complete notation envelope from border-rule removal. Flag any unexplained loss of a stable component with area >=`0.04g^2`; also inspect smaller protected marks from the clipping GT. This is a conservative alarm, not a proof of musical correctness.

---

# 4. Measure segmentation and page layout

## What can be reused safely

**VERIFIED — The newer detector contains staff-space tests for rejecting stems/glyphs, percussion-clef handling, and splitting disconnected staff segments.** [C/tools/measure_detect.py:33–70], [measure_detect.py:73–175]

**VERIFIED — The reflow prototype imports the older `measure_proto.py`, not `measure_detect.py`. Its crossing test excludes the main staff band, so it does not inspect all possible within-staff cross-barline content.** [C/tools/proto/reflow_proto.py:1–4], [reflow_proto.py:49–66]

**VERIFIED — The page prototype's nominal 8% limit is not a hard content-preservation guarantee:** its final horizontal scaling permits `MAX_STRETCH + 0.02`, and it subsequently slices the row to the target width. [C/tools/proto/page_proto.py:65–73]

**INFERRED — Port algorithms as references, not as an unchanged production module.** A barline detector is only the first half of safe segmentation; the other half is preserving all image content around the proposed cut.

## Segmentation contract

**INFERRED — Each boundary becomes `SAFE`, `LOCKED`, or `UNKNOWN`.** A safe boundary requires:
- Stable barline location within `0.25g` in at least three usable observations, or explicit review.
- Staff-spanning evidence and stem/glyph rejection.
- No connected or conservatively grouped nonstaff object crossing the cut.
- Complete left/right boundary content ownership.
- No unexplained tail pixels after the last detected barline.

Use masks for analysis only; never erase staff lines from the delivered score image.

| Case | INFERRED handling |
|---|---|
| Ordinary isolated barline | Permit a cut after the complete boundary, with explicit ownership of its pixels |
| Double/final/repeat barline | Treat the whole stroke-and-dot neighborhood as one boundary object. If direction/ownership is uncertain, lock adjacent measures together |
| Multi-measure rest | Preserve as an indivisible image unit; `measure_count=null` unless independently known |
| Volta bracket | Lock all affected units across the bracket. Preserve label and endpoints; do not redraw guessed continuation |
| Tie/slur/beam crossing boundary | Lock connected units. Analyze inside and outside the staff; a staff-band-only exclusion is unsafe |
| Text/dynamics spanning boundary | Group text with horizontal dilation of approximately `0.7g`, then lock the crossed boundary |
| Ambiguous barlines or incomplete edges | Keep the entire cleaned system |
| First-system clef/time signature/tempo | Preserve the complete prefix and above-staff annotations with the original first measure |
| Subsequent printed clefs | Remove/reuse only a positively matched clef-only patch. If prefix contents are uncertain, retain the original system break |
| New line needing a clef | Reuse a verified source clef graphic with provenance; do not duplicate a time signature or invent missing notation |

**INFERRED — Pixel-accounting invariant:** Every accepted content region must map to exactly one output placement, except explicitly repeated clef graphics. No `row[:, :width]` overflow truncation. A segmentation attempt that cannot satisfy this invariant becomes a cleaned-system unit.

## Scale, line breaking, and justification

**INFERRED — Defaults:**

| Parameter | Proposed default |
|---|---|
| Page | A4 portrait, 2480x3508 pixels at 300 dpi |
| Margins | 15 mm left/right; 14 mm top/bottom |
| Staff gap | 1.50 mm ~= 17.72 pixels at 300 dpi |
| Optional compact preset | 1.35 mm; never silently activated |
| Minimum staff gap | 1.25 mm, requiring explicit choice |
| Measure target | 4 per line, soft preference |
| Notation scaling | Isotropic to the document staff gap |
| Expansion | Staff-only slack insertion, <=8% of natural line width |
| Per-slot insertion | <=`min(1.2g, 0.5 x original_slot_width)` |
| Contraction | <=3% of natural width, removing only verified staff-only slack; retain >=0.35g per slot |
| Glyph horizontal stretch | 0% by default |
| Line separation | >=2g between content envelopes; distribute up to 4g |
| Last-page spacing | Cap at 2.5g to avoid artificially sparse pages |

**INFERRED — Normalize before pagination:** Estimate each system's staff gap from five-line geometry; require gap variation <=10% within the system. Scale the complete envelope uniformly. Align the top staff line across units in a composed line and pad above/below according to their actual envelopes. Do not stretch system width independently of height to force the margin.

**INFERRED — Dynamic-programming line breaking:**

```text
For each legal contiguous unit range i..j:
    N = natural width including required prefix
    E = available safe expansion, capped at 0.08*N
    C = available safe contraction, capped at 0.03*N

    feasible justified line iff target_width lies in [N-C, N+E]
    otherwise:
        allow an explicitly ragged line if N <= target_width
        reject overflow

    cost =
        100 * adjustment_ratio^2
        + 3 * (known_measure_count - 4)^2
        + 40 * single_measure_orphan
        + 25 * ragged_nonfinal_line

    forced section break / locked group constraints override cost
```

Here `adjustment_ratio` is the fraction of available expansion/contraction used. Omit the four-measure penalty when measure count is unknown. Reconstruct only from reachable DP states; an unreachable state must not default to a slice of oversized content.

**INFERRED — Failure ladder:**
1. Try another legal line break.
2. Keep a locked measure group intact.
3. Place the cleaned original system on its own line.
4. Show a ragged-line exception if safe justification is impossible.
5. If the intact system still cannot fit at the selected readable scale, require a size/layout decision.

Uniform staff size, preserved marks, and equal right edges cannot always coexist. The UI should identify which lines remain ragged rather than distort or clip them.

**INFERRED — Research transfer:** Knuth–Plass's boxes/glue/penalties provide the right abstraction: image units are fixed boxes, verified staff-only gaps are bounded glue, and annotation crossings impose infinite break penalties. The useful change is global break optimization with explicit feasibility, not adopting a text typesetter. [Breaking Paragraphs into Lines](https://gwern.net/doc/design/typography/tex/1981-knuth.pdf)

## Page composition and output

**INFERRED — Page-break rules:**
- Never divide a composed line.
- Keep a section label with its first line.
- Penalize a one-line last page; rebalance when feasible without violating minimum gaps.
- Use an initial first-page header budget of 28 mm, expanding for wrapped title/credits.
- Title: editable metadata suggestion, up to two lines before requesting shortening.
- Credits: editable; do not equate channel/uploader with composer or performer.
- Preserve printed tempo/section text inside the score.
- Put simple page numbers in the **upper outer margin**. No footer text, source URL, or source-link feature.
- Treat "approximately two pages" as a soft result, never a reason to omit systems or shrink below the selected staff size.

**VERIFIED — Current export needs a separate path for already-composed pages:** It finalizes/splits input pages, writes PNG/JPG before adding the document header to PDF, and has a later PDF resize helper. Passing reflow pages through that path risks changing composition or producing format differences. [R/backend/app/pipeline/export.py:62–115], [export.py:643–653]

**INFERRED — Add `export_composed_pages()`:** Encode the same composed page rasters into PNG/JPG/PDF, including identical header and pagination. Set 300-dpi physical sizing; bypass legacy page splitting, header appending, and post-composition resizing. Keep PNG as the lossless master.

**INFERRED — Resolution disclosure:** A 300-dpi page does not create source detail. Record source staff-gap pixels and effective source dpi after placement:

`effective_source_dpi = 300 / raster_enlargement_factor`

Flag effective resolution below 180 dpi or source gap below 8 pixels for detail review. These are initial warning thresholds. Use deterministic OpenCV/Pillow resampling on CPU; no learned upscaler is required for this output contract.

---

# 5. Repository integration and data contracts

## Pipeline placement

**VERIFIED — Current primary integration point:** `main.py` selects candidates, composites overlays, flattens paper, diagnoses captures, stitches, upscales, and exports. The review-export endpoint separately calls stitching before export, so both paths must change. [R/backend/app/main.py:1325–1425], [main.py:984–1005]

**INFERRED — New pipeline:**

```text
source + applied ROI
  -> observation manifest + rectification transforms
  -> system regions + full-envelope diagnostics
  -> display episodes + layout-coordinate maps
  -> score locations + occurrences + written-order constraints
  -> system cleanup
  -> review decisions, if required
  -> measure/locked-system units
  -> normalized line/page plan
  -> page rasterization + validation
  -> export_composed_pages
```

**INFERRED — Retain existing dedupe as evidence:** Run its comparison/grouping logic, but preserve a complete observation index before filtering. Persist its groups, similar pairs, and removal reasons. Do not allow "removed upstream" to make an observation unavailable to assembly.

**VERIFIED — Timestamp provenance needs extension:** Extraction emits sequential frame filenames after an FFmpeg `fps` filter; rectification renumbers output using detection enumeration. Neither filename alone is a reliable original-frame timestamp contract. [R/backend/app/pipeline/extract.py:683–734], [R/backend/app/pipeline/rectify.py:33–55]

## Modules

**INFERRED — Proposed files and responsibilities:**

| File | Responsibility |
|---|---|
| `backend/app/pipeline/observations.py` | Stable IDs, source timestamps, ROI/transform provenance |
| `backend/app/pipeline/system_detect.py` | Port hardened staff/barline primitives from corpus detector |
| `backend/app/pipeline/notation_envelope.py` | Annotation envelopes and clipping checks |
| `backend/app/pipeline/system_tracking.py` | Display episodes, playhead tracks, layout classification |
| `backend/app/pipeline/score_assembly.py` | Locations, occurrence links, evidence gates, partial-order graph |
| `backend/app/pipeline/scroll_mosaic.py` | Translation coordinate maps; vertical first |
| `backend/app/pipeline/measure_segment.py` | Safe/locked boundaries, prefix ownership, image units |
| `backend/app/pipeline/reflow_layout.py` | Staff normalization, line DP, page DP |
| `backend/app/pipeline/reflow_render.py` | Page rasters, pixel provenance, geometry checks |
| Existing `overlay_composite.py`, `paper_tone.py` | Extend diagnostics and system-level inputs |
| Existing `extract.py`, `rectify.py`, `stitch.py` | Add manifests/transforms and non-destructive evidence reporting |
| Existing `main.py`, `schemas.py`, `export.py` | Orchestration, versioned API, final-output enforcement |

## Data shapes

**INFERRED — JSON contracts; coordinates use explicit half-open `[x0,y0,x1,y1]` boxes:**

```json
{
  "schema_version": 1,
  "observation": {
    "id": "obs-000123",
    "source_id": "video-sha256",
    "t_sec": 34.625,
    "time_basis": "source_pts",
    "time_uncertainty_sec": 0.0,
    "frame_path": "artifacts/frames/...",
    "roi_revision": 3,
    "applied_roi": [[0, 797], [1920, 797], [1920, 1080], [0, 1080]],
    "source_to_crop": [1, 0, 0, 0, 1, -797, 0, 0, 1],
    "system_regions": [
      {
        "region_id": "obs-000123-r0",
        "bbox": [0, 8, 1920, 275],
        "staff_y": [105, 121.5, 138, 154.5, 171],
        "staff_gap_px": 16.5,
        "envelope_bbox": [8, 24, 1890, 266],
        "slot_id": "bottom-0",
        "role": "active",
        "playhead_x": 0.76,
        "issues": []
      }
    ]
  }
}
```

```json
{
  "assembly_revision": 7,
  "locations": [
    {
      "id": "loc-014",
      "page_map_id": null,
      "document_bbox": null,
      "number_patch_id": "patch-9",
      "number_value": null,
      "numbering_scope_id": "scope-1",
      "observation_region_ids": ["obs-000123-r0"],
      "clean_asset_id": "asset-sha256",
      "identity_state": "resolved",
      "issues": []
    }
  ],
  "occurrences": [
    {
      "id": "visit-019",
      "episode_id": "episode-019",
      "location_id": "loc-014",
      "t_start": 27.0,
      "t_end": 36.2,
      "role": "performed"
    }
  ],
  "order_edges": [
    {
      "before": "loc-013",
      "after": "loc-014",
      "basis": "page_geometry",
      "evidence_ids": ["evidence-41"],
      "state": "confirmed"
    }
  ],
  "identity_candidates": [],
  "ordered_location_ids": ["loc-013", "loc-014"],
  "review_decisions": [],
  "completion": "needs_review"
}
```

```json
{
  "unit": {
    "id": "unit-041",
    "kind": "measure_group",
    "location_id": "loc-014",
    "source_rects": [[90, 0, 740, 267]],
    "measure_count": 2,
    "break_before": "allowed",
    "break_after": "locked",
    "lock_reasons": ["crossing_annotation"],
    "staff_gap_px": 16.5,
    "safe_slack_runs": [[122, 137]],
    "prefix_asset_id": null
  },
  "page_plan": {
    "revision": 9,
    "page_px": [2480, 3508],
    "dpi": 300,
    "staff_gap_mm": 1.5,
    "pages": [
      {
        "index": 1,
        "placements": [],
        "exceptions": []
      }
    ],
    "validation": {
      "content_accounted_for": true,
      "overflow_count": 0,
      "blocking_issue_count": 0
    }
  }
}
```

**INFERRED — Use `kind="system_strip"` and `measure_count=null` for the safe strip fallback.** Store evidence objects separately with metrics, observation IDs, rule version, and reasons. IDs must survive order/crop edits; paths and list positions must not be identities.

## API and renderer behavior

**VERIFIED — Current review request accepts capture/image path lists and forbids extra fields. Current job results are a flexible dictionary. A new review contract therefore needs an explicit schema/endpoint rather than appending fields to the existing request unnoticed.** [R/backend/app/schemas.py:160–189]

**INFERRED — Add:**
- `POST /jobs/{id}/reflow-review`: revision-checked operations such as `move`, `set_included`, `link_same_location`, `unlink_location`, `set_system_bounds`, `lock_boundary`, `choose_observation`.
- `POST /jobs/{id}/reflow-export`: `{expected_revision, formats}`; server verifies all finalization gates.
- `409 REVISION_CONFLICT` for stale edits.
- `422 REFLOW_REVIEW_REQUIRED` with issue IDs for unresolved finalization.
- Job result fields: `output_model="clean_reflow_v1"`, `reflow_state`, `assembly_revision`, `systems`, `issues`, `preview_pages`, `final_revision`, `images`, `pdf`.

**INFERRED — Options:** Add `ReflowOptions` with `order_policy="source_written"`, page size, staff size, preferred measure count, and editable header. Do not expose a "raw stitch output" alternative. Cleanup settings may govern safe algorithms, but disabling a cleanup operation must not bypass quality validation.

**INFERRED — UI changes:** Update `ReviewScreen.js`, `reviewController.js`, session selectors/store/persistence, `App.js`, `ExportScreen.js`, `lib/api.js`, and Korean/English labels. Extend undo snapshots to include order, identity links, system boundaries, and observation choices.

**INFERRED — Output lifecycle:** Analysis may finish with `reflow_state="needs_review"` while final-output paths remain absent. After edits, preserve the last successful files as revisioned history and visibly mark them stale. Publish new files only after validating the new revision.

**VERIFIED — Reuse existing staged review-export commit behavior:** The endpoint renders into a staged workspace and commits only after export succeeds. [R/backend/app/main.py:981–1018]

**INFERRED — Compatibility:** Preserve legacy job files and capture selections. Opening a legacy job may show its historical files, explicitly labeled legacy; regeneration must enter the new system/reflow pipeline. Disable raw-frame copies in the final-output bundle while retaining internal evidence assets.

**INFERRED — CPU/resource policy:** Use OpenCV, NumPy, Pillow, and existing FFmpeg. Process one episode at a time; tile compositing in 256-row bands; cap decoded-image cache at 256 MB and accepted composite members at 15. Keep cancellation checkpoints between frames, episodes, and pages. Benchmark peak memory rather than claiming these limits guarantee total RSS.

---

# 6. Evaluation harness on the 18-video corpus

## What is established now

**VERIFIED — Read-only measurements:**
- 18 videos / 18 ROI entries / 18 run entries.
- 1,475 recorded candidates and 41 recorded auto-exclusions.
- Golden set: 67 captures, 100 labeled staff entries, 367 barlines.
- Running `golden.py check` returned **TP 367, FP 0, FN 0, missing staves 0**.
- An additional in-memory unmatched-detection check found **zero extra detected staff entries on these 67 inputs**.
- Detected staff gaps on that set ranged from **10.38 to 25.25 pixels**.

The inventory was computed from `rois.json`, `runs.json`, and `golden.json`; the existing scoring rule is at [C/tools/golden.py:35–54].

**VERIFIED — Important limitation:** `freeze()` stores detector output after visual checking, rather than independently entered coordinates. `check()` loops over GT staff entries and does not penalize unmatched extra detected staves. Thus the perfect result is useful regression evidence, not a complete independent accuracy claim. [C/tools/golden.py:24–32], [golden.py:38–52]

## Cheap sequence GT

**INFERRED — Label events, not individual frames or notes.**

Generate a contact sheet of:
- Stable system episodes.
- Before/after views of each transition.
- All possible revisits.
- Every excluded candidate adjacent to an apparent sequence gap.
- First/last source intervals.

For each video, assign arbitrary location IDs and mark same/different/unknown relationships. Use local playback only for ambiguous transitions. Fully label the video's episode sequence; "small GT" should mean a small number of event records, not a short easy excerpt.

**INFERRED — Suggested format:**

```json
{
  "video_id": "S1nlqQdnUks",
  "source_sha256": "...",
  "layout_intervals": [
    {"start": 0, "end": 158, "kind": "bottom_bar"}
  ],
  "locations": [
    {"id": "L01", "reference": {"t": 6.5, "bbox": [0, 797, 1920, 1080]}}
  ],
  "episodes": [
    {
      "id": "E01",
      "start": 6.0,
      "end": 15.0,
      "location_id": "L01",
      "role": "performed",
      "relation_status": "human_confirmed"
    }
  ],
  "written_order": ["L01", "L02"],
  "unknown_relations": [
    {"episodes": ["E08", "E19"], "reason": "identical_without_anchor"}
  ],
  "protected_marks": [
    {"location_id": "L01", "bbox": [990, 22, 1010, 46], "kind": "open_hat"}
  ]
}
```

**INFERRED — GT discipline:** A human must confirm identity/order labels; model-generated labels remain proposals. Mark inherently unidentifiable relations `unknown`, never force them into same/different labels. Have a second visual pass over every nonlocal merge and exclusion. No timing studies or correction-time measurements.

## Metrics and acceptance gates

**INFERRED — Initial gates:**

| Area | Metric | Acceptance |
|---|---|---|
| Location identity | False automatic merges / automatic merges, and absolute count | **0 observed false merges** on adjudicated corpus |
| Sequence coverage | Missing GT locations, including those lost through exclusions | **0 silent omissions** |
| Order | Violated confirmed adjacency/order edges; exact sequence match | **0 violations after review**, exact match where GT is determinate |
| Automatic usefulness | Resolved adjudicable identity decisions / all adjudicable decisions | Initial target **>=80%**, reported per video/layout |
| Honest uncertainty | Errors that escaped an unresolved state | **0 silent identity/order errors** |
| Clipped marks | Lost/partially clipped protected marks / all annotated protected marks | **0 accepted-output losses** |
| Cleanup | Stable notation components lost; residual overlays obscuring notation | **0 confirmed notation losses or obscured marks** in accepted outputs |
| Staff/barline detection | One-to-one staff matching, all unmatched detections counted | Preserve 367/367 legacy regression; separately score independently corrected/expanded GT |
| Cut safety | Cuts severing annotation/glyph content / accepted cuts | **0 unsafe accepted cuts**; ambiguous cuts lock |
| Unit accounting | Accepted source content missing/duplicated by layout | **0 unexplained omissions/duplications** |
| Staff normalization | Output gap deviation from selected target | <=1 output pixel; no unintended anisotropic glyph scaling |
| Justification | Right-edge error for lines marked justified | <=2 pixels; every ragged exception recorded |
| Stretch/shrink | Actual slack manipulation | Within section 4 limits, with no overflow clipping |
| Pagination | Split systems, detached labels, avoidable one-line final pages | 0 splits/detached labels; penalize and report unavoidable orphan cases |
| Format parity | Same composition in PNG/JPG/PDF | Same page count, order, header, and placements; allow encoding differences |
| Unsupported cases | Horizontal-scroll outcome before support ships | Explicit unsupported state; **0 false successful exports** |

**INFERRED — Do not hide coverage behind precision:** Report safe-cut coverage, strip-fallback rate, unresolved relationship rate, low-resolution warnings, and finalizable-video count alongside zero-error targets. A system that locks every line may be safe but has not demonstrated measure-level reflow.

**INFERRED — Dataset split:** Use six layout-diverse sources for calibration, ten remaining supported sources for a fixed evaluation pass, and the two marked horizontal sources as explicit unsupported tests. Freeze the split before tuning. Existing inspected examples are development evidence, not pristine held-out evidence.

**INFERRED — Short human visual check:** For every output, inspect page thumbnails for sequence and density, then actual-size crops of first/last systems, every uncertain join, every locked group, and all protected marks. Inspect all pilot reacquisition cases. Record pass/fail and issue location; collect no human duration measurements.

**VERIFIED — Required repository checks for implementation are documented:** backend unit tests, renderer verification, appropriate desktop-node tests, Korean/English states, and 1440x960 plus 1120x840 layout inspection. [R/AGENTS.md:17–22]

**INFERRED — Add meaningful adversarial tests:** identical grooves at different locations; exact repeated crops with ambiguous identity; numbering restart; repeat to a location older than eight episodes; short terminal display; preview-row promotion; dark playhead over a barline; clipped open-hat circle; within-staff tie crossing a cut; multi-measure rest; oversized locked group; stale review response; failed export preserving prior files.

**VERIFIED — Scope of this inspection:** Astra reran the golden detector check and performed read-only inventory/extra-staff calculations and image inspection. It did not run a new end-to-end assembly implementation, the full backend/renderer suites, or packaged macOS/Windows workflows.

---

# 7. Phased milestones for one Opus implementer

**INFERRED — Order by risk, with explicit exit criteria:**

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0. Assembly evidence and GT** | Versioned observation manifest, corpus layout override, event contact sheets, corrected evaluator, small full-sequence GT per video | Baseline error categories measurable; no mutation of corpus originals; first experiment from diagnosis completed |
| **1. Conservative systems product slice** | Episode extraction, provisional locations, system reorder/link/unlink UI, cleaned whole-system A4 composer | A reviewed song exports through `clean_reflow` only; unresolved sequence blocks finalization; all originals and prior files preserved |
| **2. Acquisition completeness and cleanup** | Full-envelope suggestions, clipping gates, alternate-observation selection, compositing coverage masks | Pilot clipped-mark cases recover through an explicitly applied ROI; no accepted obscured/clipped protected marks |
| **3. Automatic written-location assembly** | Bottom-bar resolution, page-coordinate identities, vertical-scroll maps, independent-evidence gates | Zero false automatic merges/omissions on fixed supported corpus; usefulness and unresolved rates reported |
| **4. Safe measure-level reflow** | Hardened detector port, boundary locks, prefix ownership, bounded-slack DP, page balancing | Golden regression retained; zero unsafe accepted cuts; every layout pixel-accounting/overflow gate passes |
| **5. Final-output integration and packaging** | Format parity, revisioned export, archive migration, long-title/font handling, CPU/memory profiling | Same valid chart across formats; native macOS and Windows source->ROI->review->save flow exercised |
| **6. Horizontal-scroll support** | Translation mosaics, partial-measure coverage, drift checks | Both marked horizontal sources meet the same content/order gates; otherwise remain explicitly unsupported |

**INFERRED — Shipping interpretation:** Phase 0 is a testable developer increment. Phase 1 is the earliest user-facing reflow slice because manual system decisions are explicit and the output is still a cleaned composed chart. Later phases improve automatic coverage and layout. Do not label an internal prototype as the default finished product before its exit gates pass.

**INFERRED — Implementation guardrails for Opus:**
- Inspect and preserve the current dirty worktree; do not overwrite the existing cleanup/dedupe work wholesale.
- Update `docs/DESIGN.md` with the system-review workflow before implementing its UI changes.
- Keep the existing renderer framework and visual system.
- Require a failing corpus case or invariant violation before adding another identity heuristic.
- Make every automatic merge explainable through stored evidence IDs.
- Route segmentation failure to a cleaned strip; route unresolved acquisition/identity to review or a blocked export.
- Do not optimize page count before assembly and content preservation pass.

# Open decisions for the user

**INFERRED — Recommended defaults are supplied so implementation need not pause:**

| Decision | Recommended default | Consequence |
|---|---|---|
| Meaning of "as written" | Recoverable locations of the displayed arrangement | Does not reconstruct unseen endings or compress a pre-expanded score |
| Two-page target | Soft preference | More pages are allowed to preserve readability |
| Equal-width lines | Required where safe slack permits; explicit ragged exceptions otherwise | Preserves glyph shape and annotations |
| Unresolvable identical systems | Require a same/different decision | Avoids silent musical omissions |
| Annotation policy | Preserve all score-associated text, including section labels and lyrics | May increase line height/page count |
| Low source resolution | Warning plus actual-size inspection; no invented detail | 300-dpi output is not advertised as restored resolution |
| Page numbering | Upper outer margin, numeral only | Satisfies numbering without footer text |
| Partial-song output | Only after explicit range/inclusion choice, clearly represented in document state | Missing material cannot silently become a whole-song final |
| Horizontal scroll at first release | Explicitly unsupported | The other 16 sources can be evaluated without disguising a known gap |

**INFERRED — Remaining uncertainty:** The teacher's reference PDF was described but not supplied at an identified path, so exact typography, spacing, and two-page density were not verified against that artifact. The page defaults above are implementable starting values, not a claim of a visual match.