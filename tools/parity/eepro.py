# PST:EE .pro vs GemRB .pro by projectile number (EE projectl.ids id = SPL/ITM field - 1; GemRB name from maps/projectiles.tsv)
# usage: python tools/parity/eepro.py
import sys, struct, re
sys.path.insert(0, r"D:\gemrb\tools\parity")
import pstres
e = pstres.ee(); g = pstres.gemrb()

def ids(t):
    m = {}
    for l in pstres.text(t).splitlines()[1:]:
        mm = re.match(r"\s*(\d+)\s+(\S+)", l)
        if mm and mm.group(2) != "--":
            m[int(mm.group(1))] = mm.group(2).upper()
    return m

eid = ids(e.res("projectl", "ids"))
gid = {}
for l in open(r"D:\gemrb\dev\parity\maps\projectiles.tsv", encoding="utf-8"):
    c = l.rstrip("\n").split("\t")
    if c[0].isdigit() and len(c) > 1 and c[1]:
        gid[int(c[0]) - 1] = c[1].upper()

F = [(0x08, "H", "type"), (0x0A, "H", "speed"), (0x0C, "I", "spark"), (0x2C, "I", "flags"),
     (0x200, "I", "aoeflags"), (0x204, "H", "trigger"), (0x206, "H", "radius"), (0x210, "H", "freq"), (0x214, "H", "expl")]
for num, en in sorted(eid.items()):
    a = e.res(en, "pro"); gn = gid.get(num); b = g.res(gn, "pro") if gn else None
    if not a:
        continue
    if not b:
        print(num, en, "-> GemRB", gn, "missing"); continue
    d = []
    for o, f, nm in F:
        if o + 4 > len(a) or o + 4 > len(b):
            continue
        va = struct.unpack_from("<" + f, a, o)[0]; vb = struct.unpack_from("<" + f, b, o)[0]
        if va != vb:
            d.append(f"{nm}: gemrb {vb:#x} ee {va:#x}")
    print(num, en, "/", gn, f"(len ee {len(a)} gemrb {len(b)})", "; ".join(d) if d else "same")
