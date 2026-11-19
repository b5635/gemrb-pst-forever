# Look things up in the full decompile dumps without IDA and without reading whole files (token rule, AGENT_GUIDE).
#
#   python tools/parity/dumps.py find  ee   "CGameSprite::PlaySound"     functions whose real name matches (regex)
#   python tools/parity/dumps.py find  orig CGameDialog                  original functions of a srcmap class / address
#   python tools/parity/dumps.py show  ee   "CGameSprite::Hit("  [-g PAT] [-C 30] [--all]
#                                       big functions: prints size + outline; -g greps inside with context
#   python tools/parity/dumps.py lines ee   "CGameSprite::Hit(" 120 200   a line range
#   python tools/parity/dumps.py case  ee   "CGameAIBase::ExecuteAction(" 125   one switch case body
#   python tools/parity/dumps.py callers orig sub_4B245B              who calls it (cached call index)
#   python tools/parity/dumps.py calls  ee   "CGameSprite::Hit("     what it calls
#   python tools/parity/dumps.py grep  ee   "SOUNDOFF|VerbalConstant" [--in CGameSprite]   files:lines, capped
#
# Names: ee uses the demangled name from rename_manifest.csv (a substring; first match unless it is ambiguous).
# orig: an address (sub_4B245B / 4B245B) or a class from srcmap.txt (find only).
import csv, os, re, sys
from collections import defaultdict

WORK = os.environ.get("PARITY_WORK", r"D:\gemrb\.re")
DIRS = {"ee": os.path.join(WORK, "ee", "dump", "dec_all_named"), "orig": os.path.join(WORK, "orig", "dump", "dec_all")}
BIG = 150   # lines: above this `show` prints an outline instead of the body
CAP = 60    # grep hits printed

def manifest(game):
	"""[(addr, real name, file)]"""
	if game == "ee":
		with open(os.path.join(DIRS["ee"], "rename_manifest.csv"), encoding="utf-8", errors="replace") as f:
			return [(r["Address"], r["Function"], r["NewFile"]) for r in csv.DictReader(f)]
	with open(os.path.join(DIRS["orig"], "manifest.tsv"), encoding="utf-8") as f:
		return [(r["Address"], r["Name"], r["Address"].lstrip("0") + ".c") for r in csv.DictReader(f, delimiter="\t")]

def resolve(game, key):
	"""-> (addr, name, path) for one function; exits with the candidates when ambiguous"""
	m = manifest(game)
	k = key.upper().replace("SUB_", "").replace("0X", "")
	if re.fullmatch(r"[0-9A-F]{5,8}", k):
		for a, n, f in m:
			if a.lstrip("0") == k.lstrip("0"): return a, n, os.path.join(DIRS[game], f)
	exact = [r for r in m if r[1] == key]
	hits = exact or [r for r in m if key in r[1]]
	if not hits: sys.exit("no function matches %r" % key)
	if len(hits) > 1 and len({h[1] for h in hits}) > 1:
		print("%d matches, be more specific:" % len(hits))
		for a, n, f in hits[:30]: print("  %s %s" % (a, n))
		sys.exit(1)
	a, n, f = hits[0]
	return a, n, os.path.join(DIRS[game], f)

def text(path):
	return open(path, encoding="utf-8", errors="replace").read().replace("\r", "").splitlines()

def outline(lines):
	"""switch/case labels, calls to named functions and string literals: enough to pick a line range"""
	for i, l in enumerate(lines, 1):
		s = l.strip()
		if re.match(r"(switch|case |default:)", s) or '"' in s:
			print("%5d  %s" % (i, s[:110]))

CALL = re.compile(r"([A-Za-z_][\w]*(?:::[~\w]+)*)\(")
SKIP = {"if", "while", "for", "switch", "return", "sizeof", "LODWORD", "HIDWORD", "LOBYTE", "HIBYTE", "LOWORD",
	"HIWORD", "BYTE1", "BYTE2", "BYTE3", "SLOBYTE", "SHIBYTE", "SLODWORD", "SHIDWORD", "SLOWORD", "SHIWORD", "__fastcall",
	"__thiscall", "__stdcall", "__cdecl", "COERCE_FLOAT", "COERCE_DOUBLE", "qmemcpy", "memset", "abs", "__readfsdword"}

