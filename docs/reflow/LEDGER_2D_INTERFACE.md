# Step 2D-1: ledger interface contract (lead, 2026-10-08)

This is the shared contract for the Step 2D item 1 workers. Read it together with [LEDGER.md](LEDGER.md) (existing API, evidence, transform and disposition contracts) and STRATEGY.md "Step 2C checkpoint #3" and "Step 2D plan". Where this file and LEDGER.md differ, this file wins.

Every worker owns a disjoint set of files (see the bottom of this file). Producers do **not** call each other. They return ledger fragments and transform stages in fixed record keys. The integration phase (2D-1b) merges them in `reflow_pipeline.py` / `main.py`.

## 1. Ledger shape (version `display-ledger-2`)

```python
{
  "version": "display-ledger-2",
  "source_video": str,
  "observations": [ObservationRecord],      # NEW, hook 0
  "displays": [...],                         # as in v1
  "items": [...],                            # as in v1 (+ optional partition fields, §5)
  "representations": [...],                  # as in v1
  "dispositions": [...],                     # item-level, as in v1, each gains "terminal" (§3)
  "display_dispositions": [DisplayDisposition],  # NEW (§4)
  "generated_origins": [...],                # as in v1
  "occurrence_remaps": [Remap],              # NEW (§6)
}
```

A **fragment** has the same keys; any key may be missing or empty. `merge_ledgers(*fragments)` (in `reflow_ledger_assembly.py`) concatenates every list field, refuses duplicate ids per list (`items[].id`, `displays[].id`, `observations[].id`), and keeps the first `source_video` (it raises if two differ).

`record_obligations(...)` keeps its v1 signature. It now stamps `display-ledger-2` and returns the new keys as empty lists.

## 2. Hook 0: observation inventory (`ObservationRecord`)

This record is built from the manifest **immediately after `ob.build_manifest`, before `stk.build_episodes`**. Every sampled observation gets one record, whatever happens to it later.

```python
{
  "id": "obs-000123",                 # manifest observation id
  "t_sec": float, "sample_kind": "coarse"|"fine",
  "frame_path": str,                  # absolute path of the stored PNG at inventory time
  "frame_png_sha256": str,            # sha256 of the PNG file bytes
  "pixels_sha256": str,               # reflow_ledger.pixels_hash(decoded image)
  "crop_size": [w, h], "native_crop_size": [w, h] | None, "work_scale": float,
  "source_to_crop": [...], "applied_roi": [[x,y]...], "roi_revision": int,
  "staff_regions": int,               # len(system_regions) at inventory time
  "foreground_px": int,               # raw photometric foreground count (same MIN_CONTRAST rule as record_obligations, polarity by median)
  "associations": [Association],      # appended by later stages, never rewritten
  "terminal": TerminalDisposition | None,   # set once, by finalize_terminals (§3)
}
```

`Association` (append-only):

```python
{"stage": "tracking"|"occurrence"|"composition"|"jump"|"selection",
 "display_id": str | None, "occurrence_id": str | None,
 "role": "member" | "offered" | "used" | "rejected_fade" | "rejected_registration"
         | "duration_filtered" | "excluded_candidate" | "covered_by_kept_display"
         | "transient" | "unassigned",
 "reason": str | None}
```

`frame_path` evidence must survive `prune_frames`. The integration phase copies a pruned frame into `<workspace>/ledger_evidence/<pixels_sha256>.png` before deletion when its observation's terminal is anything other than `non_score_material` with `foreground_px == 0`.

## 3. Typed terminal dispositions

There are exactly six terminals. Each one names the evidence it requires. A terminal without its required evidence is invalid.

