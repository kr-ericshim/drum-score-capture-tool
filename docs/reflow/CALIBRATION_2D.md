# Stage C frozen calibration (WC, 2026-10-09)

Contract: `LEDGER_2D_INTERFACE.md` §12.5–12.6. Fixture version: `wc-motifs-1`.
The constants below were measured and frozen **before** the dev-video comparisons.
No dev-video-specific thresholds or branches are used. Owned implementation:
`backend/app/pipeline/reflow_verify_page.py`; fixtures: `test_verify_calibration.py`.

## Frozen profiles

Residual is the absolute difference in the shared local contrast space, before
the 3×3 residual test. The prescribed rule is `epsilon = max benign + 2`.

| Profile | epsilon | Fit benign maximum | Held-out maximum | Held-out result |
|---|---:|---:|---:|---|
| lossless-gray | 2 | 0 | 0 | PASS, 16,800/16,800 |
| lossless-rgb | 2 | 0 | 0 | PASS, 16,800/16,800 |

For **each profile**, 10,080 fit cases and 16,800 held-out cases were run, 26,880
in total. Each profile measured 740,544,000 page pixels, all with residual zero.
The matrix contains 20 motifs × gaps 7/9/12/16 × phases 0/.25/.5/.75 × area/cubic
× contrasts 32/48/64/96/128/192/255 × widths 1/2/3 × two integer placements
`(8,9)` and `(19,17)`. Phase .75 **or** the second placement is held out. The fit
uses only the first placement and phases 0/.25/.5. Widths are native stroke
widths; delivered gaps come from resizing the 16-pixel native gap.

Motifs: isolated dot, staff-attached dot, thin stroke, stem/beam junction,
X notehead, repeat dots, quarter rest, eighth rest, numeral, gray dynamic,
lyric fragment, staff-only segment, barline, double barline, open notehead,
accent, staccato, tie, ledger note, flag. Near-gray chromatic ink (up to 11
levels of channel difference) is included. A fractional translation of the
native motif exercises each phase; all resize sizes/placements remain integral.

The production side uses the actual `reflow_render._to_page_paper`, OpenCV
resizing with the declared kernel, `reflow_measure._place`, and the actual final
`resize_strip`/paper conversion. Explicit kernels exercise both area and cubic
at every gap, including cubic shrink (the ordinary production chooser would
select area there). The independent side calls `render_expected`, which imports
no rendering functions from `reflow_measure` or `reflow_render`. Both use the
recorded pixel-centre matrices, integer sizes and placements. Gray/RGB page
pixels make a Flate encode/decode round trip. Full A4 PDF grammar and the actual
production lossless writer are tested separately in `test_verify_page`.

## Destructive controls

Every variant is detected for **both** accepted profiles. Detection here means
a fail with the expected mutation-specific code, not an unrelated fidelity
review. Native controls span all seven contrasts and all three stroke widths;
resize controls span four gaps, four phases and both kernels at contrast 128,
width 3, on the held-out placement. This is the stated sensitivity denominator;
it does not claim mutation coverage over the entire benign Cartesian matrix.

| Destructive variant | Gray detected | RGB detected | Expected code |
|---|---|---|---|
| Erased isolated dot | yes, 21/21 native + 32/32 resized | yes, 21/21 + 32/32 | DELIVERED_FEATURE_MISSING |
| Erased staff-attached dot, staff retained | yes, 21/21 + 32/32 | yes, 21/21 + 32/32 | DELIVERED_FEATURE_MISSING |
| Removed thin branch/beam segment | yes, 21/21 native + 32/32 junction | yes, 21/21 + 32/32 | DELIVERED_FEATURE_MISSING |
| Removed gray dynamic | yes, 21/21 native + 32/32 resized | yes, 21/21 + 32/32 | DELIVERED_FEATURE_MISSING |
| Duplicated feature | yes, 21/21 | yes, 21/21 | DELIVERED_EXTRA_INK |
| Piece shifted 2 px | yes, 21/21 | yes, 21/21 | PLACEMENT_MISMATCH |
| Altered committed strip evidence | yes, 21/21 | yes, 21/21 | ARTIFACT_MISMATCH |
| Altered PDF placement command | yes, 1/1 | yes, 1/1 | PDF_CONTRACT |
| Wrong PDF render profile | yes, 1/1 | yes, 1/1 | PDF_CONTRACT |

