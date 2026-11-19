# PST parity investigation: instructions for an agent

You are continuing a reverse-engineering audit. The goal is to find **every** place where GemRB (an open-source
re-implementation of the Infinity Engine, in this repository) behaves differently from the real Planescape:
Torment engine, and to write each difference down with proof. **You investigate and document. You do not fix
anything.** Fixing comes later, from your notes.

Read this whole file before you start. Then read, in this order:
1. `dev/parity/findings.md`: what is already known. Do not re-report it; extend it.
2. `dev/parity/README.md`: tools and file layout.
3. `PARITY_PLAN.md`: why the work is ordered as it is.

---

## 0. The rules (do not break these)

1. **Do not change engine code, game data or GemRB data files.** You only write under `dev/parity/` and, if a
   new tool is needed, under `tools/parity/`. Nothing else. If you think something must be fixed, write it as
   a finding.
2. **Never copy decompiled code into the repository.** Decompiled code (`.re/**/dec/*.c`) belongs to Black Isle
   and Beamdog. In findings, describe behaviour in your own words: conditions, numbers, order of operations.
   Short identifiers are fine (function names, addresses, constants, resource names, variable names). Pasting
   C code blocks is not.
3. **The original exe is the truth.** Ranking of sources, highest first:
   1. Original `Torment.exe` (decompiled at `.re/orig/`). This is PST 1.1 with Fixpack and UB installed.
   2. PST:EE `Torment64` (`.re/ee/`). It has real function names, so read it first to understand a feature,
      but **Beamdog changed things**. Before you call something a GemRB bug, find the same logic in the
      original. If you can't, mark the finding **S** (suspected) and say "EE only, not found in original yet".
   3. IESDP (`iesdp-gh-pages/`, via `tools/parity/iesdp.py`): community notes. Useful hints, often
      incomplete, sometimes wrong. Example: for opcode 186 IESDP says "0 = clear", but the original clears on
      −1 and ignores 0. Never use IESDP alone as proof.
   4. GemRB comments ("pst does X") are claims, not proof.
4. **Every finding needs evidence** a person can check in under a minute: original address
   (`sub_4B5DCF`), EE function name, GemRB `file:line`, the game files involved, and the numbers.
5. **Be honest about certainty.** Use the status codes in section 5. "I could not find it" is a valid result;
   write it down.
6. **Do not run two IDA commands on the same database at the same time.** The `.i64` is locked while IDA has it
   open. Run IDA commands one after another.
7. **Do not commit** unless the person running you says so. If they do, commit only `dev/parity/` and
   `tools/parity/` files.

---

## 1. Your toolbox

All commands are run from `D:\gemrb` in PowerShell or Git Bash. Python is `python`.

### 1.1 IDA helper: `tools/parity/ida.py`

| Command | What it does | Speed |
|---|---|---|
| `python tools/parity/ida.py find ee "Nameless"` | Search EE function names (demangled), printing `address size name` | instant |
| `python tools/parity/ida.py find orig "sub_4B5"` | Search original function names (mostly `sub_XXXXXX`) | instant |
| `python tools/parity/ida.py str ee "Game_Over"` | Strings in the EE binary and the functions that use them | instant |
| `python tools/parity/ida.py str orig "Game_Over"` | Same for the original. **The best way into the original** | instant |
| `python tools/parity/ida.py dec ee "CPsSpellPacify::"` | Decompile every EE function whose name contains the text. End with `$` for an exact name | 1–3 min |
| `python tools/parity/ida.py dec orig 4C61EB 4C66BE` | Decompile original functions by hex address | 1–3 min |
| `python tools/parity/ida.py xrefs orig 4B245B` | Every caller of an address | 1–3 min |
| `python tools/parity/ida.py vt orig 8DE26C` | First 24 entries of a vtable | 1–3 min |
| `python tools/parity/ida.py show orig 4B245B` | Print a function that is already decompiled | instant |

Decompiled output goes to `.re/<game>/dump/dec/`. **Look there first.** About 640 EE files and 230 original
files already exist (all effect handlers, all `CPsSpell*` classes, the action and trigger dispatchers, the
PST rule functions). Use `ls .re/ee/dump/dec | grep -i <word>`.

