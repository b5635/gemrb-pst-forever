"""Offline scene data for Planescape: Torment areas.

    python scenegen.py --stage survey|lights|depth|surface|detect|all
           [--only WED[,WED]] [--limit N] [--force] [--review]
           [--game "C:\\Program Files (x86)\\Black Isle\\Torment"]
           [--out "D:\\Games\\GemRB\\upscaled\\lighting"]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import common
import ie_formats
from state import State, cleanup_tmp

import detect
import depth
import lights
import surface
import survey


def _select(index: ie_formats.ResourceIndex, only: str, limit: int) -> list[str]:
    known = index.names("wed")
    if only:
        selected = [part.strip().upper() for part in only.split(",") if part.strip()]
    else:
        selected = list(known)
    if limit:
        selected = selected[:limit]
    seen: set[str] = set()
    ordered: list[str] = []
    for wed in selected:
        if wed in seen:
            continue
        seen.add(wed)
        ordered.append(wed)
    return ordered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate offline scene data for PST areas.")
    parser.add_argument("--stage", required=True, choices=["survey", "lights", "depth", "surface", "detect", "all"])
    parser.add_argument("--only", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--game", default=str(common.DEFAULT_GAME))
    parser.add_argument("--out", default=str(common.DEFAULT_OUT))
    parser.add_argument("--depth-input", type=int, default=1036, choices=[518, 1036])
    parser.add_argument("--depth-model", default="")
    args = parser.parse_args(argv)
    args.game = Path(args.game)
    args.out = Path(args.out)
    if not (args.game / "CHITIN.KEY").is_file() and not (args.game / "chitin.key").is_file():
        print(f"Game not found (no CHITIN.KEY) at {args.game}")
        return 1

    stages = ["survey", "lights", "depth", "surface", "detect"] if args.stage == "all" else [args.stage]
    runners = {
        "survey": survey.run,
        "lights": lights.run,
        "depth": depth.run,
        "surface": surface.run,
        "detect": detect.run,
    }

    work = common.WORK
    work.mkdir(parents=True, exist_ok=True)
    cleanup_tmp(work)
    print(f"Indexing {args.game} ...", flush=True)
    index = ie_formats.ResourceIndex(args.game, common.BIF_CACHE)
    print(
        f"  {len(index)} resources, {index.found_bifs} bif files, {len(index.missing_bifs)} missing",
        flush=True,
    )
    if len(index) == 0:
        print("The KEY/BIF index is empty. Check the game path and bif layout.")
        return 1
    weds = _select(index, args.only, args.limit)
    if not weds:
        print("No WED resources selected.")
        return 1
    ctx = common.RunContext(
        index=index,
        weds=weds,
        force=args.force,
        review=args.review,
        out=args.out,
        work=work,
        state=State(work / "state.json"),
        game=args.game,
        depth_input=int(args.depth_input),
        depth_model=str(args.depth_model or ""),
    )
    for stage in stages:
        code = runners[stage](ctx)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped. Finished areas are in the state file; rerun to continue.")
        sys.exit(130)
