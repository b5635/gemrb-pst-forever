"""Run a 4x OpenModelDB network and Lanczos-shrink to the requested scale.

RGB and alpha go through the model separately. Fully transparent pixels are
filled from the nearest opaque colour first, so the network does not invent a
dark fringe. The alpha mask itself is not filled.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "out of memory" in text or ("cuda" in text and "memory" in text)


def _dilate_rgb(rgba: np.ndarray, radius: int = 6) -> np.ndarray:
    """Copy opaque RGB into fully transparent pixels. Alpha is left alone."""
    alpha = rgba[..., 3]
    opaque = alpha != 0
    if not np.any(opaque) or np.all(opaque):
        return rgba
    rgb = rgba[..., :3].copy()
    for _ in range(radius):
        grown = rgb
        mask = opaque
        changed = False
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            shifted = np.roll(rgb, (dy, dx), axis=(0, 1))
            shifted_mask = np.roll(opaque, (dy, dx), axis=(0, 1))
            if dy == 1:
                shifted_mask[0, :] = False
            elif dy == -1:
                shifted_mask[-1, :] = False
            if dx == 1:
                shifted_mask[:, 0] = False
            elif dx == -1:
                shifted_mask[:, -1] = False
            fill = ~mask & shifted_mask
            if not np.any(fill):
                continue
            grown = grown.copy()
            grown[fill] = shifted[fill]
            mask = mask | shifted_mask
            rgb = grown
            opaque = mask
            changed = True
        if not changed or np.all(opaque):
            break
    out = rgba.copy()
    out[..., :3] = rgb
    return out


def _lanczos(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    if arr.shape[1] == width and arr.shape[0] == height:
        return arr
    mode = "L" if arr.ndim == 2 else "RGB"
    image = Image.fromarray(arr, mode)
    return np.asarray(image.resize((width, height), Image.Resampling.LANCZOS))


def _starts(length: int, tile: int, overlap: int) -> list[int]:
    if length <= tile:
        return [0]
    step = max(1, tile - overlap)
    starts = []
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


class Upscaler:
    def __init__(self, model_path: str, scale: int, fp16: bool, tile: int, overlap: int = 32):
        import torch
        from spandrel import ModelLoader

        original_load = torch.load

        def guarded_load(*args, **kwargs):
            # spandrel passes RestrictedUnpickle. Any other load must not execute pickle code.
            if "pickle_module" not in kwargs:
                kwargs.setdefault("weights_only", True)
            return original_load(*args, **kwargs)

        torch.load = guarded_load
        try:
            model = ModelLoader().load_from_file(str(model_path))
        finally:
            torch.load = original_load

        self.torch = torch
        self.out_scale = int(scale)
        self.tile = int(tile)
        self.overlap = int(overlap)
        self.model_scale = int(getattr(model, "scale"))
        req = getattr(model, "size_requirements", None)
        if callable(req):
            req = req()
        self.multiple = int(getattr(req, "multiple_of", 1) or 1)
        self.minimum = int(getattr(req, "minimum", 0) or 0)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.set_grad_enabled(False)
        model = model.cuda().eval()
        self.fp16 = bool(fp16)
        if self.fp16:
            try:
                model = model.half()
            except Exception as exc:
                if "half" not in str(exc).lower() and "fp16" not in str(exc).lower():
                    raise
                print(f"fp16 is not supported by this model ({exc}); using fp32", flush=True)
                self.fp16 = False
        self.model = model
        self.dtype = torch.float16 if self.fp16 else torch.float32
        self.name = str(model_path)

    def upscale_rgba(self, rgba: np.ndarray, kind: str) -> np.ndarray:
        return self.upscale_many([rgba], kind)[0]

    def upscale_many(self, images: list[np.ndarray], kind: str) -> list[np.ndarray]:
        saved = self.tile
        try:
            while True:
                try:
                    return self._many(images, kind)
                except RuntimeError as exc:
                    if not _is_oom(exc) or self.tile <= 32:
                        raise
                    self.torch.cuda.empty_cache()
                    self.tile = max(32, self.tile // 2)
                    if self.tile < 64:
                        raise
        finally:
            self.tile = saved

    def _many(self, images: list[np.ndarray], kind: str) -> list[np.ndarray]:
        groups: dict[tuple, list[int]] = {}
        for i, img in enumerate(images):
            groups.setdefault(img.shape, []).append(i)
        out: list[np.ndarray | None] = [None] * len(images)
        for shape, idxs in groups.items():
            height, width = shape[:2]
            chosen = [images[i] for i in idxs]
            if height <= self.tile and width <= self.tile:
                done = self._batch_small(chosen, kind)
            else:
                done = [self._one(img, kind) for img in chosen]
            for i, img in zip(idxs, done):
                out[i] = img
        return out

    def _batch_small(self, images: list[np.ndarray], kind: str) -> list[np.ndarray]:
        colours = []
        alphas = []
        shadows = []
        for rgba in images:
            rgba = np.ascontiguousarray(rgba)
            height, width = rgba.shape[:2]
            shadow = None
            if kind == "bam-gui":
                mask = rgba[..., 3] == 128
                if np.any(mask):
                    shadow = _lanczos(mask.astype(np.uint8) * 255, width * self.out_scale, height * self.out_scale) >= 128
            shadows.append(shadow)
            colours.append(_dilate_rgb(rgba)[..., :3])
            alphas.append(np.repeat(rgba[..., 3:4], 3, axis=2))
        native_rgb = self._forward_budget(colours)
        native_alpha = self._forward_budget(alphas)
        done = []
        for rgb, alp, shadow, src in zip(native_rgb, native_alpha, shadows, images):
            height, width = src.shape[:2]
            rgb = _lanczos(rgb, width * self.out_scale, height * self.out_scale)
            alp = _lanczos(alp, width * self.out_scale, height * self.out_scale)
            done.append(_compose(rgb, alp.astype(np.float32).mean(axis=2), shadow, kind))
        return done

    def _forward_budget(self, images: list[np.ndarray]) -> list[np.ndarray]:
        if not images:
            return []
        height, width = images[0].shape[:2]
        step = max(1, 2_000_000 // max(height * width, 1))
        out = []
        for start in range(0, len(images), step):
            out.extend(self._forward(images[start : start + step]))
        return out

    def _one(self, rgba: np.ndarray, kind: str) -> np.ndarray:
        rgba = np.ascontiguousarray(rgba)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError(f"expected HxWx4, got {rgba.shape}")
        height, width = rgba.shape[:2]
        shadow = None
        if kind == "bam-gui":
            mask = rgba[..., 3] == 128
            if np.any(mask):
                shadow = _lanczos((mask.astype(np.uint8) * 255), width * self.out_scale, height * self.out_scale) >= 128
        filled = _dilate_rgb(rgba)
        rgb = self._upscale_channels(filled[..., :3])
        alpha = self._upscale_channels(np.repeat(rgba[..., 3:4], 3, axis=2))
        alpha = alpha.astype(np.float32).mean(axis=2)
        return _compose(rgb, alpha, shadow, kind)

    def _upscale_channels(self, rgb: np.ndarray) -> np.ndarray:
        height, width = rgb.shape[:2]
        out_h, out_w = height * self.out_scale, width * self.out_scale
        if height <= self.tile and width <= self.tile:
            native = self._forward([rgb])[0]
            return _lanczos(native, out_w, out_h)

        acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        weight = np.zeros((out_h, out_w), dtype=np.float32)
        ys = _starts(height, self.tile, self.overlap)
        xs = _starts(width, self.tile, self.overlap)
        for yi, y in enumerate(ys):
            th = min(self.tile, height - y)
            # overlap with the neighbour, in output pixels
            oy0 = 0 if yi == 0 else (ys[yi - 1] + min(self.tile, height - ys[yi - 1]) - y) * self.out_scale
            oy1 = 0 if yi + 1 == len(ys) else ((y + th) - ys[yi + 1]) * self.out_scale
            for xi, x in enumerate(xs):
                tw = min(self.tile, width - x)
                ox0 = 0 if xi == 0 else (xs[xi - 1] + min(self.tile, width - xs[xi - 1]) - x) * self.out_scale
                ox1 = 0 if xi + 1 == len(xs) else ((x + tw) - xs[xi + 1]) * self.out_scale
                native = self._forward([rgb[y : y + th, x : x + tw]])[0]
                chunk = _lanczos(native, tw * self.out_scale, th * self.out_scale).astype(np.float32)
                wy = _axis_weight(chunk.shape[0], oy0, oy1)
                wx = _axis_weight(chunk.shape[1], ox0, ox1)
                local = wy[:, None] * wx[None, :]
                y0 = y * self.out_scale
                x0 = x * self.out_scale
                y1 = y0 + chunk.shape[0]
                x1 = x0 + chunk.shape[1]
                acc[y0:y1, x0:x1] += chunk * local[..., None]
                weight[y0:y1, x0:x1] += local
        result = acc / np.maximum(weight[..., None], 1e-6)
        return np.clip(np.rint(result), 0, 255).astype(np.uint8)

    def _forward(self, batch: list[np.ndarray]) -> list[np.ndarray]:
        torch = self.torch
        arrays = []
        meta = []
        for rgb in batch:
            h, w = rgb.shape[:2]
            need_h = max(h, self.minimum)
            need_w = max(w, self.minimum)
            if self.multiple > 1:
                need_h = (need_h + self.multiple - 1) // self.multiple * self.multiple
                need_w = (need_w + self.multiple - 1) // self.multiple * self.multiple
            if need_h != h or need_w != w:
                padded = np.pad(rgb, ((0, need_h - h), (0, need_w - w), (0, 0)), mode="edge")
            else:
                padded = rgb
            arrays.append(padded)
            meta.append((h, w))
        # same spatial size in one launch; callers batch equal frames
        if any(a.shape != arrays[0].shape for a in arrays):
            out = []
            for one in batch:
                out.extend(self._forward([one]))
            return out
        stacked = np.stack(arrays, axis=0)
        ten = torch.from_numpy(np.ascontiguousarray(stacked))
        ten = ten.permute(0, 3, 1, 2).contiguous()
        ten = ten.to(device="cuda", dtype=self.dtype).div(255.0)
        try:
            with torch.inference_mode():
                pred = self.model(ten)
        except ValueError:
            if len(batch) == 1:
                raise
            out = []
            for one in batch:
                out.extend(self._forward([one]))
            return out
        pred = pred.float().mul(255.0).round().clamp(0, 255).to(dtype=torch.uint8)
        pred = pred.permute(0, 2, 3, 1).cpu().numpy()
        images = []
        for i, (h, w) in enumerate(meta):
            images.append(pred[i, : h * self.model_scale, : w * self.model_scale])
        return images


def _compose(rgb: np.ndarray, alpha: np.ndarray, shadow, kind: str) -> np.ndarray:
    values = np.clip(np.rint(alpha), 0, 255).astype(np.uint8)
    colour = rgb
    if kind == "bam-gui":
        values = np.where(values >= 128, 255, 0).astype(np.uint8)
        if shadow is not None:
            colour = rgb.copy()
            colour[shadow] = 0
            values = values.copy()
            values[shadow] = 128
    out = np.empty((values.shape[0], values.shape[1], 4), dtype=np.uint8)
    out[..., :3] = colour
    out[..., 3] = values
    return out
