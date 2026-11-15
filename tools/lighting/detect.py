"""Open-vocabulary light labels. LIGHTING_PLAN.md section 10."""

from __future__ import annotations

import json
import os
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import common
from state import atomic_write_bytes, atomic_write_json

HF_HOME = Path(__file__).resolve().parent.parent / "upscale" / "models" / "hf"
os.environ.setdefault("HF_HOME", str(HF_HOME))

DETECT_VERSION = "detect-1"
DETECT_MODEL = "google/owlv2-base-patch16-ensemble"

TILE_SIZE = 960
OVERLAP = 128
SCORE_MIN = 0.12
NMS_IOU = 0.5
# Tune: 0.12 keeps map-sized "lava"/"portal" regions that steal kinds.
# Fixtures in the prompt table fit in a 192 px square; drop the rest.
BOX_MAX_SIDE = 192

# Prompts and the kind each maps to (plan 10.2 table). Order is the detector class index.
PROMPTS: tuple[str, ...] = (
    "a burning torch",
    "a candle flame",
    "a brazier with fire",
    "a campfire",
    "a fireplace",
    "lava",
    "a glowing lantern",
    "a lamp",
    "a glowing magical crystal",
    "a glowing portal",
    "glowing runes",
    "a glowing window",
)

PROMPT_KIND: dict[str, str] = {
    "a burning torch": "fire",
    "a candle flame": "fire",
    "a brazier with fire": "fire",
    "a campfire": "fire",
    "a fireplace": "fire",
    "lava": "fire",
    "a glowing lantern": "steady",
    "a lamp": "steady",
    "a glowing magical crystal": "magic",
    "a glowing portal": "magic",
    "glowing runes": "magic",
    "a glowing window": "pool",
}

PROMPT_SHORT: dict[str, str] = {
    "a burning torch": "torch",
    "a candle flame": "candle",
    "a brazier with fire": "brazier",
    "a campfire": "campfire",
    "a fireplace": "fireplace",
    "lava": "lava",
    "a glowing lantern": "lantern",
    "a lamp": "lamp",
    "a glowing magical crystal": "crystal",
    "a glowing portal": "portal",
    "glowing runes": "runes",
    "a glowing window": "window",
}

KIND_BGR: dict[str, tuple[int, int, int]] = {
    "fire": (40, 90, 255),
    "steady": (220, 210, 60),
    "magic": (220, 60, 220),
    "pool": (80, 200, 80),
}


@dataclass
class DetectBox:
    x0: float
    y0: float
    x1: float
    y1: float
    score: float
    prompt: str
    kind: str

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def as_dict(self) -> dict:
        return {
            "x0": float(self.x0),
            "y0": float(self.y0),
            "x1": float(self.x1),
            "y1": float(self.y1),
            "score": float(self.score),
            "prompt": self.prompt,
            "kind": self.kind,
        }


def kind_for_prompt(prompt: str) -> str:
    kind = PROMPT_KIND.get(prompt)
    if kind is None:
        raise KeyError(f"unknown detect prompt {prompt!r}")
    return kind


