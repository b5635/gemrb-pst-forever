# PST parity investigation: instructions for the agent (Sonnet)

You continue a reverse-engineering audit of how GemRB (this repository) runs Planescape: Torment compared with
the real engine. **You investigate and write things down. You do not fix anything.** Fixes come later, from
your notes, and a stronger model (Opus) will spot-check your work. So write every claim in a form somebody
can re-check in under a minute (section 5).

**The goal, in order of importance:**
1. **The game can be finished, and every quest and every dialogue works as in the original.** That means every
   script action, trigger, object selector and dialogue rule PST uses behaves exactly as the original engine
   does: same parameters, same results, same side effects on variables, items, XP, party, journal and areas.
   This is **track A** below, and it must reach **100 % coverage**: no action or trigger the game uses may be
   left with status `todo`.
2. Combat rules that decide fights (turn-based combat is this fork's priority): track B.
3. Everything else (spells' numbers, presentation): track C.

Read this whole file before you start. Then read `HANDOFF.md` (where things stand), `findings.md` (what is
known: don't re-report it, extend it) and `README.md` (tools, file layout).

---

## 0. Rules (do not break these)

1. **Only write under `dev/parity/` and `tools/parity/`.** Don't change engine code, GemRB data
   (`gemrb/unhardcoded`, `gemrb/GUIScripts`), game files or the install in `D:\Games\GemRB`. If something
   must be fixed, it's a finding.
2. **Decompiled code stays in the git-ignored workspace.** The repo pushes to a public GitHub remote, and the
   decompiled code belongs to Black Isle and Beamdog. You may read it, quote it and keep verbatim excerpts as
   much as you like in **`.re/notes/`** (git-ignored; create it). In committed files (`dev/parity/*.md`,
   `*.tsv`), describe behaviour in your own words: conditions, numbers, order of operations, plus short
   identifiers (addresses, offsets, constants, resrefs, variable names) and line references into the
   workspace (`.re/orig/dump/dec_all/4B245B.c:432`). No pasted C blocks.
3. **The original exe is the truth.** Ranking, highest first:
   1. Original `Torment.exe` 1.1 + Fixpack 4.13 + UB 4.12, decompiled in `.re/orig/`.
   2. PST:EE `Torment64` (`.re/ee/`): real C++ names, read it first to understand a feature, but Beamdog
      changed things. A difference seen only in EE is status **S**, never **V**.
   3. IESDP (`tools/parity/iesdp.py`): hints, often wrong for PST (e.g. op 186 "0 = clear": the original clears
      on −1). Never proof.
   4. GemRB comments ("pst does X") are claims to check, not proof.
4. **No IDA unless the dumps lack it.** Every function of both games is already decompiled (`dumps.py`,
   section 2). `ida.py dec/xrefs/vt` is for vtables, data xrefs and the few functions in `errors.tsv`; then one
   at a time (the `.i64` is locked while IDA runs), never in parallel, never from parallel sub-agents.
5. **Commit after each finished batch** (every 10–20 ledger rows or one sub-package), only files under
   `dev/parity/` and `tools/parity/`, message `PST parity <track/WP>: <what>, findings <ids>`. Never commit
   `.re/`. Never push. Never `git add -A`.
6. **Never invent an address, line or number.** Every `sub_XXXXXX` you write must exist in `.re/orig/dump/dec_all/`
   or `.re/orig/dump/funcs.txt`; every GemRB `file:line` must be one you opened this session (line numbers
   drift: also give the function name). If you didn't read it, don't cite it.

---

## 1. Session start (every time)

```bash
cd /d/gemrb
ls .re/orig/Torment.exe.i64 .re/ee/Torment64.i64 .re/orig/dump/strings.txt   # workspace present?
git status --short dev/parity tools/parity                                    # leftovers from last session?
python tools/parity/script_ledger.py                                          # rows left in track A
```
If the workspace is missing, stop and tell the person (README "Rebuilding everything", ~15 min of IDA).
Then open `HANDOFF.md`, pick up the "Next" item, and keep `HANDOFF.md` current when you stop (section 8).

Shell: the Bash tool is Git Bash (POSIX). PowerShell 5.1 has no `&&`. IDA calls take 1–5 minutes: give them a
10-minute timeout, and batch several names/addresses into one `dec` call.

---

## 2. Toolbox

All from `D:\gemrb`. Python is `python`.

| Command | What | Cost |
|---|---|---|
| `python tools/parity/dumps.py find ee "CGameSprite::PlaySound"` / `find orig CGameDialog` | function names in the full dumps (orig: srcmap class or address) | instant |
| `python tools/parity/dumps.py show ee "CGameSprite::Hit(" [-g PAT -C 20]` | a function; big ones print an outline (cases, strings) instead of the body; `-g` greps inside | instant |
| `python tools/parity/dumps.py lines ee "<name>" 120 200` / `case ee "<name>" 125` | a line range / one switch case | instant |
| `python tools/parity/dumps.py callers orig sub_4B245B` / `calls ee "<name>"` | who calls it / what it calls (cached index; none = virtual, use `ida.py vt`) | instant |
| `python tools/parity/dumps.py grep ee "VerbalConstant" [--in CGameSprite]` | grep all functions, capped at 60 hits | ~20 s |
| `dev/parity/maps/dump_areas.md` | which EE functions / original classes hold each track's feature; read one section: `sed -n '/^## A11/,/^## /p'` | - |
| `python tools/parity/case.py action <id>` | the original's handler case for an action (creature switch `sub_76A7EA` via `byte_76D476`, else base `sub_44B099`) | instant |
| `python tools/parity/case.py trigger <hexid>` | the original's trigger case (`sub_453258`, `sub_778529`) | instant |
| `python tools/parity/ida.py show orig <addr>` | print an already decompiled original function | instant |
| `python tools/parity/ida.py find ee "CGameSprite::Swing"` | search EE function names (address, size, name) | instant |
| `python tools/parity/ida.py find orig "sub_4B5"` | search original function names | instant |
| `python tools/parity/ida.py str orig "Fortress_Death_Counter"` | strings in the original + functions using them: **the best way in** | instant |
| `python tools/parity/ida.py dec orig 4C61EB 4C66BE` | decompile original functions | IDA |
| `python tools/parity/ida.py dec ee "CGameDialog::"` | decompile EE functions whose name contains the text (`$` = exact end) | IDA |
| `python tools/parity/ida.py xrefs orig 4B245B` | callers of an address | IDA |
| `python tools/parity/ida.py vt orig 8DE26C` | vtable entries (`VT_SLOTS=N` for more) | IDA |
| `python tools/parity/facts.py orig <addr>` | numbers, effects and calls in a function | instant |
| `python tools/parity/dossier.py SPWIxxx` | everything on one spell | instant |
| `python tools/parity/opuses.py 147 148 [--full]` | every use of an opcode in SPL/ITM headers and equipped effects (**not** SPL casting effects, see trap 9) | ~30 s |
| `python tools/parity/iesdp.py action pst 22` / `trigger pst 0x4092` / `opcode pst 192` / `format spl_v1` | IESDP lookups | instant |
| `python tools/parity/script_ledger.py` | rebuild `dev/parity/script_ledger.tsv`, keeping verdicts | instant |
| `python tools/parity/export_maps.py` | refresh `dev/parity/maps/*.tsv` after new decompiles | ~10 s |

Data access (original, EE and "what GemRB loads"):
```python
import sys; sys.path.insert(0, r"D:\gemrb\tools\parity"); import pstres
o, e, g = pstres.orig(), pstres.ee(), pstres.gemrb()
o.res("DMORTE", "dlg"); g.where("BALDUR", "bcs"); o.names("bcs"); pstres.text(o.res("action", "ids")); o.string(1234)
```
`tools/tb_gamedata.py` `GameData().spell("SPWI101")` parses SPL headers and effects.

**Full decompiles exist: IDA is almost never needed (token rule).** `.re/ee/dump/dec_all_named/` holds all
21,090 EE functions (file names are mangled: look them up by real name through `dumps.py`, which reads
`rename_manifest.csv`), and `.re/orig/dump/dec_all/` holds 13,973 original functions as `<ADDR>.c`. Spot-checked
2026-11-19: identical to IDA's single-function output (40/40 original, 644/645 EE; the one EE difference was a
function the old run failed on). Failures are listed in each folder's `errors.tsv` (library stubs, nothing we use).
**Never print a whole big function** (`CGameAIBase::ExecuteAction` is 4,735 lines): `dumps.py show` prints an
outline for anything over 150 lines; then `-g`, `case` or `lines`.
Work EE-first: understand the feature in `dec_all_named`, then confirm only the deciding condition and numbers
in the original with one targeted grep (same constant, same resref, same case number). Batch: answer 10
ledger rows from one read of a dispatcher instead of re-opening it per row.

**Maps first.** The older partial folders `.re/*/dump/dec/` still feed `export_maps.py`, `derive.py` and the
spell tools; leave them. Maps: `dev/parity/maps/` (`actions.tsv`, `triggers.tsv`, `opcodes.tsv`, `projectiles.tsv`,
`orig_index.tsv` = every original function whose role we know, `orig_strings.tsv`). After any new decompile,
add what you learned to `maps/orig_index.tsv` via `export_maps.py` and the `ORIG` dict in `facts.py`.

**Finding a feature in the original** (in this order): 1) a string it uses (`ida.py str orig`: resref, variable
name, 2DA name, log text); 2) `.re/orig/dump/srcmap.txt`: original functions grouped by the source file named
in their asserts (`CGameDialog`, `CStore`, `CKillStats`, `CRuleTables`, `CAIObjectType`, `CVisibility`,
`CGameSpawning`, `CGameJournal`, `ObjCreature`, `CItem`, `CSpell`…); 3) the EE function's constants and call
pattern, then the same constants in the original; 4) callers (`xrefs`).

