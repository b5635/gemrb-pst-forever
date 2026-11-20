"""Counts for the upscale dashboard: leftover, stale, incomplete, what to click.

A leftover resource was never upscaled. Stale means the original file or the
upscale settings changed. Incomplete means the last run died before every PNG
was written. Skip is on purpose (cursors, tiny frames).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import ie_formats
from classify import classify
from state import State, output_path, outputs_complete, png_stats, sha1

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
DEFAULT_OUT = Path(r"C:\Games\GemRB\upscaled")
WORK = HERE / "work"
CLASSIFICATION = WORK / "classification.json"
STATE_PATH = WORK / "state.json"
ERRORS_PATH = WORK / "errors.log"

CATEGORIES = ("gui", "areas", "sprites")
CATEGORY_BLURB = {
    "gui": "menus, icons, portraits, fonts",
    "areas": "maps (floors, walls, doors)",
    "sprites": "creatures, spells, ground items",
}


@dataclass
class CategoryCounts:
    name: str
    total: int = 0
    done: int = 0
    leftover: int = 0
    stale: int = 0
    incomplete: int = 0
    untracked: int = 0
    on_disk: int = 0
    bytes: int = 0
    leftover_names: list[str] = field(default_factory=list)
    stale_names: list[str] = field(default_factory=list)
    incomplete_names: list[str] = field(default_factory=list)


@dataclass
class NextClick:
    action: str
    title: str
    body: str
    button: str
    categories: list[str] = field(default_factory=list)


@dataclass
class Report:
    game: Path
    out: Path
    scale: int
    fp16: bool
    hashed: bool
    classification_ok: bool
    venv_ok: bool
    python_exe: Path | None
    game_ok: bool
    models: dict[str, str]
    missing_models: list[str]
    gpu: str
    categories: dict[str, CategoryCounts]
    skip_names: list[str]
    skip_reasons: dict[str, str]
    error_count: int
    tmp_count: int
    bytes: int
    checklist: list[tuple[str, str, str]]
    next: NextClick
    note: str = ""


def venv_python() -> Path | None:
    for name in ("python.exe", "pythonw.exe"):
        path = HERE / ".venv" / "Scripts" / name
        if path.is_file():
            return path
    return None


def load_classification(path: Path | None = None) -> dict | None:
    path = path or CLASSIFICATION
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def recount_classification(game: Path, work: Path | None = None) -> dict:
    work = work or WORK
    work.mkdir(parents=True, exist_ok=True)
    index = ie_formats.ResourceIndex(game, work / "bifcache")
    report = classify(index, REPO)
    dest = work / "classification.json"
    dest.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _error_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.startswith("Traceback"))


def _tmp_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*.tmp") if path.is_file())


def _resolve_models():
    from upscale import CANDIDATES, _resolve_model, _scan_models

    files = _scan_models(HERE / "models")
    chosen: dict[str, str] = {}
    missing: list[str] = []
    for category in CATEGORIES:
        path = _resolve_model(category, None, files)
        if path is None:
            missing.append(category)
        else:
            chosen[category] = path.name
    return chosen, missing, CANDIDATES


def _settings_match(prev: dict, model: str, scale: int, fp16: bool) -> bool:
    return (
        prev.get("model") == model
        and prev.get("scale") == scale
        and bool(prev.get("fp16")) == bool(fp16)
    )


def _kind_for(prev: dict | None, on_disk: int, model: str, scale: int, fp16: bool, digest: str | None) -> tuple[str, str]:
    if prev is None:
        if on_disk:
            return "untracked", "PNG files exist, but they are not in the upscale log"
        return "leftover", "never upscaled"
    expected = int(prev.get("outputs") or 0)
    if not outputs_complete(on_disk, expected):
        return "incomplete", f"on disk {on_disk}, last run wrote {expected}"
    if digest is not None and prev.get("sha1") != digest:
        return "stale", "the original file changed"
    if not _settings_match(prev, model, scale, fp16):
        why = []
        if prev.get("model") != model:
            why.append(f"model was {prev.get('model')}")
        if prev.get("scale") != scale:
            why.append(f"scale was {prev.get('scale')}")
        if bool(prev.get("fp16")) != bool(fp16):
            why.append("fp16 setting changed")
        return "stale", ", ".join(why) or "settings changed"
    return "done", ""


def _empty_counts() -> dict[str, CategoryCounts]:
    return {name: CategoryCounts(name=name) for name in CATEGORIES}


def _index_report(data: dict) -> tuple[dict[str, CategoryCounts], list[str], dict[str, str]]:
    counts = _empty_counts()
    skip_names: list[str] = []
    skip_reasons: dict[str, str] = {}
    for category, rows in data.get("items", {}).items():
        if category == "skip":
            for row in rows:
                skip_names.append(row["name"])
                skip_reasons[row["name"]] = row.get("reason") or "skip"
            continue
        if category not in counts:
            continue
        counts[category].total = len(rows)
    return counts, skip_names, skip_reasons


def scan(
    out: Path | None = None,
    game: Path | None = None,
    scale: int = 2,
    fp16: bool = True,
    hash_sources: bool = False,
    reclassify: bool = False,
    query_gpu: bool = False,
    progress=None,
    work: Path | None = None,
) -> Report:
    out = Path(out) if out else DEFAULT_OUT
    game = Path(game) if game else DEFAULT_GAME
    work = Path(work) if work else WORK
    classification_path = work / "classification.json"
    state_path = work / "state.json"
    python_exe = venv_python()
    venv_ok = python_exe is not None
    game_ok = (game / "CHITIN.KEY").is_file() or (game / "chitin.key").is_file()
    models, missing_models, _candidates = _resolve_models()
    data = None
    note = ""
    if reclassify:
        if not game_ok:
            note = f"Game not found at {game}"
        else:
            if progress:
                progress("Indexing the game and classifying art...")
            data = recount_classification(game, work)
    if data is None:
        data = load_classification(classification_path)
    counts, skip_names, skip_reasons = (
        _index_report(data) if data else (_empty_counts(), [], {})
    )
    classification_ok = data is not None
    state = State(state_path)

    digest_by_key: dict[str, str] = {}
    if hash_sources and classification_ok and game_ok:
        digest_by_key = _hash_sources(game, data, progress, work)

    hashed = bool(hash_sources)
    items = data.get("items", {}) if data else {}
    total_items = sum(len(items.get(name, [])) for name in CATEGORIES)
    seen = 0
    for category in CATEGORIES:
        rows = items.get(category, [])
        bucket = counts[category]
        model = models.get(category, "")
        for row in rows:
            seen += 1
            if progress and seen % 25 == 0:
                progress(f"Counting {category} {seen}/{total_items}...")
            name = row["name"]
            ext = row["ext"]
            key = f"{category}:{ext}:{name}"
            path = output_path(out, category, ext, name)
            on_disk, nbytes = png_stats(path)
            prev = state.items.get(key)
            digest = digest_by_key.get(key)
            kind, reason = _kind_for(prev, on_disk, model, scale, fp16, digest)
            bucket.on_disk += on_disk
            bucket.bytes += nbytes
            if kind == "done":
                bucket.done += 1
            elif kind == "untracked":
                bucket.untracked += 1
                bucket.done += 1
            elif kind == "leftover":
                bucket.leftover += 1
                bucket.leftover_names.append(name)
            elif kind == "stale":
                bucket.stale += 1
                bucket.stale_names.append(name)
            elif kind == "incomplete":
                bucket.incomplete += 1
                bucket.incomplete_names.append(name)

    total_bytes = sum(bucket.bytes for bucket in counts.values())
    if not venv_ok:
        gpu = "GPU environment is not set up yet"
    elif query_gpu:
        gpu = _gpu_label(python_exe)
    else:
        gpu = "not checked yet"
    nxt = recommend(counts, venv_ok, missing_models, classification_ok, game_ok, hashed)
    checklist = build_checklist(counts, venv_ok, missing_models, classification_ok, game_ok)
    if not classification_ok:
        note = note or 'No classification yet. Click "Scan the game files" once.'
    elif hashed:
        note = note or "Stale numbers compared the original files to what was upscaled."
    else:
        note = note or (
            "Stale so far only means the model or scale changed. "
            'Click "Check for stale art" to compare against the original files.'
        )
    return Report(
        game=game,
        out=out,
        scale=scale,
        fp16=fp16,
        hashed=hashed,
        classification_ok=classification_ok,
        venv_ok=venv_ok,
        python_exe=python_exe,
        game_ok=game_ok,
        models=models,
        missing_models=missing_models,
        gpu=gpu,
        categories=counts,
        skip_names=skip_names,
        skip_reasons=skip_reasons,
        error_count=_error_count(work / "errors.log"),
        tmp_count=_tmp_count(out) + _tmp_count(work),
        bytes=total_bytes,
        checklist=checklist,
        next=nxt,
        note=note,
    )


def _hash_sources(game: Path, data: dict, progress=None, work: Path | None = None) -> dict[str, str]:
    """Hash originals that were already upscaled. Leftover files are not hashed."""
    from upscale import _wed_fingerprint

    work = work or WORK
    if progress:
        progress("Opening the game files...")
    index = ie_formats.ResourceIndex(game, work / "bifcache")
    state = State(work / "state.json")
    want = set(state.items)
    if not want:
        return {}
    wed: dict[str, list] = {}
    need_areas = any(key.startswith("areas:") for key in want)
    if need_areas:
        try:
            import extract as extract_mod
        except ImportError:
            extract_mod = None
        if extract_mod is not None:
            if progress:
                progress("Reading area layouts (WED)...")
            for name in index.names("wed"):
                try:
                    overlays = extract_mod.read_wed(index.get(name, "wed"))
                except Exception:
                    continue
                for i, overlay in enumerate(overlays):
                    tis = overlay["tis"]
                    if not tis:
                        continue
                    prev = wed.get(tis)
                    if prev is None or (i == 0 and prev and prev[0]["tis"] != tis):
                        wed[tis] = overlays
    rows = []
    for category in CATEGORIES:
        for row in data.get("items", {}).get(category, []):
            key = f"{category}:{row['ext']}:{row['name']}"
            if key in want:
                rows.append((category, row, key))
    found: dict[str, str] = {}
    for i, (category, row, key) in enumerate(rows, 1):
        if progress and i % 10 == 0:
            progress(f"Comparing originals {i}/{len(rows)} {row['name']}...")
        try:
            blob = index.get(row["name"], row["ext"])
            extra = b""
            if row["ext"] == "tis":
                extra = _wed_fingerprint(wed.get(row["name"], []), row["name"])
            found[key] = sha1(blob + extra)
        except Exception:
            continue
    return found


def _gpu_label(python_exe: Path | None) -> str:
    if python_exe is None:
        return "no venv"
    try:
        import subprocess

        proc = subprocess.run(
            [
                str(python_exe),
                "-c",
                "import torch; ok=torch.cuda.is_available(); "
                "print(torch.cuda.get_device_name(0) if ok else 'CUDA not available')",
            ],
            capture_output=True,
            text=True,
            timeout=40,
            cwd=str(HERE),
        )
    except Exception as exc:
        return f"could not query the GPU ({exc})"
    line = (proc.stdout or proc.stderr or "").strip().splitlines()
    if proc.returncode != 0:
        return line[-1] if line else "CUDA not available"
    return line[-1] if line else "CUDA not available"


def recommend(
    counts: dict[str, CategoryCounts],
    venv_ok: bool,
    missing_models: list[str],
    classification_ok: bool,
    game_ok: bool,
    hashed: bool,
) -> NextClick:
    if not venv_ok:
        return NextClick(
            "setup",
            "Set up the GPU environment first",
            "This only has to be done once. It installs PyTorch with CUDA into tools\\upscale\\.venv.",
            "Set up the GPU environment",
        )
    if not game_ok:
        return NextClick(
            "none",
            "The game folder is missing",
            "CHITIN.KEY was not found at the usual Planescape: Torment path. "
            "Install classic PST (1.1 + Fixpack + UB) and scan again.",
            "",
        )
    if not classification_ok:
        return NextClick(
            "scan",
            "Scan the game files once",
            "That builds the list of GUI, maps, and sprites so the leftover counts are real.",
            "Scan the game files",
        )
    leftover_cats = [name for name in CATEGORIES if counts[name].leftover]
    incomplete_cats = [name for name in CATEGORIES if counts[name].incomplete]
    stale_cats = [name for name in CATEGORIES if counts[name].stale]
    continue_cats = [name for name in CATEGORIES if counts[name].leftover or counts[name].incomplete]
    needed = continue_cats or stale_cats
    blocked = [name for name in needed if name in missing_models]
    if blocked:
        return NextClick(
            "none",
            "Put the upscale model in tools\\upscale\\models",
            "Nothing is downloaded automatically. Drop a 4x-UltraSharp .safetensors "
            f"(or .pth) file there, then continue. Needed for: {', '.join(blocked)}.",
            "",
        )
    if continue_cats:
        label = _join_cats(continue_cats)
        left = sum(counts[name].leftover for name in continue_cats)
        incomplete = sum(counts[name].incomplete for name in continue_cats)
        bits = []
        if left:
            bits.append(f"{left:,} left")
        if incomplete:
            bits.append(f"{incomplete:,} incomplete")
        return NextClick(
            "continue",
            f"{' and '.join(bits)} ({label})",
            "This continues where the last run stopped. Finished files are skipped. "
            "Safe to stop and start again. The first full GUI+maps pass took hours; "
            "sprites will too.",
            f"Continue {label}",
            continue_cats,
        )
    if stale_cats:
        label = _join_cats(stale_cats)
        n = sum(counts[name].stale for name in stale_cats)
        return NextClick(
            "stale",
            f"{n:,} file{'s' if n != 1 else ''} are stale and should be redone",
            "The original art or the model/scale changed since these PNGs were written.",
            f"Redo stale {label}",
            stale_cats,
        )
    if not hashed:
        return NextClick(
            "hash",
            "GUI, maps, and sprites look complete",
            'Click "Check for stale art" if you changed the game files (Fixpack, override, '
            "or a new model). That compares each original to what was already upscaled.",
            "Check for stale art",
        )
    return NextClick(
        "none",
        "Nothing is waiting",
        "GUI, maps, and sprites match the current originals and settings. "
        'Use "Regenerate checked categories" only if you want to force a fresh pass.',
        "",
    )


def _join_cats(names: list[str]) -> str:
    pretty = {"gui": "GUI", "areas": "maps", "sprites": "sprites"}
    words = [pretty.get(name, name) for name in names]
    if len(words) == 1:
        return words[0]
    return " and ".join([", ".join(words[:-1]), words[-1]]) if len(words) > 2 else " and ".join(words)


def build_checklist(
    counts: dict[str, CategoryCounts],
    venv_ok: bool,
    missing_models: list[str],
    classification_ok: bool,
    game_ok: bool,
) -> list[tuple[str, str, str]]:
    def mark(done: bool) -> str:
        return "done" if done else "todo"

    gui = counts["gui"]
    areas = counts["areas"]
    sprites = counts["sprites"]
    rows = [
        (mark(venv_ok), "GPU environment", "tools\\upscale\\.venv with CUDA PyTorch"),
        (
            mark(not missing_models),
            "Upscale models",
            "4x-UltraSharp (and optional Nomos / FatalPixels) in tools\\upscale\\models",
        ),
        (mark(game_ok), "Classic PST install", str(DEFAULT_GAME)),
        (mark(classification_ok), "Art list from the game", "classification of every TIS / MOS / BAM"),
        (
            mark(gui.total > 0 and gui.leftover == 0 and gui.incomplete == 0 and gui.stale == 0),
            f"GUI art  ({gui.done:,} / {gui.total:,})" if gui.total else "GUI art",
            CATEGORY_BLURB["gui"],
        ),
        (
            mark(areas.total > 0 and areas.leftover == 0 and areas.incomplete == 0 and areas.stale == 0),
            f"Area maps  ({areas.done:,} / {areas.total:,})" if areas.total else "Area maps",
            CATEGORY_BLURB["areas"],
        ),
        (
            mark(sprites.total > 0 and sprites.leftover == 0 and sprites.incomplete == 0 and sprites.stale == 0),
            f"Sprites  ({sprites.done:,} / {sprites.total:,})" if sprites.total else "Sprites",
            CATEGORY_BLURB["sprites"],
        ),
        ("later", "Cursors and movies", "not in this tool yet (hot spots / video pipeline)"),
        ("later", "Look at it in game", "after a run: bigger window or zoom, then compare"),
    ]
    return rows


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def format_report(report: Report) -> str:
    lines = [
        "PST art upscaler",
        "================",
        f"GPU: {report.gpu}",
        f"Game: {report.game}  ({'found' if report.game_ok else 'MISSING'})",
        f"Output: {report.out}  ({format_bytes(report.bytes)})",
    ]
    if report.models:
        bits = [f"{cat}={name}" for cat, name in report.models.items()]
        lines.append("Models: " + ", ".join(bits))
    if report.missing_models:
        lines.append("Missing models: " + ", ".join(report.missing_models))
    lines += ["", "What to click", "-------------", report.next.title, report.next.body]
    if report.next.button:
        lines.append(f"Button: {report.next.button}")
    lines += [
        "",
        "Counts",
        "------",
        f"{'Category':<10} {'Total':>7} {'Done':>7} {'Left':>7} {'Stale':>7} {'Incomplete':>11}",
    ]
    for name in CATEGORIES:
        bucket = report.categories[name]
        lines.append(
            f"{name:<10} {bucket.total:>7,} {bucket.done:>7,} {bucket.leftover:>7,} "
            f"{bucket.stale:>7,} {bucket.incomplete:>11,}"
        )
        lines.append(f"           {CATEGORY_BLURB[name]}")
    if report.skip_names:
        lines.append(
            f"Skipped on purpose: {len(report.skip_names)} "
            f"({', '.join(report.skip_names)})"
        )
    if report.error_count:
        lines.append(f"Logged errors: {report.error_count}  (work\\errors.log)")
    if report.tmp_count:
        lines.append(f"Leftover .tmp files: {report.tmp_count} (cleaned on the next run)")
    lines += ["", "What's left to do", "-----------------"]
    for state, title, detail in report.checklist:
        mark = {"done": "[x]", "todo": "[ ]", "later": "[.]"}[state]
        lines.append(f"{mark} {title}  - {detail}")
    lines += ["", report.note]
    for name in CATEGORIES:
        bucket = report.categories[name]
        if bucket.leftover_names:
            sample = ", ".join(bucket.leftover_names[:12])
            extra = f" (+{bucket.leftover - 12} more)" if bucket.leftover > 12 else ""
            lines.append(f"Leftover {name}: {sample}{extra}")
        if bucket.stale_names:
            sample = ", ".join(bucket.stale_names[:12])
            extra = f" (+{bucket.stale - 12} more)" if bucket.stale > 12 else ""
            lines.append(f"Stale {name}: {sample}{extra}")
        if bucket.incomplete_names:
            sample = ", ".join(bucket.incomplete_names[:12])
            extra = f" (+{bucket.incomplete - 12} more)" if bucket.incomplete > 12 else ""
            lines.append(f"Incomplete {name}: {sample}{extra}")
    return "\n".join(lines) + "\n"


def write_name_lists(report: Report, work: Path | None = None) -> None:
    work = work or WORK
    work.mkdir(parents=True, exist_ok=True)
    for name in CATEGORIES:
        bucket = report.categories[name]
        (work / f"leftover-{name}.txt").write_text(
            "\n".join(bucket.leftover_names) + ("\n" if bucket.leftover_names else ""),
            encoding="utf-8",
        )
        (work / f"stale-{name}.txt").write_text(
            "\n".join(bucket.stale_names) + ("\n" if bucket.stale_names else ""),
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show leftover / stale upscale counts.")
    parser.add_argument("--hash", action="store_true", help="compare original files (slower)")
    parser.add_argument("--from-game", action="store_true", help="reclassify from CHITIN.KEY")
    parser.add_argument("--game", default=str(DEFAULT_GAME))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--fp16", action="store_true", default=True)
    parser.add_argument("--no-fp16", action="store_false", dest="fp16")
    parser.add_argument("--gpu", action="store_true", help="query CUDA (imports PyTorch)")
    args = parser.parse_args(argv)

    def progress(message: str) -> None:
        print(message, flush=True)

    report = scan(
        out=Path(args.out),
        game=Path(args.game),
        scale=args.scale,
        fp16=args.fp16,
        hash_sources=args.hash,
        reclassify=args.from_game,
        query_gpu=args.gpu,
        progress=progress,
    )
    write_name_lists(report)
    print(format_report(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
