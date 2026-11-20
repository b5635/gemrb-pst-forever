"""How PST's scripts call a trigger: parameter distribution over every BCS (compiled) and DLG (text).

python tools/parity/trigargs.py 0x4047                 # RandomNum: counts of (int0, int1, ...) tuples, top 25
python tools/parity/trigargs.py 0x4047 --top 60 --where   # more rows, plus a few script names per tuple
python tools/parity/trigargs.py 0x4047 --dlg           # also list the DLG text forms (state triggers + transition triggers)

BCS trigger layout: TR <id> <int0> <flags> <int1> <int2> [x,y] "<str0>" "<str1>" OB(object) TR.
flags bit 0 = negated (!Trigger).
"""
import collections, os, re, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pstres
from actargs import obj

TRG = re.compile(r'TR\s*\n(\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) \[(-?\d+),(-?\d+)\] "([^"]*)" "([^"]*)" ?(OB\s*\n.*?OB\s*\n)\s*TR', re.S)

def main():
	a = sys.argv[1:]
	tid = int(a[0], 0); top = int(a[a.index("--top") + 1]) if "--top" in a else 25
	o = pstres.orig()
	cnt = collections.Counter(); where = collections.defaultdict(list)
	for n in o.names("bcs"):
		d = o.res(n, "bcs")
		if not d: continue
		for m in TRG.finditer(d.decode("latin1")):
			if int(m.group(1)) != tid: continue
			i0, fl, i1, i2, x, y, s0, s1 = m.group(2, 3, 4, 5, 6, 7, 8, 9)
			key = "%sobj=%s int0=%s int1=%s int2=%s pt=[%s.%s] s0=%r s1=%r" % (
				"!" if int(fl) & 1 else "", obj(m.group(10)), i0, i1, i2, x, y, s0, s1)
			cnt[key] += 1
			if len(where[key]) < 4: where[key].append(n)
	print("trigger 0x%X: %d BCS uses, %d distinct" % (tid, sum(cnt.values()), len(cnt)))
	for k, c in cnt.most_common(top):
		print("%5d  %s%s" % (c, k, ("   " + " ".join(where[k])) if "--where" in a else ""))
	if "--dlg" in a:
		names = []
		for line in pstres.text(o.res("trigger", "ids")).splitlines():
			p = line.split(None, 1)
			if len(p) == 2 and int(p[0], 0) == tid: names.append(re.escape(p[1].split("(")[0]))
		name = "(?:%s)" % "|".join(names)
		dc = collections.Counter(); dw = collections.defaultdict(list)
		for n in o.names("dlg"):
			d = o.res(n, "dlg")
			if not d or d[:4] != b"DLG ": continue
			# state triggers (offset 0x18, count 0x1C) and transition triggers (0x20, 0x24)
			for to in (0x18, 0x20):
				off0, num = struct.unpack_from("<II", d, to)
				for i in range(num):
					off, ln = struct.unpack_from("<II", d, off0 + i * 8)
					for m in re.finditer(r"!?\b%s\s*\([^)]*\)" % name, d[off:off + ln].decode("latin1"), re.I):
						k = re.sub(r"\s+", " ", m.group(0)); dc[k] += 1
						if len(dw[k]) < 4 and n not in dw[k]: dw[k].append(n)
		print("DLG text: %d uses, %d distinct" % (sum(dc.values()), len(dc)))
		for k, c in dc.most_common(top):
			print("%5d  %s%s" % (c, k, ("   " + " ".join(dw[k])) if "--where" in a else ""))

if __name__ == "__main__":
	main()
