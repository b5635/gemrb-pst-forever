# Decompile PST BCS scripts to readable text (track A: A3 event triggers, A4 objects, A8 BALDUR).
#
#   python tools/parity/bcs.py 0100THV1                 one script (original data; --gemrb: what GemRB loads)
#   python tools/parity/bcs.py --grep "Help\(!|!Help"    blocks of every script whose text matches (regex)
#   python tools/parity/bcs.py --objects                 count object.ids functions and IDS fields used in all BCS
#
# PST objects have 9 IDS fields (ea faction team general race class specific gender align), 5 identifiers
# (object.ids, innermost first) and a rect; the name comes last.
import re, sys, collections
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import pstres

FIELDS = ["ea", "faction", "team", "general", "race", "class", "specific", "gender", "align"]
FIELD_IDS = ["ea", "faction", "team", "general", "race", "class", "specific", "gender", "align"]

def ids(src, name):
	d = {}
	t = src.res(name, "ids")
	if not t: return d
	for l in pstres.text(t).splitlines():
		m = re.match(r"\s*(0x[0-9a-fA-F]+|-?\d+)\s+(.+)", l)
		if m: d.setdefault(int(m.group(1), 0), m.group(2).strip())
	return d

OBJ = re.compile(r'OB\s*\n?([-\d ]+?)\s*\[([-\d.]+)\]\s*"([^"]*)"\s*OB')
TRG = re.compile(r'TR\s*\n?(-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) \[(-?\d+),(-?\d+)\] "([^"]*)" "([^"]*)" (OB.*?OB)\s*TR', re.S)
ACT = re.compile(r'AC\s*\n?(-?\d+)(OB.*?OB)\s*(OB.*?OB)\s*(OB.*?OB)\s*(-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+)\s*"([^"]*)" "([^"]*)"\s*AC', re.S)

class Dec:
	def __init__(self, src):
		self.src = src
		self.trig = {k & 0x7fff: v.split("(")[0] for k, v in ids(src, "trigger").items()}
		self.act = {k: v.split("(")[0] for k, v in ids(src, "action").items()}
		self.objf = ids(src, "object")
		self.fid = {f: ids(src, f) for f in FIELD_IDS}

	def obj(self, s, collect=None):
		m = OBJ.search(s)
		if not m: return "?"
		n = [int(x) for x in m.group(1).split()]
		if m.group(3):
			if collect is not None: collect["name"] += 1
			return '"%s"' % m.group(3)
		f, idents = n[:9], n[9:14]
		parts = []
		for i, v in enumerate(f):
			if v:
				parts.append("%s=%s" % (FIELDS[i], self.fid[FIELDS[i]].get(v, v)))
				if collect is not None: collect["field " + FIELDS[i]] += 1
		s = ""
		for v in idents:
			if v:
				fn = self.objf.get(v, str(v))
				if collect is not None: collect["fn " + fn] += 1
				s = fn + "(" + s + ")" if s else fn
		if parts: s = (s + " " if s else "") + "[" + ",".join(parts) + "]"
		if m.group(2) not in ("-1.-1.-1.-1", "0.0.0.0"): s += " rect" + m.group(2)
		return s

	def blocks(self, data, collect=None):
		t = data.decode("latin1")
		for cr in re.findall(r"CR(.*?)CR", t, re.S):
			co, _, rs = cr.partition("CO")[2].rpartition("CO")
			conds = []
			for m in TRG.finditer(co):
				tid, i0, fl, i1, i2, x, y, s0, s1, ob = m.groups()
				name = self.trig.get(int(tid) & 0x7fff, tid)
				args = [a for a in [self.obj(ob, collect) if OBJ.search(ob) and any(int(v) for v in OBJ.search(ob).group(1).split()) or OBJ.search(ob).group(3) else ""] if a]
				args += ['"%s"' % s for s in (s0, s1) if s]
				args += [v for v in (i0, i1, i2) if v != "0"]
				if (x, y) != ("0", "0"): args.append("[%s.%s]" % (x, y))
				conds.append(("!" if int(fl) & 1 else "") + name + "(" + ",".join(args) + ")")
			resp = []
			for r in re.findall(r"RE(.*?)RE", rs, re.S):
				w = re.match(r"\s*(\d+)", r)
				acts = []
				for m in ACT.finditer(r):
					aid, o0, o1, o2, i0, x, y, i1, i2, s0, s1 = m.groups()
					name = self.act.get(int(aid), aid)
					args = [self.obj(o, collect) for o in (o0, o1, o2)]
					args = [a for a in args if a]
					args += ['"%s"' % s for s in (s0, s1) if s]
					args += [v for v in (i0, i1, i2) if v != "0"]
					if (x, y) not in (("0", "0"), ("-1", "-1")): args.append("[%s.%s]" % (x, y))
					acts.append(name + "(" + ",".join(args) + ")")
				resp.append((w.group(1) if w else "?", acts))
			yield conds, resp

	def text(self, name, data, collect=None):
		out = []
		for conds, resp in self.blocks(data, collect):
			out.append("IF\n  " + "\n  ".join(conds) + "\nTHEN")
			for w, acts in resp:
				out.append("  RESPONSE #%s\n    " % w + "\n    ".join(acts))
			out.append("END")
		return "\n".join(out)

def main():
	a = sys.argv[1:]
	src = pstres.gemrb() if "--gemrb" in a else pstres.orig()
	a = [x for x in a if x != "--gemrb"]
	d = Dec(src)
	if a and a[0] == "--grep":
		pat = re.compile(a[1]); hits = 0
		for n in sorted(src.names("bcs")):
			data = src.res(n, "bcs")
			if not data: continue
			for conds, resp in d.blocks(data):
				txt = "IF " + " ".join(conds) + " THEN " + " | ".join(" ".join(x[1]) for x in resp)
				if pat.search(txt):
					hits += 1
					if hits <= 80: print(n + ": " + txt[:300])
		print("%d blocks" % hits)
	elif a and a[0] == "--objects":
		c = collections.Counter()
		for n in src.names("bcs"):
			data = src.res(n, "bcs")
			if data: d.text(n, data, c)
		for k, v in c.most_common(): print("%6d  %s" % (v, k))
	else:
		print(d.text(a[0], src.res(a[0], "bcs")))

if __name__ == "__main__":
	main()
