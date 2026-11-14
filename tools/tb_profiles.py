# Runs inside the game (tools\tb_analyze.ps1 feeds it to the DevConsole): analyzes every compiled
# script of the game with GemRB.AnalyzeCombatScript and writes a report of combat profiles and
# the actions the turn based director has no rule for.
import os
import struct
import GemRB

GAME = r"__GAMEPATH__"
OUT = os.path.join("dev", "combat_profiles.md")
BCS = 0x3EF

def key_scripts(path):
	names = set()
	with open(path, "rb") as f:
		data = f.read()
	if data[:8] != b"KEY V1  ":
		return names
	bifs, count, bifoff, resoff = struct.unpack_from("<4I", data, 8)
	for i in range(count):
		off = resoff + i * 14
		name = data[off:off + 8].split(b"\0")[0].decode("ascii", "replace")
		rtype = struct.unpack_from("<H", data, off + 8)[0]
		if rtype == BCS and name:
			names.add(name.upper())
	return names

scripts = key_scripts(os.path.join(GAME, "chitin.key"))
override = os.path.join(GAME, "override")
if os.path.isdir(override):
	for f in os.listdir(override):
		if f.lower().endswith(".bcs"):
			scripts.add(f[:-4].upper())

profiles = {}
for name in sorted(scripts):
	p = GemRB.AnalyzeCombatScript(name)
	if p["Found"]:
		profiles[name] = p

combat = {n: p for n, p in profiles.items() if p["CombatBlocks"]}
archetypes = {}
unmapped = {}
actions = {}
triggers = {}
for n, p in combat.items():
	archetypes.setdefault(p["Archetype"], []).append(n)
	for k, v in p["Unmapped"].items():
		unmapped.setdefault(k, [0, []])
		unmapped[k][0] += v
		unmapped[k][1].append(n)
	for k, v in p["Actions"].items():
		actions[k] = actions.get(k, 0) + v
	for k, v in p["Triggers"].items():
		triggers[k] = triggers.get(k, 0) + v

def top(d, n=25):
	return sorted(d.items(), key=lambda kv: -kv[1])[:n]

lines = []
lines.append("# Combat profiles of every PST script\n")
lines.append("%d scripts, %d with combat blocks, %d combat blocks of %d.\n" % (
	len(profiles), len(combat), sum(p["CombatBlocks"] for p in combat.values()), sum(p["Blocks"] for p in combat.values())))
lines.append("## Archetypes\n")
for a, names in sorted(archetypes.items(), key=lambda kv: -len(kv[1])):
	lines.append("- **%s**: %d (%s%s)" % (a, len(names), ", ".join(names[:8]), ", ..." if len(names) > 8 else ""))
lines.append("\n## Unmapped time-taking actions in combat blocks\n")
if not unmapped:
	lines.append("none")
for k, (v, names) in sorted(unmapped.items(), key=lambda kv: -kv[1][0]):
	lines.append("- `%s` x%d in %s%s" % (k, v, ", ".join(names[:6]), ", ..." if len(names) > 6 else ""))
lines.append("\n## Actions in combat blocks\n")
for k, v in top(actions):
	lines.append("- `%s` %d" % (k, v))
lines.append("\n## Triggers in combat blocks\n")
for k, v in top(triggers):
	lines.append("- `%s` %d" % (k, v))
lines.append("\n## Scripts\n")
lines.append("| script | archetype | blocks | combat | flee below HP | spells |")
lines.append("| --- | --- | ---: | ---: | ---: | --- |")
for n, p in sorted(combat.items()):
	lines.append("| %s | %s | %d | %d | %s | %s |" % (n, p["Archetype"], p["Blocks"], p["CombatBlocks"],
		p["FleeBelowHP"] if p["FleeBelowHP"] >= 0 else "", " ".join(p["Spells"])))

os.makedirs("dev", exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
	f.write("\n".join(lines) + "\n")
print("%d scripts, %d combat, report in %s" % (len(profiles), len(combat), os.path.abspath(OUT)))
for a, names in sorted(archetypes.items(), key=lambda kv: -len(kv[1])):
	print(a, len(names))
print("unmapped:", ", ".join("%s x%d" % (k, v[0]) for k, v in sorted(unmapped.items(), key=lambda kv: -kv[1][0])[:15]))
