"""Sort every TIS, MOS, BAM and relevant BMP into gui, areas, sprites or skip."""

from __future__ import annotations

import re
import struct
from pathlib import Path

from ie_formats import ResourceIndex, bam_frame_sizes, resref

_NAME = re.compile(r"""['"]([A-Za-z0-9_]{1,8})['"]""")
_SKIP_SUFFIX = ("LM", "SR", "HT")


def _stem_names(text: str, known: set[str]) -> set[str]:
    found = set()
    for match in _NAME.findall(text):
        name = match.upper()
        if name in known:
            found.add(name)
    return found


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _font_names(repo: Path, known_bams: set[str]) -> set[str]:
    path = repo / "gemrb" / "unhardcoded" / "pst" / "fonts.2da"
    if not path.is_file():
        return set()
    names = set()
    for line in _read_text(path).splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("2DA") or line.split()[0] == "RESREF":
            continue
        parts = line.split()
        # row number, then the resref column. A lone token is the default font.
        token = parts[1] if parts[0].isdigit() and len(parts) > 1 else parts[0]
        token = token.upper()
        if token in known_bams:
            names.add(token)
    return names


def _cursor_names(repo: Path) -> set[str]:
    names = {"CURSORS"}
    ini = repo / "gemrb" / "unhardcoded" / "pst" / "gemrb.ini"
    if ini.is_file():
        for line in _read_text(ini).splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            if key.strip() == "MainCursorsImage":
                names.add(value.strip().upper())
    return names


def _script_names(repo: Path, known: set[str]) -> set[str]:
    roots = [repo / "gemrb" / "GUIScripts" / "pst", repo / "gemrb" / "GUIScripts"]
    found: set[str] = set()
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.py"):
            if path in seen:
                continue
            seen.add(path)
            found |= _stem_names(_read_text(path), known)
    return found


def _chu_bams(data: bytes) -> set[str]:
    """BAM resrefs referenced by buttons, sliders, scrollbars and progress bars."""
    if len(data) < 16 or data[:8] != b"CHUIV1  ":
        return set()
    windows, ct_off, we_off = struct.unpack_from("<3I", data, 8)
    names: set[str] = set()
    for i in range(windows):
        entry = we_off + i * 0x1C
        if entry + 0x1C > len(data):
            break
        # word id, word pad, region (8), background, control count, mos (8), first control
        control_count = struct.unpack_from("<H", data, entry + 14)[0]
        first = struct.unpack_from("<H", data, entry + 24)[0]
        if control_count > 4096:
            continue
        for n in range(control_count):
            slot = ct_off + (first + n) * 8
            if slot + 8 > len(data):
                break
            ctrl_off = struct.unpack_from("<I", data, slot)[0]
            # id, region, type, pad
            if ctrl_off + 14 > len(data):
                continue
            kind = data[ctrl_off + 12]
            body = ctrl_off + 14
            if kind == 0 and body + 8 <= len(data):  # button
                names.add(resref(data[body : body + 8]))
            elif kind == 1 and body + 24 <= len(data):  # progress bar: mos, mos, bam
                names.add(resref(data[body + 16 : body + 24]))
            elif kind == 2 and body + 16 <= len(data):  # slider: mos, bam
                names.add(resref(data[body + 8 : body + 16]))
            elif kind == 3 and body + 32 <= len(data):  # text edit caret bam
                names.add(resref(data[body + 24 : body + 32]))
            elif kind == 7 and body + 8 <= len(data):  # scrollbar
                names.add(resref(data[body : body + 8]))
    names.discard("")
    return names


def _resref_at(data: bytes, off: int) -> str:
    if off < 0 or off + 8 > len(data):
        return ""
    return resref(data[off : off + 8])


def _itm_icons(data: bytes) -> set[str]:
    # inventory icon, description icon, and the "use" icon on each extended header.
    # The ground icon is a sprite, not GUI.
    if len(data) < 0x6A or not data.startswith(b"ITM "):
        return set()
    names = {_resref_at(data, 0x3A), _resref_at(data, 0x58)}
    ext_off = struct.unpack_from("<I", data, 0x64)[0]
    ext_count = struct.unpack_from("<H", data, 0x68)[0]
    for i in range(ext_count):
        names.add(_resref_at(data, ext_off + i * 56 + 4))
    names.discard("")
    names.discard("NONE")
    return names


