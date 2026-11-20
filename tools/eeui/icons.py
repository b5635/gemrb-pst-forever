"""Hotbar icons for the turn-based moves, drawn in the style of PST's radial menu icons
(AMATTCK, AMTLK): a stone rim, a dashed teal square, a half-dark inside, a metal pictogram
with an orange accent; frame 1 lit like AMATTCK's pressed frame.

    python icons.py [--out C:\\Games\\GemRB]

Writes classic BAM V1 files (32x32, the round End Turn button 64x64) into
gemrb/override/pst/ (installed with the game, they work with EEUI off too) and their 2x twins
into <out>/upscaled/gui/bam/<NAME>/<frame>.png. The base frame is AMTLK's own twin with its
speech bubble cleared, so the rim and teal dashes are PST's pixels.

Frames: 0 normal, 1 lit (pressed / selected), 2 = 1, 3 disabled.
"""
import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from derived import _write_bam_v1

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OVERRIDE = REPO / "gemrb" / "override" / "pst"
SS = 512                      # drawing canvas for the pictograms

METAL_HI = (232, 234, 240)
METAL_LO = (78, 80, 92)
OUTLINE = (12, 12, 14)
ORANGE = (226, 128, 40)
TEAL = (70, 200, 210)


# -- pictograms (white on black masks on a 512 canvas) ----------------------------------------

def _limb(d, pts, w):
    d.line(pts, fill=255, width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)


def figure(d, ox=0, oy=0, rot=0.0, pose="run"):
    """A stick figure built from thick limbs; rot in degrees around the hips."""
    hx, hy = 256 + ox, 300 + oy

    def p(x, y):
        a = math.radians(rot)
        x, y = x - 256, y - 300
        return (hx + x * math.cos(a) - y * math.sin(a), hy + x * math.sin(a) + y * math.cos(a))

    if pose == "run":
        head = p(300, 92)
        limbs = [[p(286, 150), p(250, 300)],                                # torso
                 [p(282, 172), p(350, 226), p(410, 186)],                   # front arm
                 [p(276, 172), p(206, 200), p(160, 158)],                   # back arm
                 [p(250, 300), p(330, 350), p(320, 452)],                   # front leg
                 [p(250, 300), p(178, 372), p(84, 360)]]                    # back leg
    else:  # falling: arms thrown up
        head = p(256, 92)
        limbs = [[p(256, 150), p(256, 300)],
                 [p(256, 172), p(330, 150), p(380, 80)],
                 [p(256, 172), p(182, 150), p(132, 80)],
                 [p(256, 300), p(300, 380), p(290, 460)],
                 [p(256, 300), p(214, 380), p(224, 460)]]
    for pts in limbs:
        _limb(d, pts, 54)
    d.ellipse((head[0] - 50, head[1] - 50, head[0] + 50, head[1] + 50), fill=255)


def run_icon():
    m = Image.new("L", (SS, SS)); d = ImageDraw.Draw(m)
    figure(d, ox=30)
    a = Image.new("L", (SS, SS)); da = ImageDraw.Draw(a)
    for y, x0 in ((170, 40), (250, 10), (330, 40)):                         # speed lines
        da.line((x0, y, x0 + 90, y), fill=255, width=22)
    return m, a


def withdraw_icon():
    m = Image.new("L", (SS, SS)); d = ImageDraw.Draw(m)
    # a shield held toward the foe (right), the way back an arrow to the left
    d.polygon([(330, 70), (470, 110), (456, 260), (330, 380), (204, 260), (190, 110)], fill=255)
    a = Image.new("L", (SS, SS)); da = ImageDraw.Draw(a)
    da.line((300, 430, 110, 430), fill=255, width=46)
    da.polygon([(40, 430), (150, 360), (150, 500)], fill=255)
    da.line((180, 330, 110, 330), fill=0, width=1)
    return m, a


def block_icon():
    m = Image.new("L", (SS, SS)); d = ImageDraw.Draw(m)
    d.polygon([(256, 34), (440, 88), (420, 300), (256, 478), (92, 300), (72, 88)], fill=255)
    a = Image.new("L", (SS, SS)); da = ImageDraw.Draw(a)
    da.line((256, 110, 256, 400), fill=255, width=40)                       # bronze cross
    da.line((140, 200, 372, 200), fill=255, width=40)
    da.ellipse((216, 160, 296, 240), fill=255)
    return m, a


def trip_icon():
    m = Image.new("L", (SS, SS)); d = ImageDraw.Draw(m)
    figure(d, ox=40, oy=-30, rot=58, pose="fall")
    a = Image.new("L", (SS, SS)); da = ImageDraw.Draw(a)
    da.arc((20, 300, 360, 600), 200, 330, fill=255, width=38)              # the sweep under its feet
    da.polygon([(330, 420), (390, 360), (300, 350)], fill=255)
    return m, a


