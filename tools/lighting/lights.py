"""Light-source stage: emitters in the art plus tinted spots on the light map."""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import label

import common
from state import atomic_write_bytes, atomic_write_json

LIGHTS_VERSION = "lights-1"
LIGHTS_MODEL = ""
MAX_LIGHTS = 64

# Start values from LIGHTING_PLAN.md section 6.1. Tune and record in section 14.
V_MIN = 0.85
EXCESS_MIN = 0.12
S_COLOR_MIN = 0.25
V_WHITE = 0.97
CLOSE_RADIUS = 2
CORE_MIN = 6
CORE_MAX = 4000
CORE_MAX_WIDTH = 160
A8_MIN = 0.05
CHROMA_COS_MIN = 0.6
CORE_GREY_S = 0.15
SCORE_MIN = 0.035
MERGE_DIST = 64.0
ANIM_DX = 120.0
ANIM_DY_UP = 250.0
ANIM_DY_DOWN = 40.0
LM_FLAT_STD = 3.0 / 255.0
LM_CHROMA_MIN = 0.08
LM_HUE_MAX = 40.0
LM_NEIGHBOR = 3
LM_SPOT_MIN = 12
LM_SPOT_MAX = 400
FLOOR_SCAN = 200
FLOOR_FALLBACK = 60
SAT_MIX = 0.15

KIND_FIRE = "fire"
KIND_MAGIC = "magic"
KIND_STEADY = "steady"
KIND_POOL = "pool"


@dataclass
class Light:
    x: float
    y: float
    z: float
    radius: float
    r: float
    g: float
    b: float
    strength: float
    kind: str
    casts_shadow: int
    score: float
    source: str
    emitter: tuple[float, float]
    a8: float = 0.0
    r10: float = 0.0
    halo_profile: list[float] = field(default_factory=list)
    core_pixels: int = 0
    boost: float = 1.0


@dataclass
class LightsResult:
    lights: list[Light]
    tints: list[dict]
    area_w: int
    area_h: int


def _hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r = rgb[..., 0]
    g = rgb[..., 1]
    b = rgb[..., 2]
    v = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    s = (v - mn) / np.maximum(v, 1e-4)
    delta = np.maximum(v - mn, 1e-8)
    hue = np.zeros(v.shape, dtype=np.float32)
    is_r = v == r
    is_g = (v == g) & ~is_r
    is_b = ~is_r & ~is_g
    hue[is_r] = 60.0 * np.mod((g[is_r] - b[is_r]) / delta[is_r], 6.0)
    hue[is_g] = 60.0 * ((b[is_g] - r[is_g]) / delta[is_g] + 2.0)
    hue[is_b] = 60.0 * ((r[is_b] - g[is_b]) / delta[is_b] + 4.0)
    return v, s, hue


def _hue_mean(hues: np.ndarray, weights: np.ndarray | None = None) -> float:
    if hues.size == 0:
        return 0.0
    rad = np.deg2rad(hues.astype(np.float64))
    if weights is None:
        weights = np.ones(hues.shape, dtype=np.float64)
    else:
        weights = np.asarray(weights, dtype=np.float64)
    wsum = float(weights.sum())
    if wsum <= 1e-8:
        return float(hues.flat[0])
    s = float(np.sum(np.sin(rad) * weights) / wsum)
    c = float(np.sum(np.cos(rad) * weights) / wsum)
    return float((np.rad2deg(np.arctan2(s, c)) + 360.0) % 360.0)


def _hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _luma(rgb: np.ndarray) -> np.ndarray:
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def _masked_blur(src: np.ndarray, opaque: np.ndarray, sigma: float) -> np.ndarray:
    mask = opaque.astype(np.float32)
    den = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, borderType=cv2.BORDER_REPLICATE)
    den = np.maximum(den, 1e-6)
    if src.ndim == 2:
        num = cv2.GaussianBlur(src * mask, (0, 0), sigmaX=sigma, borderType=cv2.BORDER_REPLICATE)
        return num / den
    num = cv2.GaussianBlur(src * mask[..., None], (0, 0), sigmaX=sigma, borderType=cv2.BORDER_REPLICATE)
    return num / den[..., None]


