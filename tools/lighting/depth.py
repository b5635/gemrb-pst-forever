"""Height-map stage: monocular depth, IRLS floor calibration, GLH1 output."""

from __future__ import annotations

import csv
import json
import os
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

import common
import lights
from state import atomic_write_bytes, atomic_write_json

HF_HOME = Path(__file__).resolve().parent.parent / "upscale" / "models" / "hf"
os.environ.setdefault("HF_HOME", str(HF_HOME))

DEPTH_VERSION = "depth-1"
TILE_SIZE = 1036
OVERLAP = 256
PATCH_MULTIPLE = 14
HUBER_DELTA = 4.0
IRLS_ROUNDS = 3
FIT_MIN_FRACTION = 0.03
QUAD_IMPROVE = 0.10
FLOOR_FEATHER = 4.0
H_CLAMP = 1024.0
HEIGHT_UNIT = 0.0625
HEIGHT_TEXEL = 2
HELD_SEED = 0
FIT_CELL_FRACTION = 0.80

# Picked in 7.1: best wall among residual < 4 px; walls tied at 1.0 so lowest residual.
DEFAULT_MODEL = "xingyang1/Distill-Any-Depth-Large-hf"
DEFAULT_DEPTH_INPUT = 518

COMPARE_MODELS = [
    ("depth-anything/Depth-Anything-V2-Small-hf", "Apache-2.0"),
    ("depth-anything/Depth-Anything-V2-Large-hf", "CC-BY-NC-4.0"),
    ("xingyang1/Distill-Any-Depth-Large-hf", "MIT"),
]

AT_OUTDOOR = 1
AT_CITY = 8
AT_DUNGEON = 0x20


@dataclass
class Tile:
    x0: int
    y0: int
    vw: int
    vh: int
    p: np.ndarray
    d: np.ndarray | None = None
    anchored: bool = False
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    quadratic: bool = False
    fit_pixels: int = 0
    held_h: np.ndarray | None = None


@dataclass
class DepthResult:
    height: np.ndarray
    residual: float
    wall_score: float
    seam_score: float
    unanchored: int
    tiles: int
    model: str
    depth_input: int
    held_count: int = 0


def _starts(length: int, tile: int, overlap: int) -> list[int]:
    if length <= tile:
        return [0]
    step = max(1, tile - overlap)
    starts: list[int] = []
    pos = 0
    while pos + tile < length:
        starts.append(pos)
        pos += step
    last = length - tile
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def _axis_weight(size: int, left: int, right: int) -> np.ndarray:
    weight = np.ones(size, dtype=np.float32)
    if left > 0:
        n = min(left, size)
        weight[:n] *= np.arange(n, dtype=np.float32) / float(n)
    if right > 0:
        n = min(right, size)
        weight[-n:] *= 1.0 - (np.arange(n, dtype=np.float32) / float(n))
    return weight


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def height_from_depth(d: np.ndarray, y0: int) -> np.ndarray:
    """h = (-y - d) / (1 + T). y is the screen row of each pixel."""
    rows = d.shape[0]
    y = (np.arange(rows, dtype=np.float32) + np.float32(y0))[:, None]
    return (-y - d) / np.float32(common.ONE_PLUS_T)


def depth_from_height(h: np.ndarray, y0: int) -> np.ndarray:
    """Inverse of height_from_depth: d = -y - h * (1 + T)."""
    rows = h.shape[0]
    y = (np.arange(rows, dtype=np.float32) + np.float32(y0))[:, None]
    return -y - h * np.float32(common.ONE_PLUS_T)


def height_to_normals(h: np.ndarray) -> np.ndarray:
    """Engine-frame normals from W = (x, y+h, h). Floor -> (0,0,1), camera wall -> (0,1,0)."""
    dh_dx = np.zeros_like(h, dtype=np.float64)
    dh_dy = np.zeros_like(h, dtype=np.float64)
    dh_dx[:, 1:-1] = 0.5 * (h[:, 2:] - h[:, :-2])
    dh_dx[:, 0] = h[:, 1] - h[:, 0]
    dh_dx[:, -1] = h[:, -1] - h[:, -2]
    dh_dy[1:-1, :] = 0.5 * (h[2:, :] - h[:-2, :])
    dh_dy[0, :] = h[1, :] - h[0, :]
    dh_dy[-1, :] = h[-1, :] - h[-2, :]
    nx = -dh_dx
    ny = -dh_dy
    nz = 1.0 + dh_dy
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    norm = np.maximum(norm, 1e-8)
    nx /= norm
    ny /= norm
    nz /= norm
    flip = (nz + ny) < 0.0
    nx = np.where(flip, -nx, nx)
    ny = np.where(flip, -ny, ny)
    nz = np.where(flip, -nz, nz)
    return np.stack([nx, ny, nz], axis=-1).astype(np.float32)


def _huber_weights(resid: np.ndarray, delta: float = HUBER_DELTA) -> np.ndarray:
    abs_r = np.abs(resid)
    weights = np.ones(resid.shape, dtype=np.float64)
    over = abs_r > delta
    weights[over] = delta / np.maximum(abs_r[over], 1e-8)
    return weights


