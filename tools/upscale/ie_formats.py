"""Read Planescape: Torment resources the way GemRB does: override, then KEY/BIF.

Only the fields the upscale pipeline needs. Compressed BIFs (BIFC and BIF V1.0)
are inflated once into the work cache.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

# IE resource types the pipeline actually opens.
EXT_BY_TYPE = {
    0x0001: "bmp",
    0x03E8: "bam",
    0x03E9: "wed",
    0x03EA: "chu",
    0x03EB: "tis",
    0x03EC: "mos",
    0x03ED: "itm",
    0x03EE: "spl",
    0x03F1: "cre",
}
WANTED = set(EXT_BY_TYPE.values())
TIS_TYPE = 0x03EB


def resref(raw: bytes) -> str:
    text = raw.split(b"\x00", 1)[0].decode("latin1")
    return text.strip().upper()


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _clean_bif_name(raw: bytes) -> str:
    text = raw.split(b"\x00", 1)[0].decode("latin1").strip()
    return text.replace("\\", "/").replace(":", "/").lstrip("/")


def find_bif(game: Path, name: str) -> Path | None:
    rel = Path(name)
    rel_names = [rel, Path(rel.name)]
    roots = [game, game / "data"]
    for i in range(1, 7):
        roots.append(game / f"cd{i}")
        roots.append(game / f"CD{i}")
    for root in roots:
        for candidate in rel_names:
            path = root / candidate
            if path.is_file():
                return path
            if path.suffix.lower() == ".bif":
                cbf = path.with_suffix(".cbf")
                if cbf.is_file():
                    return cbf
    return None


def _decompress_chunks(data: bytes, start: int, total: int) -> bytes:
    """BIFC payload: repeated (declen, complen, zlib)."""
    out = bytearray()
    off = start
    while len(out) < total:
        if off + 8 > len(data):
            break
        declen = _u32(data, off)
        complen = _u32(data, off + 4)
        off += 8
        chunk = zlib.decompress(data[off : off + complen])
        off += complen
        if declen and len(chunk) != declen:
            # the decompressed bytes are what the engine writes; keep them
            pass
        out += chunk
        if complen == 0:
            break
    return bytes(out)


def materialize_bif(path: Path, cache: Path) -> Path:
    """Return a plain BIFF V1 path, inflating compressed archives into `cache`."""
    with path.open("rb") as handle:
        sig = handle.read(8)
        if sig == b"BIFFV1  ":
            return path
        rest = handle.read()
    blob = sig + rest
    if sig == b"BIFCV1.0":
        total = _u32(blob, 8)
        payload = _decompress_chunks(blob, 12, total)
    elif sig == b"BIF V1.0":
        fnlen = _u32(blob, 8)
        base = 12 + fnlen
        declen = _u32(blob, base)
        complen = _u32(blob, base + 4)
        payload = zlib.decompress(blob[base + 8 : base + 8 + complen])
        if declen and len(payload) != declen:
            pass
    else:
        raise ValueError(f"unknown bif signature {sig!r} in {path}")
    if payload[:8] != b"BIFFV1  ":
        raise ValueError(f"{path.name} did not inflate to a BIFF")
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (path.name + ".bin")
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(out)
    return out


class _Bif:
    def __init__(self, path: Path, cache: Path):
        self.path = path
        self.cache = cache
        self._data_path: Path | None = None
        self._files: dict[int, tuple[int, int]] = {}
        self._tiles: dict[int, tuple[int, int]] = {}

    def _ensure(self) -> Path:
        if self._data_path is not None:
            return self._data_path
        data_path = materialize_bif(self.path, self.cache)
        with data_path.open("rb") as handle:
            header = handle.read(20)
            if header[:8] != b"BIFFV1  ":
                raise ValueError(f"{data_path} is not BIFF V1")
            file_count, tile_count, file_off = struct.unpack_from("<3I", header, 8)
            handle.seek(file_off)
            file_blob = handle.read(file_count * 16)
            tile_blob = handle.read(tile_count * 20)
        files: dict[int, tuple[int, int]] = {}
        for i in range(file_count):
            loc, off, size, _typ, _unk = struct.unpack_from("<3I2H", file_blob, i * 16)
            key = loc & 0x3FFF
            files.setdefault(key, (off, size))
        tiles: dict[int, tuple[int, int]] = {}
        for i in range(tile_count):
            loc, off, count, tile_size, _typ, _unk = struct.unpack_from("<4I2H", tile_blob, i * 20)
            key = loc & 0xFC000
            tiles.setdefault(key, (off, count * tile_size))
        self._files = files
        self._tiles = tiles
        self._data_path = data_path
        return data_path

    def read(self, locator: int, ext: str) -> bytes:
        data_path = self._ensure()
        if ext == "tis":
            entry = self._tiles.get(locator & 0xFC000)
        else:
            entry = self._files.get(locator & 0x3FFF)
        if entry is None:
            raise KeyError(f"locator {locator:#x} ({ext}) missing in {self.path.name}")
        off, size = entry
        with data_path.open("rb") as handle:
            handle.seek(off)
            buf = handle.read(size)
        if len(buf) != size:
            raise ValueError(f"short read in {self.path.name} at {off}")
        return buf


class ResourceIndex:
    """`(resref, ext) -> bytes`. Override files replace KEY entries."""

    def __init__(self, game: Path, cache: Path):
        self.game = game
        self.cache = cache
        self.loaders: dict[tuple[str, str], object] = {}
        self.missing_bifs: list[str] = []
        self.found_bifs = 0
        self._build()

    def _add(self, name: str, ext: str, loader, replace: bool = False) -> None:
        name = name.strip().upper()
        ext = ext.lower()
        if not name or ext not in WANTED:
            return
        key = (name, ext)
        if replace or key not in self.loaders:
            self.loaders[key] = loader

    def _build(self) -> None:
        key_path = self.game / "CHITIN.KEY"
        if not key_path.is_file():
            key_path = self.game / "chitin.key"
        data = key_path.read_bytes()
        if data[:8] != b"KEY V1  ":
            raise ValueError(f"{key_path} is not a KEY V1 file")
        bif_count, res_count, bif_off, res_off = struct.unpack_from("<4I", data, 8)
        bifs: list[_Bif | None] = []
        for i in range(bif_count):
            entry = bif_off + i * 12
            name_off = _u32(data, entry + 4)
            name_len = _u16(data, entry + 8)
            raw_name = data[name_off : name_off + name_len]
            rel = _clean_bif_name(raw_name)
            found = find_bif(self.game, rel) if rel else None
            if found is None:
                self.missing_bifs.append(rel or f"#{i}")
                bifs.append(None)
            else:
                self.found_bifs += 1
                bifs.append(_Bif(found, self.cache))
        for i in range(res_count):
            entry = res_off + i * 14
            name = resref(data[entry : entry + 8])
            typ = _u16(data, entry + 8)
            locator = _u32(data, entry + 10)
            ext = EXT_BY_TYPE.get(typ)
            if not ext or not name:
                continue
            bif_index = (locator >> 20) & 0xFFF
            if bif_index >= len(bifs):
                continue
            bif = bifs[bif_index]
            if bif is None:
                continue
            self._add(name, ext, _slice(bif, locator, ext))
        self._add_tree(self.game / "override", replace=True)
        portraits = self.game / "portraits"
        if portraits.is_dir():
            self._add_tree(portraits, replace=False)

    def _add_tree(self, folder: Path, replace: bool) -> None:
        if not folder.is_dir():
            return
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            ext = path.suffix.lower().lstrip(".")
            if ext not in WANTED:
                continue
            self._add(path.stem, ext, _file(path), replace=replace)

    def has(self, name: str, ext: str) -> bool:
        return (name.upper(), ext.lower()) in self.loaders

    def get(self, name: str, ext: str) -> bytes:
        return self.loaders[(name.upper(), ext.lower())]()

    def names(self, ext: str) -> list[str]:
        ext = ext.lower()
        return sorted(name for name, kind in self.loaders if kind == ext)

    def __contains__(self, key: tuple[str, str]) -> bool:
        name, ext = key
        return self.has(name, ext)

    def __len__(self) -> int:
        return len(self.loaders)


def _slice(bif: _Bif, locator: int, ext: str):
    def load() -> bytes:
        return bif.read(locator, ext)

    return load


def _file(path: Path):
    def load() -> bytes:
        return path.read_bytes()

    return load


def bam_frame_sizes(data: bytes) -> list[tuple[int, int]]:
    """Width and height of each BAM v1 frame, without decoding pixels."""
    if data[:8] == b"BAMCV1  ":
        data = zlib.decompress(data[12:])
    if data[:8] != b"BAM V1  ":
        return []
    frame_count = _u16(data, 8)
    frames_off = _u32(data, 0x0C)
    sizes = []
    for i in range(frame_count):
        entry = frames_off + i * 12
        if entry + 4 > len(data):
            break
        w, h = struct.unpack_from("<2H", data, entry)
        sizes.append((w, h))
    return sizes


def mos_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"MOSCV1  ":
        data = zlib.decompress(data[12:])
    if data[:8] != b"MOS V1  ":
        return None
    w, h = struct.unpack_from("<2H", data, 8)
    return w, h


def tis_tile_count(data: bytes) -> int:
    """How many 64x64 tiles the TIS holds. BIF tilesets have no TIS header."""
    if data[:8] == b"TIS V1  ":
        section = _u32(data, 12)
        shift = _u32(data, 16)
        if section == 0x0C:
            return 0
        blob = data[shift:]
    else:
        blob = data
    return len(blob) // 5120
