"""Decode BAM, MOS, TIS and BMP resources to straight RGBA.

Area tiles are not upscaled one by one. Overlay 0 is stitched, and every other
tile index is upscaled inside a 3x3 neighbourhood so the cut tiles share edges.
"""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
from PIL import Image

from ie_formats import resref

TILE = 64
GREEN_LOOSE = True  # match TISImporter: near-green is the colour key


def _decompress_container(data: bytes, signature: bytes) -> bytes:
    if data[:8] != signature:
        return data
    return zlib.decompress(data[12:])


def _bam_indices(data: bytes, keep_small: bool) -> tuple[list[np.ndarray | None], np.ndarray, int]:
    """Frame-table index images plus the BGRA-swapped palette. Index 0 is not remapped."""
    data = _decompress_container(data, b"BAMCV1  ")
    if data[:8] != b"BAM V1  ":
        raise ValueError("not a BAM V1")
    frame_count = struct.unpack_from("<H", data, 8)[0]
    color_key = int(data[0x0B])
    frames_off = struct.unpack_from("<I", data, 0x0C)[0]
    palette_off = struct.unpack_from("<I", data, 0x10)[0]
    if palette_off + 1024 > len(data):
        raise ValueError("BAM palette is truncated")
    pal = np.frombuffer(data[palette_off : palette_off + 1024], dtype=np.uint8).reshape(256, 4).copy()
    pal = pal[:, [2, 1, 0, 3]]

    frames: list[np.ndarray | None] = []
    for i in range(frame_count):
        entry = frames_off + i * 12
        if entry + 12 > len(data):
            frames.append(None)
            continue
        w, h = struct.unpack_from("<2H", data, entry)
        word = struct.unpack_from("<I", data, entry + 8)[0]
        rle = (word & 0x80000000) == 0
        offset = word & 0x7FFFFFFF
        if w == 0 or h == 0 or (not keep_small and (w < 8 or h < 8)):
            frames.append(None)
            continue
        if offset >= len(data):
            frames.append(None)
            continue
        src = data[offset:]
        try:
            if rle:
                indices = _decode_rle(src, w, h, color_key)
            else:
                need = w * h
                if len(src) < need:
                    frames.append(None)
                    continue
                indices = np.frombuffer(src[:need], dtype=np.uint8).reshape(h, w).copy()
        except Exception:
            frames.append(None)
            continue
        frames.append(indices)
    return frames, pal, color_key


def decode_bam(data: bytes) -> list[np.ndarray | None]:
    """One RGBA array per frame table entry. Empty and failed frames are None."""
    frames, pal, color_key = _bam_indices(data, keep_small=False)
    pal = pal.copy()
    pal[:, 3] = np.where(pal[:, 3] == 0, 255, pal[:, 3])
    if color_key != 1:
        pal[1] = (0, 0, 0, 128)
    pal[color_key] = (0, 0, 0, 0)
    return [None if indices is None else pal[indices] for indices in frames]


def decode_font(data: bytes) -> tuple[list[np.ndarray | None], list[np.ndarray | None], np.ndarray, int]:
    """Font glyphs as RGBA, plus the index image and RGB palette.

    Glyphs thinner than 8px are kept. Index 1 is ink, not a shadow. The colour
    key stays transparent and every other index keeps the palette grey.
    The index image is what gets scaled; the photo model is not used on fonts.
    """
    frames, pal, color_key = _bam_indices(data, keep_small=True)
    rgb = pal[:, :3].copy()
    images: list[np.ndarray | None] = []
    for indices in frames:
        if indices is None:
            images.append(None)
            continue
        pix = rgb[indices]
        alpha = np.where(indices == color_key, 0, 255).astype(np.uint8)
        images.append(np.dstack((pix, alpha)))
    return images, frames, rgb, color_key


def _scale2x_indices(indices: np.ndarray, color_key: int) -> np.ndarray:
    """AdvMAME2x on palette indices.

    A corner takes a neighbour only when the two adjacent neighbours are the
    same index. A transparent pixel stays transparent, so a one-pixel counter
    is not filled in. Stroke width stays the source width.
    """
    src = np.pad(indices, 1, mode="constant", constant_values=np.uint8(color_key))
    center = src[1:-1, 1:-1]
    up = src[:-2, 1:-1]
    left = src[1:-1, :-2]
    right = src[1:-1, 2:]
    down = src[2:, 1:-1]
    # never paint into an empty pixel; only chamfer corners of the ink
    rule = (center != color_key) & (up != down) & (left != right)
    e0 = np.where(rule & (left == up), left, center)
    e1 = np.where(rule & (up == right), right, center)
    e2 = np.where(rule & (left == down), left, center)
    e3 = np.where(rule & (down == right), right, center)
    out = np.empty((center.shape[0] * 2, center.shape[1] * 2), dtype=np.uint8)
    out[0::2, 0::2] = e0
    out[0::2, 1::2] = e1
    out[1::2, 0::2] = e2
    out[1::2, 1::2] = e3
    return out


