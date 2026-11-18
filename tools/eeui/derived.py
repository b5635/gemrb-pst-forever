"""Art we make from EE art (phase 18). MOS V2 pieces remap blocks of EE's own PVRZ pages (no new
pixels); EEQSLOT is a small classic BAM with a hi-res twin, for art needed at a size EE lacks.

EEACTBAR.mos: the world HUD strip (phase 18). EE's ACTBG is 960 logical px wide with the clock
sockets at its left end and the radial-wedge sockets at its right end. Our bar spans the whole
1280 px screen: left cap at the left edge, right cap at the right edge, and the plain middle
repeated in between, so the hotbar gets the middle of the screen.
"""
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from decode import bam_v2, inflate
from pvrz import decode_pvrz

# ACTBG columns in full-res pixels (2880 wide): left cap (clock + 3 circles), right cap
# (3 circles + wedge + 3 circles); everything between is plain plate
ACTBG_LEFT_END = 312
ACTBG_RIGHT_START = 2376
BAR_W = 3840


def _blocks(raw):
    w, h, n, off = struct.unpack_from("<4I", raw, 8)
    return w, h, [struct.unpack_from("<7I", raw, off + i * 28) for i in range(n)]


def _crop(blocks, x0, x1, dx):
    """Blocks covering columns [x0, x1) of the source, moved so x0 lands on dx."""
    out = []
    for page, sx, sy, bw, bh, bx, by in blocks:
        a, b = max(bx, x0), min(bx + bw, x1)
        if a >= b:
            continue
        out.append((page, sx + (a - bx), sy, b - a, bh, dx + (a - x0), by))
    return out


def _rect(blocks, x0, y0, x1, y1, dx, dy):
    """Blocks covering the source rectangle [x0, x1) x [y0, y1), moved so (x0, y0) lands on (dx, dy)."""
    out = []
    for page, sx, sy, bw, bh, bx, by in blocks:
        a, b = max(bx, x0), min(bx + bw, x1)
        c, d = max(by, y0), min(by + bh, y1)
        if a >= b or c >= d:
            continue
        out.append((page, sx + (a - bx), sy + (c - by), b - a, d - c, dx + (a - x0), dy + (c - y0)))
    return out


def _write(path, w, h, blocks):
    head = b"MOS V2  " + struct.pack("<4I", w, h, len(blocks), 24)
    body = b"".join(struct.pack("<7I", *b) for b in blocks)
    path.write_bytes(head + body)


def make_actbar(root: Path):
    src = root / "actbg.mos"
    if not src.is_file():
        return None
    raw = inflate(src.read_bytes())
    w, h, blocks = _blocks(raw)
    right_w = w - ACTBG_RIGHT_START
    out = _crop(blocks, 0, ACTBG_LEFT_END, 0)
    out += _crop(blocks, ACTBG_RIGHT_START, w, BAR_W - right_w)
    x, mid0, mid1 = ACTBG_LEFT_END, ACTBG_LEFT_END, ACTBG_RIGHT_START
    end = BAR_W - right_w
    while x < end:
        n = min(mid1 - mid0, end - x)
        out += _crop(blocks, mid0, mid0 + n, x)
        x += n
    _write(root / "eeactbar.mos", BAR_W, h, out)
    return "EEACTBAR"


# DIABG's reply panel (full-res px): its rusty rim, rounded corners included
PANEL = (1066, 34, 2788, 838)
CORNER = 75
# the dialogue picture frame: 160x241 logical (a bestiary picture at half size, 140x220, plus rim)
FRAME_W, FRAME_H = 480, 723


def make_dialog_frame(root: Path):
    """EEDLGPF.mos: a picture frame cut from DIABG's own reply panel (9-slice; edges and the
    inside are plain stretches of the panel, cropped to length, never scaled)."""
    src = root / "diabg.mos"
    if not src.is_file():
        return None
    _, _, blocks = _blocks(inflate(src.read_bytes()))
    x0, y0, x1, y1 = PANEL
    c, w, h = CORNER, FRAME_W, FRAME_H
    ew, eh = w - 2 * c, h - 2 * c       # edge lengths
    mx, my = x0 + c + 40, y0 + c        # where the straight edges and the plain inside are cut
    out = []
    out += _rect(blocks, x0, y0, x0 + c, y0 + c, 0, 0)                 # corners
    out += _rect(blocks, x1 - c, y0, x1, y0 + c, w - c, 0)
    out += _rect(blocks, x0, y1 - c, x0 + c, y1, 0, h - c)
    out += _rect(blocks, x1 - c, y1 - c, x1, y1, w - c, h - c)
    out += _rect(blocks, mx, y0, mx + ew, y0 + c, c, 0)                # top, bottom
    out += _rect(blocks, mx, y1 - c, mx + ew, y1, c, h - c)
    out += _rect(blocks, x0, my, x0 + c, my + eh, 0, c)                # left, right
    out += _rect(blocks, x1 - c, my, x1, my + eh, w - c, c)
    iy = y0 + 40                        # the inside: above the panel's slider bar
    out += _rect(blocks, mx, iy, mx + ew, iy + eh, c, c)               # inside
    _write(root / "eedlgpf.mos", w, h, out)
    return "EEDLGPF"


