"""Normals, sprite AO and per-area key light. LIGHTING_PLAN.md section 8."""

from __future__ import annotations

import json
import os
import subprocess
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

import common
import depth
import lights
from state import atomic_write_bytes, atomic_write_json

SURFACE_VERSION = "surface-1"

HEIGHT_TEXEL = 2
NORMAL_UNIT = 1.0
AO_UNIT = 1.0

BLUR_SIGMA = 1.0
AO_DIRS = 16
AO_RANGE = 96.0
AO_HEIGHT = 30.0
AO_GAMMA = 0.7
AO_STEP = 4.0
AO_NEAR_TEXELS = 8
KEY_H_MIN = 6.0
KEY_L_MIN = 0.05
KEY_L_MAX = 0.9
KEY_NVAR_MAX = 0.05
KEY_HORIZ_MIN = 0.05
KEY_TINT_COVER = 0.30
KEY_TINT_MIX = 0.50
KEY_MIN_PIXELS = 64

REVIEW_ALWAYS = (
    "AR1000",
    "AR1001",
    "AR0500",
    "AR0400",
    "AR0202",
    "AR0105",
    "AR1601",
    "AR0306",
)


@dataclass
class KeyLight:
    dir_x: float
    dir_y: float
    strength: float
    amb_r: float
    amb_g: float
    amb_b: float


@dataclass
class SurfaceResult:
    normals: np.ndarray
    ao: np.ndarray
    key: KeyLight | None
    nw: int
    nh: int


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def _masked_blur(src: np.ndarray, region: np.ndarray, sigma: float) -> np.ndarray:
    mask = np.asarray(region, dtype=np.float32)
    den = cv2.GaussianBlur(mask, (0, 0), sigmaX=sigma, borderType=cv2.BORDER_REPLICATE)
    den = np.maximum(den, 1e-6)
    num = cv2.GaussianBlur(
        np.asarray(src, dtype=np.float32) * mask,
        (0, 0),
        sigmaX=sigma,
        borderType=cv2.BORDER_REPLICATE,
    )
    return num / den


def blur_height(h: np.ndarray, wall_mask: np.ndarray, sigma: float = BLUR_SIGMA) -> np.ndarray:
    """1 px gaussian, inside and outside wall_mask separately so edges do not mix."""
    walls = np.asarray(wall_mask, dtype=bool)
    inside = _masked_blur(h, walls, sigma)
    outside = _masked_blur(h, ~walls, sigma)
    return np.where(walls, inside, outside).astype(np.float32)


def downsample_normals(n: np.ndarray, texel: int = HEIGHT_TEXEL) -> np.ndarray:
    height, width = n.shape[:2]
    out_h = (height + texel - 1) // texel
    out_w = (width + texel - 1) // texel
    pad_y = out_h * texel - height
    pad_x = out_w * texel - width
    padded = np.pad(n, ((0, pad_y), (0, pad_x), (0, 0)), mode="edge")
    blocks = padded.reshape(out_h, texel, out_w, texel, 3)
    avg = blocks.mean(axis=(1, 3))
    length = np.linalg.norm(avg, axis=-1, keepdims=True)
    return (avg / np.maximum(length, 1e-8)).astype(np.float32)


def downsample_any(mask: np.ndarray, texel: int = HEIGHT_TEXEL) -> np.ndarray:
    height, width = mask.shape
    out_h = (height + texel - 1) // texel
    out_w = (width + texel - 1) // texel
    pad_y = out_h * texel - height
    pad_x = out_w * texel - width
    padded = np.pad(np.asarray(mask, dtype=np.uint8), ((0, pad_y), (0, pad_x)), mode="edge")
    blocks = padded.reshape(out_h, texel, out_w, texel)
    return blocks.max(axis=(1, 3)).astype(bool)


