# Everything we have on one hardcoded spell, in one screen: SPL effects (original data), GemRB's projectile and helper
# SPLs, and the checkable facts of the original and EE class methods (via facts.py).
#
#   python tools/parity/dossier.py SPWI207
import os, re, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
WORK = os.environ.get("PARITY_WORK", os.path.join(ROOT, ".re"))
from tb_gamedata import GameData

def proj_row(n):
	for l in open(os.path.join(ROOT, "dev", "parity", "maps", "projectiles.tsv"), encoding="utf-8"):
		q = l.rstrip("\n").split("\t")
		if q[0] == str(n): return q
def pro(name):
	p = os.path.join(ROOT, "gemrb", "unhardcoded", "pst", name.lower() + ".pro")
	if not os.path.exists(p): return None
	d = open(p, "rb").read(); c = lambda a: d[a:a + 8].split(b"\0")[0].decode("latin1")
	r = dict(type=struct.unpack_from("<H", d, 8)[0], speed=struct.unpack_from("<H", d, 0xA)[0], snd=(c(0x10), c(0x18)),
		fail=c(0x44), succ=c(0x4C))
	if r["type"] == 3 and len(d) >= 0x220:
		r.update(aflags=hex(struct.unpack_from("<I", d, 0x200)[0]), trigger=struct.unpack_from("<H", d, 0x204)[0],
			radius=struct.unpack_from("<H", d, 0x206)[0], vvc=c(0x208), spread=c(0x210))
	return r
def effs(d, hdr=0):
	"""effects of extended header hdr of raw SPL bytes: op tgt pow p1 p2 timing dur res dice save"""
	if not d: return "missing"
	off, n = struct.unpack_from("<IH", d, 0x64); fo, = struct.unpack_from("<I", d, 0x6A)
	if hdr >= n: return []
	h = off + hdr * 40; cnt, idx = struct.unpack_from("<HH", d, h + 0x1E)
	out = []
	for i in range(cnt):
		e = fo + (idx + i) * 48
		op, tg, pw, p1, p2, tm, rs, du, pr1, pr2, res, dn, ds, st, sb = struct.unpack_from("<HBBiiBBIBB8sIIIi", d, e)
		x = "op%d t%d p1=%s p2=%s tm%d dur%d" % (op, tg, p1, hex(p2) if p2 > 255 else p2, tm, du)
		if res.strip(bytes(1)): x += " " + res.split(bytes(1))[0].decode("latin1")
		if dn or ds: x += " %dd%d" % (dn, ds)
		if st: x += " save%s%+d" % (hex(st), sb)
		if (pr1, pr2) != (100, 0): x += " prob%d-%d" % (pr2, pr1)
		out.append(x)
	return out

def main():
	r = sys.argv[1].upper(); g = GameData(); s = g.spell(r)
	h = s["headers"][0]
	print("== %s %s  level %s  target %s range %s" % (r, s["name"], s.get("level"), h.get("target"), h.get("range")), flush=True)
	import pstres
	d = pstres.orig().res(r, "spl"); off, n = struct.unpack_from("<IH", d, 0x64)
	print("   SPL effects (header 0):", effs(d), flush=True)
	pn = struct.unpack_from("<H", d, off + 0x26)[0]
	q = proj_row(pn) or []
	print("   projectile %s: %s" % (pn, q), flush=True)
	if len(q) > 1 and q[1]:
		p = pro(q[1]); print("   GemRB %s.pro: %s" % (q[1], p), flush=True)
		for hs in (p or {}).get("fail", ""), (p or {}).get("succ", ""):
			if hs:
				print("     helper %s: %s" % (hs, effs(pstres.gemrb().res(hs, "spl"))), flush=True)
	addrs = [x for x in q[4:9] if re.fullmatch(r"[0-9A-F]{6}", x or "")] if q else []
	for a in dict.fromkeys(addrs[2:]):
		if os.path.exists(os.path.join(WORK, "orig", "dump", "dec", a + ".c")):
			subprocess.run([sys.executable, os.path.join(HERE, "facts.py"), "orig", a])
	cls = q[3].rstrip("?") if len(q) > 3 else ""
	if cls:
		for f in sorted(os.listdir(os.path.join(WORK, "ee", "dump", "dec"))):
			if f.startswith(cls + "_") and not re.search(r"_" + cls + r"_", f):
				subprocess.run([sys.executable, os.path.join(HERE, "facts.py"), "ee", f[:-2]])

if __name__ == "__main__":
	main()