**GemRB source map**

| What | Where |
|---|---|
| Action / trigger implementations | `gemrb/core/GameScript/Actions.cpp`, `Triggers.cpp`, helpers in `GSUtils.cpp` |
| Name → function binding | `actionnames[]` / `triggernames[]` / `objectnames[]` in `GameScript.cpp`; PST's `action.ids`/`trigger.ids` names choose the function; GemRB's own `gemact.ids` / `gemtrig.ids` in `gemrb/unhardcoded/{pst,shared}` add or override ids |
| Object selectors and matching | `GameScript/Objects.cpp`, `Matching.cpp`, `Targets.cpp` |
| BCS / dialogue text parsing | `GameScript/ParseBCS.cpp`, `ParseText.cpp`, `GameScript.cpp` (`GenerateAction`, `GenerateTrigger`) |
| Script running (levels, responses, Continue, blocking) | `GameScript.cpp` (`Update`, `EvaluateBlock`, `ExecuteResponse`), `Scriptable/Scriptable.cpp` (action queue, `ProcessActions`) |
| Variables (GLOBAL, LOCALS, area, KAPUTZ) | `GSUtils.cpp` `SetVariable`/`CheckVariable` (KAPUTZ ~`:1797`) |
| Dialogue | `core/DialogHandler.cpp`, `core/Dialog.cpp`, `plugins/DLGImporter/` |
| Stores, items, inventory | `core/Store.cpp`, `Item.cpp`, `Inventory.cpp`, `GUIScripts/pst/GUISTORE.py` |
| Spawns (area INI files) | `core/IniSpawn.cpp` |
| GemRB's invented PST master script | `gemrb/unhardcoded/pst/source/baldur.baf` (compiled `BALDUR.bcs`, not in the original game) |
| Combat | `core/Scriptable/Actor.cpp` (`GetToHit` ~7196, `PerformAttack` ~7706, `Damage` ~4392, `Die` ~5725, `GetSavingThrow` ~3308, `LuckyRoll` ~11312), `CombatInfo.cpp`; turn-based layer `core/TurnBasedCombat/` |
| Effects | `plugins/FXOpcodes/FXOpcodes.cpp`, `plugins/PSTOpcodes/PSTOpcodes.cpp`, `core/EffectQueue.cpp` |
| PST switches | `grep -rn "GFFlags::PST\|HAS_KAPUTZ\|pstflags" gemrb/core gemrb/plugins` |

