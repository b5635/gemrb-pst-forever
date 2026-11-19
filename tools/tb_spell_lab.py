# Turn based spell lab: helpers loaded into the dev console (dev.ps1 pyfile tools\tb_spell_lab.py).
# Spawns targets near the party, starts a fight, casts spells by spell.ids number and reports what
# each target's HP, states and effect queue did, with the turn based combat clock.
#
#   lab_spawn(["THUGB1", "ZOMBIE"])   creatures next to party slot 1, hostile; returns global IDs
#   snap(gid)                         dict: HP, state, effects (opcode/timing/duration/source)
#   cast(caster, spell, target)       ForceSpell (point spells: target may be a creature, aimed at it)
#   show(gid)                         print the snapshot
#   doomed(gid)                       its saves always fail
import GemRB

IE_HITPOINTS = 0
IE_SAVES = (9, 10, 11, 12, 13)
IE_STATE_ID = 206
TIMING = {0: "lim", 1: "perm", 2: "equip", 3: "delay-lim", 4: "delay-perm", 5: "delay-unsaved", 6: "delay-pending",
	7: "after-expires", 8: "perm-unsaved", 9: "perm-after-bonus", 10: "lim-ticks", 11: "expired", 4096: "until"}

def lab_spawn(cres, near=1, hostile=True):
	ids = []
	for cre in cres:
		gid = GemRB.CreateCreature(near, cre)
		ids.append(gid)
		if hostile:
			GemRB.ExecuteString("Enemy()", gid)
	return ids

def pos(gid):
	d = GemRB.DebugEffects(gid)
	return d["X"], d["Y"]

def place(gid, x, y):
	GemRB.ExecuteString("JumpToPoint([%d.%d])" % (x, y), gid)

def cluster(caster, ids, dx=90, dy=40, gap=28):
	"""Puts the targets side by side dx/dy pixels from the caster (a tight group for area spells)."""
	cx, cy = pos(caster)
	for i, gid in enumerate(ids):
		place(gid, cx + dx + (i - len(ids) // 2) * gap, cy + dy + (i % 2) * gap)

def level(gid, lvl):
	for stat in (34, 68, 69): # IE_LEVEL, IE_LEVEL2, IE_LEVEL3
		GemRB.SetPlayerStat(gid, stat, lvl)

def hostile(ids):
	for gid in ids:
		GemRB.ExecuteString("Enemy()", gid)

def lab(cres, caster=10004, lvl=12, dx=90, dy=40):
	"""Peaceful spawn, grouped in front of the caster, caster levelled; call hostile(ids) to start."""
	ids = lab_spawn(cres, hostile=False)
	level(caster, lvl)
	cluster(caster, ids, dx, dy)
	return ids

def doomed(gid):
	for stat in IE_SAVES:
		GemRB.SetPlayerStat(gid, stat, 30)

def snap(gid):
	d = GemRB.DebugEffects(gid)
	fx = []
	for e in d["Effects"]:
		fx.append((e["Opcode"], TIMING.get(e["Timing"], e["Timing"]), e["Duration"], e["Source"], e["Param1"], e["Param2"]))
	return {
		"HP": GemRB.GetPlayerStat(gid, IE_HITPOINTS),
		"State": GemRB.GetPlayerStat(gid, IE_STATE_ID),
		"Clock": d["Clock"], "GameTime": d["GameTime"], "Round": d["Round"],
		"Effects": fx,
	}

def show(gid, label=""):
	s = snap(gid)
	clock = s["Clock"] or s["GameTime"]
	print("%s #%d HP=%d state=%#x clock=%d" % (label, gid, s["HP"], s["State"], clock))
	for op, tm, dur, src, p1, p2 in s["Effects"]:
		left = ""
		if tm not in ("perm", "equip", "perm-unsaved", "perm-after-bonus"):
			left = " left=%d ticks (%.2f rounds)" % (dur - clock, (dur - clock) / float(s["Round"]))
		print("   op%d %s dur=%d%s src=%s p1=%d p2=%d" % (op, tm, dur, left, src, p1, p2))

def cast(caster, spell, target):
	GemRB.ExecuteActionAt(caster, "ForceSpell([-1],%d)" % spell, target)

def order():
	o = GemRB.GetTurnOrder()
	if not o:
		print("no fight")
		return
	print("round", o["Round"], "active", o["Active"])
	for c in o["Combatants"]:
		print("  %6d %-24s HP %d/%d done=%s dead=%s hostile=%s" % (c["ID"], c["Name"], c["HP"], c["MaxHP"], c["Done"], c["Dead"], c["Hostile"]))

print("spell lab loaded")

# ------------------------------------------------------------------------------------------
# suite helpers (tools\tb_spell_suite.ps1)
import json

PARTY = (10002, 10003, 10004)
TARGET_CRES = ("THUGB1", "THUGB1", "ZOMBIE")
suite = globals().setdefault("suite", {"targets": [], "old": []})

def quiet(gid):
	"""no AI: test targets stand still (and never knock a caster prone)"""
	for level in range(8):
		GemRB.ExecuteString('ChangeAIScript("",%d)' % level, gid)

def sturdy(gid, hp):
	"""lots of HP, but only half of them: damage and healing both show"""
	GemRB.SetPlayerStat(gid, 1, hp) # IE_MAXHITPOINTS
	GemRB.SetPlayerStat(gid, 0, hp // 2)

def suite_party():
	for gid in PARTY:
		level(gid, 12)
		sturdy(gid, 999)

def suite_targets(caster):
	"""fresh, silent, sturdy targets in front of the caster; the previous ones are removed"""
	old = suite["targets"]
	ids = lab_spawn(list(TARGET_CRES), near=caster, hostile=False)
	for gid in ids:
		quiet(gid)
		doomed(gid)
		sturdy(gid, 300)
	cluster(caster, ids, 80, 30)
	suite["targets"] = ids
	suite["old"] = old
	print(json.dumps(ids))

def suite_engage():
	"""the new targets turn hostile at once (EA, not a queued Enemy() action)"""
	for gid in suite["targets"]:
		GemRB.SetPlayerStat(gid, 234, 255) # IE_EA: ENEMY

def suite_clear():
	"""the previous targets go, once the new ones are in the fight"""
	for gid in suite["old"]:
		GemRB.ApplyEffect(gid, "Death", 0, 0)
	suite["old"] = []

def suite_snap(ids):
	out = {}
	for gid in ids:
		try:
			d = GemRB.DebugEffects(gid)
		except RuntimeError: # gone (destroyed after death)
			out[gid] = {"HP": 0, "State": -1, "Clock": 0, "Time": 0, "Fx": []}
			continue
		out[gid] = {
			"HP": GemRB.GetPlayerStat(gid, IE_HITPOINTS), "State": GemRB.GetPlayerStat(gid, IE_STATE_ID),
			"Clock": d["Clock"], "Time": d["GameTime"],
			"Fx": [[e["Opcode"], e["Timing"], e["Duration"], e["Source"], e["Param1"], e["Param2"], e["TurnOnset"]] for e in d["Effects"]],
		}
	print(json.dumps(out))

def suite_status(caster):
	o = GemRB.GetTurnOrder()
	b = GemRB.GetTurnBudget()
	d = GemRB.DebugEffects(caster)
	print(json.dumps({"fight": bool(o), "active": o and o["Active"], "round": o and o["Round"],
		"busy": bool(b and b["Busy"]), "time": d["GameTime"], "fading": d["Fading"], "shake": d["Shake"]}))
