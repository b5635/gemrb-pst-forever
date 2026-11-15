"""Synthetic checks for tools/vve_infopoints.py."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import vve_infopoints as vve


def pack_region(*, typ=1, strref=100, dlg="") -> bytes:
    rec = bytearray(0xC4)
    struct.pack_into("<H", rec, 0x20, typ)
    struct.pack_into("<I", rec, 0x64, strref)
    if dlg:
        raw = dlg.encode("ascii")[:8]
        rec[0xBC : 0xBC + len(raw)] = raw
    return bytes(rec)


class ExamineRows(unittest.TestCase):
    def test_unique_info_text_only(self):
        regions = [
            {"type": 1, "strref": 10, "dlg": ""},
            {"type": 1, "strref": 10, "dlg": ""},
            {"type": 1, "strref": 11, "dlg": "DSSKULL"},
            {"type": 0, "strref": 12, "dlg": ""},
            {"type": 1, "strref": 0, "dlg": ""},
            {"type": 1, "strref": 0xFFFFFFFF, "dlg": ""},
            {"type": 1, "strref": 13, "dlg": ""},
        ]
        texts = {10: "Vines with black leaves.", 11: "too far", 12: "trap", 13: "A stove."}
        rows = vve.rows_from_regions(regions, texts)
        self.assertEqual([row["StrRef"] for row in rows], [10, 13])
        self.assertEqual(rows[0]["SoundResRef"], "VV10")
        self.assertEqual(rows[0]["Speaker"], "Narrator")
        self.assertEqual(rows[0]["Action"], "generate")
        self.assertEqual(rows[1]["Text"], "A stove.")

    def test_skip_plan_and_empty_text(self):
        regions = [
            {"type": 1, "strref": 10, "dlg": ""},
            {"type": 1, "strref": 14, "dlg": ""},
        ]
        texts = {10: "keep", 14: ""}
        rows = vve.rows_from_regions(regions, texts, skip={10})
        self.assertEqual(rows, [])

    def test_parse_are_region(self):
        body = pack_region(typ=1, strref=16620)
        header = bytearray(0x100)
        header[0:8] = b"AREAV1.0"
        struct.pack_into("<H", header, 0x5A, 1)
        struct.pack_into("<I", header, 0x5C, 0x100)
        regions = vve.parse_regions(bytes(header) + body)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["type"], 1)
        self.assertEqual(regions[0]["strref"], 16620)
        self.assertEqual(regions[0]["dlg"], "")

    def test_fallback_fits_resref(self):
        self.assertLessEqual(len(vve.fallback_resref(68032)), 8)
        self.assertEqual(vve.fallback_resref(16620), "VV16620")


if __name__ == "__main__":
    unittest.main()
