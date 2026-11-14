"""Install the PST AI Voices mod (made for PST:EE) into classic PST for GemRB.

The EE mod's WeiDU installer STRING_SETs every voiced line, which would replace the
classic/Fixpack/UB text with EE text. This installer instead:
  * copies the voice files into <game>/override (they are OGG data named .WAV, which
    GemRB's OGGReader picks up as a fallback for "wav"),
  * sets only the sound resref (and the "has sound" flag) of each matching string in
    Dialog.tlk and dialogF.tlk, after checking the text still matches,
  * keeps the original voice-actor sounds on the few lines that already have one
    (use --replace-original to swap those too).
The strrefs in the mod are the classic ones; only lines whose text differs a lot
from the installed tlk are skipped.

Usage:
  python tools/install_ai_voices.py [--mod D:/planescape-torment-ai-voices-master]
                                    [--game C:/Program Files (x86)/Black Isle/Torment] [--components 0,1,2,3]
                                    [--replace-original] [--dry-run]
  python tools/install_ai_voices.py --uninstall
"""

import argparse
import difflib
import json
import os
import re
import shutil
import struct
import sys

COMPONENT_NAMES = ["Companion Voices", "Key Story NPC Voices", "Side NPC Voices", "Minor NPC Voices"]
TLKS = ["Dialog.tlk", "dialogF.tlk"]
BACKUP_DIR = "ai_voices_backup"
HEADER = 18
ENTRY = 26


def norm(s):
	return re.sub(r"[^a-z0-9]", "", s.lower())


def similar(a, b):
	a, b = norm(a), norm(b)
	if a == b:
		return 1.0
	sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
	if sm.real_quick_ratio() < 0.6 or sm.quick_ratio() < 0.6:
		return 0.0
	# EE and classic differ in trailing tutorial notes ("NOTE: press..."): also accept
	# lines where most of the shorter text matches
	covered = sum(b.size for b in sm.get_matching_blocks()) / max(1, min(len(a), len(b)))
	return max(sm.ratio(), covered - 0.1)


def parse_tra(path, cache={}):
	if path not in cache:
		rx = re.compile(r"@(\d+)\s*=\s*~(.*?)~\s*(?:\[([^\]]*)\])?", re.S)
		text = open(path, encoding="utf-8", errors="replace").read()
		cache[path] = {int(m.group(1)): (m.group(2), (m.group(3) or "").strip()) for m in rx.finditer(text)}
	return cache[path]


def parse_tp2(moddir):
	"""-> list of components: {"audio": dir, "lines": [(strref, text, sound)]}, in WeiDU order."""
	root = os.path.dirname(moddir)
	tp2 = os.path.join(root, "setup-PST_AI_Voices.tp2")
	comps = []
	tra = {}
	for line in open(tp2, encoding="utf-8", errors="replace"):
		line = line.strip()
		if line.startswith("BEGIN"):
			comps.append({"audio": None, "lines": []})
		elif line.startswith("COPY") and comps:
			comps[-1]["audio"] = os.path.join(root, line.split("~")[1])
		elif line.startswith("LOAD_TRA"):
			tra = parse_tra(os.path.join(root, line.split("~")[1]))
		elif line.startswith("STRING_SET") and comps:
			m = re.match(r"STRING_SET\s+(\d+)\s+@(\d+)", line)
			if m and int(m.group(2)) in tra:
				text, sound = tra[int(m.group(2))]
				if sound:
					comps[-1]["lines"].append((int(m.group(1)), text, sound))
	return comps


class Tlk:
	def __init__(self, path):
		self.path = path
		self.data = bytearray(open(path, "rb").read())
		sig, _lang, self.count, self.offset = struct.unpack_from("<8sHII", self.data, 0)
		if sig != b"TLK V1  ":
			raise SystemExit(f"{path}: not a TLK V1 file")

	def entry(self, ref):
		flags, sound, _v, _p, off, length = struct.unpack_from("<H8sIIII", self.data, HEADER + ENTRY * ref)
		text = bytes(self.data[self.offset + off:self.offset + off + length]).decode("cp1252", "replace")
		return flags, sound.rstrip(b"\0").decode("latin1"), text

	def set_sound(self, ref, sound):
		pos = HEADER + ENTRY * ref
		flags = struct.unpack_from("<H", self.data, pos)[0] | 2
		struct.pack_into("<H8s", self.data, pos, flags, sound.upper().encode("latin1")[:8].ljust(8, b"\0"))

	def save(self):
		tmp = self.path + ".tmp"
		open(tmp, "wb").write(self.data)
		os.replace(tmp, self.path)


