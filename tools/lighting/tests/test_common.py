"""Loader checks for the lighting survey. Run with the upscale venv:

    python -m unittest discover tools/lighting/tests
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[1] / "upscale"))

import numpy as np

import common
import ie_formats
import survey


def _wed_square() -> bytes:
    # Header, secondary header at 0x20, one polygon at 0x34, vertices at 0x46.
    buf = bytearray(0x56)
    buf[0:8] = b"WED V1.3"
    struct.pack_into("<I", buf, 0x14, 0x20)
    struct.pack_into("<I", buf, 0x20, 1)
    struct.pack_into("<I", buf, 0x24, 0x34)
    struct.pack_into("<I", buf, 0x28, 0x46)
    struct.pack_into("<II", buf, 0x34, 0, 4)
    struct.pack_into("<4H", buf, 0x3E, 0, 10, 0, 10)
    for index, (x, y) in enumerate(((0, 0), (10, 0), (10, 10), (0, 10))):
        struct.pack_into("<HH", buf, 0x46 + index * 4, x, y)
    return bytes(buf)


class CommonTests(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(common.ELEV_SIN, 0.75)
        self.assertEqual(common.T, 0.5625 / 0.4375)
        self.assertEqual(common.ONE_PLUS_T, 1.0 + common.T)

    def test_terrain_passable_set(self) -> None:
        text = common.TERRAIN_2DA.read_text(encoding="utf-8")
        self.assertEqual(common.walkable_indices(text), {1, 2, 3, 4, 5, 6, 7, 9, 11, 14, 15})

    def test_map_header_round_trip(self) -> None:
        cases = ((b"GLH1", 2, 0.0625), (b"GLN1", 3, 1.0), (b"GLA1", 1, 0.0625))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            blobs = []
            for magic, width, unit in cases:
                payload = bytes((index * 17) % 256 for index in range(3 * 2 * width))
                path = root / magic.decode("ascii")
                common.write_map(path, magic, 3, 2, 2, unit, payload, width)
                blob = path.read_bytes()
                blobs.append((magic, width, blob))
                header, got = common.read_map(blob, magic, width)
                self.assertEqual(header.magic, magic)
                self.assertEqual(header.version, 1)
                self.assertEqual((header.w, header.h, header.texel), (3, 2, 2))
                self.assertEqual(header.unit, unit)
                self.assertEqual(got, payload)
                self.assertEqual(len(blob), 32 + len(payload))
            with self.assertRaises(ValueError):
                common.read_map(blobs[1][2], b"GLH1", 2)
            with self.assertRaises(ValueError):
                common.read_map(blobs[0][2][:20], b"GLH1", 2)

    def test_polygon_fill_of_a_square(self) -> None:
        walls, doors, wall_count, door_count = common.read_wed_polygons(_wed_square())
        self.assertEqual((wall_count, door_count, len(doors)), (1, 0, 0))
        self.assertEqual(walls[0].tolist(), [[0, 0], [10, 0], [10, 10], [0, 10]])
        mask = common.fill_mask(20, 20, walls)
        # (6, 6) is inside the square. (0, 0) is a vertex, so the rasterizer
        # may include it. (15, 15) and (0, 15) are outside.
        self.assertTrue(mask[6, 6])
        self.assertFalse(mask[15, 15])
        self.assertFalse(mask[0, 15])
        self.assertGreater(int(mask.sum()), 40)

    def test_hover_baseline_is_not_part_of_the_polygon(self) -> None:
        buf = bytearray(_wed_square())
        # Five vertices: two baseline points, then a triangle. Flags bit WF_HOVER.
        buf.extend(b"\x00" * 4)
        struct.pack_into("<II", buf, 0x34, 0, 5)
        buf[0x3C] = common.WF_HOVER
        struct.pack_into("<HH", buf, 0x46, 99, 98)
        struct.pack_into("<HH", buf, 0x4A, 97, 96)
        struct.pack_into("<HH", buf, 0x4E, 1, 1)
        struct.pack_into("<HH", buf, 0x52, 4, 1)
        struct.pack_into("<HH", buf, 0x56, 1, 4)
        walls, _doors, _wall_count, _door_count = common.read_wed_polygons(bytes(buf))
        self.assertEqual(walls[0].tolist(), [[1, 1], [4, 1], [1, 4]])

    def test_zero_area_polygon_is_dropped(self) -> None:
        buf = bytearray(_wed_square())
        struct.pack_into("<4H", buf, 0x3E, 5, 5, 0, 10)
        walls, _doors, wall_count, _door_count = common.read_wed_polygons(bytes(buf))
        self.assertEqual(wall_count, 1)
        self.assertEqual(walls, [])

    def test_are_animation_record(self) -> None:
        buf = bytearray(0xB4 + 0x4C)
        buf[0:8] = b"AREAV1.0"
        buf[8:16] = b"AR0202\x00\x00"
        struct.pack_into("<I", buf, 0xAC, 1)
        struct.pack_into("<I", buf, 0xB0, 0xB4)
        base = 0xB4
        struct.pack_into("<HH", buf, base + 0x20, 100, 200)
        buf[base + 0x28 : base + 0x30] = b"TORCH1\x00\x00"
        struct.pack_into("<I", buf, base + 0x34, common.PST_BLEND_BIT)
        wed, anims = common.read_area_anims(bytes(buf))
        self.assertEqual(wed, "AR0202")
        self.assertEqual(anims, [(100, 200, "TORCH1", common.PST_BLEND_BIT)])

    def test_floor_mask_erodes_one_cell_and_skips_unknown(self) -> None:
        walkable = np.ones((5, 5), dtype=bool)
        wall = np.zeros((72, 96), dtype=bool)
        alpha = np.full((72, 96), 255, dtype=np.uint8)
        wall[30, 40] = True
        alpha[30, 41] = 0
        floor = common.make_floor_mask(walkable, wall, alpha)
        # Inner cell (2, 2) survives. Its wall pixel and transparent neighbour do not.
        self.assertTrue(floor[30, 36])
        self.assertFalse(floor[30, 40])
        self.assertFalse(floor[30, 41])
        # The outer ring of cells is eroded away.
        self.assertFalse(floor[6, 8])
        # Past the search map (row 5, column 5) is unknown, not floor.
        self.assertFalse(floor[66, 40])
        self.assertFalse(floor[30, 88])
        self.assertFalse(np.any(floor & wall))

    def test_ar0202_shapes_match_survey_row(self) -> None:
        game = common.DEFAULT_GAME
        self.assertTrue((game / "CHITIN.KEY").is_file(), f"game not found at {game}")
        index = ie_formats.ResourceIndex(game, common.BIF_CACHE)
        self.assertGreater(len(index.names("are")), 0)
        area = common.load_area(index, "AR0202")
        row = survey.survey_row(area)
        self.assertEqual((row["area_h"], row["area_w"]), area.rgb.shape[:2])
        self.assertEqual((row["lm_h"], row["lm_w"]), area.lm.shape[:2])
        self.assertEqual(area.sr.shape, area.walkable.shape)
        self.assertEqual(area.ht.shape, area.sr.shape)
        self.assertEqual(area.lm.shape[:2], area.sr.shape)
        self.assertEqual(sorted((row["lm_w"], row["lm_h"])), [272, 320])
        self.assertEqual(area.wall_mask.shape, area.rgb.shape[:2])
        self.assertEqual(area.floor_mask.shape, area.rgb.shape[:2])
        self.assertEqual(area.alpha.shape, area.rgb.shape[:2])
        self.assertEqual(row["wall_polygons"], area.wall_count)
        self.assertEqual(row["door_count"], area.door_count)
        self.assertEqual(row["wed"], "AR0202")
        self.assertEqual(area.rgb.dtype, np.float32)
        self.assertEqual(area.alpha.dtype, np.uint8)
        self.assertGreaterEqual(float(area.rgb.min()), 0.0)
        self.assertLessEqual(float(area.rgb.max()), 1.0)
        self.assertFalse(np.any(area.floor_mask & area.wall_mask))
        self.assertFalse(np.any(area.floor_mask & (area.alpha != 255)))
        self.assertGreater(area.wall_count, 0)
        self.assertGreater(int(area.walkable.sum()), 0)


if __name__ == "__main__":
    unittest.main()
