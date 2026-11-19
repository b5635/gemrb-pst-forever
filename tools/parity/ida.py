# One-command IDA helper for the parity audit (wraps idat.exe + the batch scripts next to this file).
#
#   python tools/parity/ida.py dec  ee   "CPsSpellIceKnife::"      decompile EE functions whose demangled name contains it
#   python tools/parity/ida.py dec  ee   "CGameEffectDamage::ApplyEffect(CGameSprite *)$"   ($ = exact name)
#   python tools/parity/ida.py dec  orig 4B245B 4B5DCF             decompile original functions by address (hex)
#   python tools/parity/ida.py xrefs orig 4B245B                   who calls these addresses
#   python tools/parity/ida.py vt   orig 8DE26C                    first 24 slots of a vtable (VT_SLOTS=N for more; ee: address = vtable+16)
#   python tools/parity/ida.py find ee   "HandleNamelessDeath"     search the function list (no IDA run)
#   python tools/parity/ida.py str  orig "Fortress_Death"          search strings -> referencing functions (no IDA run)
#   python tools/parity/ida.py show orig 4B245B                    print an already decompiled function
#
# Output: .re/<ee|orig>/dump/dec/<name>.c ; the path is printed. Only one IDA run at a time per database
# (the .i64 is locked while open): never run two `dec` commands in parallel on the same game.
import os, re, subprocess, sys

WORK = os.environ.get("PARITY_WORK", r"D:\gemrb\.re")
IDAT = os.environ.get("IDAT", r"C:\Program Files\IDA Professional 9.1\idat.exe")
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
DB = {"ee": os.path.join(WORK, "ee", "Torment64.i64"), "orig": os.path.join(WORK, "orig", "Torment.exe.i64")}

def run(game, script, listfile, items):
	base = os.path.dirname(DB[game])
	open(os.path.join(base, listfile), "w").write("\n".join(items) + "\n")
	log = os.path.join(base, "ida_run.log")
	r = subprocess.run([IDAT, "-A", "-S%s/%s" % (HERE, script), "-L" + log, DB[game]])
	if r.returncode:
		print("idat failed (%d), see %s" % (r.returncode, log)); sys.exit(1)

def dec_dir(game): return os.path.join(WORK, game, "dump", "dec")

def main():
	if len(sys.argv) < 4 and sys.argv[1:2] != ["help"]:
		print(open(__file__).read().split("import os")[0]); return
	cmd, game, args = sys.argv[1], sys.argv[2], sys.argv[3:]
	if cmd == "dec":
		before = set(os.listdir(dec_dir(game))) if os.path.isdir(dec_dir(game)) else set()
		if game == "ee":
			run(game, "decomp.py", "decomp_list.txt", args)
		else:
			run(game, "decomp_ea.py", "decomp_ea.txt", [a.upper().replace("0X", "").replace("SUB_", "") for a in args])
		d = dec_dir(game)
		for f in sorted(os.listdir(d)):
			if game == "orig" and f[:-2] in [a.upper().replace("SUB_", "") for a in args]: print(os.path.join(d, f))
			elif game == "ee" and f.endswith(".c") and (f not in before or any(re.sub(r"[^A-Za-z0-9_]+", "_", a.rstrip("$"))[:40] in f for a in args)):
				print(os.path.join(d, f))
		errs = [f for f in os.listdir(d) if f.endswith(".err")]
		if errs: print("decompile errors:", errs)
	elif cmd == "xrefs":
		run(game, "xrefs.py", "xref_ea.txt", [a.upper().replace("SUB_", "") for a in args])
		print(open(os.path.join(WORK, game, "dump", "xrefs.txt")).read())
	elif cmd == "vt":
		run(game, "vt.py", "vt_ea.txt", [a.upper() for a in args])
		print(open(os.path.join(WORK, game, "dump", "vt.txt")).read())
	elif cmd == "find":
		pat = re.compile(" ".join(args), re.I)
		for l in open(os.path.join(WORK, game, "dump", "funcs.txt"), encoding="utf-8", errors="replace"):
			if pat.search(l): print(l.rstrip())
	elif cmd == "str":
		pat = re.compile(" ".join(args), re.I)
		f = os.path.join(WORK, game, "dump", "strings.txt")
		if not os.path.exists(f): sys.exit("no strings dump for %s (run dump.py on it first)" % game)
		for l in open(f, encoding="utf-8", errors="replace"):
			if pat.search(l): print(l.rstrip())
	elif cmd == "show":
		for a in args:
			p = os.path.join(dec_dir(game), a.upper().replace("SUB_", "") + ".c") if game == "orig" else None
			if not p or not os.path.exists(p):
				cands = [f for f in os.listdir(dec_dir(game)) if a.lower() in f.lower()]
				p = os.path.join(dec_dir(game), cands[0]) if cands else None
			print(open(p, encoding="utf-8").read() if p else "(not decompiled yet: run dec first)")
	else:
		print("unknown command", cmd)

if __name__ == "__main__":
	main()
