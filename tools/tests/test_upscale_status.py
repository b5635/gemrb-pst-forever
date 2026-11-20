"""Counts leftover / stale / incomplete upscale work without touching the GPU."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1]
_UPSCALE = _TOOLS / "upscale"
if str(_UPSCALE) not in sys.path:
    sys.path.insert(0, str(_UPSCALE))

from state import output_path, outputs_complete, png_stats  # noqa: E402
import status as up_status  # noqa: E402


class OutputLayout(unittest.TestCase):
    def test_paths(self):
        root = Path("C:/Games/GemRB/upscaled")
        self.assertEqual(output_path(root, "areas", "tis", "ar0100"), root / "areas" / "AR0100")
        self.assertEqual(output_path(root, "gui", "mos", "guiinv"), root / "gui" / "mos" / "GUIINV.png")
        self.assertEqual(output_path(root, "gui", "bmp", "port"), root / "gui" / "bmp" / "PORT.png")
        self.assertEqual(output_path(root, "gui", "bam", "guibtnb"), root / "gui" / "bam" / "GUIBTNB")
        self.assertEqual(output_path(root, "sprites", "bam", "dwlknofb"), root / "sprites" / "bam" / "DWLKNOFB")

    def test_png_stats_and_complete(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            self.assertEqual(png_stats(folder / "missing.png"), (0, 0))
            self.assertTrue(outputs_complete(0, 0))
            self.assertFalse(outputs_complete(0, 4))
            self.assertTrue(outputs_complete(4, 4))
            self.assertTrue(outputs_complete(5, 4))
            bam = folder / "bam"
            bam.mkdir()
            (bam / "0.png").write_bytes(b"x")
            (bam / "1.png").write_bytes(b"yy")
            (bam / "0.idx.png").write_bytes(b"idx")
            (bam / "notes.txt").write_text("ignore", encoding="utf-8")
            count, size = png_stats(bam)
            self.assertEqual(count, 2)
            self.assertEqual(size, 3)


class KindAndRecommend(unittest.TestCase):
    def test_kind_for(self):
        kind, _why = up_status._kind_for(None, 0, "m.safetensors", 2, True, None)
        self.assertEqual(kind, "leftover")
        kind, _why = up_status._kind_for(None, 3, "m.safetensors", 2, True, None)
        self.assertEqual(kind, "untracked")
        prev = {"sha1": "abc", "model": "m.safetensors", "scale": 2, "fp16": True, "outputs": 4}
        kind, _why = up_status._kind_for(prev, 4, "m.safetensors", 2, True, "abc")
        self.assertEqual(kind, "done")
        kind, _why = up_status._kind_for(prev, 1, "m.safetensors", 2, True, "abc")
        self.assertEqual(kind, "incomplete")
        kind, _why = up_status._kind_for(prev, 4, "m.safetensors", 2, True, "zzz")
        self.assertEqual(kind, "stale")
        kind, _why = up_status._kind_for(prev, 4, "other.pth", 2, True, None)
        self.assertEqual(kind, "stale")

    def test_recommend_leftover_sprites(self):
        counts = up_status._empty_counts()
        counts["gui"].total = 10
        counts["gui"].done = 10
        counts["areas"].total = 2
        counts["areas"].done = 2
        counts["sprites"].total = 100
        counts["sprites"].done = 13
        counts["sprites"].leftover = 87
        nxt = up_status.recommend(counts, True, [], True, True, False)
        self.assertEqual(nxt.action, "continue")
        self.assertEqual(nxt.categories, ["sprites"])
        self.assertIn("87", nxt.title)
        self.assertIn("Continue sprites", nxt.button)


class ScanTempTree(unittest.TestCase):
    def test_scan_counts_leftover_incomplete_stale(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw) / "work"
            out = Path(raw) / "upscaled"
            work.mkdir()
            (out / "gui" / "mos").mkdir(parents=True)
            (out / "areas" / "AR0100").mkdir(parents=True)
            (out / "sprites" / "bam" / "DONEBAM").mkdir(parents=True)
            (out / "gui" / "mos" / "MENUBG.png").write_bytes(b"png")
            (out / "areas" / "AR0100" / "0.png").write_bytes(b"png")
            (out / "sprites" / "bam" / "DONEBAM" / "0.png").write_bytes(b"png")
            classification = {
                "counts": {"gui": 1, "areas": 1, "sprites": 2, "skip": 0},
                "by_ext": {},
                "items": {
                    "gui": [{"name": "MENUBG", "ext": "mos"}],
                    "areas": [{"name": "AR0100", "ext": "tis"}],
                    "sprites": [
                        {"name": "DONEBAM", "ext": "bam"},
                        {"name": "LEFTBAM", "ext": "bam"},
                    ],
                    "skip": [],
                },
            }
            (work / "classification.json").write_text(json.dumps(classification), encoding="utf-8")
            state = {
                "items": {
                    "gui:mos:MENUBG": {
                        "sha1": "aaa",
                        "model": "old-model.pth",
                        "scale": 2,
                        "fp16": True,
                        "outputs": 1,
                    },
                    "areas:tis:AR0100": {
                        "sha1": "bbb",
                        "model": "4x-UltraSharp.safetensors",
                        "scale": 2,
                        "fp16": True,
                        "outputs": 8,
                    },
                    "sprites:bam:DONEBAM": {
                        "sha1": "ccc",
                        "model": "4x-UltraSharp.safetensors",
                        "scale": 2,
                        "fp16": True,
                        "outputs": 1,
                    },
                }
            }
            (work / "state.json").write_text(json.dumps(state), encoding="utf-8")
            game = Path(raw) / "game"
            game.mkdir()
            (game / "CHITIN.KEY").write_bytes(b"")
            report = up_status.scan(
                out=out,
                game=game,
                scale=2,
                fp16=True,
                hash_sources=False,
                work=work,
            )
            self.assertTrue(report.classification_ok)
            self.assertEqual(report.categories["sprites"].leftover, 1)
            self.assertEqual(report.categories["sprites"].leftover_names, ["LEFTBAM"])
            self.assertEqual(report.categories["areas"].incomplete, 1)
            self.assertEqual(report.categories["gui"].stale, 1)
            self.assertEqual(report.categories["sprites"].done, 1)
            self.assertEqual(report.next.action, "continue")
            self.assertEqual(report.next.categories, ["areas", "sprites"])
            text = up_status.format_report(report)
            self.assertIn("What to click", text)
            self.assertIn("LEFTBAM", text)


if __name__ == "__main__":
    unittest.main()
