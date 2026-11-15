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