def scale_font_indices(indices: np.ndarray, color_key: int, scale: int) -> np.ndarray:
    """Integer scale of one glyph. Powers of two use Scale2x; other factors nearest."""
    scale = int(scale)
    if scale < 2:
        return np.ascontiguousarray(indices)
    out = np.ascontiguousarray(indices)
    done = 1
    while done * 2 <= scale:
        out = _scale2x_indices(out, color_key)
        done *= 2
    factor = scale // done
    if factor > 1:
        out = np.repeat(np.repeat(out, factor, axis=0), factor, axis=1)
        done *= factor
    if done != scale:
        return np.repeat(np.repeat(np.ascontiguousarray(indices), scale, axis=0), scale, axis=1)
    return np.ascontiguousarray(out)


def _decode_rle(data: bytes, w: int, h: int, color_key: int) -> np.ndarray:
    count = w * h
    out = np.empty(count, dtype=np.uint8)
    i = 0
    p = 0
    limit = len(data)
    while i < count:
        if p >= limit:
            out[i:] = color_key
            break
        px = data[p]
        p += 1
        if px == color_key:
            if p >= limit:
                out[i:] = color_key
                break
            run = data[p] + 1
            p += 1
            run = min(run, count - i)
            out[i : i + run] = color_key
            i += run
        else:
            out[i] = px
            i += 1
    return out.reshape(h, w)


def decode_mos(data: bytes) -> np.ndarray:
    data = _decompress_container(data, b"MOSCV1  ")
    if data[:8] != b"MOS V1  ":
        raise ValueError("not a MOS V1")
    w, h, cols, rows, _block, pal_off = struct.unpack_from("<4H2I", data, 8)
    image = np.zeros((h, w, 4), dtype=np.uint8)
    header = rows * cols * 1024
    offsets = rows * cols * 4
    for y in range(rows):
        bh = _edge(h, y, rows)
        for x in range(cols):
            bw = _edge(w, x, cols)
            pal_at = pal_off + (y * cols + x) * 1024
            off_at = pal_off + header + (y * cols + x) * 4
            block_off = struct.unpack_from("<I", data, off_at)[0]
            pix_at = pal_off + header + offsets + block_off
            pal = np.frombuffer(data[pal_at : pal_at + 1024], dtype=np.uint8).reshape(256, 4).copy()
            pal = pal[:, [2, 1, 0, 3]]
            # engine colour key is the pixel 0x0000ff00: green with alpha 0, not every green
            file_a = pal[:, 3].copy()
            green = (pal[:, 0] == 0) & (pal[:, 1] == 255) & (pal[:, 2] == 0) & (file_a == 0)
            alpha = np.where(file_a == 0, 255, file_a)
            alpha = np.where(green, 0, alpha)
            pal[:, 3] = alpha
            pix = np.frombuffer(data[pix_at : pix_at + bw * bh], dtype=np.uint8)
            block = pal[pix].reshape(bh, bw, 4)
            y0, x0 = y * 64, x * 64
            image[y0 : y0 + bh, x0 : x0 + bw] = block
    return image


def _edge(full: int, index: int, count: int) -> int:
    if index < count - 1:
        return 64
    rem = full % 64
    return 64 if rem == 0 else rem


def decode_tis_tiles(data: bytes) -> np.ndarray:
    """Return `(count, 64, 64, 4)` RGBA. Near-green palette entries are transparent."""
    if data[:8] == b"TIS V1  ":
        section = struct.unpack_from("<I", data, 12)[0]
        shift = struct.unpack_from("<I", data, 16)[0]
        if section == 0x0C:
            raise ValueError("PVRZ tilesets are not upscaled")
        blob = data[shift:]
    else:
        blob = data
    count = len(blob) // 5120
    if count == 0:
        return np.zeros((0, 64, 64, 4), dtype=np.uint8)
    raw = np.frombuffer(blob[: count * 5120], dtype=np.uint8).reshape(count, 5120)
    pals = raw[:, :1024].reshape(count, 256, 4)[:, :, [2, 1, 0, 3]].copy()
    pals[:, :, 3] = np.where(pals[:, :, 3] == 0, 255, pals[:, :, 3])
    if GREEN_LOOSE:
        green = (pals[:, :, 0] <= 4) & (pals[:, :, 2] <= 4) & (pals[:, :, 1] >= 78)
    else:
        green = (pals[:, :, 0] == 0) & (pals[:, :, 1] == 255) & (pals[:, :, 2] == 0)
    pals[green] = (0, 255, 0, 0)
    pix = raw[:, 1024:]
    out = pals[np.arange(count)[:, None], pix]
    return out.reshape(count, 64, 64, 4)


