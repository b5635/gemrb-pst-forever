# Turn based spell suite (tier 2): casts every spell in dev/spell_manifest.json in a staged
# Mortuary fight and checks how it plays out in turn based combat.
#
#   python tools/tb_spell_suite.py                     all spells
#   python tools/tb_spell_suite.py SPWI502 SPWI401     just these
#   python tools/tb_spell_suite.py --from SPWI3        resume at a resref prefix (keeps earlier results)
#   python tools/tb_spell_suite.py --realtime SPWI101  the same with turn based combat off (a baseline:
#                                                      what fails here is GemRB/data, not turn based)
#
# For each spell: on the next party member's turn, three fresh silent targets (2 thugs, a zombie;
# saves always fail, 300 HP) stand in front of it; it casts (ForceSpell, level 12) at the middle
# one or at itself; the suite waits out the turn's hold and compares everyone before and after.
# Checks:
#   cast      the cast ran (gemrb.log)
#   pending   no delayed effect of the spell is still waiting once the turn is free again
#   rounding  new timed effects end on a turn boundary (N whole rounds) or within one round
#   clock     the world clock kept running while the turn was held
#   hold      the turn came free within 25 s, and the spell landed within the director's cap
#   change    something happened to someone (HP, state or a new non-cosmetic effect)
#   errors    no new ERROR lines in gemrb.log (known noise filtered)
#   crash     no crash or hang (crashes\last_crash.txt, crashes\last_hang.txt)
# Results: dev/spell_suite.jsonl (one line per spell) and dev/spell_report.md.
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tb_gamedata import REPO

GAME = r"C:\Games\GemRB"
DEV = os.path.join(GAME, "dev")
LOG = os.path.join(GAME, "gemrb.log")
CRASHES = os.path.join(GAME, "crashes")
LAB = os.path.join(REPO, "tools", "tb_spell_lab.py")
OUT_JSONL = os.path.join(REPO, "dev", "spell_suite.jsonl")
OUT_MD = os.path.join(REPO, "dev", "spell_report.md")
PARTY = (10002, 10003, 10004)
ROUND = 75
HOLD_MAX = 25.0
PER_SESSION = 12
REALTIME = False
NOISE = ("GetIWD2KitIndex", "DCTHB.2da", "Invalid item index", "Nonexistent random item", "bad table entry", "DgupCTHB")
DELAYED = (3, 4, 5, 6)
# spells that don't act on creatures in a fight (doors, items, the dead, information)
UTILITY = {"SPWI105", "SPWI215", "SPPR104", "SPPR304", "SPIN103", "SPIN108", "SPPR502", "SPPR307", "SPWI409",
	"SPWI120", "SPPR105", "SPIN104"}
# spells whose rules need a special target: "tno" (Embalming: the Nameless One or undead only),
# "weak" (Power Word, Blind skips creatures over 100 HP)
SETUP = {"SPWI103": "tno", "SPWI205": "tno", "SPWI805": "weak"}
# look only (glow, animations, sounds, screen tint/shake/flash): their timing isn't a rule
PRESENTATION = {9, 138, 174, 187, 188, 189, 190, 191, 193, 194, 195}

class GameGone(Exception):
	pass

def py(src, timeout=15):
	out = os.path.join(DEV, "out.txt")
	if os.path.exists(out):
		os.remove(out)
	tmp = os.path.join(DEV, "cmd.tmp")
	with open(tmp, "w", encoding="utf-8") as f:
		f.write(src)
	os.replace(tmp, os.path.join(DEV, "cmd.py"))
	deadline = time.time() + timeout
	while not os.path.exists(out):
		if time.time() > deadline:
			raise GameGone("no reply from the game")
		time.sleep(0.05)
	time.sleep(0.02)
	text = open(out, encoding="utf-8").read()
	return "\n".join(l for l in text.splitlines() if not l.startswith("#done")).strip()

def pyjson(src):
	text = py(src)
	for line in reversed(text.splitlines()):
		line = line.strip()
		if line.startswith("{") or line.startswith("["):
			return json.loads(line)
	raise RuntimeError("no json in reply: " + text[-400:])

def log_size():
	return os.path.getsize(LOG) if os.path.exists(LOG) else 0

def log_since(mark):
	with open(LOG, "rb") as f:
		f.seek(mark)
		return f.read().decode("utf-8", "replace").splitlines()

def fresh(name, since):
	path = os.path.join(CRASHES, name)
	if os.path.exists(path) and os.path.getmtime(path) >= since:
		lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
		return " | ".join(l.strip() for l in lines[1:6] if l.strip())
	return None

def start_game():
	ps = os.path.join(REPO, "tools", "dev.ps1")
	subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", ps, "start", "-Save", "2"], capture_output=True)
	deadline = time.time() + 90
	while time.time() < deadline:
		time.sleep(3)
		try:
			if py("print(GemRB.GetGameString(1))", timeout=5):
				break
		except GameGone:
			continue
	time.sleep(4)
	py(open(LAB, encoding="utf-8").read())
	py("suite_party()")
	if REALTIME:
		py("GemRB.SetVar('Turn Based Combat', 0)")

