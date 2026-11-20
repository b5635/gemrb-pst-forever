# Reads PST game data for the turn based spell tests: chitin.key/BIF resources (override and
# GemRB's unhardcoded PST data first), dialog.tlk strings, SPL and ITM headers and effects, and
# GemRB's projectile table. No GemRB needed.
import os
import re
import struct
import glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNHARD = os.path.join(REPO, "gemrb", "unhardcoded", "pst")
CFG = r"C:\Games\GemRB\GemRB.cfg"

TYPES = {"itm": 0x3ED, "spl": 0x3EE, "cre": 0x3F1, "ids": 0x3F0, "pro": 0x3FD}
EXT = {v: k for k, v in TYPES.items()}
TIMING = {0: "lim", 1: "perm", 2: "equip", 3: "delay-lim", 4: "delay-perm", 5: "delay-unsaved", 6: "delay-pending",
	7: "after-expires", 8: "perm-unsaved", 9: "perm-after-bonus", 10: "lim-ticks"}
SPELL_PREFIX = {"SPPR": 1000, "SPWI": 2000, "SPIN": 3000}

def game_path():
	for line in open(CFG, encoding="latin1"):
		m = re.match(r"\s*GamePath\s*=\s*(.+)", line)
		if m:
			return m.group(1).strip()
	raise RuntimeError("no GamePath in " + CFG)

