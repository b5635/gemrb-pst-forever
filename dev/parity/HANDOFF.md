# Handoff: where the parity investigation stands (2026-11-19, round 12)

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
- Round 8, second part: 19 more rows (ledger 60/310; actions 60/147): TakePartyItem, DestroyPartyItem, GivePartyGold,
  Kill, ChangeEnemyAlly/Specifics/SetTeam, TeleportParty (S), EscapeArea (S), MoraleDec/Inc/Set, StartStore,
  SetCorpseEnabled, portal travel/cursor, StartCutScene, cutscene mode on/off.
- **New sev 1: A12** TakePartyItem takes the whole stack in GemRB (original: one unit). Breaks the cranium-rat `Tail`
  trades (4 buyers, one stack). Top fix candidate (sev-1 findings don't stop the investigation).
- **New sev 2: A13** GemRB swaps Dak'kon's Karach on every MoraleDec/Inc/Set (falls to the bad blade); the original
  only at level-up.
- Left `todo` on purpose for A5: Continue (36), CutSceneId (127). FloatMessage (210) needs the creature vtable slot +104.

## Round 9 (2026-11-19): A1 actions finished
- **All 147 action rows decided** (P 93, V 33, S 20, ? 1); detail in `wp4_actions.md` "Round 9". Ledger: 147/310 rows.
- New findings: **A14 (sev 1) Damage** misreads every amount ≥ 16 as a dice code (`Damage(Protagonist,Lower,25)` = 9) and
  can kill (original floors HP at 1); **A18 (sev 1) DestroyItem** removes from the dialogue NPC instead of the named
  object: all 20 uses (FalseCon, loandoc, Mantuok's cheese, Sohmien, Legclub) remove nothing; A15 ForceAttack doesn't
  clear the attacker's queue; A16 PlaySequenceTimed waits ticks not seconds; A17 LeaveParty keeps the companion's
  scripts (original empties 5 slots); A19 SavePlace bound to SaveLocation (does nothing); A20 GlobalSetGlobal copies
  the wrong way (+ FollowCreature blocks forever, PST: no-op).
- Sev 3 V: FloatMessage family (sound/log/off-screen, KillFloatMessage owner), ChangeColor 0x4000 forms ignored,
  TransformPartyItem per member, ExploreMapChunk units + un-explore mode, ChangeDialog timing, CreateCreatureAtFeet
  placement, ForceFacing.
- S worth a look: **SetNamelessDisguise** writes GLOBAL `APPEARANCE`, which isn't in `VAR.VAR` while PST runs with
  `NoNewVariables` (run-time check: does the zombie disguise / dustman-robe look ever apply?); GeneratePartyMember
  (original loads CRE snapshots from `layout.ini`, GemRB moves and kills the live NPC); QuitGame (`Game_Over` = 6 path,
  A8); ForceSpell = ReallyForceSpell path in the original; Continue with an empty response (A5).

## Round 10 (2026-11-19): fixes A12 A18, A2 triggers complete
- **Fixed** (commit after `97267f33d`): A12 TakePartyItem takes one unit of a stack; A18 DestroyItem uses its object and
  All. Both tested in game (4 Tails → 3; Morte's DestroyItem removes the Nameless One's item).
- **A2 triggers: 75/75** (`wp5_triggers.md`, findings T1-T10). Fixed and tested in game (PST only): T1 NearbyDialog
  (700 px, no LOS), T2 MoraleLT/GT (current morale), T3 NotStateCheck, T4 RandomNum 0…Range, T5 zero timers expired
  (`ZeroTimerIsValid = 1`), T6 TimeGT/LT, T7 NearSavedLocation pixels. Open sev 3: T8 NearLocation, T9 NumCreature
  (visible only), T10 LOS.
- Tools: `trigargs.py 0x40xx [--dlg] [--where]` (trigger parameter use in BCS and DLG);
  `GemRB.EvaluateString(trigger, quiet, who)` takes a caller (party slot or global ID) for in-game trigger tests.

## Round 11 (2026-11-19): A3 event triggers, A8 BALDUR done; A4 started
- **Ledger complete: 310/310 rows have a verdict** (actions, triggers, events, BALDUR). Track A continues with the
  packages that have no ledger rows yet (A4-A7, A9-A11).
- **A3 (24/24, `wp5_triggers.md` "A3")**: how the original raises, matches and clears events (`sub_43411A`/`sub_434010`
  raise, `sub_40629D` evaluate, `sub_434215` match, `sub_45F538` clears the pending list after every pass).
  **T16 (sev 1) NullDialog** is a status check in GemRB (true almost always): AR0403's duelling Painted Thugs and the
  barking thug attack the party at once. T11 (sev 2) TimerExpired eaten by the first block that tests it (8 scripts);
  T12 (sev 2) unused events stay pending in GemRB; T14 (sev 2) a failed pickpocket counts as AttackedBy in the original;
  T15 (S) damage effects raise HitBy/AttackedBy; T13 (sev 3) negated events.
- **A8 (64/64, `wp_baldur.md`)**: **B2 (sev 1)** `Game_Over` 7 does nothing in GemRB (`0500GGRD`); B7 Fortress party
  count at the wrong moment with an extra `SkScrap`/`SkRegret` condition, companions don't leave; B4/B5 Lady's maze
  exit location and second-time death text; B1 faction joins (single stat, flips with two joins); B8 (S) original
  leave-area rules not covered at all (AR1800→FR1700, AR3017→FR0502 party dismissal, `Pregnant_Quest` world map, AR1203 slab).
- **A4 started (`wp5_objects.md`)**: usage counted (only 11 object functions are used), name lookup and
  `NearestEnemyOf` compared EE vs GemRB; original not confirmed yet.
- Notes for A5 found on the way: the original runs 7 slots (`sub_45F538`, `this+834…858`); a slot whose response is
  non-empty stops the lower slots, `Continue()` only chains blocks inside one script (`sub_414E96` checks action 36);
  in the restricted state (`sub_45F538:48`) only the override slot runs.

## Round 12 (2026-11-19): EE is now the source of truth; A4 decoder read
- **Owner's decision: PST:EE is the truth** (AGENT_GUIDE rule 3, PARITY_PLAN section 1, README). Read EE first and
  judge GemRB against it, Beamdog's changes included; open the original only when EE is unclear or lacks the
  feature, and note in one line when it differs. Rounds 1-11 findings stay valid unless EE differs: re-check one
  against EE when you fix or audit it ("EE: same/differs").
- **A4 (`wp5_objects.md` "Round 12")**: decoder, resolver and IDS matcher read in EE (`CAIObjectType::Decode`,
  `sub_ADDA10`, `CGameArea::GetNearest`) and the original (`sub_40F77C`, `sub_411B7C`, `sub_474047`, `sub_40F297`).
  **O-range (V, sev 2):** visual range = (Nameless One's fighter level + 14) × 32 px for everyone
  (`CPlanescape::SetNamelessExploreRange`), GemRB frozen at level 3. NearestEnemyOf and name lookup: P.
  O-self (S): GroupOf/Nearest/LastHitter resolve to the caller.
- Left in A4: Player1-6/Protagonist slot order in GemRB, LastAttackerOf/LastHelp/LastTrigger storage, MostDamagedOf,
  faction/team fields in GemRB, ledger rows `kind=object` (`script_ledger.py` source).

## Next, in order (detail in AGENT_GUIDE section 4)
1. **Track A:** ~~A1 actions~~ (round 9), ~~A2 triggers~~ (round 10), ~~A3 event triggers~~, ~~A8 BALDUR.bcs~~ (round 11),
   A4 object selectors (decoder done round 12; remaining functions, faction/team, ledger rows), A5 script engine, A6 dialogue engine, A7 parser, A9 INI spawns,
   A10 indirect state (death variables, XP, rest), A11 voice lines and sound slots (never investigated).
2. **Track B, combat:** combat rules (`wp10_combat.md`), effect pipeline (`wp11_effect_pipeline.md`), WP2 rest (77
   used opcodes, batched by family). Open from round 5: Guardian Mantle save direction (E-012d), GemRB's Cloak of
   Warding / Guardian Mantle vs effect damage, effect byte +6.
3. **Track C:** WP6 rules, WP7 tables, items, stores, plain projectiles, WP8 GemRB PST branches, WP9 EE data.
4. Then fixes (phases 2, 4, 5, 6), phase 3 (spell ports) last. Top fix candidates so far: **T16 NullDialog (sev 1)**, **B2 Game_Over 7 (sev 1)**, **A14 Damage amount/death (sev 1)**, T11 TimerExpired, T14 pickpocket→AttackedBy, T12 event lifetime, B7 Fortress count, (A12, A18 fixed round 10), A19 SavePlace, A20 GlobalSetGlobal, A17 LeaveParty scripts, A16 PlaySequenceTimed, A15 ForceAttack, A13 Karach, A10 PlaySequence blocking, A11 StartRandomTimer, A1 EscapeAreaRunning, R2
   Nameless death rules, A5 RunAwayFrom attacks, S14 Howl, S15 Globe, S16/S17 Power Words, E7 Curse saves, S4 attack
   rolls, E17 scroll caster level, E18 TransferHP, E19 Ball Lightning / Adder's Kiss.

## For audit (Opus spot-checks these; newest first)
- Round 12: O-range.
- Round 11: T16, B2 (sev 1) first, then T11, T14, T12, B7.
- (none yet; rounds 7-9 were written by Opus). If a Sonnet session re-checks: A18, A14 first (Re-check lines in `wp4_actions.md`).

## Tool changes (newest first; use these)
- 2026-11-19 (round 11): `bcs.py <script> [--gemrb]` decompiles a BCS to text; `bcs.py --grep REGEX` prints every
  matching block of every script on one line (the fastest way to find users of a trigger/action/variable);
  `bcs.py --objects` counts object functions and IDS fields. `dumps.py grep ... --max N` raises the 60-hit cap.
- 2026-11-19 (round 9): `exevt.py slots <VA> [N]` / `refs <addr>` / `str <VA> [N]`: read vtables, data pointers and
  strings straight from `Torment.exe` (no IDA). Creature vtable `8F07BC`, base AI object `8DC1B0`, message vtables:
  slot 6 = Run. `script_ledger.py setmany rows.tsv` sets many rows from a tab-separated file (no shell quoting).
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