Batch several names or addresses into one `dec` call: each call costs an IDA start-up.

### 1.2 Data reader: `tools/parity/pstres.py`

```python
import sys; sys.path.insert(0, r"D:\gemrb\tools\parity")
import pstres
o = pstres.orig()    # original game: override + bifs (Fixpack + UB)
e = pstres.ee()      # PST:EE
g = pstres.gemrb()   # what GemRB loads: gemrb/unhardcoded/pst, then shared, then the original game
d = g.res("SPWI805", "spl")        # bytes, or None
g.where("SPWI805", "spl")          # which folder/bif it comes from
g.names("bcs")                     # every BCS resref
pstres.text(o.res("action", "ids"))  # 2DA/IDS as text (decrypts if needed)
o.string(1234)                     # dialog.tlk string
```

File formats (byte offsets of SPL, ITM, CRE, PRO, EFF and so on): `python tools/parity/iesdp.py format spl_v1`
(names as in `iesdp-gh-pages/file_formats/ie_formats/`). There is also `tools/tb_gamedata.py`
(`GameData().spell("SPWI805")` gives parsed headers and effects).

### 1.3 IESDP lookup: `tools/parity/iesdp.py`

```
python tools/parity/iesdp.py opcode pst 192
python tools/parity/iesdp.py action pst 22
python tools/parity/iesdp.py trigger pst 0x4092
python tools/parity/iesdp.py grep pst "Embalm"
```

### 1.3a Maps (start here for "where is X")

`dev/parity/maps/*.tsv` (see its README): opcode, action, trigger and projectile number → original function
addresses; struct offsets; known-function index. Grep them first, then open the `.c` file they name. After you
decompile something new, run `python tools/parity/export_maps.py`.

### 1.4 Existing generated tables (read these, don't regenerate unless needed)

- `dev/parity/opcodes.md`: every opcode PST data uses, GemRB function, EE class, original handler address, use count.
- `dev/parity/spells.md`: the 36 hardcoded spells.
- `dev/parity/scripting.md`: every action/trigger PST scripts use, with use counts and GemRB status.
- `dev/parity/pst_functions.md`: every PST-only EE function, biggest first.
- `.re/*.json`: raw data behind those tables (`orig_apply.json` = opcode → original handler address,
  `opmap.json` = PST opcode → EE class, `fxspecial.json` = PST special cases per EE effect class,
  `psbehav.json`, `gemext.json`, `scripts.json`, `orig_actions.json`, `orig_triggers.json`).

### 1.5 GemRB source map

| What | Where |
|---|---|
| Effect opcodes | `gemrb/plugins/FXOpcodes/FXOpcodes.cpp`, `gemrb/plugins/PSTOpcodes/PSTOpcodes.cpp`, `gemrb/core/EffectQueue.cpp` |
| Which name each PST opcode number has | `gemrb/unhardcoded/pst/effects.ids` |
| Script actions / triggers | `gemrb/core/GameScript/Actions.cpp`, `Triggers.cpp`, the tables in `GameScript.cpp` (`actionnames[]`, `triggernames[]`) |
| Projectiles | `gemrb/core/Projectile.cpp`, `gemrb/plugins/PROImporter/PROImporter.cpp`, files in `gemrb/unhardcoded/pst/*.pro`, row → name in `gemrb/unhardcoded/pst/gemprjtl.ids` |
| GemRB's helper spells for PST | `gemrb/unhardcoded/pst/*.spl` |
| Creature rules (damage, death, saves, levels) | `gemrb/core/Scriptable/Actor.cpp` |
| PST start-of-game / death / respawn | `gemrb/core/IniSpawn.cpp`, `gemrb/unhardcoded/pst/source/baldur.baf` |
| PST GUI rules (level-up, records) | `gemrb/GUIScripts/pst/*.py` |
| Feature switches for PST | search `PST_` in `gemrb/core/` (`GFFlags::PST_STATE_FLAGS` and others) |

