"""Phase 2: build drop-in hi-res twins from EE art for classic layouts.

    python twins.py [--out C:\\Games\\GemRB] [--only spells,worldmap,areas,bams] [--ee PATH] [--classic PATH]

Rule for every twin: equal frame count, each frame's aspect within 1.5% of the classic frame,
Lanczos resize to exactly classic_size * n with n = max(2, round(ee_w / classic_w)). Anything that
fails is skipped and logged, never padded or cropped. Written paths go to
<out>/upscaled/ee_twins.txt so upscale.py never overwrites them.
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "upscale"))

import extract  # noqa: E402
import ie_formats  # noqa: E402
from decode import PageCache, bam_v2, bam_v2_sizes, mos_v1, mos_v2, mos_version  # noqa: E402
from ee_data import DEFAULT_EE, EEData, inflate  # noqa: E402

CLASSIC = Path(r"C:\Program Files (x86)\Black Isle\Torment")
TOL = 0.015

REMADES = ["IVSLOT", "CGPLUS", "CGMINUS", "CGCANCEL", "CGSCRL1", "STALIGN", "STFCTION",
           "WMLOCAT", "WMPICKL", "WMTIME", "WMCHRH", "FILLBAR"]
# The remakes are not all named in the plan; the report lists whatever the rule accepts. Names
# that exist in both games as BAM are collected automatically for "bams".


class Twins:
    def __init__(self, out: Path, ee: EEData, classic: ie_formats.ResourceIndex):
        self.out = out / "upscaled"
        self.ee = ee
        self.classic = classic
        self.pages = PageCache(ee)
        self.written: list[str] = []
        self.log: list[str] = []

    # -- helpers --------------------------------------------------------------------------
    def note(self, msg: str) -> None:
        self.log.append(msg)
        print(msg)

    def save(self, rel: str, arr: np.ndarray) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(arr).save(path)
        self.written.append(rel.replace("\\", "/"))

    @staticmethod
    def fit(arr: np.ndarray, w: int, h: int) -> np.ndarray:
        img = Image.fromarray(arr)
        if img.size == (w, h):
            return arr
        # premultiply so transparent texels do not bleed colour into the edges
        a = np.asarray(img).astype(np.float32)
        a[..., :3] *= a[..., 3:4] / 255.0
        parts = [Image.fromarray(a[..., c], "F").resize((w, h), Image.LANCZOS) for c in range(4)]
        out = np.stack([np.asarray(p) for p in parts], axis=-1)
        alpha = np.clip(out[..., 3:4], 0, 255)
        rgb = np.where(alpha > 0, out[..., :3] * 255.0 / np.maximum(alpha, 1e-3), 0)
        return np.concatenate([np.clip(rgb, 0, 255), alpha], axis=-1).round().astype(np.uint8)

    @staticmethod
    def aspect_ok(cw: int, ch: int, ew: int, eh: int) -> bool:
        return abs((ew / eh) / (cw / ch) - 1.0) <= TOL

    def classic_bam_frames(self, name: str):
        """(w, h, cx, cy) per classic V1 frame."""
        data = self.classic.get(name, "bam")
        if data[:8] == b"BAMCV1  ":
            data = zlib.decompress(data[12:])
        n = struct.unpack_from("<H", data, 8)[0]
        off = struct.unpack_from("<I", data, 0x0C)[0]
        return [struct.unpack_from("<2H2h", data, off + i * 12) for i in range(n)]

    # -- BAM ------------------------------------------------------------------------------
    def bam_twin(self, name: str, fixed_n: int | None = None) -> bool:
        if not self.classic.has(name, "bam"):
            self.note(f"bam {name}: not in classic")
            return False
        if not self.ee.has(name, "bam"):
            self.note(f"bam {name}: not in EE")
            return False
        eb = self.ee.read(name, "bam")
        if inflate(eb)[:8] != b"BAM V2  ":
            self.note(f"bam {name}: EE copy is not V2")
            return False
        cframes = self.classic_bam_frames(name)
        esizes = bam_v2_sizes(eb)
        if len(cframes) != len(esizes):
            self.note(f"bam {name}: SKIP frame count classic {len(cframes)} vs EE {len(esizes)}")
            return False
        for i, ((cw, ch, _x, _y), (ew, eh)) in enumerate(zip(cframes, esizes)):
            if cw == 0 or ch == 0:
                continue
            if ew == 0 or eh == 0 or not self.aspect_ok(cw, ch, ew, eh):
                self.note(f"bam {name}: SKIP frame {i} aspect classic {cw}x{ch} vs EE {ew}x{eh}")
                return False
        bam = bam_v2(eb, self.pages)
        count = 0
        staged = []
        for i, ((cw, ch, cx, cy), f) in enumerate(zip(cframes, bam.frames)):
            if cw == 0 or ch == 0:
                continue
            ew = f.image.shape[1]
            n = fixed_n or max(2, round(ew / cw))
            staged.append((i, self.fit(f.image, cw * n, ch * n)))
            ecx, ecy = f.cx / (ew / cw), f.cy / (f.image.shape[0] / ch)
            if abs(ecx - cx) > 2 or abs(ecy - cy) > 2:
                self.note(f"bam {name}: frame {i} centre classic ({cx},{cy}) vs EE scaled "
                          f"({ecx:.1f},{ecy:.1f}) (kept classic)")
        for i, arr in staged:
            self.save(f"gui/bam/{name}/{i}.png", arr)
            count += 1
        self.note(f"bam {name}: {count} frames written")
        return True

    def spells(self):
        names = [n for n in self.ee.names("bam") if n.startswith("SP") and len(n) == 5 and n[2:].isdigit()]
        ok = 0
        for n in names:
            ok += self.bam_twin(n, fixed_n=8)
        self.note(f"spells: {ok}/{len(names)} twins")

    def bams(self):
        both = [n for n in REMADES if self.ee.has(n, "bam") and self.classic.has(n, "bam")]
        ok = 0
        for n in both:
            ok += self.bam_twin(n)
        self.note(f"remade bams: {ok}/{len(both)} accepted: "
                  f"{[n for n in both if any(w.startswith(f'gui/bam/{n}/') for w in self.written)]}")

    # -- MOS ------------------------------------------------------------------------------
    def ee_mos(self, name: str) -> np.ndarray:
        blob = self.ee.read(name, "mos")
        return mos_v2(blob, self.pages) if mos_version(blob) == "MOS V2" else mos_v1(blob)

    def mos_twin(self, name: str, *, ee_name: str | None = None) -> bool:
        ee_name = ee_name or name
        if not (self.classic.has(name, "mos") and self.ee.has(ee_name, "mos")):
            return False
        c = extract.decode_mos(self.classic.get(name, "mos"))
        ch, cw = c.shape[:2]
        e = self.ee_mos(ee_name)
        eh, ew = e.shape[:2]
        if ew <= cw or eh <= ch:
            return False
        if not self.aspect_ok(cw, ch, ew, eh):
            self.note(f"mos {name}: SKIP aspect classic {cw}x{ch} vs EE {ew}x{eh}")
            return False
        n = max(2, round(ew / cw))
        self.save(f"gui/mos/{name}.png", self.fit(e, cw * n, ch * n))
        self.note(f"mos {name}: {cw}x{ch} -> {cw * n}x{ch * n} (EE {ew}x{eh})")
        return True

    def worldmap(self):
        self.mos_twin("WMWRLDB")

    def areas(self):
        names = [n for n in self.classic.names("mos") if n.startswith("AR") and self.ee.has(n, "mos")]
        ok = sum(self.mos_twin(n) for n in names)
        self.note(f"area maps: {ok}/{len(names)} twins")

    def bestiary(self):
        """2g: JR*KN pictures. EE MOS V2 1124x1764 -> classic size x4, alpha from the classic BMP."""
        ini = self.classic.game / "beast.ini"
        names = ["DEFAULT"]
        for line in ini.read_text(encoding="latin1").splitlines():
            line = line.split("//")[0].strip()
            if line.lower().startswith("imageknown="):
                n = line.split("=", 1)[1].strip().upper()
                if n and n not in names:
                    names.append(n)
        ok = 0
        for n in names:
            if not self.ee.has(n, "mos"):
                self.note(f"beast {n}: no EE picture (keeps its ESRGAN twin)")
                continue
            if not self.classic.has(n, "bmp"):
                self.note(f"beast {n}: not in classic")
                continue
            c = extract.decode_bmp(self.classic.get(n, "bmp"))
            ch, cw = c.shape[:2]
            e = self.ee_mos(n)
            if e.shape[1] != cw * 4 or abs(e.shape[0] - ch * 4) > 4:
                self.note(f"beast {n}: SKIP EE {e.shape[1]}x{e.shape[0]} is not 4x classic {cw}x{ch}")
                continue
            rgb = self.fit(e, cw * 4, ch * 4)
            alpha = np.repeat(np.repeat(c[..., 3], 4, axis=0), 4, axis=1)
            rgb[..., 3] = alpha
            rgb[alpha == 0, :3] = 0
            self.save(f"gui/bmp/{n}.png", rgb)
            ok += 1
        self.note(f"bestiary: {ok}/{len(names)} twins")

    def finish(self):
        lst = self.out / "ee_twins.txt"
        have = set()
        if lst.is_file():
            have = {l.strip() for l in lst.read_text().splitlines() if l.strip()}
        have |= set(self.written)
        lst.write_text("\n".join(sorted(have)) + "\n")
        (self.out / "ee_twins.log").write_text("\n".join(self.log) + "\n")
        print(f"{len(self.written)} files written, {len(have)} listed in {lst}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Games\GemRB")
    ap.add_argument("--ee", default=str(DEFAULT_EE))
    ap.add_argument("--classic", default=str(CLASSIC))
    ap.add_argument("--only", default="spells,worldmap,areas,bams")
    a = ap.parse_args()
    ee = EEData(Path(a.ee))
    classic = ie_formats.ResourceIndex(Path(a.classic), HERE.parent / "upscale" / "work" / "classic-cache")
    t = Twins(Path(a.out), ee, classic)
    for step in a.only.split(","):
        getattr(t, step.strip())()
    t.finish()


if __name__ == "__main__":
    main()