def box_iou(a: DetectBox, b: DetectBox) -> float:
    ix0 = max(a.x0, b.x0)
    iy0 = max(a.y0, b.y0)
    ix1 = min(a.x1, b.x1)
    iy1 = min(a.y1, b.y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = a.width * a.height + b.width * b.height - inter
    if union <= 1e-8:
        return 0.0
    return inter / union


def nms_classwise(boxes: list[DetectBox], iou: float = NMS_IOU) -> list[DetectBox]:
    """Keep the highest-score box of each prompt class when IoU is at least `iou`."""
    groups: dict[str, list[DetectBox]] = defaultdict(list)
    for box in boxes:
        groups[box.prompt].append(box)
    kept: list[DetectBox] = []
    for group in groups.values():
        remaining = sorted(group, key=lambda item: item.score, reverse=True)
        chosen: list[DetectBox] = []
        while remaining:
            best = remaining.pop(0)
            chosen.append(best)
            remaining = [item for item in remaining if box_iou(best, item) < iou]
        kept.extend(chosen)
    kept.sort(key=lambda item: item.score, reverse=True)
    return kept


def contains(box: DetectBox, x: float, y: float) -> bool:
    return box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1


def best_box_at(boxes: list[DetectBox], x: float, y: float) -> DetectBox | None:
    """Highest-score containing box. Size-filter runs before this so regions are gone."""
    hit = [box for box in boxes if contains(box, x, y)]
    if not hit:
        return None
    return max(hit, key=lambda box: box.score)


def fire_or_magic_at(boxes: list[DetectBox], x: float, y: float) -> bool:
    for box in boxes:
        if box.kind in ("fire", "magic") and contains(box, x, y):
            return True
    return False


def small_enough(box: DetectBox, max_side: float = BOX_MAX_SIDE) -> bool:
    return box.width <= max_side and box.height <= max_side


def clip_box(box: DetectBox, width: int, height: int) -> DetectBox | None:
    x0 = float(np.clip(box.x0, 0.0, width))
    y0 = float(np.clip(box.y0, 0.0, height))
    x1 = float(np.clip(box.x1, 0.0, width))
    y1 = float(np.clip(box.y1, 0.0, height))
    if x1 - x0 < 1.0 or y1 - y0 < 1.0:
        return None
    return DetectBox(x0, y0, x1, y1, box.score, box.prompt, box.kind)


def boxes_from_json(payload: dict) -> list[DetectBox]:
    boxes: list[DetectBox] = []
    for item in payload.get("boxes") or []:
        prompt = str(item["prompt"])
        boxes.append(
            DetectBox(
                x0=float(item["x0"]),
                y0=float(item["y0"]),
                x1=float(item["x1"]),
                y1=float(item["y1"]),
                score=float(item["score"]),
                prompt=prompt,
                kind=str(item.get("kind") or kind_for_prompt(prompt)),
            )
        )
    return boxes


def load_boxes(path: Path) -> list[DetectBox]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return boxes_from_json(payload)


def boxes_payload(wed: str, width: int, height: int, boxes: list[DetectBox], threshold: float) -> dict:
    return {
        "version": 1,
        "wed": wed,
        "size": [int(width), int(height)],
        "model": DETECT_MODEL,
        "threshold": float(threshold),
        "nms_iou": NMS_IOU,
        "tile": TILE_SIZE,
        "overlap": OVERLAP,
        "boxes": [box.as_dict() for box in boxes],
    }


def tile_starts(length: int, tile: int = TILE_SIZE, overlap: int = OVERLAP) -> list[int]:
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


def extract_tile(rgb: np.ndarray, x0: int, y0: int, tile: int = TILE_SIZE) -> tuple[np.ndarray, int, int]:
    """960 x 960 tile, edge-replicated at the image border. Returns (tile, valid_w, valid_h)."""
    height, width = rgb.shape[:2]
    vw = max(0, min(tile, width - x0))
    vh = max(0, min(tile, height - y0))
    crop = rgb[max(0, y0) : max(0, y0) + vh, max(0, x0) : max(0, x0) + vw]
    if crop.size == 0:
        padded = np.zeros((tile, tile, 3), dtype=np.float32)
        return padded, 0, 0
    if vw == tile and vh == tile:
        return np.ascontiguousarray(crop, dtype=np.float32), vw, vh
    pad_x = tile - vw
    pad_y = tile - vh
    padded = np.pad(crop, ((0, pad_y), (0, pad_x), (0, 0)), mode="edge")
    return np.ascontiguousarray(padded, dtype=np.float32), vw, vh


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def draw_boxes(bgr: np.ndarray, boxes: list[DetectBox], scale: float) -> None:
    """Draw labelled boxes onto a BGR review image in place."""
    for box in boxes:
        color = KIND_BGR.get(box.kind, (200, 200, 200))
        x0 = int(round(box.x0 * scale))
        y0 = int(round(box.y0 * scale))
        x1 = int(round(box.x1 * scale))
        y1 = int(round(box.y1 * scale))
        cv2.rectangle(bgr, (x0, y0), (x1, y1), color, 1, lineType=cv2.LINE_AA)
        label = f"{PROMPT_SHORT.get(box.prompt, box.kind)} {box.score:.2f}"
        ty = max(12, y0 - 4)
        cv2.putText(bgr, label, (x0, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)


def load_model(name: str = DETECT_MODEL):
    """Owlv2Processor + Owlv2ForObjectDetection, CUDA eval, fp16 if it works, safetensors."""
    import torch
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    HF_HOME.mkdir(parents=True, exist_ok=True)
    processor = Owlv2Processor.from_pretrained(name)
    fp16 = True
    try:
        model = Owlv2ForObjectDetection.from_pretrained(
            name, use_safetensors=True, torch_dtype=torch.float16
        )
        model = model.cuda().eval()
    except Exception:
        fp16 = False
        model = Owlv2ForObjectDetection.from_pretrained(name, use_safetensors=True)
        model = model.cuda().eval()
    return processor, model, torch, fp16


def infer_tile(
    tile_rgb: np.ndarray,
    processor,
    model,
    torch_mod,
    fp16: bool,
    threshold: float = SCORE_MIN,
) -> list[DetectBox]:
    """Boxes in tile-pixel coordinates, already filtered by `threshold`."""
    rgb8 = np.clip(tile_rgb * 255.0, 0, 255).astype(np.uint8)
    image = Image.fromarray(rgb8, mode="RGB")
    texts = [list(PROMPTS)]
    inputs = processor(text=texts, images=image, return_tensors="pt")
    inputs = {key: value.cuda() if hasattr(value, "cuda") else value for key, value in inputs.items()}
    if fp16 and "pixel_values" in inputs:
        inputs["pixel_values"] = inputs["pixel_values"].half()
    with torch_mod.no_grad():
        if fp16:
            with torch_mod.amp.autocast("cuda", dtype=torch_mod.float16):
                outputs = model(**inputs)
        else:
            outputs = model(**inputs)
    logits = outputs.logits.float()
    boxes_pred = outputs.pred_boxes.float()
    try:
        outputs.logits = logits
        outputs.pred_boxes = boxes_pred
        processed = outputs
    except Exception:
        processed = type(outputs)(logits=logits, pred_boxes=boxes_pred)
    target_sizes = torch_mod.tensor(
        [(image.height, image.width)], device=logits.device
    )
    if hasattr(processor, "post_process_object_detection"):
        results = processor.post_process_object_detection(
            outputs=processed, target_sizes=target_sizes, threshold=threshold
        )
    else:
        results = processor.post_process_grounded_object_detection(
            outputs=processed, target_sizes=target_sizes, threshold=threshold, text_labels=texts
        )
    result = results[0]
    boxes_t = result["boxes"]
    scores_t = result["scores"]
    labels_t = result.get("labels")
    text_labels = result.get("text_labels")
    found: list[DetectBox] = []
    for index in range(len(scores_t)):
        score = float(scores_t[index])
        if score < threshold:
            continue
        if text_labels is not None:
            prompt = str(text_labels[index])
        else:
            label = int(labels_t[index])
            if label < 0 or label >= len(PROMPTS):
                continue
            prompt = PROMPTS[label]
        xyxy = boxes_t[index]
        x0, y0, x1, y1 = (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3]))
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        found.append(
            DetectBox(
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
                score=score,
                prompt=prompt,
                kind=kind_for_prompt(prompt),
            )
        )
    return found