def _spl_icons(data: bytes) -> set[str]:
    if len(data) < 0x6A or not data.startswith(b"SPL "):
        return set()
    names = {_resref_at(data, 0x3A)}
    ext_off = struct.unpack_from("<I", data, 0x64)[0]
    ext_count = struct.unpack_from("<H", data, 0x68)[0]
    for i in range(ext_count):
        names.add(_resref_at(data, ext_off + i * 40 + 4))
    names.discard("")
    names.discard("NONE")
    return names


def _cre_portraits(data: bytes) -> set[str]:
    if len(data) < 0x44 or not data.startswith(b"CRE "):
        return set()
    version = data[4:8]
    if version not in (b"V1.0", b"V1.2", b"V1.1"):
        return set()
    names = {_resref_at(data, 0x34), _resref_at(data, 0x3C)}
    names.discard("")
    names.discard("NONE")
    return names


def _tiny(index: ResourceIndex, name: str) -> bool:
    try:
        sizes = bam_frame_sizes(index.get(name, "bam"))
    except Exception:
        return False
    real = [(w, h) for w, h in sizes if w and h]
    if not real:
        return True
    return all(w < 8 or h < 8 for w, h in real)


def classify(index: ResourceIndex, repo: Path) -> dict:
    bams = set(index.names("bam"))
    moss = set(index.names("mos"))
    known = bams | moss | set(index.names("bmp"))
    fonts = _font_names(repo, bams)
    cursors = _cursor_names(repo) & (bams | {"CURSORS"})
    scripted = _script_names(repo, known)
    gui_bams: set[str] = set()
    gui_bams |= scripted & bams
    for name in index.names("chu"):
        try:
            gui_bams |= _chu_bams(index.get(name, "chu"))
        except Exception:
            continue
    for name in index.names("itm"):
        try:
            gui_bams |= _itm_icons(index.get(name, "itm"))
        except Exception:
            continue
    for name in index.names("spl"):
        try:
            gui_bams |= _spl_icons(index.get(name, "spl"))
        except Exception:
            continue
    portrait_names: set[str] = set()
    for name in index.names("cre"):
        try:
            portrait_names |= _cre_portraits(index.get(name, "cre"))
        except Exception:
            continue
    gui_bams |= portrait_names & bams
    gui_bams &= bams

    gui_bmps: set[str] = set()
    for name in index.names("bmp"):
        if name.endswith(_SKIP_SUFFIX):
            continue
        if name in portrait_names or name in scripted:
            gui_bmps.add(name)
    # portraits named by creatures, plus every bmp that lives only as a portrait file
    # and was not a light/search/height map
    for name in portrait_names:
        if index.has(name, "bmp") and not name.endswith(_SKIP_SUFFIX):
            gui_bmps.add(name)

    # bestiary pictures are named by beast.ini, which neither portraits nor scripts mention
    for ini in (index.game / "beast.ini", index.game / "override" / "beast.ini"):
        if ini.is_file():
            for line in ini.read_text(encoding="latin1").splitlines():
                line = line.split("//")[0].strip()
                if line.lower().startswith("imageknown="):
                    name = line.split("=", 1)[1].strip().upper()
                    if name and index.has(name, "bmp"):
                        gui_bmps.add(name)

    items = {"gui": [], "areas": [], "sprites": [], "skip": []}

    def add(category: str, name: str, ext: str, reason: str = "") -> None:
        row = {"name": name, "ext": ext}
        if reason:
            row["reason"] = reason
        items[category].append(row)

    for name in index.names("tis"):
        add("areas", name, "tis")
    for name in sorted(moss):
        add("gui", name, "mos")
    for name in sorted(gui_bmps):
        add("gui", name, "bmp")
    for name in sorted(bams):
        if name in fonts:
            add("gui", name, "bam", "font")
        elif name in cursors or name.startswith("CURSORS"):
            add("skip", name, "bam", "cursor")
        elif _tiny(index, name):
            add("skip", name, "bam", "tiny")
        elif name in gui_bams:
            add("gui", name, "bam")
        else:
            add("sprites", name, "bam")

    counts = {key: len(value) for key, value in items.items()}
    by_ext: dict[str, dict[str, int]] = {}
    for category, rows in items.items():
        tally: dict[str, int] = {}
        for row in rows:
            tally[row["ext"]] = tally.get(row["ext"], 0) + 1
        by_ext[category] = tally
    return {"counts": counts, "by_ext": by_ext, "items": items}
