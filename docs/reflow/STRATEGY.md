# Clean reflow: strategy reset (2026-10-07)

**Input:** an external review (ChatGPT Pro, with 12 attachments), checked by Claude. This document **overrides the per-video patching** of the 2026-10-06/07 rounds.

## Adopted

1. **Safety is a hard constraint, never a penalty.**
   - Only SAFE (or a validated "repairable" operation) cuts may be used. LOCKED and UNKNOWN cuts are never chosen, whatever the layout gain.
   - The jump-only `OVERSIZE_SPAN` rule, which split at barlines crossed by a line, slur or text, is reverted. Those cuts are LOCKED.
2. **One bounded layout model replaces the escalation tiers.**
   - Each candidate line gets a minimum, preferred and maximum width, built from rigid content plus adjustable gaps with per-gap bounds.
   - One distortion cost: mean |z|³ + 0.5·max |z|³, with |z| ≤ 1.
   - The tier-3 "extreme spread" and the "≥2 lines and ≥5%" shrink trigger are removed.
   - Staff size is chosen by one document objective. It includes short-line cost, distortion, pages and size cost, normalised per measure, with fine size steps.
   - The user's "every line full" preference is expressed through the short-line weight and the per-gap maximum, not through unbounded spread.
   - Every remaining short line records its reason.
3. **Two separate preservation contracts:** reconstruction correctness (written occurrences versus the video) and layout preservation (the PDF versus the recovered score).
4. **Evaluation base before more features.**
   - About 12 new videos: 6 validation and 6 sealed holdout, from new channels and templates.
   - Dashboard per layer: reconstruction, seams, cut safety, preservation, overlay remnants, line occupancy, gap strain, print geometry, collisions, and the share of fully acceptable charts.
5. **Overlay remnants are a defect class of their own.** Examples: the blue box in the Betelgeuse output, the yellow highlight in qA.
6. **Job lifecycle:** rebuild/export runs as a background job with progress and cancellation. Long requests do not wait on an HTTP timeout.
7. **One structural repair at a time:**
   - First: isolated hairpins drawn as proper continuation pieces, a clean system-start clef, and removal of known MuseScore non-printing markers (the boxed "↵" system break).
   - Slurs, ties and mid-measure breaks are deferred.
8. **Dense measures:** one or two measures per line is an acceptable result. A compact size comes only from the document objective, or as an explicit profile.
9. **Optional fixed-budget experiment:** Audiveris intermediate geometry (SIG/.omr) as a source of barlines and spans, about 2 days. It is judged by additional safe, useful layouts.

## Not adopted or deferred

- Audiveris or full OMR re-engraving.
- Automatic mid-measure splitting.
- General slur and tie reconstruction.
- Smooth-scroll videos.

## Order

1. Evaluation base, job lifecycle and overlay-remnant metric. (Done.)
2. Revised after the Pro checkpoint: 2A safety and coverage, 2B primary score clean (both implemented), 2C = 2C-0 visibility gaps + 2C-L minimal ledger + 2C-O bounded optimizer (see "Step 2C (in force, 2026-10-08)").
3. Hairpins, system-start clef, editor-marker cleanup and the title/header.
4. Sealed holdout run, then decide the supported scope.

**Target:** about 80% fully acceptable automatic charts within the supported source class, with 0 silent preservation failures.

## Step 1 tasks (started 2026-10-07)

**User's sources:** atthedrum, 북선생, 열드럼 (popular Korean hobbyist sheet-music channels), plus the chops channel of playlist https://www.youtube.com/watch?v=vAex-T-44o8&list=PLzUN-ga97o97AqL5mcDEoHEdVe8NZAEP5.

**User approved:** about 12 new videos, about 2 GB, at most 1440p.

- **1a. Evaluation set:**
  - Choose 12 videos across those channels and templates: line/page switch, jump view, transparent overlay, lyrics, dense chops, long spans.
  - Split: 6 validation and 6 sealed holdout, by video. Holdout videos are chosen from metadata only and never inspected during development.
  - Freeze the manifest.