def _normalize_max(color: np.ndarray) -> np.ndarray:
    color = np.maximum(np.asarray(color, dtype=np.float64), 0.0)
    peak = float(color.max()) if color.size else 0.0
    if peak <= 1e-8:
        return np.zeros(3, dtype=np.float64)
    return color / peak


def _limit_sat(color: np.ndarray, mix: float = SAT_MIX) -> np.ndarray:
    color = _normalize_max(color)
    peak = float(color.max()) if color.size else 0.0
    if peak <= 1e-8:
        return np.array([1.0, 1.0, 1.0], dtype=np.float64)
    return color * (1.0 - mix) + peak * mix


def _chroma_cos(a: np.ndarray, b: np.ndarray) -> float:
    ca = np.asarray(a, dtype=np.float64) - float(np.mean(a))
    cb = np.asarray(b, dtype=np.float64) - float(np.mean(b))
    na = float(np.linalg.norm(ca))
    nb = float(np.linalg.norm(cb))
    if na <= 1e-8 or nb <= 1e-8:
        return 0.0
    return float(np.dot(ca, cb) / (na * nb))


def _kind_from_color(color: np.ndarray) -> str:
    rgb = np.asarray(color, dtype=np.float32).reshape(1, 1, 3)
    _v, s, hue = _hsv(rgb)
    sat = float(s[0, 0])
    h = float(hue[0, 0])
    if sat < CORE_GREY_S:
        return KIND_STEADY
    if 0.0 <= h <= 60.0 and sat >= 0.3:
        return KIND_FIRE
    return KIND_MAGIC


def _disk(radius: int) -> np.ndarray:
    k = 2 * radius + 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _halo_stats(
    excess: np.ndarray,
    rgb: np.ndarray,
    rgb_far: np.ndarray,
    alpha: np.ndarray,
    core: np.ndarray,
    ex: float,
    ey: float,
) -> dict | None:
    height, width = excess.shape
    x0 = max(0, int(ex) - 160)
    x1 = min(width, int(ex) + 161)
    y0 = max(0, int(ey) - 160)
    y1 = min(height, int(ey) + 161)
    if x1 <= x0 or y1 <= y0:
        return None
    yy, xx = np.ogrid[y0:y1, x0:x1]
    dist = np.hypot(xx.astype(np.float32) - np.float32(ex), yy.astype(np.float32) - np.float32(ey))
    opaque = (alpha[y0:y1, x0:x1] == 255) & ~core[y0:y1, x0:x1]
    ring = opaque & (dist >= 4.0) & (dist < 160.0)
    if not np.any(ring):
        return None
    exs = excess[y0:y1, x0:x1]
    band8 = opaque & (dist >= 6.0) & (dist <= 10.0)
    if not np.any(band8):
        return None
    a8 = float(exs[band8].mean())
    if a8 < A8_MIN:
        return None

    idx = np.clip(np.floor(dist).astype(np.int32), 0, 160)
    ok = ring & (idx <= 160)
    counts = np.bincount(idx[ok].ravel(), minlength=161).astype(np.float64)
    sums = np.bincount(idx[ok].ravel(), weights=exs[ok].astype(np.float64).ravel(), minlength=161)
    means = np.zeros(161, dtype=np.float64)
    np.divide(sums, counts, out=means, where=counts > 0)

    profile: list[float] = []
    r10 = 160.0
    found = False
    for inner in range(4, 160, 2):
        n = counts[inner] + counts[inner + 1]
        if n > 0:
            val = (sums[inner] + sums[inner + 1]) / n
        else:
            val = 0.0
        profile.append(float(val))
        if not found and val < 0.1 * a8:
            r10 = float(inner)
            found = True

    halo_band = opaque & (dist >= 6.0) & (dist <= 40.0)
    if not np.any(halo_band):
        return None
    delta = rgb[y0:y1, x0:x1] - rgb_far[y0:y1, x0:x1]
    delta = np.maximum(delta, 0.0)
    halo_color = delta[halo_band].mean(axis=0)
    return {"a8": a8, "r10": r10, "profile": profile, "halo_color": halo_color}


