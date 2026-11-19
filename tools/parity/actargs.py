"""How PST's scripts call an action: parameter distribution over every BCS (compiled) and DLG (text).

python tools/parity/actargs.py 219                 # WaitRandom: counts of (int0, int1, ...) tuples, top 25
python tools/parity/actargs.py 219 --top 60 --where   # more rows, plus a few script names per tuple
python tools/parity/actargs.py 219 --dlg           # also list the DLG text forms (by action name)

BCS action layout: AC <id> OB(override) OB(1) OB(2) <int0> <x> <y> <int1> <int2>"<str0>" "<str1>" AC.
Objects print as their name string, or the first non-zero object.ids fields.
"""
import collections, os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pstres

ACT = re.compile(r'AC\s*\n(\d+)(OB\s*\n.*?OB\s*\n)(OB\s*\n.*?OB\s*\n)(OB\s*\n.*?OB\s*\n)'
	r'\s*(-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+)\s*"([^"]*)" "([^"]*)" ?AC', re.S)
OBJ = re.compile(r'OB\s*\n(.*?)\[(-?\d+)\.(-?\d+)\.(-?\d+)\.(-?\d+)\] "([^"]*)"\s*OB', re.S)

def obj(s):
	m = OBJ.search(s)
	if not m: return "?"
	nums = [int(x) for x in m.group(1).split()]
	if m.group(6): return '"%s"' % m.group(6)
	return "obj(" + ",".join(str(x) for x in nums).rstrip(",0") + ")" if any(nums) else "-"

def main():
	a = sys.argv[1:]
	aid = int(a[0]); top = int(a[a.index("--top") + 1]) if "--top" in a else 25
	o = pstres.orig()
	cnt = collections.Counter(); where = collections.defaultdict(list)
	for n in o.names("bcs"):
		d = o.res(n, "bcs")
		if not d: continue
		for m in ACT.finditer(d.decode("latin1")):
			if int(m.group(1)) != aid: continue
			i0, x, y, i1, i2, s0, s1 = m.group(5, 6, 7, 8, 9, 10, 11)
			key = "obj1=%s obj2=%s int0=%s pt=[%s.%s] int1=%s int2=%s s0=%r s1=%r" % (
				obj(m.group(3)), obj(m.group(4)), i0, x, y, i1, i2, s0, s1)
			cnt[key] += 1
			if len(where[key]) < 4: where[key].append(n)
	print("action %d: %d BCS uses, %d distinct" % (aid, sum(cnt.values()), len(cnt)))
	for k, c in cnt.most_common(top):
		print("%5d  %s%s" % (c, k, ("   " + " ".join(where[k])) if "--where" in a else ""))
	if "--dlg" in a:
		names = []
		for line in pstres.text(o.res("action", "ids")).splitlines():
			p = line.split(None, 1)
			if len(p) == 2 and p[0] == str(aid): names.append(re.escape(p[1].split("(")[0]))
		name = "(?:%s)" % "|".join(names)
		dc = collections.Counter()
		for n in o.names("dlg"):
			d = o.res(n, "dlg")
			if not d or d[:4] != b"DLG ": continue
			ao, na = struct.unpack_from("<II", d, 0x28)
			for i in range(na):
				off, ln = struct.unpack_from("<II", d, ao + i * 8)
				for m in re.finditer(r"\b%s\s*\([^)]*\)" % name, d[off:off + ln].decode("latin1"), re.I):
					dc[re.sub(r"\s+", " ", m.group(0))] += 1
		print("DLG text: %d uses, %d distinct" % (sum(dc.values()), len(dc)))
		for k, c in dc.most_common(top): print("%5d  %s" % (c, k))

if __name__ == "__main__":
	main()
