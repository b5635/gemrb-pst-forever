"""Build the script coverage ledger: one row per action / trigger PST's scripts and dialogs use, plus the
GemRB-only script BALDUR.bcs. The verdict columns are filled by hand (dev/parity/AGENT_GUIDE.md, track A).

python tools/parity/script_ledger.py          # writes dev/parity/script_ledger.tsv (keeps existing verdicts)

Columns: kind, id, name, uses, orig_handler, gemrb, status, finding, by, audited, note.
status: todo | P (parity) | V (verified difference, finding written) | S | ? (see AGENT_GUIDE section 5).
"""
import csv, os, re

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
MAPS = os.path.join(ROOT, "dev", "parity", "maps")
OUT = os.path.join(ROOT, "dev", "parity", "script_ledger.tsv")
BAF = os.path.join(ROOT, "gemrb", "unhardcoded", "pst", "source", "baldur.baf")
COLS = ["kind", "id", "name", "uses", "orig_handler", "gemrb", "status", "finding", "by", "audited", "note"]
KEEP = ["status", "finding", "by", "audited", "note"]

def load(name):
	lines = [l for l in open(os.path.join(MAPS, name), encoding="utf-8") if not l.startswith("#")]
	return list(csv.DictReader(lines, delimiter="\t"))

def main():
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
	for r in rows:
		o = old.get((r["kind"], r["id"]), {})
		for k in KEEP:
			r[k] = o.get(k, "todo" if k == "status" else "")
	order = {"action": 0, "trigger": 1, "event": 2, "baldur": 3}
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
