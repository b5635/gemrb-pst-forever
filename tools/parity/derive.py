# Derived tables from the IDA dumps (run after the IDA passes, see README.md):
#   psbehav.json      effects and logic each EE CPsSpell* class applies in code
#   orig_actions.json actions the original Torment.exe handles (sprite switch + base switch)
#   orig_opvt.json    original opcode -> effect vtable; orig_apply.json opcode -> ApplyEffect address
import os, re, json, collections, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.environ.get("PARITY_WORK", r"D:\gemrb\.re"))
from pe import PE

# --- EE spell classes
ee = json.load(open("ee_opcodes.json"))
D = "ee/dump/dec"; by = collections.defaultdict(str)
for f in os.listdir(D):
	m = re.match(r"(CPsSpell\w+?)_", f)
	if m: by[m.group(1)] += open(os.path.join(D, f), encoding="utf-8").read()
FEATS = [("rolls to-hit", r"ProjectileRollToHit"), ("death effect", r"CGameEffectDeath"), ("damage effect", r"CGameEffectDamage"),
	("loads SPL effects", r"CSpell::GetAbilityEffect|LoadEffects|TransferEffects"), ("area search", r"GetAllInRange"),
	("HP-pool targeting", r"\+ 1396LL"), ("caster level", r"GetCasterLevel"), ("random", r"rand\(\)"), ("hit trigger", r"SendHitTrigger"),
	("screen flash/tint", r"SetScreenFlash|FlashTint|Tint"), ("background swap", r"SetBackgroundBmp"), ("moves creatures", r"JumpToPoint|SetSequence"),
	("checks spell state", r"GetSpellState"), ("checks undead/race", r"G_UNDEAD|RACE|GENERAL")]
res = {}
for c, s in sorted(by.items()):
	ops = sorted({int(x) for x in re.findall(r"ClearItemEffect\([^,]+, (\d+)\)", s)})
	res[c] = dict(opcodes=[(o, ee.get(str(o), "?")) for o in ops], features=[k for k, p in FEATS if re.search(p, s)])
json.dump(res, open("psbehav.json", "w"), indent=1)

# --- original effect vtables / apply functions
s = open("orig/dump/dec/4A5C21.c").read().split("switch", 1)[1]
vt, cur = {}, []
for line in s.splitlines():
	m = re.match(r"\s*case (0x[0-9A-F]+|\d+)u?:", line)
	if m: cur.append(int(m.group(1), 0)); continue
	m = re.search(r"= &off_([0-9A-F]+);", line)
	if m and cur:
		for c in cur: vt.setdefault(c, m.group(1))
		cur = []
	if re.match(r"\s*(break|return)", line): cur = []
json.dump(vt, open("orig_opvt.json", "w"))
if os.path.exists("orig/dump/vt.txt"):
	slot2 = {}
	for l in open("orig/dump/vt.txt"):
		a, i, f, n = l.rstrip("\n").split("\t")
		if i == "2": slot2[a] = f
	json.dump({op: slot2.get(v) for op, v in vt.items()}, open("orig_apply.json", "w"))

# --- original actions: sprite-level switch (sub_76A7EA, byte table at 0x76D476, 313 special-cased) + base (sub_44B099)
p = PE("orig/Torment.exe")
tab = p.bytes(0x76D476, 0x130)
body = open("orig/dump/dec/76A7EA.c").read().split("switch ( v6 )", 1)[1]
handled = set()
for b in re.split(r"\n    case ", body)[1:]:
	m = re.match(r"(\d+):((?:\s*case \d+:)*)", b)
	ids = [int(m.group(1))] + [int(x) for x in re.findall(r"case (\d+):", m.group(2))]
	if not re.match(r"\s*goto LABEL_214;", b[m.end():m.end() + 300]): handled.update(ids)
spr = {a for a in range(0x130) if tab[a] in handled} | {313}
base = {int(x, 0) for x in re.findall(r"case (0x[0-9A-Fa-f]+|\d+)u?:", open("orig/dump/dec/44B099.c").read())}
json.dump(dict(sprite=sorted(spr), base=sorted(base)), open("orig_actions.json", "w"))
trg = set()
for f in ("453258", "778529"):
	trg |= {int(x, 0) for x in re.findall(r"case (0x[0-9A-Fa-f]+|\d+)u?:", open("orig/dump/dec/%s.c" % f).read())}
json.dump(sorted(trg), open("orig_triggers.json", "w"))
print("ok", len(res), len(vt), len(spr | base), len(trg))
