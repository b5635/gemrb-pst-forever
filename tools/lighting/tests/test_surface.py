"""Normals, AO and key-light helpers for the surface stage."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "upscale"))

import numpy as np

import common
import lights
import surface


class SurfaceTests(unittest.TestCase):
    def test_blur_does_not_cross_wall_edges(self) -> None:
        h = np.zeros((32, 32), dtype=np.float32)
        h[:, 16:] = 80.0
        wall = np.zeros((32, 32), dtype=bool)
        wall[:, 16:] = True
        blurred = surface.blur_height(h, wall, sigma=1.0)
        # A pixel well inside the floor stays near 0; well inside the wall stays near 80.
        self.assertLess(float(blurred[16, 8]), 1.0)
        self.assertGreater(float(blurred[16, 24]), 79.0)
        # The two sides of the cut stay apart; a joint gaussian would mix them.
        self.assertLess(float(blurred[16, 15]), 5.0)
        self.assertGreater(float(blurred[16, 16]), 75.0)

    def test_downsample_normals_average_and_renorm(self) -> None:
        n = np.zeros((4, 4, 3), dtype=np.float32)
        n[:, :, 2] = 1.0
        n[0, 0] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        n[0, 1] = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        n[1, 0] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        n[1, 1] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        half = surface.downsample_normals(n, texel=2)
        self.assertEqual(half.shape, (2, 2, 3))
        length = float(np.linalg.norm(half[0, 0]))
        self.assertAlmostEqual(length, 1.0, places=5)
        # The 2x2 block averages (1,0,0)+(0,1,0)+(0,0,1)+(0,0,1) then renormalises.
        self.assertGreater(float(half[0, 0, 2]), float(half[0, 0, 0]))
        self.assertGreater(float(half[1, 1, 2]), 0.99)

    def test_normal_and_ao_writers_round_trip(self) -> None:
        n = np.zeros((2, 3, 3), dtype=np.float32)
        n[..., 2] = 1.0
        n[0, 1] = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        ao = np.array([[1.0, 0.5, 0.0], [0.25, 0.75, 1.0]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            n_path = root / "normal.bin"
            a_path = root / "ao.bin"
            surface.write_normal_bin(n_path, n)
            surface.write_ao_bin(a_path, ao)
            header_n, payload_n = common.read_map(n_path.read_bytes(), b"GLN1", 3)
            header_a, payload_a = common.read_map(a_path.read_bytes(), b"GLA1", 1)
            self.assertEqual((header_n.magic, header_n.w, header_n.h, header_n.texel), (b"GLN1", 3, 2, 2))
            self.assertEqual((header_a.magic, header_a.w, header_a.h, header_a.texel), (b"GLA1", 3, 2, 2))
            packed = np.frombuffer(payload_n, dtype=np.uint8).reshape(2, 3, 3)
            decoded = packed.astype(np.float32) / 255.0 * 2.0 - 1.0
            self.assertGreater(float(decoded[0, 0, 2]), 0.95)
            self.assertGreater(float(decoded[0, 1, 1]), 0.95)
            ao_bytes = np.frombuffer(payload_a, dtype=np.uint8).reshape(2, 3)
            self.assertEqual(int(ao_bytes[0, 0]), 255)
            self.assertEqual(int(ao_bytes[0, 2]), 0)
            self.assertEqual(int(ao_bytes[0, 1]), 128)

    def test_key_fit_points_shadows_away_from_the_light(self) -> None:
        size = 80
        h = np.zeros((size, size), dtype=np.float32)
        n = np.zeros((size, size, 3), dtype=np.float32)
        n[..., 2] = 1.0
        h[10:70, 10:70] = 20.0
        n[10:70, 10:70] = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        # Faces toward +x are brighter: the light is to the right, shadows fall left.
        L = 0.5 + 0.3 * n[..., 0]
        rgb = np.stack([L, L, L], axis=-1).astype(np.float32)
        alpha = np.full((size, size), 255, dtype=np.uint8)
        floor = h < 1.0
        lm = np.ones((size // 12 + 1, size // 16 + 1, 3), dtype=np.float32)
        result = lights.LightsResult(lights=[], tints=[], area_w=size, area_h=size)
        key = surface.compute_key(rgb, alpha, h, n, floor, lm, result)
        self.assertIsNotNone(key)
        assert key is not None
        self.assertLess(key.dir_x, -0.85)
        self.assertLess(abs(key.dir_y), 0.25)
        self.assertGreater(key.strength, 0.2)

    def test_key_omitted_when_shading_is_flat(self) -> None:
        size = 80
        h = np.full((size, size), 20.0, dtype=np.float32)
        n = np.zeros((size, size, 3), dtype=np.float32)
        n[..., 2] = 1.0
        rgb = np.full((size, size, 3), 0.4, dtype=np.float32)
        alpha = np.full((size, size), 255, dtype=np.uint8)
        floor = np.zeros((size, size), dtype=bool)
        lm = np.ones((8, 8, 3), dtype=np.float32)
        result = lights.LightsResult(lights=[], tints=[], area_w=size, area_h=size)
        key = surface.compute_key(rgb, alpha, h, n, floor, lm, result)
        self.assertIsNone(key)

    def test_ao_darkens_next_to_a_wall(self) -> None:
        size = 128
        h = np.zeros((size, size), dtype=np.float32)
        h[:, 90:100] = 80.0
        floor = np.ones((size, size), dtype=bool)
        floor[:, 90:100] = False
        lm = np.ones((size // 12 + 1, size // 16 + 1, 3), dtype=np.float32)
        ao = surface.compute_ao(h, floor, lm)
        open_val = float(ao[20, 10])
        near_val = float(ao[20, 42])
        self.assertGreater(open_val, 0.85)
        self.assertLess(near_val, open_val - 0.05)

    def test_lights_txt_keeps_light_lines_and_inserts_key(self) -> None:
        result = lights.LightsResult(
            lights=[
                lights.Light(
                    x=10.0,
                    y=20.0,
                    z=30.0,
                    radius=80.0,
                    r=1.0,
                    g=0.4,
                    b=0.1,
                    strength=0.8,
                    kind="fire",
                    casts_shadow=1,
                    score=1.0,
                    source="emitter",
                    emitter=(10.0, 8.0),
                )
            ],
            tints=[],
            area_w=100,
            area_h=80,
            key=(-0.2500, 0.9682, 0.5000, 1.0000, 0.9000, 0.8000),
        )
        text = lights.format_lights_txt(result)
        self.assertIn("version 1", text)
        self.assertIn("size 100 80", text)
        self.assertIn("key -0.2500 0.9682 0.5000 1.0000 0.9000 0.8000", text)
        self.assertIn("light 10.0000 20.0000 30.0000 80.0000 1.0000 0.4000 0.1000 0.8000 fire 1", text)
        payload = lights.lights_json("AR0202", result)
        round_trip = lights.result_from_json(payload)
        self.assertEqual(round_trip.key, result.key)
        self.assertEqual(len(round_trip.lights), 1)


if __name__ == "__main__":
    unittest.main()
