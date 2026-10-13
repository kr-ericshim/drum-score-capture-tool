"""Display episodes per screen slot from an observation manifest.

Design reference: docs/archive/reflow/DESIGN_astra.md section 1 (decision procedure,
first block), section 2 (shared acquisition/tracking defaults, per-layout
algorithms) and section 5 (``system_tracking.py``: display episodes, playhead
tracks, layout classification).

Rules implemented here:

* Attach an observation's system region to the open episode of its screen
  slot only if the registration is stable (page_diff alignment shift within
  ``REGISTRATION_TOL_GAPS`` staff gaps) and there is no persistent content
  change. A change is persistent when two consecutive observations agree with
  each other and differ from the episode; a single differing observation is
  recorded as a transient observation and the episode continues. That observation is
  also a one-observation display of its own (``transient_display``, started_by
  ``transient_change``; audit F01): reflow_occurrences hides it only with evidence and
  otherwise lists it in review. It takes part in no join, continuity link, layout
  classification or jump-view analysis (``without_transient_displays``), so A -> B -> A
  keeps A one display.
* An episode is confirmed with >= 3 observations spanning >= 0.5 s; shorter
  ones are kept with the ``SHORT_EPISODE`` flag. Episodes still open at the end
  of the source carry ``TERMINAL``.
* A confirmed playhead reset (drop of >= 0.3 of the width, page_diff
  ``PLAYHEAD_RESET_FRACTION``, followed by continued advance, read only while
  the row is the active one) splits an episode;
  the split is recorded as motion evidence. Playhead advance is summarized.
* A view transition (>= 2 consecutive non-matching observations in this row
  while another row also changes at the same time) splits an episode even when
  the row looks the same before and after it (identical rows on the next page).
* A stable measure-number change in the middle of an episode whose endpoints agree
  (33 -> 37 -> 33 without a cursor; audit F04) is found from the members' raw
  measure-number areas (``_middle_runs``) and split like a number step; a run of two or
  more members too short to stand alone flags the episode (``NUMBER_STEP_UNRESOLVED``).
* A stable content step below page_diff's change threshold (notation added or
  removed: a dot, a short stroke) splits an episode too; ink the majority draws and a
  minority state lacks counts as well as ink a minority adds (audit F09). Each member keeps its
  neutral ink mask; ink that the episode majority does not draw, outside that
  member's overlay columns (colored ink, the detected playhead, a cursor track)
  and not on video seen through the band, shown by >= 2 consecutive members, is
  minority content (minority_content.py). When its run starts at the episode's
  first member or ends at its last one and lasts like a confirmed display
  (>= 3 observations over >= 0.5 s), the episode is split there
  (``content_step``); the parts share a ``content_family`` and reflow_occurrences
  places every part as an ordinary system. Later parts get ``POSSIBLE_SAME_DISPLAY``
  (‡ notice), cleared only when measure numbers certainly differ. A family is one
  continuous display: a view transition starts a new family (the row shown again
  after it is placed again), a playhead reset does not; a family left with one
  part is no family. Specks at one screen
  position in several displays (``screen_fixed_minority``) never split. A run in the middle
  (shown, then gone again) does not split; the strip stage keeps it as an
  alternate and flags the system (reflow_strips ``MINORITY_CONTENT_DROPPED``).
* Active vs preview rows come from the manifest role per observation; when a
  row's content reappears in another slot right after its episode ended (a
  preview row promoted, a page moved up), a candidate link records the slot
  transition and its vertical offset. Links that share one offset in the
  same transition are marked ``consistent_translation``. A link is accepted
  as a ``continuity_link`` (the same display continues) only when it is
  verified - a preview row promoted to the active row, or a row moving with
  the rest of its page by one shared offset - and one-to-one: neither of its
  episodes has another verified match. Competing or unverified matches are
  kept as ``continuity_candidates`` (separate displays; the assembly offers
  them as "looks similar" suggestions) so identical-looking rows are never
  merged on appearance alone.
* Layout is classified per interval: bottom_bar, page, vertical_scroll
  (unsupported), horizontal_scroll (unsupported) or non_score.

No location merging happens here (see score_assembly.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from app.pipeline import minority_content as mc
from app.pipeline import page_diff
from app.pipeline import system_detect

TRACKING_VERSION = "system_tracking-8"  # 8: one-observation transient displays, removal steps, middle number steps (audit 2026-10-13)

# layouts the tracker labels but the reflow refuses (reflow_pipeline.layout_gate)
UNSUPPORTED_LAYOUTS = {"horizontal_scroll": "UNSUPPORTED_HORIZONTAL_SCROLL", "vertical_scroll": "UNSUPPORTED_VERTICAL_SCROLL"}

REGISTRATION_TOL_GAPS = 0.5
CONFIRM_MIN_OBS = 3
CONFIRM_MIN_SEC = 0.5
SLOT_GAP_TOL_SEC = 1.0
LINK_WINDOW_SEC = 1.5
WINDOW_ABOVE_GAPS = 4.0
WINDOW_BELOW_GAPS = 4.0
CLEAN_INK_MAX = 110

SHORT_EPISODE = "SHORT_EPISODE"
TERMINAL = "TERMINAL"
# boundary of a one-observation display the tracker passed over as a transient
TRANSIENT_DISPLAY = "transient_change"

ImageLoader = Callable[[Dict[str, Any]], np.ndarray]


# --------------------------------------------------------------------------- #
# Content comparison
# --------------------------------------------------------------------------- #


def clean_content(img: np.ndarray) -> np.ndarray:
    """Dark-on-light score content with non-ink pixels set to paper white.

    Polarity is normalized and everything lighter than ``min(CLEAN_INK_MAX,
    paper - 60)`` is whitened (stricter than the detector's ink threshold of
    150: calibrated on bF69tpnUk5w, whose translucent score band lets the
    drummer video show through at gray 110-150 after inversion), so a
    background behind the score does not read as a content change. Ink
    pixels keep their color (colored playheads stay detectable as overlays).
    """
    norm, _ = system_detect.normalize_polarity(img)
    return clean_normalized(norm)


def clean_normalized(norm: np.ndarray, gray: Optional[np.ndarray] = None) -> np.ndarray:
    """``clean_content`` of an image already passed through ``normalize_polarity``.
    ``gray``: ``cvtColor(norm, COLOR_BGR2GRAY)`` when the caller already has it."""
    if gray is None:
        gray = cv2.cvtColor(norm, cv2.COLOR_BGR2GRAY)
    paper = system_detect.percentile_u8(gray, 75)
    ink = gray < min(CLEAN_INK_MAX, paper - 60)
    if norm.dtype == np.uint8 and norm.ndim == 3 and norm.shape[2] == 3:
        # max(pixel, 0) keeps ink, max(pixel, 255) whitens the rest
        lift = (~ink).view(np.uint8) * np.uint8(255)
        return cv2.max(norm, cv2.cvtColor(lift, cv2.COLOR_GRAY2BGR))
    out = np.full_like(norm, 255)
    out[ink] = norm[ink]
    return out


@dataclass
class Comparison:
    state: str  # "same" | "changed" | "unregistered"
    verdict: str
    reason: str
    shift: Tuple[float, float]


def compare_content(a: np.ndarray, b: np.ndarray, gap: float, prev_cache: Optional[Dict[str, Any]] = None) -> Comparison:
    """``same`` only with stable registration and no note-sized change.

    page_diff ``ambiguous/small_change`` (sub-note residue such as a playhead
    crossing a barline) counts as same; ``ambiguous/playhead_reset`` also counts
    as same content (the reset is handled as motion evidence).

    ``prev_cache``: a dict owned by ``a`` (never shared between images, ``a`` not changed
    while it is used) that keeps ``a``'s side of the comparison (page_diff.compare_frames).
    """
    if a.shape != b.shape:
        prev_cache = None  # padded copies
        h = max(a.shape[0], b.shape[0])
        w = max(a.shape[1], b.shape[1])
        a = _pad(a, h, w)
        b = _pad(b, h, w)
    v = page_diff.compare_frames(a, b, prev_cache=prev_cache)
    shift = (float(v.shift_x), float(v.shift_y))
    if max(abs(shift[0]), abs(shift[1])) > REGISTRATION_TOL_GAPS * max(gap, 1.0):
        return Comparison("unregistered", v.verdict, v.reason, shift)
    if v.verdict == page_diff.VERDICT_SAME:
        return Comparison("same", v.verdict, v.reason, shift)
    if v.verdict == page_diff.VERDICT_AMBIGUOUS and v.reason in ("small_change", "playhead_reset"):
        return Comparison("same", v.verdict, v.reason, shift)
    return Comparison("changed", v.verdict, v.reason, shift)


def _pad(img: np.ndarray, h: int, w: int) -> np.ndarray:
    if img.shape[0] == h and img.shape[1] == w:
        return img
    return cv2.copyMakeBorder(img, 0, h - img.shape[0], 0, w - img.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))


def window_extent(region: Dict[str, Any]) -> Tuple[int, int]:
    """Rows of real content available above the top staff line and below the bottom one
    (bounded by the region's own band and the crop, minus one staff gap at a band
    edge, where a neighbouring row's stems can intrude), in pixels."""
    top = float(region["staff_y"][0])
    bot = float(region["staff_y"][4])
    g = float(region["staff_gap_px"])
    # one gap of margin at a band edge shared with a neighbouring row: its stems/beams reach into the band
    lo_margin = g if region["bbox"][1] > 0 else 0.0
    hi_margin = g
    return max(0, int(top - region["bbox"][1] - lo_margin)), max(0, int(region["bbox"][3] - bot - hi_margin))


def comparable_windows(wa: np.ndarray, ea: Tuple[int, int], wb: np.ndarray, eb: Tuple[int, int], gap: float) -> Tuple[np.ndarray, np.ndarray]:
    """Blank the rows that only one of two windows can see (rows from different
    neighbour bands must not count as a content difference)."""
    above = int(min(ea[0], eb[0], WINDOW_ABOVE_GAPS * gap))
    below = int(min(ea[1], eb[1], WINDOW_BELOW_GAPS * gap))
    a, b = wa.copy(), wb.copy()
    lim_top = int(round(WINDOW_ABOVE_GAPS * gap)) - above
    for w in (a, b):
        if lim_top > 0:
            w[:lim_top] = 255
        cut = int(round(WINDOW_ABOVE_GAPS * gap + 4 * gap)) + below
        if cut < w.shape[0]:
            w[cut:] = 255
    return a, b


def region_window(crop: np.ndarray, region: Dict[str, Any], *, staff_top: Optional[float] = None) -> np.ndarray:
    """Fixed-size band around a staff: top-4g .. bottom+4g, full crop width,
    clipped to the region's own band and padded white to the fixed size."""
    g = float(region["staff_gap_px"])
    top = float(region["staff_y"][0] if staff_top is None else staff_top)
    y0 = int(round(top - WINDOW_ABOVE_GAPS * g))
    y1 = int(round(top + 4 * g + WINDOW_BELOW_GAPS * g))
    h = y1 - y0
    b0, b1 = region["bbox"][1], region["bbox"][3]
    lo, hi = max(y0, b0, 0), min(y1, b1, crop.shape[0])
    out = np.full((h, crop.shape[1], 3), 255, np.uint8)
    if hi > lo:
        out[lo - y0 : hi - y0] = crop[lo:hi]
    return out


# --------------------------------------------------------------------------- #
# Episode building
# --------------------------------------------------------------------------- #


@dataclass
class _Member:
    obs_id: str
    region_id: str
    t: float
    staff_top: float
    gap: float
    role: Optional[str]
    playhead_x: Optional[float]
    band: Optional[np.ndarray] = None
    ink: Optional[np.ndarray] = None  # packed: all ink of the band (anchored at the episode's first staff top)
    ink_shape: Optional[Tuple[int, int]] = None
    ink_on_paper: Optional[np.ndarray] = None  # packed: ink-dark neutral ink, without components on video seen through the band
    overlay_cols: Optional[np.ndarray] = None  # colored-overlay and playhead columns of the band
    paper: Optional[float] = None  # paper level of the raw band inside the staff (75th percentile)
    number_zone: Optional[Tuple[int, np.ndarray]] = None  # raw measure-number area ink (_number_zone)


def _attach_ink(m: "_Member", band: np.ndarray, region: Dict[str, Any], raw_band: Optional[np.ndarray] = None) -> None:
    """Keep the member's neutral ink (packed bits) and its overlay columns for the
    content-step check, so the band itself need not be kept. ``raw_band``: the same window
    of the polarity-normalized crop before cleaning (video seen through the band)."""
    neutral = mc.neutral_ink(band)
    # the reference side counts all ink (anti-aliased edges and colored ink too), so an edge
    # that crosses the ink-dark threshold in some observations is not new content
    m.ink = np.packbits(mc.ink_mask(band), axis=None)
    m.ink_shape = neutral.shape
    # components on video seen through the band are not judged (they still count for the majority)
    on_paper = mc.drop_on_video_background(neutral, mc.background_texture(raw_band, m.gap))[0] if raw_band is not None else neutral
    m.ink_on_paper = np.packbits(on_paper, axis=None)
    m.overlay_cols = mc.colored_columns(band) | mc.playhead_columns(band.shape[1], region, m.gap)
    if raw_band is not None:
        g = cv2.cvtColor(raw_band, cv2.COLOR_BGR2GRAY) if raw_band.ndim == 3 else raw_band
        top = int(round(WINDOW_ABOVE_GAPS * m.gap))
        rows = g[max(0, top):min(g.shape[0], int(round(top + 4 * m.gap)))]
        m.paper = float(np.percentile(rows if rows.size else g, 75))
        m.number_zone = _number_zone(raw_band, region, m.gap)


@dataclass
class _Episode:
    slot_id: str
    members: List[_Member] = field(default_factory=list)
    started_by: str = "first_observation"
    ended_by: Optional[str] = None
    transients: List[Dict[str, Any]] = field(default_factory=list)
    anchor_band: Optional[np.ndarray] = None  # content reference: the episode's first observation
    anchor_cache: Dict[str, Any] = field(default_factory=dict)  # anchor_band's side of compare_content
    # parts of one display split at content steps: one written system in different states
    family: Optional[str] = None
    family_score: int = 0  # content steps at which this part is the state that shows the step's ink
    number_step_unresolved: bool = False

    @property
    def ref(self) -> _Member:
        return self.members[-1]

    def __post_init__(self) -> None:
        if self.anchor_band is None and self.members:
            self.anchor_band = self.members[0].band
        for m in self.members:
            m.band = None

    def release_anchor(self) -> None:
        """A closed episode is never compared again: drop its content reference and the
        cached compare work for it (memory over a long video)."""
        self.anchor_cache.clear()
        self.anchor_band = None


def _slot_key(region: Dict[str, Any]) -> str:
    sid = region.get("slot_id") or "slot-transient"
    if sid == "slot-transient":
        return f"slot-transient@{int(round(region['staff_y'][0] / max(region['staff_gap_px'], 1.0)))}"
    return sid


def build_episodes(
    manifest: Dict[str, Any],
    load_image: ImageLoader,
    *,
    logger: Callable[[str], None] = lambda _m: None,
) -> Dict[str, Any]:
    """Track display episodes for every screen slot of a manifest."""
    observations = manifest["observations"]
    open_eps: Dict[str, _Episode] = {}
    pending: Dict[str, List[_Member]] = {}
    closed: List[_Episode] = []
    transients: List[Dict[str, Any]] = []
    last_t = observations[-1]["t_sec"] if observations else 0.0
    # classify_layout's per-observation features, computed from the crops cleaned here
    has_coarse = any(o.get("sample_kind") == "coarse" for o in observations)
    layout_feats = _LayoutFeatures()

    # every observation dropped as a transient is also a one-observation display of its own
    # (DECISIONS: a short display is hidden only with evidence, otherwise listed in review);
    # the episode around it is not split, so A -> B -> A stays one display A plus B
    transient_displays: List[_Episode] = []

    def transient_display(m: _Member, slot: str, ended_by: str = TRANSIENT_DISPLAY) -> None:
        td = _Episode(slot, [m], started_by=TRANSIENT_DISPLAY, ended_by=ended_by)
        td.release_anchor()
        transient_displays.append(td)

    def close(slot: str, reason: str) -> None:
        ep = open_eps.pop(slot)
        ep.ended_by = reason
        ep.release_anchor()
        closed.append(ep)
        for m in pending.pop(slot, []):
            transients.append({"obs_id": m.obs_id, "region_id": m.region_id, "t": m.t, "slot_id": slot,
                               "reason": "unconfirmed_change_at_episode_end"})
            transient_display(m, slot, reason if reason == "end_of_source" else TRANSIENT_DISPLAY)

    for obs in observations:
        crop = None
        regions = {}
        for r in obs["system_regions"]:
            key = _slot_key(r)
            if key not in regions or abs(r["staff_x"][1] - r["staff_x"][0]) > abs(regions[key]["staff_x"][1] - regions[key]["staff_x"][0]):
                regions[key] = r
        t = obs["t_sec"]
        for slot in list(open_eps):
            if slot not in regions and t - open_eps[slot].ref.t > SLOT_GAP_TOL_SEC:
                close(slot, "slot_empty")
        for slot, r in regions.items():
            if crop is None:
                raw = load_image(obs)
                norm = system_detect.normalize_polarity(raw)[0]
                crop = clean_normalized(norm)
            m = _Member(obs["id"], r["region_id"], t, float(r["staff_y"][0]), float(r["staff_gap_px"]), r.get("role"), r.get("playhead_x"))
            ep = open_eps.get(slot)
            if ep is None:
                m.band = region_window(crop, r)
                _attach_ink(m, m.band, r, region_window(norm, r))
                open_eps[slot] = _Episode(slot, [m], started_by="slot_appeared" if closed or open_eps else "first_observation")
                continue
            m.band = region_window(crop, r, staff_top=ep.members[0].staff_top)
            c = compare_content(ep.anchor_band, m.band, m.gap, prev_cache=ep.anchor_cache)
            if c.state == "same":
                _attach_ink(m, m.band, r, region_window(norm, r, staff_top=ep.members[0].staff_top))
                for p in pending.pop(slot, []):
                    rec = {"obs_id": p.obs_id, "region_id": p.region_id, "t": p.t, "slot_id": slot, "reason": "transient_change"}
                    ep.transients.append(rec)
                    transients.append(rec)
                    transient_display(p, slot)
                m.band = None
                ep.members.append(m)
                continue
            pend = pending.get(slot, [])
            if pend:
                c2 = compare_content(pend[-1].band, region_window(crop, r, staff_top=pend[0].staff_top), m.gap)
                if c2.state == "same":
                    m.band = region_window(crop, r, staff_top=pend[0].staff_top)
                    _attach_ink(m, m.band, r, region_window(norm, r, staff_top=pend[0].staff_top))
                    pend.append(m)
                    # persistent change: two consecutive observations agree and differ from the episode
                    open_eps.pop(slot)
                    ep.ended_by = "content_change" if c.state == "changed" else "registration_change"
                    ep.release_anchor()
                    closed.append(ep)
                    pending.pop(slot)
                    open_eps[slot] = _Episode(slot, pend, started_by=ep.ended_by)
                    continue
                for p in pend:
                    rec = {"obs_id": p.obs_id, "region_id": p.region_id, "t": p.t, "slot_id": slot, "reason": "transient_change"}
                    ep.transients.append(rec)
                    transients.append(rec)
                    transient_display(p, slot)
            m.band = region_window(crop, r)
            _attach_ink(m, m.band, r, region_window(norm, r))
            pending[slot] = [m]
        if obs.get("sample_kind") == "coarse" or not has_coarse:
            layout_feats.add(obs, crop)  # crop is None exactly when the observation has no rows
    for slot in list(open_eps):
        close(slot, "end_of_source")

    episodes = []
    content_steps: List[Dict[str, Any]] = []
    number_steps: List[Dict[str, Any]] = []
    number_steps_unresolved: List[Dict[str, Any]] = []
    obs_by = {o["id"]: o for o in observations}
    # minority content of every display first: a speck at one screen place in several displays
    # belongs to the screen (video seen through the band, a player UI), not to the score
    pre: Dict[int, List[Dict[str, Any]]] = {}
    items: List[Dict[str, Any]] = []
    gaps: List[float] = []
    for k, ep0 in enumerate(closed):
        if len(ep0.members) < CONTENT_STEP_MIN_OBS:
            continue
        pre[k] = _content_step_events(ep0.members)
        y0 = _band_top(ep0.members)
        gaps.append(float(np.median([m.gap for m in ep0.members])))
        for e in pre[k]:
            if e["kind"] != "added":
                continue  # screen-fixed specks are judged on added ink (as before removals were seen)
            x0, b0, x1, b1 = e["box"]
            items.append({"display": k, "box": [x0, b0 + y0, x1, b1 + y0], "area_px": e["area_px"],
                          "t": [round(ep0.members[e["runs"][0][0]].t, 4), round(ep0.members[e["runs"][-1][1]].t, 4)]})
    spots = mc.screen_fixed_spots(items, float(np.median(gaps))) if items else []
    screen_fixed = [it for it in items if mc.in_screen_fixed_spot(it["box"], it["area_px"], spots, float(np.median(gaps)))]
    for k, ep0 in enumerate(closed):
        number_parts = _split_on_number_steps(ep0, obs_by, load_image, number_steps,
                                              unresolved=number_steps_unresolved, logger=logger)
        for numbered in number_parts:
            events = pre.get(k) if numbered is ep0 else None
            for ep in _split_on_content_steps(numbered, transients, content_steps, events=events, spots=spots):
                for part in _split_on_view_transitions(ep, transients, closed):
                    episodes.extend(_split_on_playhead_resets(part))
    _rekey_families_at_view_transitions(episodes, content_steps)
    # an observation shown as its own transient display is a member of that display, no longer a
    # transient of the display around it (the view-transition split above has used it)
    shown = {(td.slot_id, td.members[0].obs_id) for td in transient_displays}
    transients = [r for r in transients if (r["slot_id"], r["obs_id"]) not in shown]
    for ep in episodes:
        ep.transients = [r for r in ep.transients if (r["slot_id"], r["obs_id"]) not in shown]
    episodes.extend(transient_displays)
    for ep in episodes:
        for m in ep.members:
            m.ink = m.ink_on_paper = m.overlay_cols = m.number_zone = None
    episodes.sort(key=lambda e: (e.members[0].t, e.members[0].staff_top))
    out = []
    for i, ep in enumerate(episodes):
        out.append(_episode_record(f"ep-{i:04d}", ep, last_t))
    # continuity links and the layout are judged on the ordinary displays only
    ordinary = [(rec, ep) for rec, ep in zip(out, episodes) if not rec.get("transient_display")]
    _link_continuity([rec for rec, _ep in ordinary], [ep for _rec, ep in ordinary], load_image, manifest)
    layout = classify_layout(manifest, [rec for rec, _ep in ordinary], load_image, features=layout_feats.feats)
    for e in out:
        e["layout"] = _layout_at(layout, e["t_start"])
    logger(f"episodes: {len(out)} ({len(transient_displays)} one-observation transient displays), "
           f"transients: {len(transients)}, content steps split: {len(content_steps)}, number steps split: {len(number_steps)}")
    return {
        "schema_version": 1,
        "kind": "display_episodes",
        "tracking_version": TRACKING_VERSION,
        "video_id": manifest.get("video_id"),
        "manifest_schema_version": manifest.get("schema_version"),
        "rules": {
            "registration_tol_gaps": REGISTRATION_TOL_GAPS,
            "confirm_min_obs": CONFIRM_MIN_OBS,
            "confirm_min_sec": CONFIRM_MIN_SEC,
            "playhead_reset_fraction": page_diff.PLAYHEAD_RESET_FRACTION,
            "slot_gap_tol_sec": SLOT_GAP_TOL_SEC,
        },
        "episodes": out,
        "content_steps": content_steps,
        "number_steps": number_steps,
        "number_steps_unresolved": number_steps_unresolved,
        # specks judged part of the screen (minority_content.screen_fixed_spots): on record, not split
        "screen_fixed_minority": {"spots": spots, "events": [{k: v for k, v in it.items() if k != "display"} for it in screen_fixed]},
        "transient_observations": transients,
        "transient_displays": [e["id"] for e in out if e.get("transient_display")],
        "layout_intervals": layout,
    }


def without_transient_displays(tracking: Dict[str, Any]) -> Dict[str, Any]:
    """``tracking`` without the one-observation transient displays (``transient_display``):
    the episode list the jump analysis and the coverage accounting work on."""
    if not any(e.get("transient_display") for e in tracking.get("episodes", [])):
        return tracking
    return dict(tracking, episodes=[e for e in tracking.get("episodes", []) if not e.get("transient_display")])


CONTENT_STEP_MIN_OBS = 4
CONTENT_STEP_MAX_DEPTH = 8
NUMBER_STEP_MAX_DEPTH = 8


NUMBER_ZONE_RIGHT_GAPS = 8.0   # the measure-number area of reflow_occurrences (left 4 gaps, right 8 gaps)
NUMBER_ZONE_LEFT_GAPS = 4.0
NUMBER_ZONE_INK = 200          # reflow_occurrences.WRITTEN_INK_THRESHOLD (a gray-180 digit counts)
NUMBER_ZONE_MIN_PX = 8         # reflow_occurrences.WRITTEN_MIN_AREA_PX
NUMBER_ZONE_MIN_AREA_GAPS = 0.04  # reflow_occurrences.NUMBER_CHANGE_MIN_PIECE_GAPS area


def _number_zone(raw_band: np.ndarray, region: Dict[str, Any], gap: float) -> Optional[Tuple[int, np.ndarray]]:
    """The raw ink (gray < NUMBER_ZONE_INK, colored pixels left out) of a member's measure-number
    area - above the top staff line from 4 gaps left of the staff start to 8 gaps into the staff,
    and the margin left of the staff start - as (first column, mask). A cheap in-memory
    pre-filter for the middle of an episode (``_number_zone_differs``); the decision is always
    reflow_occurrences.measure_number_area_differs on the raw windows."""
    sx = region.get("staff_x")
    if not sx:
        return None
    h, w = raw_band.shape[:2]
    top = int(round(WINDOW_ABOVE_GAPS * gap))
    x0 = int(sx[0])
    xl, xr = max(0, int(x0 - NUMBER_ZONE_LEFT_GAPS * gap)), min(w, max(0, int(x0 + NUMBER_ZONE_RIGHT_GAPS * gap)))
    rows = min(h, int(top + 5 * gap))
    if xr <= xl or rows <= 0:
        return None
    sub = raw_band[:rows, xl:xr]
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY) if sub.ndim == 3 else sub
    ink = g < NUMBER_ZONE_INK
    if sub.ndim == 3:
        ink &= cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)[..., 1] <= 80
    area = np.zeros(ink.shape, bool)
    area[:max(0, top - 1)] = True
    area[:, :max(0, x0 - 1 - xl)] = True
    return xl, ink & area