def wait_party_turn(limit=60):
	"""AI turns run by themselves; a party member's free turn is where the suite casts"""
	deadline = time.time() + limit
	while time.time() < deadline:
		st = pyjson("suite_status(10002)")
		if not st["fight"]:
			return None
		if st["active"] in PARTY and not st["busy"]:
			return st["active"]
		time.sleep(0.4)
	raise GameGone("no party turn within %ds" % limit)

def ensure_fight():
	if pyjson("suite_status(10002)")["fight"]:
		return
	pyjson("suite_targets(10002)")
	time.sleep(1.5)
	py("suite_engage()")
	time.sleep(2)
	# these stay tracked: the next spell's targets replace (and remove) them

def changes(before, after):
	"""per creature: HP and state change, and effects that weren't there (matched without duration)"""
	out = {}
	for gid, b in before.items():
		a = after.get(gid)
		if not a:
			continue
		left = [(f[0], f[3], f[4], f[5]) for f in b["Fx"]]
		new = []
		for f in a["Fx"]:
			key = (f[0], f[3], f[4], f[5])
			if key in left:
				left.remove(key)
			else:
				new.append(tuple(f))
		hp = a["HP"] - b["HP"]
		st = a["State"] ^ b["State"]
		if new or hp or st:
			out[gid] = {"hp": hp, "state": "%#x->%#x" % (b["State"], a["State"]) if st else "", "new": new,
				"clock": a["Clock"] or a["Time"]}
	return out

def run_spell_realtime(entry):
	"""baseline: no fight, peaceful targets in front of Dak'kon, 12 s to play out"""
	res = {"resref": entry["resref"], "name": entry["name"], "number": entry["number"], "problems": [], "notes": [], "realtime": True}
	caster = 10004
	targets = pyjson("suite_targets(%d)" % caster)
	time.sleep(1.5)
	py("suite_engage()") # hostile like in the fight (area spells pick sides); no fight with turn based off
	py("suite_clear()")
	everyone = list(PARTY) + targets
	before = pyjson("suite_snap(%s)" % everyone)
	mark = log_size()
	py("cast(%d, %d, %d)" % (caster, entry["number"], targets[1] if entry["target"] != 5 else caster))
	time.sleep(12)
	after = pyjson("suite_snap(%s)" % everyone)
	lines = log_since(mark)
	errors = sorted({l.strip() for l in lines if "ERROR" in l and not any(n in l for n in NOISE)})
	if errors:
		res["problems"].append("errors: " + " / ".join(e.split("]: ", 1)[-1] for e in errors[:3]))
	diff = changes(before, after)
	res["changes"] = {str(k): v for k, v in diff.items()}
	real = {gid: ch for gid, ch in diff.items() if ch["hp"] or ch["state"] or [f for f in ch["new"] if f[0] not in PRESENTATION]}
	if not real and entry["resref"] not in UTILITY:
		res["problems"].append("change: nothing happened to anyone")
	return res