| terminal | applies to | required evidence | verifier outcome |
|---|---|---|---|
| `preserved` | observation, item | the item has ≥1 representation; observation: ≥1 association with role `used`/`member` in a display whose items are represented | checked on the delivered page; loss → `fail` |
| `recovered_beneath_overlay` | item (observation via its items) | the existing `cursor_recovery` disposition evidence, **plus** `recovery`: ≥2 agreeing unoccluded observations at different cursor positions, `residual_registration_px` ≤ 0.5 (native px) for each; `recovered_mask` (packed) ⊆ hypothesis | missing/insufficient → `review_required`; only `recovered_mask` pixels are discharged, the rest stays an open obligation |
| `equivalent_observation` | observation, item, display | item: v1 `overlap_duplicate`; display: a `DisplayDisposition` (§4) | containment fails → `fail` |
| `non_score_material` | observation, item | localised positive evidence: observation → `{"staff_regions": 0, "detector_version": str, "frame pixels_sha256"}` **and** the observation lies outside every episode; item → v1 `chrome`/`preview_inset` exclusion-mask evidence | evidence missing → `review_required`; mask touches source hypothesis → `fail` |
| `source_limited` | observation, item | `reason` ∈ {`fade_transition`, `registration_out_of_range`, `source_clipped`, `outside_requested_range`} **and** the measured value that triggered it (`paper_drop`, `shift_px`, ...) | always `review_required` unless reason is `fade_transition` and every pixel of that observation's hypotheses is also `preserved` via another observation of the same display |
| `unresolved` | observation, item | v1 `unresolved_alternative` evidence (artifact decodes to the raw hash) | always `review_required` |

Every existing item-level disposition kind gains a `"terminal"` field with this mapping:
`cursor_recovery`→`recovered_beneath_overlay`, `overlap_duplicate`→`equivalent_observation`, `staff_scaffold`→`preserved`, `chrome`/`preview_inset`→`non_score_material`, `structural_replacement`→`unresolved` (until Step 3), `unresolved_alternative`→`unresolved`. An item with no disposition and ≥1 representation is `preserved`.

`finalize_terminals(ledger)` (assembly) derives each observation's terminal from its associations and item outcomes, in this order. If any of the observation's foreground lies in an item that is `unresolved`, the terminal is `unresolved`. Otherwise, if any of it lies in a `source_limited` item, the terminal is `source_limited`. Otherwise it is `preserved` / `recovered_beneath_overlay` / `equivalent_observation` when all its items are discharged that way, using the first of these in that order when they are mixed. An observation with **no association at all** is `non_score_material` only when its evidence qualifies (staff_regions == 0). Otherwise it is `unresolved` with role `unassigned`.

The verifier (`verify_pages`) adds:
- `OBSERVATION_WITHOUT_TERMINAL` (review_required): an observation's terminal is None or not one of the six.
- `TERMINAL_EVIDENCE_MISSING` (review_required): the terminal lacks the evidence the table requires.
- `PRESERVED_NOT_DELIVERED` (fail): an observation or item is marked `preserved` but has no checked representation.
- `report["terminal_counts"]`: counts per terminal, separately for observations and for items.

## 4. Display-level equivalence (`DisplayDisposition`)

A deliberate user omission has `{"kind": "user_excluded", "terminal": None, "display_id": str, "system_id": str}`. Only systems explicitly unchecked by the user qualify; pipeline-excluded candidates do not. Its unplaced items are not expected on delivered pages and do not change verification status; the report counts them in `user_excluded = {"displays": n, "items": m}`.

This is for excluded duplicate displays: covered candidates, overlap regions of jump panoramas, and repeated reads of the same written display.

```python
{"kind": "display_equivalent", "terminal": "equivalent_observation",
 "display_id": str,            # the display NOT delivered
 "retained_display_id": str,   # a display whose items are delivered
 "equivalence_map": [[a,b,tx],[c,d,ty],[0,0,1]],   # excluded display px centre -> retained display px centre
 "registration_uncertainty": float,   # native px
 "region": [x0,y0,x1,y1] | None,      # optional: only items whose display_bbox lies fully inside this box (excluded display coords) are covered; e.g. a verified preview-tail cut. Items crossing the region edge are not covered.
 "evidence": {"method": str, ...}}    # e.g. same_written_display() result
```

A display that is not delivered and has no measured equivalence gets `{"kind": "display_unresolved", "terminal": "unresolved", "display_id": str, "reason": str}`. Its items are not expected to be represented, and the verifier reports review_required `DISPLAY_UNRESOLVED` (never pass, never fail by itself).

Verifier rule: map each item hypothesis of the excluded display through `equivalence_map`. Every hypothesis pixel must land within `ceil(registration_uncertainty)` px (min 1) of the **raw** foreground of a retained-display item. Use the retained items' hypotheses, never a cleaned or production mask. Pixels that do not land there are minority content of the excluded display, which gives `fail` with code `EQUIVALENCE_CONTAINMENT_FAILED` and a mismatch crop. A display that is neither represented nor dispositioned gives `review_required` `DISPLAY_UNACCOUNTED`.

## 5. Partitioned items (one written item split across lines or pages)

