"""MOS V2 / BAM V2 (PVRZ-backed) and MOS V1 decoding to RGBA arrays."""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from ee_data import EEData, inflate
from pvrz import decode_pvrz


class PageCache:
    def __init__(self, ee: EEData):
        self.ee = ee
        self.pages: dict[int, np.ndarray] = {}

    def get(self, page: int) -> np.ndarray:
        if page not in self.pages:
            self.pages[page] = decode_pvrz(self.ee.read(f"MOS{page:04d}", "pvrz"))
        return self.pages[page]


def _paste(canvas, page, sx, sy, w, h, dx, dy):
    ch, cw = canvas.shape[:2]
    w = min(w, cw - dx)
    h = min(h, ch - dy)
    if w > 0 and h > 0:
        canvas[dy:dy + h, dx:dx + w] = page[sy:sy + h, sx:sx + w]


def mos_version(blob: bytes) -> str:
    return inflate(blob)[:8].decode("latin1").strip()


def mos_v2(blob: bytes, pages: PageCache) -> np.ndarray:
    raw = inflate(blob)
    if raw[:8] != b"MOS V2  ":
        raise ValueError("not MOS V2")
    w, h, n, off = struct.unpack_from("<4I", raw, 8)
    canvas = np.zeros((h, w, 4), np.uint8)
    for i in range(n):
        page, sx, sy, bw, bh, dx, dy = struct.unpack_from("<7I", raw, off + i * 28)
        _paste(canvas, pages.get(page), sx, sy, bw, bh, dx, dy)
    return canvas


def mos_v1(blob: bytes) -> np.ndarray:
    """MOS V1 (palettised tiles) to RGBA; the green key colour becomes transparent."""
    raw = inflate(blob)
    if raw[:8] != b"MOS V1  ":
        raise ValueError("not MOS V1")
    w, h, cols, rows, bsize, poff = struct.unpack_from("<2H2HII", raw, 8)
    n = cols * rows
    canvas = np.zeros((h, w, 4), np.uint8)
    offs = struct.unpack_from(f"<{n}I", raw, poff + n * 1024)
    data0 = poff + n * 1024 + n * 4
    for r in range(rows):
        for c in range(cols):
            t = r * cols + c
            pal = np.frombuffer(raw, np.uint8, 1024, poff + t * 1024).reshape(256, 4)
            tw = min(bsize, w - c * bsize)
            th = min(bsize, h - r * bsize)
            idx = np.frombuffer(raw, np.uint8, tw * th, data0 + offs[t]).reshape(th, tw)
            rgba = np.empty((th, tw, 4), np.uint8)
            rgba[..., 0] = pal[idx, 2]
            rgba[..., 1] = pal[idx, 1]
            rgba[..., 2] = pal[idx, 0]
            key = (pal[idx, 0] == 0) & (pal[idx, 1] == 255) & (pal[idx, 2] == 0)
            rgba[..., 3] = np.where(key, 0, 255)
            canvas[r * bsize:r * bsize + th, c * bsize:c * bsize + tw] = rgba
    return canvas


@dataclass
class BamFrame:
    image: np.ndarray  # (h, w, 4)
    cx: int
    cy: int


@dataclass
class Bam:
    frames: list
    cycles: list  # (frame count, first index into the frame lookup)
    lookup: list  # frame lookup table (V2: identity)


def bam_v2(blob: bytes, pages: PageCache) -> Bam:
    raw = inflate(blob)
    if raw[:8] != b"BAM V2  ":
        raise ValueError("not BAM V2")
    nf, nc, nb, foff, coff, boff = struct.unpack_from("<6I", raw, 8)
    frames = []
    for i in range(nf):
        w, h, cx, cy, start, count = struct.unpack_from("<2H2h2H", raw, foff + i * 12)
        canvas = np.zeros((h, w, 4), np.uint8)
        for b in range(start, start + count):
            page, sx, sy, bw, bh, dx, dy = struct.unpack_from("<7I", raw, boff + b * 28)
            _paste(canvas, pages.get(page), sx, sy, bw, bh, dx, dy)
        frames.append(BamFrame(canvas, cx, cy))
    cycles = [struct.unpack_from("<2H", raw, coff + i * 4) for i in range(nc)]
    return Bam(frames, cycles, list(range(nf)))


def bam_v2_sizes(blob: bytes) -> list:
    raw = inflate(blob)
    nf = struct.unpack_from("<I", raw, 8)[0]
    foff = struct.unpack_from("<I", raw, 20)[0]
    return [struct.unpack_from("<2H", raw, foff + i * 12) for i in range(nf)]
