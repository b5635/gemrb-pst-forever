# Hardcoded special cases inside EE effect classes used by PST data: literal resrefs, plane checks, spell states,
# sub-effects. Each one is PST engine behaviour GemRB has to reproduce. -> fxspecial.json
import os, re, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.environ.get("PARITY_WORK", r"D:\gemrb\.re"))
opmap = json.load(open("opmap.json"))["map"]
cls2op = {}
for op, v in opmap.items():
	for ee_op, n, cls, ex in v: cls2op.setdefault(cls, set()).add(int(op))
D = "ee/dump/dec"; out = {}
gem = ""
for f in ("FXOpcodes/FXOpcodes.cpp", "PSTOpcodes/PSTOpcodes.cpp"):
	gem += open(os.path.join(r"D:\gemrb\gemrb\plugins", f), encoding="utf-8", errors="replace").read().upper()
for f in sorted(os.listdir(D)):
	m = re.match(r"(CGameEffect\w+?)_(ApplyEffect|OnAddSpecific|OnRemove|CheckSave)_", f)
	if not m or m.group(1) not in cls2op: continue
	s = open(os.path.join(D, f), encoding="utf-8").read()
	e = out.setdefault(m.group(1), dict(ops=sorted(cls2op[m.group(1)]), resrefs=set(), planes=set(), spellstates=set(), subfx=set(), pst=set(), lines=0))
	e["lines"] += s.count("\n")
	e["resrefs"] |= set(re.findall(r'"([A-Z0-9_]{3,8})"', s))
	e["planes"] |= set(re.findall(r"CPlanescape::IsIn(\w+)", s))
	e["spellstates"] |= {int(x, 0) for x in re.findall(r"GetSpellState\([^,]+, (0x[0-9A-F]+|\d+)u?\)", s)}
	e["subfx"] |= {int(x) for x in re.findall(r"ClearItemEffect\([^,]+, (\d+)\)", s)}
	e["pst"] |= set(re.findall(r"(CPlanescape::\w+|ENGINE_MODE == 3)", s))
res = {}
for c, e in out.items():
	e = {k: sorted(v) if isinstance(v, set) else v for k, v in e.items()}
	e["resrefs_not_in_gemrb"] = [r for r in e["resrefs"] if r not in gem]
	res[c] = e
json.dump(res, open("fxspecial.json", "w"), indent=1)
for c, e in sorted(res.items(), key=lambda x: x[1]["ops"]):
	if e["resrefs"] or e["planes"] or e["spellstates"] or e["subfx"] or len(e["pst"]) > 0:
		print(e["ops"], c[11:], e["lines"], "| res:", " ".join(e["resrefs"]), "| notGemRB:", " ".join(e["resrefs_not_in_gemrb"]), "| planes:", ",".join(e["planes"]), "| states:", e["spellstates"], "| subfx:", e["subfx"], "| pst:", ",".join(x.replace("CPlanescape::", "") for x in e["pst"]))