def _number_zone_differs(a: Tuple[int, np.ndarray], b: Tuple[int, np.ndarray], gap: float) -> bool:
    """Ink in two members' number zones that one draws and the other does not (1 px tolerance),
    in pieces of at least a digit stroke's area; no shift search, so it flags at least what the
    strict comparison would."""
    (xa, ma), (xb, mb) = a, b
    lo, hi = max(xa, xb), min(xa + ma.shape[1], xb + mb.shape[1])
    h = min(ma.shape[0], mb.shape[0])
    if hi <= lo or h <= 0:
        return False
    ia = ma[:h, lo - xa:hi - xa].astype(np.uint8)
    ib = mb[:h, lo - xb:hi - xb].astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    residue = (ia & (1 - cv2.dilate(ib, k))) | (ib & (1 - cv2.dilate(ia, k)))
    if not residue.any():
        return False
    r = max(1, int(round(0.15 * gap)))
    n, lab = cv2.connectedComponents(cv2.dilate(residue, np.ones((2 * r + 1, 2 * r + 1), np.uint8)), connectivity=8)
    sizes = np.bincount(lab[residue > 0].ravel(), minlength=n)[1:]
    return bool(sizes.size and sizes.max() >= max(NUMBER_ZONE_MIN_PX, NUMBER_ZONE_MIN_AREA_GAPS * gap * gap))


