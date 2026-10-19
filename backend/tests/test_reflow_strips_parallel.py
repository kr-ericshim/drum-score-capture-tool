"""Bounded strip workers preserve pixels, provenance, ordering and cancellation."""
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from unittest.mock import patch

import numpy as np

from app.pipeline import observations as ob
from app.pipeline import reflow_strips as rs
from app.pipeline import system_tracking as st
from app.pipeline.process_control import OperationCancelled
from drum_score_fixture import render
from reflow_fixture import build, loader, page
from test_reflow_strips import full_frames, preview_frames, system_image


def normalized(value, root):
    if isinstance(value, dict):
        return {k: normalized(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(v, root) for v in value]
    if isinstance(value, np.ndarray):
        return {"shape": list(value.shape), "pixels": hashlib.sha256(value.tobytes()).hexdigest()}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (str, Path)):
        # also the JSON-escaped form a nested record holds on Windows (backslashes doubled)
        text = str(value).replace(str(root).replace("\\", "\\\\"), "<OUT>")
        return text.replace(str(root), "<OUT>")
    return value


def systems_for(manifest):
    obs = manifest["observations"]
    return [{"id": f"sys-{i:03d}", "observations": [
        {"obs_id": o["id"], "region_id": o["system_regions"][i]["region_id"]} for o in obs]}
        for i in range(len(obs[0]["system_regions"]))]


