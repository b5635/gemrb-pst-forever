# Maps of the original engine (text, version controlled)

These files say **where** each piece of PST logic lives in the two binaries and how the pieces connect. They
hold addresses, names, numbers and short identifier strings only, never decompiled code. Our descriptions of
what the code *does* are in `../findings.md`, `../spell_expect.md` and the `../wp*_*.md` files.

**You don't need IDA to use them.** Every address with `decompiled = y` has its decompiled body in the
git-ignored workspace (`.re/orig/dump/dec/<addr>.c`, `.re/ee/dump/dec/<Class_Method>.c`), so grep and read that.
Only run IDA (`tools/parity/ida.py dec …`) for a function that isn't decompiled yet. Then rerun
`python tools/parity/export_maps.py` so the maps pick it up.

| File | Rows | What |
|---|---|---|
| `opcodes.tsv` | 203 | PST opcode → GemRB name and `fx_` function, use count in game data, original ApplyEffect (vtable slot 2) and vtable |
| `actions.tsv` | 283 | action id → `action.ids` signature, case number in the creature dispatcher `sub_76A7EA` (or base `sub_44B099`), the `sub_` the case calls, script use count |
| `triggers.tsv` | 178 | trigger id → dispatcher (`sub_453258` base, `sub_778529` creature); "none" = always false in the original |
| `projectiles.tsv` | 222 | projectile number → GemRB `.pro`, SPLs that use it, EE class, original constructor, vtable, AIUpdate / Fire / Render |
| `orig_index.tsv` | 400+ | every original function whose role we know (opcode handler, spell class method, action handler, dispatcher…) |
| `ee_symbols.tsv` | 2,100+ | PST:EE symbols for the PST-only, effect and projectile classes, with sizes |
| `orig_strings.tsv` | 3,000 | identifier strings in the original exe (resrefs, global variables, 2DA names) → the functions that use them |

## Struct layouts (original Torment.exe, 32-bit)

Confirmed in at least two functions each. Byte offsets.

**Effect object** (`this` in an ApplyEffect; built by `sub_4A56EB(opcode, p1, p2, timing, …)`)

| Offset | Field |
|---|---|
| +8 | parameter1 |
| +12 | parameter2 |
| +16 | timing mode (word) |
| +18 | duration |
| +24 | resource (8 chars) |
| +68 (`this[17]`) | done flag, set to 1 when the effect is finished |
| `this[49]` | first-application flag |

Effect vtable: slot 2 = ApplyEffect. Saving throws: slot 5 (`+20`) is the check, called with five d20 rolls and a d100 for magic
resistance (seen in `sub_6C02F8`).

**Creature** (`a2` in ApplyEffect, `v301` in projectile code)

| Offset | Field |
|---|---|
| +84 | global object id |
| +962 | current action id (word) |
| +1132 / +1136 | current action int0 / int1 |
| +1172 | script name (death variable) |
| +1288 | base state bits (`STATE_*`, see `state.ids`) |
| +1292 | current HP (signed 16-bit) |
| +3204 | derived state bits |
| +3342 | non-zero: can't be killed outright (Abyssal Fury falls back to damage) |
| +9138 | current animation sequence (4 = damage) |
| +7146 / +7150 | animation object |

**Projectile / hardcoded spell object**: vtable slot 3 = AIUpdate (one tick), slot 18 = Render,
slot 35 = Fire (launch). +106 = caster id, +110 = target id (both as `*(_DWORD*)(this + 106)` in byte
units on a `char*`).

## Struct layouts (PST:EE Torment64, 64-bit): **never mix with the table above**

Creature: +1396 current HP, +1398 max HP, +4072 `CDerivedStats`, +17494 animation id, +14584 "visible/selectable" flag
that hardcoded spells clear while they carry a creature. Effect: the object mirrors the EFF V2 body from +8,
so +64 is the saving-throw type (4 = death). Vtable +64 is the save check, +24 is ApplyEffect, creature vtable
+240 adds an effect, +296 queues an action.

## Dispatchers

| What | Original | EE |
|---|---|---|
| effects | `sub_4A5C21` (opcode → object), handlers in `opcodes.tsv` | `CGameEffect::DecodeEffect` |
| projectiles and hardcoded spells | `sub_559A5D` | `CProjectile::DecodeProjectile` (EE renumbered Rune of Torment to 300 and Blacksphere to 301) |
| actions | `sub_76A7EA` via `byte_76D476[id]`, then `sub_44B099` | `CGameSprite::ExecuteAction`, `CGameAIBase::ExecuteAction` |
| triggers | `sub_453258`, `sub_778529` | `CGameAIBase::EvaluateStatusTrigger`, `CGameSprite::EvaluateStatusTrigger` |