def call_index(game):
	"""callee -> callers, cached next to the dump (built once, ~1 min)"""
	cache = os.path.join(os.path.dirname(DIRS[game]), "calls_%s.tsv" % game)
	idx = defaultdict(set)
	if os.path.exists(cache):
		for l in open(cache, encoding="utf-8"):
			callee, caller = l.rstrip("\n").split("\t")
			idx[callee].add(caller)
		return idx
	print("building call index (once)...", file=sys.stderr)
	for a, n, f in manifest(game):
		p = os.path.join(DIRS[game], f)
		if not os.path.exists(p): continue
		body = open(p, encoding="utf-8", errors="replace").read()
		body = body.split("{", 1)[1] if "{" in body else ""
		me = n if game == "ee" else "sub_" + a.lstrip("0")
		for c in set(CALL.findall(body)) - SKIP:
			idx[c].add(me)
	with open(cache, "w", encoding="utf-8") as o:
		for c, s in idx.items():
			for x in s: o.write("%s\t%s\n" % (c, x))
	return idx

def short(name):
	"""'CGameSprite::Hit(CGameObject *,...)' -> 'CGameSprite::Hit' (how calls appear in the code)"""
	return name.split("(")[0]

AREAS = [  # (track, area, EE name regex, original srcmap classes)
	("A1/A2", "script actions + triggers", r"^CGameAIBase::|^CGameSprite::(Execute|Evaluate|Force|Set.*Trigger)|^CAIAction::|^CAITrigger::", "CGameAIBase CAIAction CAITrigger"),
	("A3", "event triggers (raised)", r"SendHitTrigger|::(AddTrigger|ClearTriggers|SetTrigger|.*Trigger\()", ""),
	("A4", "object selectors", r"^CAIObjectType::|GetTarget|::GetObject\(", "CAIObjectType"),
	("A5", "script engine", r"^CAIScript(File)?::|^CAICondition|^CAIResponse|^CAIConditionResponse|^CGameAIBase::(AIUpdate|ProcessAI|UpdateAI|ScriptUpdate)", "CAIScript CAIScriptFile CAICondition CAIResponse"),
	("A6/A7", "dialogue", r"Dialog", "CGameDialog CScreenDialog"),
	("A8", "PST hardcoded logic (BALDUR.bcs stand-in)", r"^CPlanescape::|^CModronMaze::", "CPlanescape"),
	("A9", "spawns", r"Spawn", "CGameSpawning"),
	("A10", "death, XP, journal, rest", r"::Die\b|Death|XP|Experience|KillStat|^CGameJournal::|Rest\(", "CGameJournal CKillStats"),
	("A11", "voice lines, sounds", r"Verbal|SoundOff|PlaySound|Battlecr|^CGameSprite::.*Sound", "CSoundMixer"),
	("B", "combat", r"Swing|::Hit\(|THAC0|::Damage\(|CheckSave|SavingThrow|Backstab|Critical|^CRuleTables::Get", "CRuleTables"),
	("B", "effect pipeline", r"^CGameEffect::|^CGameEffectList::|^CPersistantEffect", "CGameEffect CGameEffectList"),
	("C", "items, stores", r"^CItem::|^CStore::", "CItem CStore"),
	("C", "spells, projectiles", r"^CSpell::|^CProjectile::|^CPsSpell|^CPSTSpell", "CSpell CProjectile"),
]

def write_areas():
	ee = manifest("ee")
	srcmap = {}
	for l in open(os.path.join(WORK, "orig", "dump", "srcmap.txt"), encoding="utf-8"):
		c, subs = l.rstrip("\n").split("\t", 1); srcmap[c] = subs
	out = ["# Where each investigated area lives in the decompile dumps",
		"", "Generated by `python tools/parity/dumps.py areas ee write`. Names and addresses only (the code stays in `.re`).",
		"Read a function with `dumps.py show ee \"Name(\" -g PAT` or `lines`; original classes come from `srcmap.txt`",
		"(partial: many original functions have no class yet, find them through the EE twin's constants and strings).", ""]
	for track, area, rx, ocls in AREAS:
		hits = [(a, n) for a, n, f in ee if re.search(rx, n) and "thunk" not in n and not n.startswith(("CMessage", "CTypedPtr"))]
		out += ["## %s %s (%d EE functions)" % (track, area, len(hits)), ""]
		cls = defaultdict(list)
		for a, n in hits: cls[n.split("::")[0]].append((a, n))
		for c, fs in sorted(cls.items(), key=lambda x: -len(x[1])):
			if len(fs) > 10:
				out.append("- `%s` (%d): `dumps.py find ee \"^%s::\"`" % (c, len(fs), c))
			else:
				out += ["- `%s %s`" % (a, n[:110]) for a, n in fs]
		for oc in ocls.split():
			if oc in srcmap: out.append("- original `%s`: %s" % (oc, srcmap[oc][:300]))
		out.append("")
	p = os.path.join(os.path.dirname(__file__), "..", "..", "dev", "parity", "maps", "dump_areas.md")
	open(p, "w", encoding="utf-8", newline="\n").write("\n".join(out))
	print(p, sum(1 for l in out if l.startswith("- ")), "lines")