Use the Grep tool or `grep -rn` to find a function. Always quote GemRB as `path:line`.

---

## 2. How to read decompiled code (important, read twice)

### 2.1 The two binaries are different

- **Original:** 32-bit MSVC. Methods are `__thiscall`: `this` is the object, `a2` is usually the target creature.
  Fields appear as `*(_DWORD *)(this + 12)` (byte offset) or `this[3]` (index × 4 bytes: `this[3]` = byte 12).
- **EE:** 64-bit GCC with names. Field offsets are **different** from the original (pointers are 8 bytes,
  structures were changed). **Never reuse an offset from EE in the original, or the other way round.** Match
  by logic and constants instead.

### 2.2 Known offsets (original exe)

Effect object (`this` inside an `ApplyEffect`):

| Byte | Meaning |
|---|---|
| +8 (`this[2]`) | parameter1 |
| +12 (`this[3]`) | parameter2 |
| +16 | timing mode (word) |
| +18 | duration |
| +24 (`this + 6` as `_DWORD*`) | resource (8 chars) |
| `this[17]` (+68) | "done/remove" flag that ApplyEffect sets (1 = finished) |
| `this[49]` | "first time" flag (ApplyEffect often does work only when it is set, then clears it) |

Creature (`a2`):

| Byte | Meaning |
|---|---|
| +84 | global object id |
| +1172 | script name (death variable) |
| +1288 | base state bits (`STATE_*`) |
| +1292 | current HP (signed 16-bit; ≤ −10 is "dead") |
| +3204 | derived state bits |
| +7146/+7150 | animation object |

Confirm any new offset in at least two places before you rely on it, and add it to this table in your notes.

### 2.3 Known offsets (EE) that helped

Creature: `+1396` current HP, `+1398` max HP, `+4072` derived stats (`CDerivedStats`), `+4073 & 8` = probably
the "dead" state bit (skipped by every targeting loop), `+18512/+18520` object type / EA. These are EE offsets only.

### 2.3a Before you begin

Check that the workspace exists: `ls .re/orig/Torment.exe.i64 .re/ee/Torment64.i64 .re/ee/dump/strings.txt`.
If any file is missing, stop and tell the person: section "Rebuilding everything" in `dev/parity/README.md`
recreates them (about 15 minutes of IDA time).

### 2.4 Finding the original equivalent of an EE function

Try these in order:
1. **Strings.** Pick a literal the EE function uses (a resref like `"SPWI805"`, a variable like
   `"Fortress_Death_Counter"`, a format string) and run `ida.py str orig "<literal>"`. The third column names the
   original function.
2. **Source-file asserts.** `.re/orig/dump/srcmap.txt` maps original functions to the `.cpp` file their
   assert strings mention (`CGameEffect`, `ObjCreature`, `CProjectile`, …). EE class names map onto those files.
3. **Dispatchers.** These are already identified:
   - Effects: `sub_4A5C21` builds the effect object for opcode N. Its `ApplyEffect` is `.re/orig_apply.json[N]`.
   - Projectiles and hardcoded spells: `sub_559A5D` (switch on projectile number).
   - Actions: `sub_76A7EA` (creature level; `byte_76D476[action id]` gives the case number; id 313 is case 57;
     ids above 0x12F and unhandled cases fall through to `sub_44B099`, the base switch).
   - Triggers: `sub_453258` (base) and `sub_778529` (creature level).
   - Script compiler/parser: `sub_41D7BC` (not a dispatcher, ignore).
4. **Callers.** `ida.py xrefs orig <addr>` on a function you know, then walk up or down.
5. **Constants.** Distinctive numbers (241, 160, 0x800, 100-HP pools) appear in both binaries.

### 2.5 Reading tips

- Hex-Rays names are random (`v23`). Rename them in your head and in your notes ("v28 = HP pool").
- `rand() % 241 + 160` means 160–400. Write ranges, not formulas.
- `sub_89BC79("Name")` / `sub_463F03(&dword_96EDC8, …)` in the original: build a CString and look up a GLOBAL
  variable; `+40` on the result is the variable's value.
