# Print the original's handler for a script action or trigger, straight from the decompiled dispatchers.
#
#   python tools/parity/case.py action 125        (creature switch sub_76A7EA via byte_76D476, else base sub_44B099)
#   python tools/parity/case.py trigger 0x4040    (sub_453258 and sub_778529)
#   python tools/parity/case.py action 125 --base (force the base switch)
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("PARITY_WORK", r"D:\gemrb\.re")
DEC = os.path.join(WORK, "orig", "dump", "dec_all")   # full dump (dumps.py); was dump/dec

def cases(path, switch_hint=None):
	"""split a decompiled switch into {case value: body}; the first top-level switch unless a hint is given"""
	s = open(os.path.join(DEC, path), encoding="utf-8", errors="replace").read()
	if switch_hint and switch_hint in s:
		s = s.split(switch_hint, 1)[1]
	out, cur, buf, indent = {}, [], [], None
	for line in s.splitlines():
		m = re.match(r"^(\s*)case (0x[0-9A-Fa-f]+|\d+)u?:", line)
		if m and (indent is None or len(m.group(1)) == indent):
			indent = len(m.group(1))
			if buf and cur:
				for c in cur: out.setdefault(c, "\n".join(buf))
				cur, buf = [], []
			cur.append(int(m.group(2), 0)); continue
		if re.match(r"^(\s*)default:", line) and indent is not None and len(line) - len(line.lstrip()) == indent:
			break
		if cur: buf.append(line)
	if cur: out.setdefault(cur[-1], "\n".join(buf))
	return out

def main():
	kind, key = sys.argv[1], int(sys.argv[2], 0)
	if kind == "action":
		if key < 0x130 and "--base" not in sys.argv:
			from pe import PE
			c = PE(os.path.join(WORK, "orig", "Torment.exe")).bytes(0x76D476 + key, 1)[0]
			body = cases("76A7EA.c", "switch ( v6 )").get(c, "")
			print("== action %d: sprite switch sub_76A7EA case %d" % (key, c))
			if "goto LABEL_214" in body.lstrip()[:20]:
				print("(goto LABEL_214: not handled here)")
			else:
				print(body)
				if "goto LABEL_214" not in body[:200]: return
			print("(falls through to the base switch)")
		print("== action %d: base switch sub_44B099" % key)
		print(cases("44B099.c", "switch ( v479 )").get(key, "(no case: unhandled)"))
	else:
		for f in ("453258.c", "778529.c"):
			b = cases(f).get(key)
			if b: print("== trigger 0x%X in sub_%s" % (key, f[:-2])); print(b)

if __name__ == "__main__":
	main()