def main():
	if len(sys.argv) < 4:
		print(open(__file__).read().split("import csv")[0]); return
	cmd, game, key, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
	if cmd == "find":
		if game == "orig":
			for l in open(os.path.join(WORK, "orig", "dump", "srcmap.txt"), encoding="utf-8"):
				c, subs = l.rstrip("\n").split("\t", 1)
				if re.search(key, c, re.I): print(c, subs)
		pat = re.compile(key, re.I)
		for a, n, f in manifest(game):
			if pat.search(n): print(a, n)
	elif cmd in ("show", "lines", "case", "calls"):
		a, n, p = resolve(game, key)
		L = text(p)
		print("== %s %s  (%d lines, %s)" % (a, n, len(L), p))
		if cmd == "lines":
			lo, hi = int(rest[0]), int(rest[1])
			for i in range(lo, min(hi, len(L)) + 1): print("%5d  %s" % (i, L[i - 1]))
		elif cmd == "case":
			want = int(rest[0], 0)
			out, on, ind = [], False, None
			for i, l in enumerate(L, 1):
				m = re.match(r"^(\s*)case (0x[0-9A-Fa-f]+|-?\d+)u?:", l)
				d = re.match(r"^(\s*)default:", l)
				if m and int(m.group(2), 0) == want and not on:
					on, ind = True, len(m.group(1))
				elif on and ((m and len(m.group(1)) == ind and out and not re.match(r"^\s*case", L[i - 2])) or
						(d and len(d.group(1)) == ind) or (l.strip() == "}" and len(l) - len(l.lstrip()) < ind)):
					break
				if on: out.append("%5d  %s" % (i, l))
			print("\n".join(out) if out else "(no case %d)" % want)
		elif cmd == "calls":
			body = "\n".join(L)
			print("\n".join(sorted(set(CALL.findall(body.split("{", 1)[-1])) - SKIP)))
		else:
			g = rest[rest.index("-g") + 1] if "-g" in rest else None
			ctx = int(rest[rest.index("-C") + 1]) if "-C" in rest else 15
			if g:
				pat, shown = re.compile(g, re.I), set()
				for i, l in enumerate(L):
					if pat.search(l):
						for j in range(max(0, i - ctx), min(len(L), i + ctx + 1)):
							if j not in shown:
								if shown and j - 1 not in shown: print("  ...")
								shown.add(j); print("%5d  %s" % (j + 1, L[j]))
			elif len(L) <= BIG or "--all" in rest:
				for i, l in enumerate(L, 1): print("%5d  %s" % (i, l))
			else:
				print("(big: outline only; use -g PAT, `lines A B` or `case N`; --all to force)")
				outline(L)
	elif cmd == "callers":
		idx = call_index(game)
		k = key
		if game == "orig":
			k = "sub_" + key.upper().replace("SUB_", "").replace("0X", "")
		elif "(" in key or key not in idx:
			k = short(resolve(game, key)[1])
		for c in sorted(idx.get(k, ())): print(c)
		if not idx.get(k): print("(no callers of %s found: may be virtual, use a vtable)" % k)
	elif cmd == "areas":   # python dumps.py areas ee write  -> dev/parity/maps/dump_areas.md
		write_areas()
	elif cmd == "grep":
		pat = re.compile(key, re.I)
		only = rest[rest.index("--in") + 1] if "--in" in rest else None
		hits = 0
		for a, n, f in manifest(game):
			if only and only not in n: continue
			p = os.path.join(DIRS[game], f)
			if not os.path.exists(p): continue
			for i, l in enumerate(text(p), 1):
				if pat.search(l):
					hits += 1
					if hits <= CAP: print("%s %s:%d  %s" % (a, n[:70], i, l.strip()[:100]))
		if hits > CAP: print("(%d more hits: narrow with --in or a tighter pattern)" % (hits - CAP))
	else:
		print("unknown command", cmd)

if __name__ == "__main__":
	main()
