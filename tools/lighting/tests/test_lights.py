"""Synthetic checks for the lights stage. Run with the upscale venv:

    python -m unittest discover tools/lighting/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "upscale"))

import numpy as np

import common
import lights


def _area(rgb: np.ndarray, anims=None) -> common.Area:
    height, width = rgb.shape[:2]
    gh = max(1, (height + common.CELL_H - 1) // common.CELL_H)
    gw = max(1, (width + common.CELL_W - 1) // common.CELL_W)
    return common.Area(
        wed="TEST",
        tis="TEST",
        rgb=np.ascontiguousarray(rgb, dtype=np.float32),
        alpha=np.full((height, width), 255, dtype=np.uint8),
        lm=np.ones((gh, gw, 3), dtype=np.float32),
        sr=np.ones((gh, gw), dtype=np.uint8),
        ht=np.full((gh, gw), 128, dtype=np.uint8),
        walkable=np.ones((gh, gw), dtype=bool),
        walls=[],
        doors=[],
        wall_count=0,
        door_count=0,
        wall_mask=np.zeros((height, width), dtype=bool),
        floor_mask=np.ones((height, width), dtype=bool),
        anims=list(anims or []),
    )


def _orange_scene(two_cores: bool = False, white_rect: bool = False) -> np.ndarray:
    rng = np.random.RandomState(0)
    size = 512
    rgb = np.full((size, size, 3), 0.15, dtype=np.float32)
    rgb += rng.normal(0.0, 0.008, rgb.shape).astype(np.float32)
    rgb = np.clip(rgb, 0.0, 1.0)
    orange = np.array([1.0, 0.42, 0.03], dtype=np.float32)
    yy, xx = np.ogrid[:size, :size]
    hx, hy = 360, 360
    cores = [(hx, hy)]
    if two_cores:
        cores = [(hx - 5, hy), (hx + 5, hy)]
    dist2 = (yy - hy).astype(np.float32) ** 2 + (xx - hx).astype(np.float32) ** 2
    gauss = np.exp(-dist2 / (2.0 * 20.0 ** 2)).astype(np.float32)
    rgb += gauss[..., None] * (orange - 0.15) * 0.5
    for cx, cy in cores:
        rgb[cy - 4 : cy + 4, cx - 2 : cx + 3] = orange
    rgb = np.clip(rgb, 0.0, 1.0)
    if white_rect:
        rgb[20:220, 20:320] = 1.0
    return rgb


class LightsTests(unittest.TestCase):
    def test_orange_core_with_halo_is_one_fire_light(self) -> None:
        result = lights.find_lights(_area(_orange_scene()))
        self.assertEqual(len(result.lights), 1)
        light = result.lights[0]
        self.assertEqual(light.kind, lights.KIND_FIRE)
        self.assertLess(np.hypot(light.emitter[0] - 360.0, light.emitter[1] - 360.0), 2.0)
        self.assertEqual(light.r, 1.0)
        self.assertLess(light.b, 0.5)
        self.assertGreaterEqual(light.radius, 60.0)
        self.assertLessEqual(light.radius, 400.0)

    def test_large_white_rectangle_is_not_a_light(self) -> None:
        result = lights.find_lights(_area(_orange_scene(white_rect=True)))
        self.assertEqual(len(result.lights), 1)
        light = result.lights[0]
        self.assertLess(np.hypot(light.emitter[0] - 360.0, light.emitter[1] - 360.0), 2.0)
        self.assertEqual(light.kind, lights.KIND_FIRE)

    def test_two_close_cores_merge(self) -> None:
        result = lights.find_lights(_area(_orange_scene(two_cores=True)))
        self.assertEqual(len(result.lights), 1)
        light = result.lights[0]
        self.assertLess(np.hypot(light.emitter[0] - 360.0, light.emitter[1] - 360.0), 8.0)

    def test_blendblack_animation_removes_the_light(self) -> None:
        anims = [(360, 360, "TORCH", common.PST_BLEND_BIT)]
        result = lights.find_lights(_area(_orange_scene(), anims=anims))
        self.assertEqual(len(result.lights), 0)


if __name__ == "__main__":
    unittest.main()