def uninstall(game):
	bdir = os.path.join(game, BACKUP_DIR)
	manifest = os.path.join(bdir, "manifest.json")
	if not os.path.exists(manifest):
		raise SystemExit("PST AI Voices is not installed (no manifest)")
	info = json.load(open(manifest))
	for name in TLKS:
		src = os.path.join(bdir, name)
		if os.path.exists(src):
			shutil.copy2(src, os.path.join(game, name))
	removed = 0
	for f in info["files"]:
		p = os.path.join(game, "override", f)
		if os.path.exists(p):
			os.remove(p)
			removed += 1
	saved = os.path.join(bdir, "override")
	if os.path.isdir(saved):
		for f in os.listdir(saved):
			shutil.copy2(os.path.join(saved, f), os.path.join(game, "override", f))
	shutil.rmtree(bdir)
	print(f"Uninstalled: restored {', '.join(TLKS)}, removed {removed} voice files")


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--mod", default=r"D:\planescape-torment-ai-voices-master")
	ap.add_argument("--game", default=r"C:\Program Files (x86)\Black Isle\Torment")
	ap.add_argument("--components", default="0,1,2,3")
	ap.add_argument("--replace-original", action="store_true", help="also replace the original voice-actor sounds")
	ap.add_argument("--min-match", type=float, default=0.75, help="text similarity needed to voice a line")
	ap.add_argument("--dry-run", action="store_true")
	ap.add_argument("--uninstall", action="store_true")
	args = ap.parse_args()

	game = args.game
	if args.uninstall:
		return uninstall(game)

	moddir = args.mod
	for sub in ("EN", ""):
		if os.path.isdir(os.path.join(moddir, sub, "PST_AI_Voices")):
			moddir = os.path.join(moddir, sub, "PST_AI_Voices")
			break
	else:
		raise SystemExit(f"PST_AI_Voices folder not found under {args.mod}")

	bdir = os.path.join(game, BACKUP_DIR)
	if os.path.exists(os.path.join(bdir, "manifest.json")):
		raise SystemExit("Already installed; run with --uninstall first to reinstall")

	comps = parse_tp2(moddir)
	wanted = [int(c) for c in args.components.split(",") if c.strip()]
	tlks = [Tlk(os.path.join(game, n)) for n in TLKS if os.path.exists(os.path.join(game, n))]
	main_tlk = tlks[0]

	assign = {}  # strref -> sound (later components/lines win, like WeiDU)
	audio = {}  # SOUND -> source path
	skipped, kept, oob = [], 0, 0
	for ci in wanted:
		comp = comps[ci]
		files = {os.path.splitext(f)[0].upper(): os.path.join(comp["audio"], f) for f in os.listdir(comp["audio"])}
		for ref, text, sound in comp["lines"]:
			sound = sound.upper()
			if sound not in files:
				continue
			if ref >= main_tlk.count:
				oob += 1
				continue
			_flags, cur, cur_text = main_tlk.entry(ref)
			if cur and cur.upper() != sound and not args.replace_original:
				kept += 1
				continue
			if similar(cur_text, text) < args.min_match:
				skipped.append((ref, cur_text, text))
				continue
			assign[ref] = sound
			audio[sound] = files[sound]
		print(f"component {ci} ({COMPONENT_NAMES[ci]}): {len(comp['lines'])} lines")

	audio = {snd: audio[snd] for snd in set(assign.values())}
	print(f"voicing {len(assign)} strings, {len(audio)} files; kept {kept} original sounds; "
	      f"skipped {len(skipped)} with changed text; {oob} out of range")
	for ref, a, b in skipped[:10]:
		print(f"  skip {ref}: tlk={a[:70]!r}\n         mod={b[:70]!r}")
	if args.dry_run:
		return

	override = os.path.join(game, "override")
	os.makedirs(bdir, exist_ok=True)
	for t in tlks:
		shutil.copy2(t.path, os.path.join(bdir, os.path.basename(t.path)))
	clashes = [s for s in audio if os.path.exists(os.path.join(override, s + ".WAV"))]
	if clashes:
		print(f"note: {len(clashes)} files already in override are replaced (backed up): {clashes[:5]}")
		os.makedirs(os.path.join(bdir, "override"), exist_ok=True)
		for s in clashes:
			shutil.copy2(os.path.join(override, s + ".WAV"), os.path.join(bdir, "override", s + ".WAV"))
	files = []
	for sound, src in sorted(audio.items()):
		name = sound + ".WAV"
		shutil.copyfile(src, os.path.join(override, name))
		files.append(name)
	for t in tlks:
		for ref, sound in assign.items():
			if ref < t.count:
				t.set_sound(ref, sound)
		t.save()
	json.dump({"components": wanted, "files": files, "strings": len(assign)}, open(os.path.join(bdir, "manifest.json"), "w"))
	print(f"Installed into {game}: {len(files)} files, {len(assign)} strings in {', '.join(TLKS)}")
	print(f"Backup of the tlk files in {bdir}; undo with --uninstall")


if __name__ == "__main__":
	sys.exit(main())