When a transform chain sends parts of one item to different pieces, lines or pages (staff lines across measure cuts), `assemble_representations` partitions the item. The children are `{"id": f"{parent}/p{k}", "partition_of": parent, ...}`. Each child's `foreground_hypothesis` is the parent hypothesis restricted to one piece's `src_bbox` (in display coordinates, after the chain up to the strip), and its evidence is cropped to match. The parent gets `"partitioned_into": [child ids]` and has no representation. Verifier: the union of the children's hypotheses must equal the parent's exactly, with no pixel in two children (`PARTITION_MISMATCH`, fail). Each child is then verified like a normal item. Multiplicity is **not** incremented by partitioning.

## 6. Occurrence remaps

```python
{"root_key": str, "display_id": str, "final_system_id": str | None, "final_occurrence_id": str | None,
 "included": bool, "exclusion": str | None}
```

These are emitted by `build_occurrences` for every candidate group, including those later found covered, short, preview or excluded.

## 7. Producer outputs (fixed record keys)

| producer | where | key | content |
|---|---|---|---|
| hook 1 | `reflow_occurrences.build_occurrences` return dict | `occ["ledger"]` | fragment: one display per candidate group (`display_id = f"occ:{root_key}"`), members = all of that group's raw observation windows before duration filtering; `occurrence_remaps`; `display_dispositions` for covered or excluded candidates where equivalence was measured; `observation_associations` (list of `{obs_id, ...Association}`) |
| hook 2 | `reflow_strips.build_strip` / `build_strips` record | `rec["ledger"]` | fragment: one display per strip (`display_id = f"strip:{system_id}"`), members = **all offered** members with actual shifts, per-member `registration_uncertainty`, usable/occluded masks; `observation_associations` with roles `offered`/`used`/`rejected_fade`/`rejected_registration` |
| hook 2 | same record | `rec["ledger_chain"]` | `{"display_id": "strip:<id>", "strip_id": system_id, "stages": [ {"stage":"display_to_strip","kind":"affine","matrix":M} ]}`: one affine that maps display canvas px centres to the **final written strip PNG** px centres, including every crop/trim/finishing offset |
| hook 2 | same record | `rec["ledger_supersedes"]` | `"occ:<root_key>"` of the hook-1 display this strip display supersedes |
| hook 3 | `reflow_jump.build_jump_systems` per built record | `rec["ledger"]`, `rec["ledger_chain"]`, `rec["ledger_supersedes"]` | as hook 2, one display per **episode display** (`f"jump:{episode_id}"`); `ledger_chain` per display is a list (one per display feeding the panorama), each mapping display → final panorama strip PNG via panorama offset and trim/finish crops; overlap regions not delivered → `display_dispositions` (`display_equivalent` to the retained owner) |
| hook 4/5 | `reflow_measure._render` result | `built["ledger_placements"]` | list of `{"strip_id", "copy_index", "page_index", "line_id", "stages": [strip_to_line (piecewise, via measure_placement_transform), line_to_page (affine uniform scale + offset in page px)]}` |
| hook 5 | `reflow_render.render_pages` | second return value or attached dict `generated` | list of generated origins (header, page number, labels, review/source-clipped notices, staff insertions) with `page_index`, `origin`, packed template, `generator`, non-empty `inputs` |

The supersede rule: if a strip display supersedes an `occ:` display, the `occ:` display stays in the ledger as inventory. It gets one `display_dispositions` entry, `{"kind": "superseded_inventory", "terminal": "equivalent_observation", "display_id": "occ:..", "retained_display_id": "strip:.."}`. The verifier checks only that every `occ:` member observation id appears in the strip display's member list, and fails with `INVENTORY_MEMBER_DROPPED` otherwise. Its items are not separately represented.

## 8. Ownership (2D-1a)

| worker | owns (may edit) | adds tests |
|---|---|---|
| W-A1 verifier | `backend/app/pipeline/reflow_ledger.py` | `backend/tests/test_ledger_v2_verify.py` |
| W-A2 assembly | `backend/app/pipeline/reflow_ledger_assembly.py` (new) | `backend/tests/test_ledger_v2_assembly.py` |
| W-B hooks 1–2 | `reflow_occurrences.py`, `reflow_strips.py` | `backend/tests/test_ledger_hooks_strips.py` |
| W-C hook 3 | `reflow_jump.py` | `backend/tests/test_ledger_hooks_jump.py` |
| W-D hooks 4–5 | `reflow_measure.py`, `reflow_render.py` | `backend/tests/test_ledger_hooks_render.py` |
| W-E veto/cursor | `reflow_boundaries.py`, `minority_content.py` | `backend/tests/test_veto_footprint_cursor.py` |