def _lm_fields(lm: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float]:
    luma = _luma(lm)
    chroma = lm.max(axis=2) - lm.min(axis=2)
    _v, _s, hue = _hsv(lm)
    nonblack = luma >= 0.05
    std = float(luma.std()) if luma.size else 0.0
    if np.any(nonblack):
        lm_ref = float(np.quantile(luma[nonblack], 0.90))
    else:
        lm_ref = 1.0
    return luma, chroma, hue, nonblack, std, lm_ref


def _lm_boost(
    ex: float,
    ey: float,
    core_hue: float,
    luma: np.ndarray,
    chroma: np.ndarray,
    hue: np.ndarray,
    nonblack: np.ndarray,
    lm_std: float,
    lm_ref: float,
) -> float:
    if lm_std < LM_FLAT_STD:
        return 1.0
    gh, gw = luma.shape
    cx = int(ex) // common.CELL_W
    cy = int(ey) // common.CELL_H
    if cx < 0 or cy < 0 or cx >= gw or cy >= gh:
        return 1.0
    x0 = max(0, cx - LM_NEIGHBOR)
    x1 = min(gw, cx + LM_NEIGHBOR + 1)
    y0 = max(0, cy - LM_NEIGHBOR)
    y1 = min(gh, cy + LM_NEIGHBOR + 1)
    patch_luma = luma[y0:y1, x0:x1]
    patch_chroma = chroma[y0:y1, x0:x1]
    patch_hue = hue[y0:y1, x0:x1]
    patch_nb = nonblack[y0:y1, x0:x1]
    if not np.any(patch_nb):
        return 1.0
    delta = np.abs(patch_hue.astype(np.float64) - core_hue) % 360.0
    hue_ok = np.minimum(delta, 360.0 - delta) <= LM_HUE_MAX
    tinted = patch_nb & (patch_chroma >= LM_CHROMA_MIN) & (patch_luma >= 0.7 * lm_ref) & hue_ok
    if np.any(tinted):
        return 1.5
    if np.all((patch_luma < 0.6 * lm_ref) | ~patch_nb):
        return 0.6
    return 1.0


def _ground_from_floor(floor_mask: np.ndarray, ex: float, ey: float) -> tuple[float, float]:
    height, width = floor_mask.shape
    x = int(round(ex))
    y0 = int(round(ey))
    if 0 <= x < width:
        y1 = min(height, y0 + FLOOR_SCAN + 1)
        for y in range(max(0, y0), y1):
            if floor_mask[y, x]:
                return float(y), float(y) - ey
    return ey + float(FLOOR_FALLBACK), float(FLOOR_FALLBACK)


def _emitter_light(stats: dict, floor_mask: np.ndarray) -> Light:
    color = 0.5 * _normalize_max(stats["halo_color"]) + 0.5 * _normalize_max(stats["core_color"])
    color = _limit_sat(color)
    kind = _kind_from_color(stats["core_color"])
    radius = float(np.clip(1.6 * stats["r10"], 60.0, 400.0))
    strength = float(np.clip(stats["a8"] / 0.35, 0.15, 1.0))
    casts = 1 if kind in (KIND_FIRE, KIND_MAGIC) and strength >= 0.35 else 0
    gy, z = _ground_from_floor(floor_mask, stats["ex"], stats["ey"])
    return Light(
        x=float(stats["ex"]),
        y=float(gy),
        z=float(z),
        radius=radius,
        r=float(color[0]),
        g=float(color[1]),
        b=float(color[2]),
        strength=strength,
        kind=kind,
        casts_shadow=casts,
        score=float(stats["score"]),
        source="emitter",
        emitter=(float(stats["ex"]), float(stats["ey"])),
        a8=float(stats["a8"]),
        r10=float(stats["r10"]),
        halo_profile=[float(v) for v in stats["profile"]],
        core_pixels=int(stats["core_pixels"]),
        boost=float(stats["boost"]),
    )


