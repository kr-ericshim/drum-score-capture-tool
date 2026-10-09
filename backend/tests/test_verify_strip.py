import copy
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from app.pipeline import reflow_ledger as rl
from app.pipeline import reflow_verify_common as vc
from app.pipeline import reflow_verify_strip as va


def score():
    image = np.full((100, 192), 255, np.uint8)
    for y in (15, 30, 45, 60, 75):
        image[y, 8:184] = 0
    cv2.circle(image, (45, 38), 3, 0, -1)
    image[22:38, 48] = 0
    image[61:64, 85:88] = 0
    image[43:48, 112:115] = 0  # a dot touching the middle staff line
    image[20:22, 144:146] = 0  # isolated dot
    return image


def fixture(images=None, strip=None, shifts=None):
    if images is None:
        images = [score() for _ in range(6)]
    if strip is None:
        strip = score()
    shifts = shifts or [(0, 0)] * len(images)
    members, observations, stored = [], [], {}
    for index, (image, (dx, dy)) in enumerate(zip(images, shifts)):
        oid = f"obs-{index:06}"
        frame = cv2.warpAffine(image, np.array([[1., 0, dx], [0, 1., dy]]),
                               image.shape[1::-1], borderValue=255)
        stored[oid] = frame
        observations.append({"id": oid, "pixels_sha256": rl.pixels_hash(frame), "work_scale": 1.,
                             "associations": [{"display_id": "strip:sys-001", "role": "used"}]})
        members.append({"index": index, "observation_id": oid, "timestamp": index,
                        "frame_ref": {"observation_id": oid, "crop_box": [0, 0, image.shape[1], image.shape[0]]},
                        "transform": {"matrix": [[1, 0, -dx], [0, 1, -dy], [0, 0, 1]], "polarity": "light"}})
    ledger = {"observations": observations, "displays": [{"id": "strip:sys-001", "shape": list(strip.shape[:2]),
                                                        "members": members}], "items": []}
    chain = {"display_id": "strip:sys-001", "strip_id": "sys-001",
             "stages": [{"stage": "display_to_strip", "kind": "affine", "matrix": np.eye(3).tolist()}]}
    return ledger, {"system_id": "sys-001", "staff_gap_px": 15}, strip, stored, chain


def run_fixture(data):
    ledger, record, strip, stored, chain = data
    return va.verify_strip(ledger, record, strip, frames=stored.__getitem__, chain=chain)


def findings(cert, code):
    return [f for f in cert["findings"] if f["code"] == code]


def at(cert, x, y):
    return [f for f in cert["features"] if f["bbox"][0] <= x < f["bbox"][2]
            and f["bbox"][1] <= y < f["bbox"][3]
            and vc.unpack_mask(f["mask"])[y-f["bbox"][1], x-f["bbox"][0]]]


