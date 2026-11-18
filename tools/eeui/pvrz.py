"""PVRZ (zlib + PVR3) DXT1/DXT5 decoder, vectorised with numpy."""
from __future__ import annotations

import struct
import zlib

import numpy as np


def _rgb565(c: np.ndarray) -> np.ndarray:
    r = ((c >> 11) & 31).astype(np.int32)
    g = ((c >> 5) & 63).astype(np.int32)
    b = (c & 31).astype(np.int32)
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=-1)


def _color_blocks(blk: np.ndarray, dxt1: bool):
    """blk (N,8) uint8 -> rgb (N,16,3) uint8, transparent (N,16) bool (DXT1 punch-through)."""
    c0 = blk[:, 0].astype(np.uint16) | (blk[:, 1].astype(np.uint16) << 8)
    c1 = blk[:, 2].astype(np.uint16) | (blk[:, 3].astype(np.uint16) << 8)
    bits = (blk[:, 4].astype(np.uint32) | (blk[:, 5].astype(np.uint32) << 8)
            | (blk[:, 6].astype(np.uint32) << 16) | (blk[:, 7].astype(np.uint32) << 24))
    p0 = _rgb565(c0)
    p1 = _rgb565(c1)
    pal = np.zeros((len(blk), 4, 3), np.int32)
    pal[:, 0] = p0
    pal[:, 1] = p1
    four = (c0 > c1) | (not dxt1)
    f = four[:, None]
    pal[:, 2] = np.where(f, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3] = np.where(f, (p0 + 2 * p1) // 3, 0)
    shifts = (np.arange(16, dtype=np.uint32) * 2)[None, :]
    idx = ((bits[:, None] >> shifts) & 3).astype(np.int64)
    rgb = np.take_along_axis(pal, idx[:, :, None].repeat(3, axis=2), axis=1)
    return rgb.astype(np.uint8), (~four)[:, None] & (idx == 3)


def _alpha_blocks(blk: np.ndarray) -> np.ndarray:
    """blk (N,8) DXT5 alpha part -> (N,16) uint8."""
    a0 = blk[:, 0].astype(np.int32)
    a1 = blk[:, 1].astype(np.int32)
    bits = np.zeros(len(blk), np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    gt = a0 > a1
    pal = np.zeros((len(blk), 8), np.int32)
    pal[:, 0] = a0
    pal[:, 1] = a1
    for k in range(1, 7):
        seven = ((7 - k) * a0 + k * a1) // 7
        five = ((6 - k) * a0 + (k - 1) * a1) // 5 if k <= 5 else np.zeros_like(a0)
        pal[:, 1 + k] = np.where(gt, seven, five)
    pal[:, 6] = np.where(gt, pal[:, 6], 0)
    pal[:, 7] = np.where(gt, pal[:, 7], 255)
    shifts = (np.arange(16, dtype=np.uint64) * np.uint64(3))[None, :]
    idx = ((bits[:, None] >> shifts) & np.uint64(7)).astype(np.int64)
    return np.take_along_axis(pal, idx, axis=1).astype(np.uint8)


def decode_pvrz(blob: bytes) -> np.ndarray:
    """Return an (h, w, 4) uint8 RGBA array."""
    raw = blob
    if raw[:4] != b"PVR\x03":
        start = raw.find(b"\x78\x9c")
        if start < 0:
            start = raw.find(b"\x78\xda")
        if start < 0:
            raise ValueError("pvrz: no zlib stream")
        raw = zlib.decompress(raw[start:])
    if raw[:4] != b"PVR\x03":
        raise ValueError(f"pvrz: bad signature {raw[:4]!r}")
    fmt = struct.unpack_from("<Q", raw, 8)[0] & 0xFFFFFFFF
    h, w = struct.unpack_from("<2I", raw, 24)
    meta = struct.unpack_from("<I", raw, 48)[0]
    data = raw[52 + meta:]
    if fmt not in (7, 11):
        raise ValueError(f"pvrz: unsupported format {fmt}")
    bs = 8 if fmt == 7 else 16
    bw, bh = (w + 3) // 4, (h + 3) // 4
    arr = np.frombuffer(data, np.uint8, count=bw * bh * bs).reshape(-1, bs)
    if fmt == 7:
        rgb, tr = _color_blocks(arr, True)
        alpha = np.where(tr, 0, 255).astype(np.uint8)
    else:
        alpha = _alpha_blocks(arr[:, :8])
        rgb, _ = _color_blocks(arr[:, 8:], False)
    px = np.concatenate([rgb, alpha[:, :, None]], axis=2)
    px = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return px[:h, :w].copy()