def _merge_emitters(items: list[dict]) -> list[dict]:
    """Cluster emitters closer than MERGE_DIST and keep the highest score in each cluster.

    A chandelier or a field of speckles on one glow becomes one light. Two lamps
    farther apart than MERGE_DIST stay two. Position stays that of the winner.
    """
    n = len(items)
    if n <= 1:
        return items
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    xs = np.array([item["ex"] for item in items], dtype=np.float64)
    ys = np.array([item["ey"] for item in items], dtype=np.float64)
    for i in range(n):
        dx = xs[i + 1 :] - xs[i]
        dy = ys[i + 1 :] - ys[i]
        close = np.nonzero(dx * dx + dy * dy < MERGE_DIST * MERGE_DIST)[0]
        for off in close:
            j = i + 1 + int(off)
            ri, rj = find(i), find(j)
            if ri == rj:
                continue
            if items[ri]["score"] < items[rj]["score"]:
                ri, rj = rj, ri
            parent[rj] = ri
            items[ri]["core_pixels"] = int(items[ri]["core_pixels"] + items[rj]["core_pixels"])
    kept: list[dict] = []
    seen: set[int] = set()
    for i in range(n):
        root = find(i)
        if root in seen:
            continue
        seen.add(root)
        kept.append(items[root])
    kept.sort(key=lambda item: item["score"], reverse=True)
    return kept


def _drop_blendblack(items: list[dict], anims: list[tuple[int, int, str, int]]) -> list[dict]:
    fires = [(float(ax), float(ay)) for ax, ay, _bam, flags in anims if flags & common.PST_BLEND_BIT]
    if not fires:
        return items
    kept: list[dict] = []
    for item in items:
        ex, ey = item["ex"], item["ey"]
        drop = False
        for ax, ay in fires:
            if abs(ex - ax) <= ANIM_DX and (ay - ANIM_DY_UP) <= ey <= (ay + ANIM_DY_DOWN):
                drop = True
                break
        if not drop:
            kept.append(item)
    return kept


def _lm_spots(
    lm: np.ndarray,
    luma: np.ndarray,
    chroma: np.ndarray,
    nonblack: np.ndarray,
    lm_std: float,
    lm_ref: float,
    emitters: list[Light],
) -> tuple[list[Light], list[dict]]:
    tints: list[dict] = []
    spots: list[Light] = []
    if lm_std < LM_FLAT_STD or luma.size == 0:
        return spots, tints
    blurred = cv2.GaussianBlur(lm, (0, 0), sigmaX=1.0, borderType=cv2.BORDER_REPLICATE)
    b_luma = _luma(blurred)
    b_chroma = blurred.max(axis=2) - blurred.min(axis=2)
    mask = (b_chroma >= LM_CHROMA_MIN) & (b_luma >= 0.7 * lm_ref) & nonblack
    labeled, n = label(mask, structure=np.ones((3, 3), dtype=np.int32))
    if n == 0:
        return spots, tints
    for index in range(1, n + 1):
        cells = labeled == index
        count = int(cells.sum())
        ys, xs = np.nonzero(cells)
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        mean_color = lm[cells].mean(axis=0)
        if count > LM_SPOT_MAX:
            tints.append(
                {
                    "count": count,
                    "r": float(mean_color[0]),
                    "g": float(mean_color[1]),
                    "b": float(mean_color[2]),
                }
            )
            continue
        if count < LM_SPOT_MIN:
            continue
        gx0 = x0 - LM_NEIGHBOR
        gx1 = x1 + LM_NEIGHBOR
        gy0 = y0 - LM_NEIGHBOR
        gy1 = y1 + LM_NEIGHBOR
        covered = False
        for light in emitters:
            ecx = int(light.emitter[0]) // common.CELL_W
            ecy = int(light.emitter[1]) // common.CELL_H
            if gx0 <= ecx <= gx1 and gy0 <= ecy <= gy1:
                covered = True
                break
        if covered:
            continue
        cy = float(ys.mean())
        cx = float(xs.mean())
        x = cx * common.CELL_W + common.CELL_W / 2.0
        y = cy * common.CELL_H + common.CELL_H / 2.0
        radius = float(np.clip(1.2 * np.sqrt(count * common.CELL_W * common.CELL_H / np.pi) + 48.0, 80.0, 400.0))
        mean_chroma = float(chroma[cells].mean())
        strength = float(np.clip(mean_chroma / 0.25, 0.15, 1.0))
        color = _normalize_max(mean_color)
        spots.append(
            Light(
                x=float(x),
                y=float(y),
                z=120.0,
                radius=radius,
                r=float(color[0]),
                g=float(color[1]),
                b=float(color[2]),
                strength=strength,
                kind=KIND_POOL,
                casts_shadow=0,
                score=mean_chroma,
                source="pool",
                emitter=(float(x), float(y)),
                core_pixels=count,
            )
        )
    return spots, tints