---

## 3. Reading decompiled code (read twice)

- **Original:** 32-bit MSVC, `__thiscall`. Check the declared type before reading an offset: on `int a1` or
  `char *a1`, `a1 + 84` is **byte** 84; on `_DWORD *a1`, `a1[21]` is byte 84 (index × 4); on `_WORD *`, × 2.
  Getting this wrong is the most common mistake.
- **EE:** 64-bit GCC, different struct layouts. **Never carry an offset between the two binaries.** Match by
  logic and constants.
- Watch casts: `(char)`, `(__int16)`, `(unsigned __int8)` change signedness and the result. `rand() % 241 + 160`
  is 160–400: write ranges.
- `sub_89BC79("Name")` / `sub_463F03(&dword_96EDC8, …)` build a CString and look up a GLOBAL variable; `+40` on
  the result is its value.
- Ticks: 15 per second. Effect durations in data are **seconds**. A round is 75 ticks (5 s) in this fork.
- A tiny ApplyEffect that only sets `this[17] = 1` does nothing *in slot 2*: check the other vtable slots before
  writing "no-op".
- Known struct offsets: `maps/README.md` (effect object, creature, projectile) and HANDOFF "Facts". Confirm any
  new offset in two functions before relying on it, then add it to `maps/README.md`.
- Creature action fields (original): current action id word `+962`, int0 `+1132`, int1 `+1136`, int2 `+1140`
  (int2 unconfirmed). Strings and objects of the current action: find them by reading; write down where.