def encode_normals(n: np.ndarray) -> bytes:
    packed = np.clip(np.rint((n * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(packed).tobytes()


def encode_ao(ao: np.ndarray) -> bytes:
    packed = np.clip(np.rint(ao * 255.0), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(packed).tobytes()


def write_normal_bin(path: Path, n: np.ndarray) -> None:
    hh, ww = n.shape[:2]
    common.write_map(path, b"GLN1", ww, hh, HEIGHT_TEXEL, NORMAL_UNIT, encode_normals(n), 3)


def write_ao_bin(path: Path, ao: np.ndarray) -> None:
    hh, ww = ao.shape[:2]
    common.write_map(path, b"GLA1", ww, hh, HEIGHT_TEXEL, AO_UNIT, encode_ao(ao), 1)


def _luma(rgb: np.ndarray) -> np.ndarray:
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def _lm_ref(lm: np.ndarray) -> tuple[np.ndarray, float]:
    luma = _luma(lm).astype(np.float32)
    nonblack = luma >= 0.05
    if int(nonblack.sum()) == 0:
        return luma, 1.0
    return luma, float(np.quantile(luma[nonblack], 0.90))


def _lm_luma_half(lm: np.ndarray, hh: int, hw: int) -> np.ndarray:
    luma, _ref = _lm_ref(lm)
    gh, gw = luma.shape
    yy = np.clip((np.arange(hh) * HEIGHT_TEXEL + 1) // common.CELL_H, 0, max(0, gh - 1))
    xx = np.clip((np.arange(hw) * HEIGHT_TEXEL + 1) // common.CELL_W, 0, max(0, gw - 1))
    return luma[yy[:, None], xx[None, :]]


def compute_ao(h: np.ndarray, floor_mask: np.ndarray, lm: np.ndarray) -> np.ndarray:
    """Half-res sprite AO from a point 30 above the floor, 16 ground-plane rays."""
    near_full = downsample_any(floor_mask)
    if near_full.size:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (AO_NEAR_TEXELS * 2 + 1, AO_NEAR_TEXELS * 2 + 1)
        )
        near = cv2.dilate(near_full.astype(np.uint8), kernel).astype(bool)
    else:
        near = near_full
    hh, hw = near.shape
    ao = np.ones((hh, hw), dtype=np.float32)
    ys, xs = np.nonzero(near)
    if ys.size == 0:
        return ao
    H, W = h.shape
    px = xs.astype(np.float32) * np.float32(HEIGHT_TEXEL) + 1.0
    py = ys.astype(np.float32) * np.float32(HEIGHT_TEXEL) + 1.0
    distances = np.arange(AO_STEP, AO_RANGE + 0.01, AO_STEP, dtype=np.float32)
    acc = np.zeros(ys.shape[0], dtype=np.float32)
    h_img = np.asarray(h, dtype=np.float32)
    for index in range(AO_DIRS):
        ang = (2.0 * np.pi * index) / float(AO_DIRS)
        dx = float(np.cos(ang))
        dy = float(np.sin(ang)) * common.ELEV_SIN
        max_angle = np.full(ys.shape[0], -np.pi, dtype=np.float32)
        for dist in distances:
            sx = px + dx * dist
            sy = py + dy * dist
            outside = (sx < 0.0) | (sy < 0.0) | (sx >= float(W)) | (sy >= float(H))
            ix = np.clip(np.rint(sx).astype(np.int32), 0, W - 1)
            iy = np.clip(np.rint(sy).astype(np.int32), 0, H - 1)
            hs = h_img[iy, ix]
            hs = np.where(outside, 0.0, hs)
            np.maximum(max_angle, np.arctan2(hs - AO_HEIGHT, dist), out=max_angle)
        acc += np.maximum(np.sin(max_angle), 0.0)
    vals = np.clip(1.0 - acc / float(AO_DIRS), 0.0, 1.0)
    vals = np.power(vals, AO_GAMMA).astype(np.float32)
    ao[ys, xs] = vals
    _luma_map, lm_ref = _lm_ref(lm)
    del _luma_map
    factor = np.clip(_lm_luma_half(lm, hh, hw) / max(lm_ref, 1e-6), 0.0, 1.0)
    ao = 1.0 - (1.0 - ao) * factor
    return np.clip(ao, 0.0, 1.0).astype(np.float32)


def _normal_variance(n: np.ndarray) -> np.ndarray:
    """Per-pixel 3x3 neighbourhood variance of the normal (sum of channel vars)."""
    mean = cv2.blur(n, (3, 3))
    mean2 = cv2.blur(n * n, (3, 3))
    var = np.maximum(mean2 - mean * mean, 0.0)
    return var.sum(axis=-1).astype(np.float32)


def _exclude_lights(shape: tuple[int, int], result: lights.LightsResult, scale: float) -> np.ndarray:
    """True where a pixel is inside scale * radius of any baked light ground point."""
    mask = np.zeros(shape, dtype=np.uint8)
    for light in result.lights:
        rad = int(round(scale * float(light.radius)))
        if rad <= 0:
            continue
        cv2.circle(mask, (int(round(light.x)), int(round(light.y))), rad, 1, -1, lineType=cv2.LINE_8)
    return mask.astype(bool)


def _normalize_luma(rgb: np.ndarray) -> np.ndarray:
    color = np.asarray(rgb, dtype=np.float64).reshape(-1)
    if color.size != 3:
        color = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    luma = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    if luma <= 1e-6:
        return np.array([1.0, 1.0, 1.0], dtype=np.float64)
    return color / luma


def mix_ambient_tints(amb: np.ndarray, tints: list[dict], lm: np.ndarray) -> np.ndarray:
    luma = _luma(lm)
    nonblack = int((luma >= 0.05).sum())
    tint_cells = int(sum(int(item.get("count") or 0) for item in tints))
    if nonblack <= 0 or tint_cells <= 0:
        return amb
    if (tint_cells / float(nonblack)) <= KEY_TINT_COVER:
        return amb
    weight = 0.0
    acc = np.zeros(3, dtype=np.float64)
    for item in tints:
        count = float(item.get("count") or 0)
        if count <= 0:
            continue
        acc += count * np.array(
            [float(item.get("r") or 0.0), float(item.get("g") or 0.0), float(item.get("b") or 0.0)],
            dtype=np.float64,
        )
        weight += count
    if weight <= 0:
        return amb
    tint = _normalize_luma(acc / weight)
    mixed = (1.0 - KEY_TINT_MIX) * amb + KEY_TINT_MIX * tint
    return _normalize_luma(mixed)


def compute_key(
    rgb: np.ndarray,
    alpha: np.ndarray,
    h: np.ndarray,
    n_full: np.ndarray,
    floor_mask: np.ndarray,
    lm: np.ndarray,
    result: lights.LightsResult,
) -> KeyLight | None:
    L = _luma(rgb)
    nvar = _normal_variance(n_full)
    near_half = _exclude_lights(h.shape, result, 0.5)
    near_full = _exclude_lights(h.shape, result, 1.0)
    used = (
        (h > KEY_H_MIN)
        & (alpha == 255)
        & (L > KEY_L_MIN)
        & (L < KEY_L_MAX)
        & (nvar < KEY_NVAR_MAX)
        & ~near_half
    )
    key: KeyLight | None = None
    ys, xs = np.nonzero(used)
    if ys.size >= KEY_MIN_PIXELS:
        samples = np.column_stack(
            [
                np.ones(ys.shape[0], dtype=np.float64),
                n_full[ys, xs, 0].astype(np.float64),
                n_full[ys, xs, 1].astype(np.float64),
                n_full[ys, xs, 2].astype(np.float64),
            ]
        )
        target = L[ys, xs].astype(np.float64)
        beta, *_ = np.linalg.lstsq(samples, target, rcond=None)
        c0, c1, c2, c3 = (float(beta[0]), float(beta[1]), float(beta[2]), float(beta[3]))
        horiz = float(np.hypot(c1, c2))
        if c0 > 1e-6 and (horiz / c0) >= KEY_HORIZ_MIN:
            key = KeyLight(
                dir_x=-c1 / horiz,
                dir_y=-c2 / horiz,
                strength=float(np.clip(np.linalg.norm([c1, c2, c3]) / c0, 0.0, 1.0)),
                amb_r=1.0,
                amb_g=1.0,
                amb_b=1.0,
            )

    far = floor_mask & ~near_full & (alpha == 255)
    if not np.any(far):
        far = floor_mask & (alpha == 255)
    if np.any(far):
        med = np.median(rgb[far], axis=0)
    else:
        med = np.array([1.0, 1.0, 1.0], dtype=np.float64)
    amb = mix_ambient_tints(_normalize_luma(med), result.tints or [], lm)
    if key is None:
        return None
    key.amb_r, key.amb_g, key.amb_b = float(amb[0]), float(amb[1]), float(amb[2])
    return key


def process_surface(area: common.Area, h: np.ndarray, result: lights.LightsResult) -> SurfaceResult:
    h_blur = blur_height(h, area.wall_mask)
    n_full = depth.height_to_normals(h_blur)
    n_half = downsample_normals(n_full)
    ao = compute_ao(h, area.floor_mask, area.lm)
    key = compute_key(area.rgb, area.alpha, h, n_full, area.floor_mask, area.lm, result)
    return SurfaceResult(normals=n_half, ao=ao, key=key, nw=n_half.shape[1], nh=n_half.shape[0])


def key_line(key: KeyLight) -> str:
    return (
        "key "
        f"{key.dir_x:.4f} {key.dir_y:.4f} {key.strength:.4f} "
        f"{key.amb_r:.4f} {key.amb_g:.4f} {key.amb_b:.4f}"
    )


def apply_key(result: lights.LightsResult, key: KeyLight | None) -> None:
    if key is None:
        result.key = None
        return
    result.key = (key.dir_x, key.dir_y, key.strength, key.amb_r, key.amb_g, key.amb_b)


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def _down_bgr(rgb: np.ndarray, max_width: int) -> tuple[np.ndarray, float]:
    height, width = rgb.shape[:2]
    scale = 1.0 if width <= max_width else max_width / float(width)
    new_w = max(1, int(round(width * scale)))
    new_h = max(1, int(round(height * scale)))
    bgr = cv2.cvtColor(np.clip(rgb * 255.0, 0, 255).astype(np.uint8), cv2.COLOR_RGB2BGR)
    if (new_w, new_h) != (width, height):
        bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return bgr, scale


def render_normal_review(rgb: np.ndarray, n_half: np.ndarray, max_width: int = 800) -> np.ndarray:
    packed = np.clip(n_half * 0.5 + 0.5, 0.0, 1.0)
    vis = cv2.cvtColor((packed * 255.0).astype(np.uint8), cv2.COLOR_RGB2BGR)
    orig, _scale = _down_bgr(rgb, max_width)
    vis = cv2.resize(vis, (orig.shape[1], orig.shape[0]), interpolation=cv2.INTER_AREA)
    gap = np.zeros((orig.shape[0], 8, 3), dtype=np.uint8)
    return np.hstack([orig, gap, vis])


def render_ao_review(ao: np.ndarray, max_width: int = 1600) -> np.ndarray:
    vis = np.clip(ao * 255.0, 0, 255).astype(np.uint8)
    color = cv2.applyColorMap(vis, cv2.COLORMAP_BONE)
    height, width = color.shape[:2]
    if width > max_width:
        new_h = max(1, int(round(height * max_width / float(width))))
        color = cv2.resize(color, (max_width, new_h), interpolation=cv2.INTER_AREA)
    return color


def draw_key_arrow(bgr: np.ndarray, key: KeyLight, scale: float) -> np.ndarray:
    """Arrow in screen space: engine y is toward the camera (down-screen)."""
    out = bgr.copy()
    h, w = out.shape[:2]
    cx, cy = w // 2, h // 2
    length = max(40.0, min(w, h) * 0.18)
    # dir is a ground vector; draw it in area pixels (x right, y down).
    ex = int(round(cx + key.dir_x * length))
    ey = int(round(cy + key.dir_y * length))
    color = (0, 220, 255)
    cv2.arrowedLine(out, (cx, cy), (ex, ey), color, 3, line_type=cv2.LINE_AA, tipLength=0.18)
    label = f"key {key.dir_x:.2f},{key.dir_y:.2f} s={key.strength:.2f}"
    cv2.putText(out, label, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    _ = scale
    return out


def write_review(
    review_dir: Path,
    wed: str,
    rgb: np.ndarray,
    result: lights.LightsResult,
    surface: SurfaceResult,
) -> None:
    review_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(review_dir / f"normal_{wed}.png", _encode_png(render_normal_review(rgb, surface.normals)))
    atomic_write_bytes(review_dir / f"ao_{wed}.png", _encode_png(render_ao_review(surface.ao)))
    lights_img = lights.render_review(rgb, result)
    if surface.key is not None:
        height, width = rgb.shape[:2]
        scale = 1.0 if width <= 1600 else 1600.0 / float(width)
        lights_img = draw_key_arrow(lights_img, surface.key, scale)
    atomic_write_bytes(review_dir / f"lights_{wed}.png", _encode_png(lights_img))


def hcache_paths(work: Path, wed: str) -> tuple[Path, Path]:
    folder = work / "hcache"
    return folder / f"{wed}.npy", folder / f"{wed}.json"


def save_hcache(work: Path, wed: str, h: np.ndarray, model: str, depth_input: int) -> None:
    npy_path, meta_path = hcache_paths(work, wed)
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = npy_path.with_name(npy_path.name + ".tmp")
    with tmp.open("wb") as handle:
        np.save(handle, np.ascontiguousarray(h, dtype=np.float32))
    os.replace(tmp, npy_path)
    atomic_write_json(
        meta_path,
        {
            "wed": wed,
            "model": model,
            "depth_input": depth_input,
            "version": depth.DEPTH_VERSION,
            "shape": [int(h.shape[0]), int(h.shape[1])],
        },
    )


def load_hcache(work: Path, wed: str, shape: tuple[int, int], model: str, depth_input: int) -> np.ndarray | None:
    npy_path, meta_path = hcache_paths(work, wed)
    if not npy_path.is_file():
        return None
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        if (
            str(meta.get("model") or "") != model
            or int(meta.get("depth_input") or 0) != int(depth_input)
            or str(meta.get("version") or "") != depth.DEPTH_VERSION
        ):
            return None
    try:
        with npy_path.open("rb") as handle:
            h = np.load(handle)
    except (OSError, ValueError):
        return None
    if tuple(h.shape) != tuple(shape):
        return None
    return np.ascontiguousarray(h, dtype=np.float32)


def _gpu_report() -> None:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total",
                "--format=csv,noheader",
            ],
            text=True,
            timeout=15,
        )
        print("gpu: " + out.strip(), flush=True)
    except Exception as exc:
        print(f"nvidia-smi failed: {exc}", flush=True)


def _resolved_model(ctx: common.RunContext) -> tuple[str, int]:
    return depth._resolved_model(ctx)


def write_manifest(path: Path, area_count: int, failed: list[str], keys: int, model: str) -> None:
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    stages["surface"] = {
        "version": SURFACE_VERSION,
        "model": model,
        "areas": area_count,
        "failed": failed,
        "key_lines": keys,
    }
    payload = {
        "version": 1,
        "area_count": max(int(current.get("area_count") or 0), area_count),
        "stages": stages,
    }
    atomic_write_json(path, payload)


def _want_review(ctx: common.RunContext, wed: str) -> bool:
    return bool(ctx.review) or wed in REVIEW_ALWAYS


class _DepthNet:
    def __init__(self) -> None:
        self.processor = None
        self.model = None
        self.torch_mod = None
        self.loaded = False

    def load(self, name: str) -> None:
        if self.loaded:
            return
        _gpu_report()
        self.processor, self.model, self.torch_mod = depth.load_depth_model(name)
        self.loaded = True


def _full_h(
    ctx: common.RunContext,
    area: common.Area,
    wed: str,
    model: str,
    depth_input: int,
    net: _DepthNet,
) -> np.ndarray:
    cached = load_hcache(ctx.work, wed, area.rgb.shape[:2], model, depth_input)
    if cached is not None:
        return cached
    net.load(model)
    result = depth.process_area(area, net.processor, net.model, net.torch_mod, depth_input)
    h = result.height
    save_hcache(ctx.work, wed, h, model, depth_input)
    parts = common.source_parts(ctx.index, wed)
    depth_digest = common.source_digest(parts, depth.DEPTH_VERSION, depth.model_tag(model, depth_input))
    height_path = ctx.out / wed / "height.bin"
    stale = (not height_path.is_file()) or ctx.state.fresh(
        f"depth:{wed}", depth_digest, depth.DEPTH_VERSION, 1, False
    )
    if stale:
        depth.write_height_bin(height_path, h)
        print(f"  {wed}: rewrote height.bin (digest stale or missing)", flush=True)
    return h


def run(ctx: common.RunContext) -> int:
    errors = ctx.work / "errors.log"
    review_dir = ctx.work / "review"
    failed: list[str] = []
    rows: list[dict] = []
    total = len(ctx.weds)
    model, depth_input = _resolved_model(ctx)
    model_tag = depth.model_tag(model, depth_input)
    net = _DepthNet()
    print(f"surface model={model} input={depth_input}", flush=True)
    for number, wed in enumerate(ctx.weds, start=1):
        key = f"surface:{wed}"
        started = time.perf_counter()
        try:
            if any(char in wed for char in "\\/:"):
                raise ValueError(f"bad WED name {wed!r}")
            digest = common.source_digest(common.source_parts(ctx.index, wed), SURFACE_VERSION, model_tag)
            out_dir = ctx.out / wed
            normal_path = out_dir / "normal.bin"
            ao_path = out_dir / "ao.bin"
            cached = (
                not ctx.force
                and not ctx.state.fresh(key, digest, SURFACE_VERSION, 1, False)
                and normal_path.is_file()
                and ao_path.is_file()
            )
            area = None
            result = None
            surface = None
            if cached:
                payload_path = out_dir / "lights.json"
                if payload_path.is_file():
                    result = lights.result_from_json(json.loads(payload_path.read_text(encoding="utf-8")))
                label = "cached"
                has_key = result is not None and result.key is not None
                if _want_review(ctx, wed):
                    area = common.load_area(ctx.index, wed)
                    header_n, payload_n = common.read_map(normal_path.read_bytes(), b"GLN1", 3)
                    header_a, payload_a = common.read_map(ao_path.read_bytes(), b"GLA1", 1)
                    n_img = np.frombuffer(payload_n, dtype=np.uint8).reshape(header_n.h, header_n.w, 3)
                    n_half = (n_img.astype(np.float32) / 255.0) * 2.0 - 1.0
                    ao_img = np.frombuffer(payload_a, dtype=np.uint8).reshape(header_a.h, header_a.w)
                    ao = ao_img.astype(np.float32) / 255.0
                    key_obj = None
                    if result is not None and result.key is not None:
                        key_obj = KeyLight(*result.key)
                    surface = SurfaceResult(normals=n_half, ao=ao, key=key_obj, nw=header_n.w, nh=header_n.h)
                    if result is None:
                        result = lights.LightsResult(lights=[], tints=[], area_w=area.rgb.shape[1], area_h=area.rgb.shape[0])
                    write_review(review_dir, wed, area.rgb, result, surface)
            else:
                area = common.load_area(ctx.index, wed)
                json_path = out_dir / "lights.json"
                if json_path.is_file():
                    result = lights.result_from_json(json.loads(json_path.read_text(encoding="utf-8")))
                else:
                    result = lights.LightsResult(
                        lights=[], tints=[], area_w=area.rgb.shape[1], area_h=area.rgb.shape[0]
                    )
                h = _full_h(ctx, area, wed, model, depth_input, net)
                surface = process_surface(area, h, result)
                write_normal_bin(normal_path, surface.normals)
                write_ao_bin(ao_path, surface.ao)
                apply_key(result, surface.key)
                txt_path = out_dir / "lights.txt"
                atomic_write_bytes(txt_path, lights.format_lights_txt(result).encode("utf-8"))
                atomic_write_json(json_path, lights.lights_json(wed, result))
                ctx.state.mark(key, digest, SURFACE_VERSION, 1, False, 1)
                label = f"{time.perf_counter() - started:.1f}s"
                has_key = surface.key is not None
                if _want_review(ctx, wed):
                    write_review(review_dir, wed, area.rgb, result, surface)
                del h
            elapsed = time.perf_counter() - started
            rows.append({"wed": wed, "key": int(bool(has_key)), "seconds": elapsed})
            print(
                f"surface {wed} {number}/{total} {label} key={int(bool(has_key))} "
                f"n={surface.nw if surface else '?'}x{surface.nh if surface else '?'}",
                flush=True,
            )
            del area, result, surface
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failed.append(wed)
            _log_error(errors, key, exc)
            print(f"surface {wed} {number}/{total} failed: {exc}", flush=True)

    key_count = sum(int(row["key"]) for row in rows)
    text = (
        f"surface: {len(rows)} areas, {len(failed)} failed, version {SURFACE_VERSION}\n"
        f"key lines: {key_count}/{len(rows)}\n"
        f"model: {model}\n"
        f"depth_input: {depth_input}"
    )
    if failed:
        text += "\nfailed: " + " ".join(failed)
    atomic_write_bytes(ctx.work / "surface_summary.txt", (text + "\n").encode("utf-8"))
    ctx.out.mkdir(parents=True, exist_ok=True)
    write_manifest(ctx.out / "manifest.json", len(rows), failed, key_count, model)
    print(text, flush=True)
    return 1 if failed else 0
