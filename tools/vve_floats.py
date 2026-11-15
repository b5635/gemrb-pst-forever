"""Dump PST FloatMessage / FloatMessageRnd lines as VVE plan.csv rows.

These are BCS overhead barks (idle "Deaders?", worker chatter, SRC pools), not
dialog. GemRB already plays the TLK sound on FloatMessage; it also plays
VV<strref>.wav by name if that slot is still empty. Starting a real dialog
stops the speech. Do not STRING_SET the text.

Speaker/Voice come from the creature's DLG via VVE npcs.json / casting.json
when --vve is set. Shared strrefs get one row and the most common dialog's voice.

  python tools/vve_floats.py
  python tools/vve_floats.py --csv D:/VVE_Builder-main/pst_revoice/floats.csv
  python tools/vve_floats.py --skip-plan D:/VVE_Builder-main/pst_revoice/plan.csv --vve D:/VVE_Builder-main
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

_UPSCALE = Path(__file__).resolve().parent / "upscale"
if str(_UPSCALE) not in sys.path:
	sys.path.insert(0, str(_UPSCALE))
_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
	sys.path.insert(0, str(_TOOLS))

import ie_formats  # noqa: E402
import vve_infopoints as inf  # noqa: E402

DEFAULT_GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
DEFAULT_VVE = Path(r"D:\VVE_Builder-main")
COLUMNS = inf.COLUMNS
CRE_SCRIPTS = (0x248, 0x250, 0x258, 0x260, 0x268)
CRE_DIALOG = 0x370
CRE_LONGNAME = 0x08

FLOAT_RE = re.compile(
	r'AC\n210OB\n.*?""OB\nOB\n.*?""OB\nOB\n.*?""OB\n(\d+) 0 0 0 0',
	re.S,
)
RND_RE = re.compile(
	r'AC\n212OB\n.*?""OB\nOB\n.*?""OB\nOB\n.*?""OB\n0 0 0 0 0"([^"]*)"',
	re.S,
)


def enable_script_types() -> None:
	ie_formats.EXT_BY_TYPE[0x3EF] = "bcs"
	ie_formats.EXT_BY_TYPE[0x3F1] = "cre"
	ie_formats.EXT_BY_TYPE[0x803] = "src"
	ie_formats.WANTED.update({"bcs", "cre", "src"})


def looks_spoken(text: str) -> bool:
	"""True for overhead speech/emotes; false for item text and VB slot labels."""
	t = text.strip()
	if len(t) < 2:
		return False
	if t[0] in "\"'*":
		return True
	return t.startswith("::")


def parse_src(data: bytes) -> list[int]:
	if len(data) < 4:
		return []
	count = struct.unpack_from("<I", data, 0)[0]
	refs = []
	for i in range(count):
		off = 4 + i * 8
		if off + 4 > len(data):
			break
		refs.append(struct.unpack_from("<I", data, off)[0])
	return refs


def parse_bcs_floats(data: bytes) -> tuple[list[int], list[str]]:
	text = data.decode("latin1", "replace")
	refs = [int(m) for m in FLOAT_RE.findall(text)]
	pools = [m.upper() for m in RND_RE.findall(text) if m.strip()]
	return refs, pools


def cre_resref(data: bytes, off: int) -> str:
	if off + 8 > len(data) or data[:8] != b"CRE V1.2":
		return ""
	return inf.rr(data[off : off + 8])


def load_vve_voices(vve: Path) -> tuple[dict[str, str], dict[str, str]]:
	"""dialog resref -> (speaker, voice_id)."""
	speakers: dict[str, str] = {}
	voices: dict[str, str] = {}
	npcs = vve / "pst_cast" / "npcs.json"
	casting = vve / "pst_cast" / "casting.json"
	if npcs.is_file():
		for npc in json.loads(npcs.read_text(encoding="utf-8")):
			dlg = str(npc.get("dialog", "")).upper()
			if dlg:
				speakers[dlg] = npc.get("speaker") or dlg
	if casting.is_file():
		raw = json.loads(casting.read_text(encoding="utf-8"))
		for key, row in raw.items():
			dlg = str(row.get("dialog") or key).upper()
			if row.get("speaker"):
				speakers[dlg] = row["speaker"]
			if row.get("voice_id"):
				voices[dlg] = row["voice_id"]
	return speakers, voices


def pick_identity(dialogs: list[str], speakers: dict[str, str], voices: dict[str, str]) -> tuple[str, str]:
	usable = [d for d in dialogs if d and d != "NONE"]
	if not usable:
		return "", ""
	dlg = Counter(usable).most_common(1)[0][0]
	return speakers.get(dlg, dlg), voices.get(dlg, "")


def rows_from_hits(
	hits: dict[int, list[str]],
	script_dialogs: dict[str, list[str]],
	texts: dict[int, str],
	speakers: dict[str, str],
	voices: dict[str, str],
	skip: set[int] | None = None,
) -> list[dict]:
	skip = skip or set()
	rows = []
	for strref in sorted(hits):
		if strref <= 0 or strref == inf.INVALID or strref in skip:
			continue
		text = texts.get(strref, "")
		if not looks_spoken(text):
			continue
		dialogs: list[str] = []
		for script in hits[strref]:
			dialogs.extend(script_dialogs.get(script, []))
		speaker, voice = pick_identity(dialogs, speakers, voices)
		rows.append(
			{
				"StrRef": strref,
				"Speaker": speaker or "Unknown",
				"Action": "generate",
				"SoundResRef": inf.fallback_resref(strref),
				"Text": text,
				"Voice": voice,
			}
		)
	return rows


def parse_are_actors(data: bytes) -> list[tuple[str, str, list[str]]]:
	"""(cre, dialog, scripts) from each ARE actor stub (0x110)."""
	sig = data[:8]
	if sig not in (b"AREAV1.0", b"AREAV9.1"):
		return []
	extra = 16 if sig == b"AREAV9.1" else 0
	base = 0x54 + extra
	if base + 6 > len(data):
		return []
	off = struct.unpack_from("<I", data, base)[0]
	count = struct.unpack_from("<H", data, base + 4)[0]
	out = []
	for i in range(count):
		rec = data[off + i * 0x110 : off + (i + 1) * 0x110]
		if len(rec) < 0x88:
			break
		dlg = inf.rr(rec[0x48:0x50])
		scripts = [inf.rr(rec[0x50 + j * 8 : 0x58 + j * 8]) for j in range(6)]
		cre = inf.rr(rec[0x80:0x88])
		out.append((cre, dlg, scripts))
	return out


def collect(game: Path, skip: set[int] | None = None, vve: Path | None = None) -> list[dict]:
	enable_script_types()
	cache = Path(__file__).resolve().parent / "upscale" / "work" / "bifcache"
	index = ie_formats.ResourceIndex(game, cache)
	tlk = inf.Tlk(game / "dialog.tlk")
	speakers, voices = load_vve_voices(vve) if vve and vve.is_dir() else ({}, {})

	src_refs: dict[str, list[int]] = {}
	for name in index.names("src"):
		src_refs[name] = parse_src(index.get(name, "src"))

	hits: dict[int, list[str]] = defaultdict(list)
	for name in index.names("bcs"):
		refs, pools = parse_bcs_floats(index.get(name, "bcs"))
		for ref in refs:
			hits[ref].append(name)
		for pool in pools:
			for ref in src_refs.get(pool, []):
				hits[ref].append(name)

	cre_dialog: dict[str, str] = {}
	script_dialogs: dict[str, list[str]] = defaultdict(list)
	for name in index.names("cre"):
		cre = index.get(name, "cre")
		dlg = cre_resref(cre, CRE_DIALOG)
		cre_dialog[name] = dlg
		for off in CRE_SCRIPTS:
			script = cre_resref(cre, off)
			if script and script != "NONE":
				script_dialogs[script].append(dlg)
	for name in index.names("are"):
		for cre, dlg, scripts in parse_are_actors(index.get(name, "are")):
			if not dlg or dlg == "NONE":
				dlg = cre_dialog.get(cre, "")
			for script in scripts:
				if script and script != "NONE":
					script_dialogs[script].append(dlg)

	needed = {ref for ref in hits if ref > 0}
	texts = {ref: tlk.text(ref) for ref in needed}
	return rows_from_hits(hits, script_dialogs, texts, speakers, voices, skip)


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
	ap.add_argument("--vve", type=Path, default=DEFAULT_VVE, help="VVE_Builder root for npcs.json / casting.json")
	args = ap.parse_args()
	skip = inf.load_plan_strrefs(args.skip_plan) if args.skip_plan else set()
	rows = collect(args.game, skip, args.vve)
	chars = sum(len(row["Text"]) for row in rows)
	refs = [row["StrRef"] for row in rows]
	print(
		f"# {len(rows)} unique float lines, {chars} chars, sum {sum(refs) if refs else 0}, "
		f"min {min(refs) if refs else 0}, max {max(refs) if refs else 0}, skipped {len(skip)} plan strrefs",
		file=sys.stderr,
	)
	write_csv(rows, args.csv)


if __name__ == "__main__":
	main()