class VerifyStripTest(unittest.TestCase):
    def test_clean_six_shifted_observations(self):
        data = fixture(shifts=[(-2, 0), (-1, 1), (0, -1), (1, 0), (2, 1), (0, 0)])
        cert = run_fixture(data)
        self.assertEqual(cert["findings"], [])
        self.assertTrue(cert["features"])
        self.assertTrue(all(f["qualified"] and len(f["supporters"]) == 2 for f in cert["features"]))
        self.assertEqual(cert["strip_sha256"], rl.pixels_hash(data[2]))
        self.assertEqual(cert["counters"]["observations"], 6)
        self.assertEqual(len(cert["counters"]["registrations"]), 6)
        self.assertTrue(all(r["residual_registration_px"] == 0 for r in cert["counters"]["registrations"]))
        self.assertTrue(all(r["warp_operation"] == "integer_translation_copy" and r["contrast_interpolation"] is None
                            for r in cert["counters"]["registrations"]))
        json.dumps(cert, allow_nan=False)

    def test_three_observation_missing_dot_fails(self):
        blank = score(); blank[20:22, 144:146] = 255
        cert = run_fixture(fixture([score()]*3 + [blank]*3, strip=blank))
        misses = findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP")
        self.assertTrue(any(f["severity"] == "fail" and f["bbox"][0] <= 145 < f["bbox"][2] for f in misses))

    def test_erased_dot_touching_staff_fails_locally(self):
        erased = score(); erased[43:48, 112:115] = 255; erased[45, 112:115] = 0
        cert = run_fixture(fixture([score()]*3 + [erased]*3, strip=erased))
        misses = findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP")
        self.assertTrue(misses)
        self.assertTrue(any(f["bbox"][0] <= 113 < f["bbox"][2] and f["bbox"][2]-f["bbox"][0] <= 5 for f in misses))
        self.assertTrue(any(f["contradicts"] for f in at(cert, 113, 45)))

    def test_one_observation_missing_dot_stays_minority(self):
        blank = score(); blank[20:22, 144:146] = 255
        cert = run_fixture(fixture([score()] + [blank]*5, strip=blank))
        self.assertFalse(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))
        self.assertGreater(cert["counters"]["source_minority_pixels"], 0)
        self.assertFalse(at(cert, 144, 20))

    def test_one_observation_strip_dot_is_unqualified(self):
        blank = score(); blank[20:22, 144:146] = 255
        cert = run_fixture(fixture([score()] + [blank]*5))
        self.assertTrue(findings(cert, "STRIP_CONTENT_UNSUPPORTED"))
        self.assertTrue(all(not f["qualified"] and len(f["supporters"]) == 1 for f in at(cert, 144, 20)))
        self.assertFalse(any(f["severity"] == "fail" for f in cert["findings"]))

    def test_added_strip_dot_requires_review(self):
        added = score(); added[84:87, 162:165] = 0
        cert = run_fixture(fixture(strip=added))
        self.assertTrue(findings(cert, "STRIP_CONTENT_UNSUPPORTED"))
        self.assertTrue(all(not f["qualified"] and f["supporters"] == [] for f in at(cert, 163, 85)))

    def test_one_added_staff_attached_pixel_cannot_use_tile_majority(self):
        added = score(); added[44, 96] = 0
        cert = run_fixture(fixture(strip=added))
        self.assertTrue(findings(cert, "STRIP_CONTENT_UNSUPPORTED"))
        self.assertTrue(all(not f["qualified"] for f in at(cert, 96, 44)))

    def test_cursor_over_note_in_two_frames_other_four_qualify(self):
        images = [cv2.cvtColor(score(), cv2.COLOR_GRAY2BGR) for _ in range(6)]
        for image in images[:2]:
            image[5:88, 111:116] = [0, 0, 255]
        cert = run_fixture(fixture(images, strip=cv2.cvtColor(score(), cv2.COLOR_GRAY2BGR)))
        self.assertEqual(cert["findings"], [])
        dot = at(cert, 113, 46)
        self.assertTrue(dot and all(f["qualified"] for f in dot))
        self.assertTrue(all(set(f["supporters"]) <= {f"obs-{i:06}" for i in range(2, 6)} for f in dot))

    def test_same_parked_cursor_state_is_not_two_witnesses(self):
        image = cv2.cvtColor(score(), cv2.COLOR_GRAY2BGR)
        image[5:88, 170:173] = [0, 0, 255]
        cert = run_fixture(fixture([image]*6, strip=cv2.cvtColor(score(), cv2.COLOR_GRAY2BGR)))
        self.assertTrue(findings(cert, "STRIP_CONTENT_UNSUPPORTED"))
        self.assertTrue(all(len(f["supporters"]) <= 1 for f in cert["features"]))

    def test_tampered_frame_one_pixel_fails_hook_zero_hash(self):
        data = fixture(); data[3]["obs-000000"][2, 2] = 254
        cert = run_fixture(data)
        self.assertEqual(len(findings(cert, "EVIDENCE_INTEGRITY")), 1)
        self.assertEqual(findings(cert, "EVIDENCE_INTEGRITY")[0]["severity"], "fail")

    def test_recomputed_embedded_hash_does_not_anchor_evidence(self):
        images = [score() for _ in range(6)]
        ledger = rl.record_obligations(source_video="synthetic", display_id="strip:sys-001", occurrence_id="sys-001",
            members=[{"id": f"obs-{i:06}", "timestamp": i, "image": im, "roi_origin": [0, 0],
                      "registration_shift": [0, 0], "registration_uncertainty": 0.} for i, im in enumerate(images)])
        data = fixture(images); ledger["observations"] = data[0]["observations"]
        data = (ledger, *data[1:])
        ev = ledger["items"][0]["evidence"][0]
        patch = rl.unpack_crop(ev["raw_patch"]); patch[0, 0] ^= 1
        ev["raw_patch"] = rl.pack_crop(patch)  # internally valid, externally false
        cert = run_fixture(data)
        self.assertTrue(findings(cert, "EVIDENCE_INTEGRITY"))

    def test_persistent_weak_contrast_40_is_qualified(self):
        marked = score(); marked[86:89, 145:148] = 215
        cert = run_fixture(fixture([marked]*3 + [score()]*3, strip=marked))
        weak = at(cert, 146, 87)
        self.assertTrue(weak)
        self.assertTrue(all(f["kind"] == "weak" and f["qualified"] and f["max_contrast"] == 40 for f in weak))
        self.assertEqual(cert["findings"], [])

    def test_persistent_weak_feature_erasure_fails(self):
        marked = score(); marked[86:89, 145:148] = 215
        cert = run_fixture(fixture([marked]*3 + [score()]*3, strip=score()))
        self.assertTrue(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))

    def test_antialias_attached_fringe_differences_are_context(self):
        fringe = score(); fringe[14, 8:184] = 215
        cert = run_fixture(fixture([fringe]*6, strip=score()))
        self.assertEqual(cert["findings"], [])
        cert = run_fixture(fixture(strip=fringe))
        self.assertEqual(cert["findings"], [])

    def test_rejected_observations_scanned_but_cannot_qualify(self):
        data = fixture()
        for obs in data[0]["observations"]:
            obs["associations"][0]["role"] = "excluded_candidate"
        cert = run_fixture(data)
        self.assertTrue(all(not f["qualified"] for f in cert["features"]))
        erased = score(); erased[20:22, 144:146] = 255
        data = (data[0], data[1], erased, data[3], data[4])
        cert = run_fixture(data)
        self.assertTrue(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))

    def test_association_only_observation_is_still_integrity_checked(self):
        data = fixture()
        data[0]["displays"][0]["members"].pop()
        data[3]["obs-000005"][0, 0] = 254
        cert = run_fixture(data)
        self.assertEqual(cert["counters"]["observations"], 6)
        self.assertTrue(findings(cert, "EVIDENCE_INTEGRITY"))

    def test_referenced_masks_and_tampered_mask_fail(self):
        data = fixture()
        with tempfile.TemporaryDirectory(prefix="wa-") as root:
            data[0]["evidence_root"] = root
            hidden = np.zeros(score().shape, np.uint8); hidden[10:80, 110:117] = 255
            path = Path(root)/"mask.png"; cv2.imwrite(str(path), hidden)
            member = data[0]["displays"][0]["members"][0]
            member["usable_ref"] = "all"
            member["occluded_ref"] = {"path": path.name, "sha256": vc.file_sha256(path)}
            cert = run_fixture(data)
            self.assertEqual(cert["findings"], [])
            hidden[0, 0] = 255; cv2.imwrite(str(path), hidden)
            cert = run_fixture(data)
            self.assertTrue(findings(cert, "EVIDENCE_INTEGRITY"))

    def test_residual_over_half_native_pixel_is_uninformative(self):
        data = fixture(shifts=[(1, 0)]*6)
        for member in data[0]["displays"][0]["members"]:
            member["transform"]["matrix"] = np.eye(3).tolist()
        cert = run_fixture(data)
        self.assertEqual(cert["counters"]["informative"], 0)
        self.assertEqual(cert["counters"]["uninformative"], 6)
        self.assertFalse(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))
        self.assertTrue(findings(cert, "SOURCE_REGISTRATION_UNRESOLVED"))

    def test_native_scale_and_recorded_chain_crop(self):
        data = fixture(shifts=[(0, 0)]*6)
        strip = data[2][8:92]
        chain = copy.deepcopy(data[4]); chain["stages"][0]["matrix"][1][2] = -8
        cert = run_fixture((data[0], data[1], strip, data[3], chain))
        self.assertEqual(cert["findings"], [])
        self.assertEqual(cert["counters"]["registrations"][0]["matrix"][1][2], -8)

    def test_residual_is_converted_to_native_frame_pixels(self):
        data = fixture(shifts=[(1, 0)]*6)
        for member in data[0]["displays"][0]["members"]:
            member["transform"]["matrix"] = np.eye(3).tolist()
        for observation in data[0]["observations"]:
            observation["work_scale"] = 4.
        cert = run_fixture(data)
        self.assertEqual(cert["counters"]["informative"], 6)
        self.assertTrue(all(0 < r["residual_registration_px"] < .5 for r in cert["counters"]["registrations"]))

    def test_multiple_display_chains_and_domain_ownership(self):
        data = fixture()
        second = copy.deepcopy(data[0]["displays"][0]); second["id"] = "jump:ep-1"
        data[0]["displays"].append(second)
        first_chain = copy.deepcopy(data[4]); first_chain["domain_strip"] = [0, 96]
        second_chain = copy.deepcopy(data[4]); second_chain["display_id"] = second["id"]
        second_chain["domain_strip"] = [96, 192]
        cert = run_fixture((*data[:4], {"sys-001": [first_chain, second_chain]}))
        self.assertEqual(cert["counters"]["observations"], 12)
        self.assertFalse(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))
        self.assertTrue(all(f["qualified"] for f in at(cert, 144, 20)))

    def test_one_observation_cannot_vote_twice_through_display_chains(self):
        data = fixture([score()])
        second = copy.deepcopy(data[0]["displays"][0]); second["id"] = "jump:ep-1"
        second["members"][0]["cursor_position"] = 120
        data[0]["displays"].append(second)
        second_chain = copy.deepcopy(data[4]); second_chain["display_id"] = second["id"]
        erased = score(); erased[20:22, 144:146] = 255
        cert = run_fixture((data[0], data[1], erased, data[3], [data[4], second_chain]))
        self.assertFalse(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))
        self.assertTrue(all(not f["qualified"] and len(set(f["supporters"])) == len(f["supporters"]) for f in cert["features"]))

    def test_certificate_feature_ids_unique_and_specific_finding_witnesses(self):
        erased = score(); erased[20:22, 144:146] = 255
        cert = run_fixture(fixture([score()]*3 + [erased]*3, strip=erased))
        ids = [f["id"] for f in cert["features"]]
        self.assertEqual(len(ids), len(set(ids)))
        for finding in findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"):
            witnesses = finding["detail"]["witness_observation_ids"]
            self.assertEqual(len(set(witnesses)), 2)
            self.assertTrue(set(witnesses) <= {"obs-000000", "obs-000001", "obs-000002"})

    def test_certificate_ids_do_not_reuse_component_tile_labels(self):
        image = score()
        rng = np.random.default_rng(0)
        ys = rng.integers(2, 98, 100); xs = rng.integers(2, 190, 100)
        image[ys, xs] = 0
        cert = run_fixture(fixture([image]*6, strip=image))
        ids = [f["id"] for f in cert["features"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(cert["findings"], [])

    def test_superseded_inventory_rejects_are_not_dropped(self):
        erased = score(); erased[20:22, 144:146] = 255
        data = fixture([score()]*2 + [erased]*4, strip=erased)
        data[0]["displays"][0]["members"] = data[0]["displays"][0]["members"][2:]
        data[0]["displays"].append({"id": "occ:ep-0", "inventory_only": True,
                                    "observations": [o["id"] for o in data[0]["observations"]]})
        data[0]["display_dispositions"] = [{"kind": "superseded_inventory", "display_id": "occ:ep-0",
                                           "retained_display_id": "strip:sys-001"}]
        for obs in data[0]["observations"][:2]:
            obs["associations"][0]["display_id"] = "occ:ep-0"
        cert = run_fixture(data)
        self.assertEqual(cert["counters"]["observations"], 6)
        self.assertTrue(findings(cert, "SOURCE_FEATURE_MISSING_IN_STRIP"))


if __name__ == "__main__":
    unittest.main()
