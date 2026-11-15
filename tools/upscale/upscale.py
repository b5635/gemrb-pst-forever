"""Offline upscale of Planescape: Torment art into D:\\Games\\GemRB\\upscaled.

    python upscale.py --categories gui,areas [--scale 2] [--limit N]
        [--only RESREF[,RESREF]] [--force] [--dry-run]
        [--game "C:\\Program Files (x86)\\Black Isle\\Torment"]
        [--out "D:\\Games\\GemRB\\upscaled"] [--tile 512] [--fp16]
        [--model-areas PATH] [--model-gui PATH] [--model-sprites PATH]
        [--compare]

Dry-run only classifies. It does not import PyTorch. Models are never downloaded.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import traceback
from pathlib import Path

import ie_formats
from classify import classify
from state import State, atomic_write_bytes, atomic_write_json, cleanup_tmp, sha1

# numpy, Pillow and extract are imported by _need() so --dry-run stays stdlib-only.
np = None
Image = None
extract = None


def _need():
    global np, Image, extract
    if extract is not None:
        return
    import numpy as _np
    from PIL import Image as _Image

    import extract as _extract

    np = _np
    Image = _Image
    extract = _extract

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
DEFAULT_OUT = Path(r"D:\Games\GemRB\upscaled")

# One file per category is enough for a run. Compare uses every candidate present.
CANDIDATES = {
    "areas": ["4x-UltraSharp", "4xNomos8kDAT"],
    "gui": ["4x-UltraSharp", "4x-FatalPixels"],
    "sprites": ["4x-UltraSharp"],
}
MODEL_EXTS = {".safetensors", ".pth", ".pt"}


def _save_png(path: Path, arr: np.ndarray) -> None:
    image = Image.fromarray(np.ascontiguousarray(arr), "RGBA")
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False, compress_level=6)
    atomic_write_bytes(path, buf.getvalue())


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def _key_name(name: str) -> str:
    folded = name.lower().replace("_", "").replace("-", "")
    return folded


def _scan_models(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MODEL_EXTS]


def _match_candidate(files: list[Path], candidate: str) -> Path | None:
    want = _key_name(candidate)
    for path in files:
        stem = _key_name(path.stem)
        if want in stem or stem in want:
            return path
    return None


def _resolve_model(category: str, explicit: str | None, files: list[Path]) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise SystemExit(f"--model-{category} is not a file: {path}")
        return path
    for name in CANDIDATES[category]:
        found = _match_candidate(files, name)
        if found is not None:
            return found
    return None


def _print_missing(categories: list[str]) -> None:
    print("No upscale model is available. Nothing is downloaded automatically.")
    print("Put a .safetensors (or .pth) file in tools/upscale/models/.")
    print("OpenModelDB names, one of which is used per category:")
    for category in categories:
        print(f"  {category}: {', '.join(CANDIDATES[category])}")
    print("Pass --model-<category> PATH once the file is there.")


def _wed_map(index: ie_formats.ResourceIndex) -> dict[str, list]:
    """TIS name -> overlay list of the WED that should drive its stitch."""
    users: dict[str, list] = {}
    for name in index.names("wed"):
        try:
            overlays = extract.read_wed(index.get(name, "wed"))
        except Exception:
            continue
        for i, overlay in enumerate(overlays):
            tis = overlay["tis"]
            if not tis:
                continue
            # prefer a WED whose first overlay is this tileset
            prev = users.get(tis)
            if prev is None or (i == 0 and prev and prev[0]["tis"] != tis):
                users[tis] = overlays
    return users


def _kind(category: str, ext: str) -> str:
    if ext == "bam" and category == "gui":
        return "bam-gui"
    if ext == "bam":
        return "bam-sprite"
    if ext == "tis":
        return "area"
    return ext


def _write_frames(folder: Path, frames: list[np.ndarray | None], ups: list[np.ndarray]) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    written = 0
    cursor = 0
    for index, frame in enumerate(frames):
        if frame is None:
            continue
        _save_png(folder / f"{index}.png", ups[cursor])
        cursor += 1
        written += 1
    return written


def _save_indexed_png(path: Path, indices: np.ndarray, palette_rgb: np.ndarray, color_key: int) -> None:
    image = Image.fromarray(np.ascontiguousarray(indices), "P")
    flat = []
    for i in range(256):
        if i < len(palette_rgb):
            flat.extend(int(v) for v in palette_rgb[i, :3])
        else:
            flat.extend((0, 0, 0))
    image.putpalette(flat[:768])
    buf = io.BytesIO()
    image.save(buf, format="PNG", transparency=int(color_key), optimize=False, compress_level=6)
    atomic_write_bytes(path, buf.getvalue())


def _process_bam(data: bytes, category: str, name: str, out: Path, upscaler, font: bool = False) -> int:
    folder = out / ("gui" if category == "gui" else "sprites") / "bam" / name
    if font:
        # A photo model fills the counters of an 8px face and eats the punctuation.
        # Scale the original indices instead; the grey ramp is already the antialiasing.
        _images, indices, palette, color_key = extract.decode_font(data)
        real = [frame for frame in indices if frame is not None]
        if not real:
            return 0
        folder.mkdir(parents=True, exist_ok=True)
        written = 0
        for index, frame in enumerate(indices):
            if frame is None:
                continue
            scaled = extract.scale_font_indices(frame, color_key, upscaler.out_scale)
            _save_indexed_png(folder / f"{index}.png", scaled, palette, color_key)
            written += 1
        return written
    frames = extract.decode_bam(data)
    real = [frame for frame in frames if frame is not None]
    if not real:
        return 0
    ups = upscaler.upscale_many(real, _kind(category, "bam"))
    return _write_frames(folder, frames, ups)


def _process_image(data: bytes, ext: str, name: str, out: Path, upscaler) -> int:
    if ext == "mos":
        image = extract.decode_mos(data)
        rel = out / "gui" / "mos" / f"{name}.png"
    else:
        image = extract.decode_bmp(data)
        rel = out / "gui" / "bmp" / f"{name}.png"
    up = upscaler.upscale_rgba(image, ext)
    _save_png(rel, up)
    return 1


def _process_tis(name: str, data: bytes, overlays: list, out: Path, upscaler, scale: int) -> int:
    tiles = extract.decode_tis_tiles(data)
    plan = extract.area_plan(tiles, overlays, name)
    folder = out / "areas" / name
    written = 0
    side = 64 * scale
    image = plan["image"]
    print(
        f"  {name}: {len(tiles)} tiles, placed {len(plan['placed'])}, "
        f"patches {len(plan['extras'])}, solo {len(plan['solo'])}",
        flush=True,
    )
    if image is not None and plan["placed"]:
        up = upscaler.upscale_rgba(image, "area")
        if up.shape[0] != image.shape[0] * scale or up.shape[1] != image.shape[1] * scale:
            raise ValueError(
                f"{name} stitch came out {up.shape[1]}x{up.shape[0]}, "
                f"expected {image.shape[1] * scale}x{image.shape[0] * scale}"
            )
        for index, (x, y) in plan["placed"].items():
            tile = np.ascontiguousarray(up[y * side : (y + 1) * side, x * side : (x + 1) * side])
            if tile.shape[0] != side or tile.shape[1] != side:
                raise ValueError(f"{name} tile {index} came out {tile.shape[1]}x{tile.shape[0]}")
            _save_png(folder / f"{index}.png", tile)
            written += 1
        del up
    batch = []

    def flush_patches(pending):
        nonlocal written
        if not pending:
            return
        ups = upscaler.upscale_many([patch for _, patch in pending], "area")
        for (index, _), up in zip(pending, ups):
            if up.shape[0] != side * 3 or up.shape[1] != side * 3:
                raise ValueError(f"{name} patch {index} came out {up.shape[1]}x{up.shape[0]}")
            tile = np.ascontiguousarray(up[side : 2 * side, side : 2 * side])
            if tile.shape[0] != side or tile.shape[1] != side:
                raise ValueError(f"{name} patch tile {index} came out {tile.shape[1]}x{tile.shape[0]}")
            _save_png(folder / f"{index}.png", tile)
            written += 1

    for index, (grid, x, y) in plan["extras"].items():
        batch.append((index, extract.patch_3x3(tiles, grid, x, y, index)))
        if len(batch) >= 8:
            flush_patches(batch)
            batch = []
    flush_patches(batch)

    pad = 16 * scale
    solo = []

    def flush_solo(pending):
        nonlocal written
        if not pending:
            return
        ups = upscaler.upscale_many([patch for _, patch in pending], "area")
        for (index, _), up in zip(pending, ups):
            if up.shape[0] != pad * 2 + side or up.shape[1] != pad * 2 + side:
                raise ValueError(f"{name} solo {index} came out {up.shape[1]}x{up.shape[0]}")
            tile = np.ascontiguousarray(up[pad : pad + side, pad : pad + side])
            if tile.shape[0] != side or tile.shape[1] != side:
                raise ValueError(f"{name} solo tile {index} came out {tile.shape[1]}x{tile.shape[0]}")
            _save_png(folder / f"{index}.png", tile)
            written += 1

    for index in plan["solo"]:
        solo.append((index, extract.pad_solo(tiles[index])))
        if len(solo) >= 16:
            flush_solo(solo)
            solo = []
    flush_solo(solo)
    return written


def _manifest(path: Path, scale: int, category: str, model: str, count: int, failed: int, ran: int) -> None:
    payload = {"version": 1, "scale": scale, "categories": {}}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    payload["version"] = 1
    payload["scale"] = scale
    payload.setdefault("categories", {})[category] = {
        "model": model,
        "count": count,
        "failed": failed,
        "ran": ran,
    }
    atomic_write_json(path, payload)


def _peek(index: ie_formats.ResourceIndex, names: list[str]) -> None:
    try:
        _need()
    except ImportError:
        pass
    for name in names:
        if index.has(name, "tis"):
            data = index.get(name, "tis")
            count = ie_formats.tis_tile_count(data)
            shape = "numpy not installed"
            if extract is not None:
                try:
                    tiles = extract.decode_tis_tiles(data)
                    shape = f"{tiles.shape[2]}x{tiles.shape[1]}" if len(tiles) else "none"
                except Exception as exc:
                    shape = f"decode failed ({exc})"
            print(f"  {name}.TIS {count} tiles, decoded {shape}")
        elif index.has(name, "mos"):
            size = ie_formats.mos_size(index.get(name, "mos"))
            print(f"  {name}.MOS {size}")
        elif index.has(name, "bam"):
            sizes = ie_formats.bam_frame_sizes(index.get(name, "bam"))
            print(f"  {name}.BAM {len(sizes)} frames")
        elif index.has(name, "bmp"):
            print(f"  {name}.BMP")
        else:
            print(f"  {name} is not in the index")


def _sample_area(index, wed, name: str):
    tiles = extract.decode_tis_tiles(index.get(name, "tis"))
    plan = extract.area_plan(tiles, wed.get(name, []), name)
    image = plan["image"]
    if image is not None and image.shape[0] >= 128 and image.shape[1] >= 128:
        y = image.shape[0] // 2 - 64
        x = image.shape[1] // 2 - 64
        return image[y : y + 128, x : x + 128]
    if len(tiles):
        return tiles[len(tiles) // 2]
    return None


def _sample_gui(index, row: dict):
    name, ext = row["name"], row["ext"]
    data = index.get(name, ext)
    if ext == "mos":
        image = extract.decode_mos(data)
    elif ext == "bmp":
        image = extract.decode_bmp(data)
    else:
        frames = extract.decode_bam(data)
        image = next((frame for frame in frames if frame is not None), None)
        if image is None:
            return None
    if image.shape[0] > 160 and image.shape[1] > 160:
        y = image.shape[0] // 2 - 80
        x = image.shape[1] // 2 - 80
        image = image[y : y + 160, x : x + 160]
    return image


def _sheet(rows: list[tuple[str, list[tuple[str, np.ndarray]]]], path: Path) -> None:
    if not rows:
        return
    from PIL import ImageDraw

    pad = 8
    label_h = 16
    cell_label_h = 14
    height = 0
    width = 0
    prepared = []
    for title, cells in rows:
        cell_h = max(img.shape[0] for _, img in cells)
        cell_w = sum(img.shape[1] for _, img in cells) + pad * (len(cells) + 1)
        prepared.append((title, cells, cell_w, cell_h))
        width = max(width, cell_w)
        height += cell_h + label_h + cell_label_h + pad
    canvas = Image.new("RGB", (max(width, 1), max(height, 1)), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    y = 0
    for title, cells, _cell_w, cell_h in prepared:
        draw.text((pad, y), title, fill=(230, 230, 230))
        y += label_h
        x = pad
        for label, _img in cells:
            draw.text((x, y), label, fill=(190, 190, 190))
            x += _img.shape[1] + pad
        y += cell_label_h
        x = pad
        for _label, img in cells:
            view = Image.fromarray(img, "RGBA")
            plate = Image.new("RGBA", view.size, (32, 32, 32, 255))
            plate.alpha_composite(view)
            canvas.paste(plate.convert("RGB"), (x, y))
            x += img.shape[1] + pad
        y += cell_h + pad
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, optimize=False, compress_level=6)


def _compare(args, index, report, models: dict[str, list[Path]]) -> int:
    _need()
    from upscaler import Upscaler

    wed = _wed_map(index) if "areas" in args.categories else {}
    out_dir = HERE / "work" / "compare"
    any_written = False
    for category in args.categories:
        present = models.get(category) or []
        if not present:
            continue
        upscalers = [
            (path.stem, Upscaler(str(path), args.scale, args.fp16, args.tile))
            for path in present
        ]
        rows = []
        attempts = 0
        for row in report["items"][category]:
            if args.only and row["name"] not in args.only:
                continue
            attempts += 1
            if attempts > 40 or len(rows) >= 10:
                break
            try:
                if category == "areas":
                    sample = _sample_area(index, wed, row["name"])
                else:
                    sample = _sample_gui(index, row)
            except Exception as exc:
                _log_error(HERE / "work" / "errors.log", f"compare {row['name']}", exc)
                continue
            if sample is None:
                continue
            cells = [("original", _nearest(sample, args.scale))]
            for label, scaler in upscalers:
                kind = _kind(category, row["ext"])
                cells.append((label, scaler.upscale_rgba(sample, kind)))
            rows.append((f"{row['name']}.{row['ext']}", cells))
        dest = out_dir / f"{category}.png"
        _sheet(rows, dest)
        print(f"compare {category}: {len(rows)} samples -> {dest}")
        any_written = any_written or bool(rows)
    if not any_written:
        _print_missing(args.categories)
        return 2
    return 0


def _nearest(image: np.ndarray, scale: int) -> np.ndarray:
    view = Image.fromarray(image, "RGBA")
    return np.asarray(view.resize((image.shape[1] * scale, image.shape[0] * scale), Image.Resampling.NEAREST))


def _wed_fingerprint(overlays: list, name: str) -> bytes:
    parts = []
    for overlay in overlays:
        if overlay["tis"] != name:
            continue
        cells = [
            (cell["x"], cell["y"], cell["indices"], cell["secondary"])
            for cell in overlay["cells"]
        ]
        parts.append((overlay["w"], overlay["h"], cells))
    return json.dumps(parts, separators=(",", ":")).encode("utf-8")


def _run_category(args, index, report, category: str, model: Path, state: State) -> tuple[int, int, int]:
    _need()
    from upscaler import Upscaler

    upscaler = Upscaler(str(model), args.scale, args.fp16, args.tile)
    # half() can refuse a model; the state has to record the dtype that was used
    used_fp16 = bool(upscaler.fp16)
    wed = _wed_map(index) if category == "areas" else {}
    rows = report["items"][category]
    if args.only:
        rows = [row for row in rows if row["name"] in args.only]
    if args.limit:
        rows = rows[: args.limit]
    errors = HERE / "work" / "errors.log"
    current = 0
    failed = 0
    ran = 0
    try:
        from tqdm import tqdm

        progress = tqdm(rows, desc=category, unit="res")
    except Exception:
        progress = rows
    for row in progress:
        name = row["name"]
        ext = row["ext"]
        key = f"{category}:{ext}:{name}"
        try:
            data = index.get(name, ext)
            extra = b""
            if ext == "tis":
                # which tiles share an edge lives in the WED, so it belongs in the source hash
                extra = _wed_fingerprint(wed.get(name, []), name)
            digest = sha1(data + extra)
            if not args.force and not state.fresh(key, digest, model.name, args.scale, used_fp16):
                current += 1
                continue
            if ext == "bam":
                count = _process_bam(data, category, name, args.out, upscaler, font=row.get("reason") == "font")
            elif ext == "tis":
                count = _process_tis(name, data, wed.get(name, []), args.out, upscaler, args.scale)
            else:
                count = _process_image(data, ext, name, args.out, upscaler)
            state.mark(key, digest, model.name, args.scale, used_fp16, count)
            ran += 1
            current += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failed += 1
            _log_error(errors, key, exc)
            print(f"  failed {key}: {exc}", flush=True)
    return current, failed, ran


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upscale PST art for the GemRB GL driver.")
    parser.add_argument("--categories", default="gui,areas")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--game", default=str(DEFAULT_GAME))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--tile", type=int, default=512)
    parser.add_argument("--fp16", action="store_true")
    parser.add_argument("--model-areas", default="")
    parser.add_argument("--model-gui", default="")
    parser.add_argument("--model-sprites", default="")
    args = parser.parse_args(argv)
    args.categories = [part.strip() for part in args.categories.split(",") if part.strip()]
    args.only = {part.strip().upper() for part in args.only.split(",") if part.strip()}
    args.game = Path(args.game)
    args.out = Path(args.out)
    unknown = [name for name in args.categories if name not in CANDIDATES]
    if unknown or args.scale < 2:
        parser.error("categories are gui, areas, sprites and --scale must be >= 2")
    if not (args.game / "CHITIN.KEY").is_file() and not (args.game / "chitin.key").is_file():
        print(f"Game not found (no CHITIN.KEY) at {args.game}")
        return 1

    work = HERE / "work"
    work.mkdir(parents=True, exist_ok=True)
    print(f"Indexing {args.game} ...", flush=True)
    index = ie_formats.ResourceIndex(args.game, work / "bifcache")
    print(f"  {len(index)} resources, {index.found_bifs} bif files, {len(index.missing_bifs)} missing")
    if index.missing_bifs:
        print("  missing: " + ", ".join(index.missing_bifs[:8]))
    if len(index) == 0:
        print("The KEY/BIF index is empty. Check the game path and bif layout.")
        return 1

    report = classify(index, REPO)
    atomic_write_json(work / "classification.json", report)
    for category in ("gui", "areas", "sprites", "skip"):
        counts = report["by_ext"].get(category, {})
        detail = ", ".join(f"{ext} {n}" for ext, n in sorted(counts.items()))
        print(f"  {category}: {report['counts'][category]}" + (f" ({detail})" if detail else ""))
    if args.dry_run:
        if args.only:
            _peek(index, sorted(args.only))
        print("Dry run stops after classification.")
        return 0

    explicit = {
        "areas": args.model_areas,
        "gui": args.model_gui,
        "sprites": args.model_sprites,
    }
    files = _scan_models(HERE / "models")
    if args.compare:
        available = {}
        for category in args.categories:
            if explicit[category]:
                available[category] = [_resolve_model(category, explicit[category], files)]
            else:
                found = []
                for name in CANDIDATES[category]:
                    path = _match_candidate(files, name)
                    if path is not None and path not in found:
                        found.append(path)
                available[category] = found
        if not any(available.values()):
            _print_missing(args.categories)
            return 2
        return _compare(args, index, report, available)

    chosen = {}
    for category in args.categories:
        path = _resolve_model(category, explicit[category] or None, files)
        if path is None:
            _print_missing([category])
            return 2
        chosen[category] = path
        print(f"  model {category}: {path.name}")

    cleanup_tmp(args.out)
    cleanup_tmp(work)
    state = State(work / "state.json")
    for category in args.categories:
        current, failed, ran = _run_category(args, index, report, category, chosen[category], state)
        print(f"{category}: {ran} upscaled, {failed} failed, {current} current")
        if not args.only and not args.limit:
            _manifest(
                args.out / "manifest.json",
                args.scale,
                category,
                chosen[category].name,
                current,
                failed,
                ran,
            )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Finished resources are in the state file; rerun to continue.")
        sys.exit(130)