Nobody in 2D-1a edits `reflow_pipeline.py`, `main.py`, `export.py`, `system_tracking.py`, `observations.py`, renderer files, or another worker's files. W-A2 may import from `reflow_ledger` only the v1 public helpers (`pack_crop`, `unpack_crop`, `pixels_hash`, `record_obligations`, `measure_placement_transform`, `MIN_CONTRAST`, `VERSION`).

## 9. Referenced evidence (round 2, replaces per-item embedded patches for real jobs)

Measured in round 1: embedding raw/display/contrast/mask PNGs per item per member costs about 3.5 MB per display at 100 items × 20 members. That extrapolates to 0.5–0.6 GB of ledger JSON for a real job. Real jobs therefore use **referenced** evidence. Embedded evidence (v1 `evidence` list) stays valid for direct callers and tests.

`record_obligations(..., evidence_dir: Path | None = None)`; each member may carry `frame_ref = {"observation_id", "crop_box": [x0,y0,x1,y1]}`, the box of the observation frame (hook 0 `frame_path`) the member canvas was cut from, before any resize.
- With `evidence_dir` set, the display gets `"evidence_mode": "referenced"`. It also gets `"members": [{"index", "observation_id", "timestamp", "frame_ref" | "canvas_ref", "transform" (observation_to_display stage, as today), "registration_uncertainty", "polarity", "usable_ref", "occluded_ref", "counted"}]`.
  - `canvas_ref = {"path", "sha256"}` is a lossless PNG of the member canvas, written only when there is no frame_ref.
  - `usable_ref` and `occluded_ref` are each `"all"`, `"none"` or `{"path", "sha256"}`, a 1-bit PNG of the full canvas. Paths are relative to the ledger's `evidence_root`.