def find_lights(area: common.Area) -> LightsResult:
    rgb = np.ascontiguousarray(area.rgb, dtype=np.float32)
    alpha = area.alpha
    height, width = rgb.shape[:2]
    opaque = alpha == 255
    v, s, hue = _hsv(rgb)
    lum = _luma(rgb).astype(np.float32)
    lbg = _masked_blur(lum, opaque, 24.0)
    lfar = _masked_blur(lum, opaque, 96.0)
    rgb_far = _masked_blur(rgb, opaque, 96.0)
    excess = lum - lfar

    hue_ok = ((hue <= 70.0) | ((hue >= 150.0) & (hue <= 330.0))) & (s >= S_COLOR_MIN)
    cand = opaque & (v >= V_MIN) & ((lum - lbg) >= EXCESS_MIN) & (hue_ok | (v >= V_WHITE))
    closed = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_CLOSE, _disk(CLOSE_RADIUS))
    labeled, n = label(closed, structure=np.ones((3, 3), dtype=np.int32))

    lm_luma, lm_chroma, lm_hue, lm_nonblack, lm_std, lm_ref = _lm_fields(area.lm)

    accepted: list[dict] = []
    for index in range(1, n + 1):
        core = labeled == index
        pixels = int(core.sum())
        if pixels < CORE_MIN or pixels > CORE_MAX:
            continue
        ys, xs = np.nonzero(core)
        if int(xs.max()) - int(xs.min()) + 1 > CORE_MAX_WIDTH:
            continue
        weights = lum[ys, xs]
        wsum = float(weights.sum())
        if wsum <= 1e-8:
            ey = float(ys.mean())
            ex = float(xs.mean())
        else:
            ey = float((ys * weights).sum() / wsum)
            ex = float((xs * weights).sum() / wsum)
        halo = _halo_stats(excess, rgb, rgb_far, alpha, core, ex, ey)
        if halo is None:
            continue
        core_color = rgb[ys, xs].mean(axis=0)
        core_s = float(_hsv(core_color.reshape(1, 1, 3))[1][0, 0])
        if core_s >= CORE_GREY_S and _chroma_cos(halo["halo_color"], core_color) < CHROMA_COS_MIN:
            continue
        mean_v = float(v[ys, xs].mean())
        score = mean_v * halo["a8"] * min(1.0, np.sqrt(pixels / 20.0))
        core_hue = _hue_mean(hue[ys, xs], weights)
        boost = _lm_boost(ex, ey, core_hue, lm_luma, lm_chroma, lm_hue, lm_nonblack, lm_std, lm_ref)
        score *= boost
        if score < SCORE_MIN:
            continue
        accepted.append(
            {
                "ex": ex,
                "ey": ey,
                "a8": halo["a8"],
                "r10": halo["r10"],
                "profile": halo["profile"],
                "halo_color": halo["halo_color"],
                "core_color": core_color,
                "core_pixels": pixels,
                "score": float(score),
                "boost": boost,
            }
        )

    accepted = _merge_emitters(accepted)
    accepted = _drop_blendblack(accepted, area.anims)
    emitters = [_emitter_light(item, area.floor_mask) for item in accepted]
    spots, tints = _lm_spots(area.lm, lm_luma, lm_chroma, lm_nonblack, lm_std, lm_ref, emitters)
    lights = emitters + spots
    lights.sort(key=lambda item: item.score, reverse=True)
    lights = lights[:MAX_LIGHTS]
    return LightsResult(lights=lights, tints=tints, area_w=width, area_h=height)


