"""Read static data from the PST:EE ELF binary (.re/ee/Torment64) by symbol name or address.

  python tools/parity/eeconst.py CGameSprite::INVISIBILITY_MOD CGameSprite::ATTACK_DICE
  python tools/parity/eeconst.py "CGameSprite::*RANGE*"      (glob over names.txt)
  python tools/parity/eeconst.py 0xECE9BC --size 4
  python tools/parity/eeconst.py 0xED4DA0 --strptr 10   (an array of char* : print each string, stop at NULL)

Prints address, then the bytes as signed int8/int16/int32 (the width of a static is not known: take the one
the code uses, e.g. `(unsigned __int8)CGameSprite::GRID...` or a `_WORD` read).
"""
import fnmatch, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / ".re" / "ee"


class Elf:
    def __init__(self, path):
        d = self.d = path.read_bytes()
        shoff, = struct.unpack_from("<Q", d, 0x28)
        shentsize, shnum = struct.unpack_from("<HH", d, 0x3A)
        self.secs = []
        for i in range(shnum):
            _, typ, _, addr, off, size = struct.unpack_from("<IIQQQQ", d, shoff + i * shentsize)
            if addr:
                self.secs.append((addr, size, off, typ))

    def read(self, va, n):
        for addr, size, off, typ in self.secs:
            if addr <= va < addr + size:
                if typ == 8:  # NOBITS (.bss): zero at start
                    return b"\0" * n
                return self.d[off + va - addr: off + va - addr + n]
        return None


def names():
    out = {}
    for line in (ROOT / "dump" / "names.txt").read_text(errors="replace").splitlines():
        p = line.split("\t")
        if len(p) >= 3:
            out[p[2]] = int(p[0], 16)
    return out


def main(argv):
    size = 4
    if "--size" in argv:
        i = argv.index("--size"); size = int(argv[i + 1]); del argv[i:i + 2]
    strptr = 0
    if "--strptr" in argv:
        i = argv.index("--strptr"); strptr = int(argv[i + 1]); del argv[i:i + 2]
    elf = Elf(ROOT / "Torment64")
    if strptr:
        for a in argv:
            base = int(a, 16) if a.lower().startswith("0x") else names().get(a)
            for k in range(strptr):
                ptr, = struct.unpack_from("<Q", elf.read(base + 8 * k, 8))
                if not ptr:
                    break
                raw = elf.read(ptr, 256) or b""
                print(f"[{k}] {base + 8 * k:08X} -> {ptr:08X} {raw.split(bytes(1))[0].decode('latin1')!r}")
        return
    nm = None
    for a in argv:
        if a.lower().startswith("0x"):
            targets = [(a, int(a, 16))]
        else:
            nm = nm or names()
            targets = [(k, v) for k, v in nm.items() if fnmatch.fnmatchcase(k, a)] if any(c in a for c in "*?[") \
                else [(a, nm.get(a))]
        for name, va in sorted(targets, key=lambda t: t[1] or 0):
            if va is None:
                print(f"{name}: not in names.txt"); continue
            b = elf.read(va, max(size, 4))
            if b is None:
                print(f"{va:08X} {name}: not mapped"); continue
            print(f"{va:08X} {name}: i8={struct.unpack_from('<b', b)[0]} i16={struct.unpack_from('<h', b)[0]} "
                  f"i32={struct.unpack_from('<i', b)[0]} bytes={b[:size].hex()}")


if __name__ == "__main__":
    main(sys.argv[1:])
