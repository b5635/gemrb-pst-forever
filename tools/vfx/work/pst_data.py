"""Layered PST resource reader for the spell-visuals survey.

Search order mirrors GemRB (core/Interface.cpp): gemrb override/pst, override/shared,
the game's override folder, chitin.key, then gemrb unhardcoded/pst and unhardcoded/shared.
Classic PST has no PRO or VVC files; GemRB supplies them in unhardcoded/.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools" / "upscale"))

import ie_formats  # noqa: E402

GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
GEMRB = REPO / "gemrb"
CACHE = HERE / "cache"

EXTRA_TYPES = {
    0x03EF: "bcs",
    0x03F0: "ids",
    0x03F4: "2da",
    0x03F8: "eff",
    0x03FB: "vvc",
    0x03FC: "vef",
    0x03FD: "pro",
}
ie_formats.EXT_BY_TYPE.update(EXTRA_TYPES)
ie_formats.WANTED.update(EXTRA_TYPES.values())

LAYERS = [
    ("gemrb-override", GEMRB / "override" / "pst"),
    ("gemrb-override-shared", GEMRB / "override" / "shared"),
    ("game-override", GAME / "override"),
    ("chitin", None),
    ("gemrb-unhardcoded", GEMRB / "unhardcoded" / "pst"),
    ("gemrb-unhardcoded-shared", GEMRB / "unhardcoded" / "shared"),
]


def u8(b, o):
    return b[o]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def s16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def s32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def rr(b, o):
    return ie_formats.resref(b[o : o + 8])


class ChitinOnly(ie_formats.ResourceIndex):
    """KEY/BIF entries only; override folders are separate layers here."""

    def _add_tree(self, folder: Path, replace: bool) -> None:
        return


class Resources:
    """`(name, ext) -> bytes` with the GemRB layer that supplied it."""

    def __init__(self):
        self.chitin = ChitinOnly(GAME, CACHE)
        self.layer_files: dict[str, dict[tuple[str, str], Path]] = {}
        for label, folder in LAYERS:
            if folder is None:
                continue
            files = {}
            if folder.is_dir():
                for path in folder.iterdir():
                    if path.is_file():
                        ext = path.suffix.lower().lstrip(".")
                        files.setdefault((path.stem.upper(), ext), path)
            self.layer_files[label] = files
        self.chitin_keys = set(self.chitin.loaders)
        self._chitin_loaders = self.chitin.loaders

    def source(self, name: str, ext: str) -> str | None:
        key = (name.upper(), ext.lower())
        for label, _ in LAYERS:
            if label == "chitin":
                if key in self.chitin_keys:
                    return label
            elif key in self.layer_files[label]:
                return label
        return None

    def has(self, name: str, ext: str) -> bool:
        return self.source(name, ext) is not None

    def get(self, name: str, ext: str) -> bytes:
        key = (name.upper(), ext.lower())
        src = self.source(name, ext)
        if src is None:
            raise KeyError(key)
        if src == "chitin":
            return self._chitin_loaders[key]()
        return self.layer_files[src][key].read_bytes()

    def get_chitin(self, name: str, ext: str) -> bytes | None:
        key = (name.upper(), ext.lower())
        if key in self.chitin_keys:
            return self._chitin_loaders[key]()
        return None

    def names(self, ext: str) -> list[str]:
        ext = ext.lower()
        out = set()
        for label, _ in LAYERS:
            if label == "chitin":
                out.update(n for n, e in self.chitin_keys if e == ext)
            else:
                out.update(n for n, e in self.layer_files[label] if e == ext)
        return sorted(out)

    def count_by_layer(self, ext: str) -> dict[str, int]:
        ext = ext.lower()
        res = {}
        for label, _ in LAYERS:
            if label == "chitin":
                res[label] = sum(1 for n, e in self.chitin_keys if e == ext)
            else:
                res[label] = sum(1 for n, e in self.layer_files[label] if e == ext)
        return res


# ---------------------------------------------------------------- TLK


class Tlk:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        assert self.data[:8] == b"TLK V1  ", self.data[:8]
        self.count = u32(self.data, 0x0A)
        self.base = u32(self.data, 0x0E)

    def __call__(self, strref: int) -> str:
        if strref < 0 or strref >= self.count or strref == 0xFFFFFFFF:
            return ""
        e = 0x12 + strref * 26
        off = u32(self.data, e + 18)
        ln = u32(self.data, e + 22)
        raw = self.data[self.base + off : self.base + off + ln]
        return raw.decode("cp1252", "replace").replace("\r", " ").replace("\n", " ").strip()


# ---------------------------------------------------------------- effects


def parse_fx(b: bytes, o: int) -> dict:
    return {
        "opcode": u16(b, o),
        "target": u8(b, o + 2),
        "power": u8(b, o + 3),
        "p1": u32(b, o + 4),
        "p2": u32(b, o + 8),
        "timing": u8(b, o + 0x0C),
        "resist": u8(b, o + 0x0D),
        "duration": u32(b, o + 0x0E),
        "prob1": u8(b, o + 0x12),
        "prob2": u8(b, o + 0x13),
        "res": rr(b, o + 0x14),
        "dice_thrown": u32(b, o + 0x1C),
        "dice_sides": u32(b, o + 0x20),
        "save": u32(b, o + 0x24),
        "save_bonus": s32(b, o + 0x28),
    }


def parse_spl(b: bytes) -> dict | None:
    if b[:8] != b"SPL V1  ":
        return None
    spl = {
        "name_strref": u32(b, 0x08),
        "name_id_strref": u32(b, 0x0C),
        "completion_sound": rr(b, 0x10),
        "flags": u32(b, 0x18),
        "type": u16(b, 0x1C),
        "school": u16(b, 0x1E),
        "priest_type": u16(b, 0x20),
        "casting_graphics": u16(b, 0x22),
        "level": u32(b, 0x34),
        "icon": rr(b, 0x3A),
        "desc_strref": u32(b, 0x50),
    }
    ext_off = u32(b, 0x64)
    ext_cnt = u16(b, 0x68)
    fx_off = u32(b, 0x6A)
    cast_idx = u16(b, 0x6E)
    cast_cnt = u16(b, 0x70)
    spl["casting_fx"] = [parse_fx(b, fx_off + 48 * (cast_idx + i)) for i in range(cast_cnt) if fx_off + 48 * (cast_idx + i) + 48 <= len(b)]
    headers = []
    for i in range(ext_cnt):
        h = ext_off + 40 * i
        if h + 40 > len(b):
            break
        cnt = u16(b, h + 0x1E)
        idx = u16(b, h + 0x20)
        fx = []
        for j in range(cnt):
            o = fx_off + 48 * (idx + j)
            if o + 48 <= len(b):
                fx.append(parse_fx(b, o))
        headers.append(
            {
                "form": u8(b, h),
                "location": u8(b, h + 2),
                "target": u8(b, h + 0x0C),
                "target_count": u8(b, h + 0x0D),
                "range": u16(b, h + 0x0E),
                "req_level": u16(b, h + 0x10),
                "cast_time": u32(b, h + 0x12),
                "projectile_raw": u16(b, h + 0x26),
                "fx": fx,
            }
        )
    spl["headers"] = headers
    return spl


def parse_itm(b: bytes) -> dict | None:
    if b[:8] not in (b"ITM V1  ", b"ITM V1.1"):
        return None
    itm = {
        "name_strref": u32(b, 0x08),
        "name_id_strref": u32(b, 0x0C),
        "type": u16(b, 0x1C),
    }
    ext_off = u32(b, 0x64)
    ext_cnt = u16(b, 0x68)
    fx_off = u32(b, 0x6A)
    eq_idx = u16(b, 0x6E)
    eq_cnt = u16(b, 0x70)
    itm["equip_fx"] = [parse_fx(b, fx_off + 48 * (eq_idx + i)) for i in range(eq_cnt) if fx_off + 48 * (eq_idx + i) + 48 <= len(b)]
    headers = []
    for i in range(ext_cnt):
        h = ext_off + 56 * i
        if h + 56 > len(b):
            break
        cnt = u16(b, h + 0x1E)
        idx = u16(b, h + 0x20)
        fx = []
        for j in range(cnt):
            o = fx_off + 48 * (idx + j)
            if o + 48 <= len(b):
                fx.append(parse_fx(b, o))
        headers.append({"attack_type": u8(b, h), "projectile_raw": u16(b, h + 0x2A), "fx": fx})
    itm["headers"] = headers
    return itm


def parse_eff(b: bytes) -> dict | None:
    """EFF V2.0 (GemRB's speak.eff) or V1 body."""
    if b[:8] == b"EFF V2.0":
        o = 8
        return {
            "opcode": u32(b, o + 0x08),
            "p1": u32(b, o + 0x14),
            "p2": u32(b, o + 0x18),
            "res": rr(b, o + 0x28),
        }
    return None


# ---------------------------------------------------------------- PRO / VVC / BAM


def parse_pro(b: bytes) -> dict | None:
    if b[:8] != b"PRO V1.0":
        return None
    p = {
        "size": len(b),
        "type": u16(b, 0x08),
        "speed": u16(b, 0x0A),
        "sflags": u32(b, 0x0C),
        "fire_sound": rr(b, 0x10),
        "arrival_sound": rr(b, 0x18),
        "travel_vvc": rr(b, 0x20),
        "spark_color": u32(b, 0x28),
        "ext_flags": u32(b, 0x2C),
        "strref": u32(b, 0x30),
        "rgb": u32(b, 0x34),
        "color_speed": u16(b, 0x38),
        "shake": u16(b, 0x3A),
        "fail_spell": rr(b, 0x44),
        "success_spell": rr(b, 0x4C),
    }
    if len(b) >= 0x154:
        p.update(
            {
                "tflags": u32(b, 0x100),
                "bam1": rr(b, 0x104),
                "bam2": rr(b, 0x10C),
                "seq1": u8(b, 0x114),
                "seq2": u8(b, 0x115),
                "light_z": u16(b, 0x116),
                "light_x": u16(b, 0x118),
                "light_y": u16(b, 0x11A),
                "palette": rr(b, 0x11C),
                "smoke_anim": u16(b, 0x134),
                "trail": [rr(b, 0x136 + 8 * i) for i in range(3)],
            }
        )
    if p["type"] == 3 and len(b) >= 0x226:
        a = 0x200
        p["area"] = {
            "aflags": u32(b, a),
            "trigger_radius": u16(b, a + 4),
            "explosion_radius": u16(b, a + 6),
            "sound": rr(b, a + 8),
            "delay": u16(b, a + 0x10),
            "frag_anim": u16(b, a + 0x12),
            "frag_proj": u16(b, a + 0x14),
            "expl_count": u8(b, a + 0x16),
            "expl_type": u8(b, a + 0x17),
            "expl_color": u16(b, a + 0x18),
            "expl_proj_raw": u16(b, a + 0x1A),
            "vvc": rr(b, a + 0x1C),
            "cone_width": u16(b, a + 0x24),
            "spread": rr(b, a + 0x28),
            "secondary": rr(b, a + 0x30),
            "area_sound": rr(b, a + 0x38),
            "apflags": u32(b, a + 0x40),
        }
    return p


def parse_vvc(b: bytes) -> dict | None:
    if b[:8] != b"VVC V1.0":
        return None
    return {
        "bam": rr(b, 0x08),
        "shadow": rr(b, 0x10),
        "transparency": u32(b, 0x18),
        "seq_flags": u32(b, 0x20),
        "x": s32(b, 0x28),
        "y": s32(b, 0x2C),
        "framerate": u32(b, 0x34),
        "orientations": u32(b, 0x38),
        "z": s32(b, 0x4C),
        "light_x": u32(b, 0x50),
        "light_y": u32(b, 0x54),
        "light_z": u32(b, 0x58),
        "duration": u32(b, 0x5C),
        "seq1": s32(b, 0x68),
        "seq2": s32(b, 0x6C),
        "sound1": rr(b, 0x78),
        "sound2": rr(b, 0x80),
        "seq3": s32(b, 0x90),
        "sound3": rr(b, 0x94),
    }


def parse_bam(b: bytes) -> dict | None:
    compressed = False
    if b[:8] == b"BAMCV1  ":
        b = zlib.decompress(b[12:])
        compressed = True
    if b[:8] != b"BAM V1  ":
        return None
    nframes = u16(b, 8)
    ncycles = u8(b, 0x0A)
    foff = u32(b, 0x0C)
    frames = []
    for i in range(nframes):
        e = foff + 12 * i
        if e + 12 > len(b):
            break
        frames.append((u16(b, e), u16(b, e + 2), s16(b, e + 4), s16(b, e + 6)))
    coff = foff + 12 * nframes
    cycles = []
    for i in range(ncycles):
        e = coff + 4 * i
        if e + 4 > len(b):
            break
        cycles.append(u16(b, e))
    return {"frames": frames, "cycles": cycles, "compressed": compressed, "unpacked_size": len(b)}


def read_text_table(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if parts:
            rows.append(parts)
    return rows


def parse_ids(b: bytes) -> dict[int, str]:
    out = {}
    for parts in read_text_table(b.decode("latin1"))[1:]:
        if len(parts) < 2:
            continue
        try:
            val = int(parts[0], 0)
        except ValueError:
            continue
        out[val] = parts[1]
    return out
