# Look up an IESDP entry as plain text (community documentation: a cross-check, not ground truth).
#   python tools/parity/iesdp.py opcode pst 82        (also: pstee, bg2tob, bgee, ...)
#   python tools/parity/iesdp.py action pst 19
#   python tools/parity/iesdp.py trigger pst 0x4092
#   python tools/parity/iesdp.py format pro_v1        (file_formats/ie_formats/<name>.htm, whole page)
#   python tools/parity/iesdp.py grep pst "Soul Exodus"   (search the PST opcode/action/trigger pages)
import html, os, re, sys

ROOT = os.environ.get("IESDP", r"D:\gemrb\iesdp-gh-pages")

def text(path):
	s = open(path, encoding="utf-8", errors="replace").read()
	s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
	s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</tr>|<hr[^>]*>", "\n", s)
	s = html.unescape(re.sub(r"<[^>]+>", " ", s))
	return "\n".join(re.sub(r"[ \t]+", " ", l).strip() for l in s.splitlines() if l.strip())

def page(kind, game):
	return {"opcode": os.path.join(ROOT, "opcodes", game + ".htm"),
		"action": os.path.join(ROOT, "scripting", "actions", game + "actions.htm"),
		"trigger": os.path.join(ROOT, "scripting", "triggers", game + "triggers.htm")}[kind]

def entry(kind, game, key):
	t = text(page(kind, game))
	n = int(key, 0)
	if kind == "opcode":
		start = re.search(r"#%d \(0x%X\)" % (n, n), t, re.I)
		nxt = re.compile(r"#\d+ \(0x[0-9A-F]+\)", re.I)
	else:
		start = re.search(r"(?m)^(0x%04X|0x%X|%d)\s+\w+\(" % (n, n, n), t, re.I)
		nxt = re.compile(r"(?m)^(0x[0-9A-F]{4}|\d+)\s+\w+\(", re.I)
	if not start:
		return "(no %s %s entry in %s)" % (kind, key, game)
	m = nxt.search(t, start.end())
	return t[start.start():m.start() if m else start.start() + 3000]

if __name__ == "__main__":
	if len(sys.argv) < 3:
		sys.exit(__doc__ if __doc__ else "see header")
	kind = sys.argv[1]
	if kind == "format":
		print(text(os.path.join(ROOT, "file_formats", "ie_formats", sys.argv[2] + ".htm")))
	elif kind == "grep":
		pat = re.compile(sys.argv[3], re.I)
		for k in ("opcode", "action", "trigger"):
			for i, l in enumerate(text(page(k, sys.argv[2])).splitlines()):
				if pat.search(l): print("%s:%d: %s" % (k, i, l[:200]))
	else:
		print(entry(kind, sys.argv[2], sys.argv[3]))