- `CGameEffect::ClearItemEffect(v, 74)` in EE: start building an effect with opcode 74. The lines after it fill
  its fields; `CGameEffect::DecodeEffect` creates it, and a virtual call at `+240` on the creature adds it.
- Ticks: 15 ticks = 1 second (AI updates). A round is 75 ticks (5 s) in this fork.
- **Vtables (original):** slot 2 is `ApplyEffect`. A 5-line ApplyEffect that only sets `this[17] = 1` does
  nothing. Check the other slots against the defaults before saying "no-op" (see findings section 7).

---

## 3. Work packages

Do them in this order. Each one has its own output file, so the packages can't collide. Inside a package,
work in the order given (most important first). After every 5–10 items, save your file. Don't keep findings
only in your head.

### WP1: per-spell expectations (highest priority)

**Why:** the spell test (`tools/tb_spell_suite.py`) only checks that *something* happened. It needs to know what
*should* happen.

**Items:** the 36 `CPsSpell*` classes listed in `dev/parity/spells.md`, plus `CPSTSpellMechanusCannon`,
`CPSTSpellSpiritualHammer` and `CPSTSpellCallLightning`.
Order: Abyssal Fury, Power Word Blind, Power Word Kill, Ice Knife, Bladestorm, Celestial Host, Rune of Torment,
Blacksphere, Missile of Patience, Meteor Storm Bombardment, Stygian Ice Storm, Howl of Pandemonium, Pacify,
Hold Undead, Fire and Ice, Ignus' Fury, Swarm Curse, Chain Lightning Storm, Death Bolt, Desert Hell,
Conflagration, Elysium's Fires, Elysium's Tears (+Meteor), Cloud Kill, Vampiric Touch, Tasha's, Shroud of
Shadows, Globe of Invulnerability, Embalming, Strength, Improved Strength, Power of One, Force Missile,
Ball Lightning, Ax of Torment, then the three `CPSTSpell*`.

**Steps for one spell:**
1. Decompiled files: `ls .re/ee/dump/dec | grep CPsSpell<Name>`. Usually there are a constructor, `Fire`,
   `AIUpdate`, sometimes `OnArrival`, `TransferEffects`, `CheckForTargets`, `Render`.
2. Read the constructor (resources, sizes, flags), then `Fire` (what happens at launch), then `AIUpdate`
   (the state machine: what happens each tick, when it hits, when it ends).
3. Read the spell's own SPL in the original (`tb_gamedata.GameData().spell("SPWIxxx")`): effects, target type,
   range, projectile number.
4. Answer these questions. Every one needs an answer, or "not in code":
   - **Targets:** who can be hit? (radius in pixels/feet, allies? caster? undead only? sorted by HP? how many?)
   - **Roll:** attack roll (`ProjectileRollToHit`), saving throw (which type), magic resistance?
   - **Effects in the SPL** that are applied (all, or only some headers? per target or once?)
   - **Effects created in code:** opcode, parameter1/2, duration (ticks), random ranges.
   - **Damage:** dice, scaling (caster level, `CheckForIncreasedSpellLevel`), damage type.
   - **Timing:** when the damage lands relative to cast start (ticks), how long the whole spell runs.
   - **Side effects:** creatures moved, screen freeze, background change, flashes, sounds, script triggers
     (`SendHitTrigger`).
   - **Visuals and sounds:** resrefs played and in which order (a short list is enough).
5. Find the same spell in the original: `ida.py str orig "<a resref from step 1>"` and confirm at least the
   targeting rule and the numbers. Write `orig: sub_XXXXXX` or `orig: not found`.
6. Compare with GemRB: the `.pro` (`gemrb/unhardcoded/pst/<name>.pro`; its row in `gemprjtl.ids` is the SPL
   projectile number minus 1). Read its helper spells (`failureSpell` at offset 0x44 and `successSpell` at
   0x4C of the PRO, 8-char resrefs) and any GemRB code special-casing the spell
   (`grep -rn "<resref>\|<projectile id>" gemrb/`). List each question in step 4 where GemRB differs.
