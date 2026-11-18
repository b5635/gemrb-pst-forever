"""Decode one EE MOS/BAM to PNG: python dump.py NAME [outdir]"""
import sys
from pathlib import Path

from PIL import Image

from decode import PageCache, bam_v2, mos_v1, mos_v2, mos_version
from ee_data import EEData


def main():
    name = sys.argv[1].upper()
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "dump")
    out.mkdir(parents=True, exist_ok=True)
    ee = EEData()
    pages = PageCache(ee)
    if ee.has(name, "mos"):
        blob = ee.read(name, "mos")
        v = mos_version(blob)
        arr = mos_v2(blob, pages) if v == "MOS V2" else mos_v1(blob)
        Image.fromarray(arr).save(out / f"{name}.png")
        print(name, v, arr.shape[1], arr.shape[0])
    if ee.has(name, "bam"):
        bam = bam_v2(ee.read(name, "bam"), pages)
        for i, f in enumerate(bam.frames[:8]):
            Image.fromarray(f.image).save(out / f"{name}_{i}.png")
        print(name, "bam", len(bam.frames), "frames", len(bam.cycles), "cycles",
              [f.image.shape[1::-1] for f in bam.frames[:3]])


if __name__ == "__main__":
    main()
