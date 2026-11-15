"""Nearest-neighbour 2x index maps for live PST creature recolour.

The RGBA upscale keeps extra colours. These paletted PNGs say which original
BAM index each hi-res pixel came from. The GL driver shifts the RGBA by
(live palette - original BAM palette) at that index.

    python index_maps.py
    python index_maps.py --only DWLKNOFB --limit 3

Writes sprites/bam/<BAM>/<frame>.idx.png next to the existing RGBA frames.
Does not use the GPU. Safe to run while the RGBA upscale continues: it only
writes .idx.png and skips frames whose RGBA is not there yet.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

import extract
import ie_formats
from state import atomic_write_bytes
from upscale import DEFAULT_GAME, DEFAULT_OUT, HERE

WORK = HERE / "work"


def save_indexed_png(path: Path, indices: np.ndarray, palette_rgb: np.ndarray, color_key: int) -> None:
    """Paletted PNG whose PLTE is the BAM default. Independent of upscale.Image."""
    image = Image.fromarray(np.ascontiguousarray(indices), "P")
    flat: list[int] = []
    for i in range(256):
        if i < len(palette_rgb):
            flat.extend(int(v) for v in palette_rgb[i, :3])
        else:
            flat.extend((0, 0, 0))
    image.putpalette(flat[:768])
    buf = io.BytesIO()
    image.save(buf, format="PNG", transparency=int(color_key), optimize=False, compress_level=6)
    atomic_write_bytes(path, buf.getvalue())


def residual_rgb(rgb: np.ndarray, orig: np.ndarray, live: np.ndarray, idx: int) -> np.ndarray:
    """Same shift the GL shader applies. Colour-key 0 and shadow 1 stay put."""
    rgb = np.asarray(rgb, dtype=np.uint8)
    if idx <= 1:
        return rgb
    out = rgb.astype(np.int16) + live[idx].astype(np.int16) - orig[idx].astype(np.int16)
    return np.clip(out, 0, 255).astype(np.uint8)


def scale_nearest(indices: np.ndarray, scale: int) -> np.ndarray:
    """Repeat each original pixel into a scale x scale block."""
    if scale < 2:
        raise ValueError("scale must be >= 2")
    return np.repeat(np.repeat(indices, scale, axis=0), scale, axis=1)


def png_hw(path: Path) -> tuple[int, int] | None:
    """Width, height from the PNG header. None if unreadable."""
    try:
        with Image.open(path) as image:
            return int(image.size[0]), int(image.size[1])
    except OSError:
        return None


def write_bam_indices(
    name: str,
    data: bytes,
    folder: Path,
    *,
    force: bool = False,
) -> tuple[int, int]:
    """Write missing .idx.png files for one BAM folder. Returns (wrote, skipped)."""
    frames, pal, color_key = extract._bam_indices(data, keep_small=False)
    rgb = pal[:, :3].copy()
    wrote = skipped = 0
    for index, indices in enumerate(frames):
        if indices is None:
            continue
        rgba_path = folder / f"{index}.png"
        idx_path = folder / f"{index}.idx.png"
        if not rgba_path.is_file():
            continue
        size = png_hw(rgba_path)
        if size is None:
            continue
        src_h, src_w = int(indices.shape[0]), int(indices.shape[1])
        if src_w <= 0 or src_h <= 0:
            continue
        if size[0] % src_w or size[1] % src_h:
            continue
        scale = size[0] // src_w
        if scale < 2 or size[1] // src_h != scale:
            continue
        if idx_path.is_file() and not force:
            existing = png_hw(idx_path)
            if existing == size:
                skipped += 1
                continue
        scaled = scale_nearest(indices, scale)
        save_indexed_png(idx_path, scaled, rgb, color_key)
        wrote += 1
    return wrote, skipped


def run(game: Path, out: Path, only: set[str], limit: int, force: bool) -> int:
    root = out / "sprites" / "bam"
    if not root.is_dir():
        print(f"No sprite folder at {root}")
        return 1
    print(f"Indexing {game} ...", flush=True)
    index = ie_formats.ResourceIndex(game, WORK / "bifcache")
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    if only:
        folders = [p for p in folders if p.name.upper() in only]
    if limit:
        folders = folders[:limit]
    started = time.perf_counter()
    wrote = skipped = failed = 0
    done = 0
    total = len(folders)
    for folder in folders:
        name = folder.name.upper()
        done += 1
        try:
            data = index.get(name, "bam")
            w, s = write_bam_indices(name, data, folder, force=force)
            wrote += w
            skipped += s
        except Exception as exc:
            failed += 1
            print(f"  failed {name}: {exc}", flush=True)
            continue
        if done % 50 == 0 or done == total:
            elapsed = time.perf_counter() - started
            print(
                f"idx {done}/{total} wrote={wrote} skipped={skipped} failed={failed} "
                f"{elapsed:.1f}s",
                flush=True,
            )
    print(
        f"index maps: {total} bams, wrote {wrote} frames, skipped {skipped}, failed {failed}",
        flush=True,
    )
    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default=str(DEFAULT_GAME))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--only", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    only = {part.strip().upper() for part in args.only.split(",") if part.strip()}
    game = Path(args.game)
    if not (game / "CHITIN.KEY").is_file() and not (game / "chitin.key").is_file():
        print(f"Game not found at {game}")
        return 1
    return run(game, Path(args.out), only, args.limit, args.force)


if __name__ == "__main__":
    sys.exit(main())