def decode_bmp(data: bytes) -> np.ndarray:
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    arr = np.array(image, dtype=np.uint8)
    green = (arr[:, :, 0] == 0) & (arr[:, :, 1] == 255) & (arr[:, :, 2] == 0)
    arr[green, 3] = 0
    return arr


def read_wed(data: bytes) -> list[dict]:
    if data[:8] != b"WED V1.3":
        raise ValueError("not a WED V1.3")
    count = struct.unpack_from("<I", data, 8)[0]
    ov_off = struct.unpack_from("<I", data, 16)[0]
    overlays = []
    for i in range(count):
        base = ov_off + i * 24
        if base + 24 > len(data):
            break
        w, h = struct.unpack_from("<2H", data, base)
        name = resref(data[base + 4 : base + 12])
        tilemap_off, til_off = struct.unpack_from("<2I", data, base + 16)
        cells = []
        for y in range(h):
            for x in range(w):
                cell = tilemap_off + (y * w + x) * 10
                if cell + 6 > len(data):
                    break
                start, n, secondary = struct.unpack_from("<3H", data, cell)
                if n > 64:
                    n = 64
                indices = []
                for k in range(n):
                    pos = til_off + (start + k) * 2
                    if pos + 2 > len(data):
                        break
                    indices.append(struct.unpack_from("<H", data, pos)[0])
                cells.append(
                    {
                        "x": x,
                        "y": y,
                        "indices": indices,
                        "secondary": None if secondary == 0xFFFF else secondary,
                    }
                )
        overlays.append({"w": w, "h": h, "tis": name, "cells": cells})
    return overlays


def _grid_from_overlay(overlay: dict, as_stitch: bool):
    h, w = overlay["h"], overlay["w"]
    grid = np.full((h, w), -1, dtype=np.int32)
    extras = []
    for cell in overlay["cells"]:
        indices = cell["indices"]
        if indices:
            grid[cell["y"], cell["x"]] = indices[0]
            rest = indices if not as_stitch else indices[1:]
            for index in rest:
                extras.append((cell["x"], cell["y"], index))
        if cell["secondary"] is not None:
            extras.append((cell["x"], cell["y"], cell["secondary"]))
    return grid, extras


def area_plan(tiles: np.ndarray, overlays: list[dict], tis_name: str) -> dict:
    """Decide which tile indices are stitched, which get a 3x3 patch, which are alone."""
    stitch = None
    extra_overlays = []
    for overlay in overlays:
        if overlay["tis"] != tis_name:
            continue
        if stitch is None and overlay is overlays[0]:
            stitch = overlay
        else:
            extra_overlays.append(overlay)
    # a tileset that is only a higher overlay still wants its own 3x3 grid
    if stitch is None and extra_overlays:
        pass
    elif stitch is None:
        extra_overlays = []

    placed: dict[int, tuple[int, int]] = {}
    image = None
    grids = []
    if stitch is not None and stitch["w"] and stitch["h"]:
        grid, more = _grid_from_overlay(stitch, as_stitch=True)
        grids.append((grid, more))
        image = np.zeros((stitch["h"] * TILE, stitch["w"] * TILE, 4), dtype=np.uint8)
        n = len(tiles)
        for y in range(stitch["h"]):
            for x in range(stitch["w"]):
                index = int(grid[y, x])
                if index < 0 or index >= n:
                    continue
                image[y * TILE : (y + 1) * TILE, x * TILE : (x + 1) * TILE] = tiles[index]
                placed.setdefault(index, (x, y))
    for overlay in extra_overlays:
        grid, more = _grid_from_overlay(overlay, as_stitch=False)
        grids.append((grid, more))

    extra_at: dict[int, tuple[np.ndarray, int, int]] = {}
    for grid, more in grids:
        for x, y, index in more:
            if index in placed or index in extra_at:
                continue
            if index < 0 or index >= len(tiles):
                continue
            extra_at[index] = (grid, x, y)
    solo = [i for i in range(len(tiles)) if i not in placed and i not in extra_at]
    return {"image": image, "placed": placed, "extras": extra_at, "solo": solo}


def patch_3x3(tiles: np.ndarray, grid: np.ndarray, x: int, y: int, center: int) -> np.ndarray:
    patch = np.zeros((TILE * 3, TILE * 3, 4), dtype=np.uint8)
    height, width = grid.shape
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                index = center
            else:
                ny = min(max(y + dy, 0), height - 1)
                nx = min(max(x + dx, 0), width - 1)
                index = int(grid[ny, nx])
                if index < 0:
                    index = center
            if index < 0 or index >= len(tiles):
                continue
            py, px = (dy + 1) * TILE, (dx + 1) * TILE
            patch[py : py + TILE, px : px + TILE] = tiles[index]
    return patch


def pad_solo(tile: np.ndarray, pad: int = 16) -> np.ndarray:
    return np.pad(tile, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