7. Write the entry in **`dev/parity/spell_expect.md`** (human-readable, template in section 4.2) **and** in
   **`dev/parity/spell_expect.json`** (machine-readable for the suite, schema in 4.3).

### WP2: effect opcodes side by side

**Items:** every row of `dev/parity/opcodes.md`. Order: PST-only first (186–212, 82, 100, 138, 146–148), then
by use count (12, 187, 146, 174, 54, 0, 191, 147, …), then the rest.
**Output:** `dev/parity/wp2_opcodes.md`, one entry per opcode (template 4.1, shortened).

Steps for opcode N:
1. Original: `python tools/parity/ida.py show orig <orig_apply.json[N]>`. If it is tiny, check its vtable for
   other overridden slots (`ida.py vt orig <vtable from orig_opvt.json[N]>`).
2. EE: the class from `opcodes.md` → `ls .re/ee/dump/dec | grep <Class>_`; read `ApplyEffect`, `OnAddSpecific`,
   `CheckSave`, `OnRemove`.
3. GemRB: the `fx_` function from `opcodes.md` (grep `^int fx_name` in the plugins).
4. Compare: parameter meanings (every value of parameter2 the PST data uses: see `.re/opcodes.json` `p2`),
   timing handling, caps and limits, saving throws, special resrefs, plane checks, spell states, sub-effects,
   what happens on removal.
5. Verdict: **match**, **differs** (say exactly how), **missing**, or **not checked**.

### WP3: PST branches in generic effects

**Items:** the table in findings section 8 plus every class in `.re/fxspecial.json` with `ENGINE_MODE == 3` or a
non-empty `resrefs`/`planes`/`spellstates`. Read only the branch and compare it with GemRB.
**Output:** append to `dev/parity/wp2_opcodes.md` under a heading "PST branches".

### WP4: script actions

**Items:** `dev/parity/scripting.md` "All actions used" (147). Order: the remaining Ex actions first
(`RunAwayFromEx` NoAttacks, `DeactivateEx` RenderMode, `FullHealEx`, `StartCutSceneEx`), then by use count.
**Output:** `dev/parity/wp4_actions.md`.

Steps for action id A:
1. Signature and documentation: `python tools/parity/iesdp.py action pst A`.
2. Original handler: if `A <= 0x12F`, the case number is `byte_76D476[A]` (read it with `tools/parity/pe.py`:
   `PE(r".re\orig\Torment.exe").bytes(0x76D476 + A, 1)`). Find `case <n>:` in `.re/orig/dump/dec/76A7EA.c`.
   If that case is `goto LABEL_214` or A > 0x12F, look for `case A:` in `.re/orig/dump/dec/44B099.c`. Handlers
   often call one `sub_`: decompile it.
3. Action parameters on the creature's current action (original): the current action id is the word at
   creature +962, int0 is at +1132 (`this[283]`) and int1 at +1136 (seen in `sub_785E47`, `sub_7A0423`, case 72).
   int2 is probably +1140: confirm it before you rely on it. Strings and objects are stored elsewhere: find
   them by reading.
4. GemRB: `GameScript::<Name>` in `gemrb/core/GameScript/Actions.cpp`.
5. Compare: parameters used, blocking or instant, what it does when the target is missing or dead, side
   effects (variables, journal, XP, party changes), PST-only behaviour.

### WP5: triggers

**Items:** `scripting.md` triggers (102). Original: `case <id>:` in `453258.c` or `778529.c`. GemRB:
`GameScript::<Name>` in `Triggers.cpp`. Same comparison style. **Output:** `dev/parity/wp5_triggers.md`.
Event triggers (ids below 0x4000, like `AttackedBy` and `Died`) are set elsewhere: find where the original
sets them (`str orig` on the trigger name rarely works; look for callers that write trigger ids).

### WP6: PST rule functions

