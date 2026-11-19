# Handoff: where the parity investigation stands (2026-11-18, round 6)

Read this first in a new conversation, then `AGENT_GUIDE.md` (rules, tools, the work packages) and `findings.md` (all findings, by round).

## Done
- **WP1 hardcoded spells: complete.** All 39 classes read in the original: `spell_expect.md` / `spell_expect.json`,
  findings S14–S42. Includes the 3 plain projectiles with factory-made effects (Blood Bridge, Acid Storm, Faerie Fire).
- **WP2 opcodes: partial** (`wp2_opcodes.md`): 0, **12 (in full)**, 17, 54, 74, 82, 100, 109, 138, 146–148, 186–196, 201
  (all overlay cases), 203–211, damage dice + luck, plane Spell Keys. Findings E7–E27. **S37 was wrong** (Ball Lightning
  works through its SPL *casting* effect op 196): check casting effects too, `opuses.py` doesn't read them.
- **WP4 actions: partial** (`wp4_actions.md`): the Ex actions, RestParty, IncrementGlobalOnce, Enemy. Findings A5–A9.
- **Text maps** of both binaries: `maps/*.tsv` (`tools/parity/export_maps.py`), no IDA needed to look things up.

## Round 6 (2026-11-18): scope check before handing over to Sonnet
- GemRB loads the original's BCS (2,228), DLG (814), IDS, INI and ARE files **byte-identical**; the only script
  GemRB adds is its own `BALDUR.bcs` (`gemrb/unhardcoded/pst/source/baldur.baf`, 64 blocks) standing in for logic
  the original hardcodes. Script risk = GemRB's *interpretation* (binding, parameters, parsing, engine rules).
- New: `script_ledger.tsv` (`tools/parity/script_ledger.py`): every action (147), trigger (75), event trigger (24)
  and BALDUR block (64) the game uses, with a verdict column. 11 rows decided so far.
- Areas no package covered before, now in `AGENT_GUIDE.md`: event triggers (`triggers.tsv` wrongly says "always
  false" for them), object selectors, the script runner, the dialogue engine, the dialogue text parser, BALDUR.bcs,
  INI spawns, combat rules (EE keeps them in generic functions, so `pst_functions.md` misses them), the effect
  pipeline, items/stores/XP, plain projectiles. Big original areas not decompiled yet: `CGameDialog`,
  `CGameSpawning`, `CAIObjectType`, `CVisibility`, `CKillStats`, `CStore`, `CItem`, `CSpell`, `CRuleTables`,
  `CGameJournal` (function lists in `.re/orig/dump/srcmap.txt`).
- Needs the person: a GemRB-side harness that parses all 9,648 dialogue strings and logs failures (engine code;
  AGENT_GUIDE A7).

## Next, in order (detail in AGENT_GUIDE section 4)
1. **Track A, scripts and dialogue, to 100 % of `script_ledger.tsv`:** A1 actions (by use), A2 triggers, A3 event
   triggers, A4 object selectors, A5 script engine, A6 dialogue engine, A7 parser, A8 BALDUR.bcs, A9 INI spawns,
   A10 indirect state (death variables, XP, rest), A11 voice lines and sound slots (never investigated).
2. **Track B, combat:** combat rules (`wp10_combat.md`), effect pipeline (`wp11_effect_pipeline.md`), WP2 rest (77
   used opcodes, batched by family). Open from round 5: Guardian Mantle save direction (E-012d), GemRB's Cloak of
   Warding / Guardian Mantle vs effect damage, effect byte +6.
3. **Track C:** WP6 rules, WP7 tables, items, stores, plain projectiles, WP8 GemRB PST branches, WP9 EE data.
4. Then fixes (phases 2, 4, 5, 6), phase 3 (spell ports) last. Top fix candidates so far: A1 EscapeAreaRunning, R2
   Nameless death rules, A5 RunAwayFrom attacks, S14 Howl, S15 Globe, S16/S17 Power Words, E7 Curse saves, S4 attack
   rolls, E17 scroll caster level, E18 TransferHP, E19 Ball Lightning / Adder's Kiss.

## For audit (Opus spot-checks these; newest first)
- (none yet)

## Tool changes (newest first; use these)
- 2026-11-19: `dumps.py` (find/show/lines/case/callers/calls/grep over the full dumps, outline for big
  functions, cached call index `.re/*/dump/calls_*.tsv`), `maps/dump_areas.md` (where each track's code lives),
  `case.py`/`facts.py`/`dossier.py`/`ida.py show` read the original from `dec_all`. Dumps spot-checked accurate.

## Fast tools (all in `tools/parity/`)
- `dumps.py find|show|lines|case|callers|calls|grep ee|orig ...` – the full decompiles, no IDA (start here).
- `opuses.py 147 148 [--full]` – every use of an opcode in the original SPL/ITM data (p1/p2/timing/res; header and
  equipped effects only, not SPL casting effects).
- `dossier.py SPWIxxx` – everything on one spell. `facts.py orig <addr>` – numbers/effects/calls in a function.
- `case.py action <id>` / `case.py trigger <id>` – the original's handler.
- `ida.py dec|xrefs|vt|find|str|show` – IDA in one command (one run at a time; `VT_SLOTS=N` for long vtables).
- Known original addresses: `maps/orig_index.tsv` and the `ORIG` dict in `facts.py` (extend both as you learn more).

## Facts worth remembering
- Effect durations in item effects are **seconds**; GemRB hooks sometimes use ticks by mistake (PW Blind).
- Hardcoded spell ctors call `sub_4128C8` (GetEnemyOf) on the caster's type: that's the "enemies only" filter.
- Plane checks `sub_7BD15D/7BD264/7BD327` (Carceri/Baator/Negative Material) are off when the caster carries the
  plane's Spell Key item (CARCERSK/BAATORSK/NEGMATSK).
- Original roll-to-hit: `sub_577BD4` (objects) / `sub_577E7C` (ids); THAC0 −127 = use the caster's own.
- Creature +21266–21272: overlay counters read by op 12 (Cloak of Warding pool, Shield, Barbed Shield, Pain Mirror
  reflections, Guardian Mantle, Armor pool): see E-012 in `wp2_opcodes.md`.
- Scrolls: op 146/148 cast at max(p1, first-header min level); PST data puts the spell level in p1.
- Creature: +3204 derived state, +3220 THAC0, +3222–3226 saves (higher = worse), +3883 luck, +3342 immortal flag.
