"""Survey PST spell visuals: SPL/ITM opcodes, projectiles, VVCs, PlayBAM users, BAM sizes.

Run: D:\\gemrb\\tools\\upscale\\.venv\\Scripts\\python.exe survey.py
Writes pst_spell_visuals.md and survey.json next to this script.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from pst_data import (
    GAME,
    GEMRB,
    HERE,
    Resources,
    Tlk,
    parse_bam,
    parse_eff,
    parse_ids,
    parse_itm,
    parse_pro,
    parse_spl,
    parse_vvc,
    read_text_table,
)

res = Resources()
tlk = Tlk(GAME / "Dialog.tlk")

# ---------------------------------------------------------------- opcode names

OPNAMES = parse_ids((GEMRB / "unhardcoded" / "pst" / "effects.ids").read_bytes())

# purely visual: no stat, state or script-visible change in GemRB's implementation
VISUAL = {
    0x07, 0x08, 0x09, 0x29, 0x32, 0x33, 0x34, 0x42, 0x72, 0x79, 0x8C, 0x8D,
    0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC1, 0xC2, 0xC3, 0xC5, 0xC7, 0xCD,
}
# visual plus something a script can see (state bit, animation id, stance, overlay mechanics)
MIXED = {0x14, 0x35, 0x41, 0x8A, 0xC9}
# presentation, not visual
PRESENTATION = {0x8B, 0x8E, 0x98, 0xAE}
# effects that pull in another resource that can carry visuals
CHAIN = {0x92: "spl", 0x94: "spl", 0xB1: "eff", 0xC4: "special"}
PLAYBAM = {0xBB, 0xBC, 0xBD, 0xBE, 0xBF}


def opname(op: int) -> str:
    return OPNAMES.get(op, f"unknown_{op:#x}")


def vis_class(op: int) -> str:
    if op in VISUAL:
        return "visual"
    if op in MIXED:
        return "visual+state"
    if op in PRESENTATION:
        return "presentation"
    return ""


SPELL_TYPES = {0: "special", 1: "wizard", 2: "priest", 3: "psionic", 4: "innate"}
PRO_TYPES = {1: "no-BAM", 2: "single", 3: "area"}

# ---------------------------------------------------------------- tables

proj_ids = parse_ids(res.get("GEMPRJTL", "ids"))
projectl_present = res.has("PROJECTL", "ids")


def proj_name(raw: int) -> str | None:
    if raw == 0:
        return None
    return proj_ids.get(raw - 1)


def text_table(name: str) -> list[list[str]] | None:
    if not res.has(name, "2da"):
        return None
    return read_text_table(res.get(name, "2da").decode("latin1"))


cg_rows = text_table("CGTABLE") or []
CASTING_GLOWS = []
for row in cg_rows[3:]:
    CASTING_GLOWS.append(row[1] if len(row) > 1 else "*")

AREAPRO = []
for row in (text_table("AREAPRO") or [])[3:]:
    if len(row) >= 4 and not row[0].startswith("#"):
        AREAPRO.append([x.upper() for x in row[1:4]])

sh_rows = text_table("SHTABLE")
SPELL_HITS = [r[1] if len(r) > 1 else "*" for r in (sh_rows or [])[3:]]


def vef_table_refs(name: str) -> list[str] | None:
    """GemRB VEFObject::Load2DA: rows of XPOS YPOS RESREF DELAY DURATION."""
    rows = text_table(name)
    if rows is None or len(rows) < 3:
        return None
    header = rows[2]
    if "RESREF" not in [h.upper() for h in header]:
        return None
    col = [h.upper() for h in header].index("RESREF") + 1
    return [r[col].upper() for r in rows[3:] if len(r) > col]


# ---------------------------------------------------------------- load data

SPELLS: dict[str, dict] = {}
for name in res.names("spl"):
    s = parse_spl(res.get(name, "spl"))
    if s is None:
        continue
    s["source"] = res.source(name, "spl")
    if s["source"].startswith("gemrb-unhardcoded"):
        # GemRB helper payloads: strref 0 or another game's strref, never a PST name
        s["name"] = ""
    else:
        s["name"] = tlk(s["name_strref"]) if s["name_strref"] else ""
        s["name"] = s["name"] or (tlk(s["name_id_strref"]) if s["name_id_strref"] else "")
    SPELLS[name] = s

ITEMS: dict[str, dict] = {}
for name in res.names("itm"):
    it = parse_itm(res.get(name, "itm"))
    if it is None:
        continue
    it["source"] = res.source(name, "itm")
    it["name"] = tlk(it["name_id_strref"]) or tlk(it["name_strref"])
    ITEMS[name] = it

PROS: dict[str, dict] = {}
for name in res.names("pro"):
    p = parse_pro(res.get(name, "pro"))
    if p is not None:
        p["source"] = res.source(name, "pro")
        PROS[name] = p

VVCS: dict[str, dict] = {}
for name in res.names("vvc"):
    v = parse_vvc(res.get(name, "vvc"))
    if v is not None:
        v["source"] = res.source(name, "vvc")
        VVCS[name] = v

BAM_CACHE: dict[str, dict | None] = {}


def bam_info(name: str) -> dict | None:
    name = name.upper()
    if name not in BAM_CACHE:
        BAM_CACHE[name] = parse_bam(res.get(name, "bam")) if res.has(name, "bam") else None
        if BAM_CACHE[name] is not None:
            BAM_CACHE[name]["file_size"] = len(res.get(name, "bam"))
    return BAM_CACHE[name]


def all_fx(entry: dict) -> list[tuple[str, dict]]:
    out = []
    for fx in entry.get("casting_fx", []):
        out.append(("cast", fx))
    for fx in entry.get("equip_fx", []):
        out.append(("equip", fx))
    for i, h in enumerate(entry["headers"]):
        for fx in h["fx"]:
            out.append((f"h{i}", fx))
    return out


# ---------------------------------------------------------------- resolving visual resources


def resolve_anim(ref: str) -> tuple[str, list[str]]:
    """What GameData::GetScriptedAnimation would load for `ref`: (kind, bams)."""
    ref = ref.upper()
    if not ref:
        return ("none", [])
    if ref in VVCS:
        return ("vvc", [VVCS[ref]["bam"]] if VVCS[ref]["bam"] else [])
    if res.has(ref, "bam"):
        return ("bam", [ref])
    return ("missing", [])


def resolve_vef(ref: str) -> tuple[str, list[str]]:
    """GameData::GetVEFObject: VEF, then 2DA table, then plain animation."""
    ref = ref.upper()
    if res.has(ref, "vef"):
        return ("vef", [])
    rows = vef_table_refs(ref)
    if rows is not None:
        bams = []
        for r in dict.fromkeys(rows):
            bams.extend(resolve_anim(r)[1])
        return ("2da", bams)
    return resolve_anim(ref)


def pro_for_raw(raw: int) -> str | None:
    n = proj_name(raw)
    return n.upper() if n else None


class Collector:
    """Walk everything a spell can show: fx, chained spells, projectiles, VVCs."""

    def __init__(self):
        self.bams: dict[str, set[str]] = defaultdict(set)  # bam -> how reached
        self.seen: set[tuple[str, str]] = set()
        self.notes: list[str] = []

    def add_bam(self, bam: str, how: str):
        if bam:
            self.bams[bam.upper()].add(how)

    def fx(self, fx: dict, ctx: str):
        op = fx["opcode"]
        r = fx["res"]
        if op in PLAYBAM or op == 0x79:
            kind, bams = resolve_anim(r)
            for b in bams:
                self.add_bam(b, f"{ctx} {opname(op)} {r}({kind})")
        elif op == 0xC5:
            kind, bams = resolve_vef(r)
            for b in bams:
                self.add_bam(b, f"{ctx} MultipleVVC {r}({kind})")
        elif op == 0x8C:
            idx = fx["p2"]
            if idx < len(CASTING_GLOWS) and not CASTING_GLOWS[idx].startswith("*"):
                for b in resolve_anim(CASTING_GLOWS[idx])[1]:
                    self.add_bam(b, f"{ctx} CastingGlow[{idx}]")
        elif op == 0x8D:
            idx = fx["p2"]
            if idx < len(SPELL_HITS) and not SPELL_HITS[idx].startswith("*"):
                for b in resolve_anim(SPELL_HITS[idx])[1]:
                    self.add_bam(b, f"{ctx} VisualSpellHit[{idx}]")
        elif op in (0x92, 0x94) and r:
            self.spell(r, f"{ctx}>cast")
        elif op == 0xC4:
            target = {0: "ADDER", 1: "BALL", 2: "RDEAD"}.get(fx["p2"])
            if target:
                self.spell(target, f"{ctx}>special")
        elif op == 0xB1 and r and res.has(r, "eff"):
            e = parse_eff(res.get(r, "eff"))
            if e:
                self.fx({"opcode": e["opcode"], "res": e["res"], "p1": e["p1"], "p2": e["p2"]}, f"{ctx}>eff")

    def spell(self, name: str, ctx: str):
        name = name.upper()
        if ("spl", name) in self.seen or name not in SPELLS:
            return
        self.seen.add(("spl", name))
        s = SPELLS[name]
        cg = s["casting_graphics"]
        if cg < len(CASTING_GLOWS) and not CASTING_GLOWS[cg].startswith("*"):
            for b in resolve_anim(CASTING_GLOWS[cg])[1]:
                self.add_bam(b, f"{ctx} {name} casting glow[{cg}]")
        for where, fx in all_fx(s):
            self.fx(fx, f"{ctx} {name}.{where}")
        for h in s["headers"]:
            p = pro_for_raw(h["projectile_raw"])
            if p:
                self.projectile(p, f"{ctx} {name}")

    def projectile(self, name: str, ctx: str):
        if ("pro", name) in self.seen:
            return
        self.seen.add(("pro", name))
        p = PROS.get(name)
        if p is None:
            return
        tag = f"{ctx} pro:{name}"
        for key in ("bam1", "bam2"):
            if p.get(key):
                self.add_bam(p[key], f"{tag} {key}")
        for t in p.get("trail", []):
            if t:
                # Projectile::AddTrail goes through GetVEFObject, so a VVC of that name wins
                for b in resolve_vef(t)[1]:
                    self.add_bam(b, f"{tag} trail {t}")
        if p["travel_vvc"]:
            for b in resolve_anim(p["travel_vvc"])[1]:
                self.add_bam(b, f"{tag} travel_vvc")
        a = p.get("area")
        if a:
            if a["vvc"]:
                for b in resolve_vef(a["vvc"])[1]:
                    self.add_bam(b, f"{tag} area vvc {a['vvc']}")
            for key in ("spread", "secondary"):
                if a[key]:
                    for b in resolve_anim(a[key])[1]:
                        self.add_bam(b, f"{tag} {key}")
            if a["expl_proj_raw"]:
                sub = proj_ids.get(a["expl_proj_raw"] - 1)
                if sub:
                    self.projectile(sub.upper(), f"{tag} explosion")
            if a["aflags"] & 16 and a["frag_proj"]:
                sub = proj_ids.get(a["frag_proj"])
                if sub:
                    self.projectile(sub.upper(), f"{tag} fragment")
            if a["expl_type"] < len(AREAPRO):
                for r in AREAPRO[a["expl_type"]]:
                    if r != "*":
                        for b in resolve_anim(r)[1]:
                            self.add_bam(b, f"{tag} areapro[{a['expl_type']}] {r}")
        if p["success_spell"]:
            self.spell(p["success_spell"], f"{tag} success_spell")
        # PEF_NOTIDS with no IDS set makes FailedIDS() true, so the failure spell is the real payload
        if p["fail_spell"] and p["ext_flags"] & 0x2000000:
            self.spell(p["fail_spell"], f"{tag} fail_spell")


def spell_bams(name: str) -> dict[str, set[str]]:
    c = Collector()
    c.spell(name, "")
    return c.bams


# ---------------------------------------------------------------- 1. counts and spell list

SPELL_PREFIXES = ("SPWI", "SPPR", "SPIN")


def fx_brief(fx: dict) -> str:
    op = fx["opcode"]
    bits = [f"{op:#04x} {opname(op)}"]
    if fx["res"]:
        kind = ""
        if op in PLAYBAM:
            kind = "/" + resolve_anim(fx["res"])[0]
        elif op == 0xC5:
            kind = "/" + resolve_vef(fx["res"])[0]
        bits.append(f"`{fx['res']}`{kind}")
    if op in (0x8C, 0x8D, 0x29, 0xC3, 0xC4, 0xC9):
        bits.append(f"p2={fx['p2']}")
    if op in (0x08, 0x09, 0x32, 0x33, 0x34, 0xC2, 0xC3):
        bits.append(f"rgb={fx['p1']:#010x}")
    return " ".join(bits)


def spell_visual_fx(s: dict) -> list[str]:
    seen = []
    for _, fx in all_fx(s):
        op = fx["opcode"]
        if op in VISUAL or op in MIXED or op in CHAIN:
            b = fx_brief(fx)
            if b not in seen:
                seen.append(b)
    return seen


def spell_projectiles(s: dict) -> list[str]:
    out = []
    for h in s["headers"]:
        raw = h["projectile_raw"]
        n = proj_name(raw)
        if raw <= 1:
            label = f"{raw} (none)"
        elif n is None:
            label = f"{raw} (not in gemprjtl)"
        else:
            label = f"{raw}->{n}"
        if n and n.upper() not in PROS:
            label += "(no .pro)"
        if label not in out:
            out.append(label)
    return out


def md_escape(t: str) -> str:
    return t.replace("|", "\\|")


lines: list[str] = []
W = lines.append

W("# PST spell visuals survey")
W("")
W("Generated by `tools/vfx/work/survey.py` (rerun it to refresh). Data: classic PST at "
  "`C:\\Program Files (x86)\\Black Isle\\Torment` (chitin.key + override, Fixpack + UB) layered "
  "the way GemRB searches it: `gemrb/override/pst` > `gemrb/override/shared` > game `override` > "
  "chitin.key > `gemrb/unhardcoded/pst` > `gemrb/unhardcoded/shared`.")
W("")
W("Important context: **classic PST ships no PRO and no VVC files.** Torment.exe hardcoded its "
  "projectiles. Every PRO and VVC below is a GemRB reconstruction in `gemrb/unhardcoded/pst` "
  "(plus generic ones in `unhardcoded/shared`), together with 43 helper SPLs that those projectiles "
  "fire as their payload (`successSpell` at PRO offset 0x4C). `PROJECTL.IDS` is "
  + ("present" if projectl_present else "**not present** in the game data")
  + "; GemRB maps projectile numbers with `gemrb/unhardcoded/pst/gemprjtl.ids`. A SPL extended "
  "header stores projectile N, `SPLImporter` decrements it, so the PRO is `gemprjtl[N-1]`.")
W("")
KEY_AT = len(lines)
W("## 1. Resource counts")
W("")
W("| Type | Effective (what GemRB sees) | gemrb override/pst | game override | chitin.key | gemrb unhardcoded/pst | unhardcoded/shared |")
W("|---|---|---|---|---|---|---|")
COUNTS = {}
for ext in ("spl", "pro", "vvc", "bam", "itm", "eff", "vef"):
    c = res.count_by_layer(ext)
    COUNTS[ext] = {"effective": len(res.names(ext)), **c}
    W(f"| {ext.upper()} | {len(res.names(ext))} | {c['gemrb-override']} | {c['game-override']} | "
      f"{c['chitin']} | {c['gemrb-unhardcoded']} | {c['gemrb-unhardcoded-shared']} |")
W("")
W("Layer columns count files present in that layer; overridden copies are counted in each layer, so "
  "they can add up to more than the effective total. `gemrb/override/shared` holds none of these types.")
W("")

by_prefix = Counter()
for n in SPELLS:
    by_prefix[n[:4] if n.startswith(SPELL_PREFIXES) else "other"] += 1
W("SPL by prefix: " + ", ".join(f"{k} {v}" for k, v in sorted(by_prefix.items())) + ".")
W("")

W("### 1a. Every SPWI / SPPR / SPIN spell")
W("")
W("Columns: type and level from the SPL header; `cg` is the casting-graphics index into "
  "`cgtable.2da` (the BAM it plays); projectile is the raw ext-header value -> gemprjtl name (deduplicated "
  "over all ext headers). Visual fx lists every purely visual, visual+state, or chaining opcode "
  "(Spell:Cast, ApplyEffect, SpecialEffect) found in casting features and ext-header features. `/vvc` or `/bam` says "
  "what GemRB resolves the resref to.")
W("")
W("| Resref | Name | Type | Lvl | cg (glow BAM) | Projectile | Visual / chaining opcodes | Source |")
W("|---|---|---|---|---|---|---|---|")
SPELL_ROWS = []
for name in sorted(SPELLS):
    if not name.startswith(SPELL_PREFIXES):
        continue
    s = SPELLS[name]
    cg = s["casting_graphics"]
    glow = CASTING_GLOWS[cg] if cg < len(CASTING_GLOWS) else "?"
    vis = spell_visual_fx(s)
    projs = spell_projectiles(s)
    SPELL_ROWS.append({"resref": name, "name": s["name"], "type": SPELL_TYPES.get(s["type"], s["type"]),
                       "level": s["level"], "cg": cg, "glow": glow, "projectiles": projs, "visual_fx": vis,
                       "source": s["source"]})
    W(f"| {name} | {md_escape(s['name'])} | {SPELL_TYPES.get(s['type'], s['type'])} | {s['level']} | "
      f"{cg} ({glow}) | {', '.join(projs) or '-'} | {'<br>'.join(md_escape(v) for v in vis) or '-'} | {s['source']} |")
W("")

W("### 1b. Other SPL files (GemRB projectile payloads and non-prefixed game spells)")
W("")
W("| Resref | Name | Type | Lvl | Projectile | Visual / chaining opcodes | Source |")
W("|---|---|---|---|---|---|---|")
for name in sorted(SPELLS):
    if name.startswith(SPELL_PREFIXES):
        continue
    s = SPELLS[name]
    vis = spell_visual_fx(s)
    W(f"| {name} | {md_escape(s['name']) or '-'} | {SPELL_TYPES.get(s['type'], s['type'])} | {s['level']} | "
      f"{', '.join(spell_projectiles(s)) or '-'} | {'<br>'.join(md_escape(v) for v in vis) or '-'} | {s['source']} |")
W("")

# ---------------------------------------------------------------- 2. opcode histogram

op_total = Counter()
op_spl = Counter()
op_itm = Counter()
op_files = defaultdict(set)
for name, s in SPELLS.items():
    for _, fx in all_fx(s):
        op_total[fx["opcode"]] += 1
        op_spl[fx["opcode"]] += 1
        op_files[fx["opcode"]].add("spl:" + name)
for name, it in ITEMS.items():
    for _, fx in all_fx(it):
        op_total[fx["opcode"]] += 1
        op_itm[fx["opcode"]] += 1
        op_files[fx["opcode"]].add("itm:" + name)

W("## 2. Opcode histogram (all SPL and ITM, effective set)")
W("")
W(f"{len(SPELLS)} SPL and {len(ITEMS)} ITM files, {sum(op_total.values())} feature blocks "
  "(SPL casting features + ext-header features; ITM equipping features + ext-header features). "
  "Names from `gemrb/unhardcoded/pst/effects.ids`. Class: **visual** = GemRB's implementation only "
  "changes what is drawn (or is a no-op); **visual+state** = visible but also sets something a script "
  "can test; **presentation** = sound, text, icon, movie.")
W("")
W("| Opcode | Name | Total | in SPL | in ITM | Files | Class |")
W("|---|---|---|---|---|---|---|")
for op, cnt in sorted(op_total.items(), key=lambda kv: (-kv[1], kv[0])):
    cls = vis_class(op)
    cls_md = f"**{cls}**" if cls == "visual" else cls
    W(f"| {op:#04x} ({op}) | {opname(op)} | {cnt} | {op_spl[op]} | {op_itm[op]} | {len(op_files[op])} | {cls_md} |")
W("")

# ---------------------------------------------------------------- 3. projectiles

pro_users = defaultdict(set)
for name, s in SPELLS.items():
    for h in s["headers"]:
        p = pro_for_raw(h["projectile_raw"])
        if p:
            pro_users[p].add(name)
for name, it in ITEMS.items():
    for h in it["headers"]:
        p = pro_for_raw(h["projectile_raw"])
        if p:
            pro_users[p].add("itm:" + name)
for name, p in PROS.items():
    a = p.get("area")
    if a and a["expl_proj_raw"]:
        sub = proj_ids.get(a["expl_proj_raw"] - 1)
        if sub:
            pro_users[sub.upper()].add("pro:" + name)
    if a and a["aflags"] & 16 and a["frag_proj"]:
        sub = proj_ids.get(a["frag_proj"])
        if sub:
            pro_users[sub.upper()].add("pro:" + name + "(fragment)")

PEF_NAMES = {1: "bounce", 2: "continue", 4: "freeze", 8: "no-travel", 16: "trail", 32: "curve",
             64: "random", 128: "pillar", 256: "halftrans", 512: "tint", 1024: "iteration",
             2048: "defspell", 4096: "falling", 8192: "incoming", 16384: "line", 32768: "wall",
             0x10000: "background", 0x20000: "pop", 0x80000: "fade", 0x100000: "text",
             0x200000: "wandering", 0x400000: "cycle", 0x800000: "rgb", 0x1000000: "touch",
             0x10000000: "delay"}
PTF_NAMES = {1: "colour", 2: "smoke", 8: "tint", 32: "shadow", 64: "light", 128: "trans",
             256: "brighten", 512: "blend", 0x4000: "timeless"}
PAF_NAMES = {1: "visible", 2: "inanimate", 4: "trigger", 8: "delayed", 16: "secondary",
             32: "fragment", 64: "enemy", 128: "party", 256: "lev_mage", 512: "lev_cleric",
             1024: "vvc", 2048: "cone", 0x1000: "no_wall", 0x2000: "trigger_d", 0x4000: "delay",
             0x8000: "affect_one"}


def flags(val: int, names: dict[int, str]) -> str:
    out = [n for bit, n in names.items() if val & bit]
    rest = val & ~sum(names)
    if rest:
        out.append(f"{rest:#x}")
    return ",".join(out)


def pro_shape(p: dict) -> str:
    a = p.get("area")
    ef = p["ext_flags"]
    if a and a["aflags"] & 2048:
        return f"cone {a['cone_width']}deg"
    if ef & 16384:
        return "line"
    if ef & 32768:
        return "wall"
    if ef & 128:
        return "pillar"
    if ef & 1024:
        return "multi-missile"
    if a:
        return "area"
    if ef & 8:
        return "instant single"
    return PRO_TYPES.get(p["type"], str(p["type"]))


W("## 3. Projectiles")
W("")
type_counts = Counter(PRO_TYPES.get(p["type"], p["type"]) for p in PROS.values())
shape_counts = Counter(pro_shape(p).split(" ")[0] for p in PROS.values())
W(f"{len(PROS)} PRO files ({COUNTS['pro']['gemrb-unhardcoded']} in unhardcoded/pst, "
  f"{COUNTS['pro']['gemrb-unhardcoded-shared']} in unhardcoded/shared), all GemRB-made. "
  "PRO type field: " + ", ".join(f"{k} {v}" for k, v in type_counts.items()) + ". "
  "Shape derived from area flags (cone), GemRB extension flags (line, wall, pillar, iteration, no-travel) "
  "and type: " + ", ".join(f"{k} {v}" for k, v in shape_counts.most_common()) + ".")
W("")
sizes = Counter(p["size"] for p in PROS.values())
W("PRO file sizes: " + ", ".join(f"{k} bytes x{v}" for k, v in sorted(sizes.items())) + ".")
W("")
light_set = [n for n, p in PROS.items() if p.get("light_x") or p.get("light_y") or p.get("light_z")]
light_flag = [n for n, p in PROS.items() if p.get("tflags", 0) & 64]
light_drawn = [n for n in light_flag if n in light_set]
W("Light spot: `PROImporter` reads 0x116 LightZ, 0x118 LightX, 0x11A LightY; `Projectile.cpp` only "
  "creates the light when travel flag 0x40 (PTF_LIGHT) is set, as `CreateLight(Size(LightX, LightY), LightZ)` "
  "(X/Y = spot size, Z = intensity). The table prints X,Y,Z.")
W("")
W(f"- {len(light_set)} PROs have non-zero light fields: {', '.join(light_set) or 'none'}.")
W(f"- {len(light_flag)} have PTF_LIGHT set: {', '.join(light_flag) or 'none'}.")
W(f"- So {len(light_drawn)} actually draw a light spot: {', '.join(light_drawn) or 'none'}. "
  f"The other {len(light_set) - len(light_drawn)} carry light values that GemRB never uses.")
W("")
W("gemprjtl.ids names used by spells or items that have **no PRO file** (GemRB then builds a default, "
  "invisible projectile):")
W("")
missing_pro = sorted(n for n in pro_users if n not in PROS)
for n in missing_pro:
    W(f"- `{n}`: {', '.join(sorted(pro_users[n]))}")
if not missing_pro:
    W("- none")
W("")
W("Columns: speed; BAM1 travel animation (seq), BAM2 shadow; travel flags (0x100); GemRB ext flags (0x2C); "
  "for area projectiles: area flags, trigger/explosion radius, center VVC/BAM (0x21C), explosion type "
  "(0x217, 255=none, else areapro.2da row), explosion projectile; success/fail payload spells; users.")
W("")
reached_pros_all = set()
for _n in SPELLS:
    _c = Collector()
    _c.spell(_n, "")
    reached_pros_all.update(x for kind, x in _c.seen if kind == "pro")
used_pros = {n for n in PROS if n in pro_users or n in reached_pros_all}
W(f"### 3a. The {len(used_pros)} PROs that a SPL, ITM or another PRO actually reaches")
W("")
W("| PRO | Shape | Spd | BAM1 (seq) / BAM2 | Light XYZ | Travel flags | Ext flags | Area: flags / radii / VVC / expl | Payload | Used by |")
W("|---|---|---|---|---|---|---|---|---|---|")
PRO_ROWS = []
unused_rows = []
for name in sorted(PROS):
    p = PROS[name]
    if name not in used_pros:
        unused_rows.append(name)
        PRO_ROWS.append({"pro": name, "shape": pro_shape(p), **{k: v for k, v in p.items() if k != "area"},
                         "area": p.get("area"), "users": []})
        continue
    a = p.get("area")
    area_txt = "-"
    if a:
        expl = proj_ids.get(a["expl_proj_raw"] - 1) if a["expl_proj_raw"] else None
        frag = proj_ids.get(a["frag_proj"]) if (a["aflags"] & 16 and a["frag_proj"]) else None
        area_txt = (f"{flags(a['aflags'], PAF_NAMES) or 0} / {a['trigger_radius']},{a['explosion_radius']} / "
                    f"{a['vvc'] or '-'} / type {a['expl_type']}" + (f", proj {expl}" if expl else "")
                    + (f", fragments {frag}" if frag else "")
                    + (f", spread {a['spread']}" if a["spread"] else ""))
    bam = f"{p.get('bam1') or '-'} ({p.get('seq1', 0)})" + (f" / {p['bam2']}" if p.get("bam2") else "")
    light = f"{p.get('light_x', 0)},{p.get('light_y', 0)},{p.get('light_z', 0)}"
    payload = ", ".join(x for x in (p["success_spell"] and f"ok:{p['success_spell']}",
                                    p["fail_spell"] and f"fail:{p['fail_spell']}") if x) or "-"
    users = sorted(pro_users.get(name, []))
    PRO_ROWS.append({"pro": name, "shape": pro_shape(p), **{k: v for k, v in p.items() if k != "area"},
                     "area": a, "users": users})
    W(f"| {name} | {pro_shape(p)} | {p['speed']} | {bam} | {light} | {flags(p.get('tflags', 0), PTF_NAMES) or '-'} | "
      f"{flags(p['ext_flags'], PEF_NAMES) or '-'} | {area_txt} | {payload} | {', '.join(users) or '-'} |")
W("")
W(f"### 3b. The {len(unused_rows)} PROs nothing references")
W("")
W("Mostly generic BG-style projectiles from `unhardcoded/shared` and PST leftovers; listed for completeness.")
W("")
W("| PRO | Source | Shape | BAM1 | Draws light | Area VVC / expl type |")
W("|---|---|---|---|---|---|")
for name in unused_rows:
    p = PROS[name]
    a = p.get("area")
    lit = "yes" if (p.get("tflags", 0) & 64 and name in light_set) else "no"
    W(f"| {name} | {p['source'].replace('gemrb-', '')} | {pro_shape(p)} | {p.get('bam1') or '-'} | {lit} | "
      f"{(a['vvc'] or '-') + ' / ' + str(a['expl_type']) if a else '-'} |")
W("")

# ---------------------------------------------------------------- 4. VVCs

vvc_users = defaultdict(set)


def note_ref(ref: str, who: str):
    if ref and ref.upper() in VVCS:
        vvc_users[ref.upper()].add(who)


for name, s in SPELLS.items():
    for _, fx in all_fx(s):
        note_ref(fx["res"], f"spl:{name}")
    cg = s["casting_graphics"]
    if cg < len(CASTING_GLOWS):
        note_ref(CASTING_GLOWS[cg], f"spl:{name}(cg)")
for name, it in ITEMS.items():
    for _, fx in all_fx(it):
        note_ref(fx["res"], f"itm:{name}")
for name, p in PROS.items():
    note_ref(p["travel_vvc"], f"pro:{name}")
    for t in p.get("trail", []):
        note_ref(t, f"pro:{name}(trail)")
    if p.get("area"):
        for key in ("vvc", "spread", "secondary"):
            note_ref(p["area"][key], f"pro:{name}({key})")
for tab in res.names("2da"):
    refs = vef_table_refs(tab)
    if refs:
        for r in refs:
            note_ref(r, f"2da:{tab}")

TRANS_NAMES = {2: "transparent", 8: "blended", 0x10: "mirrorx", 0x20: "mirrory", 0x40: "clipped",
               0x200: "3d_blend", 0x400: "nocover2", 0x800: "no_timestop", 0x1000: "no_sepia",
               0x2000: "2d_blend", 0x30000: "tint", 0x80000: "greyscale", 0x200000: "glowing",
               0x2000000: "sepia"}
SEQ_NAMES = {1: "loop", 2: "lightspot", 4: "height", 8: "bam", 0x40: "nocover", 0x80: "mid_brighten",
             0x100: "high_brighten", 0x40000000: "static", 0x80000000: "freeze"}

W("## 4. VVCs")
W("")
W(f"{len(VVCS)} VVC files, all GemRB-made ({COUNTS['vvc']['gemrb-unhardcoded']} in unhardcoded/pst, "
  f"{COUNTS['vvc']['gemrb-unhardcoded-shared']} in unhardcoded/shared). Transparency dword at 0x18, "
  "sequence flags at 0x20, decoded with `ScriptedAnimation.h`. Note `GetScriptedAnimation` tries a VVC "
  "first and falls back to a BAM of the same name, so most PST play-BAM opcodes point straight at BAMs.")
W("")
W("| VVC | BAM | BAM frames/cycles, max W x max H | Transparency (0x18) | Seq flags (0x20) | fps | seq1/2/3 | Light XYZ | Referenced by |")
W("|---|---|---|---|---|---|---|---|---|")
VVC_ROWS = []
for name in sorted(VVCS):
    v = VVCS[name]
    b = bam_info(v["bam"]) if v["bam"] else None
    bdesc = "-"
    if b:
        mw = max((f[0] for f in b["frames"]), default=0)
        mh = max((f[1] for f in b["frames"]), default=0)
        bdesc = f"{len(b['frames'])}f/{len(b['cycles'])}c, {mw}x{mh}"
    elif v["bam"]:
        bdesc = "BAM missing"
    users = sorted(vvc_users.get(name, []))
    VVC_ROWS.append({"vvc": name, **v, "bam_desc": bdesc, "users": users})
    W(f"| {name} | {v['bam']} | {bdesc} | {v['transparency']:#x} {flags(v['transparency'], TRANS_NAMES)} | "
      f"{v['seq_flags']:#x} {flags(v['seq_flags'], SEQ_NAMES)} | {v['framerate']} | {v['seq1']}/{v['seq2']}/{v['seq3']} | "
      f"{v['light_x']},{v['light_y']},{v['light_z']} | {', '.join(users) or 'none found'} |")
W("")

# ---------------------------------------------------------------- 5. PlayBAM


def decode_bb(fx: dict) -> str:
    p2 = fx["p2"]
    out = []
    out.append("repeat" if (p2 & 1 and fx["timing"] == 0) else "once")
    out.append("area (not sticky)" if p2 & 2 else "sticky on target")
    return ", ".join(out)


def decode_bc(fx: dict) -> str:
    p2 = fx["p2"]
    out = []
    out.append("sticky" if p2 & 0x1000 else ("area, random offset" if p2 & 1 else "area"))
    layer = p2 & 0x30000
    out.append({0x10000: "background", 0x20000: "foreground", 0x30000: "twin fg+bg"}.get(layer, "background(default)"))
    blend = p2 & 0x300000
    out.append({0x100000: f"fade a={fx['p1'] & 0xFF} speed={fx['dice_sides']}",
                0x200000: f"blend+fade a={fx['p1'] & 0xFF}", 0x300000: "blend"}.get(blend, "tint" if fx["p1"] else "plain"))
    out.append("loops for duration" if fx["timing"] == 0 else "once")
    return ", ".join(out)


playbam_rows = []
for kind, table in (("spl", SPELLS), ("itm", ITEMS)):
    for name, e in table.items():
        for where, fx in all_fx(e):
            if fx["opcode"] in PLAYBAM:
                playbam_rows.append((kind, name, e.get("name", ""), where, fx))

W("## 5. PST play-BAM opcodes")
W("")
W("From `gemrb/plugins/PSTOpcodes/PSTOpcodes.cpp` and `gemrb/unhardcoded/pst/effects.ids`:")
W("")
W("| Opcode | effects.ids name | GemRB function | Behaviour |")
W("|---|---|---|---|")
W("| 0xBB (187) | PlayBAM1 | `fx_play_bam_blended` | Loads resref via `GetScriptedAnimation(res, twin=true)` and always `SetBlend()` (additive). p1 != 0 is an RGB tint. p2 bit0: repeat (only with timing 0 = limited; duration then = one sequence length), bit1: drop on the area at fx position instead of sticking to the target. |")
W("| 0xBC (188) | PlayBAM2 | `fx_play_bam_not_blended` | Not blended unless asked. p2 bits: 0x1 random 0-31px offset (area only), 0x1000 sticky on target, 0x10000 background / 0x20000 foreground / 0x30000 twin (loads two-part BAM), 0x100000 fade to alpha p1 at speed dice_sides, 0x200000 blend+fade, 0x300000 blend. p1 is an RGB tint when no blend bits. Timing 0 loops for the duration, else plays once. |")
W("| 0xBD (189) | PlayBAM3 | `fx_play_bam_not_blended` | Same function as 0xBC. |")
W("| 0xBE (190) | PlayBAM4 | `fx_play_bam_not_blended` | Same function as 0xBC. |")
W("| 0xBF (191) | PlayBAM5 | `fx_play_bam_not_blended` | Same function as 0xBC. |")
W("")
W("There is no `fx_transparency_fade` in GemRB's PST plugin; fading is the 0x100000 bit of 0xBC-0xBF. "
  "The generic opcode 0x42 TransparencyModifier (FXOpcodes) changes the creature's translucency. Related PST "
  "screen opcodes: 0xC1 ScreenShake, 0xC2 FlashScreen, 0xC3 TintScreen, 0xC5 MultipleVVC (GemRB-only, "
  "plays a VEF or a 2DA list like `chost.2da`), 0xC7 ChangeBackground (GemRB-only).")
W("")
op_use = Counter(fx["opcode"] for *_, fx in playbam_rows)
W("Uses: " + ", ".join(f"{opname(op)} {cnt}" for op, cnt in sorted(op_use.items())) + f" ({len(playbam_rows)} total).")
W("")
grouped: dict[tuple, list[str]] = {}
first_fx: dict[tuple, tuple] = {}
for kind, name, ename, where, fx in playbam_rows:
    key = (kind, name, fx["opcode"], fx["res"], fx["p1"], fx["p2"], fx["timing"], fx["duration"], fx["target"], fx["dice_sides"])
    grouped.setdefault(key, []).append(where)
    first_fx.setdefault(key, (kind, name, ename, fx))
W(f"{len(grouped)} distinct (file, opcode, resref, parameters) combinations; identical effects repeated across "
  "level-scaled ext headers are merged and the `Where` column lists the headers (`cast` = casting feature).")
W("")
W("| File | Name | Where | Opcode | Resref -> BAM | BAM frames/cycles, max W x max H | p1 | p2 | Decoded | Timing / dur | Target |")
W("|---|---|---|---|---|---|---|---|---|---|---|")
for key in sorted(grouped, key=lambda k: (k[0], k[1])):
    kind, name, ename, fx = first_fx[key]
    wheres = grouped[key]
    where = wheres[0] if len(wheres) == 1 else f"{wheres[0]}..{wheres[-1]} ({len(wheres)})"
    rk, bams = resolve_anim(fx["res"])
    bdesc = "-"
    if bams:
        b = bam_info(bams[0])
        if b:
            mw = max((f[0] for f in b["frames"]), default=0)
            mh = max((f[1] for f in b["frames"]), default=0)
            bdesc = f"{len(b['frames'])}f/{len(b['cycles'])}c, {mw}x{mh}"
    dec = decode_bb(fx) if fx["opcode"] == 0xBB else decode_bc(fx)
    target = f"`{fx['res']}`({rk})" + (f" -> {bams[0]}" if rk == "vvc" and bams else "")
    W(f"| {kind}:{name} | {md_escape(ename)} | {where} | {opname(fx['opcode'])} | {target} | {bdesc} | {fx['p1']:#x} | "
      f"{fx['p2']:#x} | {dec} | {fx['timing']} / {fx['duration']} | {fx['target']} |")
W("")

# BAM ranking over everything spells reach
spell_bam_users: dict[str, set[str]] = defaultdict(set)
for name in SPELLS:
    for bam in spell_bams(name):
        spell_bam_users[bam].add(name)
ranked = []
for bam, users in spell_bam_users.items():
    b = bam_info(bam)
    if not b or not b["frames"]:
        continue
    mw = max(f[0] for f in b["frames"])
    mh = max(f[1] for f in b["frames"])
    area = max(f[0] * f[1] for f in b["frames"])
    total = sum(f[0] * f[1] for f in b["frames"])
    ranked.append((area, total, bam, mw, mh, len(b["frames"]), len(b["cycles"]), b["file_size"], users))
ranked.sort(key=lambda r: (-r[0], -r[1]))

W("### 5a. Largest BAMs reachable from spells")
W("")
W(f"{len(ranked)} distinct BAMs are reachable from SPL files (direct play-BAM/MultipleVVC/casting-glow fx, "
  "chained Spell:Cast and SpecialEffect spells, projectile travel BAMs, area VVCs and payload spells). "
  "Ranked by the largest single frame (w x h). PST's game resolution is 640x480, so a 640-wide frame is a "
  "full-screen cinematic.")
W("")
W("`Max W x max H` takes the widest and the tallest frame separately (they can be different frames); "
  "elsewhere in this report `largest frame` means the single frame with the biggest area.")
W("")
W("| # | BAM | Max W x max H | Frames | Cycles | Sum of frame px | File bytes | Reached from spells |")
W("|---|---|---|---|---|---|---|---|")
for i, (area, total, bam, mw, mh, nf, nc, fs, users) in enumerate(ranked[:15], 1):
    W(f"| {i} | {bam} | {mw}x{mh} | {nf} | {nc} | {total:,} | {fs:,} | {', '.join(sorted(users))} |")
W("")

# named showcase cinematics
NAMED = ["Celestial Host", "Rune of Torment", "Elysium's Tears", "Mechanus' Cannon", "Abyssal Fury",
         "Power Word, Kill", "Meteor", "Elysium's Fires", "Desert Hell", "Conflagration", "Ax of Torment",
         "Blade Storm", "Chain Lightning Storm", "Acid Storm", "Ice Storm", "Deathbolt", "Ignus' Fury",
         "Power Word, Blind", "Fire and Ice", "Blacksphere"]
W("### 5b. The big cinematic spells by name")
W("")
W("| Spell | Resref | Lvl | Projectile | BAMs it reaches (frames, largest frame) |")
W("|---|---|---|---|---|")
by_name = defaultdict(list)
for n, s in SPELLS.items():
    by_name[s["name"].lower()].append(n)
for label in NAMED:
    hits = [n for n in by_name.get(label.lower(), []) if n.startswith(SPELL_PREFIXES)] or by_name.get(label.lower(), [])
    if not hits:
        # loose match
        hits = [n for n, s in SPELLS.items() if label.lower().replace(",", "") in s["name"].lower().replace(",", "")]
    if not hits:
        W(f"| {label} | not found in TLK names | | | |")
        continue
    for n in hits:
        s = SPELLS[n]
        parts = []
        for bam in sorted(spell_bams(n)):
            b = bam_info(bam)
            if b and b["frames"]:
                big = max(b["frames"], key=lambda f: f[0] * f[1])
                parts.append(f"{bam} ({len(b['frames'])}f, {big[0]}x{big[1]})")
        W(f"| {s['name']} | {n} | {s['level']} | {', '.join(spell_projectiles(s))} | {', '.join(parts) or '-'} |")
W("")

W("### 5c. Gaps and oddities found while resolving references")
W("")
gaps = []
for n in missing_pro:
    gaps.append(f"Projectile `{n}` is named in gemprjtl.ids and used by {', '.join(sorted(pro_users[n]))}, but no PRO file "
                "exists, so GemRB builds an empty default projectile.")
for name, s in sorted(SPELLS.items()):
    for _, fx in all_fx(s):
        if fx["opcode"] == 0xC5 and resolve_vef(fx["res"])[0] == "missing":
            gaps.append(f"`{name}` runs MultipleVVC `{fx['res']}`, but there is no VEF, 2DA, VVC or BAM of that name: it shows nothing.")
        if fx["opcode"] in PLAYBAM and resolve_anim(fx["res"])[0] == "missing":
            gaps.append(f"`{name}` plays `{fx['res']}` with {opname(fx['opcode'])}, but no VVC or BAM of that name exists.")
for name, p in sorted(PROS.items()):
    a = p.get("area")
    if not a:
        continue
    if a["frag_proj"] and not a["aflags"] & 16 and proj_ids.get(a["frag_proj"]):
        gaps.append(f"PRO `{name}` (used by {', '.join(sorted(pro_users.get(name, []))) or 'nothing'}) names fragment projectile "
                    f"`{proj_ids[a['frag_proj']]}` but lacks area flag PAF_SECONDARY (0x10), so `Projectile.cpp` never spawns it.")
    if a["expl_type"] < len(AREAPRO):
        missing = [r for r in AREAPRO[a["expl_type"]] if r != "*" and resolve_anim(r)[0] == "missing"]
        if missing and pro_users.get(name):
            gaps.append(f"PRO `{name}` (used by {', '.join(sorted(pro_users[name]))}) uses areapro.2da explosion type "
                        f"{a['expl_type']}, whose animations {', '.join(missing)} do not exist in PST, so no explosion is drawn.")
for name, v in sorted(VVCS.items()):
    if v["bam"] and not res.has(v["bam"], "bam"):
        gaps.append(f"VVC `{name}` points at BAM `{v['bam']}`, which PST does not have.")
    if not vvc_users.get(name):
        gaps.append(f"VVC `{name}` is not referenced by any SPL, ITM, PRO or VEF-style 2DA.")
for name, s in sorted(SPELLS.items()):
    if name.startswith(SPELL_PREFIXES) and s["name"] and not any(True for _ in all_fx(s)):
        gaps.append(f"`{name}` ({s['name']}) has no feature blocks at all.")
proj_names_used = set(pro_users)
reached_pros = set()
for n in SPELLS:
    c = Collector()
    c.spell(n, "")
    reached_pros.update(x for kind, x in c.seen if kind == "pro")
unreferenced = sorted(n for n in PROS if n not in proj_names_used and n not in reached_pros)
gaps.append(f"{len(unreferenced)} of {len(PROS)} PRO files are not reachable from any SPL, ITM or other PRO "
            "(table 3b), including the only two line projectiles SPSCORCH and SPSCORIC, and ROCK, which looks like "
            "the intended Meteor Storm fragment.")
for g in dict.fromkeys(gaps):
    W(f"- {g}")
W("")

# ---------------------------------------------------------------- party spellbooks


def cre_known(name: str) -> list[tuple[str, int, int]] | None:
    if not res.has(name, "cre"):
        return None
    b = res.get(name, "cre")
    if b[:8] != b"CRE V1.2":
        return None
    import struct
    off, cnt = struct.unpack_from("<2I", b, 0x344)
    out = []
    for i in range(cnt):
        e = off + 12 * i
        nm = b[e : e + 8].split(b"\0", 1)[0].decode("latin1").upper()
        lvl, typ = struct.unpack_from("<2H", b, e + 8)
        out.append((nm, lvl, typ))
    return out


PARTY = {}
for cre in ("DAKKON", "GRACE", "IGNUS", "ANNAH", "MORTE", "NORDOM", "VHAIL"):
    PARTY[cre] = cre_known(cre)

# ---------------------------------------------------------------- 6. showcase

SHOWCASE = [
    ("SPWI107", "TNO (mage)",
     "Bolt/missile. MMISS + MMISS2 multi-missile (curve, iteration) with PTF_LIGHT, so it tests travel BAM, "
     "curved paths, a moving light spot, and the S002 hit BAMs plus FlashScreen and ScreenShake. Level 1, repeatable."),
    ("SPWI218", "Ignus (in IGNUS.CRE)",
     "Orb bolt. IGNUSORB projectile: curved, touch attack, travel BAM S006CMBO, centre VVC IGNUSORB "
     "(transparency 0x200008 = blended + glowing). Glowing is still a TODO in GemRB's ScriptedAnimation.h, "
     "so this is a direct test case for implementing it."),
    ("SPWI313", "Ignus (in IGNUS.CRE)",
     "AoE explosion. FRAIN drops FBOMB falling bombs that explode with VVC S070BOOM, plus a 300x480 S070CSTR "
     "cast column, TintScreen and MoveView. Covers falling projectiles, area hits and screen tint at once."),
    ("SPWI502", "TNO (mage)",
     "Cone. COCOLD is a 60 degree cone area projectile with centre VVC S052CONE (200 frames, 640x480, "
     "transparent flag) plus TintScreen and PlayBAM3 S052HOWS. The only cone projectile with a centre VVC."),
    ("SPIN102", "Morte (innate, granted in play; not in MORTE.CRE at start)",
     "Second cone type. SKMOB is a 120 degree cone that spawns SKMOB2 fragments (K001SKMB skulls) with the "
     "CRUNMRTB travel BAM, so it tests the fragment/secondary path rather than a centre VVC. SPIN102 itself has "
     "no feature blocks; everything comes from the projectile."),
    ("SPPR301", "Fall-From-Grace (in GRACE.CRE)",
     "Strike from the sky (the closest PST has to a vertical ray). CALLIH: no-travel area projectile, centre "
     "BAM SP31CLLT (16 frames, 300x420), payload LIGHTNIN. Tests a tall centre animation and a delayed area hit. "
     "SPPR301 itself has no feature blocks."),
    ("SPWI803", "TNO (mage)",
     "Ray substitute. No PST spell uses a GemRB line projectile (SPSCORCH/SPSCORIC exist but nothing references "
     "them). Deathbolt's DBOLT draws S083BGCL, a 640x231 horizontal bolt, plus ScreenShake and PlayBAM5 S083DBHT "
     "on the target. Note its payload DBOLT.SPL calls MultipleVVC `DBOLT`, which resolves to nothing."),
    ("SPWI219", "Dak'kon (in DAKKON.CRE)",
     "Single-creature buff glow. POONE carries payload POO (PulseRGBGlobal + Overlay type 17) and the SPL plays "
     "PlayBAM1 S029GLOW and S029STMN (sticky, blended) on the target. Tests colour pulse plus a sticky BAM."),
    ("SPPR303", "Fall-From-Grace (in GRACE.CRE)",
     "Party buff. Prayer plays PlayBAM1 SP33HAND and PlayBAM5 SP33PRAY. Tests sticky BAMs on several party "
     "members at once and the 0xBF flag path (layer/blend bits)."),
    ("SPWI901", "TNO (mage, level 9)",
     "Big summoning cinematic. CHOST projectile (centre S091GATE) -> payload CHOST.SPL -> MultipleVVC "
     "`chost.2da` (19 rows, DELAY column 2..25) using S091* BAMs, including S091PHNX (132 frames, 640x480) and "
     "S091ARRS (640x408). Celestial Host is a wizard spell in PST, not a priest one."),
    ("SPWI914", "TNO (mage, level 9)",
     "Second full-screen cinematic with different plumbing: ROTORM area projectile spawns RUNE fragments, whose "
     "forced-failure payload RUNE.SPL plays `rune.2da` (6 rows: S914RUNE 50 frames up to 603x398, 4x S914BGBL, "
     "S914HGBL 591x406) plus ScreenShake and TintScreen. Its VVCs use the freeze and loop sequence flags."),
    ("SPWI807", "TNO (mage, level 8)",
     "Projectile into a near full-screen blast. MCANNON (speed 100, PTF_LIGHT) then payload MCANNON.SPL: "
     "PlayBAM1 S087BLST (96 frames, 640x408, area, not sticky), FlashScreen and ScreenShake."),
]

W("## 6. Showcase shortlist (12)")
W("")
W("Who can cast what (from the party CRE known-spell lists, CRE V1.2 offset 0x344):")
W("")
for cre, known in PARTY.items():
    if known is None:
        W(f"- `{cre}.CRE`: not found or not CRE V1.2")
    elif not known:
        W(f"- `{cre}.CRE`: no known spells")
    else:
        W(f"- `{cre}.CRE`: " + ", ".join(f"{n} ({SPELLS[n]['name'] if n in SPELLS else '?'})" for n, _, _ in known))
W("")
W("Annah, Nordom and Vhailor have no spells or innate abilities in their CREs, so none of the 12 is theirs. "
  "TNO's spellbook is not in a CRE (he learns spells in play), so any SPWI is reachable for him as a mage. "
  "PST has no Fireball, no true ray spell, and no priest summoning cinematic; the list uses the closest real "
  "equivalents and says so.")
W("")
W("| # | Resref | Name | Type | Lvl | Caster | Projectile | Visual resources (BAMs reached: frames, largest frame) | Why it is a good test |")
W("|---|---|---|---|---|---|---|---|---|")
for i, (n, who, why) in enumerate(SHOWCASE, 1):
    s = SPELLS.get(n)
    if s is None:
        W(f"| {i} | {n} | missing | | | {who} | | | {why} |")
        continue
    parts = []
    for bam in sorted(spell_bams(n)):
        b = bam_info(bam)
        if b and b["frames"]:
            big = max(b["frames"], key=lambda f: f[0] * f[1])
            parts.append(f"{bam} {len(b['frames'])}f {big[0]}x{big[1]}")
    W(f"| {i} | {n} | {s['name']} | {SPELL_TYPES.get(s['type'])} | {s['level']} | {who} | {', '.join(spell_projectiles(s))} | "
      f"{'; '.join(parts) or '-'} | {why} |")
W("")

visual_ops = [op for op in op_total if op in VISUAL]
visual_fx = sum(op_total[op] for op in visual_ops)
big = [r for r in ranked if r[3] >= 590]
key = [
    "## Key findings",
    "",
    f"- Effective counts: {COUNTS['spl']['effective']} SPL, {COUNTS['pro']['effective']} PRO, "
    f"{COUNTS['vvc']['effective']} VVC, {COUNTS['bam']['effective']} BAM, {COUNTS['itm']['effective']} ITM. "
    "Every PRO and VVC is GemRB's; the original game hardcoded them in Torment.exe.",
    f"- {len(visual_ops)} purely visual opcodes account for {visual_fx} of {sum(op_total.values())} feature blocks "
    f"in SPL+ITM. PlayBAM1 (0xBB) alone is {op_total[0xBB]}, the most used opcode in the game.",
    f"- PST play-BAM opcodes are 0xBB-0xBF (187-191), not 186-190: 0xBA is SetStatus. 0xBB is "
    "`fx_play_bam_blended`; 0xBC-0xBF all run `fx_play_bam_not_blended` with flag bits in p2. "
    f"They appear {len(playbam_rows)} times; 0xBE (PlayBAM4) is never used.",
    f"- {len(big)} spell BAMs have frames 590+ px wide (PST runs at 640x480): "
    + ", ".join(f"{r[2]} ({r[3]}x{r[4]}, {r[5]} frame{'s' if r[5] != 1 else ''})" for r in big) + ".",
    "- The multi-stage cinematics (Celestial Host, Rune of Torment) are GemRB 2DA sequences "
    "(`chost.2da`, `rune.2da`) played by opcode 0xC5 MultipleVVC (`fx_multiple_vvc` in PSTOpcodes.cpp) from GemRB helper SPLs.",
    "- Projectile light spots: GemRB draws one only with travel flag 0x40; "
    f"{len(light_drawn)} PROs qualify, {len(light_set) - len(light_drawn)} more carry unused light values.",
    "- Several visuals never play in GemRB as shipped (section 5c): Chain Lightning Storm's `lstorm.2da` and "
    "Blade Storm's BSTORM2 (fragments without PAF_SECONDARY), Deathbolt's MultipleVVC `DBOLT` (no such resource), "
    "Abyssal Fury and Blacksphere projectiles (no PRO), Meteor's `<stoned>` fragments. Found by reading data and "
    "`Projectile.cpp`; not checked in game.",
    "",
]
lines[KEY_AT:KEY_AT] = key

out_md = HERE / "pst_spell_visuals.md"
out_md.write_text("\n".join(lines), encoding="utf-8")


def jsonable(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o))


(HERE / "survey.json").write_text(json.dumps({
    "counts": COUNTS,
    "spells": SPELL_ROWS,
    "opcodes": {f"{op:#04x}": {"name": opname(op), "total": c, "spl": op_spl[op], "itm": op_itm[op],
                               "files": len(op_files[op]), "class": vis_class(op)} for op, c in op_total.items()},
    "projectiles": PRO_ROWS,
    "vvcs": VVC_ROWS,
    "playbam": [{"file": f"{k}:{n}", "where": w, **fx} for k, n, _, w, fx in playbam_rows],
    "top_bams": [{"bam": r[2], "w": r[3], "h": r[4], "frames": r[5], "cycles": r[6], "bytes": r[7],
                  "spells": sorted(r[8])} for r in ranked[:40]],
    "party": PARTY,
}, indent=1, default=jsonable), encoding="utf-8")
print("wrote", out_md, "lines", len(lines))