**Items:** `dev/parity/pst_functions.md` (140), biggest first. Skip pure UI, cheats and rendering, and say
that you skipped them. Most important: `HandleNamelessDeath`, `GetNamelessRevivalReaction`,
`HandleNamelessBonuses`, `AssignFighterProficienciesOnLevelUp`, `SpellPST`, `SpellPointPST`, `ForceSpellPST`,
`ForceSpellPointPST`, `MultiFireSpell`, `IsProjectileTargetAffected`, `ProjectileRollToHit`, `DoesTrapHitTarget`,
`EffectDamageDecodeHitSound`, `PSTCanRestParty`, `IsSpriteInDark`, `SetGameFreeze`, `PlanescapeLeaveAreaName`,
`AreaFirstAIUpdate`, `IsWorldMapTrigger`, `CacheNamelessFactionFlags`, `LetMorteBeCreepy`, `GetGraceRingJoke`,
`SetNamelessClass`, `HandleTormentNPCs`.
**Output:** `dev/parity/wp6_rules.md`. For each: what it does, where the original has it, what GemRB does
(name the file), verdict.

### WP7: rule tables and formulas

Compare GemRB's PST tables (`gemrb/unhardcoded/pst/*.2da`) and hardcoded formulas with the original:
XP per level, HP per level, THAC0 per level, saving throws per level, thief skill base values, weapon
proficiency limits, ability modifiers (STR to-hit/damage, DEX AC/missile, CON HP, INT/WIS spell slots), lore,
regeneration, rest healing, encumbrance, movement speed. Find each in the original (the 2DA it reads, or the
constant in code). The tables EE moved out of the exe (`XPLIST`, `XPBONUS`, `HPCLASS`, `CLSWPBON`,
`ABCLSMOD`, `SPLPROT`, `NUMWSLOT`, `ITEMEXCL`, `PSTCHAR`, `THIEFSKL`, `THIEFSCL`) are hints only.
**Output:** `dev/parity/wp7_tables.md`, with a value-by-value diff where they differ.

### WP8: GemRB's own PST hacks

`grep -rn -i "pst" gemrb/core gemrb/plugins --include=*.cpp` plus `GFFlags::PST_` and `HasFeature`. Every
PST-specific branch in GemRB is a claim about the original: check each against the exe.
**Output:** `dev/parity/wp8_gemrb_pst_code.md`.

### WP9: EE data changes (lowest priority)

`.re/opmap.json` → `changed` lists 734 SPL/ITM files whose effects differ in EE. Sample 50, sort them into
*bug fix*, *rebalance* and *EE engine change*, and estimate the totals. **Output:** `dev/parity/wp9_ee_data.md`.

---

## 4. Output formats

### 4.1 A finding (all WP files)

```
### <ID> <one-line title>
- **Status:** V | S | P | ?      **Severity:** 1 | 2 | 3
- **Original:** sub_XXXXXX (what it does, in words; numbers)
- **EE:** Class::Method (only if it adds something)
- **GemRB:** path/to/file.cpp:123 `function` (what it does)
- **Difference:** exactly what is wrong or missing, with an example ("STR 16 + roll 5 → GemRB 19, original 18")
- **Data affected:** which spells/items/scripts, with use counts if known
- **Check in game:** one sentence on how to see it (optional)
```

IDs: WP1 `X-<SPLRES>` (e.g. `X-SPWI805`), WP2/3 `E-<opcode>`, WP4 `A-<id>`, WP5 `T-<hex id>`, WP6 `R-<short name>`,
WP7 `D-<table>`, WP8 `G-<n>`, WP9 `EE-<n>`. Before adding one, check `findings.md` for an existing finding
and refer to it instead of duplicating.

**Status:** V = verified in the original *and* in GemRB's source; S = suspected (only EE, or the code is unclear);
P = parity holds (GemRB matches, or it is a harmless difference); ? = could not determine (say why).
**Severity:** 1 = gameplay wrong or a feature does nothing; 2 = wrong numbers or detail; 3 = presentation only.

### 4.2 Spell expectation (dev/parity/spell_expect.md)

