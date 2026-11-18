"""Read-only access to the Planescape: Torment Enhanced Edition install (chitin.key + BIFs).

Never writes into the EE folder. The BIF inflation cache goes to `cache`.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upscale"))
import ie_formats  # noqa: E402

DEFAULT_EE = Path(r"D:\GOG Games\Planescape Torment - Enhanced Edition")
DEFAULT_CACHE = Path(__file__).resolve().parent / "cache"

# The correct type map (ee_pull.py's), not ee_gui_survey.py's.
TYPES = {
    0x0001: "bmp", 0x0002: "mve", 0x0004: "wav", 0x0006: "plt", 0x03E8: "bam", 0x03E9: "wed",
    0x03EA: "chu", 0x03EB: "tis", 0x03EC: "mos", 0x03ED: "itm", 0x03EE: "spl", 0x03EF: "bcs",
    0x03F0: "ids", 0x03F1: "cre", 0x03F2: "are", 0x03F3: "dlg", 0x03F4: "2da", 0x03F5: "gam",
    0x03F6: "sto", 0x03F7: "wmp", 0x03F8: "eff", 0x03F9: "bs", 0x03FB: "vvc", 0x03FD: "pro",
    0x0400: "fnt", 0x0402: "gui", 0x0404: "pvrz", 0x0405: "glsl", 0x0408: "menu", 0x0409: "lua",
    0x040A: "ttf", 0x040B: "png", 0x0802: "ini", 0x0803: "src",
}


def inflate(blob: bytes) -> bytes:
    """Undo the zlib wrapper of MOSC/BAMC/CHUC files."""
    if blob[:4] in (b"MOSC", b"BAMC", b"CHUC"):
        return zlib.decompress(blob[12:])
    return blob


class EEData:
    def __init__(self, root: Path = DEFAULT_EE, cache: Path = DEFAULT_CACHE):
        self.root = Path(root)
        self.cache = Path(cache)
        key = self.root / "chitin.key"
        if not key.is_file():
            raise FileNotFoundError(f"no chitin.key in {self.root}")
        data = key.read_bytes()
        bif_count, res_count, bif_off, res_off = struct.unpack_from("<4I", data, 8)
        self.bifs: list[str] = []
        for i in range(bif_count):
            e = bif_off + i * 12
            name_off = ie_formats._u32(data, e + 4)
            name_len = ie_formats._u16(data, e + 8)
            self.bifs.append(ie_formats._clean_bif_name(data[name_off:name_off + name_len]))
        self.index: dict[tuple[str, str], tuple[int, int]] = {}
        for i in range(res_count):
            e = res_off + i * 14
            name = ie_formats.resref(data[e:e + 8])
            typ = ie_formats._u16(data, e + 8)
            loc = ie_formats._u32(data, e + 10)
            self.index.setdefault((name, TYPES.get(typ, f"{typ:#x}")), (loc, (loc >> 20) & 0xFFF))
        self._readers: dict = {}

    def has(self, name: str, ext: str) -> bool:
        return (name.upper(), ext) in self.index

    def names(self, ext: str) -> list[str]:
        return sorted(n for n, e in self.index if e == ext)

    def read(self, name: str, ext: str) -> bytes:
        loc, bi = self.index[(name.upper(), ext)]
        if bi not in self._readers:
            path = ie_formats.find_bif(self.root, self.bifs[bi])
            self._readers[bi] = ie_formats._Bif(path, self.cache) if path else None
        reader = self._readers[bi]
        if reader is None:
            raise KeyError(f"BIF missing: {self.bifs[bi]}")
        return reader.read(loc, ext)
