"""NMS, prompt-to-kind mapping, and the three detect-box rules. No model."""

from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "upscale"))

import numpy as np

import common
import detect
import lights
from test_lights import _area, _orange_scene


def _box(x0, y0, x1, y1, score, prompt) -> detect.DetectBox:
    return detect.DetectBox(
        x0=float(x0),
        y0=float(y0),
        x1=float(x1),
        y1=float(y1),
        score=float(score),
        prompt=prompt,
        kind=detect.kind_for_prompt(prompt),
    )


class DetectMappingTests(unittest.TestCase):
    def test_prompt_kinds_match_the_plan_table(self) -> None:
        fire = [
            "a burning torch",
            "a candle flame",
            "a brazier with fire",
            "a campfire",
            "a fireplace",
            "lava",
        ]
        steady = ["a glowing lantern", "a lamp"]
        magic = ["a glowing magical crystal", "a glowing portal", "glowing runes"]
        pool = ["a glowing window"]
        for prompt in fire:
            self.assertEqual(detect.kind_for_prompt(prompt), "fire")
        for prompt in steady:
            self.assertEqual(detect.kind_for_prompt(prompt), "steady")
        for prompt in magic:
            self.assertEqual(detect.kind_for_prompt(prompt), "magic")
        for prompt in pool:
            self.assertEqual(detect.kind_for_prompt(prompt), "pool")
        self.assertEqual(len(detect.PROMPTS), 12)
        self.assertEqual(set(detect.PROMPTS), set(detect.PROMPT_KIND))

    def test_unknown_prompt_raises(self) -> None:
        with self.assertRaises(KeyError):
            detect.kind_for_prompt("a dragon")


class DetectNmsTests(unittest.TestCase):
    def test_same_class_overlap_keeps_higher_score(self) -> None:
        a = _box(0, 0, 10, 10, 0.9, "a lamp")
        b = _box(1, 1, 11, 11, 0.4, "a lamp")
        kept = detect.nms_classwise([a, b], iou=0.5)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].score, 0.9)

    def test_different_classes_are_not_suppressed(self) -> None:
        a = _box(0, 0, 10, 10, 0.9, "a lamp")
        b = _box(1, 1, 11, 11, 0.8, "a burning torch")
        kept = detect.nms_classwise([a, b], iou=0.5)
        self.assertEqual(len(kept), 2)
        kinds = {box.kind for box in kept}
        self.assertEqual(kinds, {"steady", "fire"})

    def test_low_iou_same_class_keeps_both(self) -> None:
        a = _box(0, 0, 10, 10, 0.9, "a lamp")
        b = _box(50, 50, 60, 60, 0.8, "a lamp")
        kept = detect.nms_classwise([a, b], iou=0.5)
        self.assertEqual(len(kept), 2)

    def test_iou_of_identical_boxes_is_one(self) -> None:
        a = _box(0, 0, 10, 10, 0.5, "lava")
        self.assertAlmostEqual(detect.box_iou(a, a), 1.0)

    def test_region_sized_boxes_are_dropped(self) -> None:
        small = _box(0, 0, 80, 90, 0.4, "a lamp")
        huge = _box(0, 0, 800, 700, 0.9, "lava")
        self.assertTrue(detect.small_enough(small))
        self.assertFalse(detect.small_enough(huge))


class DetectBoxRuleTests(unittest.TestCase):
    def test_emitter_inside_lantern_box_becomes_steady(self) -> None:
        rgb = _orange_scene()
        boxes = [_box(350, 350, 370, 370, 0.5, "a glowing lantern")]
        result = lights.find_lights(_area(rgb), boxes)
        self.assertEqual(len(result.lights), 1)
        light = result.lights[0]
        self.assertEqual(light.kind, lights.KIND_STEADY)
        self.assertEqual(light.casts_shadow, 0)

    def test_higher_score_lantern_wins_over_a_lower_score_lava_box(self) -> None:
        rgb = _orange_scene()
        boxes = [
            _box(200, 200, 450, 450, 0.3, "lava"),
            _box(350, 350, 370, 370, 0.5, "a glowing lantern"),
        ]
        result = lights.find_lights(_area(rgb), boxes)
        self.assertEqual(result.lights[0].kind, lights.KIND_STEADY)
        self.assertEqual(result.lights[0].casts_shadow, 0)

    def test_emitter_inside_fire_box_keeps_fire_and_casts(self) -> None:
        rgb = _orange_scene()
        boxes = [_box(350, 350, 370, 370, 0.5, "a burning torch")]
        result = lights.find_lights(_area(rgb), boxes)
        self.assertEqual(len(result.lights), 1)
        light = result.lights[0]
        self.assertEqual(light.kind, lights.KIND_FIRE)
        self.assertEqual(light.casts_shadow, 1)

    def test_fire_box_lowers_score_threshold(self) -> None:
        rgb = _orange_scene()
        baseline = lights.find_lights(_area(rgb))
        self.assertEqual(len(baseline.lights), 1)
        score = baseline.lights[0].score
        raised = score * 1.2
        boxes = [_box(350, 350, 370, 370, 0.4, "a burning torch")]
        with unittest.mock.patch.object(lights, "SCORE_MIN", raised):
            without = lights.find_lights(_area(rgb))
            with_box = lights.find_lights(_area(rgb), boxes)
        self.assertEqual(len(without.lights), 0)
        self.assertEqual(len(with_box.lights), 1)

    def test_pool_box_with_lm_support_and_no_emitter_adds_a_pool(self) -> None:
        size = 256
        rgb = np.full((size, size, 3), 0.12, dtype=np.float32)
        area = _area(rgb)
        area.lm[0, 0] = np.array([0.2, 0.2, 0.2], dtype=np.float32)
        area.lm[12, 10] = np.array([1.0, 0.85, 0.4], dtype=np.float32)
        box = _box(160, 120, 176, 144, 0.4, "a glowing window")
        result = lights.find_lights(area, [box])
        pools = [item for item in result.lights if item.kind == lights.KIND_POOL]
        self.assertEqual(len(result.lights), 1)
        self.assertEqual(len(pools), 1)
        light = pools[0]
        self.assertAlmostEqual(light.x, 168.0, places=3)
        self.assertAlmostEqual(light.y, 144.0, places=3)
        self.assertEqual(light.z, 120.0)
        self.assertEqual(light.casts_shadow, 0)
        self.assertGreaterEqual(light.radius, 80.0)
        self.assertLessEqual(light.radius, 400.0)
        self.assertAlmostEqual(light.radius, float(np.clip(32.0, 80.0, 400.0)))

    def test_pool_box_without_lm_support_creates_nothing(self) -> None:
        size = 256
        rgb = np.full((size, size, 3), 0.12, dtype=np.float32)
        result = lights.find_lights(_area(rgb), [_box(160, 120, 176, 144, 0.4, "a glowing window")])
        self.assertEqual(len(result.lights), 0)

    def test_pool_box_with_an_emitter_does_not_add_a_second_light(self) -> None:
        rgb = _orange_scene()
        boxes = [_box(340, 340, 380, 380, 0.5, "a glowing window")]
        result = lights.find_lights(_area(rgb), boxes)
        self.assertEqual(len(result.lights), 1)
        self.assertEqual(result.lights[0].kind, lights.KIND_POOL)
        self.assertEqual(result.lights[0].source, "emitter")


if __name__ == "__main__":
    unittest.main()