- **1b. Dashboard runner:** runs the app backend on a set of videos and reports the per-layer metrics from "Adopted" item 4, including overlay remnants and per-stage time, memory and disk.
- **1c. Job lifecycle:** review export and rebuild run as a background job with progress and cancellation. The renderer polls the job and does not wait on one long request.
- **Freeze:** no new layout exceptions until Step 2.

## Checkpoints (user, 2026-10-07)

After each step, before the next one starts, send the step's results to ChatGPT Pro (relayed by the user) for a mid-course review: the dashboard table, key images, what changed and the open questions. The next step starts only after that review has been read and weighed.

## Step 1 checkpoint: Pro reply weighed (2026-10-07)

Checked against the code and `eval_v1/baseline_dashboard` before adopting.

**Confirmed in the code or the outputs:**
- `TIER3_MAX_GAP_RATIO = 3.0` lets a gap grow to 4× its natural width (`reflow_lines.py:92`). "Strain 3.00" means 4× width.
- The dashboard gate `max |strain| <= 1` uses Δ/natural, not directional cap use z. z is computed but measured against the tier caps, so a tier-3 line looks in bounds.
- The right-edge error is taken only over lines ≥ 90%. bF69 shows 0.00 mm while 25 of 26 lines stop at 87%.
- bF69's short lines come from the plan, not the renderer: planned width 0.870 of the page line, rendered 0.869, z max 0.20. `plan_document` chose an inner common edge (DECISIONS "Justified edge"). S1nl and SZwT likewise end 6–8 mm inside the margin with left insets of 5–7 mm.
- The acceptance proxy requires `measure_lines`, so a correct whole-system result can never pass.
- SZwT page 1: two consecutive systems both numbered 26, same notes, different playback highlight, then 30. Numbers in an engraved score do not repeat, so this is very likely one written system captured twice (an occurrence-identity defect). The dashboard cannot see it: validation videos have no GT. To be audited against the source.
- w7mK passes with no GT. Its pass says nothing about reconstruction.

**Adopted:** the reordered Step 2 below; occurrence identity made explicit; separate runtime coverage and independent reconstruction fields; the right-edge, cap-use and acceptance fixes; whole-system fallback may pass; per-interval jump handling under a whole-job completeness gate; overlay recovery that must keep the notation underneath; the remnant detector renamed and used as a suspicion signal only; supported scope and acceptance rules declared before the holdout is opened; reserve system-start and header/footer geometry in the layout model now; frozen strips for optimizer experiments; metric-definition version on every dashboard.

**Adjusted:**
- Fzc0-type conflicts: an automatic whole-system fallback at the largest fitting size is allowed down to the existing automatic floor of 1.2 mm (DECISIONS "Automatic staff size"), disclosed with size and reason. Below that floor it is a visible layout conflict. This extends the measure-mode floor to whole-system fallback.
- "Every line full" (DECISIONS "Fill every line") stays the product target. A line advertised as justified must reach its declared edge within 0.5 mm. The default edge is the page margin; an inner edge is used only when the bounded caps cannot reach the margin, and then it is reported with its reason, not counted as full.
- The adjudicated evidence base stays small and agent-labelled: the measure-26 passage, w7mK, the jump leftovers, and about 20 cleanup crops. The user spot-checks at most 10 doubtful items with one yes/no question. No timing studies.
- Collision and clipping checks and retained temp disk after failure or cancel are added to the per-video report, not the main table.

**Not adopted:** nothing rejected outright. A general notation-over-live-video separator stays out of scope (Pro agrees).

## Step 2 (revised, in force)

**2A. Safety, truthful completion, coverage.**
- Revert `OVERSIZE_SPAN`. Keep the old `_7g` output as a regression fixture. No LOCKED/UNKNOWN cut in an eligible output.
- No "done" without a valid placement plan and a non-empty PDF. Otherwise a specific failure or review state.
- Whole-system fallback at a fitting size (≥ 1.2 mm), disclosed; it may pass the acceptance check.
- Source class gate by input properties: opaque light paper, opaque dark paper (invertible, positive control), notation composited over live imagery (refused with evidence).
- Jump videos: each interval is handled on its own. Every leftover interval is accounted as non-score, redundant (content recovered elsewhere, identity and order known), recovered, or unresolved. Any unresolved interval makes the result visibly incomplete: labelled, with timestamps, excluded from success counts.
- Dashboard v2 (metric version 2, baseline recomputed where saved data allows): all-line signed right-edge deficit (median/P95/max, n) with target, planned and rendered endpoints; overflow reported separately; cap use z against fixed style caps as the spacing gate, Δ/natural kept as a diagnostic; "suspected colored remnants"; separate fields for runtime coverage, independent reconstruction (pass/fail/not evaluated), preservation, and visual/print; dev and validation reported separately; acceptance no longer requires measure mode.