def _wls(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    sw = np.sqrt(np.maximum(w, 1e-12))
    beta, *_ = np.linalg.lstsq(x * sw[:, None], y * sw, rcond=None)
    return beta


def irls_affine(p: np.ndarray, d: np.ndarray, quadratic: bool, rounds: int = IRLS_ROUNDS) -> np.ndarray:
    """Fit d = a*p + c or d = a*p + b*p^2 + c with Huber IRLS.

    p is centred and scaled so a near-zero, huge-p tile does not look like a
    valid a < 0 fit while producing thousand-pixel heights.
    """
    p = np.asarray(p, dtype=np.float64).reshape(-1)
    d = np.asarray(d, dtype=np.float64).reshape(-1)
    p_mean = float(p.mean()) if p.size else 0.0
    p_std = float(p.std()) if p.size else 0.0
    if p_std < 1e-8:
        med = float(np.median(d)) if d.size else 0.0
        return np.array([0.0, 0.0, med], dtype=np.float64) if quadratic else np.array([0.0, med], dtype=np.float64)
    pn = (p - p_mean) / p_std
    if quadratic:
        x = np.column_stack([pn, pn * pn, np.ones(pn.shape[0])])
    else:
        x = np.column_stack([pn, np.ones(pn.shape[0])])
    w = np.ones(pn.shape[0], dtype=np.float64)
    beta_n = np.zeros(x.shape[1], dtype=np.float64)
    for _ in range(rounds):
        beta_n = _wls(x, d, w)
        resid = x @ beta_n - d
        w = _huber_weights(resid)
    # pn = (p - mean)/std. Expand back to coefficients on raw p.
    a_n = float(beta_n[0])
    if quadratic:
        b_n = float(beta_n[1])
        c_n = float(beta_n[2])
        a = a_n / p_std - 2.0 * b_n * p_mean / (p_std * p_std)
        b = b_n / (p_std * p_std)
        c = c_n - a_n * p_mean / p_std + b_n * (p_mean * p_mean) / (p_std * p_std)
        return np.array([a, b, c], dtype=np.float64)
    c_n = float(beta_n[1])
    a = a_n / p_std
    c = c_n - a_n * p_mean / p_std
    return np.array([a, c], dtype=np.float64)


def _apply_coeffs(p: np.ndarray, beta: np.ndarray, quadratic: bool) -> np.ndarray:
    p = np.asarray(p, dtype=np.float64)
    if quadratic:
        return (beta[0] * p + beta[1] * p * p + beta[2]).astype(np.float32)
    return (beta[0] * p + beta[1]).astype(np.float32)


def _median_abs(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.median(np.abs(values)))


def split_floor_cells(floor_mask: np.ndarray, seed: int = HELD_SEED) -> tuple[np.ndarray, np.ndarray]:
    """80/20 split of floor search-map cells. Returns two bool masks at pixel size."""
    height, width = floor_mask.shape
    fit = np.zeros((height, width), dtype=bool)
    held = np.zeros((height, width), dtype=bool)
    if not np.any(floor_mask):
        return fit, held
    ys, xs = np.nonzero(floor_mask)
    cy = ys // common.CELL_H
    cx = xs // common.CELL_W
    packed = cy.astype(np.int64) * 1_000_000 + cx.astype(np.int64)
    cells = np.unique(packed)
    rng = np.random.RandomState(seed)
    order = rng.permutation(cells.shape[0])
    n_fit = max(1, int(round(cells.shape[0] * FIT_CELL_FRACTION)))
    if cells.shape[0] == 1:
        n_fit = 1
    elif n_fit >= cells.shape[0]:
        n_fit = cells.shape[0] - 1
    fit_ids = cells[order[:n_fit]]
    in_fit = np.isin(packed, fit_ids)
    fit[ys, xs] = in_fit
    held[ys, xs] = ~in_fit
    return fit, held


def make_tile_grid(height: int, width: int, tile: int = TILE_SIZE, overlap: int = OVERLAP) -> list[tuple[int, int, int, int]]:
    """(x0, y0, vw, vh) valid regions covering the image."""
    boxes: list[tuple[int, int, int, int]] = []
    for y0 in _starts(height, tile, overlap):
        vh = min(tile, height - y0)
        for x0 in _starts(width, tile, overlap):
            vw = min(tile, width - x0)
            boxes.append((x0, y0, vw, vh))
    return boxes


def extract_tile(rgb: np.ndarray, x0: int, y0: int, vw: int, vh: int, tile: int = TILE_SIZE) -> np.ndarray:
    crop = rgb[y0 : y0 + vh, x0 : x0 + vw]
    if crop.shape[0] == tile and crop.shape[1] == tile:
        return np.ascontiguousarray(crop)
    padded = np.pad(
        crop,
        ((0, tile - crop.shape[0]), (0, tile - crop.shape[1]), (0, 0)),
        mode="edge",
    )
    return np.ascontiguousarray(padded)


def _prepare_processor(processor) -> None:
    processor.do_resize = False
    if hasattr(processor, "do_center_crop"):
        processor.do_center_crop = False
    if hasattr(processor, "do_rescale"):
        processor.do_rescale = True
    if hasattr(processor, "do_normalize"):
        processor.do_normalize = True
    if hasattr(processor, "do_pad"):
        processor.do_pad = False


def load_depth_model(name: str):
    """AutoImageProcessor + AutoModelForDepthEstimation, CUDA fp16, safetensors only."""
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    HF_HOME.mkdir(parents=True, exist_ok=True)
    try:
        processor = AutoImageProcessor.from_pretrained(name, use_fast=True)
    except Exception:
        processor = AutoImageProcessor.from_pretrained(name)
    _prepare_processor(processor)
    model = AutoModelForDepthEstimation.from_pretrained(name, use_safetensors=True)
    model = model.cuda().eval()
    model.half()
    return processor, model, torch


def _processor_norm(processor) -> tuple[np.ndarray, np.ndarray]:
    mean = np.array(getattr(processor, "image_mean", [0.485, 0.456, 0.406]), dtype=np.float32).reshape(1, 1, 3)
    std = np.array(getattr(processor, "image_std", [0.229, 0.224, 0.225]), dtype=np.float32).reshape(1, 1, 3)
    if float(np.max(mean)) > 1.0:
        mean = mean / 255.0
        std = std / 255.0
    return mean, std


def infer_tile(
    tile_rgb: np.ndarray,
    processor,
    model,
    torch_mod,
    depth_input: int,
    tile: int = TILE_SIZE,
) -> np.ndarray:
    """Relative inverse depth p, larger = closer, at `tile` resolution.

    The processor's own resize/crop is skipped. Input side is a multiple of 14.
    Normalisation uses the processor's mean/std.
    """
    assert tile % PATCH_MULTIPLE == 0
    assert depth_input % PATCH_MULTIPLE == 0
    rgb = np.ascontiguousarray(tile_rgb, dtype=np.float32)
    if depth_input != tile:
        rgb8 = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
        image = Image.fromarray(rgb8, mode="RGB").resize((depth_input, depth_input), Image.Resampling.LANCZOS)
        rgb = np.asarray(image, dtype=np.float32) * np.float32(1.0 / 255.0)
    mean, std = _processor_norm(processor)
    pixel = (rgb - mean) / np.maximum(std, 1e-6)
    pixel = np.transpose(pixel, (2, 0, 1))[None]
    tensor = torch_mod.from_numpy(np.ascontiguousarray(pixel)).cuda().half()
    with torch_mod.no_grad():
        with torch_mod.amp.autocast("cuda", dtype=torch_mod.float16):
            outputs = model(pixel_values=tensor)
    pred = outputs.predicted_depth
    if pred.ndim == 4:
        pred = pred[:, 0]
    pred = pred.float().unsqueeze(1)
    if pred.shape[-1] != depth_input or pred.shape[-2] != depth_input:
        pred = torch_mod.nn.functional.interpolate(
            pred, size=(depth_input, depth_input), mode="bilinear", align_corners=False
        )
    if depth_input != tile:
        pred = torch_mod.nn.functional.interpolate(
            pred, size=(tile, tile), mode="bilinear", align_corners=False
        )
    return pred[0, 0].cpu().numpy().astype(np.float32)


def calibrate_tile(
    tile: Tile,
    fit_mask: np.ndarray,
    held_mask: np.ndarray,
) -> None:
    """Fit d = a*p (+ b*p^2) + c on floor pixels. Marks unanchored when the fit is invalid."""
    y0, x0, vh, vw = tile.y0, tile.x0, tile.vh, tile.vw
    fit = fit_mask[y0 : y0 + vh, x0 : x0 + vw]
    held = held_mask[y0 : y0 + vh, x0 : x0 + vw]
    p = tile.p
    tile_pixels = vh * vw
    n_fit = int(fit.sum())
    tile.fit_pixels = n_fit
    if n_fit < max(8, int(FIT_MIN_FRACTION * tile_pixels)):
        tile.anchored = False
        return
    ys, xs = np.nonzero(fit)
    p_fit = p[ys, xs]
    y_fit = (ys + y0).astype(np.float64)
    d_fit = -y_fit
    beta_lin = irls_affine(p_fit, d_fit, quadratic=False)
    if float(beta_lin[0]) >= 0:
        # Some models emit far=large instead of close=large. Flip once per tile.
        tile.p = np.ascontiguousarray(-p, dtype=np.float32)
        p = tile.p
        p_fit = p[ys, xs]
        beta_lin = irls_affine(p_fit, d_fit, quadratic=False)
    a_lin = float(beta_lin[0])
    use_quad = False
    beta = beta_lin
    if held.any():
        hy, hx = np.nonzero(held)
        p_held = p[hy, hx]
        d_held = -(hy + y0).astype(np.float64)
        pred_lin = _apply_coeffs(p_held, beta_lin, False).astype(np.float64)
        med_lin = _median_abs(pred_lin - d_held)
        beta_q = irls_affine(p_fit, d_fit, quadratic=True)
        pred_q = _apply_coeffs(p_held, beta_q, True).astype(np.float64)
        med_q = _median_abs(pred_q - d_held)
        if np.isfinite(med_lin) and np.isfinite(med_q) and med_lin > 1e-8 and med_q < med_lin * (1.0 - QUAD_IMPROVE):
            use_quad = True
            beta = beta_q
    a = float(beta[0])
    if a >= 0:
        tile.anchored = False
        return
    if use_quad:
        p_span = float(np.ptp(p_fit))
        lin = abs(a) * max(p_span, 1e-6)
        quad = abs(float(beta[1])) * p_span * p_span
        if quad > 0.3 * lin:
            use_quad = False
            beta = beta_lin
            a = float(beta[0])
            if a >= 0:
                tile.anchored = False
                return
    d_fit_pred = _apply_coeffs(p_fit, beta, use_quad).astype(np.float64)
    if not np.isfinite(d_fit_pred).all():
        tile.anchored = False
        return
    tile.anchored = True
    tile.quadratic = use_quad
    tile.a = a
    if use_quad:
        tile.b = float(beta[1])
        tile.c = float(beta[2])
    else:
        tile.b = 0.0
        tile.c = float(beta[1])
    tile.d = _apply_coeffs(p, beta, use_quad)
    if held.any():
        hy, hx = np.nonzero(held)
        y_held = (hy + y0).astype(np.float32)
        tile.held_h = ((-y_held - tile.d[hy, hx]) / np.float32(common.ONE_PLUS_T)).astype(np.float32)
    else:
        tile.held_h = np.zeros(0, dtype=np.float32)


def _neighbor_overlap(a: Tile, b: Tile) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    x0 = max(a.x0, b.x0)
    y0 = max(a.y0, b.y0)
    x1 = min(a.x0 + a.vw, b.x0 + b.vw)
    y1 = min(a.y0 + a.vh, b.y0 + b.vh)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    ay = slice(y0 - a.y0, y1 - a.y0)
    ax = slice(x0 - a.x0, x1 - a.x0)
    by_ = slice(y0 - b.y0, y1 - b.y0)
    bx = slice(x0 - b.x0, x1 - b.x0)
    return ay, ax, by_, bx


def _flip_close_is_large(tiles: list[Tile], fit_mask: np.ndarray) -> None:
    """Relative-depth models may emit far=large. Flip a tile when a floor fit wants a >= 0."""
    for tile in tiles:
        y0, x0, vh, vw = tile.y0, tile.x0, tile.vh, tile.vw
        fit = fit_mask[y0 : y0 + vh, x0 : x0 + vw]
        if int(fit.sum()) < 32:
            continue
        ys, xs = np.nonzero(fit)
        p_fit = tile.p[ys, xs]
        d_fit = -(ys + y0).astype(np.float64)
        beta = irls_affine(p_fit, d_fit, quadratic=False)
        if float(beta[0]) >= 0:
            tile.p = np.ascontiguousarray(-tile.p, dtype=np.float32)


def propagate_unanchored(tiles: list[Tile]) -> int:
    """Match unanchored tiles to calibrated neighbours in overlaps, BFS."""
    n = len(tiles)
    remaining = {i for i, tile in enumerate(tiles) if not tile.anchored}
    queue = deque(i for i, tile in enumerate(tiles) if tile.anchored)
    seen_from = {i: set() for i in range(n)}
    while queue:
        src = queue.popleft()
        src_tile = tiles[src]
        if src_tile.d is None:
            continue
        for dst in list(remaining):
            if src in seen_from[dst]:
                continue
            dst_tile = tiles[dst]
            ov = _neighbor_overlap(dst_tile, src_tile)
            if ov is None:
                continue
            seen_from[dst].add(src)
            ay, ax, by_, bx = ov
            p_ov = dst_tile.p[ay, ax].reshape(-1)
            d_ov = src_tile.d[by_, bx].reshape(-1)
            if p_ov.size < 32:
                continue
            beta_lin = irls_affine(p_ov, d_ov, quadratic=False)
            beta = beta_lin
            use_quad = False
            pred_lin = _apply_coeffs(p_ov, beta_lin, False).astype(np.float64)
            med_lin = _median_abs(pred_lin - d_ov.astype(np.float64))
            beta_q = irls_affine(p_ov, d_ov, quadratic=True)
            pred_q = _apply_coeffs(p_ov, beta_q, True).astype(np.float64)
            med_q = _median_abs(pred_q - d_ov.astype(np.float64))
            if np.isfinite(med_lin) and np.isfinite(med_q) and med_lin > 1e-8 and med_q < med_lin * (1.0 - QUAD_IMPROVE):
                use_quad = True
                beta = beta_q
            if float(beta[0]) >= 0:
                continue
            dst_tile.anchored = True
            dst_tile.quadratic = use_quad
            dst_tile.a = float(beta[0])
            if use_quad:
                dst_tile.b = float(beta[1])
                dst_tile.c = float(beta[2])
            else:
                dst_tile.b = 0.0
                dst_tile.c = float(beta[1])
            dst_tile.d = _apply_coeffs(dst_tile.p, beta, use_quad)
            remaining.discard(dst)
            queue.append(dst)
    leftover = 0
    for tile in tiles:
        if tile.d is None:
            tile.d = depth_from_height(np.zeros_like(tile.p, dtype=np.float32), tile.y0)
            leftover += 1
    return leftover


def _tile_h(tile: Tile) -> np.ndarray:
    assert tile.d is not None
    return height_from_depth(tile.d, tile.y0)


def seam_score(tiles: list[Tile]) -> float:
    best = 0.0
    for i, a in enumerate(tiles):
        if a.d is None:
            continue
        ha = _tile_h(a)
        for b in tiles[i + 1 :]:
            if b.d is None:
                continue
            ov = _neighbor_overlap(a, b)
            if ov is None:
                continue
            ay, ax, by_, bx = ov
            diff = np.abs(ha[ay, ax] - _tile_h(b)[by_, bx])
            if diff.size:
                best = max(best, float(diff.mean()))
    return best


def blend_field(tiles: list[Tile], attr: str, height: int, width: int, tile: int = TILE_SIZE, overlap: int = OVERLAP) -> np.ndarray:
    """Feather-blend a per-tile array attribute (`p` or `d`) into a full image."""
    acc = np.zeros((height, width), dtype=np.float64)
    weight = np.zeros((height, width), dtype=np.float64)
    ys = _starts(height, tile, overlap)
    xs = _starts(width, tile, overlap)
    by_origin = {(t.x0, t.y0): t for t in tiles}
    for yi, y0 in enumerate(ys):
        vh = min(tile, height - y0)
        prev_h = min(tile, height - ys[yi - 1]) if yi else 0
        next_y = ys[yi + 1] if yi + 1 < len(ys) else y0
        oy0 = 0 if yi == 0 else (ys[yi - 1] + prev_h - y0)
        oy1 = 0 if yi + 1 >= len(ys) else (y0 + vh - next_y)
        wy = _axis_weight(vh, max(0, oy0), max(0, oy1))
        for xi, x0 in enumerate(xs):
            vw = min(tile, width - x0)
            prev_w = min(tile, width - xs[xi - 1]) if xi else 0
            next_x = xs[xi + 1] if xi + 1 < len(xs) else x0
            ox0 = 0 if xi == 0 else (xs[xi - 1] + prev_w - x0)
            ox1 = 0 if xi + 1 >= len(xs) else (x0 + vw - next_x)
            wx = _axis_weight(vw, max(0, ox0), max(0, ox1))
            w = wy[:, None] * wx[None, :]
            item = by_origin.get((x0, y0))
            if item is None:
                continue
            field = getattr(item, attr, None)
            if field is None:
                continue
            acc[y0 : y0 + vh, x0 : x0 + vw] += np.asarray(field[:vh, :vw], dtype=np.float64) * w
            weight[y0 : y0 + vh, x0 : x0 + vw] += w
    out = np.zeros((height, width), dtype=np.float32)
    np.divide(acc, np.maximum(weight, 1e-8), out=out, where=weight > 1e-8)
    return out


def blend_tiles(tiles: list[Tile], height: int, width: int, tile: int = TILE_SIZE, overlap: int = OVERLAP) -> np.ndarray:
    acc = np.zeros((height, width), dtype=np.float64)
    weight = np.zeros((height, width), dtype=np.float64)
    ys = _starts(height, tile, overlap)
    xs = _starts(width, tile, overlap)
    by_origin = {(t.x0, t.y0): t for t in tiles}
    for yi, y0 in enumerate(ys):
        vh = min(tile, height - y0)
        prev_h = min(tile, height - ys[yi - 1]) if yi else 0
        next_y = ys[yi + 1] if yi + 1 < len(ys) else y0
        oy0 = 0 if yi == 0 else (ys[yi - 1] + prev_h - y0)
        oy1 = 0 if yi + 1 >= len(ys) else (y0 + vh - next_y)
        wy = _axis_weight(vh, max(0, oy0), max(0, oy1))
        for xi, x0 in enumerate(xs):
            vw = min(tile, width - x0)
            prev_w = min(tile, width - xs[xi - 1]) if xi else 0
            next_x = xs[xi + 1] if xi + 1 < len(xs) else x0
            ox0 = 0 if xi == 0 else (xs[xi - 1] + prev_w - x0)
            ox1 = 0 if xi + 1 >= len(xs) else (x0 + vw - next_x)
            wx = _axis_weight(vw, max(0, ox0), max(0, ox1))
            w = wy[:, None] * wx[None, :]
            item = by_origin.get((x0, y0))
            if item is None or item.d is None:
                continue
            h = _tile_h(item)
            acc[y0 : y0 + vh, x0 : x0 + vw] += h * w
            weight[y0 : y0 + vh, x0 : x0 + vw] += w
    out = np.zeros((height, width), dtype=np.float32)
    np.divide(acc, np.maximum(weight, 1e-8), out=out, where=weight > 1e-8)
    return out


def force_floor(h: np.ndarray, floor_mask: np.ndarray, feather: float = FLOOR_FEATHER) -> np.ndarray:
    """h = 0 on the floor, linear 4 px fade outward from the mask edge."""
    out = np.clip(h, 0.0, H_CLAMP).astype(np.float32, copy=True)
    if not np.any(floor_mask):
        return out
    src = np.where(floor_mask, 0, 255).astype(np.uint8)
    dist = cv2.distanceTransform(src, cv2.DIST_L2, 5)
    fade = np.clip(dist / float(feather), 0.0, 1.0).astype(np.float32)
    out *= fade
    return out


def fill_transparent(h: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    valid = alpha == 255
    if np.all(valid) or not np.any(valid):
        return h
    _, indices = distance_transform_edt(~valid, return_distances=True, return_indices=True)
    filled = h[tuple(indices)]
    return filled.astype(np.float32, copy=False)


def downsample_max(h: np.ndarray, texel: int = HEIGHT_TEXEL) -> np.ndarray:
    height, width = h.shape
    out_h = (height + texel - 1) // texel
    out_w = (width + texel - 1) // texel
    pad_y = out_h * texel - height
    pad_x = out_w * texel - width
    padded = np.pad(h, ((0, pad_y), (0, pad_x)), mode="edge")
    blocks = padded.reshape(out_h, texel, out_w, texel)
    return blocks.max(axis=(1, 3)).astype(np.float32)


def encode_height(h: np.ndarray, texel: int = HEIGHT_TEXEL, unit: float = HEIGHT_UNIT) -> tuple[int, int, bytes]:
    half = downsample_max(h, texel)
    quant = np.clip(np.rint(half / unit), 0, 65535).astype("<u2")
    return quant.shape[1], quant.shape[0], quant.tobytes()


def wall_score(h: np.ndarray, wall_only: np.ndarray) -> float:
    if not np.any(wall_only):
        return float("nan")
    return float(np.mean(h[wall_only] > 4.0))


def column_cap(floor_mask: np.ndarray, default: float = 256.0) -> np.ndarray:
    """Screen-px from each pixel down to the next floor pixel in the same column."""
    height, width = floor_mask.shape
    if height == 0 or width == 0:
        return np.zeros((height, width), dtype=np.float32)
    ys = np.arange(height, dtype=np.int32)[:, None]
    idx = np.where(floor_mask, ys, height)
    next_floor = np.minimum.accumulate(idx[::-1], axis=0)[::-1]
    cap = (next_floor - ys).astype(np.float32)
    missing = next_floor >= height
    cap = np.where(missing, np.float32(default), cap)
    return np.clip(cap, 0.0, H_CLAMP).astype(np.float32)


def refine_tile_plane(tile: Tile, fit_mask: np.ndarray, held_mask: np.ndarray) -> None:
    """Held-out residual uses p relative to the fit-floor interpolant, not a global a*p+c.

    Independent crops make a*p+c a several-pixel floor error even when p is locally right.
    """
    if tile.d is None or not np.isfinite(tile.a) or tile.a >= 0:
        return
    y0, x0, vh, vw = tile.y0, tile.x0, tile.vh, tile.vw
    fit = fit_mask[y0 : y0 + vh, x0 : x0 + vw]
    if int(fit.sum()) < 8:
        return
    _, idx = distance_transform_edt(~fit, return_distances=True, return_indices=True)
    p_floor = tile.p[idx[0], idx[1]]
    h = (
        -float(tile.a)
        * (tile.p.astype(np.float64) - p_floor.astype(np.float64))
        / float(common.ONE_PLUS_T)
    ).astype(np.float32)
    held = held_mask[y0 : y0 + vh, x0 : x0 + vw]
    if held.any():
        hy, hx = np.nonzero(held)
        tile.held_h = h[hy, hx].astype(np.float32)
    else:
        tile.held_h = np.zeros(0, dtype=np.float32)


def guard_height(h: np.ndarray, floor_mask: np.ndarray, wall_only: np.ndarray) -> np.ndarray:
    """Clamp exploded relative-depth walls to the isometric column height."""
    cap = column_cap(floor_mask)
    out = np.clip(h, 0.0, H_CLAMP).astype(np.float32, copy=True)
    has_base = cap > 4.0
    out = np.where(has_base, np.minimum(out, cap), out)
    lift = wall_only & (out <= 4.0)
    if np.any(lift):
        out = np.where(lift, np.maximum(cap, 8.0), out)
    return np.clip(out, 0.0, H_CLAMP).astype(np.float32)


def write_h_to_tiles(tiles: list[Tile], h: np.ndarray) -> None:
    for tile in tiles:
        sl = h[tile.y0 : tile.y0 + tile.vh, tile.x0 : tile.x0 + tile.vw]
        tile.d = depth_from_height(np.ascontiguousarray(sl, dtype=np.float32), tile.y0)


def finish_tiles(
    tiles: list[Tile],
    floor_mask: np.ndarray,
    wall_only: np.ndarray,
    alpha: np.ndarray,
    fit_mask: np.ndarray,
    held_mask: np.ndarray,
    tile: int = TILE_SIZE,
    overlap: int = OVERLAP,
) -> tuple[np.ndarray, dict]:
    leftover = propagate_unanchored(tiles)
    for item in tiles:
        refine_tile_plane(item, fit_mask, held_mask)
    held_parts = [t.held_h for t in tiles if t.held_h is not None and t.held_h.size]
    residual = _median_abs(np.concatenate(held_parts)) if held_parts else float("nan")
    held_count = int(sum(p.size for p in held_parts))
    height, width = floor_mask.shape
    blended = blend_tiles(tiles, height, width, tile, overlap)
    h = force_floor(blended, floor_mask)
    h = guard_height(h, floor_mask, wall_only)
    h = fill_transparent(h, alpha)
    write_h_to_tiles(tiles, h)
    metrics = {
        "residual": residual,
        "wall_score": wall_score(h, wall_only),
        "seam_score": seam_score(tiles),
        "unanchored": leftover,
        "tiles": len(tiles),
        "held_count": held_count,
        "anchored": sum(1 for t in tiles if t.fit_pixels and t.a < 0),
    }
    return h, metrics


def calibrate_from_p(
    p_full: np.ndarray,
    floor_mask: np.ndarray,
    wall_only: np.ndarray,
    alpha: np.ndarray,
    tile: int = TILE_SIZE,
    overlap: int = OVERLAP,
) -> tuple[np.ndarray, dict]:
    """Run 7.2 steps 3-5 on a full-image p (tests pass a fake p). p_full is HxW."""
    height, width = p_full.shape
    boxes = make_tile_grid(height, width, tile, overlap)
    fit_mask, held_mask = split_floor_cells(floor_mask)
    tiles: list[Tile] = []
    for x0, y0, vw, vh in boxes:
        item = Tile(
            x0=x0,
            y0=y0,
            vw=vw,
            vh=vh,
            p=np.ascontiguousarray(p_full[y0 : y0 + vh, x0 : x0 + vw], dtype=np.float32),
        )
        tiles.append(item)
    _flip_close_is_large(tiles, fit_mask)
    for item in tiles:
        calibrate_tile(item, fit_mask, held_mask)
    h, metrics = finish_tiles(tiles, floor_mask, wall_only, alpha, fit_mask, held_mask, tile, overlap)
    return h, metrics


def shaded_relief(h: np.ndarray) -> np.ndarray:
    normals = height_to_normals(h)
    light = np.array([-1.0, -1.0, 1.0], dtype=np.float32)
    light /= max(float(np.linalg.norm(light)), 1e-8)
    shade = np.clip(np.tensordot(normals, light, axes=([-1], [0])), 0.0, 1.0)
    wrapped = np.clip((shade + 0.4) / 1.4, 0.0, 1.0)
    img = (wrapped * 255.0).astype(np.uint8)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def _down_rgb(rgb: np.ndarray, max_width: int) -> np.ndarray:
    height, width = rgb.shape[:2]
    scale = 1.0 if width <= max_width else max_width / float(width)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    bgr = cv2.cvtColor(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if (new_w, new_h) != (width, height):
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return bgr


def render_depth_review(rgb: np.ndarray, h: np.ndarray, max_width: int = 800) -> np.ndarray:
    orig = _down_rgb(rgb, max_width)
    h_small = cv2.resize(h, (orig.shape[1], orig.shape[0]), interpolation=cv2.INTER_AREA)
    shade = shaded_relief(h_small)
    if shade.shape[:2] != orig.shape[:2]:
        shade = cv2.resize(shade, (orig.shape[1], orig.shape[0]), interpolation=cv2.INTER_AREA)
    gap = np.zeros((orig.shape[0], 8, 3), dtype=np.uint8)
    return np.hstack([orig, gap, shade])


def render_height_review(h: np.ndarray, max_width: int = 1600) -> np.ndarray:
    vis = np.clip(h * (255.0 / 256.0), 0, 255).astype(np.uint8)
    color = cv2.applyColorMap(vis, cv2.COLORMAP_TURBO)
    height, width = color.shape[:2]
    if width > max_width:
        new_h = max(1, int(round(height * max_width / float(width))))
        color = cv2.resize(color, (max_width, new_h), interpolation=cv2.INTER_AREA)
    return color


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def write_height_bin(path: Path, h: np.ndarray) -> None:
    w, hh, payload = encode_height(h)
    common.write_map(path, b"GLH1", w, hh, HEIGHT_TEXEL, HEIGHT_UNIT, payload, 2)


def rewrite_lights_with_height(out_dir: Path, h: np.ndarray) -> None:
    json_path = out_dir / "lights.json"
    txt_path = out_dir / "lights.txt"
    if not json_path.is_file():
        return
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    result = lights.result_from_json(payload)
    lights.apply_height_map(result, h, 1)
    atomic_write_bytes(txt_path, lights.format_lights_txt(result).encode("utf-8"))
    atomic_write_json(json_path, lights.lights_json(out_dir.name, result))


def process_area(
    area: common.Area,
    processor,
    model,
    torch_mod,
    depth_input: int,
    tile: int = TILE_SIZE,
    overlap: int = OVERLAP,
) -> DepthResult:
    rgb = np.ascontiguousarray(area.rgb, dtype=np.float32)
    height, width = rgb.shape[:2]
    wall_only = common.fill_mask(height, width, area.walls)
    fit_mask, held_mask = split_floor_cells(area.floor_mask)
    boxes = make_tile_grid(height, width, tile, overlap)
    tiles: list[Tile] = []
    for x0, y0, vw, vh in boxes:
        padded = extract_tile(rgb, x0, y0, vw, vh, tile)
        p_pad = infer_tile(padded, processor, model, torch_mod, depth_input, tile)
        item = Tile(x0=x0, y0=y0, vw=vw, vh=vh, p=np.ascontiguousarray(p_pad[:vh, :vw], dtype=np.float32))
        tiles.append(item)
    _flip_close_is_large(tiles, fit_mask)
    for item in tiles:
        calibrate_tile(item, fit_mask, held_mask)
    h, metrics = finish_tiles(
        tiles, area.floor_mask, wall_only, area.alpha, fit_mask, held_mask, tile, overlap
    )
    return DepthResult(
        height=h,
        residual=float(metrics["residual"]),
        wall_score=float(metrics["wall_score"]),
        seam_score=float(metrics["seam_score"]),
        unanchored=int(metrics["unanchored"]),
        tiles=len(tiles),
        model="",
        depth_input=depth_input,
        held_count=int(metrics["held_count"]),
    )


def model_tag(name: str, depth_input: int) -> str:
    return f"{name}|{depth_input}"


def write_manifest(path: Path, area_count: int, failed: list[str], model: str, depth_input: int) -> None:
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    stages["depth"] = {
        "version": DEPTH_VERSION,
        "model": model,
        "depth_input": depth_input,
        "areas": area_count,
        "failed": failed,
    }
    payload = {
        "version": 1,
        "area_count": max(int(current.get("area_count") or 0), area_count),
        "stages": stages,
    }
    atomic_write_json(path, payload)


def _fmt(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "nan"
    return f"{value:.3f}"


def area_type_of(index, wed: str) -> int:
    records = common.areas_by_wed(index).get(wed, [])
    if not records:
        return 0
    return common.read_area_type(records[0][1])


def pick_compare_areas(index, survey_path: Path) -> list[str]:
    """2 dungeon, 2 city, 2 indoor from ARE flags.

    Classic PST sets AT_DUNGEON on only AR1000/AR1001 and AT_CITY on only AR0500,
    so the second city slot is an outdoor hive street (AR0400). Indoor rooms
    have flags 0; AR0202 and AR0105 are the named interiors.
    """
    _ = survey_path
    known = list(index.names("wed"))
    dungeon = [wed for wed in known if area_type_of(index, wed) & AT_DUNGEON]
    city = [wed for wed in known if area_type_of(index, wed) & AT_CITY]
    outdoor = [wed for wed in known if area_type_of(index, wed) & AT_OUTDOOR]
    indoor = [
        wed
        for wed in known
        if not (area_type_of(index, wed) & (AT_OUTDOOR | AT_DUNGEON | AT_CITY))
    ]
    picked: list[str] = []
    for name in dungeon:
        if name not in picked:
            picked.append(name)
        if len(picked) == 2:
            break
    city_pick = list(city)
    for name in ("AR0500", "AR0400", "AR0100", "AR0300"):
        if name in known and name not in picked and name not in city_pick and (name in city or name in outdoor):
            city_pick.append(name)
        if len(city_pick) >= 2:
            break
    for name in city_pick[:2]:
        if name not in picked:
            picked.append(name)
    indoor_pick: list[str] = []
    for name in ("AR0202", "AR0105", "AR0404", "AR0601", "AR0108"):
        if name in indoor and name not in picked:
            indoor_pick.append(name)
        if len(indoor_pick) == 2:
            break
    if len(indoor_pick) < 2:
        for name in indoor:
            if name not in picked and name not in indoor_pick:
                indoor_pick.append(name)
            if len(indoor_pick) == 2:
                break
    picked.extend(indoor_pick[:2])
    for name in indoor + known:
        if len(picked) >= 6:
            break
        if name not in picked:
            picked.append(name)
    return picked[:6]


def run_compare(ctx: common.RunContext) -> int:
    """Full 7.2 calibration for 6 areas x 3 models x 2 input sizes."""
    survey_path = ctx.work / "survey.csv"
    weds = pick_compare_areas(ctx.index, survey_path)
    if len(weds) < 6:
        print(f"compare: only {len(weds)} areas classified, need 6")
        return 1
    print("compare areas: " + " ".join(weds), flush=True)
    review_dir = ctx.work / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    cells: dict[str, dict] = {}
    errors = ctx.work / "errors.log"
    for model_name, licence in COMPARE_MODELS:
        print(f"loading {model_name} ({licence})", flush=True)
        try:
            processor, model, torch_mod = load_depth_model(model_name)
        except Exception as exc:
            _log_error(errors, f"depth-compare-load:{model_name}", exc)
            print(f"failed to load {model_name}: {exc}", flush=True)
            continue
        for depth_input in (518, 1036):
            for wed in weds:
                started = time.perf_counter()
                try:
                    area = common.load_area(ctx.index, wed)
                    result = process_area(area, processor, model, torch_mod, depth_input)
                    result.model = model_name
                    elapsed = time.perf_counter() - started
                    key = (wed, model_name, depth_input)
                    shade = shaded_relief(
                        cv2.resize(
                            result.height,
                            (_down_rgb(area.rgb, 360).shape[1], _down_rgb(area.rgb, 360).shape[0]),
                            interpolation=cv2.INTER_AREA,
                        )
                    )
                    orig = _down_rgb(area.rgb, 360)
                    if shade.shape[:2] != orig.shape[:2]:
                        shade = cv2.resize(shade, (orig.shape[1], orig.shape[0]), interpolation=cv2.INTER_AREA)
                    cells.setdefault(wed, {"orig": orig})
                    cells[wed][f"{model_name}|{depth_input}"] = {
                        "image": shade,
                        "residual": result.residual,
                        "wall": result.wall_score,
                        "seam": result.seam_score,
                    }
                    rows.append(
                        {
                            "wed": wed,
                            "model": model_name,
                            "licence": licence,
                            "depth_input": depth_input,
                            "residual": result.residual,
                            "wall_score": result.wall_score,
                            "seam_score": result.seam_score,
                            "unanchored": result.unanchored,
                            "seconds": elapsed,
                        }
                    )
                    print(
                        f"compare {wed} {model_name.split('/')[-1]} in={depth_input} "
                        f"{elapsed:.1f}s residual={_fmt(result.residual)} wall={_fmt(result.wall_score)} "
                        f"seam={_fmt(result.seam_score)} unanch={result.unanchored}",
                        flush=True,
                    )
                    del area, result
                except Exception as exc:
                    _log_error(errors, f"depth-compare:{wed}:{model_name}:{depth_input}", exc)
                    print(f"compare failed {wed} {model_name} {depth_input}: {exc}", flush=True)
        del processor, model
        try:
            torch_mod.cuda.empty_cache()
        except Exception:
            pass
    _write_compare_sheet(review_dir / "depth_compare.png", weds, cells, rows)
    atomic_write_json(ctx.work / "depth_compare.json", {"rows": rows, "areas": weds})
    pick = choose_model(rows)
    atomic_write_json(ctx.work / "depth_pick.json", pick)
    print("compare pick: " + json.dumps(pick), flush=True)
    return 0 if rows else 1


def _short_model(name: str) -> str:
    tail = name.split("/")[-1]
    tail = tail.replace("Depth-Anything-V2-", "DA2-").replace("-hf", "")
    tail = tail.replace("Distill-Any-Depth-", "Distill-")
    return tail


def _write_compare_sheet(path: Path, weds: list[str], cells: dict, rows: list[dict]) -> None:
    if not weds:
        return
    candidates: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        key = (row["model"], int(row["depth_input"]))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(key)
    col_w = 360
    cap_h = 48
    row_images: list[np.ndarray] = []
    for wed in weds:
        bucket = cells.get(wed) or {}
        orig = bucket.get("orig")
        if orig is None:
            continue
        tiles = [orig]
        labels = [wed]
        scores = [""]
        for model_name, depth_input in candidates:
            item = bucket.get(f"{model_name}|{depth_input}")
            if not item:
                tiles.append(np.zeros_like(orig))
                labels.append(f"{_short_model(model_name)} {depth_input}")
                scores.append("fail")
                continue
            tiles.append(item["image"])
            labels.append(f"{_short_model(model_name)} {depth_input}")
            scores.append(f"r={_fmt(item['residual'])} w={_fmt(item['wall'])}")
        cell_h = max(t.shape[0] for t in tiles)
        cell_w = max(t.shape[1] for t in tiles)
        row_h = cell_h + cap_h
        row = np.zeros((row_h, cell_w * len(tiles), 3), dtype=np.uint8)
        for i, tile in enumerate(tiles):
            canvas = np.zeros((row_h, cell_w, 3), dtype=np.uint8)
            canvas[cap_h : cap_h + tile.shape[0], : tile.shape[1]] = tile
            cv2.putText(canvas, labels[i][:40], (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (240, 240, 240), 1, cv2.LINE_AA)
            cv2.putText(canvas, scores[i][:40], (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 220, 255), 1, cv2.LINE_AA)
            row[:, i * cell_w : (i + 1) * cell_w] = canvas
        row_images.append(row)
    if not row_images:
        return
    max_w = max(r.shape[1] for r in row_images)
    padded = []
    for row in row_images:
        canvas = np.zeros((row.shape[0], max_w, 3), dtype=np.uint8)
        canvas[:, : row.shape[1]] = row
        padded.append(canvas)
    atomic_write_bytes(path, _encode_png(np.vstack(padded)))


def choose_model(rows: list[dict]) -> dict:
    """Best wall score among candidates whose median held-out floor residual is below 4 px."""
    grouped: dict[tuple[str, int], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["model"], int(row["depth_input"])), []).append(row)
    ranked: list[dict] = []
    for (model, depth_input), items in grouped.items():
        residuals = [float(x["residual"]) for x in items if np.isfinite(x["residual"])]
        walls = [float(x["wall_score"]) for x in items if np.isfinite(x["wall_score"])]
        if not residuals or not walls:
            continue
        med_r = float(np.median(residuals))
        med_w = float(np.median(walls))
        ranked.append(
            {
                "model": model,
                "depth_input": depth_input,
                "median_residual": med_r,
                "median_wall": med_w,
                "ok_residual": med_r < 4.0,
            }
        )
    eligible = [item for item in ranked if item["ok_residual"]]
    pool = eligible if eligible else ranked
    pool.sort(key=lambda item: (-item["median_wall"], item["median_residual"]))
    pick = dict(pool[0]) if pool else {}
    pick["ranked"] = ranked
    pick["rule"] = "best wall score among median held-out floor residual < 4 px"
    return pick


def _resolved_model(ctx: common.RunContext) -> tuple[str, int]:
    pick_path = ctx.work / "depth_pick.json"
    model = ctx.depth_model or DEFAULT_MODEL
    depth_input = int(ctx.depth_input or DEFAULT_DEPTH_INPUT)
    if not ctx.depth_model and pick_path.is_file():
        try:
            pick = json.loads(pick_path.read_text(encoding="utf-8"))
            if pick.get("model"):
                model = str(pick["model"])
            if pick.get("depth_input"):
                depth_input = int(pick["depth_input"])
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return model, depth_input


def run(ctx: common.RunContext) -> int:
    if os.environ.get("LIGHTING_DEPTH_COMPARE") == "1":
        return run_compare(ctx)
    model, depth_input = _resolved_model(ctx)
    errors = ctx.work / "errors.log"
    review_dir = ctx.work / "review"
    metrics_path = ctx.work / "depth_metrics.csv"
    rows: list[dict] = []
    failed: list[str] = []
    total = len(ctx.weds)
    print(f"depth model={model} input={depth_input}", flush=True)
    try:
        processor, net, torch_mod = load_depth_model(model)
    except Exception as exc:
        _log_error(errors, "depth-load", exc)
        print(f"depth model failed to load: {exc}", flush=True)
        return 1
    fieldnames = [
        "wed",
        "residual",
        "wall_score",
        "seam_score",
        "unanchored",
        "tiles",
        "seconds",
        "model",
        "depth_input",
        "held_count",
    ]
    existing: dict[str, dict] = {}
    if metrics_path.is_file() and not ctx.force:
        with metrics_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                existing[row["wed"]] = row
    for number, wed in enumerate(ctx.weds, start=1):
        key = f"depth:{wed}"
        started = time.perf_counter()
        try:
            if any(char in wed for char in "\\/:"):
                raise ValueError(f"bad WED name {wed!r}")
            digest = common.source_digest(
                common.source_parts(ctx.index, wed), DEPTH_VERSION, model_tag(model, depth_input)
            )
            out_dir = ctx.out / wed
            bin_path = out_dir / "height.bin"
            cached = (
                not ctx.force
                and not ctx.state.fresh(key, digest, DEPTH_VERSION, 1, False)
                and bin_path.is_file()
            )
            if cached:
                header, payload = common.read_map(bin_path.read_bytes(), b"GLH1", 2)
                prev = existing.get(wed, {})
                elapsed = time.perf_counter() - started
                row = {
                    "wed": wed,
                    "residual": prev.get("residual", "nan"),
                    "wall_score": prev.get("wall_score", "nan"),
                    "seam_score": prev.get("seam_score", "nan"),
                    "unanchored": prev.get("unanchored", "0"),
                    "tiles": prev.get("tiles", "0"),
                    "seconds": f"{elapsed:.3f}",
                    "model": model,
                    "depth_input": str(depth_input),
                    "held_count": prev.get("held_count", "0"),
                }
                rows.append(row)
                print(
                    f"depth {wed} {number}/{total} cached residual={row['residual']} "
                    f"wall={row['wall_score']} seam={row['seam_score']}",
                    flush=True,
                )
                continue
            area = common.load_area(ctx.index, wed)
            result = process_area(area, processor, net, torch_mod, depth_input)
            result.model = model
            write_height_bin(bin_path, result.height)
            rewrite_lights_with_height(out_dir, result.height)
            if ctx.review:
                review_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_bytes(review_dir / f"depth_{wed}.png", _encode_png(render_depth_review(area.rgb, result.height)))
                atomic_write_bytes(review_dir / f"height_{wed}.png", _encode_png(render_height_review(result.height)))
            ctx.state.mark(key, digest, DEPTH_VERSION, 1, False, 1)
            elapsed = time.perf_counter() - started
            row = {
                "wed": wed,
                "residual": _fmt(result.residual),
                "wall_score": _fmt(result.wall_score),
                "seam_score": _fmt(result.seam_score),
                "unanchored": str(result.unanchored),
                "tiles": str(result.tiles),
                "seconds": f"{elapsed:.3f}",
                "model": model,
                "depth_input": str(depth_input),
                "held_count": str(result.held_count),
            }
            rows.append(row)
            print(
                f"depth {wed} {number}/{total} {elapsed:.1f}s residual={row['residual']} "
                f"wall={row['wall_score']} seam={row['seam_score']} unanch={result.unanchored} "
                f"tiles={result.tiles}",
                flush=True,
            )
            if result.unanchored:
                print(f"  {wed}: {result.unanchored} unanchored tiles left at h=0", flush=True)
            del area, result
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failed.append(wed)
            _log_error(errors, key, exc)
            print(f"depth {wed} {number}/{total} failed: {exc}", flush=True)
        existing_rows = [row for row in existing.values() if row.get("wed") not in {r["wed"] for r in rows}]
        all_rows = existing_rows + rows
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        with metrics_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
    write_manifest(ctx.out / "manifest.json", len(rows), failed, model, depth_input)
    _write_summary(ctx, rows, failed, model, depth_input)
    del processor, net
    return 1 if failed else 0


def _write_summary(ctx: common.RunContext, rows: list[dict], failed: list[str], model: str, depth_input: int) -> None:
    def nums(key: str) -> list[float]:
        out: list[float] = []
        for row in rows:
            try:
                value = float(row[key])
            except (TypeError, ValueError, KeyError):
                continue
            if np.isfinite(value):
                out.append(value)
        return out

    residuals = nums("residual")
    walls = nums("wall_score")
    seams = nums("seam_score")
    seam_ok = sum(1 for v in seams if v < 3.0)
    lines = [
        f"depth: {len(rows)} areas, {len(failed)} failed, version {DEPTH_VERSION}",
        f"model: {model}",
        f"depth_input: {depth_input}",
        f"median residual: {_fmt(float(np.median(residuals)) if residuals else float('nan'))} n={len(residuals)}",
        f"median wall: {_fmt(float(np.median(walls)) if walls else float('nan'))} n={len(walls)}",
        f"seam < 3 px: {seam_ok}/{len(seams)}" + (f" ({100.0 * seam_ok / len(seams):.1f}%)" if seams else ""),
    ]
    if failed:
        lines.append("failed: " + " ".join(failed))
    text = "\n".join(lines)
    atomic_write_bytes(ctx.work / "depth_summary.txt", (text + "\n").encode("utf-8"))
    print(text, flush=True)