Total destructive controls: 554/554. Stage A's hook-0 frame-evidence integrity
belongs to WA; WC's altered-evidence control checks the committed strip hash.
Additional page tests reject a corrupt generated template and a template whose
self-hash was updated but whose Stage B commitment was not. A 1-pixel line
offset passes; a 2-pixel offset fails. Erasure of a feature by the approved area
resize yields `OUTPUT_FIDELITY` review even when E equals D.

## Certificate and integration contract

`verify_pages(cert_b, strip_pngs, pdf_path, *, generated, profile, pages=None)`
accepts `lossless-gray` and `lossless-rgb`, or `lossless` to select the frozen
profile separately for each decoded page (including mixed gray/RGB PDFs).
PDF pages must be A4 portrait,
2480×3508, one 8-bit DeviceGray/DeviceRGB Flate image per page, one full-page
image command, no clipping/annotations/rotation/masks or auxiliary graphics.
Pillow parses PDF objects; WC independently decompresses and validates the
Flate raster. Certificate page hashes cover the decoded gray/BGR arrays.

`pages=` is expressly a diagnostic/test transport, requires `pdf_path=None`,
sets `pdf_contract_checked=false`, and has no PDF hash. It proves only the page
comparison, not the PDF container or installation. Real PNG experiments use
this transport because their PNGs are the supplied lossless delivered rasters.

WC accepts WB's `plan_records`, re-hashes it against `plan_sha256`, and checks
that all instance transforms and generated records match its committed records.
It reads the page size from that payload. Features come from WB's forwarded
`features: {strip_id: [certA feature, ...]}`. Missing features yield
`VERIFICATION_INCOMPLETE` review; unbound generated records yield
`GENERATED_ORIGIN_UNBOUND` review. The small synthetic/test adapter can instead
provide `page_px` and `generated_sha256`. It is not a substitute for Stage B.
Forward **all** A features, including unsupported ones. C independently rebuilds
the shared feature geometry and compares the strong/weak mask unions, enforces
local tile sizes, and rejects duplicate IDs or altered geometry as
`ARTIFACT_MISMATCH`; a tampered mask cannot silently suppress a page obligation.

## Reproduction and initial verification

```
PYTHONPATH=backend:backend/tests backend/.venv/bin/python -m unittest test_verify_page test_verify_calibration test_verify_common test_measure_staff_continuity
```

Before dev-video diagnostics: `Ran 27 tests in 53.507s`, `OK`.
The benign matrix took 38.084 s. Logs and machine-readable frozen results are
`/tmp/wc/tests-owned.log`, `/tmp/wc/calibration-benign.json`, and
`/tmp/wc/calibration-destructive.json`.

The separately requested combined run including `test_ledger_measure_e2e`
reported `Ran 38 tests in 62.041s`, `FAILED (failures=14, errors=1)`.
All failures/errors were in that old integration module: the newly landed
lossless writer is rejected by the old JPEG verifier as
`DELIVERED_PDF_UNASSESSED`, and the below-floor partition test raises
`StopIteration` while seeking a representation. Those assertions were not
changed. Log: `/tmp/wc/tests-requested.log`. Lead integration must retire the
old PDF path and investigate that separate partition fixture failure.

## Scope and limits

- This freezes pixel residual tolerances, not a claim that every thin rendered
  motif is legible. Qualified source-feature survival remains a separate review
  gate. Weak or shrunken motifs can legitimately trigger `OUTPUT_FIDELITY`.
- Calibration checks maximum residual over every benign page pixel. It does not
  promote synthetic support records into real hook-0 observation evidence.
- C trusts Stage B's authorisation of replicas/removals; it checks the committed
  replay and delivery. The job result must compose inventory, A, B and C findings.
- Residual grouping is after local testing. Components do not dilute the test.
- The feature counterfactual uses phase-preserving local separable area/cubic
  kernels; random controls show at most 1 gray-code rounding difference from
  full OpenCV resize. It keeps the approved whole-strip/line paper estimates
  fixed, so removing a feature cannot globally change the paper estimate.
- The installation hash check and packaged application/media workflow belong
  to the lead integration step and are not certified by these source tests.