def run_spell(entry):
	if REALTIME:
		return run_spell_realtime(entry)
	res = {"resref": entry["resref"], "name": entry["name"], "number": entry["number"], "problems": [], "notes": []}
	ensure_fight()
	caster = wait_party_turn()
	if caster is None:
		ensure_fight()
		caster = wait_party_turn()
	targets = pyjson("suite_targets(%d)" % caster)
	time.sleep(1.2)
	py("suite_engage()")
	time.sleep(1.0)
	py("suite_clear()")
	time.sleep(0.5)
	caster = wait_party_turn() or caster
	everyone = list(PARTY) + targets
	setup = SETUP.get(entry["resref"])
	if setup == "weak":
		py("[GemRB.SetPlayerStat(x, 0, 20) for x in %s]" % targets)
	before = pyjson("suite_snap(%s)" % everyone)
	mark = log_size()
	target = targets[1] if entry["target"] != 5 else caster
	if setup == "tno":
		target = 10002
	py("cast(%d, %d, %d)" % (caster, entry["number"], target))
	t0 = time.time()
	times = []
	stalled = 0.0
	while True:
		time.sleep(0.5)
		st = pyjson("suite_status(%d)" % caster)
		times.append(st["time"])
		if len(times) > 1 and times[-1] == times[-2] and st["busy"]:
			stalled += 0.5
		if not st["fight"] or (time.time() - t0 > 1.5 and not st["busy"]) or st["active"] != caster:
			break
		if time.time() - t0 > HOLD_MAX:
			res["problems"].append("hold: turn still busy after %ds" % HOLD_MAX)
			break
	res["held"] = round(time.time() - t0, 1)
	time.sleep(1.0) # deaths and the fight's end settle (states refresh on the handback)
	after = pyjson("suite_snap(%s)" % everyone)
	lines = log_since(mark)
	res["caster"] = caster
	res["cast"] = any("runs 'forcespell'" in l for l in lines)
	cast_check_pending = not res["cast"]
	errors = sorted({l.strip() for l in lines if "ERROR" in l and not any(n in l for n in NOISE)})
	if errors:
		res["problems"].append("errors: " + " / ".join(e.split("]: ", 1)[-1] for e in errors[:3]))
	if any("doesn't land" in l for l in lines):
		res["problems"].append("hold: spell didn't land within the director's cap")
	if stalled >= 2:
		res["problems"].append("clock: world time stood still %.1fs while held" % stalled)
	diff = changes(before, after)
	res["changes"] = {str(k): v for k, v in diff.items()}
	for gid, ch in diff.items():
		for op, timing, dur, source, p1, p2, realtime in ch["new"]:
			if timing in DELAYED and realtime:
				res["problems"].append("pending: op%d from %s on #%s still waiting for its real time onset" % (op, source, gid))
			elif timing in DELAYED:
				res["notes"].append("op%d scheduled %d rd out" % (op, (dur - ch["clock"]) // ROUND))
			elif timing == 0x1000 and dur > ch["clock"] and op not in PRESENTATION:
				left = dur - ch["clock"]
				if left >= ROUND and left % ROUND != 1:
					res["problems"].append("rounding: op%d on #%s ends %d ticks out (not a turn boundary)" % (op, gid, left))
				elif left >= ROUND:
					res["notes"].append("op%d %d rd" % (op, left // ROUND))
	real = {gid: ch for gid, ch in diff.items() if ch["hp"] or ch["state"] or [f for f in ch["new"] if f[0] not in PRESENTATION]}
	# the log line can be missed at the mark; anything the spell did proves the cast
	if cast_check_pending and not diff:
		res["problems"].append("cast: no forcespell in the log")
	if not real:
		if entry["resref"] in UTILITY:
			res["notes"].append("no effect on creatures (utility spell)")
		else:
			res["problems"].append("change: nothing happened to anyone")
	res["fight_over"] = not pyjson("suite_status(10002)")["fight"]
	if not res["fight_over"]:
		py("GemRB.EndTurn()")
	return res

def report(results):
	bad = [r for r in results if r["problems"]]
	lines = ["# Turn based spell suite", "",
		"Generated by `tools/tb_spell_suite.py` (see its header for the checks). %d spells: **%d with problems, %d clean.**"
		% (len(results), len(bad), len(results) - len(bad)), "",
		"| Spell | # | Held s | Problems | Notes |", "|---|---|---|---|---|"]
	for r in sorted(results, key=lambda r: (not r["problems"], r["resref"])):
		lines.append("| %s %s | %s | %s | %s | %s |" % (r["resref"], r["name"], r["number"], r.get("held", ""),
			"<br>".join(r["problems"]) or "ok", ", ".join(sorted(set(r.get("notes", []))))))
	with open(OUT_MD, "w", encoding="utf-8") as f:
		f.write("\n".join(lines) + "\n")

def main(args):
	global REALTIME, OUT_JSONL, OUT_MD
	if args and args[0] == "--realtime":
		REALTIME = True
		args = args[1:]
		OUT_JSONL = OUT_JSONL.replace(".jsonl", "_realtime.jsonl")
		OUT_MD = OUT_MD.replace(".md", "_realtime.md")
	manifest = json.load(open(os.path.join(REPO, "dev", "spell_manifest.json"), encoding="utf-8"))
	todo = [s for s in manifest if s["number"]]
	results = []
	if args and args[0] == "--from":
		todo = [s for s in todo if s["resref"] >= args[1].upper()]
		if os.path.exists(OUT_JSONL):
			results = [json.loads(l) for l in open(OUT_JSONL, encoding="utf-8")]
			done = {r["resref"] for r in results}
			todo = [s for s in todo if s["resref"] not in done]
	else:
		if args:
			want = {a.upper() for a in args}
			todo = [s for s in todo if s["resref"] in want]
		if os.path.exists(OUT_JSONL):
			os.remove(OUT_JSONL)
	done_in_session = PER_SESSION
	for entry in todo:
		r = None
		since = time.time()
		for attempt in (1, 2):
			try:
				if done_in_session >= PER_SESSION:
					start_game()
					done_in_session = 0
				# loading blocks the window for a while (preloaded art): hangs before this don't count
				since = time.time()
				r = run_spell(entry)
				done_in_session += 1
				break
			except (GameGone, RuntimeError, ValueError) as e:
				r = {"resref": entry["resref"], "name": entry["name"], "number": entry["number"],
					"problems": ["stall: %s (attempt %d)" % (e, attempt)], "notes": []}
				done_in_session = PER_SESSION # restart the game
				if fresh("last_crash.txt", since) or fresh("last_hang.txt", since):
					break # a real crash/hang: report it, don't retry
		for name, label in (("last_crash.txt", "CRASH"), ("last_hang.txt", "HANG")):
			text = fresh(name, since)
			if text:
				r["problems"].append("%s: %s" % (label, text[:300]))
				if label == "CRASH":
					done_in_session = PER_SESSION
		results.append(r)
		with open(OUT_JSONL, "a", encoding="utf-8") as f:
			f.write(json.dumps(r) + "\n")
		print("%-8s %-28s held %5ss  %s" % (r["resref"], r["name"][:28], r.get("held", "-"), "; ".join(r["problems"]) or "ok"), flush=True)
		report(results)

if __name__ == "__main__":
	main(sys.argv[1:])
