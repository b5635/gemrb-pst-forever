"""Dump PST question-mark examine lines as VVE plan.csv rows.

These are ARE info-point (region type 1) strings. Clicking one floats the text;
GemRB plays the TLK sound on that strref, or VV<strref>.wav if that file exists.
Talking objects (a dialog resref on the region) are skipped: VVE already voices
those through their DLG files.

  python tools/vve_infopoints.py
  python tools/vve_infopoints.py --csv D:/VVE_Builder-main/pst_revoice/infopoints.csv
  python tools/vve_infopoints.py --skip-plan D:/VVE_Builder-main/pst_revoice/plan.csv
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from pathlib import Path

_UPSCALE = Path(__file__).resolve().parent / "upscale"
if str(_UPSCALE) not in sys.path:
    sys.path.insert(0, str(_UPSCALE))

import ie_formats  # noqa: E402

DEFAULT_GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
INVALID = 0xFFFFFFFF
INFO_TYPE = 1
SPEAKER = "Narrator"
COLUMNS = ["StrRef", "Speaker", "Action", "SoundResRef", "Text", "Voice"]


def rr(raw: bytes) -> str:
    text = raw.split(b"\x00", 1)[0].decode("latin1", "replace")
    if not text or not text.isascii() or not text.isprintable():
        return ""
    return text.strip().upper()


def fallback_resref(strref: int) -> str:
    return f"VV{strref}"


class Tlk:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        if self.data[:8] != b"TLK V1  ":
            raise SystemExit(f"{path} is not a TLK V1 file")
        self.count = struct.unpack_from("<I", self.data, 0x0A)[0]
        self.base = struct.unpack_from("<I", self.data, 0x0E)[0]

    def text(self, strref: int) -> str:
        if strref <= 0 or strref >= self.count or strref == INVALID:
            return ""
        entry = 0x12 + strref * 26
        off = struct.unpack_from("<I", self.data, entry + 18)[0]
        length = struct.unpack_from("<I", self.data, entry + 22)[0]
        raw = self.data[self.base + off : self.base + off + length]
        return raw.decode("cp1252", "replace").replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()


def parse_regions(data: bytes) -> list[dict]:
    sig = data[:8]
    if sig not in (b"AREAV1.0", b"AREAV9.1"):
        return []
    extra = 16 if sig == b"AREAV9.1" else 0
    base = 0x54 + extra
    count = struct.unpack_from("<H", data, base + 6)[0]
    off = struct.unpack_from("<I", data, base + 8)[0]
    out = []
    for i in range(count):
        o = off + i * 0xC4
        if o + 0xC4 > len(data):
            break
        rec = data[o : o + 0xC4]
        out.append(
            {
                "type": struct.unpack_from("<H", rec, 0x20)[0],
                "strref": struct.unpack_from("<I", rec, 0x64)[0],
                "dlg": rr(rec[0xBC:0xC4]),
            }
        )
    return out


def rows_from_regions(regions: list[dict], texts: dict[int, str], skip: set[int] | None = None) -> list[dict]:
    """Unique examine lines: info type, real strref, no dialog, non-empty text."""
    skip = skip or set()
    seen: set[int] = set()
    rows = []
    for region in regions:
        if region["type"] != INFO_TYPE:
            continue
        strref = region["strref"]
        if strref <= 0 or strref == INVALID or strref in seen or strref in skip:
            continue
        if region["dlg"]:
            continue
        text = texts.get(strref, "")
        if not text:
            continue
        seen.add(strref)
        rows.append(
            {
                "StrRef": strref,
                "Speaker": SPEAKER,
                "Action": "generate",
                "SoundResRef": fallback_resref(strref),
                "Text": text,
                "Voice": "",
            }
        )
    rows.sort(key=lambda row: row["StrRef"])
    return rows


def load_plan_strrefs(path: Path) -> set[int]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {int(row["StrRef"]) for row in csv.DictReader(handle) if row.get("StrRef")}


def collect(game: Path, skip: set[int] | None = None) -> list[dict]:
    cache = Path(__file__).resolve().parent / "upscale" / "work" / "bifcache"
    index = ie_formats.ResourceIndex(game, cache)
    tlk = Tlk(game / "dialog.tlk")
    regions = []
    for name in index.names("are"):
        regions.extend(parse_regions(index.get(name, "are")))
    texts = {}
    for region in regions:
        strref = region["strref"]
        if strref not in texts:
            texts[strref] = tlk.text(strref)
    return rows_from_regions(regions, texts, skip)


def write_csv(rows: list[dict], path: Path | None) -> None:
    handle = sys.stdout if path is None else path.open("w", encoding="utf-8-sig", newline="")
    close = path is not None
    try:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if close:
            handle.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", type=Path, default=DEFAULT_GAME)
    ap.add_argument("--csv", type=Path, help="write plan.csv rows here (default: stdout)")
    ap.add_argument("--skip-plan", type=Path, help="omit strrefs already in this VVE plan.csv")
    args = ap.parse_args()
    skip = load_plan_strrefs(args.skip_plan) if args.skip_plan else set()
    rows = collect(args.game, skip)
    chars = sum(len(row["Text"]) for row in rows)
    print(f"# {len(rows)} unique examine lines, {chars} chars, skipped {len(skip)} plan strrefs", file=sys.stderr)
    write_csv(rows, args.csv)


if __name__ == "__main__":
    main()