Dev-video findings and performance will be added below without changing the
frozen epsilon or fixture matrix.

## Final owned verification

The reproduction command above, with the final implementation, reported
`Ran 31 tests in 40.803s`, `OK`. The benign matrix took 32.383 s in that run;
fit/holdout maxima and epsilon were unchanged. Log:
`/tmp/wc/tests-owned-final.log`. New controls also cover forwarded feature-mask
tampering, recorded `column_repeat` scaffold replicas, a scaffold donor cache
later used for source obligations, WB plan-record binding, and a mixed gray/RGB
PDF from the current production writer.

```
PYTHONPATH=backend:backend/tests backend/.venv/bin/python -m unittest test_ledger_measure_e2e
```

Final requested old integration run: `Ran 13 tests in 12.439s`,
`FAILED (failures=14, errors=1)`, for the unchanged reasons described above.
Log: `/tmp/wc/tests-existing-final.log`. The failure count includes subtests.
No full backend suite was run. Runtime was Python **3.13.4**; all three owned
Python files also parsed successfully with Python 3.12 grammar. A Python 3.12
runtime execution was not performed.

## Real saved-artifact diagnostics

Inputs were only `/tmp/wd3_jobs/<video>/strips/`, the saved
`/tmp/v1_e2e/<video>/sink.json` and `plan.json`, and its supplied
`images/page_*.png`. No video was recaptured and no corpus files were written.
The adapter builds instances from saved placements, including declared
one-column scaffold replicas (`column_repeat`). It assigns IDs in the same
style as WA, because the shared helper's temporary IDs can collide (see lead
request below). Native feature geometry is real, but supporter lists are empty
and no A/B validity verdict is fabricated. Fidelity findings below are
**candidates pending real A qualification/B ownership**, not confirmed human
legibility failures. Page comparisons certify only the replay of saved records.

| Video/page | PNG comparison seconds | E vs delivered PNG | OUTPUT_FIDELITY candidates | DELIVERED_EXTRA_INK | Other delivery/seam codes | Compact cert bytes |
|---|---:|---|---:|---:|---|---:|
| S1nlqQdnUks / 1 | 0.813 | pixel-identical | 167 | 0 | none | 46,754 |
| S1nlqQdnUks / 2 | 0.579 | pixel-identical | 128 | 0 | none | 35,355 |
| 01MrRtwZgoE / 1 | 1.771 | 2,263 changed gray pixels | 612 | 40 | none | 165,051 |

There were **zero** `DELIVERED_FEATURE_MISSING`, `PLACEMENT_MISMATCH`, or
`STAFF_SEAM` findings in these three PNG comparisons. All 2,263 changed gray
pixels in 01Mr are darker in the delivered raster, and **all 2,263 lie outside
every declared placement piece and generated-template footprint**. Thus there
is an exact saved-record provenance gap; C does not waive it. The larger
examples are staff strokes across expected paper gaps. This does not establish
that the video acquired an extra notation mark. Mutation sensitivity is measured
above; human precision and the real-job false-blocking rate were not measured.

Examples (left expected, right supplied delivered, original pixel coordinates):

- `/tmp/wc/01MrRtwZgoE/page_0001-DELIVERED_EXTRA_INK-1.png`, bbox
  `[1258,1178,1283,1185]`; examples 2 and 3 are beside it.
- `/tmp/wc/S1nlqQdnUks/page_0001-OUTPUT_FIDELITY-1.png`; two more per code/page
  are beside each report.
- `/tmp/wc/01MrRtwZgoE/extra-ink-provenance.json` contains every extra-ink bbox
  and the independent covered/uncovered changed-pixel counts.

Independent expected rendering took **0.136 s for S1's two pages** and
**0.148 s for 01Mr's one page**. The saved adapter has 19,425 and 15,029 source
feature tiles respectively; its JSON sizes are 3,558,053 and 2,975,925 bytes.
Decoded strip arrays total 25,461,924 and 21,085,983 bytes. Metadata sizes do not
include input evidence pixels. Full results: `/tmp/wc/real-summary.json` and
per-page reports under `/tmp/wc/<video>/`.

### Actual lossless PDF transport