def format_lights_txt(result: LightsResult) -> str:
    lines = [
        "# GemRB baked scene lights",
        "version 1",
        f"size {result.area_w} {result.area_h}",
    ]
    for light in result.lights:
        lines.append(
            "light "
            f"{light.x:.4f} {light.y:.4f} {light.z:.4f} {light.radius:.4f} "
            f"{light.r:.4f} {light.g:.4f} {light.b:.4f} {light.strength:.4f} "
            f"{light.kind} {int(light.casts_shadow)}"
        )
    return "\n".join(lines) + "\n"


def lights_json(wed: str, result: LightsResult) -> dict:
    return {
        "version": 1,
        "wed": wed,
        "size": [result.area_w, result.area_h],
        "thresholds": {
            "v_min": V_MIN,
            "excess_min": EXCESS_MIN,
            "a8_min": A8_MIN,
            "score_min": SCORE_MIN,
            "chroma_cos_min": CHROMA_COS_MIN,
            "merge_dist": MERGE_DIST,
        },
        "lights": [
            {
                "x": light.x,
                "y": light.y,
                "z": light.z,
                "radius": light.radius,
                "r": light.r,
                "g": light.g,
                "b": light.b,
                "strength": light.strength,
                "kind": light.kind,
                "castsShadow": light.casts_shadow,
                "score": light.score,
                "source": light.source,
                "emitter": [light.emitter[0], light.emitter[1]],
                "halo": {"a8": light.a8, "r10": light.r10, "profile": light.halo_profile},
                "core_pixels": light.core_pixels,
                "boost": light.boost,
            }
            for light in result.lights
        ],
        "tints": result.tints,
    }


def result_from_json(payload: dict) -> LightsResult:
    lights: list[Light] = []
    for item in payload.get("lights", []):
        emitter = item.get("emitter") or [item.get("x", 0.0), item.get("y", 0.0)]
        halo = item.get("halo") or {}
        lights.append(
            Light(
                x=float(item["x"]),
                y=float(item["y"]),
                z=float(item["z"]),
                radius=float(item["radius"]),
                r=float(item["r"]),
                g=float(item["g"]),
                b=float(item["b"]),
                strength=float(item["strength"]),
                kind=str(item["kind"]),
                casts_shadow=int(item.get("castsShadow", 0)),
                score=float(item.get("score", 0.0)),
                source=str(item.get("source", "emitter")),
                emitter=(float(emitter[0]), float(emitter[1])),
                a8=float(halo.get("a8", 0.0)),
                r10=float(halo.get("r10", 0.0)),
                halo_profile=[float(v) for v in halo.get("profile", [])],
                core_pixels=int(item.get("core_pixels", 0)),
                boost=float(item.get("boost", 1.0)),
            )
        )
    size = payload.get("size") or [0, 0]
    return LightsResult(
        lights=lights,
        tints=list(payload.get("tints") or []),
        area_w=int(size[0]),
        area_h=int(size[1]),
    )


def _kind_letter(kind: str) -> str:
    return {"fire": "F", "magic": "M", "steady": "S", "pool": "P"}.get(kind, "?")


