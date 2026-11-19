# PST parity audit: sources, method, tools

This folder compares GemRB's Planescape: Torment support with the real engine.

- [HANDOFF.md](HANDOFF.md): current state and what to do next. **Read first in a new session.**
- [findings.md](findings.md): what is wrong or missing, with evidence. **Start here.**
- [spells.md](spells.md): the 36 hardcoded spells, EE engine vs GemRB (generated).
- [opcodes.md](opcodes.md): every opcode PST data uses → GemRB fx, EE class, original handler (generated).
- [scripting.md](scripting.md): actions and triggers used by scripts/dialogs, GemRB status, original handler (generated).
- [pst_functions.md](pst_functions.md): every PST-only engine function in PST:EE, the rules checklist (generated).
- The plan: [PARITY_PLAN.md](../../PARITY_PLAN.md).
- [maps/](maps/README.md): where everything lives in both binaries (address maps, struct offsets), as text. No IDA needed to use them.
- [AGENT_GUIDE.md](AGENT_GUIDE.md): step-by-step instructions for an agent that continues the investigation.

Tools added for that: `tools/parity/ida.py` (one-command decompile/xrefs/vtables/search), `tools/parity/iesdp.py`
(IESDP lookups; the site is at `iesdp-gh-pages/`, git-ignored) and `tools/parity/strings.py` (EE string dump).

## Sources

| Source | Where | Used for |
|---|---|---|
| Original Torment.exe 1.1 (+Fixpack 4.13, UB 4.12) | `C:\Program Files (x86)\Black Isle\Torment` | **Ground truth.** Not packed; MSVC asserts name the source file of many functions (`F:\Torment\Source\baldur\CGameEffect.cpp`, …), see `.re/orig/dump/srcmap.txt`. |
| PST:EE Linux binary `Torment64` | `D:\GOG Games\Planescape Torment - Enhanced Edition` | **Map with names.** It keeps full C++ symbols (21,704 functions, e.g. `CPsSpellIceKnife::AIUpdate`) and Hex-Rays decompiles it. Use it to find and understand code, then confirm in the original, because EE changed things. |
| PST:EE data | same | `.pro` files and tables Beamdog moved out of the exe; data fixes. |
| GemRB | `gemrb/unhardcoded/pst`, `gemrb/plugins/*Opcodes`, `gemrb/core/GameScript` | What we do today. |
| Spell suite | `dev/spell_report.md`, `dev/spell_suite.jsonl` | What actually happens in game. |

IDA Professional 9.1 runs headless (`idat.exe -A -S<script>`), with the x86 and x64 decompilers.

## Workspace

The IDA databases, decompiled code and JSON are kept in **`D:\gemrb\.re\`**, which is git-ignored through
`.git/info/exclude`. The decompiled code belongs to Black Isle and Beamdog: it never goes into the repo. Only
the tools and our own findings are committed.

```
.re/orig/Torment.exe(.i64)   original exe + IDA database
.re/orig/dump/               funcs.txt, strings.txt (string → referencing functions), srcmap.txt, dec/<addr>.c
.re/ee/Torment64(.i64)       EE Linux binary + IDA database
.re/ee/dump/                 funcs.txt (demangled), names.txt (incl. vtables), dec/<Class_Method>.c
.re/*.json                   tool output
```

## Rebuilding everything

Run from any folder; the tools `chdir` to `PARITY_WORK` (default `D:\gemrb\.re`). An IDA pass takes 1–5 minutes.

```powershell
$ida = "C:\Program Files\IDA Professional 9.1\idat.exe"
# 1. analyse (once)
& $ida -A -B -L"D:\gemrb\.re\orig\ida.log" D:\gemrb\.re\orig\Torment.exe
& $ida -A -B -L"D:\gemrb\.re\ee\ida.log" D:\gemrb\.re\ee\Torment64
# 2. dumps
& $ida -A -S"D:/gemrb/tools/parity/dump.py" D:\gemrb\.re\orig\Torment.exe.i64        # funcs + strings
& $ida -A -S"D:/gemrb/tools/parity/ee_list.py" D:\gemrb\.re\ee\Torment64.i64          # demangled funcs
& $ida -A -S"D:/gemrb/tools/parity/names.py" D:\gemrb\.re\ee\Torment64.i64            # names + vtables
# 3. decompile: EE by name substring (.re/ee/decomp_list.txt), original by address (.re/orig/decomp_ea.txt)
& $ida -A -S"D:/gemrb/tools/parity/decomp.py" D:\gemrb\.re\ee\Torment64.i64
& $ida -A -S"D:/gemrb/tools/parity/decomp_ea.py" D:\gemrb\.re\orig\Torment.exe.i64
#    vtable slots (.re/*/vt_ea.txt) and callers (.re/orig/xref_ea.txt)
& $ida -A -S"D:/gemrb/tools/parity/vt.py" D:\gemrb\.re\orig\Torment.exe.i64
& $ida -A -S"D:/gemrb/tools/parity/xrefs.py" D:\gemrb\.re\orig\Torment.exe.i64
```

Then the Python passes, in order:

| Tool | Output | What it does |
|---|---|---|
| `pstres.py` | — | KEY/BIF/override reader for the original, EE and "what GemRB sees" (GemRB's unhardcoded data first). |
| `opcodes.py` | `opcodes.json` | Every opcode in PST data → GemRB effects.ids name → `fx_` function, plus hints from GemRB's source. |
| `scripts.py` | `scripts.json` | Every action/trigger in BCS + DLG → GemRB's tables. |
| `ee_opcodes.py` | `ee_opcodes.json` | EE opcode → effect class (`CGameEffect::DecodeEffect` switch + vtable symbols). |
| `opmap.py` | `opmap.json` | Aligns the same SPL/ITM in the original and EE (difflib on parameters) → which EE effect each PST opcode became. |
| `projmap.py` | `projmap.json` | Projectile number of every spell/item: GemRB row and file vs EE. |
| `prodiff.py`, `gemext.py`, `pssum.py` | `prodiff.json`, `gemext.json`, `pssum.md` | The 36 `CPsSpell*` classes: assets, GemRB projectile and its helper SPLs. |
| `derive.py` | `psbehav.json`, `orig_*.json` | Code-applied effects per spell class; the original's opcode vtables, handled actions and triggers. |
| `gen_docs.py` | `dev/parity/*.md` | The generated tables in this folder. |
| `export_maps.py` | `dev/parity/maps/*.tsv` | Address maps (opcodes, actions, triggers, projectiles, known functions, EE symbols, strings). Rerun after new decompiles. |

## Tips for reading the original

- Effect `ApplyEffect`: opcode N → `orig_apply.json[N]` → `.re/orig/dump/dec/<addr>.c`. The effect object has
  parameter1 at `+8`, parameter2 at `+12`, timing at `+16` and duration at `+18`.
- Creature fields: find the field in EE first (named, e.g. `CDerivedStats`), then match the offset pattern in
  the original. Common ones: `+1288` base state, `+3204` derived state, `+1292` current HP.
- Actions: `sub_76A7EA` (creature) → `byte_76D476[id]` → case; the rest goes to `sub_44B099`.
  Triggers: `sub_453258` and `sub_778529`.
- A string → function lookup (`strings.txt`) is often the quickest way into a feature, through resrefs,
  `.cpp` asserts or log text.