def detect_area(
    rgb: np.ndarray,
    processor,
    model,
    torch_mod,
    fp16: bool,
    threshold: float = SCORE_MIN,
) -> list[DetectBox]:
    height, width = rgb.shape[:2]
    raw: list[DetectBox] = []
    xs = tile_starts(width)
    ys = tile_starts(height)
    for y0 in ys:
        for x0 in xs:
            tile, vw, vh = extract_tile(rgb, x0, y0)
            if vw <= 0 or vh <= 0:
                continue
            for box in infer_tile(tile, processor, model, torch_mod, fp16, threshold):
                shifted = DetectBox(
                    x0=box.x0 + x0,
                    y0=box.y0 + y0,
                    x1=box.x1 + x0,
                    y1=box.y1 + y0,
                    score=box.score,
                    prompt=box.prompt,
                    kind=box.kind,
                )
                cx = 0.5 * (shifted.x0 + shifted.x1)
                cy = 0.5 * (shifted.y0 + shifted.y1)
                if not (x0 <= cx < x0 + vw and y0 <= cy < y0 + vh):
                    continue
                clipped = clip_box(shifted, width, height)
                if clipped is not None and small_enough(clipped):
                    raw.append(clipped)
    return nms_classwise(raw, NMS_IOU)


def write_manifest(path: Path, area_count: int, failed: list[str], threshold: float) -> None:
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    stages["detect"] = {
        "version": DETECT_VERSION,
        "model": DETECT_MODEL,
        "areas": area_count,
        "failed": failed,
        "threshold": threshold,
    }
    payload = {
        "version": 1,
        "area_count": max(int(current.get("area_count") or 0), area_count),
        "stages": stages,
    }
    atomic_write_json(path, payload)


