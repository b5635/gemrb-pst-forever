"""Read the original Torment.exe directly (no IDA): vtable slots and pointer searches.

  python tools/parity/exevt.py slots 8F0788 [N]      N dword slots from a VA (default 64), with function names
  python tools/parity/exevt.py refs 76A7EA            every place the exe stores this 32-bit value (data xrefs)
"""
import struct, sys, os
ROOT = os.path.join(os.path.dirname(__file__), "..", "..", ".re", "orig")
d = open(os.path.join(ROOT, "Torment.exe"), "rb").read()
pe = struct.unpack_from("<I", d, 0x3C)[0]
ns = struct.unpack_from("<H", d, pe + 6)[0]; opt = struct.unpack_from("<H", d, pe + 20)[0]
base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
secs = []
o = pe + 24 + opt
for i in range(ns):
	vs, va, rs, ra = struct.unpack_from("<IIII", d, o + 8); secs.append((va, ra, rs)); o += 40
def to_va(off):
	for v, r, s in secs:
		if r <= off < r + s: return base + v + off - r
def to_off(a):
	for v, r, s in secs:
		if base + v <= a < base + v + s: return a - base - v + r
funcs = set()
fl = os.path.join(ROOT, "dump", "dec_all")
if os.path.isdir(fl): funcs = {f[:-2].upper() for f in os.listdir(fl) if f.endswith(".c")}
cmd, a = sys.argv[1], int(sys.argv[2], 16)
if cmd == "slots":
	n = int(sys.argv[3]) if len(sys.argv) > 3 else 64
	for i in range(n):
		v = struct.unpack_from("<I", d, to_off(a + 4 * i))[0]
		h = "%X" % v
		print("%3d +%-4d %X  %s" % (i, 4 * i, a + 4 * i, ("sub_" + h) if h in funcs else h))
elif cmd == "refs":
	b = struct.pack("<I", a); i = d.find(b)
	while i != -1:
		print("%X" % to_va(i)); i = d.find(b, i + 1)
