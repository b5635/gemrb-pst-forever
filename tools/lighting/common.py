"""Shared paths, area loading and the map files the engine reads.

Imports `ie_formats`, `extract` and `state` from tools/upscale. The camera
constants match LIGHTING_PLAN.md section 3 and are shared with the shader later:

    sin(elev) = 0.75, because a search cell is 16 x 12.
    T = tan^2(elev) = sin^2 / cos^2 = 0.5625 / 0.4375.
    Moving up a floor changes depth by +1 per screen pixel (floor depth is
    normalised to -y). Moving up a vertical surface changes it by -T.
"""

from __future__ import annotations

import io
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion

_UPSCALE = Path(__file__).resolve().parent.parent / "upscale"
if str(_UPSCALE) not in sys.path:
    sys.path.insert(0, str(_UPSCALE))

import extract  # noqa: E402
import ie_formats  # noqa: E402
from state import atomic_write_bytes  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORK = HERE / "work"
BIF_CACHE = _UPSCALE / "work" / "bifcache"
TERRAIN_2DA = REPO / "gemrb" / "unhardcoded" / "pst" / "terrain.2da"

DEFAULT_GAME = Path(r"C:\Program Files (x86)\Black Isle\Torment")
DEFAULT_OUT = Path(r"D:\Games\GemRB\upscaled\lighting")

# Exact values from the plan. T is 0.5625 / 0.4375, not a rounded literal.
ELEV_SIN = 0.75
T = 0.5625 / 0.4375
ONE_PLUS_T = 1.0 + T

CELL_W = 16
CELL_H = 12

# PST file bit that AREImporter::AdjustPSTFlags copies onto the runtime
# BlendBlack flag (AreaAnimation::Flags::Background == 0x100). That runtime
# flag is what Map::CollectSceneLights turns into a light. The generic IE
# BlendBlack bit is 0x2, and PST does not use it for this.
PST_BLEND_BIT = 0x100

WF_HOVER = 4
_POLY_SIZE = 0x12
_DOOR_SIZE = 0x1A

_MAP_HEADER = struct.Struct("<4sIIIIfII")


@dataclass
class MapHeader:
    magic: bytes
    version: int
    w: int
    h: int
    texel: int
    unit: float


@dataclass
class Area:
    wed: str
    tis: str
    rgb: np.ndarray
    alpha: np.ndarray
    lm: np.ndarray
    sr: np.ndarray
    ht: np.ndarray
    walkable: np.ndarray
    walls: list[np.ndarray]
    doors: list[np.ndarray]
    wall_count: int
    door_count: int
    wall_mask: np.ndarray
    floor_mask: np.ndarray
    anims: list[tuple[int, int, str, int]]


@dataclass
class RunContext:
    index: ie_formats.ResourceIndex
    weds: list[str]
    force: bool
    review: bool
    out: Path
    work: Path
    state: object
    game: Path


_WALKABLE: set[int] | None = None
_AREA_CACHE: dict[int, dict[str, list[tuple[str, bytes, list]]]] = {}
_AREA_PROBLEMS: dict[int, list[str]] = {}


