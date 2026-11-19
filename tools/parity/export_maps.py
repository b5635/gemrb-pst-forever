# Export the facts we dug out of the two binaries as plain-text maps under dev/parity/maps/ (version controlled).
#
#   python tools/parity/export_maps.py
#
# Only addresses, names, numbers, case indexes and short identifier strings go out: never decompiled code.
# The maps say *where* to look; the code itself stays in the git-ignored .re/ workspace (see README).
import collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
WORK = os.environ.get("PARITY_WORK", r"D:\gemrb\.re")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dev", "parity", "maps")
OUT = os.path.normpath(OUT)
os.chdir(WORK)
os.makedirs(OUT, exist_ok=True)
from pe import PE
import pstres

ODEC, EDEC = "orig/dump/dec", "ee/dump/dec"
def odec(a): return os.path.exists(os.path.join(ODEC, a + ".c"))
def subs_in(body, skip=("89B946", "81B75E", "89BC0B", "81BDCC", "89BC79", "89BD94")):
	out = []
	for s in re.findall(r"sub_([0-9A-F]{6})\(", body):
		if s not in skip and s not in out: out.append(s)
	return out
def write(name, header, rows, note):
	with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
		f.write("# " + note + "\n")
		f.write("\t".join(header) + "\n")
		for r in rows: f.write("\t".join("" if v is None else str(v) for v in r) + "\n")
	print(name, len(rows))

# ---------- original functions: size, source file (asserts) ----------
osize = {}
for l in open("orig/dump/funcs.txt"):
	p = l.split()
	if len(p) >= 3: osize[p[1].replace("sub_", "")] = int(p[2])
srcfile = {}
for l in open("orig/dump/srcmap.txt"):
	k, v = l.rstrip("\n").split("\t")
	for s in v.split(","): srcfile[s.replace("sub_", "")] = k
role = collections.defaultdict(list)

# ---------- opcodes ----------
apply_ = json.load(open("orig_apply.json")); opvt = json.load(open("orig_opvt.json"))
ops = {o["op"]: o for o in json.load(open("opcodes.json"))}
eeop = json.load(open("ee_opcodes.json")) if os.path.exists("ee_opcodes.json") else {}
opmap = json.load(open("opmap.json")) if os.path.exists("opmap.json") else {}
rows = []
for n in sorted(set(int(k) for k in apply_) | set(ops)):
	o = ops.get(n, {}); a = apply_.get(str(n))
	if a: role[a].append("opcode %d ApplyEffect" % n)
	m = opmap.get("map", {}).get(str(n)) if isinstance(opmap, dict) else None
	rows.append((n, o.get("name"), o.get("func"), o.get("uses", 0), a, opvt.get(str(n)), "y" if a and odec(a) else "n",
		json.dumps(m) if m else ""))
write("opcodes.tsv", ["op", "gemrb_name", "gemrb_fx", "uses_in_data", "orig_apply", "orig_vtable", "orig_dec", "ee_mapping"], rows,
	"PST opcode -> GemRB function, original ApplyEffect (vtable slot 2) and vtable, EE mapping from opmap.json. orig_dec=y: .re/orig/dump/dec/<addr>.c exists")

# ---------- actions ----------
o = pstres.orig()
def ids(name):
	r = {}
	for l in pstres.text(o.res(name, "ids")).splitlines():
		m = re.match(r"\s*(0x[0-9A-Fa-f]+|\d+)\s+(.+)", l)
		if m: r.setdefault(int(m.group(1), 0), m.group(2).strip())
	return r
act = ids("action"); trg = ids("trigger")
p = PE("orig/Torment.exe"); tab = p.bytes(0x76D476, 0x130)
spr_body = open(os.path.join(ODEC, "76A7EA.c")).read().split("switch ( v6 )", 1)[1]
cases = {}
for b in re.split(r"\n    case ", spr_body)[1:]:
	m = re.match(r"(\d+):((?:\s*case \d+:)*)", b)
	if not m: continue
	idsx = [int(m.group(1))] + [int(x) for x in re.findall(r"case (\d+):", m.group(2))]
	body = b[m.end():].split("\n    case ")[0]
	fall = bool(re.match(r"\s*goto LABEL_214;", body[:300]))
	for c in idsx: cases[c] = ("fallthrough" if fall else "handled", subs_in(body[:4000])[:6])
base_src = open(os.path.join(ODEC, "44B099.c")).read()
base_cases = {}
for m in re.finditer(r"\n      case (0x[0-9A-Fa-f]+|\d+)u?:", base_src.split("switch ( v479 )", 1)[0] and base_src):
	pass
body = base_src.split("switch ( v479 )", 1)[1]
cur = []
for chunk in re.split(r"(\n\s*case (?:0x[0-9A-Fa-f]+|\d+)u?:)", body):
	m = re.match(r"\n\s*case (0x[0-9A-Fa-f]+|\d+)u?:", chunk)
	if m: cur.append(int(m.group(1), 0)); continue
	if cur:
		s = subs_in(chunk[:4000])[:6]
		for c in cur: base_cases.setdefault(c, s)
		if chunk.strip(): cur = []