---

## 4. The work: tracks and packages

Work **track A to completion first.** Within a package, go most-used first. Save the output file every 5–10
items. Each package lists its *done* condition.

### Track A: scripts and dialogue (top priority, must reach 100 %)

**What is already known (round 6 check, 2026-11-18):** GemRB loads the original's 2,228 BCS, 814 DLG, 54 IDS,
183 INI and 208 ARE files **byte-identical** (no override shadows them). So the risk is entirely in how GemRB
*interprets* them, plus one file GemRB invented: `BALDUR.bcs` (64 blocks, `baldur.baf`), which stands in for
logic the original keeps in its code. The dialogues hold 5,637 distinct trigger texts and 4,011 action texts,
compiled from text at run time by both engines; every name in them exists in PST's `action.ids`/`trigger.ids`.

**The ledger:** `dev/parity/script_ledger.tsv`, one row per action (147), trigger (75), event trigger (24) and
BALDUR block (64) the game uses, with use counts. Every row ends with a `status` (P / V / S / ? as in section 5),
the `finding` id or `-`, `by` = `sonnet`, and a `note` of ≤ 1 line. Track A is done when no row says `todo`
and every `?` says what blocked it. Rerun `script_ledger.py` after adding rows by hand: it keeps verdicts.

#### A1: actions (147, `wp4_actions.md`)
Done so far: the Ex actions, RestParty, IncrementGlobalOnce, Enemy (ledger rows marked `by opus`). Do the rest
by use count. For action id N:
1. `python tools/parity/iesdp.py action pst N` (signature), `python tools/parity/case.py action N` (original
   case). If the case calls a `sub_`, read it (decompile if missing). Follow it until you know every effect.
2. GemRB: which function the **name** in PST's `action.ids` binds to (`actionnames[]` in `GameScript.cpp`; mind
   aliases: `SetCorpseEnabled` → `AmbientActivate`, `SetAnimState` → `PlaySequence`, `GiveExperience` →
   `AddXPObject`, `AddexperienceParty` lower-case `e`, `JoinPartyEX` in DLG text). Then read that function and
   every helper it calls.
3. Answer **every** question below, in the entry, with numbers:
   - **Parameters:** which of int0/int1/int2, point, strings, objects each engine reads; defaults when absent.
   - **Target resolution:** what if the object is missing, dead, not in the area, in the party, or several match?
   - **Blocking:** instant or queued; when does it finish; can it be interrupted; what does it do on failure
     (abort the queue, skip, retry forever)? A queued action that never finishes **hangs a cutscene**: sev 1.
   - **State it changes:** variables (scope, created or not), items (stacking, charges, identified flag, where
     created when inventory is full), gold, XP (who gets it, split or not, level-up), party membership,
     journal, alignment/faction, area/door/container/trap state, dialogue file, script slots, death variables.
   - **PST-only behaviour** in either engine.
   - **Cutscene behaviour:** inside `StartCutSceneMode`/`CutSceneId`, does it behave differently?
4. Verdict; ledger row; next.

Priority hints (gameplay-breaking risk): anything that **gives or takes** items, gold or XP; party joins and
leaves; `ChangeAIScript`/`ForceAIScript`/`SetDialog`/`ChangeDialog` (which slot, does it reset?);
`CreateCreature*` (where it appears, what if blocked, the script name / death variable it gets);
`TeleportParty`, `EscapeArea*`, `EnablePortalTravel`, `ActivatePortalCursor`, `LeaveAreaLUA`, `QuitGame`
(game endings); `StartCutScene*`, `CutSceneId`, `EndCutSceneMode`; timers (`StartTimer`, `StartRandomTimer`,
`SetGlobalTimer`: **units**, seconds vs game time vs ticks); `Kill`, `Damage`, `DestroySelf`; `SetNamelessClass`,
`SetNamelessDisguise`, `PermanentStatChange`, `IncrementProficiency`, `IncrementExtraProficiency`,
`ChangeAlignment`, `SetFaction`; `GenerateModronMaze`, `FixEngineRoom`, `GeneratePartyMember`.