**2B. Primary score, clean.**
- Audit the SZwT 26 → 26 → 30 sequence against the source. Default output is the written chart; merge observations of one written occurrence, keep genuinely repeated written measures.
- Primary-score vs preview ("Next" inset) region roles; preview pixels never enter the primary representation.
- Overlay recovery from other registered observations of the same content. A detector mask is never an erase mask. Acceptance: overlay gone and notation underneath preserved (crop set). No clean observation → review-required. Time-box: a few days.

**2C. Bounded optimizer on frozen clean strips.**
- First trace target vs planned vs rendered width per line (bF69, S1nl, SZwT) and fix any padding or coordinate error.
- One admissible break graph (SAFE only), min/preferred/max widths, fixed directional gap caps, one distortion cost, document-wide staff size on a fine grid, reserved system-start and header/footer geometry.
- A full-width candidate is evaluated at the target width; if the target is outside [Wmin, Wmax] the reason is recorded and another grouping or allowed size is tried. No unsupported stretching.
- Small predeclared parameter comparison on frozen strips, then a full dev + validation run.

**Exit check for Step 2 (before the Pro checkpoint):** zero successful empty exports and zero non-SAFE cuts in eligible outputs; measure-26 audited and occurrence semantics explicit; every jump leftover accounted for or the result marked incomplete; GTOc refused and a dark-paper control accepted; SZwT recovered cleanly or held for review; all-line edge and cap-use metrics with bF69 explained; optimizer comparison on frozen inputs; dev and validation separate; holdout unopened.

**Before Step 4:** write the supported scope and acceptance rules into this file, then open the holdout once. Report: complete charts among all requests, within the declared class, correct refusals, false refusals, unsupported shown as success, partial/unresolved.

## Step 2A + 2B status (2026-10-07, end of round)

- 2A and 2B are implemented. Step 2C has not started. Exit-condition status and the audit history are in `~/Documents/drum-score-corpus/advice_pack_3/00_round_summary.md`.
- Dashboard (metric definitions v2): baseline re-measured 0/12 → now dev 0/6, validation 1/6 (`eval_v1/step2_r4_dashboard`). GTOc refused correctly, Fzc0 passes, both jump videos complete, 0 non-SAFE breaks, the SZwT duplicate and the dropped m.54 line fixed. Remaining failures: layout (inner edge without a recorded reason, or edge reached only via wide/extreme caps) and suspected remnants (editor icons, thin colored separators).
- Four Codex audit rounds (gpt-6.1-sol, xhigh) found 18 issues, 16 of them silent-loss paths on synthetic counterexamples; all fixed with regression tests (backend 758). One fix regressed bF69 (26 → 43) and was corrected.
- Next: the Pro checkpoint (`PRO_CHECKPOINT_STEP2AB.md`). Proposed for discussion: an end-to-end source-to-output ink ledger instead of more local patches, then 2C.
- Open, not yet traced to code: source-cut lines (aOED lyrics cut by the video frame itself) should be flagged through to review and output.

## Step 2 checkpoint #2: Pro reply weighed (2026-10-08)

Checked against the code and `eval_v1/step2_r4_dashboard` before adopting.