class ParallelEquivalenceTest(unittest.TestCase):
    def test_sequential_retains_adjacent_members_without_loader_lru(self):
        image = render(page([7, 8]))
        manifest, images = build([(i * .25, image.copy()) for i in range(3)])
        decoded = []

        def load(obs):
            decoded.append(obs["id"])
            return images[obs["id"]]

        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, REFLOW_STRIP_THREADS="1"), \
             patch.object(rs, "job_screen_chrome", return_value=(None, {})):
            rs.build_strips({"systems": systems_for(manifest)}, manifest, load, Path(td))
        self.assertCountEqual(decoded, list(images))

    def compare(self, manifest, images, systems, *, ledger=False, chrome=None):
        before = copy.deepcopy(manifest), copy.deepcopy(systems)
        originals = {k: v.copy() for k, v in images.items()}
        # Input views and shared chrome cannot be written in-place.
        for image in images.values():
            image.flags.writeable = False
        if chrome is not None:
            chrome[0].flags.writeable = False
            chrome[1]["_appearance"].flags.writeable = False
        with tempfile.TemporaryDirectory() as td:
            snapshots = []
            for count in (1, 4):
                root = Path(td) / str(count)
                logs, progress, callback_threads = [], [], []

                def checkpoint():
                    callback_threads.append(threading.get_ident())

                with patch.dict(os.environ, REFLOW_STRIP_THREADS=str(count)):
                    with patch.object(rs, "job_screen_chrome", return_value=chrome) if chrome is not None else nullcontext():
                        records = rs.build_strips({"systems": systems}, manifest, loader(images), root / "strips",
                            logger=logs.append, progress=progress.append, checkpoint=checkpoint, ledger=ledger)
                self.assertEqual(set(callback_threads), {threading.get_ident()})
                snapshots.append((json.dumps(normalized(records, root), sort_keys=True),
                    {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.png")}, logs, progress))
            self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(before, (manifest, systems))
        for key, image in images.items():
            np.testing.assert_array_equal(image, originals[key])
        return snapshots[0]

    def test_shared_frames_and_chrome_views(self):
        image = render(page([7, 8, 9, 10]))
        mask = np.zeros(image.shape[:2], bool)
        mask[3:9, 30:75] = True
        image[mask] = (220, 120, 40)
        manifest, images = build([(i * .25, image.copy()) for i in range(4)])
        appearance = np.full(image.shape, np.nan, np.float32)
        appearance[mask] = (220, 120, 40)
        self.compare(manifest, images, systems_for(manifest), chrome=(mask, {"_appearance": appearance}))

    def test_preview_uncut_and_minority_alternate_png_bytes(self):
        cur, nxt = system_image(7), system_image(8)
        frames = preview_frames(cur, nxt, n=4) + full_frames(nxt, n=4, t0=2)
        frames[5][1][5:18, 600:603] = 0
        manifest, images = build(frames)
        systems = [{"id": f"sys-{i:03d}", "observations": [
            {"obs_id": o["id"], "region_id": o["system_regions"][0]["region_id"]}
            for o in manifest["observations"][i * 4:(i + 1) * 4]]} for i in range(2)]
        snapshot = self.compare(manifest, images, systems)
        self.assertTrue(any("uncut/" in p for p in snapshot[1]))
        self.assertTrue(any("alt/" in p for p in snapshot[1]))

    def test_shared_ledger_evidence_paths(self):
        image = render(page([7, 8]))
        manifest, images = build([(i * .25, image.copy()) for i in range(3)])
        self.compare(manifest, images, systems_for(manifest), ledger=True)


class WorkerLifecycleTest(unittest.TestCase):
    def test_slow_first_system_bounds_started_work(self):
        started, records = [], []
        release = threading.Event()
        initial_window_done = threading.Event()
        lock = threading.Lock()

        def clean(system, *_args, **_kwargs):
            with lock:
                started.append(system["id"])
                if len(started) == 4:
                    initial_window_done.set()
            if system["id"] == "0":
                self.assertTrue(release.wait(2))
            return np.full((5, 5, 3), 255, np.uint8), {"system_id": system["id"]}

        def unblock():
            if initial_window_done.wait(2):
                time.sleep(.05)  # later systems finish while the first remains blocked
                with lock:
                    records.extend(started)
            release.set()

        observer = threading.Thread(target=unblock)
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, REFLOW_STRIP_THREADS="4"), \
             patch.object(rs, "job_screen_chrome", return_value=(None, {})), \
             patch.object(rs, "build_strip", side_effect=clean):
            observer.start()
            try:
                # Cancel after enough systems are consumed; no post-loop record schema needed.
                def progress(value):
                    if value >= .6:
                        raise OperationCancelled()

                with self.assertRaises(OperationCancelled):
                    rs.build_strips({"systems": [{"id": str(i)} for i in range(10)]},
                        {"observations": []}, lambda _: None, Path(td), progress=progress)
            finally:
                release.set()
                observer.join()
        self.assertEqual(set(records), {"0", "1", "2", "3"})

    def test_cancellation_stops_writes_and_joins_workers(self):
        seen = []

        class Executor(ThreadPoolExecutor):
            def shutdown(self, *args, **kwargs):
                seen.append(kwargs)
                return super().shutdown(*args, **kwargs)

        for count, k, expected in ((1, 2, 1), (4, 5, 0), (4, 7, 1)):
            with self.subTest(threads=count, checkpoint=k), tempfile.TemporaryDirectory() as td:
                calls = []

                def checkpoint():
                    self.assertEqual(threading.current_thread(), threading.main_thread())
                    calls.append(1)
                    if len(calls) == k:
                        raise OperationCancelled("stop")

                def clean(system, *_args, **_kwargs):
                    time.sleep(.01)
                    return np.full((5, 5, 3), 255, np.uint8), {"system_id": system["id"]}

                with patch.dict(os.environ, REFLOW_STRIP_THREADS=str(count)), \
                     patch.object(rs, "ThreadPoolExecutor", Executor), \
                     patch.object(rs, "job_screen_chrome", return_value=(None, {})), \
                     patch.object(rs, "build_strip", side_effect=clean):
                    with self.assertRaises(OperationCancelled):
                        rs.build_strips({"systems": [{"id": str(i)} for i in range(10)]},
                            {"observations": []}, lambda _: None, Path(td), checkpoint=checkpoint)
                self.assertEqual(len(list(Path(td).glob("strip_*.png"))), expected)
                self.assertFalse(any(t.name.startswith("strips") for t in threading.enumerate()))
        self.assertEqual(seen, [{"wait": True, "cancel_futures": True}] * 2)

    def test_errors_propagate_in_system_order(self):
        second_done = threading.Event()

        def clean(system, *_args, **_kwargs):
            if system["id"] == "first":
                self.assertTrue(second_done.wait(2))
                raise ValueError("first in display order")
            second_done.set()
            raise RuntimeError("later system finished first")

        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, REFLOW_STRIP_THREADS="4"), \
             patch.object(rs, "job_screen_chrome", return_value=(None, {})), \
             patch.object(rs, "build_strip", side_effect=clean):
            with self.assertRaisesRegex(ValueError, "first in display order"):
                rs.build_strips({"systems": [{"id": "first"}, {"id": "second"}]},
                    {"observations": []}, lambda _: None, Path(td))
            self.assertEqual(list(Path(td).glob("*.png")), [])
        self.assertFalse(any(t.name.startswith("strips") for t in threading.enumerate()))

    def test_default_and_invalid_overrides(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(rs.os, "cpu_count", return_value=None):
            self.assertEqual(rs._strip_threads(), 1)
        for ram, cpus, expected in ((None, 8, 1), (8.0, 8, 1), (12.0, 8, 2), (16.0, 8, 4), (64.0, 3, 2), (64.0, 16, 4)):
            with patch.dict(os.environ, {}, clear=True), patch.object(rs.os, "cpu_count", return_value=cpus), \
                 patch.object(rs, "_physical_ram_gib", return_value=ram):
                self.assertEqual(rs._strip_threads(), expected, (ram, cpus))
        for value in ("0", "-1", "garbage", "1.5"):
            with patch.dict(os.environ, REFLOW_STRIP_THREADS=value), self.assertRaises(ValueError):
                rs._strip_threads()


class ConcurrentLoaderTest(unittest.TestCase):
    def test_equal_arrays_once_per_cached_id_and_budget(self):
        decoded = []
        barrier = threading.Barrier(8)
        frame = np.arange(300, dtype=np.uint8).reshape(10, 10, 3)

        def decode(_root, obs, _manifest):
            decoded.append(obs["id"])
            time.sleep(.01)
            return frame.copy()

        with patch.object(ob, "load_observation_image", side_effect=decode):
            load = st.manifest_image_loader(Path("unused"), {}, max_bytes=600)

            def same(_):
                barrier.wait()
                return load({"id": "shared"})

            with ThreadPoolExecutor(max_workers=8) as pool:
                images = list(pool.map(same, range(8)))
                for image in images:
                    np.testing.assert_array_equal(image, frame)
                self.assertEqual(decoded, ["shared"])
                list(pool.map(lambda i: load({"id": str(i)}), range(24)))
            state = inspect.getclosurevars(load).nonlocals
            self.assertEqual(state["held"][0], sum(v.nbytes for v in state["cache"].values()))
            self.assertLessEqual(state["held"][0], 600)
            self.assertFalse(state["decoding"])
            tiny = st.manifest_image_loader(Path("unused"), {}, max_bytes=1)
            np.testing.assert_array_equal(tiny({"id": "oversize"}), frame)
            self.assertEqual(inspect.getclosurevars(tiny).nonlocals["held"][0], 0)

    def test_decode_failure_wakes_waiters(self):
        barrier = threading.Barrier(4)

        def fail(*_):
            time.sleep(.01)
            raise ValueError("decode failed")

        with patch.object(ob, "load_observation_image", side_effect=fail):
            load = st.manifest_image_loader(Path("unused"), {})

            def attempt(_):
                barrier.wait()
                with self.assertRaisesRegex(ValueError, "decode failed"):
                    load({"id": "broken"})

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(attempt, range(4)))
            self.assertFalse(inspect.getclosurevars(load).nonlocals["decoding"])


if __name__ == "__main__":
    unittest.main()