def hourglass_icon():
    m = Image.new("L", (SS, SS)); d = ImageDraw.Draw(m)
    d.rectangle((120, 60, 392, 100), fill=255)                              # caps
    d.rectangle((120, 412, 392, 452), fill=255)
    d.line((150, 100, 150, 412), fill=255, width=26)                        # posts
    d.line((362, 100, 362, 412), fill=255, width=26)
    glass = [(180, 108), (332, 108), (268, 256), (332, 404), (180, 404), (244, 256)]
    d.polygon(glass, fill=255)
    d.polygon([(206, 128), (306, 128), (262, 236), (250, 236)], fill=0)    # hollow upper bulb
    d.polygon([(250, 276), (262, 276), (306, 384), (206, 384)], fill=0)    # hollow lower bulb
    a = Image.new("L", (SS, SS)); da = ImageDraw.Draw(a)
    da.polygon([(226, 170), (286, 170), (262, 226), (250, 226)], fill=255)  # sand
    da.polygon([(256, 300), (300, 384), (212, 384)], fill=255)
    da.line((256, 230, 256, 300), fill=255, width=6)
    return m, a


# -- shading --------------------------------------------------------------------------------

def metal(mask):
    """Brushed metal: a diagonal light-to-dark ramp, a dark outline, a soft top-left highlight."""
    w, h = mask.size
    yy, xx = np.mgrid[0:h, 0:w]
    t = np.clip((xx + yy) / (w + h) * 1.3 - 0.1, 0, 1)[..., None]
    rgb = np.array(METAL_HI) * (1 - t) + np.array(METAL_LO) * t
    img = Image.fromarray(rgb.astype(np.uint8)).convert("RGBA")
    img.putalpha(mask)
    edge = mask.filter(ImageFilter.MaxFilter(17))
    out = Image.new("RGBA", mask.size, OUTLINE + (0,))
    out.putalpha(edge)
    out.alpha_composite(img)
    return out


def accent(mask, color):
    img = Image.new("RGBA", mask.size, color + (0,))
    lit = Image.new("RGBA", mask.size, tuple(min(255, c + 60) for c in color) + (0,))
    img.putalpha(mask)
    lit.putalpha(ImageChops.multiply(mask, mask.filter(ImageFilter.MinFilter(15))))
    edge = Image.new("RGBA", mask.size, OUTLINE + (0,))
    edge.putalpha(mask.filter(ImageFilter.MaxFilter(13)))
    edge.alpha_composite(img)
    edge.alpha_composite(lit)
    return edge


def pictogram(shape, accent_color, size, accent_on_top=False):
    m, a = shape()
    art = Image.new("RGBA", (SS, SS))
    layers = [metal(m), accent(a, accent_color)] if accent_on_top else [accent(a, accent_color), metal(m)]
    for layer in layers:
        art.alpha_composite(layer)
    return art.resize((size, size), Image.LANCZOS)


def glow(img, strength=1.0):
    """AMATTCK's pressed look: a white-hot bloom over the middle."""
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2, yy - h / 2) / (w / 2)
    a = np.clip(1 - r * 1.6, 0, 1) ** 2 * 210 * strength
    bloom = np.zeros((h, w, 4), np.uint8)
    bloom[..., 0], bloom[..., 1], bloom[..., 2] = 255, 236, 238
    bloom[..., 3] = a.astype(np.uint8)
    out = img.copy()
    out.alpha_composite(Image.fromarray(bloom))
    return out


def disabled(img):
    arr = np.array(img).astype(np.float32)
    g = arr[..., :3].mean(axis=2, keepdims=True)
    arr[..., :3] = g * 0.55
    return Image.fromarray(arr.astype(np.uint8))


# -- bases -----------------------------------------------------------------------------------

def square_base(twins: Path):
    """AMTLK's twin frame (64x64) with the speech bubble cleared to the half-dark inside."""
    base = np.array(Image.open(twins / "AMTLK" / "0.png").convert("RGBA"))
    inside = (slice(13, 49), slice(13, 49))   # inside the teal dashes (10-12, 49-51)
    base[inside] = (0, 0, 0, 128)
    lit_base = base.copy()
    lit_base[inside] = (20, 20, 24, 235)                                     # AMATTCK's dark lit plate
    return Image.fromarray(base), Image.fromarray(lit_base)