**Confirmed in the code or the outputs:**
- The line block is centred (`reflow_measure.py:1260`, `x_offset = (content_w - edge) // 2`). The width a line is missing is therefore twice the right deficit: SZwT/aOED 170 px = 14.4 mm, S1nl 135 px = 11.4 mm, bF69 276 px = 23.4 mm, 01Mr 37 px = 3.1 mm (plan widths 1956 / 1991 / 1850 / 2089 of 2126 px).
- So uniform enlargement of the same grouping would fill the line: SZwT/aOED at 1.63 mm, S1nl at 1.60, 01Mr at 1.53, bF69 at 1.72. The reference teacher gap is ≈ 1.6 mm (DECISIONS line 17); the search so far only went down from 1.5.
- The tier-1 expansion cap is `max(0.35 g0, 0.6 s)` (`reflow_lines.slot_caps`): a tiny corridor gets a large absolute allowance. The contraction cap is already clamped at 0 (Pro's negative-capacity concern does not apply to the code).
- Dashboard runtime coverage returns "passed" when the job carries no coverage record and no failure (`coverage_metrics`, last line). Missing evidence counts as success.
- Independent reconstruction is a count only. Right-edge "rendered" is the rightmost ink anywhere in the band, which an editor icon or hairpin can satisfy. The final line is reported apart from the full-line rule, although DECISIONS "Spread justification" says the last line is included.
- Explicit size: the API treats a request of exactly 1.5 mm with no mode flag as automatic (`schemas.resolve_staff_gap_mode`); the renderer sends no mode flag.
- The delivered PDF embeds 300 dpi JPEG pages (`export.py:854`). Rasterising it at 600 dpi adds no information.

**Adopted:**
- Status wording: 2A/2B implemented; the "no silent loss" exit condition stays open until the known uncertainties are visible in the result.
- Ledger, with Pro's protection rule: evidence classes (repeated aligned → protected; credible but seen in few clear observations → preserved or unresolved alternative; ambiguous → explicit disposition before destructive cleanup), not "majority = protected". High-confidence label: ≥ 80% of eligible observations across ≥ 3 separated groups; obscured observations leave the denominator. Evidence items, not component ids; obligations taken before any destructive step; both directions checked (source → output and output → source); explanations need evidence; three outcomes pass / review required / fail; mutation tests from the earlier audit findings; time-boxed.
- Close the known visibility gaps first: minority thin strokes and translucent-plate gray are preserved or flagged, never silently erased; jump finishing diagnostics reach the record; source-cut lines carry `SOURCE_CLIPPED` to review and the PDF (local mark + page-1 summary); explicit size is a mode sent by the UI.
- Scope: translucent dark plates leave the clean-complete class (conditional / review). Unknown source class never passes by fall-through.
- 2C experiment as proposed: caps A and B (min-form joint ceilings, barline packages budgeted on both sides together), objective J with λU ∈ {4, 8}, size grid 1.20–1.60 mm in 0.025 steps with no penalty in 1.50–1.60, three near-best break plans per size paginated with real geometry, the four configurations A1/A2/B1/B2 on frozen dev strips, the hard pass rules, selection by common output metrics (not J), stop rules. No centring. Corridor eligibility 0.25 s vs 0.6 s as the one ablation if needed.
- Dense jump charts: 1–2 measures per line allowed, compact size when it materially helps, no 4× gaps, each remaining short line with numerical feasibility evidence. Z4eb's isolated short lines need a specific diagnosis.
- Dashboard v3: runtime coverage "unassessed" without evidence; reconstruction checks ordered occurrences against GT; line endpoint = staff end, both left and right endpoints, missing width = target − (right − left); final line under the same rule; |z| ≤ 1 in the contract; separate fields "content accounted", "complete vs source-limited/review", "target layout achieved", "usable with declared compromises" — a reason string never turns a short line into a full one.
- Process: each audit finding records supported-input assumption, violated invariant and required response; pivotal findings keep small raw crops, timestamps, transforms and hashes.
- Written-chart semantics written down (see DECISIONS): output = the sequence of displayed written occurrences in video order; a display left and later shown again is placed again; one display seen in several observations is placed once.

**Adjusted:**
- Ledger output check reads the page images embedded in the delivered PDF (300 dpi JPEG) instead of rasterising at 600 dpi. Native accounting through cuts and joins stays exact (already in `reflow_measure`); the page check uses the predicted footprint with ≈ 1 output px placement tolerance and a contrast test robust to JPEG.
- Ledger first version is minimal: obligations from the display composites' unmasked members (foreground before cleaning, plus minority evidence), transforms already recorded by strips and the page plan, the delivered PDF. A second registration chain from raw frames is not built.
- Enlargement is searched in the same grid (up to 1.60 mm, and the planner records the size that would make the current grouping full when it lies above 1.60).

**Not adopted:** nothing rejected. Pro's numbers are experiment settings; one cap policy is kept globally after the experiment.

## Step 2C (in force, 2026-10-08)

1. **2C-0 Visibility gaps and metrics.** Minority thin strokes and translucent-plate gray: preserve or flag. Jump finishing diagnostics into the record. `SOURCE_CLIPPED` per line through review and PDF. Explicit size mode from the UI. Dashboard v3 (above). Baseline r4 re-measured under v3.
2. **2C-L Minimal ledger.** Evidence-item schema and transform contract, verifier on the delivered PDF, mutation tests (missing dot, gray dynamic, excluded display, duplicate + loss, false chrome exemption) and controls (scaling, cursor recovery, genuine repeats). Runs alongside 2C-O; gates "complete" claims (pass / review required / fail).
3. **2C-O Bounded optimizer.** Frozen strip packages of the six dev videos; caps A/B; objective J; size search with enlargement; no centring; four configurations; hard pass rules; pick by output metrics; then one validation run.

**Exit check for Step 2C (before the next Pro checkpoint):** no known uncertainty disappears silently (each gap above closed or flagged); ledger catches all mutation tests and passes the controls; optimizer comparison done with a chosen policy or a recorded capacity limit; dashboard v3 on dev + validation; holdout unopened.

## Step 2C checkpoint #3: Pro reply weighed (2026-10-08)

Not yet re-checked against code beyond what the round already measured; items marked (verify) are checked at the start of the work.

**Adopted:**
- B2 is not promoted and Step 2C is not closed. Headline corrected: on the five charts both planners render, B2 and legacy both give 114 lines / 11 pages; B2 53/114 full vs legacy 0/114 under the both-endpoint rule; legacy's extra 74 lines / 5 pages are all `_7g`. Spacing distortion is the real gain (legacy Q8 8.47 mm gap change vs B2 ≤ 1.27 mm).
- The per-short-line fee (λU·1(d>0.5)) was the wrong shape: it makes one half-empty line cheaper than several slightly short ones. Replace with φ(u) = 20u² + 200u⁴ on planned staff endpoints; other J terms unchanged.
- 85% minimum fill on every line (final line included) for an automatically usable layout; a reason never waives it. Fillable groups are still justified to full width. The 85% check runs on the complete break graph per staff size before the three near-best paths are taken; if no complete path meets it, keep a review draft chosen by min-max deficit per size, then J.
- Staff target 15–195 mm (180 mm staff) and a separate permitted ink extent 12–198 mm for identified external overhangs (measure numbers, brackets). Place the staff start at 15 mm; the prefix hangs left of it. Endpoint tolerance stays 0.5 mm. No empty staff extension to pass the metric. Fixed before the next experiment.
- `_7g`: no per-group shrink, no document below 1.20 mm (absolute floor for primary content; 1.50–1.60 preferred; < 1.40 = declared compact). Current outcome = review/refusal. Adjudicate `bar@2576`, `bar@4774`, `bar@5300` at full source resolution (time-boxed); a verified hairpin may justify the first structural continuation operation (Step 3), a crossing word or unknown edge stays indivisible.
- Uncertain marks: one bundle per system is the right review organisation, not a clean steady state. Report unresolved hypothesis counts, not just bundles; every hypothesis reachable in review (incl. excluded candidates). Cut-veto footprint = possible mark location + registration uncertainty + pixels the cut/trim touches, with connected text/spans. Cursor identity ≠ underlay recovery: recovery needs two agreeing unoccluded observations at different cursor positions with ≤ 0.5 native px residual registration; partial recovery discharges only the recovered part. Translucent plates stay review-only (optimizer may make a preview).
- Ledger: wire now, before more layout work. Add hook 0: immutable inventory of every sampled raw ROI observation before identity comparison, rejection, duration filtering, cropping, fade/registration rejection (ids, timestamps, hashes, full owned ROI, lossless evidence, later associations, visibility/registration state, disposition). Later hooks annotate it. Terminal dispositions limited to: preserved / recovered beneath overlay / equivalent observation / non-score material (localised positive evidence) / source-limited / unresolved. Verifier must not rely only on the production foreground mask. Output→source accounting too.
- Release contract that ends open-ended audit rounds (all must hold): inventory completeness; supported discharges; two-way accounting incl. duplicate+loss; export enforcement in both paths (absent/skipped/failed verification → no clean claim); delivered-page verification; evidence retained and reachable; all known counterexamples closed. Frozen regression matrix over both export paths and both reflow modes, with positive controls and at least one real opaque-source end-to-end clean pass. After that, new failures are ordinary defects.
- Validation videos are "monitored" from now on (seen three times); report the protocol plainly. No fresh validation set needed for R0/R1/R2. Freeze scope, layout/size policy, ledger and qualification versions, definitions, denominators and report template before the holdout.
- Reconcile the cap ratio (aOED corridor relative change 0.6576 under B / 0.652 under A vs stated joint caps 0.60 / 0.40): show natural width definition, corridor type, cumulative delta, per-side and joint budgets, scale conversion, ratio numerator/denominator (verify).
- Report best attainable deficit vs selected deficit per chart (bF69: bound 11.60 mm, selected 16.93 mm).
- The v3 dashboard of r4 is not an integrated product result; next phase has one owner and one build manifest.
- Render a real aOED page with SOURCE_CLIPPED summary and local marks (crowded lyric/label system) as the presentation check.

**Adjusted:**
- Delivered-PDF check: our PDF is written by Pillow (one JPEG image per page). First enforce a narrow format contract checked independently (page boxes = A4, exactly one image XObject drawn full-page with the expected matrix, no clip path, no other content), then compare the extracted image. Add an independent renderer (e.g. pypdfium2) only if the contract cannot be checked reliably; no new dependency is added without need.

**Not adopted:** nothing.

## Step 2D plan (in force after checkpoint #3; work not started)

Order. One integration owner, one build manifest per phase. Workers: Codex gpt-6.1-sol high; audits xhigh.

1. **Ledger integration and review access.**
   - Hook 0 (pre-tracker raw inventory) + producer hooks 1–5 (`LEDGER.md` ~346), annotating hook 0.
   - Typed terminal dispositions; verifier independent of the production mask; output→source accounting.
   - Delivered-PDF format contract + page check in both export paths on the staged deliverable.
   - Review UI: every hypothesis reachable (raw witness vs primary at the same scale, timestamp, occurrence, status), hypothesis counts reported.
   - Veto footprint with registration uncertainty; cursor underlay recovery rule (two observations, ≤ 0.5 px).
   - Release-contract regression matrix incl. the 7 audit-5 cases; positive control: at least one real opaque dev video passes end-to-end clean (01Mr or S1nl).
   - Exit: release contract items 1–7 demonstrated; review burden reported per dev video (hypotheses, bundles, SAFE/UNKNOWN, pages).
2. **Geometry and accounting fixes.** Staff target / ink extent model (15–195 / 12–198 mm), staff start at the margin; cap-ratio reconciliation; best-attainable vs selected deficit reporting. Re-freeze dev packages (versioned) if ledger work changes protection or boundary metadata.
3. **R0 / R1 / R2 on frozen dev packages.** R0 = B2 + step-2 fixes; R1 = φ(u) without the guard; R2 = φ(u) + 85% guard on the complete graph. Caps B, size grid, pixels, boundaries, page and size costs fixed. Selection order: safety/preservation/cap/geometry → requests with a complete ≥ 85% path → worst deficit and tail on matched outputs → staff size, gap change, pages → full-line fraction. Stop after this comparison; if the guard is unattainable, record it per chart.
4. **`_7g` boundary adjudication** (time-boxed): identify the objects at the three boundaries. Verified hairpin → first structural operation in Step 3 (positive span type/anchors, exact mask, replacement geometry, provenance, collision + ledger recheck). Otherwise `_7g` stays review/refusal.
5. **Integrated monitored run** (dev + monitored validation) on one manifest with dashboard v3; real aOED source-clipped page check; then Step 3 (editor markers, hairpin op if justified, system-start clef, header), freeze scope/policies/definitions, then the holdout once.
