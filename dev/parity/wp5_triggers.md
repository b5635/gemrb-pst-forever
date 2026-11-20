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