- Each item then drops its `evidence` list and carries `"evidence_bits": {"eligible": hex, "supports": hex}`, bitsets over `display.members[].index`. Bit k set means member k satisfied the v1 rule. `foreground_hypothesis` and `expected_contrast` stay packed (≤ 64 px).
- `rl.EvidenceResolver(ledger, root)` lazily rebuilds any v1 evidence view (`raw_patch`, `display_patch`, `contrast`, masks, `transform`) for an item and member, from frames (`observations[].frame_path`, else canvas_ref). It keeps a small LRU frame cache. The verifier and assembler use the resolver for both modes, so their logic is unchanged.
- The ledger top level gets `"evidence_root"`, the directory the relative paths resolve against (the job's `ledger_evidence/`).

### 9.1 Streaming members (round 2)

`record_obligations(*, ..., members, evidence_dir=None, ...)`: `members[k]["image"]` may be a zero-argument callable that returns the canvas. With callables, the function streams in two passes and never keeps more than one canvas (plus its masks) in memory at a time:
- pass 1 accumulates the union foreground, the clear foreground and the polarity per member;
- pass 2 computes each item's per-member eligible/supports bits and max clear contrast.
All members of one display go into **one** call, never one call per member, so cross-member support classification (`protected` / `credible-few` / `ambiguous`) works. `usable`/`occluded` may also be callables. Producers pass `frame_ref` whenever the canvas is a crop of a stored observation frame.

### 9.2 Chain domains (round 2)

A `ledger_chain` entry may carry `"domain_strip": [x0, x1]`: the written-strip columns this display actually owns (jump panoramas, where a chunk also contains a neighbour's overlap columns). The assembler routes a hypothesis pixel through the chain only when its mapped strip column lies in the domain. Pixels outside every domain of their display stay unplaced; they are covered only by that display's `display_equivalent` disposition.

## 10. Review access (2D-1b)

Every hypothesis that does not end `pass` is reachable from the review screen. The backend serves it; the renderer only displays it.

`GET /jobs/{job_id}/review-hypotheses?offset=0&limit=100` (limit ≤ 500) reads the ledger report of the job's **last delivered export** (`staged/ledger_report.json`, kept beside the export) and answers:

```
{"job_id": str, "status": "pass"|"review_required"|"fail"|"unassessed",
 "export_revision": int | None,
 "counts": {"hypotheses": int,            # entries below, all pages of the list
            "bundles": int,               # minority-content alternates offered in review
            "boundaries_safe": int, "boundaries_unknown": int,   # measure mode; 0/0 for whole systems
            "pages": int,
            "by_code": {code: int},
            "user_excluded": {"displays": int, "items": int}},
 "total": int, "offset": int, "limit": int,
 "hypotheses": [{"id": str,               # stable within one export: f"{item_id}:{code}"
                 "item_id": str, "display_id": str, "occurrence_id": str | None,
                 "system_id": str | None,  # the review list entry that shows this display, if any
                 "timestamp_sec": float | None,   # the clear witness observation's t_sec
                 "status": "review_required" | "unresolved" | "fail",
                 "code": str,             # verifier issue code or disposition reason
                 "page_index": int | None,        # 1-based delivered page, None when not delivered
                 "raw_crop": str,         # absolute PNG path: witness frame crop around the item bbox
                 "primary_crop": str | None,      # absolute PNG path: the same source region as delivered, None when not delivered
                 "crop_scale": float}]}   # output px per native px, identical for both crops
```

Order: `fail` first, then `review_required`, then `unresolved`; inside each, by `timestamp_sec`. Both crops cover the item bbox padded by 2 staff gaps (native px) and are written once per export under `<export>/review_hypotheses/` (PNG, ≤ 480 px on the long side, same scale for the pair). At most 2000 entries carry crops; later entries have `raw_crop: ""` and `primary_crop: None`, and the file sets `"truncated": true` (counts still cover all). A job without a ledger report answers `status: "unassessed"`, empty list, zero counts. `404` only for an unknown job.

The job result carries the small summary only: `result.reflow.ledger_summary` (§ I-1 task 4) plus `counts` above. Review burden per dev video is reported from `counts`.

## 11. Mark-level matching (Worker V)

Preservation means every clear mark remains present, legible, with its shape and
placement preserved. Mild resampling or JPEG softening is acceptable. A mark is
an eight-connected component inside a raw hypothesis at source contrast >=64;
lower-contrast pixels remain raw inventory/context and impose no delivery
obligation (`delivery_obligation: faint_only`). Compact mark records contain a
bbox, packed native core and source contrast statistics. Raw frame references
and raw hypotheses remain available for independent evidence and partition checks.

Core erosion removes one native pixel in each direction where a three-pixel ink
run exists; thinner strokes retain their pixels. First register each page/line/copy
against all projected cores, using masked correlation within integer +/-3 output
pixels. A displacement exceeding one pixel fails `PLACEMENT_MISMATCH`; otherwise
apply that displacement before the per-mark residual +/-1 pixel search.

Page ink is >=64 darker than local P90 paper. A mark needs core coverage >=0.90
and shape IoU >=0.60. IoU uses page components touching the projected mark inside
its two-pixel dilated footprint; disconnected neighbouring marks are verified
separately. Cores with projected area <3 pixels need contrast >=32 within the
searched footprint. Checks use the recorded resize phase and interpolation, with
small-window area integrals/cubic remaps instead of full-canvas per-item resizing.
Loss stays `SOURCE_FOREGROUND_MISSING_OR_CHANGED`, with cover, IoU and offsets.

Evidence support is measured per mark core from eligible raw registered
observations, with coverage >=0.90 and residual +/-1 native pixel. Two supporters
qualify repeated evidence. Exactly one is recorded as minority (`credible-few`),
retaining the existing explicit-alternative flow; zero requires ambiguous review.
Registration metadata remains independently required. Generated staff is qualified
only in its declared raw local staff window; a connected note elsewhere cannot
invalidate a witnessed staff segment or certify non-staff additions.

Reverse accounting scans the entire page at the same clear-ink threshold. Every
page component, including a 2x2 dot, needs projected source or validated generated
origin within a two-output-pixel halo; no minimum-area exemption applies. Distinct
occurrence/copy ownership uses projected cores rather than resampling fringes.
Native partition unions remain exact and disjoint. Compact delivered JSON removes
fringe contrast values and redundant projection context, and retains only transform
pieces intersecting each item's native footprint plus its interpolation context.

## 12. Staged verification (2D-1c; replaces raw→PDF projection; DECISIONS "Staged delivered verification")

The base ledger (hook 0 inventory, producer items, dispositions, chains) stays as the inventory and disposition layer. Delivery is proven in three stages plus integrity, each a pure function over committed artifacts, each returning a **certificate** (small JSON, digests + findings). Modules: `reflow_verify_strip.py` (A), `reflow_verify_plan.py` (B), `reflow_verify_page.py` (C), shared helpers in `reflow_verify_common.py`. The old `rl.verify_pages` raw projection path is retired once A/B/C are wired (integration step), but its inventory/terminal logic (`finalize_terminals`, observation outcomes, display dispositions) is kept.

### 12.1 Common
- **Contrast space:** 8-bit, `contrast = clip(paper − gray, 0, 255)` with `paper` the local paper level (local max over a 31×31 window of the 3×3-median image; local min for light-on-dark sources). Implemented in `reflow_verify_common.contrast_map` — use it, do not re-derive.
- **Strong** pixel: contrast ≥ `C_STRONG = 64`. **Weak** pixel: 16 ≤ contrast < 64. Below 16: background.
- **Feature** (A's output unit): a local region in strip coordinates = connected strong pixels plus weak pixels within 1 px of them (*attached weak*), or a connected weak region that is isolated and persistent (≥ 2 supporting observations; *weak feature*). Features are split into tiles of at most 16×16 px so no feature is large (staff lines become chains of tiles; a dot on a staff line lies in a tile whose obligation is local).
- **Local obligation:** every 3×3 window (stride 1) whose centre is a strong pixel of a feature, or any pixel of a weak feature.
- **Finding:** `{"stage": "A"|"B"|"C"|"I", "severity": "fail"|"review_required", "code": str, "strip_id"|"page_index", "bbox": [x0,y0,x1,y1] (stage coordinates), "feature_ids": [..], "detail": {...}}`. Adjacent failing windows are grouped into one finding (8-connected) after testing, never before.
- **Digests:** `sha256` of decoded pixels (`pixels_sha256`, as `rl.pixels_hash`) for images, of canonical JSON for plans.

### 12.2 Integrity (I)
- Every evidence crop A uses is obtained from a hook-0 observation by `observation_id` + crop box and checked against the hook-0 `pixels_sha256` of that observation frame (or a tile hash committed in hook 0). A crop whose hash is computed from itself is not an anchor. Mismatch → fail `EVIDENCE_INTEGRITY`.
- `certA.strip_sha256` = pixels hash of the strip PNG that was checked; B and C refuse (fail `ARTIFACT_MISMATCH`) when the strip they read hashes differently. `certB.plan_sha256` binds the plan; `certC.pdf_sha256` = file hash of the staged PDF; the export path installs only that file (compare before install).

### 12.3 Stage A — observations → strip (`verify_strip(base_ledger, strip_record, strip_png, resolver) -> certA`)
1. Register each eligible observation of the strip's display(s) to strip coordinates once (the recorded `display_to_strip` chain + measured residual; record the operation actually used incl. any interpolation).
2. Build strip features (12.1) from the strip PNG.
3. Per feature tile and per observation: state `supports` (≥ 90% of the tile's strong pixels are strong in the registered observation, and no strong pixel of the observation inside the tile's 1-px dilation is absent from the strip... see 4), `uninformative` (occluded/overlay mask, outside ROI, registration residual > 0.5 px, transition), or `contradicts` (visible, registered, and differs). Qualified = ≥ 2 supporters with distinct visibility state (cursor position / transition state differ, or no overlay in the source). Unqualified strip content → review `STRIP_CONTENT_UNSUPPORTED` (one-observation content goes to the existing minority/alternates flow).
4. **Source → strip:** for every observation, strong pixels in uninformative-free regions that are absent from the strip (3×3 local window test against the strip, after registration) are aggregated across observations; a region seen in ≥ 2 distinct-visibility observations and missing in the strip → fail `SOURCE_FEATURE_MISSING_IN_STRIP`; seen in 1 → stays with the existing minority/unresolved disposition. Contradicting observations are never relabelled ineligible.
5. Cursor recovery rule unchanged (DECISIONS Step 2D).
6. certA: `{strip_id, strip_sha256, features: [{id, bbox, packed mask, kind: strong|weak, supporters: [obs ids ≤ 2], contradicts: [obs ids]}], findings, counters}`. Features are stored as packed masks (no per-observation images).

### 12.4 Stage B — strip → layout plan (`verify_plan(certAs, plan, ledger_sink) -> certB`)
1. **Ownership map** per strip: native strip pixel → output instance(s) (`line_id`, `copy_index`, `page_index`) from `ledger_placements` piecewise/affine stages, by mapped pixel centre. Kernel support reads are NOT ownership.
2. **Authorized changes** are exact 2-D footprints: `ledger_removed` entries become removal footprints only for pixels that are staff scaffold per the strip's staff model (row band of a detected staff line, width ≤ line thickness + 1) or paper; any strong pixel of a non-scaffold feature inside a removal footprint → fail `REMOVED_FEATURE` (or review if the removal op is a declared clef/lead replica with a verified replacement instance → `replica` role). Replicas need a declared role (`clef`, `scaffold`) and their exact source footprint.
3. **Plan validator (independent of the optimiser):** every included system's strip is owned once per canonical occurrence; source column intervals in order, no unexplained gaps/overlaps (gaps only where B authorised removal); boundaries cut only at SAFE boundaries recorded by the plan; monotone mappings with permitted scales (uniform per line, ≥ 1.2 mm staff floor); page bounds/margins respected; no clipping/draw-order overlap can hide owned content. Violations → fail `PLAN_INVALID` with detail.
4. certB: `{plan_sha256, strips: {strip_id: strip_sha256}, instances: [{line_id, page_index, copy_index, strip_id, owned_strip_bbox, transform (the recorded stages), removal_footprints (packed), replica_role}], findings}`.

### 12.5 Stage C — expected render → staged PDF (`verify_pages(certB, strip_pngs, pdf_path) -> certC`)
1. Check the PDF format contract (lossless profile: one image XObject per page, FlateDecode, 8-bit DeviceGray or DeviceRGB, content `q w 0 0 h 0 0 cm /Im Do Q`, A4, no clip/annots/rotate/SMask).
2. **Independent expected render** E per page from the strip PNGs and certB instances with own code (cv2.resize with the recorded size + interpolation, integer placement, page paper fill, header/page-number/generated elements taken from `generated_origins` templates). Not by calling `reflow_render`/`reflow_measure`.
3. Decode the staged PDF page D (lossless). One registration decision per line (integer offset search ±3 px for diagnosis; |offset| > 1 → fail `PLACEMENT_MISMATCH`; the decided offset is applied to the whole line).
4. **Residual test** on 3×3 windows: `r⁻ = max(0, E − D − ε)`, `r⁺ = max(0, D − E − ε)` in contrast space; a window fails if its mean r⁻ or r⁺ > 0 at any obligation window (12.1, mapped to page coordinates) for r⁻, and at any window for r⁺. `ε = ε_profile` from the fixture calibration (12.6). Missing → fail `DELIVERED_FEATURE_MISSING`; extra → fail `DELIVERED_EXTRA_INK`.
5. **Feature survival:** for each certA feature, its contribution in E (E rendered with vs. without that feature tile, local window only) must keep ≥ 1 output pixel with contrast ≥ 32 and local max contrast ≥ 50% of the feature's source max contrast for strong features; else review `OUTPUT_FIDELITY` (the render profile cannot show it). Compute vectorised per page; render-without only for features flagged as at-risk (small/thin/weak after scaling).
6. **Staff continuity** (presentation): S's metric (`test_measure_staff_continuity`) on D → review `STAFF_SEAM` (separate code).
7. certC: `{pdf_sha256, pages: [{index, pixels_sha256, profile}], findings, counters}`.

### 12.6 Calibration fixture (frozen before dev-video reruns)
20 motifs (isolated dot, staff-attached dot, thin stroke, stem/beam junction, X notehead, repeat dots, rests, numerals, gray dynamic, lyric fragment, staff-only segment, …) × delivered staff gaps ≈ 7, 9, 12, 16 px × subpixel phases 0, .25, .5, .75 × {area, cubic}; contrasts 32/48/64/96/128/192/255; widths 1–3 px. Destructive variants: erased isolated dot, erased staff-attached dot, removed thin branch/beam segment, removed gray dynamic, duplicated feature, piece shifted 2 px, altered evidence, altered PDF placement, wrong render profile. ε_profile = max benign residual + 2, accepted only if every destructive variant is detected; a held-out phase/placement subset checks it. Results in `docs/reflow/CALIBRATION_2D.md`.

### 12.7 Composition
Job status = worst of (inventory/disposition outcomes from the base ledger, certA findings, certB findings, certC findings). Review hypotheses (§10) are built from these findings (crops: strip-space for A/B, page-space for C; primary crop = contiguous delivered-page crop, never an inverse-mapped grid).