def walkable_indices(text: str) -> set[int]:
    """Search-map values whose terrain.2da PASSABLE cell is 1 or 3."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("2DA"):
            continue
        rows.append(line.split())
    labels: list[str] | None = None
    data_rows: list[list[str]] = []
    for i, row in enumerate(rows):
        if row[0] == "*":
            if i + 2 > len(rows):
                break
            labels = [part.lower() for part in rows[i + 1]]
            data_rows = rows[i + 2 :]
            break
    if labels is None:
        raise ValueError("terrain.2da has no default row")
    column = {label: index for index, label in enumerate(labels)}
    for row in data_rows:
        if not row or row[0].upper() != "PASSABLE":
            continue
        values = row[1:]
        found: set[int] = set()
        for nibble in range(16):
            key = format(nibble, "x")
            index = column.get(key)
            if index is None or index >= len(values):
                raise ValueError(f"PASSABLE has no column {key}")
            if int(values[index]) in (1, 3):
                found.add(nibble)
        return found
    raise ValueError("terrain.2da has no PASSABLE row")


def walkable_set() -> set[int]:
    global _WALKABLE
    if _WALKABLE is None:
        _WALKABLE = walkable_indices(TERRAIN_2DA.read_text(encoding="utf-8"))
    return _WALKABLE


def map_resref(wed: str, suffix: str) -> str:
    """LM/SR/HT stem. The engine keeps six characters of the WED, then the suffix."""
    return f"{wed.upper()[:6]}{suffix}"


def require_resource(index: ie_formats.ResourceIndex, name: str, ext: str) -> bytes:
    name = name.upper()
    ext = ext.lower()
    if not index.has(name, ext):
        raise KeyError(f"missing {name}.{ext}")
    return index.get(name, ext)


def source_parts(index: ie_formats.ResourceIndex, wed: str) -> list[bytes]:
    """TIS, WED, LM, SR, then every ARE that names this WED. Same for every stage."""
    wed_bytes = require_resource(index, wed, "wed")
    overlays = extract.read_wed(wed_bytes)
    if not overlays or not overlays[0].get("tis"):
        raise ValueError(f"{wed} has no primary tileset")
    tis = overlays[0]["tis"]
    parts = [
        require_resource(index, tis, "tis"),
        wed_bytes,
        require_resource(index, map_resref(wed, "LM"), "bmp"),
        require_resource(index, map_resref(wed, "SR"), "bmp"),
    ]
    records = sorted(areas_by_wed(index).get(wed, []), key=lambda rec: rec[0])
    for name, data, _anims in records:
        parts.append(name.encode("ascii"))
        parts.append(data)
    return parts


def source_digest(parts: list[bytes], version: str, model: str) -> str:
    """sha1 of the plan's source list: TIS, WED, LM, SR, each ARE, version, model."""
    import hashlib

    hasher = hashlib.sha1()
    for part in parts:
        hasher.update(struct.pack("<Q", len(part)))
        hasher.update(part)
    tail = f"{version}\0{model}".encode("utf-8")
    hasher.update(struct.pack("<Q", len(tail)))
    hasher.update(tail)
    return hasher.hexdigest()


def encode_map(magic: bytes, w: int, h: int, texel: int, unit: float, payload: bytes, bytes_per_texel: int) -> bytes:
    if len(magic) != 4:
        raise ValueError("map magic must be 4 bytes")
    if w <= 0 or h <= 0:
        raise ValueError("map size must be positive")
    expect = w * h * bytes_per_texel
    if len(payload) != expect:
        raise ValueError(f"map payload {len(payload)} bytes, expected {expect}")
    header = _MAP_HEADER.pack(magic, 1, w, h, texel, float(unit), 0, 0)
    return header + payload


def write_map(path: Path, magic: bytes, w: int, h: int, texel: int, unit: float, payload: bytes, bytes_per_texel: int) -> None:
    atomic_write_bytes(path, encode_map(magic, w, h, texel, unit, payload, bytes_per_texel))


def read_map(blob: bytes, magic: bytes, bytes_per_texel: int) -> tuple[MapHeader, bytes]:
    if len(blob) < _MAP_HEADER.size:
        raise ValueError("map header truncated")
    got, version, w, h, texel, unit, _reserved0, _reserved1 = _MAP_HEADER.unpack_from(blob, 0)
    if got != magic:
        raise ValueError(f"map magic {got!r} is not {magic!r}")
    if version != 1 or w <= 0 or h <= 0:
        raise ValueError("bad map header")
    payload = blob[_MAP_HEADER.size :]
    expect = w * h * bytes_per_texel
    if len(payload) != expect:
        raise ValueError(f"map payload {len(payload)} bytes, expected {expect}")
    return MapHeader(got, version, w, h, texel, float(unit)), payload


def _polygon_at(data: bytes, poly_off: int, vert_off: int, index: int) -> np.ndarray | None:
    base = poly_off + index * _POLY_SIZE
    if base + _POLY_SIZE > len(data):
        return None
    first, count = struct.unpack_from("<II", data, base)
    flags = data[base + 8]
    min_x, max_x, min_y, max_y = struct.unpack_from("<4H", data, base + 10)
    # Width or height of 0 is not a polygon. PST AR0600 has one of these.
    if max_x <= min_x or max_y <= min_y:
        return None
    if flags & WF_HOVER:
        # The first two vertices are the baseline, not the outline.
        if count < 5:
            return None
        first += 2
        count -= 2
    if count < 3 or count > 8192 or first > 1_000_000:
        return None
    start = vert_off + first * 4
    end = start + count * 4
    if end > len(data):
        return None
    points = np.frombuffer(data[start:end], dtype="<u2").reshape(count, 2)
    return points.astype(np.int32, copy=True)


