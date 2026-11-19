"""List every use of given effect opcodes in the original PST data (SPL + ITM, Fixpack/UB).

python tools/parity/opuses.py 147 148 [--full]
Prints: opcode, file, header, p1, p2, timing, duration, resource, save. --full prints every use,
otherwise a summary of distinct (p1, p2, timing) per opcode plus up to 5 example files.
"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tb_gamedata import GameData

def uses(g, ops):
	for ext, get in (("spl", g.spell), ("itm", g.item)):
		for n in g.names(ext):
			try:
				r = get(n)
			except Exception:
				continue
			if not r:
				continue
			groups = [("h%d" % i, h["effects"]) for i, h in enumerate(r["headers"])]
			if ext == "itm":
				groups.append(("eq", r["equipped"]))
			for tag, fxs in groups:
				for fx in fxs:
					if fx["op"] in ops:
						yield n.upper() + "." + ext, tag, fx

def main():
	args = [a for a in sys.argv[1:] if not a.startswith("--")]
	full = "--full" in sys.argv
	ops = {int(a) for a in args}
	g = GameData()
	summ = collections.defaultdict(lambda: collections.defaultdict(list))
	for f, tag, fx in uses(g, ops):
		if full:
			print("%d\t%s\t%s\tp1=%d\tp2=%d\tt=%d\tdur=%d\tres=%s\tsave=%#x" % (fx["op"], f, tag, fx["p1"], fx["p2"],
				fx["timing"], fx["duration"], fx["res"], fx["save"]))
		summ[fx["op"]][(fx["p1"], fx["p2"], fx["timing"])].append(f)
	if not full:
		for op in sorted(summ):
			print("op %d: %d uses" % (op, sum(len(v) for v in summ[op].values())))
			for k, v in sorted(summ[op].items(), key=lambda kv: -len(kv[1])):
				print("  p1=%d p2=%d t=%d  x%d  %s" % (k + (len(v), " ".join(sorted(set(v))[:5]))))

if __name__ == "__main__":
	main()