```
## SPWI805 Power Word, Blind
- **Engine:** CPsSpellPowerWordBlind (EE) / orig sub_XXXXXX
- **Targets:** all creatures within N of the point, not dead, HP between −9 and 99, sorted by current HP ascending;
  stops once the summed HP would exceed 100
- **Roll:** none
- **Effects:** op 74 blindness, duration by pool: ≤25 → 160–400 ticks, 26–50 → 80–200, >50 → 16–40;
  op 9 glow pulse, same duration; source set to SPWI805
- **Timing:** effects land at tick T after cast; spell ends at tick U
- **Side effects:** hit trigger per target; screen tint restored at the end
- **Visuals/sounds:** PWBLI03, PWBLI05, …
- **GemRB today:** pwblind.pro → PWB.spl (194, 74, 51): no HP pool, fixed duration X
- **Differences:** 1) no HP pool  2) duration fixed  3) …
```

### 4.3 Spell expectation (dev/parity/spell_expect.json)

One object per spell, keyed by SPL resref. Only facts the suite can check:

```json
{
  "SPWI805": {
    "targets": {"radius": 0, "hp_pool": 100, "sort": "hp_asc", "excludes": ["dead"]},
    "roll": "none",
    "effects": [
      {"op": 74, "duration_ticks": [[0, 25, 160, 400], [26, 50, 80, 200], [51, 100, 16, 40]], "duration_by": "pool"},
      {"op": 9}
    ],
    "damage": null,
    "lands_after_ticks": null,
    "notes": "durations depend on the HP pool used so far"
  }
}
```

Use `null` for unknown and say in `notes` why.

---

## 5. Working method (how not to get lost)

1. **One item at a time.** Finish the entry (even if the result is "?") before you move on.
2. **Keep a progress line** at the top of each WP file: `Done: 12/39. Next: SPWI702.`
3. **Show numbers, not adjectives.** "Duration 160–400 ticks", not "long duration".
4. **When stuck for more than ~15 tool calls on one item,** write what you know with status "?" and what blocked
   you, then move on.
5. **Double-check every V.** Before you mark something V, reopen the original function and the GemRB line and
   confirm both say what you wrote.
6. **Don't trust the automated tables blindly.** Known false positives: `spells.md` "Code ops" (GemRB may do the
   same through its own PST overlay types, e.g. Strength through `fx_overlay` case 17); `opcodes.md`
   "GemRB note" (a keyword hint only); `scripting.md` "MISSING" on Ex names (GemRB binds one of the two names).
7. **Common traps:**
   - The same opcode number means different things in PST, BG2 and EE. Always use the PST meaning
     (`gemrb/unhardcoded/pst/effects.ids` for GemRB's name, the original handler for the truth).
   - EE renumbered PST's effects (186+ became 3xx in EE). `opcodes.md` lists both.
   - Fixpack and UB changed the original data. "Original data" here always includes them, and
     `WeiDU.log` in the game folder lists the components.
   - Some `action.ids` lines were added by Fixpack, but the engine handled those actions all along (e.g. 313).
   - A trigger with no handler is always false in the original. That is parity, not a bug.
   - GemRB's turn-based combat changes timing and rounds deliberately. Compare logic and numbers, not
     wall-clock timing.
8. **When you finish a work package**, add one line to the "Progress" table in `PARITY_PLAN.md`
   (date, package, counts, top three findings), and move important new findings into `findings.md` with the
   next free ID in the right section.

---

## 6. Worked example (the pattern to copy)

Question: "Does Litany of Curses (op 82) behave like the original?"

1. `opcodes.md` row 82: GemRB `fx_set_ai_script`, EE `InciteRunningAttack (358)`, original apply `4C2218`.
2. `ida.py show orig 4C2218`: on the first application it builds a script action with id 10, sets its target from
   the creature and pushes it onto the target's action queue. `iesdp.py action pst 10` says id 10 is `Enemy()`.
3. `iesdp.py opcode pst 82`: "incites a repeating RunningAttack … chosen target is always male/undead". That
   agrees (Morte), so it supports the reading.
4. GemRB `gemrb/plugins/FXOpcodes/FXOpcodes.cpp:3307`: sets the override script to `SPIN101` permanently.
5. Finding: V, severity 1. The original makes the target hostile/attack for the effect's duration; GemRB
   swaps a script and never restores it. Data: SPIN101.spl (1 use).

That is the level of detail and proof every entry needs.