def make_info_tab(root: Path):
    """EEBARTAB.mos: a 1008x20 logical strip of ACTBG's plain plate for the hotbar's info line."""
    src = root / "actbg.mos"
    if not src.is_file():
        return None
    _, h, blocks = _blocks(inflate(src.read_bytes()))
    w, th = 3024, 60
    out, x = [], 0
    while x < w:
        n = min(ACTBG_RIGHT_START - ACTBG_LEFT_END, w - x)
        out += _rect(blocks, ACTBG_LEFT_END, 0, ACTBG_LEFT_END + n, th, x, 0)
        x += n
    _write(root / "eebartab.mos", w, th, out)
    return "EEBARTAB"


class _Pages:
    """PVRZ pages read back from the output folder (they were copied there by build.py)."""
    def __init__(self, root):
        self.root, self.cache = root, {}

    def get(self, page):
        if page not in self.cache:
            self.cache[page] = decode_pvrz((self.root / f"mos{page:04d}.pvrz").read_bytes())
        return self.cache[page]


def _write_bam_v1(path, frames, cycles=None):
    """Uncompressed BAM V1; frames are RGBA arrays of one size, cycles a list of frame counts
    (default: one cycle of all frames, in order). Palette index 0 is the transparent green."""
    h, w = frames[0].shape[:2]
    strip = np.concatenate(frames, axis=1)
    rgb = Image.fromarray(strip[..., :3]).quantize(255, method=Image.Quantize.MEDIANCUT)
    idx = np.array(rgb, np.uint8) + 1
    idx[strip[..., 3] < 128] = 0
    pal = rgb.getpalette()[:255 * 3]
    n = len(frames)
    frames_off = 24
    cycles = cycles or [n]
    pal_off = frames_off + 12 * n + 4 * len(cycles)
    lut_off = pal_off + 1024
    data_off = lut_off + 2 * n
    out = bytearray(b"BAM V1  " + struct.pack("<HBBIII", n, len(cycles), 0, frames_off, pal_off, lut_off))
    for i in range(n):
        out += struct.pack("<HHhhI", w, h, 0, 0, (data_off + i * w * h) | 0x80000000)
    first = 0
    for c in cycles:
        out += struct.pack("<HH", c, first)
        first += c
    out += bytes((0, 255, 0, 0))
    for i in range(255):
        r, g, b = pal[i * 3:i * 3 + 3]
        out += bytes((b, g, r, 0))
    out += b"".join(struct.pack("<H", i) for i in range(n))
    for i in range(n):
        out += idx[:, i * w:(i + 1) * w].tobytes()
    path.write_bytes(bytes(out))


# hotbar slots: QUICKSLT (45 logical px in EE) at the hotbar's 36 px
SLOT = 36


def make_slot(root: Path, k=3):
    src = root / "quickslt.bam"
    if not src.is_file():
        return None
    bam = bam_v2(src.read_bytes(), _Pages(root))
    hi = Image.fromarray(bam.frames[0].image).convert("RGBA").resize((SLOT * k, SLOT * k), Image.LANCZOS)
    lit = np.array(hi).astype(np.float32)
    lit[..., :3] = np.minimum(255, lit[..., :3] * 1.35)
    his = [np.array(hi), lit.astype(np.uint8)]          # normal, pressed
    lows = [np.array(Image.fromarray(f).resize((SLOT, SLOT), Image.LANCZOS)) for f in his]
    _write_bam_v1(root / "eeqslot.bam", lows)
    tw = root.parent / "upscaled" / "gui" / "bam" / "EEQSLOT"
    tw.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(his):
        Image.fromarray(f).save(tw / f"{i}.png")
    return "EEQSLOT"


# EECIRC: EE's round HUD buttons (CIRCBUTT, 230 px art that EE scales into 23 px buttons) at
# their button size. Each cycle: normal, pressed, selected, disabled; the toggles take their
# "on" picture as the selected frame. (CIRCBUTT cycle, on cycle or None)
CIRC_SIZE = 23
CIRC_CYCLES = [
    (0, None),   # 0 select all
    (1, None),   # 1 abort
    (2, None),   # 2 formations
    (3, None),   # 3 message log
    (4, 5),      # 4 lock view, green when locked
    (6, 7),      # 5 party AI, green when on
]


def make_circ(root: Path, k=3):
    src = root / "circbutt.bam"
    if not src.is_file():
        return None
    bam = bam_v2(src.read_bytes(), _Pages(root))

    def frame(cycle, i):
        cnt, first = bam.cycles[cycle]
        return bam.frames[bam.lookup[first + min(i, cnt - 1)]].image

    his = []
    for c, on in CIRC_CYCLES:
        picks = [frame(c, 0), frame(c, 2), frame(on, 0) if on is not None else frame(c, 2), frame(c, 3)]
        his += [Image.fromarray(f).convert("RGBA").resize((CIRC_SIZE * k, CIRC_SIZE * k), Image.LANCZOS) for f in picks]
    lows = [np.array(f.resize((CIRC_SIZE, CIRC_SIZE), Image.LANCZOS)) for f in his]
    _write_bam_v1(root / "eecirc.bam", lows, [4] * len(CIRC_CYCLES))
    tw = root.parent / "upscaled" / "gui" / "bam" / "EECIRC"
    tw.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(his):
        f.save(tw / f"{i}.png")
    return "EECIRC"


def make_all(root: Path):
    return [n for n in (make_actbar(root), make_dialog_frame(root), make_info_tab(root), make_slot(root),
                        make_circ(root)) if n]
