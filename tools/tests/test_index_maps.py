"""Nearest index maps used for live PST creature recolour."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

_TOOLS = Path(__file__).resolve().parents[1]
_UPSCALE = _TOOLS / "upscale"
if str(_UPSCALE) not in sys.path:
    sys.path.insert(0, str(_UPSCALE))

from index_maps import residual_rgb, save_indexed_png, scale_nearest  # noqa: E402


class ScaleNearest(unittest.TestCase):
    def test_repeats_each_index(self):
        src = np.array([[10, 20], [30, 40]], dtype=np.uint8)
        out = scale_nearest(src, 2)
        self.assertEqual(out.shape, (4, 4))
        self.assertEqual(int(out[0, 0]), 10)
        self.assertEqual(int(out[0, 1]), 10)
        self.assertEqual(int(out[1, 0]), 10)
        self.assertEqual(int(out[1, 2]), 20)
        self.assertEqual(int(out[2, 3]), 40)
        self.assertEqual(int(out[3, 3]), 40)

    def test_rejects_scale_one(self):
        with self.assertRaises(ValueError):
            scale_nearest(np.zeros((2, 2), dtype=np.uint8), 1)


class SaveIndexed(unittest.TestCase):
    def test_roundtrip_keeps_indices_and_palette(self):
        pal = np.zeros((256, 3), dtype=np.uint8)
        pal[7] = [9, 8, 7]
        indices = np.array([[7, 0], [1, 7]], dtype=np.uint8)
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "0.idx.png"
            save_indexed_png(path, indices, pal, 0)
            with Image.open(path) as image:
                self.assertEqual(image.mode, "P")
                self.assertEqual(image.size, (2, 2))
                pix = np.array(image)
                self.assertEqual(int(pix[0, 0]), 7)
                self.assertEqual(int(pix[0, 1]), 0)
                self.assertEqual(int(pix[1, 0]), 1)
                self.assertEqual(int(pix[1, 1]), 7)
                plte = image.getpalette() or []
                self.assertEqual(plte[7 * 3 : 7 * 3 + 3], [9, 8, 7])


class ResidualShift(unittest.TestCase):
    def test_extra_colour_follows_the_slot_ramp(self):
        orig = np.zeros((256, 3), dtype=np.uint8)
        live = np.zeros((256, 3), dtype=np.uint8)
        orig[10] = [40, 20, 10]
        live[10] = [200, 20, 10]
        extra = np.array([50, 30, 18], dtype=np.uint8)
        self.assertEqual(list(residual_rgb(extra, orig, live, 10)), [210, 30, 18])

    def test_key_and_shadow_are_left_alone(self):
        orig = np.zeros((256, 3), dtype=np.uint8)
        live = np.zeros((256, 3), dtype=np.uint8)
        live[0] = [255, 0, 0]
        live[1] = [0, 255, 0]
        rgb = np.array([12, 8, 4], dtype=np.uint8)
        self.assertEqual(list(residual_rgb(rgb, orig, live, 0)), [12, 8, 4])
        self.assertEqual(list(residual_rgb(rgb, orig, live, 1)), [12, 8, 4])


if __name__ == "__main__":
    unittest.main()