The current WP `_write_composed_pdf` wrote the supplied delivered PNG rasters to
new **scratch-only** `/tmp/wc/<video>/lossless-delivered.pdf` files. C decoded and
verified those exact files with `profile="lossless"`; their container checks
passed, all embedded pages were DeviceGray, and findings matched the PNG runs.
These are controlled transport experiments, not installed application exports.

| Video | PDF pages | PDF bytes | Write seconds | C verify seconds, including PDF decode/hash | Average verify seconds/page | Compact cert bytes |
|---|---:|---:|---:|---:|---:|---:|
| S1nlqQdnUks | 2 | 823,449 | 0.772 | 1.272 | 0.636 | 81,682 |
| 01MrRtwZgoE | 1 | 395,177 | 0.355 | 1.653 | 1.653 | 165,057 |

S1 PDF SHA-256:
`c35a20b834026d87781407e3815c0ca13d38062695b2466d7553330fd7a8f1c7`.
01Mr PDF SHA-256:
`c7b86ca07ae9b19c8ccc1aacaf31c76dd97a725048c92fdef4d2d9d5dcd4ff49`.
Reports: `/tmp/wc/lossless-pdf-summary.json` and
`/tmp/wc/<video>/lossless-pdf-report.json`. Original saved JPEG PDFs were also
checked and correctly yielded `PDF_CONTRACT` because they contain DCT images.

### Memory and performance limits

The <=2 s/page target was met for all three final PNG page runs and for the
scratch PDF comparisons above. This is a measurement on these inputs, not a
worst-case bound. Initial slower runs motivated caching validated geometry and
phase-correct support boxes, local counterfactual windows, identity-resize fast
paths, and generated scaffold donors. No pixel threshold changed.

A fresh 01Mr page process used 1.850 s and had peak RSS **569,982,976 bytes**
(543.6 MiB). The process high-water mark before C was 161,513,472 bytes, so the
high-water mark grew by 408,469,504 bytes (389.5 MiB). This is not an exact
measurement of C's incremental peak allocation. The combined two-job process
peaked at 679,084,032 bytes (647.6 MiB). The overall 512 MiB **extra** budget is
therefore not independently established by these RSS measurements. Evidence
and findings were not dropped to fit a memory/metadata target.

## Requests for the lead (exact anchors)

1. `backend/app/pipeline/reflow_pipeline.py::_verify_delivered_ledger`, currently
   calling `rl.verify_pdf` around line 1147: wire A/B/C and compose their findings
   with inventory/terminal outcomes. Pass WB `plan_records`, all A features,
   committed strip PNGs and generated origins; use `profile="lossless"` for WP's
   per-page color selection. Neither saved adapter nor `pages=` is a production
   certificate. Keep the old assertions until integration has a valid replacement.
2. `backend/app/main.py::_install_staged_export_workspace`: compare the staged
   PDF file hash with `certC.pdf_sha256` immediately before installation; install
   that same verified file. Installation/packaged-media flow was not exercised.
3. `backend/app/pipeline/reflow_measure.py::_ledger_line_records`, especially
   `_exclude_boxes(stage, changed)` around lines 943–946, and `_declef_join`
   around line 307: investigate the 01Mr unrepresented staff strokes. Declare
   exact source/generated footprints for authorised restoration, rather than
   treating the 40 C findings as waived ink. The saved artifact proves the gap;
   the producer operation responsible still needs tracing by the lead.
4. `backend/app/pipeline/reflow_verify_common.py::strip_features`, lines 63–72:
   `key/ys/xs` are reordered, but the temporary ID reads unreordered `lab[a]`.
   Retain/reorder the corresponding label before ID construction and add an ID
   uniqueness check. Current real inputs have 78 colliding ID groups across
   15 S1 strips and 27 groups across 15 01Mr strips. Evidence:
   `/tmp/wc/shared-feature-id-collisions.json`. WA already replaces those IDs
   with indexed IDs; WC's test adapter now follows WA. The shared file was not
   edited and C refuses duplicated forwarded IDs.
5. `backend/tests/test_ledger_measure_e2e.py::test_sub_floor_partition_child_is_proven_without_page_obligation`,
   the `next(...)` around line 154: investigate why the assembled representation
   lacks `below_contrast_floor`. This is separate from JPEG-vs-Flate rejection;
   WC did not change the assembler or this assertion.
