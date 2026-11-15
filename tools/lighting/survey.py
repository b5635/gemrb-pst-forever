"""Survey stage: one row per WED, no generated maps."""

from __future__ import annotations

import csv
import io
import json
import time
import traceback
from collections import Counter
from pathlib import Path

import numpy as np

import common
import extract
from state import atomic_write_bytes, atomic_write_json

SURVEY_VERSION = "survey-1"
SURVEY_MODEL = ""
FLAT_LM_STD = 3.0 / 255.0

COLUMNS = [
    "wed",
    "tis",
    "area_w",
    "area_h",
    "lm_w",
    "lm_h",
    "lm_luma_mean",
    "lm_luma_std",
    "lm_luma_p99",
    "ht_unique",
    "ht_std",
    "walkable_fraction",
    "floor_fraction",
    "wall_polygons",
    "door_count",
    "blend_black",
    "transparent_fraction",
]


def survey_row(area: common.Area) -> dict:
    luma = 0.299 * area.lm[:, :, 0] + 0.587 * area.lm[:, :, 1] + 0.114 * area.lm[:, :, 2]
    blend = sum(1 for anim in area.anims if anim[3] & common.PST_BLEND_BIT)
    walkable_fraction = float(np.mean(area.walkable)) if area.walkable.size else 0.0
    return {
        "wed": area.wed,
        "tis": area.tis,
        "area_w": int(area.rgb.shape[1]),
        "area_h": int(area.rgb.shape[0]),
        "lm_w": int(area.lm.shape[1]),
        "lm_h": int(area.lm.shape[0]),
        "lm_luma_mean": float(luma.mean()) if luma.size else 0.0,
        "lm_luma_std": float(luma.std()) if luma.size else 0.0,
        "lm_luma_p99": float(np.quantile(luma, 0.99)) if luma.size else 0.0,
        "ht_unique": int(np.unique(area.ht).size) if area.ht.size else 0,
        "ht_std": float(np.std(area.ht.astype(np.float32))) if area.ht.size else 0.0,
        "walkable_fraction": walkable_fraction,
        "floor_fraction": float(np.mean(area.floor_mask)) if area.floor_mask.size else 0.0,
        "wall_polygons": int(area.wall_count),
        "door_count": int(area.door_count),
        "blend_black": int(blend),
        "transparent_fraction": float(np.mean(area.alpha != 255)) if area.alpha.size else 0.0,
    }


def _sources(index, wed: str) -> list[bytes]:
    wed_bytes = common.require_resource(index, wed, "wed")
    overlays = extract.read_wed(wed_bytes)
    if not overlays or not overlays[0].get("tis"):
        raise ValueError(f"{wed} has no primary tileset")
    tis = overlays[0]["tis"]
    parts = [
        common.require_resource(index, tis, "tis"),
        wed_bytes,
        common.require_resource(index, common.map_resref(wed, "LM"), "bmp"),
        common.require_resource(index, common.map_resref(wed, "SR"), "bmp"),
    ]
    records = sorted(common.areas_by_wed(index).get(wed, []), key=lambda rec: rec[0])
    for name, data, _anims in records:
        parts.append(name.encode("ascii"))
        parts.append(data)
    return parts


def _log_error(path: Path, label: str, exc: BaseException) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{label}\n{''.join(traceback.format_exception(exc))}\n")


def _cell(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.6f}"
    return value


def _write_csv(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _cell(row[key]) for key in COLUMNS})
    atomic_write_bytes(path, buf.getvalue().encode("utf-8"))


def _blend_counts(index, weds: list[str]) -> tuple[Counter, Counter]:
    file_bit = Counter()
    engine_bit = Counter()
    grouped = common.areas_by_wed(index)
    for wed in weds:
        for _name, _data, anims in grouped.get(wed, []):
            for _x, _y, bam, flags in anims:
                if flags & 0x2:
                    file_bit[bam] += 1
                if flags & common.PST_BLEND_BIT:
                    engine_bit[bam] += 1
    return file_bit, engine_bit