scr = json.load(open("scripts.json")) if os.path.exists("scripts.json") else {}
uses = {}
for kind in ("actions", "triggers"):
	for it in (scr.get(kind) or []):
		if isinstance(it, dict): uses[(kind, it.get("id"))] = (it.get("uses"), it.get("gemrb"))
rows = []
for a in sorted(set(act) | set(base_cases) | set(range(0x130))):
	if a not in act and a not in base_cases: continue
	c = tab[a] if a < 0x130 else None
	st, s = cases.get(c, (None, [])) if c is not None else (None, [])
	if a == 313: st, c = "handled", 57
	handler = "sprite case %s" % c if st == "handled" else ("base sub_44B099" if a in base_cases else "none")
	if st == "handled":
		for x in s[:1]: role[x].append("action %d %s (sprite case %s)" % (a, act.get(a, "?").split("(")[0], c))
	u = uses.get(("actions", a), (None, None))
	rows.append((a, act.get(a), c, handler, " ".join(s) if st == "handled" else " ".join(base_cases.get(a, [])), u[0], u[1]))
write("actions.tsv", ["id", "action_ids", "sprite_case", "handler", "orig_subs_called", "uses", "gemrb"], rows,
	"Original action dispatch: sub_76A7EA switch on byte_76D476[id] (ids < 0x130), else base switch sub_44B099. Read the case in .re/orig/dump/dec/76A7EA.c or 44B099.c")

# ---------- triggers ----------
rows = []
tsrc = {f: open(os.path.join(ODEC, f + ".c")).read() for f in ("453258", "778529")}
tcase = {}
for f, s in tsrc.items():
	for m in re.finditer(r"case (0x[0-9A-Fa-f]+|\d+)u?:", s):
		tcase.setdefault(int(m.group(1), 0), []).append(f)
for t in sorted(set(trg) | set(tcase)):
	u = uses.get(("triggers", t), (None, None))
	rows.append(("0x%04X" % t, trg.get(t), ",".join(sorted(set(tcase.get(t, [])))) or "none (always false)", u[0], u[1]))
write("triggers.tsv", ["id", "trigger_ids", "orig_dispatcher", "uses", "gemrb"], rows,
	"Original trigger handlers: case <id> in sub_453258 (base) / sub_778529 (creature). Event triggers (< 0x4000) are raised elsewhere")

# ---------- hardcoded spells (projectile switch sub_559A5D) ----------
src = open(os.path.join(ODEC, "559A5D.c")).read()
parts = re.split(r"\n    case (0x[0-9A-F]+|\d+)u:", src)
proj = {}
for i in range(1, len(parts), 2):
	k = int(parts[i], 0); body = parts[i + 1].split("break;")[0]
	s = [x for x in subs_in(body) if x not in ("559A5D",)]
	res = re.findall(r"\ba(S[0-9a-z_]+)\)", body)
	proj[k] = (s, res)
vts = collections.defaultdict(dict)
if os.path.exists("orig/spell_vt.txt"):
	for l in open("orig/spell_vt.txt"):
		q = l.rstrip("\n").split("\t")
		if len(q) >= 3: vts[q[0]][int(q[1])] = q[2]
def ctor_vt(a):
	f = os.path.join(ODEC, a + ".c")
	if not os.path.exists(f): return None
	t = open(f).read()
	m = re.findall(r"\*(?:\(_DWORD \*\))?this = &?off_([0-9A-F]+)", t) or re.findall(r"= &?off_([0-9A-F]+)", t)
	return m[-1] if m else None
psmap = json.load(open("psorig.json")) if os.path.exists("psorig.json") else {}
# SPL -> projectile (original data)
import struct
splproj = collections.defaultdict(list)
for r in o.names("spl"):
	d = o.res(r, "spl")
	if not d or len(d) < 0x6A: continue
	off, n = struct.unpack_from("<IH", d, 0x64)
	for i in range(min(n, 30)):
		if off + i * 40 + 0x28 <= len(d):
			pv = struct.unpack_from("<H", d, off + i * 40 + 0x26)[0]
			if r not in splproj[pv]: splproj[pv].append(r)
prjtl = {}
for l in pstres.text(o.res("projectl", "ids") or b"").splitlines() if o.res("projectl", "ids") else []:
	m = re.match(r"\s*(\d+)\s+(\S+)", l)
	if m: prjtl[int(m.group(1))] = m.group(2)
gem = {}
gp = os.path.join(os.path.dirname(OUT), "..", "..", "gemrb", "unhardcoded", "pst", "gemprjtl.ids")
for l in open(os.path.normpath(gp)):
	m = re.match(r"\s*(\d+)\s+(\S+)", l)
	if m: gem[int(m.group(1)) + 1] = m.group(2)
# EE class per projectile: SPL -> class from spells.md, plus the classes no PST SPL names directly
spl_cls = {}
for l in open(os.path.join(os.path.dirname(OUT), "spells.md"), encoding="utf-8"):
	m = re.match(r"\| (SP\w+) \| (\w+) \|", l)
	if m: spl_cls[m.group(1)] = "CPsSpell" + m.group(2)
