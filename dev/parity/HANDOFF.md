# Handoff: where the parity investigation stands (2026-11-18, round 4)

Read this first in a new conversation, then `AGENT_GUIDE.md` (rules, tools) and `findings.md` (all findings, by round).

## Done
- **WP1 hardcoded spells: complete.** All 39 classes read in the original: `spell_expect.md` / `spell_expect.json`,
  findings S14–S42. Includes the 3 plain projectiles with factory-made effects (Blood Bridge, Acid Storm, Faerie Fire).
- **WP2 opcodes: partial** (`wp2_opcodes.md`): 0, **12 (in full)**, 17, 54, 74, 82, 100, 109, 138, 146–148, 186–196, 201
  (all overlay cases), 203–211, damage dice + luck, plane Spell Keys. Findings E7–E27. **S37 was wrong** (Ball Lightning
  works through its SPL *casting* effect op 196): check casting effects too, `opuses.py` doesn't read them.
- **WP4 actions: partial** (`wp4_actions.md`): the Ex actions, RestParty, IncrementGlobalOnce, Enemy. Findings A5–A9.
- **Text maps** of both binaries: `maps/*.tsv` (`tools/parity/export_maps.py`), no IDA needed to look things up.

## Next, in order
1. **WP2 rest:** 13 Death level bands (Cloudkill, `sub_4B5DCF`), then 39, 45, 128, 73, 6, 42, 44, 98, 120, 129 by
   `maps/opcodes.tsv` use count. Open in op 12: the Guardian Mantle save direction (E-012d) and whether GemRB's
   Cloak of Warding / Guardian Mantle touch effect damage; the meaning of effect byte +6 (255 = half damage).
2. **WP4 rest:** top actions by use (`maps/actions.tsv`): PermanentStatChange (230), AddPartyExperience/GiveExperience
   (XP split), FloatRebus, SetInternal/IncInternal, PlaySequence/SetAnimState, SetCorpseEnabled, Morale* (GemRB's
   Karach hook), StartSong, ReturnToSavedPlace, EnablePortalTravel. Then GemRB's other PST branches in `Actions.cpp`.
3. **WP5 triggers** (`maps/triggers.tsv`, `case.py trigger <id>`).
4. **WP6 rules:** `pst_functions.md` list (Nameless death/revival R2, level-up bonuses, SpellPST casting path,
   resting PSTCanRestParty, IsSpriteInDark, game-over).
5. **WP7 tables**, **WP8** GemRB PST branches (`grep pstflags|GFFlags::PST` = 266 hits; Actor.cpp 66, CharAnimations 54),
   **WP9** EE data sample.
6. Then fixes (phases 2, 4, 5, 6), phase 3 (spell ports) last. Top fix candidates: S14 Howl, S15 Globe, S16/S17 Power
   Words, E7 Curse saves, A5 RunAwayFrom attacks, S4 attack rolls, E17 scroll caster level, E18 TransferHP, E19 Ball
   Lightning / Adder's Kiss.

## Fast tools (all in `tools/parity/`)
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
