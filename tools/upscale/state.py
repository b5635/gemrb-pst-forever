"""Resumable upscale bookkeeping.

A resource is finished when its state entry matches the source bytes, the model
and the scale. Output files are written to `*.png.tmp` and then renamed, so a
crash leaves at most the resource in progress.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def cleanup_tmp(root: Path) -> int:
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob("*.tmp"):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    atomic_write_bytes(path, raw)


def output_path(out: Path, category: str, ext: str, name: str) -> Path:
    """Where the pipeline writes this resource. A BAM/TIS is a folder of PNGs."""
    name = name.upper()
    ext = ext.lower()
    if ext == "tis":
        return out / "areas" / name
    if ext == "mos":
        return out / "gui" / "mos" / f"{name}.png"
    if ext == "bmp":
        return out / "gui" / "bmp" / f"{name}.png"
    bucket = "gui" if category == "gui" else "sprites"
    return out / bucket / "bam" / name


def png_stats(path: Path) -> tuple[int, int]:
    """How many PNG files sit at this output path, and their total bytes."""
    if path.suffix.lower() == ".png":
        if not path.is_file():
            return 0, 0
        try:
            return 1, path.stat().st_size
        except OSError:
            return 1, 0
    if not path.is_dir():
        return 0, 0
    count = 0
    size = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if not entry.is_file() or not entry.name.lower().endswith(".png"):
                    continue
                # live-recolour index maps sit next to the RGBA frames
                if entry.name.lower().endswith(".idx.png"):
                    continue
                count += 1
                try:
                    size += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        return 0, 0
    return count, size


def outputs_complete(on_disk: int, expected) -> bool:
    """True when the finished PNG count is at least what the last run wrote."""
    try:
        want = int(expected or 0)
    except (TypeError, ValueError):
        want = 0
    if want <= 0:
        return True
    return on_disk >= want


class State:
    def __init__(self, path: Path):
        self.path = path
        self.items: dict[str, dict] = {}
        if path.is_file():
            try:
                self.items = json.loads(path.read_text(encoding="utf-8")).get("items", {})
            except (OSError, json.JSONDecodeError):
                self.items = {}

    def fresh(self, key: str, digest: str, model: str, scale: int, fp16: bool) -> bool:
        prev = self.items.get(key)
        if not prev:
            return True
        return not (
            prev.get("sha1") == digest
            and prev.get("model") == model
            and prev.get("scale") == scale
            and prev.get("fp16") == bool(fp16)
        )

    def mark(self, key: str, digest: str, model: str, scale: int, fp16: bool, outputs: int) -> None:
        self.items[key] = {
            "sha1": digest,
            "model": model,
            "scale": scale,
            "fp16": bool(fp16),
            "outputs": outputs,
        }
        self.flush()

    def flush(self) -> None:
        atomic_write_json(self.path, {"items": self.items})