#### A2: triggers (75, `wp5_triggers.md`)
`case.py trigger <id>`, then GemRB `GameScript::<Name>` in `Triggers.cpp`. Compare: parameter use, comparison
direction and equality (`GT` strict?), which object is tested when the object is missing (false? true?),
dead creatures (do `See`, `Range`, `Exists`, `InParty`, `NearbyDialog` count the dead or the unconscious?),
range units (feet, search-map cells or pixels), `See` rules (invisibility, line of sight, fog, sleeping),
`NearbyDialog` (4,761 uses: what "nearby" means, which party members, conscious only?), `NumTimesTalkedTo*`
(who increments it, when: at dialogue start or end, for which speaker), `Global*` with missing variables,
`PartyHasItem`/`HasItem` (containers inside inventory, equipped slots, stacks), `CheckStat*` (PST stat numbers:
`stats.ids` → GemRB's stat), `Class`/`ClassLevel*` for the Nameless One's class changes, `Alignment` masks,
`Faction`/`Team` (PST-only object fields).

#### A3: event triggers (24, also `wp5_triggers.md`)
Ids below 0x4000 (`AttackedBy`, `Help`, `Die`, `OnCreation`, `WasInDialog`, `HarmlessEntered`, `Entered`,
`Trigger`, `Vacant`, `TimerExpired`, `Opened`, `Died`, `NamelessBitTheDust`…). **`maps/triggers.tsv` says
"none (always false)" for them: that is wrong for events.** They are raised by engine code into the creature's
trigger list and only *matched* in the dispatcher. For each: find where the original raises it (look for code
writing the trigger id constant, e.g. `0x25`, into a trigger object: start from `sub_453258`'s handling of
the trigger list, then `xrefs` on the function that adds a trigger), what object it carries, how long it
stays set (one script pass? until handled?), and compare with GemRB (`AddTrigger(TriggerEntry(trigger_...))`
in `gemrb/core`). Pay attention to `Die`/`Died` (death scripts and death variables), `OnCreation` (once per
creature, also after load?), `TimerExpired`, `WasInDialog`, `NamelessBitTheDust` (Nameless One's death).

#### A4: object selectors (`wp5_objects.md`, add ledger rows `kind=object`)
Scripts name targets with `object.ids` functions (`Myself`, `Protagonist`, `LastTalkedToBy`, `NearestEnemyOf`,
`LastAttackerOf`, `Gabber`, `Player1..6`, …) and IDS matching on object fields (PST has extra fields:
faction, team). 1) Extend a tool under `tools/parity/` that decodes every object in every BCS (`OB` blocks;
format: `iesdp.py format bcs`; PST's object layout differs from BG: check it) and every object in DLG text,
and counts the functions and fields used. 2) For each used function: original (`CAIObjectType`, srcmap) vs
GemRB `Objects.cpp`/`Matching.cpp`: what it returns when nothing matches, whether the dead/party/invisible
count, nearest by what distance. 3) IDS field matching rules (0 = any? EA ranges like `GOODCUTOFF`, `ENEMY`,
`EVILCUTOFF`; PST's `Specifics`, `Faction`, `Team`).

#### A5: the script engine (`wp_script_engine.md`)
Read the original's script runner and compare it with `GameScript.cpp`. Items: order of script slots (override,
area, specifics, class, race, general, default; PST's names in `scrlev.ids`) and whether a block that runs in
one slot stops the lower ones; how often each runs; `Continue()`; response selection by weight (`RESPONSE #n`:
random formula); which actions are **instant** (run during evaluation) vs queued (the original's instant list:
find it; GemRB marks them in `actionflags`); `ActionOverride`; interrupts (`SetInterrupt`); what clears the
queue; cutscene mode (whose scripts run, `CutSceneId` lock); `OR(n)` counting; the `!` negation of event
triggers; variable scopes (`GLOBAL`, `LOCALS`, area, **KAPUTZ**, missing-variable rules, A9); timers' units.

#### A6: the dialogue engine (`wp_dialog.md`)
Original `CGameDialog` (srcmap), EE `CGameDialog::`/`CMessage*Dialog*`; GemRB `DialogHandler.cpp`. Items:
which state starts a dialogue (state triggers evaluated in which order: PST: last true wins or first?); which
replies show (transition triggers, evaluated when); action timing (on reply click, before or after the next
state?); `NumTimesTalkedTo` increment; dialogue with a hostile/dead/sleeping/far creature; `StartDialog*`,
`Dialogue`, `NearbyDialog`/`InteractingWith`; journal entries (`CGameJournal`: types, how PST marks quests
done); text tokens (`<CHARNAME>`, PST tokens like `<GABBER>`); "end dialogue" vs "continue"; dialogues with
`ActionOverride` and `StartCutScene` inside; what happens to queued actions when the dialogue ends.

#### A7: the text parser (`wp_dialog.md`, section "Parsing")
Both engines compile the 9,648 dialogue strings at run time. Check that GemRB parses all of them as the
original does. Plan: 1) dump all distinct trigger and action strings (DLG V1.0: state triggers at header
`+0x18/+0x1C`, transition triggers `+0x20/+0x24`, actions `+0x28/+0x2C`, each an offset/length pair) to
`.re/notes/dlg_strings.txt`; 2) find odd forms (missing quotes, extra spaces, `[x.y]` points, comments, numbers
in hex, constants from IDS, empty arguments, `!` placement, trailing garbage) and count them; 3) read how the
original's compiler (`sub_41D7BC`) and GemRB (`ParseText.cpp`, `GenerateAction`) handle each odd form.
Each form GemRB rejects or reads differently is a sev-1 finding (the line silently does nothing).
**A run-time check needs a small GemRB-side harness (parse every string, log failures). That is engine code:
don't write it; write down what it should check, and tell the person it is needed.**

