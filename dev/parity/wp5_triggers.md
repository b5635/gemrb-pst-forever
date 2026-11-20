# WP5 / A2: triggers (round 10, 2026-11-19)

All 75 non-event triggers PST's scripts and dialogues use (`script_ledger.tsv`, kind `trigger`), compared with the
original's two trigger dispatchers: the base one `sub_453258` (all objects) and the creature one `sub_778529`
(`NumTimesTalkedTo*`, `HaveSpell`, `HaveAnySpells`, `NearSavedLocation`, `InteractingWith`, a second `See`).
GemRB: `gemrb/core/GameScript/Triggers.cpp`.

How to read the original's cases: `v105`/`this` = the caller, `v598` = int0, `v602` = int1, `v599` = the object,
`v596` = the resolved object (`vfunc +172`; a missing object returns **false** in every trigger that has one),
`v589`/`v65` = the result. Re-check any case with `python tools/parity/case.py trigger 0x40xx`.
Parameter use in the data: `python tools/parity/trigargs.py 0x40xx --dlg --where` (new this round).

Fixes made this round are marked **Fixed** (PST only, behind `PST_STATE_FLAGS`, plus `ZeroTimerIsValid = 1` in
`unhardcoded/pst/gemrb.ini`).

## Differences (findings T1-T10, `findings.md` section 14)

