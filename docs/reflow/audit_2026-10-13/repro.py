# Astra 감사(2026-10-13) 재현 스크립트. 각 항목이 현재 코드에서 재현되면 REPRODUCED를 출력한다.
# 고친 뒤에는 해당 항목이 "NOT reproduced"로 바뀌어야 한다(단, assert는 결함 상태를 기대하는 형태).
# 실행(저장소 루트): PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:backend/tests backend/.venv/bin/python -B docs/reflow/audit_2026-10-13/repro.py
import cv2, traceback, tempfile
import numpy as np
from pathlib import Path
from unittest.mock import patch
from reflow_fixture import build, loader, show, strip, STEP
from drum_score_fixture import render
from app.pipeline import system_tracking as st
from app.pipeline import reflow_occurrences as ro
from app.pipeline import reflow_strips as rs
from app.pipeline import observations as ob
from app.pipeline import source_class as sc

def audit(frames):
    manifest, images = build(frames)
    load = loader(images)
    tracking = st.build_episodes(manifest, load)
    occurrences = ro.build_occurrences(tracking, manifest, load)
    kept = []
    for system in occurrences["systems"]:
        if system["included"]:
            image, rec = rs.build_strip(system, manifest, load)
            kept.append((system, image, rec))
    return tracking, occurrences, kept
def static(specs):
    return [(i * STEP, render(spec)) for i, spec in enumerate(specs)]

R = {}
def case(name):
    def deco(fn):
        try:
            fn(); R[name] = "REPRODUCED"
        except Exception as e:
            R[name] = "NOT reproduced: " + repr(e)[:200]
        return fn
    return deco

@case("F01")
def _():
    a, b = strip(4), strip(9)
    tr, oc, kept = audit(static([a]*12 + [b] + [a]*12))
    assert [e["n_obs"] for e in tr["episodes"]] == [24]
    assert len(kept) == 1
    assert kept[0][0]["issues"] == kept[0][2]["issues"] == []

@case("F02")
def _():
    a, b = strip(4), strip(9)
    tr, oc, kept = audit(static([a]*12 + [b]*4 + [a]*12))
    assert [s["included"] for s in oc["systems"]] == [True, False, True]

@case("F03")
def _():
    tr, oc, kept = audit(
        show(strip(4), 0, 4, seed=1, phases=lambda i, n: .3 + .6*(i+.5)/n)
        + show(strip(4), 4, 4, seed=2, phases=lambda i, n: .3 + .6*(i+.2)/n))
    assert [e["n_obs"] for e in tr["episodes"]] == [16, 16]
    assert len(oc["systems"]) == 1

@case("F04")
def _():
    bars = [33]*12 + [37]*12 + [33]*12
    tr, oc, kept = audit(static([strip(4, numbers=True, first_bar=n) for n in bars]))
    assert [e["n_obs"] for e in tr["episodes"]] == [36]
    assert len(kept) == 1

@case("F05")
def _():
    a, c = strip(4), strip(9)
    b = a.copy()
    b.notes = {k: list(v) for k, v in a.notes.items() if k[1] < 2}
    b.notes.update({k: list(v) for k, v in c.notes.items() if k[1] >= 2})
    tr, oc, kept = audit(static([a]*12 + [b]*4 + [c]*12))
    assert len(oc["systems"]) == len(kept) == 2
    assert oc["fragments"][0]["hidden"] is True

@case("F09")
def _():
    frames = show(strip(4), 0, 8, seed=1)
    for i, (_, im) in enumerate(frames):
        if i < 20:
            cv2.line(im, (700,150), (760,150), (0,0,0), 2)
    tr, oc, kept = audit(frames)
    assert [e["n_obs"] for e in tr["episodes"]] == [32]
    assert tr["content_steps"] == []
    assert kept[0][2]["minority_content"]["events"] == []

@case("F06")
def _():
    A, B = render(strip(1)), render(strip(2))
    roi = [[0,0],[1400,0],[1400,190],[0,190]]
    info = ob.VideoInfo("memory", 30., 75, 1400, 190, 2.5)
    for choose in (lambda t: B if .1 <= t < .4 else A, lambda t: B if t >= 2.1 else A):
        sampled = {}
        def decode(path, targets):
            for t in targets:
                sampled[t] = choose(t); yield t, t, sampled[t]
        with patch.object(ob, "probe_video", return_value=info), \
             patch.object(ob, "iter_frames_at", side_effect=decode), \
             patch.object(ob, "file_sha256", return_value="0"*64):
            m = ob.build_manifest(video_path=Path("/tmp/x"), roi=roi, store_frames=False, work_scale=1.)
        load = lambda o: sampled[o["t_sec"]]
        oc = ro.build_occurrences(st.build_episodes(m, load), m, load)
        assert len(oc["systems"]) == 1