def render_review(rgb: np.ndarray, result: LightsResult, max_width: int = 1600) -> np.ndarray:
    height, width = rgb.shape[:2]
    scale = 1.0 if width <= max_width else max_width / float(width)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    bgr = cv2.cvtColor(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if (new_w, new_h) != (width, height):
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    for light in result.lights:
        color = (
            int(np.clip(light.b * 255.0, 0, 255)),
            int(np.clip(light.g * 255.0, 0, 255)),
            int(np.clip(light.r * 255.0, 0, 255)),
        )
        cx = int(round(light.emitter[0] * scale))
        cy = int(round(light.emitter[1] * scale))
        gx = int(round(light.x * scale))
        gy = int(round(light.y * scale))
        rad = max(4, int(round(light.radius * scale)))
        cv2.circle(bgr, (gx, gy), rad, color, 1, lineType=cv2.LINE_AA)
        cv2.drawMarker(bgr, (cx, cy), color, markerType=cv2.MARKER_CROSS, markerSize=12, thickness=1)
        cv2.circle(bgr, (gx, gy), 3, color, -1, lineType=cv2.LINE_AA)
        cv2.putText(
            bgr,
            _kind_letter(light.kind),
            (cx + 6, cy - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return bgr


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def write_review_image(path: Path, rgb: np.ndarray, result: LightsResult) -> None:
    atomic_write_bytes(path, _encode_png(render_review(rgb, result)))


def write_review_sheet(path: Path, cells: list[tuple[str, np.ndarray, LightsResult]], cell_width: int = 480) -> None:
    if not cells:
        return
    tiles: list[np.ndarray] = []
    for wed, rgb, result in cells:
        img = render_review(rgb, result, max_width=cell_width)
        caption_h = 28
        canvas = np.zeros((img.shape[0] + caption_h, img.shape[1], 3), dtype=np.uint8)
        canvas[caption_h:] = img
        label = f"{wed}  {len(result.lights)} lights"
        cv2.putText(canvas, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1, cv2.LINE_AA)
        tiles.append(canvas)
    rows = 2
    cols = 6
    while len(tiles) < rows * cols:
        tiles.append(np.zeros_like(tiles[0]))
    row_h = max(t.shape[0] for t in tiles)
    col_w = max(t.shape[1] for t in tiles)

    def pad(img: np.ndarray) -> np.ndarray:
        out = np.zeros((row_h, col_w, 3), dtype=np.uint8)
        out[: img.shape[0], : img.shape[1]] = img
        return out

    padded = [pad(t) for t in tiles[: rows * cols]]
    top = np.hstack(padded[:cols])
    bottom = np.hstack(padded[cols : cols * 2])
    atomic_write_bytes(path, _encode_png(np.vstack([top, bottom])))


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def write_manifest(path: Path, area_count: int, failed: list[str]) -> None:
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    stages["lights"] = {
        "version": LIGHTS_VERSION,
        "model": LIGHTS_MODEL,
        "areas": area_count,
        "failed": failed,
    }
    payload = {
        "version": 1,
        "area_count": max(int(current.get("area_count") or 0), area_count),
        "stages": stages,
    }
    atomic_write_json(path, payload)


def format_summary(rows: list[dict], failed: list[str]) -> str:
    lines: list[str] = []
    lines.append(f"lights: {len(rows)} areas, {len(failed)} failed, version {LIGHTS_VERSION}")
    if failed:
        lines.append("failed: " + ", ".join(failed))
    total = sum(int(row["n"]) for row in rows)
    kinds = {KIND_FIRE: 0, KIND_MAGIC: 0, KIND_STEADY: 0, KIND_POOL: 0}
    empty = [row["wed"] for row in rows if int(row["n"]) == 0]
    for row in rows:
        for kind, count in row["kinds"].items():
            kinds[kind] = kinds.get(kind, 0) + int(count)
    lines.append(f"total lights: {total}")
    lines.append(
        "by kind: "
        + ", ".join(f"{kind} {kinds.get(kind, 0)}" for kind in (KIND_FIRE, KIND_MAGIC, KIND_STEADY, KIND_POOL))
    )
    lines.append(f"areas with 0 lights: {len(empty)}")
    if empty:
        lines.append("  " + " ".join(empty[:40]) + (" ..." if len(empty) > 40 else ""))
    lines.append(
        "thresholds: "
        f"V_MIN={V_MIN} EXCESS_MIN={EXCESS_MIN} A8_MIN={A8_MIN} SCORE_MIN={SCORE_MIN} "
        f"CHROMA_COS_MIN={CHROMA_COS_MIN} MERGE_DIST={MERGE_DIST}"
    )
    if rows:
        richest = max(rows, key=lambda row: row["n"])
        lines.append(f"most lights: {richest['wed']} {richest['n']}")
    return "\n".join(lines)


def _kind_counts(result: LightsResult) -> dict[str, int]:
    counts = {KIND_FIRE: 0, KIND_MAGIC: 0, KIND_STEADY: 0, KIND_POOL: 0}
    for light in result.lights:
        counts[light.kind] = counts.get(light.kind, 0) + 1
    return counts


def _pick_sheet_weds(rows: list[dict]) -> list[str]:
    picked: list[str] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: -int(item["n"]))[:6]:
        picked.append(row["wed"])
        seen.add(row["wed"])
    for row in sorted(rows, key=lambda item: -int(item["blend"])):
        if row["wed"] in seen:
            continue
        picked.append(row["wed"])
        seen.add(row["wed"])
        if len(picked) >= 12:
            break
    if len(picked) < 12:
        for row in rows:
            if row["wed"] in seen:
                continue
            picked.append(row["wed"])
            seen.add(row["wed"])
            if len(picked) >= 12:
                break
    return picked[:12]


def run(ctx: common.RunContext) -> int:
    errors = ctx.work / "errors.log"
    review_dir = ctx.work / "review"
    rows: list[dict] = []
    failed: list[str] = []
    total = len(ctx.weds)
    for number, wed in enumerate(ctx.weds, start=1):
        key = f"lights:{wed}"
        started = time.perf_counter()
        try:
            if any(char in wed for char in "\\/:"):
                raise ValueError(f"bad WED name {wed!r}")
            digest = common.source_digest(common.source_parts(ctx.index, wed), LIGHTS_VERSION, LIGHTS_MODEL)
            out_dir = ctx.out / wed
            txt_path = out_dir / "lights.txt"
            json_path = out_dir / "lights.json"
            cached = (
                not ctx.force
                and not ctx.state.fresh(key, digest, LIGHTS_VERSION, 1, False)
                and txt_path.is_file()
                and json_path.is_file()
            )
            area = None
            if cached:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                result = result_from_json(payload)
                label = "cached"
            else:
                area = common.load_area(ctx.index, wed)
                result = find_lights(area)
                atomic_write_bytes(txt_path, format_lights_txt(result).encode("utf-8"))
                atomic_write_json(json_path, lights_json(wed, result))
                ctx.state.mark(key, digest, LIGHTS_VERSION, 1, False, 1)
                label = f"{time.perf_counter() - started:.1f}s"
            kinds = _kind_counts(result)
            blend = 0
            if area is None:
                grouped = common.areas_by_wed(ctx.index).get(wed, [])
                for _name, _data, anims in grouped:
                    blend += sum(1 for anim in anims if anim[3] & common.PST_BLEND_BIT)
            else:
                blend = sum(1 for anim in area.anims if anim[3] & common.PST_BLEND_BIT)
            if ctx.review:
                if area is None:
                    area = common.load_area(ctx.index, wed)
                write_review_image(review_dir / f"lights_{wed}.png", area.rgb, result)
            rows.append(
                {
                    "wed": wed,
                    "n": len(result.lights),
                    "kinds": kinds,
                    "blend": blend,
                    "seconds": time.perf_counter() - started,
                }
            )
            print(
                f"lights {wed} {number}/{total} {label} n={len(result.lights)} "
                f"fire={kinds[KIND_FIRE]} magic={kinds[KIND_MAGIC]} "
                f"steady={kinds[KIND_STEADY]} pool={kinds[KIND_POOL]} blend={blend}",
                flush=True,
            )
            del area
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failed.append(wed)
            _log_error(errors, key, exc)
            print(f"lights {wed} {number}/{total} failed: {exc}", flush=True)

    if ctx.review and rows:
        sheet_weds = _pick_sheet_weds(rows)
        cells: list[tuple[str, np.ndarray, LightsResult]] = []
        for wed in sheet_weds:
            json_path = ctx.out / wed / "lights.json"
            if not json_path.is_file():
                continue
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            result = result_from_json(payload)
            area = common.load_area(ctx.index, wed)
            cells.append((wed, area.rgb, result))
            del area
        write_review_sheet(review_dir / "lights_sheet.png", cells)

    text = format_summary(rows, failed)
    atomic_write_bytes(ctx.work / "lights_summary.txt", (text + "\n").encode("utf-8"))
    ctx.out.mkdir(parents=True, exist_ok=True)
    write_manifest(ctx.out / "manifest.json", len(rows), failed)
    print(text, flush=True)
    return 1 if failed else 0