class GameData:
	def __init__(self, path=None):
		self.path = path or game_path()
		k = open(os.path.join(self.path, "chitin.key"), "rb").read()
		nbif, nres, obif, ores = struct.unpack_from("<IIII", k, 8)
		self.bifs = []
		for i in range(nbif):
			ln, fo, fl, loc = struct.unpack_from("<IIHH", k, obif + i * 12)
			self.bifs.append(k[fo:fo + fl].rstrip(b"\0").decode().replace("\\", os.sep))
		self.index = {}
		for i in range(nres):
			rn, rt, loc = struct.unpack_from("<8sHI", k, ores + i * 14)
			self.index[(rn.rstrip(b"\0").decode().upper(), rt)] = loc
		self.bifcache = {}
		tlk = open(os.path.join(self.path, "dialog.tlk"), "rb").read()
		self.tlk = tlk
		self.tcount, self.toff = struct.unpack_from("<II", tlk, 0x0A)
		self.projectiles = {}
		for line in open(os.path.join(UNHARD, "gemprjtl.ids"), encoding="latin1"):
			m = re.match(r"\s*(\d+)\s+(\S+)", line)
			if m:
				self.projectiles[int(m.group(1))] = m.group(2)

	def names(self, ext):
		t = TYPES[ext]
		return sorted(n for (n, rt) in self.index if rt == t)

	def _bif(self, bp):
		if bp not in self.bifcache:
			data = None
			for c in [os.path.join(self.path, bp)] + glob.glob(os.path.join(self.path, "**", os.path.basename(bp)), recursive=True):
				if os.path.exists(c):
					data = open(c, "rb").read()
					break
			self.bifcache[bp] = data
		return self.bifcache[bp]

	def res(self, name, ext):
		for d in (UNHARD, os.path.join(self.path, "override")):
			p = os.path.join(d, name.lower() + "." + ext)
			if os.path.exists(p):
				return open(p, "rb").read()
		loc = self.index.get((name.upper(), TYPES[ext]))
		if loc is None:
			return None
		b = self._bif(self.bifs[loc >> 20])
		if not b:
			return None
		nf, = struct.unpack_from("<I", b, 8)
		off, = struct.unpack_from("<I", b, 16)
		for j in range(nf):
			l, o, s, t = struct.unpack_from("<IIIH", b, off + j * 16)
			if (l & 0x3FFF) == (loc & 0x3FFF):
				return b[o:o + s]
		return None

	def string(self, ref):
		if ref >= self.tcount:
			return ""
		fl, snd, v, p, o, l = struct.unpack_from("<H8sIIII", self.tlk, 0x12 + ref * 26)
		return self.tlk[self.toff + o:self.toff + o + l].decode("cp1252", "replace")

	def projectile(self, index):
		"""SPL/ITM projectile field -> (resref, kind, explosion radius, delay, explosions)"""
		if not index:
			return None
		name = self.projectiles.get(index - 1)
		if not name:
			return ("#%d" % index, "?", 0, 0, 0)
		d = self.res(name, "pro")
		if not d:
			return (name, "missing", 0, 0, 0)
		t, = struct.unpack_from("<H", d, 8)
		kind = {1: "none", 2: "single", 3: "area"}.get(t, str(t))
		if t == 3 and len(d) >= 0x218:
			af, trig, rad = struct.unpack_from("<IHH", d, 0x200)
			delay, = struct.unpack_from("<H", d, 0x210)
			return (name, kind, rad, delay, d[0x216])
		return (name, kind, 0, 0, 0)

	@staticmethod
	def _effect(d, eo):
		op, tgt, power, p1, p2, tm, rs, dur, pmax, pmin = struct.unpack_from("<HBBIIBBIBB", d, eo)
		res = d[eo + 0x14:eo + 0x1C].split(b"\0")[0]
		res = "".join(chr(c) for c in res if 32 <= c < 127)
		save, = struct.unpack_from("<I", d, eo + 0x24)
		return {"op": op, "target": tgt, "p1": p1, "p2": p2, "timing": tm, "duration": dur, "res": res, "save": save}

	def spell(self, name):
		d = self.res(name, "spl")
		if not d or d[:4] != b"SPL ":
			return None
		nm, = struct.unpack_from("<I", d, 0x08)
		stype, = struct.unpack_from("<H", d, 0x1C)
		lvl, = struct.unpack_from("<I", d, 0x34)
		desc, = struct.unpack_from("<I", d, 0x50)
		eho, ehc, fxo, cfi, cfc = struct.unpack_from("<IHIHH", d, 0x64)
		headers = []
		for h in range(ehc):
			ho = eho + h * 0x28
			nfx, fi = struct.unpack_from("<HH", d, ho + 0x1E)
			pj, = struct.unpack_from("<H", d, ho + 0x26)
			headers.append({
				"minlevel": struct.unpack_from("<H", d, ho + 0x10)[0],
				"target": d[ho + 0x0C], "range": struct.unpack_from("<H", d, ho + 0x0E)[0],
				"projectile": self.projectile(pj),
				"effects": [self._effect(d, fxo + (fi + e) * 0x30) for e in range(nfx)],
			})
		text = self.string(desc)
		m = re.search(r"Duration:\s*([^\n|]*)", text)
		return {"resref": name.upper(), "name": self.string(nm), "type": stype, "level": lvl,
			"duration_text": m.group(1).strip() if m else "", "description": text, "headers": headers}

	def item(self, name):
		d = self.res(name, "itm")
		if not d or d[:4] != b"ITM ":
			return None
		nm, = struct.unpack_from("<I", d, 0x0C) # identified name
		desc, = struct.unpack_from("<I", d, 0x54)
		eho, ehc, fxo, fei, fec = struct.unpack_from("<IHIHH", d, 0x64)
		headers = []
		for h in range(ehc):
			ho = eho + h * 0x38
			nfx, fi = struct.unpack_from("<HH", d, ho + 0x1E)
			pj, = struct.unpack_from("<H", d, ho + 0x2A)
			headers.append({"type": d[ho], "target": d[ho + 0x0C],
				"projectile": self.projectile(pj),
				"effects": [self._effect(d, fxo + (fi + e) * 0x30) for e in range(nfx)]})
		equipped = [self._effect(d, fxo + (fei + e) * 0x30) for e in range(fec)]
		return {"resref": name.upper(), "name": self.string(nm), "description": self.string(desc),
			"headers": headers, "equipped": equipped}

def spell_number(resref):
	base = SPELL_PREFIX.get(resref[:4].upper())
	if base is None or not resref[4:].isdigit():
		return None
	return base + int(resref[4:])