def read_wed_polygons(data: bytes) -> tuple[list[np.ndarray], list[np.ndarray], int, int]:
    """Wall polygons, door polygons (open and closed), and the header counts.

    Layout matches WEDImporter: secondary header at 0x14, polygon record 0x12,
    door record 0x1A with the open/closed pair at 0x0E.
    """
    if data[:8] != b"WED V1.3":
        raise ValueError("not a WED V1.3")
    if len(data) < 0x20:
        raise ValueError("WED header truncated")
    door_count = struct.unpack_from("<I", data, 0x0C)[0]
    sec_off = struct.unpack_from("<I", data, 0x14)[0]
    door_off = struct.unpack_from("<I", data, 0x18)[0]
    if sec_off + 20 > len(data):
        raise ValueError("WED secondary header truncated")
    wall_count, poly_off, vert_off = struct.unpack_from("<3I", data, sec_off)
    if wall_count > 100_000 or door_count > 4096:
        raise ValueError(f"implausible WED counts walls={wall_count} doors={door_count}")

    walls: list[np.ndarray] = []
    for index in range(wall_count):
        points = _polygon_at(data, poly_off, vert_off, index)
        if points is not None:
            walls.append(points)

    doors: list[np.ndarray] = []
    for index in range(door_count):
        base = door_off + index * _DOOR_SIZE
        if base + _DOOR_SIZE > len(data):
            break
        open_n, closed_n, open_at, closed_at = struct.unpack_from("<HHII", data, base + 0x0E)
        for count, at in ((open_n, open_at), (closed_n, closed_at)):
            if count == 0 or at < poly_off:
                continue
            if count > 4096:
                raise ValueError(f"implausible door polygon count {count}")
            start = (at - poly_off) // _POLY_SIZE
            for offset in range(count):
                points = _polygon_at(data, poly_off, vert_off, start + offset)
                if points is not None:
                    doors.append(points)
    return walls, doors, wall_count, door_count


def read_area_anims(data: bytes) -> tuple[str, list[tuple[int, int, str, int]]]:
    """WED resref and `(x, y, bam, flags)` for an AREAV1.0 file.

    Header: WED at 0x08, animation count at 0xAC, animation offset at 0xB0.
    Each animation is 0x4C bytes: x at 0x20, y at 0x22, BAM at 0x28, flags at 0x34.
    """
    if len(data) < 8 or data[:8] != b"AREAV1.0":
        raise ValueError(f"unexpected ARE signature {data[:8]!r}")
    wed = ie_formats.resref(data[8:16])
    if len(data) < 0xB4:
        raise ValueError("ARE header truncated")
    count = struct.unpack_from("<I", data, 0xAC)[0]
    offset = struct.unpack_from("<I", data, 0xB0)[0]
    if count > 4096:
        raise ValueError(f"implausible animation count {count}")
    anims: list[tuple[int, int, str, int]] = []
    for index in range(count):
        base = offset + index * 0x4C
        if base + 0x4C > len(data):
            break
        x, y = struct.unpack_from("<2H", data, base + 0x20)
        bam = ie_formats.resref(data[base + 0x28 : base + 0x30])
        flags = struct.unpack_from("<I", data, base + 0x34)[0]
        anims.append((x, y, bam, flags))
    return wed, anims


def areas_by_wed(index: ie_formats.ResourceIndex) -> dict[str, list[tuple[str, bytes, list]]]:
    """Every ARE that names a WED: `(resref, bytes, anims)`, cached per index."""
    key = id(index)
    cached = _AREA_CACHE.get(key)
    if cached is not None:
        return cached
    grouped: dict[str, list[tuple[str, bytes, list]]] = {}
    problems: list[str] = []
    for name in index.names("are"):
        data = index.get(name, "are")
        try:
            wed, anims = read_area_anims(data)
        except ValueError as exc:
            problems.append(f"{name}.are: {exc}")
            continue
        grouped.setdefault(wed, []).append((name, data, anims))
    _AREA_CACHE[key] = grouped
    _AREA_PROBLEMS[key] = problems
    return grouped


def area_problems(index: ie_formats.ResourceIndex) -> list[str]:
    areas_by_wed(index)
    return list(_AREA_PROBLEMS.get(id(index), []))


def fill_mask(height: int, width: int, polygons: list[np.ndarray]) -> np.ndarray:
    """True where a pixel is inside any polygon. Coordinates are area pixels, x right, y down."""
    mask = np.zeros((height, width), dtype=np.uint8)
    shapes = []
    for poly in polygons:
        if len(poly) < 3:
            continue
        shapes.append(np.ascontiguousarray(poly, dtype=np.int32).reshape(-1, 1, 2))
    if shapes:
        cv2.fillPoly(mask, shapes, 1)
    return mask.astype(bool)


