# Handoff: where the parity investigation stands (2026-11-19, round 8)

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

## Round 7 (2026-11-19): tooling on the full dumps, first phase run with it (A11 voices)
- Dumps spot-checked accurate; `dumps.py` + `maps/dump_areas.md` replace IDA for reading code (see Tool changes).
- **A11 voices** (`wp_voices.md`): the original's voice player is `sub_73DEEF` (EE `CGameSprite::PlaySound(uchar,...)`).
  Findings V1-V5: swings speak damage/spell-casting lines and casts speak nothing (V1, the "combat lines feel off"
  report), hide/disrupt/trap speak location comments (V2), selection order/rare/frequency (V3-V5). Open: locations,
  banter cases, battle cries on GemRB's side.
- Cost of the phase: ~25 tool calls, no IDA run. The original was found in 3 steps from a known door (op 13 sends
  the same event numbers → message vtable → Run → `sub_73DEEF`), not by searching.

## Round 8 (2026-11-19): A1 actions by use count
- 37 action rows decided this round (ledger: 41 of 310 rows have a verdict; actions 41/147). Detail in
  `wp4_actions.md` "Round 8". Rows done: MoveToPoint, Wait, WaitRandom, SmallWait, Face, Attack, SetGlobal,
  IncrementGlobal, BitSet, Help, CreateCreature, ChangeAIScript, AddexperienceParty, PlaySequence, SetAnimState,
  FaceObject, ReturnToSavedPlace, GiveItemCreate, TakePartyGold, StartTimer, StartRandomTimer, Set/IncInternal, Fades,
  GiveExperience, DestroySelf (S), RunToPoint, PlaySoundNotRanged, PermanentStatChange (max HP moves current HP in the original; LEVEL case unread).
- New findings: **A10** (sev 2) PlaySequence/SetAnimState block until the animation ends in PST, GemRB doesn't;
  **A11** (sev 2) StartRandomTimer rolls max…2·max−min−1 in GemRB; sev 3: WaitRandom never rolls its max,
  AddexperienceParty drops the remainder, ReturnToSavedPlace doesn't restore facing.
- **Correction:** A9 was wrong (PST `NoNewVariables = 1`: GemRB doesn't create variables either) → P.
- Notes for later packages: the original holds `Dialogue` while a fade runs (A6, `wp4_actions.md` A-204); DLG variable
  names with stray spaces (`"PILLAR "`, `" KNOW_SIGIL"`…, A7, listed under A-30); GLOBAL↔KAPUTZ fallback for
  `_DEAD`/`KILL_` names missing in GemRB (only `EiVene_Dead`, harmless); SetGlobal's `JOIN_*` hook (A8);
  GemRB's DestroySelf ends cutscene mode for PST (A5).
- Left `todo` on purpose for A5: Continue (36), CutSceneId (127). FloatMessage (210) needs the creature vtable slot +104.

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
- (none yet; rounds 7-8 were written by Opus)

## Tool changes (newest first; use these)
- 2026-11-19 (round 8): `actargs.py <id> [--dlg] [--where] [--top N]`: how every BCS (and DLG text) calls an action,
  parameters counted; `script_ledger.py set <kind> <id> <status> <finding> "<note>" [by]` sets one row;
  `dumps.py find` accepts names with `(` (literal match when the regex is invalid).
- 2026-11-19 (later): `dumps.py grep` reads a packed copy (`.re/*/dump/all_*.c`, built once, ~0.2-2 s per grep
  instead of 15-60 s; regex is case-sensitive, `-i` for not); `show`/`lines`/`case` hide Hex-Rays local declarations
  and join multi-line calls (`--decl`, `--raw` to undo); outlines also list labels and named calls.
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