@case("F07")
def _():
    from test_reflow_occurrences import ep, tracking, EMPTY_MANIFEST, never_load
    from test_reflow_measure import Doc, measure_strip
    eps = [ep("a","slot-00",0,4,started="first_observation",ended="content_step"),
           ep("b","slot-00",4.25,4.75,started="content_step",ended="content_step"),
           ep("c","slot-00",5,9,started="content_step",ended="end_of_source")]
    for e in eps: e["content_family"] = {"id":"F","score":0}
    oc = ro.build_occurrences(tracking(eps), EMPTY_MANIFEST, never_load)
    assert [s["included"] for s in oc["systems"]] == [True, False, True]
    with tempfile.TemporaryDirectory() as tmp:
        doc = Doc(Path(tmp))
        for o in oc["systems"]:
            s = doc.add(o["id"], *measure_strip())
            for k in ("included","issues","content_family","possible_repeat_of"):
                if k in o: s[k] = o[k]
        plan, pages = doc.compose([s for s in doc.systems if s["included"]], measure_reflow=True)
        assert not [m for p in plan["pages"] for m in p.get("markers", [])]
        assert plan["header"].get("notice") is None

@case("F07b_issues_not_in_pdf")
def _():
    from test_reflow_measure import Doc, measure_strip
    with tempfile.TemporaryDirectory() as tmp:
        doc = Doc(Path(tmp)); s = doc.add("s", *measure_strip())
        _, base = doc.compose(measure_reflow=True)
        s["issues"] = ["MINORITY_CONTENT_DROPPED","OVERLAY_UNRECOVERED","SHORT_DISPLAY"]
        plan, pages = doc.compose(measure_reflow=True)
        assert all(np.array_equal(a,b) for a,b in zip(pages, base))

@case("F08")
def _():
    img = render(strip(1))
    class EarlyEOF:
        def __init__(self,*a): self.i=-1
        def isOpened(self): return True
        def grab(self): self.i+=1; return self.i<45
        def retrieve(self): return True, img
        def get(self,k):
            if k==cv2.CAP_PROP_FPS: return 30.
            if k==cv2.CAP_PROP_POS_MSEC: return self.i/30*1000
            return 0
        def release(self): pass
    with patch.object(ob,"probe_video",return_value=ob.VideoInfo("memory",30,180,1400,190,6.)), \
         patch.object(ob.cv2,"VideoCapture",EarlyEOF), patch.object(ob,"file_sha256",return_value="0"*64):
        m = ob.build_manifest(video_path=Path("/tmp/x"), roi=[[0,0],[1400,0],[1400,190],[0,190]], store_frames=False, work_scale=1.)
    assert m["sampling"]["sampled_until_sec"] == 6.
    assert ob.validate_manifest(m) == []

@case("F10")
def _():
    from test_overlay_chrome import staff
    patterns = [[60+90*j for j in range(9)], [65+85*j+20*(j%2) for j in range(9)], [80+70*j for j in range(10)]]
    frames = []
    for k, notes in enumerate(patterns):
        im = staff(notes=notes)
        cv2.putText(im,"A",(180,180),cv2.FONT_HERSHEY_SIMPLEX,.9,(40,40,220),2,cv2.LINE_AA)
        frames += [(k*2+i*.25, im.copy()) for i in range(8)]
    tr, oc, kept = audit(frames)
    assert len(kept) == 3
    for system, image, rec in kept:
        assert rec["screen_chrome"]["filled_px"] > 0
        assert rec["box_crop"][1] + rec["box_crop"][3] <= 160 or rec["box_crop"][3] <= 140

@case("F11")
def _():
    from test_reflow_visibility_marks import paper, system_case
    for dark, level in ((False,200),(True,55)):
        images = [(255-paper()) if dark else paper() for _ in range(8)]
        for im in images:
            cv2.putText(im,"pp",(410,125),cv2.FONT_HERSHEY_SIMPLEX,.55,(level,)*3,1,cv2.LINE_AA)
        _, manifest, load = system_case(images)
        tr = st.build_episodes(manifest, load); oc = ro.build_occurrences(tr, manifest, load)
        inc = [s for s in oc["systems"] if s["included"]]
        image, rec = rs.build_strip(inc[0], manifest, load, chrome=False)
        assert rec["box_crop"] == [15,25,788,109], rec["box_crop"]

@case("F12")
def _():
    from test_reflow_visibility_marks import paper, system_case
    images = [paper() for _ in range(12)]
    for i in (5,6): images[i][110,420:432] = 0
    _, manifest, load = system_case(images)
    tr = st.build_episodes(manifest, load); oc = ro.build_occurrences(tr, manifest, load)
    inc = [s for s in oc["systems"] if s["included"]]
    image, rec = rs.build_strip(inc[0], manifest, load, chrome=False)
    assert rec["issues"] == ["MINORITY_CONTENT_DROPPED","UNCERTAIN_MARK_KEPT"]

@case("F13")
def _():
    from test_source_class import _flat, _compose, _notation, TOP, GAP, X0
    frames = []
    for i in range(4):
        bg = _flat((12,12,12)); x = X0+i*280
        bg[TOP-20:TOP+4*GAP+20, x:x+280] = 40
        frames.append(_compose(bg, _notation(i), (245,245,245)))
    r = sc.classify_frames(frames)
    assert r["flags"] == ["translucent_plate"]

for k, v in R.items(): print(k, v)