#### A8: GemRB's BALDUR.bcs (64 blocks, ledger `kind=baldur`)
Each block claims "the original engine does this in code": faction changes from `JOIN_*` globals, alignment
from globals, game-over (`QuitGame`), movies, teleports. For each block find the original logic (strings:
`JOIN_ANARCHISTS`, `Game_Over`, the movie names; EE `CPlanescape::CacheNamelessFactionFlags`,
`HandleGameOverConditions`) and compare conditions, order and timing. Also list original rules that BALDUR
*doesn't* cover (R2: `Game_Over` 3/4 are never set). Note that BALDUR uses non-PST actions (`ChangeFaction`,
`GlobalSet`, `UsedExit` from `gemact.ids`): check that they do what the block intends.

#### A9: area spawns and area scripts (`wp_spawns.md`)
PST areas spawn creatures from `ARxxxx.INI`. Original: `CGameSpawning` (srcmap) and the INI key strings
(`critters` `sub_7E7EFD`, `control_var` `sub_7E7F5E`, `spawn_point` `sub_7E8BE9`, `spawn_point_global`
`sub_7E8F54`); GemRB: `IniSpawn.cpp`. Compare every key the 183 INIs use (count them first), when spawning
runs (area load, every N seconds, once), conditions, death variables, facing, the Nameless One's respawn.
A creature that doesn't spawn, or spawns twice, breaks quests: sev 1. Also area-entry scripts and
`AreaFirstAIUpdate` (EE) vs GemRB.

