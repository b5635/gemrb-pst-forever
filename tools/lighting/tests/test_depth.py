"""Calibration and height-map checks for the depth stage.

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
import depth


def _ortho_box(size: int = 256, box_x0: int = 80, box_x1: int = 160, box_y0: int = 120, box_y1: int = 200, noise: float = 0.2):
    """Floor plane plus a camera-facing box of known height, and a fake affine p."""
    ys = np.arange(size, dtype=np.float32)[:, None]
    xs = np.arange(size, dtype=np.float32)[None, :]
    front = (xs >= box_x0) & (xs < box_x1) & (ys >= box_y0) & (ys < box_y1)
    true_h = np.where(front, box_y1 - ys, 0.0).astype(np.float32)
    d = -ys - true_h * np.float32(common.ONE_PLUS_T)
    a = -1.7
    c = 12.0
    p = ((d - c) / a).astype(np.float32)
    rng = np.random.RandomState(0)
    p = p + rng.normal(0.0, noise, p.shape).astype(np.float32)
    floor = ~front
    alpha = np.full((size, size), 255, dtype=np.uint8)
    return true_h, p, floor, front, alpha, box_y1 - box_y0


class DepthTests(unittest.TestCase):
    def test_box_calibration(self) -> None:
        true_h, p, floor, front, alpha, box_h = _ortho_box()
        h, metrics = depth.calibrate_from_p(p, floor, front, alpha, tile=256, overlap=32)
        floor_err = np.abs(h[floor])
        band = front & (true_h >= 70.0)
        recovered = float(np.median(h[band]))
        expect = float(np.median(true_h[band]))
        self.assertLess(float(np.median(floor_err)), 1.0)
        self.assertGreater(recovered, 0.0)
        self.assertLess(abs(recovered - expect) / box_h, 0.10)
        self.assertLess(metrics["residual"], 2.0)

    def test_height_to_normals(self) -> None:
        true_h, _p, floor, front, _alpha, _box_h = _ortho_box()
        normals = depth.height_to_normals(true_h)
        floor_n = normals[floor]
        # Stay away from the box silhouette where the difference mixes floor and wall.
        inner = np.zeros_like(front)
        inner[130:190, 90:150] = True
        wall_n = normals[inner]
        mean_floor = floor_n.mean(axis=0)
        mean_wall = wall_n.mean(axis=0)
        self.assertGreater(mean_floor[2], 0.95)
        self.assertLess(abs(mean_floor[0]), 0.08)
        self.assertLess(abs(mean_floor[1]), 0.08)
        self.assertGreater(mean_wall[1], 0.90)
        self.assertLess(abs(mean_wall[0]), 0.12)
        self.assertLess(abs(mean_wall[2]), 0.20)

    def test_unanchored_propagation(self) -> None:
        width, height = 112, 64
        tile, overlap = 64, 16
        ys = np.arange(height, dtype=np.float32)[:, None]
        xs = np.arange(width, dtype=np.float32)[None, :]
        true_h = np.broadcast_to(xs >= 64, (height, width)).astype(np.float32) * 40.0
        d = -ys - true_h * np.float32(common.ONE_PLUS_T)
        a = -1.4
        c = 5.0
        p = ((d - c) / a).astype(np.float32)
        rng = np.random.RandomState(1)
        p = p + rng.normal(0.0, 0.05, p.shape).astype(np.float32)
        floor = np.broadcast_to(xs < 48, (height, width)).copy()
        wall = np.broadcast_to(xs >= 64, (height, width)).copy()
        alpha = np.full((height, width), 255, dtype=np.uint8)
        h, metrics = depth.calibrate_from_p(p, floor, wall, alpha, tile=tile, overlap=overlap)
        self.assertEqual(metrics["unanchored"], 0)
        right = h[:, 80:100]
        self.assertGreater(right.size, 0)
        med = float(np.median(right))
        self.assertLess(abs(med - 40.0) / 40.0, 0.05)

    def test_height_bin_round_trip(self) -> None:
        h = np.array([[0.0, 1.0, 2.0, 3.0], [4.0, 8.0, 16.0, 32.0]], dtype=np.float32)
        w, hh, payload = depth.encode_height(h, texel=2, unit=0.0625)
        self.assertEqual((w, hh), (2, 1))
        values = np.frombuffer(payload, dtype="<u2").reshape(hh, w)
        # 2x2 max of the four left pixels is 8, of the right is 32.
        self.assertEqual(int(values[0, 0]), int(round(8.0 / 0.0625)))
        self.assertEqual(int(values[0, 1]), int(round(32.0 / 0.0625)))


if __name__ == "__main__":
    unittest.main()
