"""Build the script coverage ledger: one row per action / trigger PST's scripts and dialogs use, plus the
GemRB-only script BALDUR.bcs. The verdict columns are filled by hand (dev/parity/AGENT_GUIDE.md, track A).

python tools/parity/script_ledger.py          # writes dev/parity/script_ledger.tsv (keeps existing verdicts)
python tools/parity/script_ledger.py set action 219 V A10 "note"   # set one row's verdict (by = the session's model)
python tools/parity/script_ledger.py setmany rows.tsv              # many rows: kind, id, status, finding, note[, by] per line, tab-separated

Columns: kind, id, name, uses, orig_handler, gemrb, status, finding, by, audited, note.
status: todo | P (parity) | V (verified difference, finding written) | S | ? (see AGENT_GUIDE section 5).
"""
import csv, os, re, sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
MAPS = os.path.join(ROOT, "dev", "parity", "maps")
OUT = os.path.join(ROOT, "dev", "parity", "script_ledger.tsv")
BAF = os.path.join(ROOT, "gemrb", "unhardcoded", "pst", "source", "baldur.baf")
OBJECTS = [("1", "Myself", 10016), ("name", "by script name", 2632), ("12", "NearestEnemyOf", 2325),
	("10", "LastAttackerOf", 1377), ("16", "LastHelp", 606), ("27", "Protagonist", 5587),
	("21", "Player1", 79), ("22", "Player2", 26), ("23", "Player3", 26), ("24", "Player4", 24), ("25", "Player5", 24),
	("26", "Player6", 22), ("6", "MostDamagedOf", 11), ("14", "Nearest", 4), ("17", "LastTrigger", 3),
	("ea", "IDS field ea", 3336), ("specific", "IDS field specific", 618), ("team", "IDS field team", 361),
	("gender", "IDS field gender", 189), ("race", "IDS field race", 159), ("align", "IDS field align", 153),
	("general", "IDS field general", 66), ("faction", "IDS field faction", 17), ("pc", "[PC] in DLG text", 49)]
COLS = ["kind", "id", "name", "uses", "orig_handler", "gemrb", "status", "finding", "by", "audited", "note"]
KEEP = ["status", "finding", "by", "audited", "note"]

def load(name):
	lines = [l for l in open(os.path.join(MAPS, name), encoding="utf-8") if not l.startswith("#")]
	return list(csv.DictReader(lines, delimiter="\t"))

def set_row(kind, rid, status, finding, note, by):
	lines = open(OUT, encoding="utf-8").read().splitlines(True)
	for i, l in enumerate(lines):
		c = l.rstrip("\n").split("\t")
		if len(c) == len(COLS) and c[0] == kind and c[1].lower() == rid.lower():
			c[6:9] = [status, finding, by]; c[10] = note
			lines[i] = "\t".join(c) + "\n"
			open(OUT, "w", encoding="utf-8", newline="").writelines(lines)
			print("set", kind, rid, c[2], status); return
	sys.exit("no row %s %s" % (kind, rid))

def main():
	if len(sys.argv) > 2 and sys.argv[1] == "setmany":
		# one row per line: kind<TAB>id<TAB>status<TAB>finding<TAB>note[<TAB>by]  (no shell quoting needed)
		for line in open(sys.argv[2], encoding="utf-8"):
			a = line.rstrip("\r\n").split("\t")
			if len(a) >= 4 and not line.startswith("#"):
				set_row(a[0], a[1], a[2], a[3], a[4] if len(a) > 4 else "", a[5] if len(a) > 5 else "opus")
		return
	if len(sys.argv) > 1 and sys.argv[1] == "set":
		a = sys.argv[2:]
		return set_row(a[0], a[1], a[2], a[3], a[4] if len(a) > 4 else "", a[5] if len(a) > 5 else "opus")
	old = {}
	if os.path.exists(OUT):
		lines = [l for l in open(OUT, encoding="utf-8") if not l.startswith("#")]
		for r in csv.DictReader(lines, delimiter="\t"):
			old[(r["kind"], r["id"])] = r
	rows = []
	for r in load("actions.tsv"):
		if int(r["uses"] or 0) > 0:
			rows.append({"kind": "action", "id": r["id"], "name": r["action_ids"], "uses": r["uses"],
				"orig_handler": r["handler"], "gemrb": r["gemrb"]})
	for r in load("triggers.tsv"):
		if int(r["uses"] or 0) > 0:
			ev = int(r["id"], 16) < 0x4000
			rows.append({"kind": "event" if ev else "trigger", "id": r["id"], "name": r["trigger_ids"],
				"uses": r["uses"], "orig_handler": "raised elsewhere (find it)" if ev else r["orig_dispatcher"],
				"gemrb": r["gemrb"]})
	if os.path.exists(BAF):
		text = open(BAF, encoding="latin1").read()
		for i, block in enumerate(re.findall(r"^IF\b.*?^END\b", text, re.S | re.M)):
			first = " ".join(l.strip() for l in block.splitlines()[1:4])
			rows.append({"kind": "baldur", "id": "block%02d" % i, "name": first[:120], "uses": "1",
				"orig_handler": "hardcoded? find it", "gemrb": "unhardcoded/pst/source/baldur.baf"})
	# object selectors and IDS fields PST uses (counts: bcs.py --objects, BCS + DLG text; wp5_objects.md)
	for oid, name, uses in OBJECTS:
		rows.append({"kind": "object", "id": oid, "name": name, "uses": str(uses),
			"orig_handler": "sub_40F77C / EE CAIObjectType::Decode", "gemrb": "GameScript/Objects.cpp, Matching.cpp"})
	for r in rows:
		o = old.get((r["kind"], r["id"]), {})
		for k in KEEP:
			r[k] = o.get(k, "todo" if k == "status" else "")
	order = {"action": 0, "trigger": 1, "event": 2, "baldur": 3, "object": 4}
	rows.sort(key=lambda r: (order[r["kind"]], -int(r["uses"] or 0)))
	with open(OUT, "w", encoding="utf-8", newline="") as f:
		f.write("# Script coverage ledger (tools/parity/script_ledger.py). Fill status/finding/by/note by hand; rerun keeps them.\n")
		w = csv.DictWriter(f, COLS, delimiter="\t", lineterminator="\n")
		w.writeheader()
		w.writerows(rows)
	n = {k: sum(1 for r in rows if r["kind"] == k) for k in order}
	done = sum(1 for r in rows if r["status"] not in ("todo", ""))
	print("%s: %d rows %s, %d with a verdict" % (OUT, len(rows), n, done))

if __name__ == "__main__":
	main()