### T1 0x4093 NearbyDialog(S:Dialog), 4,761 uses (sev 2, **Fixed**)
- **Original:** `sub_4748E0(caller, dialog, 700)` then `sub_4756FA` (same, second object list): the nearest object
  whose dialog (either of the creature's two dialog fields) is the resref, within **700 px** of the caller with y
  counted ×4/3 (`(dx)² + (4dy/3)² ≤ 700²`), creatures only when active (`+7076/7080/7084`). **No line of sight, no
  visual range.**
- **GemRB:** the *first* actor in the area with that dialog, then `CanSee`: the caller's visual range and line of sight.
- **Breaks:** companion interjections (`NearbyDialog("DMorte")` etc.) vanish when the companion is behind a wall or
  beyond visual range but within 700 px; with two creatures sharing a dialog GemRB may test the far one.

### T2 0x4015 MoraleGT / 0x4016 MoraleLT(O, I), 52 uses (sev 2, **Fixed**)
- **Original:** creature byte +1831, the **current morale** (what op 23 and MoraleInc/Dec change, see A-104).
- **GemRB:** `IE_MORALEBREAK` (the flee threshold, a fixed CRE value). All 51 dialogue uses are companion morale
  gates (`MoraleLT("Dakkon",6)`, `MoraleGT("Annah",9)`, Morte, Grace): they ignored every morale change.

### T3 0x4038 NotStateCheck(O, I:State), 8 uses (sev 2, **Fixed**)
- **Original:** `(state & int0) == 0`: true when none of the bits is set.
- **GemRB:** `state & ~int0`: true when some *other* bit is set, so false for an ordinary creature. Users: Trias
  (`0901TRIA`, 6), Ravel (`0610RAVL`, 2).

### T4 0x4047 RandomNum / 0x4049 RandomNumLT(I:Range, I:Value), 200 uses (sev 2, **Fixed**)
- **Original:** `roll = pass_random % max(Range + 1, 1)` (0…Range, one roll per script pass, `+1216`), then
  `roll == Value` / `roll < Value`.
- **GemRB:** `Value − 1 == roll % Range` (1…Range); Value ≤ 0 is always false.
- **Breaks:** the dialogue uses count from 0 (`RandomNum(2,0)`, `(2,1)`, `(2,2)`: 24 lines): the `0` branch never
  fires in GemRB; every other RandomNum has 1/Range instead of 1/(Range+1).

### T5 0x4040 GlobalTimerExpired(S, S), 50 uses (sev 2, **Fixed**: `ZeroTimerIsValid = 1`)
- **Original:** variable exists and `value < game time`: a timer at **0 is expired**.
- **GemRB (PST had `ZeroTimerIsValid = 0`):** 0 = not expired. VAR.VAR starts `No_Gamble`, `Bedai_Timer`,
  `Alarm2_Timer`, `Kiina_Return`, `Able_Timer_*` at 0: e.g. gambling (`GlobalTimerExpired("No_Gamble")`) and Able's
  Ravel/language/incarnation lines were closed until something set the timer.

### T6 0x4068 TimeGT / 0x4069 TimeLT(I:Hour), 12 uses (sev 3, **Fixed**)
- **Original:** `hour = (time % 108000) / 4500`, `hour > int0` / `hour < int0`.
- **GemRB:** schedule bit masks on the time half an hour earlier, with bit 23 excluded from TimeGT: `TimeGT(21)` is
  true 21:30-23:30 instead of 22:00-24:00. Users: day/night switches in `AR0500`, `AR0600`, `AR1500`.

### T7 0x4076 NearSavedLocation(I:Range), 334 uses (sev 3, **Fixed**)
- **Original:** saved x and y > 0, then **plain pixel** distance ≤ int0 (no isometric scaling).
- **GemRB:** int0 in search-map cells (×16/×12 px). 319 uses are `!NearSavedLocation(0)` (same); the 15 others
  (3, 5, 6, 8, 10, 50, 66) were 12-16× wider. GemRB still falls back to the home location when nothing is saved.

### T8 0x4075 NearLocation(O, P, I), 326 uses (sev 3, open)
- **Original:** search-cell distance between the object's cell and the point's cell ≤ (int0 + 1)².
- **GemRB:** `WithinPersonalRange` (ellipse in cells, minus the object's personal radius), int0 not +1.
  Slightly wider in GemRB; boundary cases only.

### T9 0x4029/0x402A/0x4028 NumCreature(LT/GT), 19 uses (S, sev 3)
- **Original:** `sub_47699E(caller pos, object, visual range, …)`: counts matches **the caller can see**.
- **GemRB:** `GetObjectCount`: every match in the area. Users are area scripts (`AR1601`, `AR1401`) and `0400RC*`;
  what visual range an area script has in the original was not checked.

### T10 0x4013 LOS(O, I:Range), 34 uses (sev 3, open)
- **Original:** search-cell distance ≤ (Range+1)² and a line-of-sight test (`sub_472F1C`), nothing else.
- **GemRB:** `SeeCore` (visual range, not hidden/invisible, not dead) then `Range`. Differs for hidden/invisible
  targets.

## Same (P), short notes

| Trigger | Uses | Note |
|---|---|---|
| 0x400F Global, 0x4034 GlobalGT, 0x4035 GlobalLT | 17,093 / 2,415 / 795 | variable must exist (false otherwise), signed compare; GemRB `valid` flag, same |
| 0x407F BitCheck | 171 | existing variable, `(value & int0) != 0` |
| 0x4086 GlobalORGlobal | 46 | original needs **both** variables to exist; GemRB returns true on the first alone (edge only) |
| 0x409C StuffGlobalRandom | 4 | existing variable = random 0…int0, trigger true |
| 0x4023 True, 0x4030 False | 2,044 / 99 | |
| 0x401C See | 1,532 | nearest visible match within the caller's visual range (search cells) with line of sight, sets LastSeen; the creature dispatcher also tests the fog map (`sub_598AEC`). Invisibility/sleep rules not compared (S) |
| 0x4045 CheckStatGT, 0x4046 CheckStatLT | 1,502 / 1,180 | stat > / < int0, missing object false. Stat numbers through `stats.ids`; ability checks (INT, CHR, WIS…) are the bulk |
| 0x400B Allegiance | 788 | original: EA byte **==** int0; data uses 255 and 128 only, GemRB's exact branch |
| 0x4042 PartyHasItem | 747 | any party member, first matching slot |
| 0x40A1 Internal, 0x40A3 InternalGT, 0x40A2 InternalLT | 728 / 50 / 4 | creature only, `(short)` value vs int1 |
| 0x4043 InParty | 705 | `sub_7BD41D`: party member (or in the second party list) and not dead (state 0x800) |
| 0x400D Exists | 667 | object resolves |
| 0x4051 Dead | 588 | death variable > 0 (KAPUTZ / GLOBAL, see round 8) |
| 0x4039/0x403A/0x403B NumTimesTalkedTo(GT/LT) | 479 / 342 / 1 | the caller's own count (+6902); who increments it: A6 |
| 0x407C TimerActive | 401 | a timer with that id in the caller's list |
| 0x402D HPPercentLT, 0x402C HPPercent, 0x402E HPPercentGT | 379 / 3 / 2 | `100·HP / max HP` |
| 0x4012 HPLT, 0x4011 HPGT | 94 / 23 | current HP |
| 0x404F PartyGoldGT, 0x4050 PartyGoldLT, 0x404E PartyGold | 341 / 71 / 16 | |
| 0x4061 HasItem | 190 | object's first matching slot |
| 0x4018 Range | 185 | search-cell distance² ≤ (int0+1)², same formula in GemRB |
| 0x407E CreatureInArea | 163 | caller's area name, case-insensitive |
| 0x400C Class, 0x40AD ClassLevelGT, 0x40AE ClassLevelLT | 141 / 18 / 13 | |
| 0x40B1 LastPersonTalkedTo | 100 | the caller's last talker (+610) matches the object |
| 0x4099/0x4098/0x4097 Proficiency(GT/LT) | 65 / 40 / 10 | slot byte & 7 |
| 0x4031 HaveSpell, 0x4032 HaveAnySpells | 55 / 21 | memorised and available |
| 0x401D Specifics, 0x400A Alignment, 0x4017 Race, 0x409B Team, 0x409A Faction | 45 / 44 / 12 / 9 / 5 | byte == int0; data uses exact values only. GemRB Specifics falls back to the caller for a missing object (edge) |
| 0x408B/0x4089/0x408A PartyCount(GT/EQ/LT) | 38 / 27 / 4 | party size |
| 0x40AA ExtraProficiencyGT, 0x40A8 ExtraProficiency | 33 / 20 | free proficiency points |
| 0x401F TimeOfDay | 31 | day 7-21, dusk 21-22, night 22-6, morning 6-7: same hours |
| 0x4041 GlobalTimerNotExpired | 5 | `now < value` |
| 0x4091/0x4090 PartyItemCount(GT/LT) | 9 / 2 | |
| 0x40A6 IsLocked | 3 | original: doors only (containers false); all three uses are doors |
| 0x4062 InteractingWith | 1 | `sub_40F297` object match; not compared further |
| 0x40B2 IsInGuardianMantle | 1 | Guardian Mantle counter (+21271) == 1; GemRB `IMM_GUARDIAN` (see E-012) |

---

# A3: event triggers (round 11, 2026-11-19)

Done: 24/24. Event triggers (ids < 0x4000) are not cases of the dispatchers: engine code raises them into the
object's **pending trigger list** and the condition evaluator only matches them.

**How the original handles events (read once, applies to every row):**
- **Raise:** the trigger constructors `sub_43411A(id, int)` and `sub_434010(id, object, int)` build the trigger; a
  message carries it to the object's pending list (creature `+890`). Every raise site in the exe:
  `python tools/parity/dumps.py grep orig "sub_(434010|43411A)\(" --max 400` (188 lines; `--max` is new).
- **Evaluate:** `sub_40629D` walks a block's conditions: a status trigger (bit 0x4000) goes to the dispatcher and
  its `!` flips the result; an **event** is true when **some pending trigger** matches it through `sub_434215`: same
  id (or **a pending 0x5D PickPocketFailed satisfies a script 0x02 AttackedBy**), pending int == script int unless the
  script's int is 0, object match `sub_40F297`. The `!` of an event flips the match **only for a pending trigger with
  the same id**: `!Event(x)` is true when a trigger of that id is pending whose parameters *don't* match, and false
  when none is pending.
- **Lifetime:** the script pass `sub_45F538` (7 slots `this+834…858`) empties the pending list at the end of **every**
  pass (line 225 `sub_898F22(this+890)`), whether a block ran or not. Exception: in the restricted state of line 48
  (A5) only the override slot runs, and the list survives unless a block ran.
- EE numbers the PST-only events differently (`WasInDialog` 257, `NamelessBitTheDust` 262, `FailedToOpen` 264,
  `NullDialog` 269, `Vacant` 274, `HarmlessOpened` 275, `HarmlessClosed` 276, `HarmlessEntered` 277): grep
  `CAITrigger::CAITrigger\(` in ee to find a raise site by name.

**GemRB:** raises with `AddTrigger(TriggerEntry(trigger_x, …))` into `Scriptable::triggers`; trigger functions use
`MatchTrigger`/`MatchTriggerWithObject` (`Scriptable.cpp`), which don't consume; `Trigger::Evaluate`
(`GameScript.cpp`) applies `!` to the whole result; `Scriptable::Update` clears the list only `if (changed)` (a block ran).

New tool: `python tools/parity/bcs.py <script>` decompiles a BCS; `--grep REGEX` searches every block of every
script (one line per block); `--objects` counts object functions and fields (A4).

## Differences (findings T11-T16, `findings.md` section 14)

### T16 NullDialog is a status check in GemRB: true almost always (sev 1, V)
- **Original:** `sub_7A3A64:309-315` (the talk action; EE `CGameSprite::PlayerDialog:298-309`): when a creature is
  asked to talk and its dialogue resref is empty, event 0xA4 `NullDialog(talker)` is raised on it. Nothing else raises it.
- **GemRB:** `Triggers.cpp` `GameScript::NullDialog`: resolves the object and returns true when **it is not in a
  dialogue**. Nothing raises `trigger_nulldialog`. So `NullDialog([ea=PC])` is true on any pass where a PC resolves
  and isn't talking.
- **Data (2 blocks, both in `AR0403`):** `0403PROP` on "Starved Dog Barking" (`SDTHUG2`, which *has* dialogue
  `DSDTHUG`, so the event can never fire in the original): `NullDialog([ea=PC])` → `Enemy()`,
  `RunningAttack(NearestEnemyOf(Myself))`. `0403GDUL` on the two Painted Thugs (`PTHUG1`/`PTHUG2`, dialogue `None`):
  `NullDialog([ea=PC])` → `AR0403Dueling_Gangers` = 4, which makes them stop duelling each other and attack the party.
- **Re-check:** `python tools/parity/bcs.py 0403GDUL`; `python tools/parity/dumps.py lines orig sub_7A3A64 305 320`;
  `grep -n "int GameScript::NullDialog" -A14 gemrb/core/GameScript/Triggers.cpp`; `grep -rn trigger_nulldialog gemrb/core`.
  In game (AR0403): `GemRB.EvaluateString("NullDialog([PC])", 0, <thug id>)` returns 1 with nobody talking.
- **Breaks:** the AR0403 duelling-gangers scene: they turn on the party on sight instead of fighting each other until
  talked to, attacked or approached within 5; the barking thug attacks unprovoked.

### T11 TimerExpired is consumed by the first block that tests it (sev 2, V)
- **Original:** `sub_44A918` (timer tick, EE `CGameAIBase::CheckTimers`, once a second): each timer counts down; at
  ≤ 0 it is removed and event 0x22 with int = timer id is raised (line 38). It is pending for the whole next pass, so
  every block of that pass that tests `TimerExpired(n)` sees it.
- **GemRB:** a status check (`Scriptable::TimerExpired`): the first evaluation after expiry returns true **and erases
  the timer**. Conditions stop at the first false one, so a block `TimerExpired(n) <other>` whose other condition fails
  eats the timer, and a later fallback block `TimerExpired(n)` never fires.
- **Data (8 scripts):** `0605DOL3`, `0605ECC3`, `0605KES3`, `0605NEN3`, `0605VIV3` (`TimerExpired(4)
  Internal(Myself,3,2)` then `TimerExpired(4)` → `ChangeAIScript`): unless Internal 3 is 2 the creature never switches
  script and its timer is gone. `0200DF5` (`TimerExpired(1) TimeOfDay(2)` first, then two `GLOBALleaving` branches),
  `0200DM2`, `0200DM3` (two `GLOBALleaving` branches): the relocation on the second branch is lost.
- **Re-check:** `python tools/parity/bcs.py 0605DOL3`; `python tools/parity/dumps.py lines orig sub_44A918 20 70`;
  `grep -n "bool Scriptable::TimerExpired" -A12 gemrb/core/Scriptable/Scriptable.cpp`.
- **Breaks:** ambient 0605 NPCs and the 0200 dustmen get stuck in their current script or place.

### T12 Unhandled events stay pending across script passes in GemRB (sev 2, V)
- **Original:** `sub_45F538:202-225`: after the last slot the pending list is emptied, every pass.
- **GemRB:** `Scriptable::Update`: `if (changed) ClearTriggers();`, `changed` true only when a block ran
  (`GameScript::Update`). An event no block used waits until some block runs, possibly many passes later.
- **Difference:** `AttackedBy([ea=PC]) Global("x",1)` fires in GemRB when `x` becomes 1 long after the attack (if nothing
  else ran meanwhile); in the original only in the pass right after. Same for `OnCreation()` with other conditions
  (`0000SUMN`, `0403GANG`, `0403GDUL`, `0403GNGB`, `0701HGRD`).
- **Re-check:** `python tools/parity/dumps.py lines orig sub_45F538 196 226`; `grep -n "if (changed)" -B2 -A3 gemrb/core/Scriptable/Scriptable.cpp`.

### T13 Negated event triggers (sev 3, V)
- **Original:** `sub_40629D`: `!Event(x)` = "an event of this id is pending whose parameters differ"; with nothing
  pending, or for a parameterless event, false.
- **GemRB:** true whenever no matching event is pending.
- **Data (161 blocks):** `Help() !Help([ea=PC])` (158 guard scripts, e.g. `0100THV1`): same outcome except when a PC
  and a non-PC Help are pending together (original true, GemRB false); `0301BLAR` `AttackedBy() !AttackedBy([ea=PC])`
  likewise. **`AR1501` `!Global("GLOBALCurrent_Area",1501) !Vacant()`** is never true in the original (the block
  setting `GLOBALCurrent_Area` = 1501 and toggling corpses `AR1501_K`/`AR1501_N` never runs); GemRB runs it on the first
  pass with the party there (`1501CS1`/`1501CS4` set the corpses again). `1800TR21` `!NamelessBitTheDust()` also has
  `False()` (dead in both).
- **Re-check:** `python tools/parity/bcs.py --grep '!(Help|AttackedBy|Vacant|NamelessBitTheDust)\('`; `python tools/parity/ida.py show orig 40629D`.

### T14 A failed pickpocket doesn't count as AttackedBy in GemRB (sev 2, V)
- **Original:** `sub_7A9B03:138` (pickpocket) raises only 0x5D PickPocketFailed on the victim, and `sub_434215` lets a
  pending 0x5D satisfy a script's `AttackedBy` (0x02): every `AttackedBy([ea=PC])` block (1,060 uses: `Enemy()`,
  `Attack(LastAttackerOf(Myself))`, `RunAwayFrom`) fires on a failed pickpocket.
- **GemRB:** `Actions.cpp` `PickPocket`: PST has `StealIsAttack = 0` and no `ppbehave.2da`, so only
  `trigger_pickpocketfailed` is raised. (EE raises both: S.)
- **Re-check:** `python tools/parity/ida.py show orig 434215`; `python tools/parity/dumps.py lines orig sub_7A9B03 130 140`;
  `sed -n 4756,4770p gemrb/core/GameScript/Actions.cpp`.
- **Breaks:** victims that should turn hostile, flee or shout for help after a caught pickpocket stay calm (only the 8
  `PickPocketFailed(Protagonist)` scripts of 0600/0601 react).

### T15 Damage effects raise HitBy and AttackedBy in the original (sev 2, S)
- **Original:** `sub_4B534F` (virtual; matches EE `CGameEffectDamage::OnAddSpecific`): when an op-12 effect is added
  the target gets `HitBy(source, damage type = high word of param2)` (0x20) and `AttackedBy(source)` (0x02), whatever the
  damage and whether or not the source is hostile.
- **GemRB:** `Actor::Damage` raises `trigger_hitby` only for damage > 0, naming `LastHitter`, which is set only while it
  is 0 (the **first** hitter stays); `AttackedBy` comes from weapon attacks and `SF_HOSTILE` effects (`EffectQueue.cpp`).
- **Data:** `HitBy([ea=PC],64)` (magic) in `0205CNTR`, `0205POS3`, `0205SERV` (`AR0205DisturbanceLevel`); `AttackedBy`
  blocks against non-hostile damage.
- **Missing:** the vtable that owns `sub_4B534F` (`ida.py xrefs orig 4B534F`), to prove it is op 12's add hook.

## Parity rows (P)

| Event | Uses | Original raise site | GemRB |
|---|---|---|---|
| 0x02 AttackedBy | 1,280 | weapon hit `7BC70E:80`, damage effect `4B534F:35`, `67B6A2:291`, `78113D:253` | `Actor::AttackedBy`; see T12, T14, T15 |
| 0x03 Help | 1,031 | `sub_79FB29:27`, every object within range (A-17) | `Map::Shout`; `!Help` see T13 |
| 0x25 Die | 407 | `sub_4B71B4:60,153`, the dying creature | `Actor::Die` |
| 0x36 OnCreation | 337 | object ctor `sub_44997C:82` (objects are rebuilt when a save loads) | `Scriptable` ctor; see T12 |
| 0xA5 WasInDialog | 244 | dialogue end `sub_49907D:26`, every participant | `DialogHandler::EndDialog` → `LeftDialog` |
| 0x9F HarmlessEntered | 113 | `sub_4F113E:396`, once per entry when the region doesn't fire | `InfoPoint::TriggerTrap` (not trapped) |
| 0x4C Entered | 70 | `sub_4F113E:335` (trap fires), `sub_7AAA11:406` | `Highlightable::TriggerTrap` |
| 0x24 Trigger | 52 | `SendTrigger` `sub_465BEB:25` | `Actions.cpp` `SendTrigger` |
| 0x94 Vacant | 49 | `sub_7D1D1C:888`: each update, every loaded area that isn't the viewed one | status: no party member in the area; `!Vacant` T13 |
| 0x22 TimerExpired | 47 | T11 | T11 |
| 0x52 Opened, 0x9D HarmlessOpened, 0x9E HarmlessClosed, 0xAF FailedToOpen, 0x57 Unlocked, 0x60 PickLockFailed | 18/11/1/5/1/4 | `sub_4A17F7` (151, 408, 444, 579, 630), `sub_4955F4`, `sub_7AE549`, `sub_7AFE03` | `Door.cpp`, `Actions.cpp`, `Highlightable.cpp` |
| 0x5E StealFailed | 9 | store `sub_67B6A2:264` | `GUIScript.cpp` steal |
| 0x5D PickPocketFailed | 8 | `sub_7A9B03:138` | T14 |
| 0x79 TriggerClick | 8 | `sub_4F38D6:702` | `GameControl.cpp` `trigger_clicked` |
| 0x06 ReceivedOrder | 3 | `GiveOrder` `sub_46C958:25` | `Actions.cpp` `GiveOrder` |
| 0x20 HitBy | 3 | T15 | T15 |
| 0x4A Died | 3 | `sub_4B71B4:196`, every object within visual range (`sub_47699E`) | `Actor::SendDiedTrigger` |
| 0xA4 NullDialog | 2 | T16 | T16 |
| 0xAB NamelessBitTheDust | 2 | **never raised**: no constructor call or other constant 171 in the exe. EE raises 262 on the area of the dying protagonist (`CInfGame::DispatchCharacterDeathMessage`) | `Actor::Die`, Player1's own list. Users: `0901SHM0` (creature script: never fires in any engine), `1800TR21` (dead block) |