def format_summary(rows: list[dict], failed: list[str], file_bit: Counter, engine_bit: Counter) -> str:
    lines: list[str] = []
    lines.append(f"survey: {len(rows)} areas, {len(failed)} failed, version {SURVEY_VERSION}")
    if failed:
        lines.append("failed: " + ", ".join(failed))
    if not rows:
        return "\n".join(lines)

    flat = [row for row in rows if row["lm_luma_std"] < FLAT_LM_STD]
    varied = [row for row in rows if row["ht_unique"] > 1]
    smallest = min(rows, key=lambda row: row["floor_fraction"])
    median_std = float(np.median([row["lm_luma_std"] for row in rows]))
    lines.append(f"flat light maps (luma std < 3/255): {len(flat)}")
    if flat:
        lines.append("  " + " ".join(row["wed"] for row in flat))
    lines.append(f"median luma std: {median_std * 255:.2f}/255")
    share = len(varied) / len(rows)
    lines.append(f"non-uniform HT (more than one value): {len(varied)}/{len(rows)} ({share * 100:.1f}%)")
    if varied:
        lines.append("  " + ", ".join(f"{row['wed']}({row['ht_unique']})" for row in varied))
    lines.append(
        f"smallest floor fraction: {smallest['floor_fraction']:.4f} {smallest['wed']}"
    )
    histogram: dict[int, int] = {}
    for row in rows:
        histogram[int(row["ht_unique"])] = histogram.get(int(row["ht_unique"]), 0) + 1
    hist_text = ", ".join(f"{count} values: {histogram[count]}" for count in sorted(histogram))
    lines.append(f"HT unique-value histogram: {hist_text}")
    lines.append(f"blend-black animations (engine bit 0x100): {sum(engine_bit.values())}")
    if engine_bit:
        top = ", ".join(f"{name} {count}" for name, count in engine_bit.most_common(12))
        lines.append(f"  top: {top}")
    lines.append(f"file bit 0x2 animations: {sum(file_bit.values())}")
    if file_bit:
        top = ", ".join(f"{name} {count}" for name, count in file_bit.most_common(8))
        lines.append(f"  top: {top}")
    if share > 0.10:
        lines.append(
            f"STOP: {len(varied)} of {len(rows)} areas ({share * 100:.1f}%) have a non-uniform HT map. "
            "The h = 0 floor rule may not cover them. Ask the owner before phase 1."
        )
    return "\n".join(lines)


def write_manifest(path: Path, area_count: int, failed: list[str]) -> None:
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    stages = current.get("stages") if isinstance(current.get("stages"), dict) else {}
    stages["survey"] = {
        "version": SURVEY_VERSION,
        "model": SURVEY_MODEL,
        "areas": area_count,
        "failed": failed,
    }
    payload = {"version": 1, "area_count": area_count, "stages": stages}
    atomic_write_json(path, payload)


def run(ctx: common.RunContext) -> int:
    if ctx.review:
        print("survey writes no review images", flush=True)
    problems = common.area_problems(ctx.index)
    for problem in problems:
        print(f"  are problem: {problem}", flush=True)
    errors = ctx.work / "errors.log"
    row_dir = ctx.work / "survey"
    rows: list[dict] = []
    failed: list[str] = []
    total = len(ctx.weds)
    for number, wed in enumerate(ctx.weds, start=1):
        key = f"survey:{wed}"
        started = time.perf_counter()
        try:
            if any(char in wed for char in "\\/:"):
                raise ValueError(f"bad WED name {wed!r}")
            digest = common.source_digest(_sources(ctx.index, wed), SURVEY_VERSION, SURVEY_MODEL)
            row_path = row_dir / f"{wed}.json"
            cached = (
                not ctx.force
                and not ctx.state.fresh(key, digest, SURVEY_VERSION, 1, False)
                and row_path.is_file()
            )
            if cached:
                row = json.loads(row_path.read_text(encoding="utf-8"))
                label = "cached"
            else:
                area = common.load_area(ctx.index, wed)
                row = survey_row(area)
                del area
                atomic_write_json(row_path, row)
                ctx.state.mark(key, digest, SURVEY_VERSION, 1, False, 1)
                label = f"{time.perf_counter() - started:.1f}s"
            rows.append(row)
            print(
                f"survey {wed} {number}/{total} {label} "
                f"lm_std={row['lm_luma_std']:.4f} ht={row['ht_unique']} "
                f"floor={row['floor_fraction']:.3f} walls={row['wall_polygons']} "
                f"doors={row['door_count']} blend={row['blend_black']}",
                flush=True,
            )
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            failed.append(wed)
            _log_error(errors, key, exc)
            print(f"survey {wed} {number}/{total} failed: {exc}", flush=True)
    rows.sort(key=lambda row: row["wed"])
    _write_csv(ctx.work / "survey.csv", rows)
    file_bit, engine_bit = _blend_counts(ctx.index, [row["wed"] for row in rows])
    # Areas whose WED is named by no ARE. blend_black alone cannot say that,
    # because an area can have animations that are not additive.
    grouped = common.areas_by_wed(ctx.index)
    missing_are = [row["wed"] for row in rows if not grouped.get(row["wed"])]
    text = format_summary(rows, failed, file_bit, engine_bit)
    if missing_are:
        text += f"\nWEDs with no ARE: {len(missing_are)}"
        if len(missing_are) <= 20:
            text += "\n  " + " ".join(missing_are)
    if problems:
        text += f"\nARE files that did not parse: {len(problems)}"
    summary_path = ctx.work / "survey_summary.txt"
    atomic_write_bytes(summary_path, (text + "\n").encode("utf-8"))
    ctx.out.mkdir(parents=True, exist_ok=True)
    write_manifest(ctx.out / "manifest.json", len(rows), failed)
    print(text, flush=True)
    if problems:
        return 1
    return 1 if failed else 0