def round_base(size):
    """A bronze ring with rivets around a dark dial, for End Turn."""
    S = size * 4
    img = Image.new("RGBA", (S, S))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, S - 1, S - 1), fill=(24, 18, 12, 255))
    yy, xx = np.mgrid[0:S, 0:S]
    r = np.hypot(xx - S / 2, yy - S / 2) / (S / 2)
    t = np.clip((xx + yy) / (2 * S), 0, 1)
    ring = (r > 0.80) & (r < 0.98)
    arr = np.array(img).astype(np.float32)
    bronze_hi, bronze_lo = np.array((214, 150, 78)), np.array((88, 48, 20))
    col = bronze_hi * (1 - t[..., None]) + bronze_lo * t[..., None]
    arr[ring, :3] = col[ring]
    inner = r <= 0.80
    shade = (1 - r) * 30
    arr[inner, :3] = np.stack([22 + shade, 18 + shade, 14 + shade], axis=-1)[inner]
    arr[r >= 0.98, 3] = 0
    img = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(img)
    d.ellipse((S * 0.1, S * 0.1, S * 0.9, S * 0.9), outline=(10, 8, 6, 255), width=S // 64)
    d.ellipse((S * 0.012, S * 0.012, S * 0.988, S * 0.988), outline=(10, 8, 6, 255), width=S // 80)
    for k in range(8):                                                       # rivets
        a = math.radians(k * 45 + 22.5)
        x, y = S / 2 + math.cos(a) * S * 0.445, S / 2 + math.sin(a) * S * 0.445
        rr = S * 0.025
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(236, 196, 128, 255), outline=(40, 24, 10, 255))
    return img.resize((size, size), Image.LANCZOS)


# -- output ----------------------------------------------------------------------------------

def write(name, frames_hi, low_size, out: Path):
    lows = [np.array(f.resize((low_size, low_size), Image.LANCZOS)) for f in frames_hi]
    OVERRIDE.mkdir(parents=True, exist_ok=True)
    _write_bam_v1(OVERRIDE / f"{name.lower()}.bam", lows)
    tw = out / "upscaled" / "gui" / "bam" / name
    tw.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames_hi):
        f.save(tw / f"{i}.png")


MOVES = {
    "TBRUN": (run_icon, TEAL, False),
    "TBWITHDR": (withdraw_icon, ORANGE, False),
    "TBBLOCK": (block_icon, ORANGE, True),
    "TBTRIP": (trip_icon, ORANGE, False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\Games\GemRB")
    out = Path(ap.parse_args().out)
    twins = out / "upscaled" / "gui" / "bam"
    base, lit_base = square_base(twins)
    for name, (shape, col, on_top) in MOVES.items():
        pic = pictogram(shape, col, 46, on_top)
        f0 = base.copy(); f0.alpha_composite(pic, (9, 9))
        f1 = lit_base.copy(); f1.alpha_composite(pic, (9, 9)); f1 = glow(f1, 0.8)
        write(name, [f0, f1, f1, disabled(f0)], 32, out)
        print(name)
    # End Turn: 64 px round button (twin 128)
    ring = round_base(128)
    pic = pictogram(hourglass_icon, ORANGE, 76)
    f0 = ring.copy(); f0.alpha_composite(pic, (26, 26))
    f1 = glow(f0, 0.9)
    f1.putalpha(ring.getchannel("A"))
    write("TBENDTRN", [f0, f1, f1, disabled(f0)], 64, out)
    print("TBENDTRN")
    movebar(out)


def movebar(out: Path):
    """TBMOVBAR: the hotbar's movement bar, EE's remade health bar (FILLBAR, red to green) at
    138x19, frame 0 the fill, frame 1 the empty trough (the same bar, dark and grey)."""
    from decode import PageCache, bam_v2
    from ee_data import EEData
    ee = EEData()
    bam = bam_v2(ee.read("FILLBAR", "bam"), PageCache(ee))
    w, h = 138, 19
    fill = Image.fromarray(bam.frames[0].image).convert("RGBA").resize((w * 3, h * 3), Image.LANCZOS)
    arr = np.array(fill).astype(np.float32)
    g = arr[..., :3].mean(axis=2, keepdims=True)
    arr[..., :3] = g * 0.28 + np.array((14, 10, 6))
    trough = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    frames = [fill, trough]
    lows = [np.array(f.resize((w, h), Image.LANCZOS)) for f in frames]
    _write_bam_v1(OVERRIDE / "tbmovbar.bam", lows)
    tw = out / "upscaled" / "gui" / "bam" / "TBMOVBAR"
    tw.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(tw / f"{i}.png")
    print("TBMOVBAR")


if __name__ == "__main__":
    main()
