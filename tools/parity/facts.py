# Pull the checkable facts out of a decompiled function: random ranges, effects it builds, resrefs, calls,
# comparisons with constants. Prints "line: fact" so you can open the .c at that line for context.
#
#   python tools/parity/facts.py orig 6C02F8            (original, by address)
#   python tools/parity/facts.py ee CPsSpellPacify_AIUpdate   (EE, file-name prefix)
#   python tools/parity/facts.py orig 6C02F8 --calls    (also list every sub_ called, with counts)
import collections, os, re, sys
WORK = os.environ.get("PARITY_WORK", r"D:\gemrb\.re")

# names of original helpers we have identified (extend as you learn more; see dev/parity/maps/orig_index.tsv)
ORIG = {"4A56EB": "MakeEffect(op,p1,p2,timing,...)", "5A4864": "GetObject(id)", "89BC79": "CString", "81B75E": "ResRef",
	"89B946": "new", "463F03": "GlobalVar", "404D61": "MakeAction(id,...)", "4EA100": "LoadSPL", "4A5C21": "DecodeEffect(itemeffect)", "577BD4": "ProjectileRollToHit", "577E7C": "ProjectileRollToHit(ids)", "7BC70E": "SendHitTrigger", "476177": "GetAllInRange", "4128C8": "GetEnemyOf", "7BD15D": "IsInCarceri", "7BD264": "IsInBaator", "7BD327": "IsInNegativeMaterialPlane", "82015B": "RollDie(size,adj)", "4ADD0E": "ClearItemEffect(op)"}

def load(game, name):
	d = os.path.join(WORK, game, "dump", "dec")
	p = os.path.join(d, name.upper().replace("SUB_", "") + ".c") if game == "orig" else None
	if not p or not os.path.exists(p):
		c = sorted(f for f in os.listdir(d) if f.lower().startswith(name.lower()))
		if not c: sys.exit("not decompiled: " + name)
		p = os.path.join(d, c[0])
	return p, open(p, encoding="utf-8", errors="replace").read().splitlines()

def main():
	game, name = sys.argv[1], sys.argv[2]
	p, L = load(game, name)
	print(p)
	calls = collections.Counter()
	for i, l in enumerate(L, 1):
		s = l.strip()
		f = []
		for m in re.finditer(r"rand\(\) % (\w+)( \+ (\w+))?", s):
			n = int(m.group(1), 0) if re.fullmatch(r"(0x)?[0-9A-Fa-f]+", m.group(1)) else None
			lo = int(m.group(3), 0) if m.group(3) and re.fullmatch(r"(0x)?\d+", m.group(3)) else 0
			f.append("random %s" % ("%d..%d" % (lo, lo + n - 1) if n else "0..%s-1 (+%s)" % (m.group(1), m.group(3) or 0)))
		m = re.search(r"sub_4A56EB\(([^;]*)\)", s)
		if m: f.append("EFFECT op=%s" % m.group(1).split(",")[0] + " args=(" + m.group(1)[:120] + ")")
		m = re.search(r"CGameEffect::CGameEffect\(\s*\(_DWORD\)\w+,\s*(\d+),\s*([^,]+),\s*([^,]+)", s)
		if m: f.append("EFFECT op=%s p1=%s p2=%s" % m.groups())
		m = re.search(r"CGameEffect::ClearItemEffect\(\w+, (\d+)\)", s)
		if m: f.append("EFFECT op=%s (fields follow)" % m.group(1))
		for m in re.finditer(r'"([A-Za-z0-9_#]{3,12})"', s): f.append("resref/string %s" % m.group(1))
		for m in re.finditer(r"\ba([A-Z][a-z0-9_]{2,12})\b", s):
			if game == "orig": f.append("string a%s" % m.group(1))
		for m in re.finditer(r"(GetAllInRange|GetNearest\w*|CheckForIncreasedSpellLevel|SendHitTrigger|ProjectileRollToHit|GetSpellState|SetGameFreeze|GetCasterLevel|CheckSave|SetBackground\w*|PlaySound|JumpToPoint|SetSequence|AddEffect|ApplyEffect)\b", s):
			f.append("call %s" % m.group(1))
		m = re.search(r"\b(v\d+|\*\([^)]*\)[^ ]*) (<=|>=|<|>|==|!=) (-?\d{2,6})\b", s)
		if m and "for" not in s[:4]: f.append("compare %s %s %s" % m.groups())
		for m in re.finditer(r"sub_([0-9A-F]{6})\(", s):
			calls[m.group(1)] += 1
			if m.group(1) in ORIG and m.group(1) not in ("89B946", "81B75E", "89BC79"): f.append("call %s" % ORIG[m.group(1)])
		if f: print("%5d: %s" % (i, "; ".join(dict.fromkeys(f))))
	if "--calls" in sys.argv:
		print("calls:", ", ".join("%s%s x%d" % (k, "=" + ORIG[k] if k in ORIG else "", v) for k, v in calls.most_common()))

if __name__ == "__main__":
	main()
