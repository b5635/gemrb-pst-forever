"""Synthetic checks for tools/vve_floats.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import vve_floats as vve


SAMPLE_FLOAT = (
    b"AC\n210OB\n0 0 0 0 0 0 0 0 0 0 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"OB\n0 0 0 0 0 0 0 0 0 1 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"OB\n0 0 0 0 0 0 0 0 0 0 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"32196 0 0 0 0\"\" \"\" AC\n"
)
SAMPLE_RND = (
    b"AC\n212OB\n0 0 0 0 0 0 0 0 0 0 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"OB\n0 0 0 0 0 0 0 0 0 1 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"OB\n0 0 0 0 0 0 0 0 0 0 0 0 0 0 [-1.-1.-1.-1] \"\"OB\n"
    b"0 0 0 0 0\"1500aca2\" \"\" AC\n"
)


class FloatRows(unittest.TestCase):
    def test_parse_floatmessage(self):
        refs, pools = vve.parse_bcs_floats(SAMPLE_FLOAT)
        self.assertEqual(refs, [32196])
        self.assertEqual(pools, [])

    def test_parse_floatmessagernd(self):
        refs, pools = vve.parse_bcs_floats(SAMPLE_RND)
        self.assertEqual(refs, [])
        self.assertEqual(pools, ["1500ACA2"])

    def test_src_entries(self):
        import struct

        blob = struct.pack("<I", 2) + struct.pack("<II", 51046, 1) + struct.pack("<II", 51047, 1)
        self.assertEqual(vve.parse_src(blob), [51046, 51047])

    def test_looks_spoken(self):
        self.assertTrue(vve.looks_spoken('"Deaders?"'))
        self.assertTrue(vve.looks_spoken("::Yawn::"))
        self.assertTrue(vve.looks_spoken("*Oof*"))
        self.assertTrue(vve.looks_spoken('"Them boxes sure are heavy!"'))
        self.assertFalse(vve.looks_spoken("POUCH Weight: 0  A small bag."))
        self.assertFalse(vve.looks_spoken("Morte Taunts 1"))
        self.assertFalse(vve.looks_spoken("Ghoul Male Battle Cry 1 (Approach 1)"))
        self.assertFalse(vve.looks_spoken(""))

    def test_skip_plan_and_labels(self):
        hits = {8161: ["0100MHUL"], 61943: ["X"], 10: ["0100MHUL"]}
        script_dialogs = {"0100MHUL": ["DMHULT"]}
        texts = {
            8161: '"Deaders?"',
            61943: "Morte Taunts 1",
            10: '"already in plan"',
        }
        speakers = {"DMHULT": "Mhult"}
        voices = {"DMHULT": "nwn:demo"}
        rows = vve.rows_from_hits(hits, script_dialogs, texts, speakers, voices, skip={10})
        self.assertEqual([row["StrRef"] for row in rows], [8161])
        self.assertEqual(rows[0]["Speaker"], "Mhult")
        self.assertEqual(rows[0]["Voice"], "nwn:demo")
        self.assertEqual(rows[0]["SoundResRef"], "VV8161")

    def test_shared_strref_picks_common_dialog(self):
        hits = {27432: ["A", "B", "B"]}
        script_dialogs = {"A": ["DLG1"], "B": ["DLG2"]}
        texts = {27432: '"Help! Guards! I\'m being attacked!"'}
        speakers = {"DLG1": "One", "DLG2": "Two"}
        voices = {"DLG2": "nwn:two"}
        rows = vve.rows_from_hits(hits, script_dialogs, texts, speakers, voices)
        self.assertEqual(rows[0]["Speaker"], "Two")
        self.assertEqual(rows[0]["Voice"], "nwn:two")


if __name__ == "__main__":
    unittest.main()