def _middle_runs(ms: Sequence[_Member]) -> List[Tuple[int, bool]]:
    """(middle member, stable) of each run of two or more consecutive members whose number zone
    differs from the first member's (``_number_zone_differs``) and that ends before the episode's
    last member: a state shown, then gone again (audit F04: 33 -> 37 -> 33 without a cursor; the
    endpoints agree). ``stable``: the run lasts like a confirmed display (``mc.stable_run``)."""
    n = len(ms)
    if n < 3 or ms[0].number_zone is None:
        return []
    flagged = [False] + [m.number_zone is not None and _number_zone_differs(ms[0].number_zone, m.number_zone, m.gap)
                         for m in ms[1:]]
    times = [m.t for m in ms]
    out: List[Tuple[int, bool]] = []
    i = 1
    while i < n:
        if not flagged[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flagged[j + 1]:
            j += 1
        if j < n - 1 and j > i:
            out.append(((i + j) // 2, mc.stable_run(times, i, j)))
        i = j + 1
    return out


def _split_on_number_steps(ep: _Episode, obs_by: Dict[str, Dict[str, Any]], load_image: ImageLoader,
                           log: List[Dict[str, Any]], depth: int = 0, *,
                           unresolved: Optional[List[Dict[str, Any]]] = None,
                           logger: Callable[[str], None] = lambda _m: None) -> List[_Episode]:
    """Split a verified stable left run from a certainly different right endpoint.

    Top-level endpoint agreement costs just two windows. Differing endpoints trigger
    bisection, then every left member must agree. A recursive suffix scans every member
    against its first, even when its endpoints agree, before accepting one state.
    When the endpoints agree, the middle of each stable run of members whose number zone
    differs from the first one (``_middle_runs``) is compared too (audit F04: 33 -> 37 -> 33): a
    certain digit-scale difference there makes the episode scanned member by member like a
    suffix. Sub-digit residue counts as agreement; a certain change without a clean cut
    remains flagged for review (``NUMBER_STEP_UNRESOLVED``).
    """
    if len(ep.members) < 2 or (depth == 0 and len(ep.members) < CONTENT_STEP_MIN_OBS):
        return [ep]
    # Runtime import: occurrences imports tracking's window geometry at module load.
    # Reuse its strict raw comparator without a second implementation or import cycle.
    from app.pipeline.reflow_occurrences import _raw_window_of, measure_number_area_differs

    ms = ep.members
    evidence = None
    split_kind = "number_step"

    def not_split(reason, **details):
        ep.number_step_unresolved = True
        record = {"slot_id": ep.slot_id, "t_start": round(ms[0].t, 4), "t_end": round(ms[-1].t, 4),
                  "observation_ids": [m.obs_id for m in ms], "region_ids": [m.region_id for m in ms],
                  "evidence": evidence, "reason": reason, **details}
        if unresolved is not None:
            unresolved.append(record)
        logger(f"number step not split: {ep.slot_id} {ms[0].obs_id}: {reason}")
        return [ep]

    def window(i):
        return _raw_window_of(obs_by, load_image, ms[i].obs_id, ms[i].region_id)

    middle = False
    try:
        first, last = window(0), window(len(ms) - 1)
        evidence = measure_number_area_differs(first, last, require_digit_scale=True)
        comparisons = {len(ms) - 1: evidence}
        if depth == 0 and (evidence is None or evidence.get("reason") != "measure_number_area_differs"):
            for i, stable in _middle_runs(ms):
                probe = measure_number_area_differs(first, window(i), require_digit_scale=True)
                comparisons[i] = probe
                if probe is not None and probe.get("reason") == "measure_number_area_differs":
                    evidence, middle = probe, True
                    if not stable:
                        # too short to be a display of its own: never split (that would print the
                        # surrounding display twice); the line carries the notice
                        return not_split("unstable_middle_run", obs_id=ms[i].obs_id)
                    break
            if not middle:
                return [ep]

        def comparison(i):
            if i not in comparisons:
                comparisons[i] = measure_number_area_differs(first, first if i == 0 else window(i),
                                                            require_digit_scale=True)
            return comparisons[i]

        if depth > 0 or middle:
            cut = next((i for i in range(len(ms)) if comparison(i) is not None), None)
            if cut is None:
                return [ep]
            evidence = comparison(cut)
        else:
            lo, hi = 0, len(ms) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if comparison(mid) is None:
                    lo = mid
                else:
                    hi = mid
            cut = hi
        if depth >= NUMBER_STEP_MAX_DEPTH:
            return not_split("depth_limit")
        if (comparison(cut) or {}).get("reason") != "measure_number_area_differs":
            return not_split("cut_member_uncertain", obs_id=ms[cut].obs_id, member_evidence=comparison(cut))
        times = [m.t for m in ms]
        left_stable = cut > 0 and mc.stable_run(times, 0, cut - 1)
        right_stable = mc.stable_run(times, cut, len(ms) - 1)
        if not (left_stable and right_stable):
            if depth > 0 or middle or evidence.get("number_present") != [True, True]:
                return not_split("unstable_side")
            # A short edge at an actual line change is a hand-over, not two stable
            # displays merged together. Keep it as a separate short episode; only
            # the stable side whose every member certainly agrees can remain confirmed.
            changes = ("content_change", "registration_change", "view_transition")
            if depth == 0 and not left_stable and right_stable and ep.started_by in changes:
                right = window(cut)
                if any(measure_number_area_differs(right, window(i), require_digit_scale=True) is not None
                       for i in range(cut, len(ms))):
                    return not_split("unstable_side")
            elif not (depth == 0 and left_stable and not right_stable and ep.ended_by in changes):
                return not_split("unstable_side")
            split_kind = "view_transition"
        for i in range(cut):
            if comparison(i) is not None:
                return not_split("no clean cut", obs_id=ms[i].obs_id, member_evidence=comparison(i))
    except Exception as exc:  # no pixels/comparison means no evidence to split
        if depth > 0 or (evidence is not None and evidence.get("reason") == "measure_number_area_differs"):
            return not_split("comparison_failed", detail=str(exc))
        logger(f"number step not split: {ep.slot_id} {ms[0].obs_id}: comparison failed: {exc}")
        return [ep]
    if split_kind == "number_step":
        log.append({"slot_id": ep.slot_id, "t": round(ms[cut].t, 4), "obs_id": ms[cut].obs_id,
                    "evidence": evidence})
    parts = []
    for a, b in ((0, cut), (cut, len(ms))):
        part = _Episode(ep.slot_id, ms[a:b], started_by=ep.started_by if a == 0 else split_kind,
                        ended_by=split_kind if b < len(ms) else ep.ended_by,
                        number_step_unresolved=ep.number_step_unresolved)
        t_lo = ms[a - 1].t if a > 0 else -np.inf
        t_hi = ms[b].t if b < len(ms) else np.inf
        part.transients = [r for r in ep.transients if t_lo < r["t"] < t_hi]
        parts.extend([part] if a == 0 or split_kind != "number_step" else _split_on_number_steps(
            part, obs_by, load_image, log, depth + 1, unresolved=unresolved, logger=logger))
    return parts


def _band_top(members: List["_Member"]) -> int:
    """Crop row of the members' band row 0 (region_window anchored at the first member's staff top)."""
    m = members[0]
    return int(round(m.staff_top - WINDOW_ABOVE_GAPS * m.gap))


def _faded_members(members: List[_Member]) -> List[bool]:
    """Members of a fade into or out of the video behind the plate (6MPX's last line: paper
    246 -> 133), whose added ink is not judged for content steps: the run of members at the
    start or end of the episode whose paper is not clearly light, when other members show
    clearly light paper and the run reaches paper as dark as the ink threshold (there the
    background cannot be told from ink). Paper levels: reflow_occurrences.RAW_PAPER_MIN and
    WRITTEN_INK_THRESHOLD. A dim stretch elsewhere, or a plate that only dips below clearly
    light, keeps every member judged."""
    from app.pipeline.reflow_occurrences import RAW_PAPER_MIN, WRITTEN_INK_THRESHOLD
    n = len(members)
    dim = [m.paper is not None and m.paper < RAW_PAPER_MIN for m in members]
    out = [False] * n
    if all(dim) or not any(dim):
        return out
    for run in (range(n), range(n - 1, -1, -1)):  # from the start, from the end
        edge = []
        for i in run:
            if not dim[i]:
                break
            edge.append(i)
        if edge and min(members[i].paper for i in edge) <= WRITTEN_INK_THRESHOLD:
            for i in edge:
                out[i] = True
    return out


def _content_step_events(members: List[_Member]) -> List[Dict[str, Any]]:
    """Minority content of an episode's members, both ways (DECISIONS round 4: notation added
    or removed):

    * ``added``: neutral ink some members show and the majority of the members does not draw;
    * ``removed``: neutral ink the majority draws (as ink-dark ink on paper) and some members
      do not draw at all (audit F09: a mark shown in the first 20 observations and gone in
      the last 12 - the state without it is the minority).

    Columns a member's overlay covers are not judged for that member, nor are components on
    video seen through the band, nor the members of a fade (``_faded_members``)."""
    if any(m.ink is None or m.ink_on_paper is None or m.ink_shape is None for m in members):
        return []
    # bands of one episode share their top row; their height can differ by a rounding pixel
    shape = (min(m.ink_shape[0] for m in members), min(m.ink_shape[1] for m in members))
    g = float(np.median([m.gap for m in members]))

    def unpack(bits: np.ndarray, m: _Member) -> np.ndarray:
        return np.unpackbits(bits, count=m.ink_shape[0] * m.ink_shape[1]).reshape(m.ink_shape).astype(bool)[:shape[0], :shape[1]]

    cols = [m.overlay_cols[:shape[1]] if m.overlay_cols is not None else np.zeros(shape[1], bool) for m in members]
    count = np.zeros(shape, np.uint16)
    count_dark = np.zeros(shape, np.uint16)
    seen = np.zeros(shape[1], np.uint16)
    for m, cv in zip(members, cols):
        count += (unpack(m.ink, m) & ~cv[None, :]).astype(np.uint16)
        count_dark += (unpack(m.ink_on_paper, m) & ~cv[None, :]).astype(np.uint16)
        seen += (~cv).astype(np.uint16)
    majority = (count.astype(np.int32) * 2 > seen[None, :].astype(np.int32)) & (seen[None, :] > 0)
    majority_dark = (count_dark.astype(np.int32) * 2 > seen[None, :].astype(np.int32)) & (seen[None, :] > 0)
    maj_d = mc._dilate(majority, mc.tolerance_px(g))
    added: Dict[int, np.ndarray] = {}
    removed: Dict[int, np.ndarray] = {}
    # members of a fade still vote for the majority, but neither the background they show nor
    # the ink they lose in it is judged
    faded = _faded_members(members)
    for i, (m, cv) in enumerate(zip(members, cols)):
        if faded[i]:
            added[i] = removed[i] = np.zeros(shape, bool)
            continue
        mine = unpack(m.ink_on_paper, m)
        added[i] = mc.unexplained(mine, majority, cv, g, reference_dilated=maj_d)[0]
        # the member's own ink at any darkness explains the majority's ink (a lighter stroke is not gone)
        removed[i] = mc.unexplained(majority_dark, unpack(m.ink, m), cv, g)[0]
    added, _track = mc.remove_cursor_track(added, g)
    return ([dict(e, kind="added") for e in mc.minority_events(added, g)]
            + [dict(e, kind="removed") for e in mc.minority_events(removed, g)])


def _split_on_content_steps(ep: _Episode, transients: List[Dict[str, Any]], log: List[Dict[str, Any]],
                            depth: int = 0, *, events: Optional[List[Dict[str, Any]]] = None,
                            spots: Sequence[Dict[str, Any]] = ()) -> List[_Episode]:
    """Split an episode at a stable content step page_diff tolerated as a small change:
    minority content whose run starts at the first member or ends at the last one
    (notation added or removed) and lasts like a confirmed display (``mc.stable_run``: a
    shorter run at the edge is the hand-over to the neighbouring display, e.g. a page curl).
    Runs in the middle (shown, then gone again) do not split here, nor do specks at a
    screen-fixed spot (``spots``). Each part is checked again (several steps).

    The parts share ``family`` and each counts the steps at which it is the state that
    shows the step's ink (``family_score``). reflow_occurrences places every part as an ordinary
    system; later parts get ``POSSIBLE_SAME_DISPLAY`` (‡ notice), cleared only when measure
    numbers certainly differ."""
    ms = ep.members
    n = len(ms)
    if n < CONTENT_STEP_MIN_OBS or depth > CONTENT_STEP_MAX_DEPTH:
        return [ep]
    times = [m.t for m in ms]
    cut = None
    best = None
    left_shows = False
    y0 = _band_top(ms)
    g = float(np.median([m.gap for m in ms]))
    # members of a fade are unknown: a run reaching the first or last judged member reaches the edge
    judged = [i for i, faded in enumerate(_faded_members(ms)) if not faded] or [0, n - 1]
    first, last = judged[0], judged[-1]
    for e in (events if events is not None else _content_step_events(ms)):
        x0, b0, x1, b1 = e["box"]
        if mc.in_screen_fixed_spot([x0, b0 + y0, x1, b1 + y0], e["area_px"], spots, g):
            continue
        for i0, i1 in e["runs"]:
            if not mc.stable_run(times, i0, i1):
                continue
            # an added run is the state that shows the ink; a removed run the state that lacks it
            if i0 <= first and i1 < last:
                k, shows_left = i1 + 1, e["kind"] == "added"
            elif i1 >= last and i0 > first:
                k, shows_left = i0, e["kind"] != "added"
            else:
                continue
            if best is None or e["area_px"] > best["area_px"]:
                best, cut, left_shows = e, k, shows_left
    if cut is None:
        return [ep]
    family = ep.family or f"cs-{ep.slot_id}-{ms[0].obs_id}"
    log.append({"slot_id": ep.slot_id, "t": round(ms[cut].t, 4), "obs_id": ms[cut].obs_id, "kind": best["kind"],
                "box_band": best["box"], "box_crop": [best["box"][0], best["box"][1] + y0, best["box"][2], best["box"][3] + y0],
                "area_px": best["area_px"], "family": family, "state_with_ink": "earlier" if left_shows else "later",
                "run": [round(ms[best["runs"][0][0]].t, 4), round(ms[best["runs"][0][1]].t, 4)]})
    parts = []
    for a, b in ((0, cut), (cut, n)):
        seg = _Episode(ep.slot_id, ms[a:b], number_step_unresolved=ep.number_step_unresolved)
        seg.anchor_band = None
        seg.started_by = ep.started_by if a == 0 else "content_step"
        seg.ended_by = "content_step" if b < n else ep.ended_by
        seg.family = family
        seg.family_score = ep.family_score + (1 if (a == 0) == left_shows else 0)
        t_lo = ms[a - 1].t if a > 0 else -np.inf
        t_hi = ms[b].t if b < n else np.inf
        seg.transients = [r for r in ep.transients if t_lo < r["t"] < t_hi]
        parts.extend(_split_on_content_steps(seg, transients, log, depth + 1, spots=spots))
    return parts


VIEW_TRANSITION_MIN_OBS = 2
VIEW_TRANSITION_PEER_SEC = 0.3


def _split_on_view_transitions(ep: _Episode, transients: List[Dict[str, Any]], closed: List[_Episode]) -> List[_Episode]:
    """Split an episode across a whole-view transition it survived unchanged.

    A run of >= 2 consecutive transient (non-matching) observations inside the
    episode, while another screen slot also has transient observations at the
    same time (+-0.3 s), is a view transition (page curl / page change / scroll)
    even when this row looks identical before and after it: an identical row on
    the next page must not be silently continued as the same display episode.
    Another slot "changes" when it has transient observations or an episode
    starting/ending in that window. The two parts are kept as separate episodes
    (started_by "view_transition").
    """
    if not ep.transients or len(ep.members) < 2:
        return [ep]
    t_trans = sorted(r["t"] for r in ep.transients)
    others = [r["t"] for r in transients if r["slot_id"] != ep.slot_id]
    # content changes / appearances in other rows at the same time also mark a view change
    others += [o.members[0].t for o in closed if o.slot_id != ep.slot_id and o.started_by != "first_observation" and o.members]
    others += [o.members[-1].t for o in closed if o.slot_id != ep.slot_id and o.ended_by not in (None, "end_of_source") and o.members]
    member_t = [m.t for m in ep.members]
    runs: List[List[float]] = []
    for t in t_trans:
        # consecutive = no episode member observed between the two transients
        if runs and not any(runs[-1][-1] < mt < t for mt in member_t):
            runs[-1].append(t)
        else:
            runs.append([t])
    cuts = []
    for run in runs:
        if len(run) < VIEW_TRANSITION_MIN_OBS:
            continue
        a, b = run[0] - VIEW_TRANSITION_PEER_SEC, run[-1] + VIEW_TRANSITION_PEER_SEC
        if not any(a <= t <= b for t in others):
            continue
        k = next((i for i, mt in enumerate(member_t) if mt > run[-1]), None)
        if k is not None and 0 < k < len(ep.members):
            cuts.append((k, run))
    if not cuts:
        return [ep]
    parts, start = [], 0
    for k, run in cuts + [(len(ep.members), None)]:
        seg = _Episode(ep.slot_id, ep.members[start:k], number_step_unresolved=ep.number_step_unresolved)
        seg.anchor_band = None
        # the family is re-keyed at view transitions once every split is made (build_episodes)
        seg.family, seg.family_score = ep.family, ep.family_score
        seg.started_by = ep.started_by if start == 0 else "view_transition"
        seg.ended_by = "view_transition" if run is not None else ep.ended_by
        seg.transients = [r for r in ep.transients if (start == 0 or r["t"] > ep.members[start - 1].t) and (run is None or r["t"] <= run[-1])]
        parts.append(seg)
        start = k
    return [p for p in parts if p.members]


def _split_on_playhead_resets(ep: _Episode) -> List[_Episode]:
    # Only readings taken while this row holds the playhead count: on a page the
    # playhead line can be seen in a row's band while another row is played.
    xs = [(i, m.playhead_x) for i, m in enumerate(ep.members) if m.playhead_x is not None and m.role in ("active", None)]
    cuts = []
    for k in range(1, len(xs)):
        i_prev, x_prev = xs[k - 1]
        i_cur, x_cur = xs[k]
        if x_prev - x_cur < page_diff.PLAYHEAD_RESET_FRACTION:
            continue
        # confirmation: the next two readings continue from the new position and
        # at least one of them advances (a static false reading never advances)
        if k + 2 >= len(xs):
            continue
        x_n1, x_n2 = xs[k + 1][1], xs[k + 2][1]
        if not (x_cur - 0.05 <= x_n1 <= x_cur + 0.35 and x_cur - 0.05 <= x_n2 <= x_cur + 0.5):
            continue
        if max(x_n1, x_n2) <= x_cur + 0.01:
            continue
        cuts.append(i_cur)
    if not cuts:
        return [ep]
    parts, start = [], 0
    for c in cuts + [len(ep.members)]:
        seg = _Episode(ep.slot_id, ep.members[start:c], number_step_unresolved=ep.number_step_unresolved)
        seg.family, seg.family_score = ep.family, ep.family_score
        seg.started_by = ep.started_by if start == 0 else "playhead_reset"
        seg.ended_by = "playhead_reset" if c < len(ep.members) else ep.ended_by
        if start == 0:
            seg.transients = ep.transients
        parts.append(seg)
        start = c
    return [p for p in parts if p.members]


def _rekey_families_at_view_transitions(episodes: List[_Episode], log: List[Dict[str, Any]]) -> None:
    """A content family is the states of one continuous display. A view transition ends that
    display (the row shown again after a page change is a new display and is placed again), so
    per family, in time order, a part that starts at a view transition starts a new family and
    the parts after it share the new id until the next view transition. A playhead reset does
    not end the display: its parts keep the family. ``family_score`` is kept. A family left with
    one part is no family (nothing to choose between). Content-step log entries take the family
    of the part the step starts."""
    fams: Dict[str, List[_Episode]] = {}
    for ep in episodes:
        if ep.family:
            fams.setdefault(ep.family, []).append(ep)
    started: Dict[Tuple[str, str], Optional[str]] = {}
    for fid, parts in fams.items():
        parts.sort(key=lambda e: e.members[0].t)
        groups: List[List[_Episode]] = [[]]
        for p in parts:
            if p.started_by == "view_transition" and groups[-1]:
                groups.append([])
            groups[-1].append(p)
        for gi, grp in enumerate(groups):
            new_id = (fid if gi == 0 else f"{fid}-v{gi}") if len(grp) > 1 else None
            for p in grp:
                p.family = new_id
                started[(p.slot_id, p.members[0].obs_id)] = new_id
    for rec in log:
        key = (rec["slot_id"], rec["obs_id"])
        if key in started:
            rec["family"] = started[key]


def _episode_record(eid: str, ep: _Episode, last_t: float) -> Dict[str, Any]:
    ms = ep.members
    t0, t1 = ms[0].t, ms[-1].t
    flags = []
    if len(ms) < CONFIRM_MIN_OBS or (t1 - t0) < CONFIRM_MIN_SEC:
        flags.append(SHORT_EPISODE)
    if ep.ended_by == "end_of_source":
        flags.append(TERMINAL)
    roles = [m.role for m in ms if m.role]
    # sorted keys and an "unknown"-first tie-break keep the record the same in every process
    role_counts = {r: roles.count(r) for r in sorted(set(roles))}
    track = [[round(m.t, 4), m.playhead_x] for m in ms if m.playhead_x is not None]
    advance = None
    if len(track) >= 2:
        diffs = np.diff([p[1] for p in track])
        advance = {"readings": len(track), "forward_steps": int((diffs > 0.005).sum()), "backward_steps": int((diffs < -0.005).sum()),
                   "x_first": track[0][1], "x_last": track[-1][1]}
    return {
        "id": eid,
        "slot_id": ep.slot_id,
        "t_start": round(t0, 6),
        "t_end": round(t1, 6),
        "n_obs": len(ms),
        "observation_ids": [m.obs_id for m in ms],
        "region_ids": [m.region_id for m in ms],
        "staff_top_y": round(float(np.median([m.staff_top for m in ms])), 1),
        "staff_gap_px": round(float(np.median([m.gap for m in ms])), 2),
        "role": max(role_counts, key=lambda r: (role_counts[r], r == "unknown")) if role_counts else None,
        "role_counts": role_counts,
        "flags": flags,
        "confirmed": SHORT_EPISODE not in flags,
        "started_by": ep.started_by,
        "ended_by": ep.ended_by,
        "transient_observation_ids": [r["obs_id"] for r in ep.transients],
        "motion": {
            "playhead_track": track,
            "playhead_advance": advance,
            "reset_at_start": ep.started_by == "playhead_reset",
            "reset_at_end": ep.ended_by == "playhead_reset",
        },
        "continuity_links": [],
        **({"content_family": {"id": ep.family, "score": ep.family_score}} if ep.family else {}),
        **({"number_step_unresolved": True} if ep.number_step_unresolved else {}),
        **({"transient_display": True} if ep.started_by == TRANSIENT_DISPLAY else {}),
    }


def _member_window(load_image: ImageLoader, manifest: Dict[str, Any], obs_id: str, region_id: str) -> Tuple[np.ndarray, float, Tuple[int, int]]:
    obs = next(o for o in manifest["observations"] if o["id"] == obs_id)
    r = next(r for r in obs["system_regions"] if r["region_id"] == region_id)
    crop = clean_content(load_image(obs))
    return region_window(crop, r), float(r["staff_gap_px"]), window_extent(r)


def _link_continuity(records: List[Dict[str, Any]], episodes: List[_Episode], load_image: ImageLoader, manifest: Dict[str, Any]) -> None:
    """Record slot transitions of the same displayed content (row shift / page move)."""
    by_id = {r["id"]: r for r in records}
    links = []
    for rec in records:
        if rec["started_by"] in ("first_observation", "playhead_reset", "content_step"):
            continue
        t_new = rec["t_start"]
        cands = [o for o in records if o["id"] != rec["id"] and o["slot_id"] != rec["slot_id"]
                 and t_new - LINK_WINDOW_SEC <= o["t_end"] <= t_new + 0.25 and o["t_start"] < t_new]
        if not cands:
            continue
        new_win, gap, new_ext = _member_window(load_image, manifest, rec["observation_ids"][0], rec["region_ids"][0])
        for o in cands:
            old_win, _, old_ext = _member_window(load_image, manifest, o["observation_ids"][-1], o["region_ids"][-1])
            a_w, b_w = comparable_windows(old_win, old_ext, new_win, new_ext, gap)
            c = compare_content(a_w, b_w, gap)
            if c.state == "same":
                dy = rec["staff_top_y"] - o["staff_top_y"]
                links.append({"from": o["id"], "to": rec["id"], "t": t_new, "dy_px": round(dy, 1), "gap": gap,
                              "kind": "row_shift", "from_role": o["role"], "to_role": rec["role"]})
    # consistent translation: >= 2 links within 0.5 s sharing dy (+-0.5 gap)
    for lk in links:
        peers = [p for p in links if p is not lk and p["from"] != lk["from"] and p["to"] != lk["to"]
                 and abs(p["t"] - lk["t"]) <= 0.5 and abs(p["dy_px"] - lk["dy_px"]) <= 0.5 * lk["gap"]]
        lk["consistent_translation"] = len(peers) >= 1
        lk["peer_links"] = len(peers)
        if lk["from_role"] == "preview" and lk["to_role"] == "active":
            lk["kind"] = "preview_promotion"
        elif lk["consistent_translation"]:
            lk["kind"] = "page_translation"
    # accept only verified links that are one-to-one among the verified links
    verified = [lk for lk in links if lk["kind"] in ("preview_promotion", "page_translation")]
    n_from: Dict[str, int] = {}
    n_to: Dict[str, int] = {}
    for lk in verified:
        n_from[lk["from"]] = n_from.get(lk["from"], 0) + 1
        n_to[lk["to"]] = n_to.get(lk["to"], 0) + 1
    for lk in links:
        public = {k: v for k, v in lk.items() if k != "gap"}
        if lk["kind"] not in ("preview_promotion", "page_translation"):
            public["rejected"] = "unverified_row_shift"
        elif n_from[lk["from"]] > 1 or n_to[lk["to"]] > 1:
            public["rejected"] = "competing_match"
        if "rejected" in public:
            by_id[lk["to"]].setdefault("continuity_candidates", []).append(public)
            continue
        by_id[lk["to"]]["continuity_links"].append(public)
        by_id[lk["from"]].setdefault("continued_by", []).append(lk["to"])


# --------------------------------------------------------------------------- #
# Layout classification
# --------------------------------------------------------------------------- #


class _LayoutFeatures:
    """classify_layout's features, one coarse observation at a time (in manifest order).
    ``clean``: clean_content of the observation's crop (None when it has no rows)."""

    def __init__(self) -> None:
        self.feats: List[Dict[str, Any]] = []
        self.prev: Optional[Tuple[Dict[str, Any], Optional[np.ndarray]]] = None

    def add(self, o: Dict[str, Any], clean: Optional[np.ndarray]) -> None:
        prev = self.prev
        n = len(o["system_regions"])
        gap = float(np.median([r["staff_gap_px"] for r in o["system_regions"]])) if n else 0.0
        hshift = vshift = 0.0
        img = None
        if n:
            img = _small(clean)
        hx = None
        if prev is not None and n and prev[1] is not None:
            v = page_diff.compare_frames(prev[1], img)
            scale = o["crop_size"][0] / float(img.shape[1])
            if v.reason != "alignment_out_of_range":
                hshift, vshift = abs(v.shift_x) * scale, abs(v.shift_y) * scale
            # A paged system starts with a clef at its left end; a scrolling staff shows the
            # middle of the music. Horizontal motion counts only between clef-less views
            # (calibration: paged rows have a clef in 88-100% of observations, the five
            # horizontal-scroll videos in 1-17%), which rejects groove-periodic aliases
            # between consecutive paged systems.
            noclef = not any(r.get("clef") for r in o["system_regions"]) and not any(r.get("clef") for r in prev[0]["system_regions"])
            if noclef:
                hx = horizontal_shift(prev[1], img, gap / scale if scale else gap)
                if hx is not None:
                    hx = hx * scale
            else:
                hshift = 0.0
        changed = bool(prev is not None and n and prev[1] is not None and (v.verdict == page_diff.VERDICT_DIFFERENT or hx is not None))
        self.feats.append({"t": o["t_sec"], "rows": n, "gap": gap, "h": hshift, "v": vshift, "hx": hx, "changed": changed})
        self.prev = (o, img)


def classify_layout(manifest: Dict[str, Any], episodes: List[Dict[str, Any]], load_image: ImageLoader,
                    *, window_sec: float = 10.0, features: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Per-interval layout from coarse observations.

    Features per coarse observation: number of system rows; translation to the
    previous coarse observation (page_diff alignment on cleaned crops).
    * horizontal_scroll: in the window, >= 40% of score pairs move by >= 0.5 gap
      horizontally (page_diff alignment, or ``horizontal_shift`` phase
      correlation on staff-line-free ink, which also finds shifts beyond
      page_diff's 35% range) -> unsupported; also when, in a 20 s window,
      >= 2 content changes are horizontal translations and they make up >= 50%
      of all content changes (jump scrolling).
    * vertical_scroll: >= 3 vertical moves of >= 0.5 gap in the window with
      content overlap (alignment found) -> continuous vertical scroll -> unsupported
      (2026-10-11: a multi-line block scrolling up re-captures every line it moves;
      refused until it has its own path).
    * page: >= 3 rows, or 2 rows whose episodes change together.
    * bottom_bar: 1-2 rows otherwise. non_score: no rows.
    """
    if features is None:
        coarse = [o for o in manifest["observations"] if o.get("sample_kind") == "coarse"] or manifest["observations"]
        acc = _LayoutFeatures()
        for o in coarse:
            acc.add(o, clean_content(load_image(o)) if o["system_regions"] else None)
        features = acc.feats
    feats = features
    together = _rows_change_together(episodes)
    labels = []
    for f in feats:
        win = [g for g in feats if abs(g["t"] - f["t"]) <= window_sec / 2 and g["rows"]]
        if not f["rows"]:
            labels.append("non_score")
            continue
        gap = max(f["gap"], 1.0)
        hmoves = sum(1 for g in win if (g["h"] >= 0.5 * gap and g["v"] < 0.5 * gap) or (g.get("hx") is not None and abs(g["hx"]) >= 0.5 * gap))
        # jump scrolling: the content stays still, then jumps left by part of the width;
        # most content changes in a 20 s window are horizontal translations
        win20 = [g for g in feats if abs(g["t"] - f["t"]) <= 10.0 and g["rows"]]
        jumps = sum(1 for g in win20 if g.get("hx") is not None)
        changes = sum(1 for g in win20 if g.get("changed"))
        vmoves = sum(1 for g in win if g["v"] >= 0.5 * gap)
        rows = int(np.median([g["rows"] for g in win])) if win else f["rows"]
        if (win and hmoves >= max(2, 0.4 * len(win))) or (jumps >= 2 and jumps >= 0.5 * max(1, changes)):
            labels.append("horizontal_scroll")
        elif vmoves >= 3:
            labels.append("vertical_scroll")
        elif rows >= 3 or (rows == 2 and together):
            labels.append("page")
        else:
            labels.append("bottom_bar")
    # smooth: runs shorter than 3 s take the neighbouring label
    intervals = []
    for f, lab in zip(feats, labels):
        if intervals and intervals[-1]["kind"] == lab:
            intervals[-1]["end"] = f["t"]
            intervals[-1]["samples"] += 1
        else:
            intervals.append({"start": f["t"], "end": f["t"], "kind": lab, "samples": 1})
    changed = True
    while changed and len(intervals) > 1:
        changed = False
        for i, iv in enumerate(intervals):
            if iv["end"] - iv["start"] < 3.0 and iv["kind"] != "non_score":
                j = i - 1 if i > 0 else i + 1
                intervals[j]["start"] = min(intervals[j]["start"], iv["start"])
                intervals[j]["end"] = max(intervals[j]["end"], iv["end"])
                intervals[j]["samples"] += iv["samples"]
                intervals.pop(i)
                changed = True
                break
        merged = []
        for iv in intervals:
            if merged and merged[-1]["kind"] == iv["kind"]:
                merged[-1]["end"] = iv["end"]
                merged[-1]["samples"] += iv["samples"]
            else:
                merged.append(iv)
        intervals = merged
    for iv in intervals:
        iv["supported"] = iv["kind"] not in UNSUPPORTED_LAYOUTS
        if iv["kind"] in UNSUPPORTED_LAYOUTS:
            iv["issue"] = UNSUPPORTED_LAYOUTS[iv["kind"]]
    return intervals


def horizontal_shift(a: np.ndarray, b: np.ndarray, gap: float) -> Optional[float]:
    """Horizontal content translation between two cleaned crops (pixels of these crops), or None.

    Staff lines are removed (they are invariant under horizontal motion), then
    the column profile of the remaining ink and the 2-D phase correlation must
    agree: a clear peak (response >= 0.15) with vertical shift < 0.3 gap and a
    shift of >= 0.5 gap. A page/system change has no consistent peak.
    """
    if a is None or b is None or a.shape != b.shape:
        return None
    ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY) if a.ndim == 3 else a
    gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY) if b.ndim == 3 else b
    ia = (ga < 150).astype(np.uint8)
    ib = (gb < 150).astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, int(4 * gap)), 1))
    ia = ia & (1 - cv2.morphologyEx(ia, cv2.MORPH_OPEN, k))
    ib = ib & (1 - cv2.morphologyEx(ib, cv2.MORPH_OPEN, k))
    if ia.sum() < 50 or ib.sum() < 50:
        return None
    win = cv2.createHanningWindow((ia.shape[1], ia.shape[0]), cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(ia.astype(np.float32), ib.astype(np.float32), win)
    if resp < 0.15 or abs(dy) >= 0.3 * max(gap, 1.0) or abs(dx) < 0.5 * max(gap, 1.0):
        return None
    return float(dx)


def _small(img: np.ndarray, max_w: int = 960) -> np.ndarray:
    if img.shape[1] <= max_w:
        return img
    s = max_w / float(img.shape[1])
    return cv2.resize(img, (max_w, max(1, int(round(img.shape[0] * s)))), interpolation=cv2.INTER_AREA)


def _rows_change_together(episodes: List[Dict[str, Any]]) -> bool:
    ends = [e for e in episodes if e["ended_by"] in ("content_change", "registration_change")]
    if len({e["slot_id"] for e in episodes}) < 2 or not ends:
        return False
    together = 0
    for e in ends:
        if any(o is not e and o["slot_id"] != e["slot_id"] and abs(o["t_end"] - e["t_end"]) <= 1.5 for o in ends):
            together += 1
    return together >= 0.6 * len(ends)


def _layout_at(intervals: List[Dict[str, Any]], t: float) -> str:
    for iv in intervals:
        if iv["start"] - 0.5 <= t <= iv["end"] + 0.5:
            return iv["kind"]
    return "unknown"


LOADER_CACHE_BYTES = 768 * 1024 * 1024


def manifest_image_loader(manifest_dir: Path, manifest: Dict[str, Any],
                          max_bytes: int = LOADER_CACHE_BYTES) -> ImageLoader:
    """Decoded observation crops, least recently used first out, within a byte budget.

    Strip cleaning walks all members of a system several times in order; a budget
    that holds a whole system decodes each stored frame once instead of every pass.
    Callers must not mutate returned arrays, including their sliced views.
    """
    from collections import OrderedDict
    from threading import Event, Lock

    from app.pipeline.observations import load_observation_image

    cache: "OrderedDict[str, np.ndarray]" = OrderedDict()
    held = [0]
    lock = Lock()
    decoding = {}

    def load(obs: Dict[str, Any]) -> np.ndarray:
        oid = obs["id"]
        while True:
            with lock:
                img = cache.get(oid)
                if img is not None:
                    cache.move_to_end(oid)
                    return img
                event = decoding.get(oid)
                if event is None:
                    event = decoding[oid] = Event()
                    break
            event.wait()
        try:
            # Independent observations decode concurrently; cache bookkeeping
            # and publication are atomic. Callers treat returned frames as read-only.
            img = load_observation_image(manifest_dir, obs, manifest)
            with lock:
                if img.nbytes <= max_bytes:
                    cache[oid] = img
                    held[0] += int(img.nbytes)
                    while held[0] > max_bytes:
                        _old, dropped = cache.popitem(last=False)
                        held[0] -= int(dropped.nbytes)
            return img
        finally:
            with lock:
                decoding.pop(oid)
                event.set()

    return load