def make_floor_mask(walkable: np.ndarray, wall_mask: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Walkable cells eroded by one cell, upsampled, excluding walls and transparent pixels.

    Erosion is 8-connected, so a kept cell is walkable together with every
    neighbour, corners included. A cell the search map does not cover (the
    bitmap is short, or the pixel is past the grid) stays unknown, not floor.
    """
    height, width = wall_mask.shape
    cells = np.zeros((height, width), dtype=bool)
    if walkable.size and height and width:
        structure = np.ones((3, 3), dtype=bool)
        eroded = binary_erosion(np.asarray(walkable, dtype=bool), structure=structure, border_value=0)
        if eroded.size:
            ys = np.arange(height) // CELL_H
            xs = np.arange(width) // CELL_W
            y_ok = ys < eroded.shape[0]
            x_ok = xs < eroded.shape[1]
            ys_c = np.clip(ys, 0, eroded.shape[0] - 1)
            xs_c = np.clip(xs, 0, eroded.shape[1] - 1)
            sampled = np.asarray(eroded[ys_c][:, xs_c], dtype=bool)
            sampled[~y_ok, :] = False
            sampled[:, ~x_ok] = False
            cells = sampled
    return cells & ~wall_mask & (alpha == 255)


def _paletted(data: bytes, label: str) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    if image.mode != "P":
        image.close()
        raise ValueError(f"{label} mode is {image.mode}, expected P")
    return image


def decode_indices(data: bytes, label: str) -> np.ndarray:
    image = _paletted(data, label)
    try:
        return np.array(image, dtype=np.uint8)
    finally:
        image.close()


def decode_height(data: bytes) -> np.ndarray:
    """Elevation per cell: the palette red, which is what MakeTileProps stores."""
    image = _paletted(data, "height map")
    try:
        indices = np.array(image, dtype=np.uint8)
        palette = image.getpalette() or []
        if not palette:
            raise ValueError("height map has no palette")
        red = np.zeros(256, dtype=np.uint8)
        reds = palette[0::3]
        red[: len(reds)] = np.asarray(reds, dtype=np.uint8)
        return red[indices]
    finally:
        image.close()


def load_area(index: ie_formats.ResourceIndex, wed: str) -> Area:
    """Stitch one WED and the maps, walls and animations that belong to it."""
    wed = wed.strip().upper()
    wed_bytes = require_resource(index, wed, "wed")
    overlays = extract.read_wed(wed_bytes)
    if not overlays or not overlays[0].get("tis"):
        raise ValueError(f"{wed} has no primary tileset")
    tis = overlays[0]["tis"]
    tiles = extract.decode_tis_tiles(require_resource(index, tis, "tis"))
    image = extract.area_plan(tiles, overlays, tis)["image"]
    if image is None or image.ndim != 3 or image.shape[2] < 4 or image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError(f"{wed} stitch produced no image")
    rgb = image[:, :, :3].astype(np.float32) * np.float32(1.0 / 255.0)
    alpha = np.ascontiguousarray(image[:, :, 3])

    lm_rgba = extract.decode_bmp(require_resource(index, map_resref(wed, "LM"), "bmp"))
    lm = lm_rgba[:, :, :3].astype(np.float32) * np.float32(1.0 / 255.0)
    sr = decode_indices(require_resource(index, map_resref(wed, "SR"), "bmp"), "search map")
    ht = decode_height(require_resource(index, map_resref(wed, "HT"), "bmp"))

    allowed = np.zeros(256, dtype=bool)
    for value in walkable_set():
        allowed[value] = True
    walkable = allowed[sr]

    walls, doors, wall_count, door_count = read_wed_polygons(wed_bytes)
    height, width = rgb.shape[:2]
    wall_mask = fill_mask(height, width, walls + doors)
    floor_mask = make_floor_mask(walkable, wall_mask, alpha)

    anims: list[tuple[int, int, str, int]] = []
    for _name, _data, found in areas_by_wed(index).get(wed, []):
        anims.extend(found)

    return Area(
        wed=wed,
        tis=tis,
        rgb=rgb,
        alpha=alpha,
        lm=lm,
        sr=sr,
        ht=ht,
        walkable=walkable,
        walls=walls,
        doors=doors,
        wall_count=wall_count,
        door_count=door_count,
        wall_mask=wall_mask,
        floor_mask=floor_mask,
        anims=anims,
    )