def format_summary(rows: list[dict], failed: list[str], threshold: float) -> str:
    lines = [
        f"detect: {len(rows)} areas, {len(failed)} failed, version {DETECT_VERSION}",
        f"model: {DETECT_MODEL}",
        f"threshold: {threshold} nms_iou={NMS_IOU} tile={TILE_SIZE} overlap={OVERLAP} "
        f"box_max_side={BOX_MAX_SIDE}",
    ]
    if failed:
        lines.append("failed: " + ", ".join(failed))
    total = sum(int(row["n"]) for row in rows)
    kinds = {"fire": 0, "magic": 0, "steady": 0, "pool": 0}
    for row in rows:
        for kind, count in row["kinds"].items():
            kinds[kind] = kinds.get(kind, 0) + int(count)
    lines.append(f"total boxes: {total}")
    lines.append(
        "by kind: "
        + ", ".join(f"{kind} {kinds.get(kind, 0)}" for kind in ("fire", "magic", "steady", "pool"))
    )
    empty = [row["wed"] for row in rows if int(row["n"]) == 0]
    lines.append(f"areas with 0 boxes: {len(empty)}")
    if empty:
        lines.append("  " + " ".join(empty[:40]) + (" ..." if len(empty) > 40 else ""))
    if rows:
        richest = max(rows, key=lambda row: row["n"])
        lines.append(f"most boxes: {richest['wed']} {richest['n']}")
    return "\n".join(lines)


def _kind_counts(boxes: list[DetectBox]) -> dict[str, int]:
    counts = {"fire": 0, "magic": 0, "steady": 0, "pool": 0}
    for box in boxes:
        counts[box.kind] = counts.get(box.kind, 0) + 1
    return counts


def run(ctx: common.RunContext) -> int:
    errors = ctx.work / "errors.log"
    review_dir = ctx.work / "review"
    rows: list[dict] = []
    failed: list[str] = []
    total = len(ctx.weds)
    threshold = SCORE_MIN
    print(f"detect model={DETECT_MODEL} threshold={threshold} fp16=try", flush=True)
    processor = model = torch_mod = None
    fp16 = False
    try:
        processor, model, torch_mod, fp16 = load_model(DETECT_MODEL)
        print(f"detect loaded fp16={int(fp16)}", flush=True)
    except Exception as exc:
        _log_error(errors, "detect-load", exc)
        print(f"detect model failed to load: {exc}", flush=True)
        return 1

    try:
        for number, wed in enumerate(ctx.weds, start=1):
            key = f"detect:{wed}"
            started = time.perf_counter()
            try:
                if any(char in wed for char in "\\/:"):
                    raise ValueError(f"bad WED name {wed!r}")
                digest = common.source_digest(
                    common.source_parts(ctx.index, wed), DETECT_VERSION, DETECT_MODEL
                )
                out_dir = ctx.out / wed
                json_path = out_dir / "detect.json"
                cached = (
                    not ctx.force
                    and not ctx.state.fresh(key, digest, DETECT_VERSION, 1, False)
                    and json_path.is_file()
                )
                area = None
                if cached:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                    boxes = boxes_from_json(payload)
                    label = "cached"
                else:
                    area = common.load_area(ctx.index, wed)
                    boxes = detect_area(area.rgb, processor, model, torch_mod, fp16, threshold)
                    atomic_write_json(
                        json_path,
                        boxes_payload(wed, area.rgb.shape[1], area.rgb.shape[0], boxes, threshold),
                    )
                    ctx.state.mark(key, digest, DETECT_VERSION, 1, False, 1)
                    label = f"{time.perf_counter() - started:.1f}s"
                kinds = _kind_counts(boxes)
                if ctx.review:
                    if area is None:
                        area = common.load_area(ctx.index, wed)
                    import lights

                    lights_path = out_dir / "lights.json"
                    if lights_path.is_file():
                        result = lights.result_from_json(json.loads(lights_path.read_text(encoding="utf-8")))
                    else:
                        result = lights.LightsResult(
                            lights=[], tints=[], area_w=area.rgb.shape[1], area_h=area.rgb.shape[0]
                        )
                    result.boxes = boxes
                    lights.write_review_image(review_dir / f"lights_{wed}.png", area.rgb, result)
                rows.append(
                    {
                        "wed": wed,
                        "n": len(boxes),
                        "kinds": kinds,
                        "seconds": time.perf_counter() - started,
                    }
                )
                print(
                    f"detect {wed} {number}/{total} {label} n={len(boxes)} "
                    f"fire={kinds['fire']} magic={kinds['magic']} "
                    f"steady={kinds['steady']} pool={kinds['pool']}",
                    flush=True,
                )
                del area
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                failed.append(wed)
                _log_error(errors, key, exc)
                print(f"detect {wed} {number}/{total} failed: {exc}", flush=True)
    finally:
        del model
        del processor
        if torch_mod is not None:
            try:
                torch_mod.cuda.empty_cache()
            except Exception:
                pass

    text = format_summary(rows, failed, threshold)
    atomic_write_bytes(ctx.work / "detect_summary.txt", (text + "\n").encode("utf-8"))
    ctx.out.mkdir(parents=True, exist_ok=True)
    write_manifest(ctx.out / "manifest.json", len(rows), failed, threshold)
    print(text, flush=True)
    return 1 if failed else 0