proj_cls = {241: "CPsSpellAxOfTorment", 253: "CPSTSpellMechanusCannon", 260: "CPSTSpellSpiritualHammer",
	261: "CPSTSpellCallLightning", 227: "CPsSpellForceMissile", 281: "CPsSpellForceMissile", 224: "CBallLightningSphere?",
	225: "CPsSpellBallLightning?", 205: "CProjectileSpeakWithDead", 216: "CSkullMob", 217: "CSkullMobChunk"}
rows = []
for k in sorted(proj):
	s, res = proj[k]
	if not s and not res: continue
	ctor = next((x for x in s if x not in ("4128C8", "433BC0", "405F00", "40F27B", "40EFAD", "569C2A", "4EB0A0", "57A130", "83DA4F", "462C70")), s[0] if s else None)
	vt = ctor_vt(ctor) if ctor else None
	sl = vts.get(vt, {})
	ai, fire, rend = sl.get(3), sl.get(35), sl.get(18)
	cls = proj_cls.get(k) or next((spl_cls[x] for x in splproj.get(k, []) if x in spl_cls), "")
	for x, r in ((ctor, "ctor"), (ai, "AIUpdate"), (fire, "Fire"), (rend, "Render")):
		if x and k >= 205: role[x].append("projectile %d %s %s" % (k, cls or "", r))
	rows.append((k, gem.get(k), " ".join(splproj.get(k, [])[:6]), cls, ctor, vt, ai, fire, rend, " ".join(res[:3])))
write("projectiles.tsv", ["projectile", "gemrb_pro", "spl_using_it", "ee_class", "orig_ctor", "orig_vtable", "orig_AIUpdate(slot3)", "orig_Fire(slot35)", "orig_Render(slot18)", "resrefs_in_case"], rows,
	"Original projectile factory sub_559A5D: switch on the SPL/ITM projectile number. Vtable slot 3 = AIUpdate, 18 = Render, 35 = Fire (spell classes). Slots read from .re/orig/spell_vt.txt")

# ---------- index of original functions with a known role ----------
for c, v in psmap.items():
	for f, n in v["orig"][:3]:
		if f: role[f.replace("sub_", "")].append("uses resrefs of %s" % c)
known = {
	"4A5C21": "effect factory (opcode -> effect object)", "559A5D": "projectile factory (projectile number -> object)",
	"76A7EA": "creature action dispatcher", "44B099": "base action dispatcher", "453258": "base trigger dispatcher",
	"778529": "creature trigger dispatcher", "41D7BC": "script compiler/parser", "4B5DCF": "creature death handling (Nameless One rules, Game_Over)",
	"785E47": "MoveToObjectEx timeout", "4089DC": "JoinPartyEx flag helper", "4A56EB": "CGameEffect constructor (opcode, p1, p2, timing, ...)",
	"5A4864": "object id -> object (GetShare)", "89BC79": "CString from literal", "463F03": "global variable lookup",
}
for a, d in known.items(): role[a].insert(0, d)
rows = [(a, osize.get(a), srcfile.get(a, ""), "; ".join(dict.fromkeys(role[a])), "y" if odec(a) else "n") for a in sorted(role)]
write("orig_index.tsv", ["addr", "size", "assert_source", "role", "decompiled"], rows,
	"Original Torment.exe functions whose role we know. Decompiled bodies: .re/orig/dump/dec/<addr>.c (git-ignored)")

# ---------- EE symbols worth knowing (PST-specific and effect/projectile classes) ----------
keep = re.compile(r"^(CPsSpell|CPSTSpell|CPlanescape|CPST|CGameEffect|CProjectile|CMeteorStorm|CScreenRangeFlashTint)|::(HandleNameless|SpellPST|ForceSpellPST)")
ee_dec = [f[:-2] for f in os.listdir(EDEC) if f.endswith(".c")]
rows = []
for l in open("ee/dump/funcs.txt", encoding="utf-8", errors="replace"):
	q = l.rstrip("\n").split("\t")
	if len(q) >= 3 and keep.search(q[2]):
		fn = re.sub(r"[^A-Za-z0-9_]+", "_", q[2])
		rows.append((q[0], q[1], q[2], "y" if any(f.startswith(fn[:min(len(fn), 50)]) for f in ee_dec) else "n"))
write("ee_symbols.tsv", ["addr", "size", "name", "decompiled"], rows,
	"PST:EE Torment64 symbols for PST-only, effect and projectile classes. Decompiled: .re/ee/dump/dec/<Class_Method>.c")

# ---------- identifier strings -> original functions ----------
rows = []
for l in open("orig/dump/strings.txt", encoding="utf-8", errors="replace"):
	q = l.rstrip("\n").split("\t")
	if len(q) >= 3 and q[2] and re.fullmatch(r"[A-Za-z0-9_#\-\.\*]{3,40}", q[1]):
		rows.append((q[0], q[1], q[2]))
write("orig_strings.tsv", ["addr", "string", "used_by"], rows,
	"Identifier-like strings in the original exe (resrefs, variables, table names) and the functions that use them")
