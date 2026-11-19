"""Phase 4 converter: EE's UI.menu / BGEE.lua / art -> <out>/ee_ui/ for the GemRB EE-layout screens.

    python tools\\eeui\\build.py --ee "<EE path>" --out D:\\Games\\GemRB [--height 720] [--no-previews]

Writes into <out>/ee_ui/: art (MOS/BAM + PVRZ pages, byte for byte, aliased to EU####.ext when a
classic name would clash), layout/<MENU>.json, styles.json, aliases.txt, previews/<MENU>.png,
review/bestiary.txt, summary.txt. Never writes into the EE or classic installs.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "upscale"))

import ie_formats  # noqa: E402
import menu_parser as mp  # noqa: E402
from decode import PageCache, bam_v2, mos_v2  # noqa: E402
from ee_data import DEFAULT_EE, EEData, inflate  # noqa: E402

CLASSIC = Path(r"C:\Program Files (x86)\Black Isle\Torment")
REPO = HERE.parents[1]
EE_W, EE_H = 1366, 768
ART_PX_PER_UNIT = 2.8125     # EE art pixels per EE layout unit (3840 / 1366)
CTRL_KINDS = {"button", "label", "text", "list", "edit", "slider", "slot", "map", "movie",
              "template", "handle"}


# -- Lua tables -------------------------------------------------------------------------------
def lua_block(text: str, start_pat: str) -> str:
    """The body of the brace block that follows `start_pat` (balanced, quotes ignored)."""
    m = re.search(start_pat, text)
    if not m:
        return ""
    i = text.index("{", m.end())
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
        j += 1
    return text[i + 1:]


def parse_styles(bgee: str):
    colors = {}
    for m in re.finditer(r"fontcolors\['(.)'\]\s*=\s*'([0-9A-Fa-f]{8})'", bgee):
        a, b, g, r = (int(m.group(2)[k:k + 2], 16) for k in (0, 2, 4, 6))  # AABBGGRR
        colors[m.group(1)] = [r, g, b, a]
    body = lua_block(bgee, r"\nstyles\s*=")
    styles = {}
    for m in re.finditer(r"(\w+)\s*=\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", body):
        s = {}
        for k, v in re.findall(r"(\w+)\s*=\s*('[^']*'|\"[^\"]*\"|\{[^}]*\}|[-\w.]+)", m.group(2)):
            v = v.strip()
            if v[0] in "'\"":
                v = v[1:-1]
            elif v[0] == "{":
                v = [int(x) for x in re.findall(r"-?\d+", v)]
            elif re.fullmatch(r"-?\d+", v):
                v = int(v)
            s[k] = v
        if "color" in s:
            s["rgba"] = colors.get(str(s["color"]))
        styles[m.group(1)] = s
    return styles, colors


def parse_ui_strings(lua: str) -> dict:
    body = lua_block(lua, r"uiStrings\s*=")
    return {k: int(v) for k, v in re.findall(r"(\w+)\s*=\s*(\d+)", body)}


def parse_ee_bestiary(bgee: str) -> list:
    body = lua_block(bgee, r"\nbestiary\s*=")
    out, i = [], 0
    while True:
        i = body.find("{", i)
        if i < 0:
            break
        j = body.find("}", i)
        d = {}
        for k, v in re.findall(r"(\w+)\s*=\s*('[^']*'|-?\d+)", body[i + 1:j]):
            d[k] = v[1:-1] if v[0] == "'" else int(v)
        out.append(d)
        i = j + 1
    return out


# -- TLK --------------------------------------------------------------------------------------
class Tlk:
    def __init__(self, path: Path):
        self.d = path.read_bytes()
        self.count, self.base = struct.unpack_from("<II", self.d, 10)

    def get(self, n: int):
        if not 0 <= n < self.count:
            return None
        flags, _snd, _v, _p, off, ln = struct.unpack_from("<H8sIIII", self.d, 18 + n * 26)
        if not flags & 1:
            return ""
        return self.d[self.base + off:self.base + off + ln].decode("cp1252", "replace")


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


# -- classic name tables ----------------------------------------------------------------------
def classic_names(classic: ie_formats.ResourceIndex, out: Path) -> set:
    """(NAME, ext) pairs a classic screen could already load: KEY/override plus our own folders."""
    names = set(classic.loaders)
    for folder in (REPO / "gemrb" / "override", REPO / "gemrb" / "unhardcoded", out / "override"):
        if folder.is_dir():
            for p in folder.rglob("*"):
                if p.is_file():
                    names.add((p.stem.upper(), p.suffix.lower().lstrip(".")))
    return names


# -- the converter ----------------------------------------------------------------------------
class Build:
    def __init__(self, ee: EEData, classic, out: Path, height: int):
        if height not in (720, 1080):
            raise SystemExit(f"logical height {height} is not supported (720 or 1080)")
        self.ee, self.classic = ee, classic
        self.root = out / "ee_ui"
        self.height = height
        self.s = height / EE_H
        self.width = round(height * 16 / 9)
        self.taken = classic_names(classic, out)
        self.pages = PageCache(ee)
        self.copied: dict[tuple, str] = {}       # (EE NAME, ext) -> name used in layouts
        self.missing: set = set()
        self.classic_only: set = set()
        self.aliases: dict[str, str] = {}
        self.known_alias: dict[tuple, str] = {}
        self.log: list = []
        self.ui_strings: dict = {}
        self.classic_tlk = Tlk(classic.game / "dialog.tlk")
        self.ee_tlk = Tlk(ee.root / "lang" / "en_US" / "dialog.tlk")
        self.string_stats = {"strref": 0, "ee": 0, "literal": 0, "unknown_key": 0}

    # -- art ----------------------------------------------------------------------------------
    def load_aliases(self):
        f = self.root / "aliases.txt"
        if f.is_file():
            for line in f.read_text().splitlines():
                p = line.split()
                if len(p) == 2:
                    name, ext = p[0].rsplit(".", 1) if "." in p[0] else (p[0], "")
                    self.known_alias[(name.upper(), ext.lower())] = p[1]

    def next_alias(self, ext: str) -> str:
        used = {v.split(".")[0].upper() for v in self.known_alias.values()} | \
               {v.split(".")[0].upper() for v in self.aliases.values()}
        n = 1
        while f"EU{n:04d}" in used:
            n += 1
        return f"EU{n:04d}"

    def art(self, name: str, ext: str) -> str | None:
        """Copy EE art `name.ext` (mos or bam) into ee_ui; return the name layouts must use."""
        name = name.strip().upper()
        key = (name, ext)
        if key in self.copied:
            return self.copied[key]
        if not self.ee.has(name, ext):
            if (name, ext) in self.taken:      # classic-only art the EE menus also name
                self.classic_only.add(f"{name}.{ext}")
                self.copied[key] = name
                return name
            self.missing.add(f"{name}.{ext}")
            return None
        blob = self.ee.read(name, ext)
        use = name
        if key in self.taken:
            use = self.known_alias.get(key) or self.next_alias(ext)
            self.aliases[f"{name}.{ext}"] = use
            self.known_alias[key] = use
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{use.lower()}.{ext}").write_bytes(blob)
        raw = inflate(blob)
        if raw[:8] == b"MOS V2  ":
            w, h, n, off = struct.unpack_from("<4I", raw, 8)
            pages = {struct.unpack_from("<I", raw, off + i * 28)[0] for i in range(n)}
        elif raw[:8] == b"BAM V2  ":
            nf, nc, nb, foff, coff, boff = struct.unpack_from("<6I", raw, 8)
            pages = {struct.unpack_from("<I", raw, boff + i * 28)[0] for i in range(nb)}
        else:
            pages = set()
        for p in sorted(pages):
            f = self.root / f"mos{p:04d}.pvrz"
            if not f.is_file():
                f.write_bytes(self.ee.read(f"MOS{p:04d}", "pvrz"))
        self.copied[key] = use
        return use

    def art_pattern(self, pat: str):
        """extra_art.txt line: NAME, wildcard, optionally with .mos / .bam."""
        pat = pat.strip()
        exts = ("mos", "bam")
        if re.search(r"\.(mos|bam)$", pat, re.I):
            pat, e = pat.rsplit(".", 1)
            exts = (e.lower(),)
        found = False
        for ext in exts:
            for n in self.ee.names(ext):
                if fnmatch.fnmatch(n, pat.upper()):
                    self.art(n, ext)
                    found = True
        if not found:
            self.missing.add(pat)

    # -- strings ------------------------------------------------------------------------------
    def string(self, s: str, quoted: bool = True) -> dict:
        n = int(s) if s.isdigit() else self.ui_strings.get(s)
        if n is None:
            self.string_stats["literal" if not re.fullmatch(r"[A-Z0-9_]+", s) else "unknown_key"] += 1
            return {"literal": s}
        c, e = self.classic_tlk.get(n), self.ee_tlk.get(n)
        if c is not None and e is not None and norm(c) == norm(e):
            self.string_stats["strref"] += 1
            return {"strref": n}
        self.string_stats["ee"] += 1
        return {"text": e if e is not None else "", "ee_strref": n}

    # -- layout -------------------------------------------------------------------------------
    def px(self, v: float) -> int:
        return round(v * self.s)

    @staticmethod
    def area(a):
        try:
            v = [int(float(t.v)) for t in a[:4]]
        except (ValueError, IndexError):
            return None
        return v if len(v) == 4 else None

    def place(self, menu: mp.Block):
        """(origin x, origin y, bbox) in EE space of the menu's aligned bounding box."""
        rects = []
        for c in menu.children:
            if c.kind in CTRL_KINDS and c.get("area"):
                r = self.area(c.get("area"))
                if r and r[2] > 0 and r[3] > 0:
                    rects.append(r)
        if not rects:
            return None
        x0 = min(r[0] for r in rects)
        y0 = min(r[1] for r in rects)
        x1 = max(r[0] + r[2] for r in rects)
        y1 = max(r[1] + r[3] for r in rects)
        al = [t.v.lower() for t in (menu.get("align") or [])]
        h = al[0] if al else "left"
        v = al[1] if len(al) > 1 else "top"
        bw, bh = x1 - x0, y1 - y0
        ox = {"left": 0, "center": (EE_W - bw) / 2, "right": EE_W - bw}.get(h, 0)
        oy = {"top": 0, "center": (EE_H - bh) / 2, "bottom": EE_H - bh}.get(v, 0)
        return ox - x0, oy - y0, (x0, y0, bw, bh)

    def text_props(self, c: mp.Block, key: str):
        """`text`/`tooltip` props: literal or strings key, plus style/lua/point/align sub-props."""
        out, extra = None, {}
        for a in c.all(key):
            if not a:
                continue
            head = a[0].v.lower()
            if not a[0].q and head in ("style", "lua", "point", "align", "color", "shadow", "highlight",
                                       "usefontzoom", "target", "valign", "halign", "wrap", "pad"):
                sub = a[1:]
                if head == "lua":
                    extra["lua"] = sub[0].v if sub else ""
                elif head == "color" and sub and sub[0].v.lower() == "lua":
                    extra["color_lua"] = sub[1].v if len(sub) > 1 else ""
                elif head == "shadow" and sub and sub[0].v.lower() == "lua":
                    extra["shadow_lua"] = sub[1].v if len(sub) > 1 else ""
                else:
                    extra[head] = [t.v for t in sub] if len(sub) != 1 else sub[0].v
            elif out is None:
                out = self.string(a[0].v)
        return out, extra

    def control(self, c: mp.Block, ox, oy, bbox, index):
        d = {"type": c.kind, "index": index}
        nm = c.get("name")
        if nm:
            d["name"] = nm[0].v
        r = self.area(c.get("area") or [])
        if r:
            x, y, w, h = r
            d["ee_area"] = r
            d["frame"] = [self.px(ox + x), self.px(oy + y), self.px(w), self.px(h)]
        bam = c.get("bam")
        if bam:
            if bam[0].v.lower() == "lua":
                d["bam_lua"] = bam[1].v if len(bam) > 1 else ""
            else:
                use = self.art(bam[0].v, "bam")
                d["bam"] = use
                if use is None:
                    d["bam_missing"] = bam[0].v.upper()
                elif use != bam[0].v.upper():
                    d["bam_ee"] = bam[0].v.upper()
        seq = c.get("sequence")
        if seq:
            d["sequence"] = int(seq[0].v) if seq[0].v.lstrip("-").isdigit() else {"lua": seq[-1].v}
        fr = c.get("frame")
        if fr and c.kind != "label":
            d["frame_index"] = [t.v for t in fr]
        for key in ("mosaic", "bitmap"):
            m = c.get(key)
            if m:
                if key == "bitmap" and m[0].v.lower() in ("res", "lua"):
                    d["bitmap_lua"] = m[-1].v if len(m) > 1 else ""    # picture set at run time
                elif m[0].v.lower() == "lua":
                    d["mosaic_lua"] = m[1].v if len(m) > 1 else ""
                else:
                    use = self.art(m[0].v, "mos")
                    d["mosaic"] = use
                    if use is None:
                        d["mosaic_missing"] = m[0].v.upper()
                    elif use != m[0].v.upper():
                        d["mosaic_ee"] = m[0].v.upper()
        txt, tx = self.text_props(c, "text")
        if txt:
            d["text"] = txt
        if tx:
            d["text_opts"] = tx
            if "style" in tx:
                d["style"] = tx["style"]
        tip, tp = self.text_props(c, "tooltip")
        if tip:
            d["tooltip"] = tip
        if tp.get("target"):
            d["tooltip_target"] = tp["target"]
        bp = c.get("boundingPoints")
        if bp:
            pts = re.findall(r"(-?\d+)\s*,\s*(-?\d+)", " ".join(t.v for t in bp))
            d["hit"] = [[self.px(int(a)), self.px(int(b))] for a, b in pts]
        sb = c.get("scrollbar")
        if sb:
            d["scrollbar"] = self.art(sb[0].v, "bam") or sb[0].v
        for key in ("var", "table", "position", "settings", "rowheight", "maxlines", "icon", "slot", "slotinfo"):
            v = c.get(key)
            if v:
                d[key] = " ".join(t.v for t in v)
        raw = {}
        for key in ("enabled", "clickable", "action", "actionEnter", "actionExit", "actionAlt",
                    "actionDbl", "actionHold"):
            v = c.get(key)
            if v:
                raw[key.lower()] = " ".join(t.v for t in v).strip()
        if raw:
            d["raw"] = raw
        if c.kind == "list":
            # row template: children of each `column`, frames relative to the row, scaled
            cols = []
            for col in c.children:
                if col.kind != "column":
                    continue
                w = col.get("width")
                cols.append({"width": int(w[0].v) if w and w[0].v.isdigit() else None,
                             "controls": [self.control(ch, 0, 0, None, k)
                                          for k, ch in enumerate(col.children)]})
            if cols:
                d["columns"] = cols
        return d

    def menus(self, menus):
        self.root.joinpath("layout").mkdir(parents=True, exist_ok=True)
        done, summary = {}, []
        inherited = {}      # menu pushed by another menu's onOpen -> that menu's background
        for m in menus:
            on_open = m.get("onOpen")
            if on_open:
                bg = re.search(r"Infinity_SetBackground\(\s*'(\w+)'", on_open[0].v)
                if bg:
                    for pm in re.findall(r"Infinity_PushMenu\(\s*'(\w+)'", on_open[0].v):
                        inherited[pm] = bg.group(1)
        for m in menus:
            nm = (m.get("name") or [None])[0]
            if nm is None:
                continue
            name = nm.v
            plate = None
            on_open = m.get("onOpen")
            if on_open:
                mm = re.search(r"Infinity_SetBackground\(\s*'(\w+)'", on_open[0].v)
                plate = mm.group(1) if mm else None
            if plate is None:
                plate = inherited.get(name)
            pl = self.place(m)
            doc = {"menu": name, "logical": [self.width, self.height], "scale": self.s,
                   "align": [t.v for t in (m.get("align") or [])], "plate_menu": plate,
                   "modal": m.has("modal"), "controls": []}
            if pl:
                ox, oy, bbox = pl
                doc["ee_bbox"] = list(bbox)
                doc["slot_dy"] = self.px(oy)
                doc["bbox"] = [self.px(ox + bbox[0]), self.px(oy + bbox[1]), self.px(bbox[2]), self.px(bbox[3])]
                idx = 0
                for c in m.children:
                    if c.kind in CTRL_KINDS:
                        doc["controls"].append(self.control(c, ox, oy, bbox, idx))
                    idx += 1
            (self.root / "layout" / f"{name}.json").write_text(json.dumps(doc, indent=1))
            done[name] = doc
            summary.append(f"{name}: {len(doc['controls'])} controls")
        return done, summary

    # -- previews -----------------------------------------------------------------------------
    def previews(self, docs):
        import numpy as np
        from PIL import Image, ImageDraw
        out = self.root / "previews"
        out.mkdir(parents=True, exist_ok=True)
        cache: dict = {}

        def art_image(name, ext, seq=None):
            key = (name, ext, seq)
            if key in cache:
                return cache[key]
            img = None
            if not name:
                return None
            try:
                f = self.root / f"{name.lower()}.{ext}"
                blob = f.read_bytes()
                raw = inflate(blob)
                pc = LocalPages(self.root)
                if ext == "mos" and raw[:8] == b"MOS V2  ":
                    img = mos_v2(blob, pc)
                elif ext == "bam" and raw[:8] == b"BAM V2  ":
                    bam = bam_v2(blob, pc)
                    if bam.frames:
                        cyc = seq if isinstance(seq, int) and seq < len(bam.cycles) else 0
                        cnt, first = bam.cycles[cyc] if bam.cycles else (1, 0)
                        img = bam.frames[min(first, len(bam.frames) - 1)].image
            except Exception as e:  # preview only
                self.log.append(f"preview art {name}.{ext}: {e}")
            cache[key] = img
            return img

        def paste(canvas, img, x, y, w, h):
            if img is None or w <= 0 or h <= 0:
                return
            im = Image.fromarray(img).resize((max(1, w), max(1, h)), Image.LANCZOS)
            canvas.alpha_composite(im, (0, 0)) if False else canvas.paste(im, (x, y), im)

        n = 0
        for name, doc in docs.items():
            if not doc["controls"]:
                continue
            canvas = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 255))
            plate_doc = docs.get(doc.get("plate_menu") or "")
            if plate_doc:
                for c in plate_doc["controls"]:
                    if "mosaic" in c and "frame" in c:
                        paste(canvas, art_image(c["mosaic"], "mos"), *c["frame"])
            dr = ImageDraw.Draw(canvas)
            for c in doc["controls"]:
                if "frame" not in c:
                    continue
                x, y, w, h = c["frame"]
                if "mosaic" in c:
                    paste(canvas, art_image(c["mosaic"], "mos"), x, y, w, h)
                if "bam" in c:
                    sq = c.get("sequence")
                    img = art_image(c["bam"], "bam", sq if isinstance(sq, int) else None)
                    if img is not None:
                        aw = round(img.shape[1] / ART_PX_PER_UNIT * self.s)
                        ah = round(img.shape[0] / ART_PX_PER_UNIT * self.s)
                        paste(canvas, img, x + (w - aw) // 2, y + (h - ah) // 2, aw, ah)
                dr.rectangle([x, y, x + w, y + h], outline=(255, 64, 64, 255) if c["type"] == "button"
                             else (64, 160, 255, 255))
                dr.text((x + 2, y + 1), c.get("name") or str(c["index"]), fill=(255, 255, 0, 255))
                if c.get("hit"):
                    dr.polygon([(x + a, y + b) for a, b in c["hit"]], outline=(0, 255, 0, 255))
            canvas.convert("RGB").save(out / f"{name}.png")
            n += 1
        return n

    # -- bestiary report ----------------------------------------------------------------------
    def bestiary(self, bgee: str):
        entries = {}
        cur = None
        for line in (self.classic.game / "beast.ini").read_text(encoding="latin1").splitlines():
            line = line.split("//")[0].strip()
            m = re.match(r"\[(\d+)\]", line)
            if m:
                cur = int(m.group(1))
                entries[cur] = {}
            elif cur is not None and "=" in line:
                k, v = line.split("=", 1)
                entries[cur][k.strip().lower()] = v.strip()
        ee = {e["index"]: e for e in parse_ee_bestiary(bgee) if "index" in e}
        tw = Path(self.root.parent / "upscaled" / "ee_twins.txt")
        twins = set(tw.read_text().split()) if tw.is_file() else set()
        lines = ["index | name | EE picture | twin source | EE entry same name/desc*/global", "-" * 90]
        for i in sorted(entries):
            e = entries[i]
            img = e.get("imageknown", "").upper()
            has = self.ee.has(img, "mos")
            src = "EE" if f"gui/bmp/{img}.png" in twins else "ESRGAN/none"
            ee_e = ee.get(i)
            if ee_e is None:
                same = "no EE entry"
            else:
                diffs = [k for k in ("name", "desc0", "desc1", "desc2", "global")
                         if str(ee_e.get(k)) != e.get(k) and not (ee_e.get(k) is None and k not in e)]
                same = "same" if not diffs else "differs: " + ",".join(diffs)
            name = self.classic_tlk.get(int(e["name"])) if e.get("name", "").isdigit() else e.get("name")
            lines.append(f"{i} | {name} | {'yes' if has else 'NO'} {img} | {src} | {same}")
        d = self.root / "review"
        d.mkdir(parents=True, exist_ok=True)
        (d / "bestiary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(entries)


class LocalPages:
    """PageCache over the copied pvrz files in ee_ui (what the engine will read)."""

    def __init__(self, root: Path):
        from pvrz import decode_pvrz
        self.root, self.decode, self.pages = root, decode_pvrz, {}

    def get(self, page: int):
        if page not in self.pages:
            self.pages[page] = self.decode((self.root / f"mos{page:04d}.pvrz").read_bytes())
        return self.pages[page]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ee", default=str(DEFAULT_EE))
    ap.add_argument("--out", default=r"D:\Games\GemRB")
    ap.add_argument("--classic", default=str(CLASSIC))
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--no-previews", action="store_true")
    a = ap.parse_args()
    ee = EEData(Path(a.ee))
    classic = ie_formats.ResourceIndex(Path(a.classic), HERE.parent / "upscale" / "work" / "classic-cache")
    b = Build(ee, classic, Path(a.out), a.height)
    b.load_aliases()

    menu_text = ee.read("UI", "menu").decode("latin1")
    bgee = ee.read("BGEE", "lua").decode("latin1")
    lang = ee.read("L_EN_US", "lua").decode("latin1")
    b.ui_strings = parse_ui_strings(lang)
    styles, colors = parse_styles(bgee)
    b.root.mkdir(parents=True, exist_ok=True)
    (b.root / "styles.json").write_text(json.dumps({"styles": styles, "colors": colors}, indent=1))

    # EEFonts=1 (gemrb/unhardcoded/pst/eefonts.2da): EE's body-text face
    try:
        (b.root / "BOOKMANI.ttf").write_bytes(ee.read("BOOKMANI", "ttf"))
    except Exception as e:  # noqa: BLE001
        b.log.append(f"BOOKMANI.ttf not copied: {e}")

    menus = mp.parse(menu_text)
    docs, summary = b.menus(menus)

    extra = HERE / "extra_art.txt"
    if extra.is_file():
        for line in extra.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                b.art_pattern(line)

    import derived
    b.log.append("derived art: " + " ".join(derived.make_all(b.root)))
    (b.root / "aliases.txt").write_text(
        "".join(f"{k} {v}\n" for k, v in sorted(b.aliases.items())))
    nb = b.bestiary(bgee)
    npv = 0 if a.no_previews else b.previews(docs)

    lines = [f"menus: {len(docs)} ({sum(1 for d in docs.values() if d['controls'])} with controls, "
             f"{sum(len(d['controls']) for d in docs.values())} controls)",
             f"art copied: {len(b.copied)} ({sum(1 for k in b.copied if k[1] == 'mos')} MOS, "
             f"{sum(1 for k in b.copied if k[1] == 'bam')} BAM), pvrz pages: "
             f"{len(list(b.root.glob('mos*.pvrz')))}",
             f"aliases: {len(b.aliases)} (aliases.txt)",
             f"styles: {len(styles)}, colours: {len(colors)}",
             f"strings: {b.string_stats}",
             f"bestiary rows: {nb} (review/bestiary.txt)",
             f"previews: {npv}",
             f"classic-only art ({len(b.classic_only)}): {' '.join(sorted(b.classic_only))}",
             f"missing everywhere ({len(b.missing)}): {' '.join(sorted(b.missing))}"]
    lines += b.log[:20]
    (b.root / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
