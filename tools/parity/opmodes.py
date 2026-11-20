"""Count how PST data uses opcodes: p2 (mode) values, timing modes, p1 range, files.

Reads every feature block of every SPL and ITM GemRB loads (header, equipped AND SPL casting effects: the whole
feature table, unlike opuses.py).

  python tools/parity/opmodes.py 33 34 35 36 37        one line per opcode: uses, p2 values, timings, p1 min..max
  python tools/parity/opmodes.py 44 --files            also list the files per p2 value
"""
import collections, struct, sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import pstres


def blocks():
    g = pstres.gemrb()
    for ext in ("spl", "itm"):
        for n in g.names(ext):
            d = g.res(n, ext)
            if not d or len(d) < 0x72:
                continue
            fo, = struct.unpack_from("<I", d, 0x6A)
            o = fo
            while o + 48 <= len(d):
                op, = struct.unpack_from("<H", d, o)
                p1, p2 = struct.unpack_from("<iI", d, o + 4)
                dur, = struct.unpack_from("<I", d, o + 14)
                yield n, ext, op, d[o + 2], p1, p2, d[o + 12], dur, d[o + 18], d[o + 19]
                o += 48


def main(argv):
    files = "--files" in argv
    ops = {int(a) for a in argv if a.isdigit()}
    stats = collections.defaultdict(lambda: {"n": 0, "p2": collections.Counter(), "t": collections.Counter(),
                                             "p1": [], "f": collections.defaultdict(set)})
    for n, ext, op, tgt, p1, p2, t, dur, pr1, pr2 in blocks():
        if op not in ops:
            continue
        s = stats[op]; s["n"] += 1; s["p2"][p2] += 1; s["t"][t] += 1; s["p1"].append(p1); s["f"][p2].add(n)
    for op in sorted(ops):
        s = stats.get(op)
        if not s:
            print(f"{op}: no uses"); continue
        p2 = " ".join(f"{k}x{v}" for k, v in sorted(s["p2"].items()))
        t = " ".join(f"{k}x{v}" for k, v in sorted(s["t"].items()))
        print(f"{op}: {s['n']} uses; p2 {p2}; timing {t}; p1 {min(s['p1'])}..{max(s['p1'])}")
        if files:
            for k in sorted(s["f"]):
                print(f"   p2={k}: {' '.join(sorted(s['f'][k]))}")


if __name__ == "__main__":
    main(sys.argv[1:])