#### A10: things scripts observe indirectly (`wp_script_engine.md`, last section)
Death variables (`Dead("name")`: which name, PST's `KILL_*`/`SPRITE_IS_DEAD*` style variables, set when),
XP on kill (`CKillStats`, split rules), item usage limits that quests test (`PartyHasItem` after an item is used
up), store transactions that scripts test (`StartStore`, `TakePartyGold`), rest (`RestParty`, `PSTCanRestParty`:
when resting is forbidden, what resting runs).

#### A11: voice lines and sound slots (`wp_voices.md`)
Nobody has compared these yet; the owner reports combat/selection lines feel wrong. 1) How GemRB reads the PST
CRE sound-slot table (`iesdp.py format cre_v1.2`, its layout differs from BG) vs the original's reader.
2) Slot → event mapping: `soundoff.ids`, `VerbalConstant`, GemRB's `VB_*` constants vs the original's slots.
3) When the original plays each line (attack, damaged, dying, select, select-rare, action, bored timer,
battle cry, leader, tired): conditions, chance, order/rotation, cooldown, which party member. Original: strings
of sound resrefs, `CGameSprite::PlaySound*`/`VerbalConstant` in EE, then the same constants in the original;
GemRB: `Actor.cpp` `VerbalConstant`/`ReactToDamage`/`PlaySelectionSound`. Each slot misread or never played is
sev 2 (sev 1 if a script's `VerbalConstant` plays nothing a cutscene waits for).

### Track B: combat rules (turn-based priority)

Not covered by any earlier package because EE keeps these in generic, not PST-only, functions. Output
`wp10_combat.md`. Entry points: EE `CGameSprite::Swing` (9D7DB0), `CGameSprite::Hit` (9A8270),
`CRuleTables::GetTHAC0` (7F21B0), `CGameEffect::CheckSave` (6CFCF0), srcmap `ObjCreature`, `CRuleTables`;
original roll helpers `sub_577BD4`/`sub_577E7C`, luck dice `sub_82015B`. GemRB: `Actor.cpp`. Questions: to-hit
formula (THAC0, STR/DEX/proficiency/weapon bonuses, luck, natural 1 and 20), criticals (range, damage),
attacks per round, damage (STR bonus, resistances: % or flat, rounding), death threshold (HP ≤ 0 vs −10,
unconscious, the Nameless One, the immortal flag `+3342`), morale and panic thresholds, saving-throw roll
(d20 + what vs which number, luck), magic resistance roll, spell disruption on damage, XP per kill.
Then the generic **effect pipeline** (`wp11_effect_pipeline.md`): timing modes and delay units, probability
bytes, when dice are rolled (E8), save bonus sign, MR checks, stacking and refresh, dispel, effects on death.
Then **WP2 rest**: the 77 remaining used opcodes in `wp2_opcodes.md` (list: `maps/opcodes.tsv` by use). Most are
stat modifiers: batch them by family (save modifiers 33–37, resistances 27–30/84–89/173, thief skills 59/90–92,
abilities 6/10/15/19/44/49) and check per family: modes 0/1/2 (add/set/percent), caps, PST branches; give each
opcode its own one-line verdict. Open items from round 5: Guardian Mantle save direction (E-012d), whether
GemRB's Cloak of Warding / Guardian Mantle absorb effect damage, effect byte `+6` (255 = half damage?).

### Track C: the rest (after A and B)

WP6 rules (`pst_functions.md`: Nameless death R2, level-up bonuses, `SpellPST` casting path, `PSTCanRestParty`,
`IsSpriteInDark`), WP7 tables (`CRuleTables` in the original vs `gemrb/unhardcoded/pst/*.2da`: XP, HP, THAC0,
saves, thief skills, ability modifiers), items (`CItem`: usability, charges, recharge, PST slots), stores
(`CStore`: prices, selling, identify, rent), plain projectiles (`maps/projectiles.tsv` rows without a
`CPsSpell` class: speed, radius, enemies-only flags vs GemRB's `.pro`), WP8 GemRB's PST branches
(`grep -rn "GFFlags::PST" gemrb/core gemrb/plugins`), WP9 EE data sample (lowest).

---

## 5. Evidence standard (what Opus will check)

Every entry uses this template:

```
### <ID> <one-line title>
- **Status:** V | S | P | ?      **Severity:** 1 | 2 | 3      **Uses:** <count>      **By:** sonnet
- **Original:** sub_XXXXXX (.re/orig/dump/dec_all/XXXXXX.c:<lines>): what it does, in words, with numbers
- **EE:** Class::Method (only if it adds something)
- **GemRB:** path/file.cpp:<line> `Function` (what it does)
- **Difference:** exactly what differs, with a concrete example ("SetGlobalTimer 10 → original 10 game seconds
  = 150 ticks; GemRB 10 × AI_UPDATE_TIME …")
- **Data affected:** which scripts/dialogs (names + counts; `grep` the decompiled BCS in `.re/` or count with pstres)
- **Re-check:** the exact commands that show the evidence (`python tools/parity/case.py action 117`,
  `sed -n 2640,2660p gemrb/core/GameScript/GSUtils.cpp`)
- **Breaks:** for sev 1, the quest/dialogue/area that goes wrong, if you can name it
```

- **V** = you read the behaviour in the original *and* in GemRB's source, and they differ.
- **S** = suspected: EE only, or code you couldn't fully follow. Say what is missing.
- **P** = parity: they match (or differ only in presentation). P entries can be one line, but still need the
  original address and GemRB function.
- **?** = couldn't determine; say what blocked you.
- **Severity:** 1 = a quest, dialogue, cutscene or fight can go wrong or hang; 2 = wrong numbers or detail;
  3 = looks or sounds only.
- IDs: `A-<id>` actions, `T-<hexid>` triggers and events, `O-<name>` object selectors, `SE-<n>` script engine,
  `D-<n>` dialogue, `SP-<n>` spawns, `B-<n>` BALDUR, `C-<n>` combat, `E-<op>` opcodes. Before adding one, search
  `findings.md` and the `wp*.md` files; extend an existing entry instead of duplicating it.
- **Be honest.** "I couldn't find it" is a good result. A wrong **V** costs far more than an honest **?**.
  Before writing **V**, reopen both the original function and the GemRB line and confirm both say what you wrote.

---

## 6. Traps (each of these has already caught somebody)

1. The same opcode/action/trigger number means different things in PST, BG2 and EE: use PST's ids files and
   the original handler.
2. GemRB binds by **name**: a PST name that GemRB aliases to a generic function may lose a PST detail.
3. `scripting.md` "MISSING" on Ex names is often a false positive (GemRB binds one of the two names).
4. `maps/triggers.tsv` "none (always false)" is right for status triggers with no case (A3: 0x4070, 0x4092,
   0x40C0, 0x40FF) and **wrong for event triggers** (ids < 0x4000), see A3 above.
5. Some `action.ids` lines were added by Fixpack, but the engine always had the action (313).
6. Fixpack/UB changed data: "original data" always includes them (`WeiDU.log` lists the components).
7. Turn-based combat changes timing on purpose. Compare logic, counts and units, not wall-clock time; but a
   unit mismatch (seconds vs ticks vs rounds) is a real finding (S17 was 15× off).
8. `spells.md` "code ops" and `opcodes.md` "GemRB note" are to-do hints, not verdicts.
9. `opuses.py` and the use counts in `opcodes.tsv` skip SPL **casting** (global) effects. Those use ops 174, 187,
   188, 195, 196, 205, 207 (S37 went wrong because of this). PST CREs carry no effects of their own.
10. Two GemRB functions can do a job the original does in one place (and the reverse): follow helpers to the end.
11. A GemRB comment saying "pst does X" is a claim: check it.
12. Variables: a trigger that reads a missing variable and an action that creates it can disagree (A9).

---

## 7. Working method

1. **One item at a time.** Finish the entry (even as "?") and its ledger row before the next.
2. **Progress line** at the top of each output file: `Done: 42/147. Next: action 140 GiveItemCreate.`
3. **Numbers, not adjectives.**
4. **Stuck for ~15 tool calls on one item?** Write what you know, status "?", what blocked you, move on.
5. **Context:** your context fills up. Write findings to the file as you go; never keep results only in
   your head. Before a long read, save.
6. **When a package is done:** a line in `PARITY_PLAN.md` "Progress" (date, package, counts, top three
   findings); copy every sev-1 and sev-2 V into `findings.md` (next free id in the right section, one table
   row with a link to the detail); refresh `HANDOFF.md`; commit.
7. **Self-heal: notice repetition and fix the cause.** If you run the same kind of command 3+ times (the same
   grep with a different id, opening the same dispatcher again, hand-copying a column), stop and ask what
   would make it one step: a flag on an existing tool, a new column in a map, a cache, a ledger column filled
   by script. Small tool changes (< ~50 lines in `tools/parity/`) you make yourself, then note them in
   `HANDOFF.md` "Tool changes" so the next session uses them. Likewise when a tool gives a wrong or misleading
   answer (e.g. `triggers.tsv` "always false" for events): fix the tool, not just your notes. Re-reading
   the same file region twice in one session is the warning sign: write down what you needed from it.
8. **Ask the person** (stop and say so) when: the workspace is missing, a tool is broken in a way you'd need to
   rewrite more than ~50 lines to fix, a check needs engine code (A7's harness), or you find a sev-1 issue you
   think should be fixed before the investigation continues.

---

## 8. Handoff and audit

At the end of every session update `HANDOFF.md`: what you finished (ledger counts), the next item, open
questions, and a list **"For audit"** of your V findings since the last audit, sev 1 first. Opus will pick from
that list and re-run the **Re-check** commands; a finding that doesn't reproduce gets status `?` and an
`audited: failed` ledger note, so make the Re-check lines exact.

---

## 9. Worked example (copy this level of detail)

Question: does `RestParty` (296) behave like the original?
1. `iesdp.py action pst 296`: `RestParty(I:SuggestedDream, I:HP, I:Renting)`.
2. `case.py action 296`: base case 296 calls `sub_5C68CC` → `sub_5C6A9E`. Reading it: each party member gets
   op 17 with p1 = HP, mode 0 (add), **except the Nameless One, who gets mode 4 (full heal)**; a dream is chosen,
   the `TIME` movie plays.
3. GemRB: `action.ids` name `RestParty` → `GameScript::RestParty` (`Actions.cpp:5521`) → `Game::RestParty(…, hp)`
   → `Heal(hp)` for everyone.
4. Entry A-296: V, sev 2, 20 uses; Re-check `python tools/parity/case.py action 296`, `grep -n "RestParty"
   gemrb/core/Game.cpp`; Difference: with an HP limit the Nameless One should wake fully healed, GemRB heals
   him by the limit. Ledger row 296: `V A7 sonnet`.
