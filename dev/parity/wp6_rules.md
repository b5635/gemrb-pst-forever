# WP6: PST rules (track C), judged against PST:EE

Done: death, level-up, rest, stealth, casting branches, flavour, caster-level durations (R-7…R-16).
Checklist: `pst_functions.md`. IDs `R-<n>` continue R1-R6 (`findings.md` section 6).

## 1. The Nameless One's death and revival

EE chain: protagonist death → `CInfGame::ReadyCharacterTerminationSequence` (countdown `+13220` = 150 ticks in PST,
fade at 30) → `CScreenWorld::AsynchronousUpdate:1043-1066` → `CInfGame::StartCharacterTerminationSequence` →
`CScreenWorld::StartDeath` → `CGameArea::HandleNamelessDeath`; if that returns 0, `StartDeath:141-301` sends him to
the Mortuary. GemRB: `Game::EveryoneDead` (`gemrb/core/Game.cpp`, PST branch) → `IniSpawn::RespawnNameless`
(`gemrb/core/IniSpawn.cpp`), INI keys read in the `IniSpawn` constructor.

INI data (`[nameless]`, 179 INIs with a section, `$TEMP` script over `pstres.gemrb()`): `destare`/`point`/`state` in
166, `partyarea`/`partypoint` only in AR1800; `[namelessvar]` only AR0201-AR0203 (`Mortuary_Alert*`). Every point is
written `[x.y]` (AR0702 `[4550.2759:4]`). `SetNamelessDeath`/`SetNamelessDeathParty` (288/289): 0 BCS, 0 DLG uses.

### R-7 The `Death` counter never goes up in GemRB
- **Status:** V      **Severity:** 1      **Uses:** 31 DLG references in 9 dialogues + 8 AR1201 blocks      **By:** opus
- **EE:** `CInfGame::StartCharacterTerminationSequence:29-32` adds 1 to GLOBAL `Death` every time the protagonist's
  death sequence starts (callers: `ReadyCharacterTerminationSequence` ← `CGameEffectDeath`, petrification,
  imprisonment, `ExecuteAction`). The constant `CGameArea::NamelessDeathCounterLabel` = `"Death"` (`ctor_003:22`).
- **GemRB:** nothing writes `Death`: `grep -rn '"Death"' gemrb/core gemrb/GUIScripts gemrb/unhardcoded/pst`
  finds only the effect name. Only the dialogues' own `IncrementGlobal("Death",…)` (DDEATHAD ×2, DJOLMI, DYI'MINN,
  DAWAIT) raise it.
- **Difference:** after the Nameless One has died 5 times in EE, `Death` = 5; in GemRB it stays 0 unless one of those
  dialogues ran.
- **Data affected:** DTRANS (Transcendent One: `Global("Death",1)`, `GlobalGT(…,0)`, `GlobalGT(…,1)`), DSERE,
  DAWAIT (Deionarra), DNORDOM, D0202P and DSKSCRAP (`GlobalGT(…,20)`), AR1201 (Fortress: shadow count chosen by
  `Death` < 5, 5-9, 10-14, …).
- **Re-check:** `python tools/parity/dumps.py show ee "CInfGame::StartCharacterTerminationSequence("`;
  `python tools/parity/bcs.py --grep 'GLOBALDeath"'`; `grep -rn '"Death"' gemrb/core gemrb/GUIScripts`.
- **Breaks:** the Transcendent One's and Deionarra's lines about past deaths never show; the Fortress spawns the
  fewest shadows however often he died.

### R-8 `partyarea`/`partypoint` used at the wrong moment (AR1800)
- **Status:** V      **Severity:** 2      **Uses:** 1 INI (AR1800: `partyarea=ar1700`, `partypoint=[3928.2708]`)
- **EE:** `HandleNamelessDeath:387-551`: on the Nameless One's death the party (still in the party) is sent with
  `LEAVEAREALUA` to `partyarea`/`partypoint`; without those keys, to `destare`/`point`. Nothing reads them at area load.
- **GemRB:** `IniSpawn::InitialSpawn` (run by the `IniSpawn` constructor, i.e. when the area is loaded) moves every
  companion to `PartySpawnArea`/`PartySpawnPoint` **and removes them from the party** when `partypoint` is set;
  `RespawnNameless` ignores both and moves every PC to the Nameless One's point (`Game::MovePCs`).
- **Difference:** in GemRB entering AR1800 dismisses the companions to AR1700; in EE they stay until the B8 rule
  (leaving AR1800 to FR1700, `PlanescapeLeaveAreaName`) dismisses them, and on a death in AR1800 they go to AR1700
  [3928,2708]. **Correction to B8:** GemRB does cover the AR1800 dismissal, but on entry, not on exit.
- **Re-check:** `sed -n '/void IniSpawn::InitialSpawn/,/^}/p' gemrb/core/IniSpawn.cpp`;
  `python tools/parity/dumps.py lines ee "CGameArea::HandleNamelessDeath(" 383 551`.

### R-9 Revival animation for `state` 35 / 36
- **Status:** V      **Severity:** 3      **Uses:** 166 INIs (35 in 150, 36 in 16)
- **EE:** `HandleNamelessDeath:552-566`: `state` is a sequence number. 36 = `SEQ_MISC1` (lying, direction 2, a game
  flag `+26452` = 1); anything else is played as given, so 35 = `SEQ_GETUP` (direction 0). A missing key = "36"
  (`:411-418`), an empty value = `SEQ_GETUP`; `CGameSprite::SEQ_MISC1` = 36, `SEQ_GETUP` = 35 (`eeconst.py`).
- **GemRB:** `RespawnNameless`: 36 → `IE_ANI_PST_START`; 35 → nothing (comment "already standing"); default 36.
- **Difference:** for 35 EE plays the get-up animation, GemRB shows him standing.

### Parity
| Item | Note |
|---|---|
| no `[nameless]` section / no INI | EE: Mortuary AR0202 [1476,2356] lying (`StartDeath:141-301`); GemRB: `JoinParty(JP_INITPOS)` → `start.2da`/`startpos.2da`/`startare.2da` = AR0202 [1476,2356], state 36. Party: EE [1400,2400], GemRB the Nameless One's point (presentation). |
| `[namelessvar]` | both write the current area's list as GLOBALs on death, creating missing ones (EE `CVariableHash::AddKey`, `:335-381`). |
| healing | EE: full heal through an op 17 effect, unequip/re-equip, actions cleared, reselected; GemRB: `Resurrect` + `Heal(0)` + reselect. |
| point syntax | EE accepts `.` or `,` after the x, GemRB only `.`; all 166 use `.`. |
| `Transcendent_Final_Speech` | GemRB's own rule (commit `e1142ad06`: the final fight is fatal): not in EE (`dumps.py grep ee Transcendent` = 0). EE ends it through `Game_Over` 4 in AR1203/AR1204 (R2). Keep until R2 is fixed. |
| EE bug | `HandleNamelessDeath:723` formats the party area with `"AR4.4d"` (no `%`) when `Nameless_death_party_area` is set: only reachable through the unused action 289. |

### R-10 No revival line after the Nameless One gets up
- **Status:** V      **Severity:** 3      **By:** opus
- **EE:** `CScreenWorld::StartDeathReaction:94-231`: when the dead one is `nameless`, one random line from the
  members' `death.2da` entries plays at once (channel 8) **and** a revival line is queued for a random member from
  `CPlanescape::GetNamelessRevivalReaction` (hardcoded: Morte MRT397A-MRT407A (10), Annah ANA506D-ANA512C (9), Grace
  FFG295-298, Vhailor VHA218-221, Nordom NOR223-225, Dakkon DAK162-164, Ignus IGN218-219, the Nameless One NAM151B-154).
- **GemRB:** `Game::PartyMemberDied` → `Actor::ReactToDeath` plays the `death.2da` line only. No revival list
  (`grep -rn MRT397A gemrb/` = 0).
- **Re-check:** `python tools/parity/dumps.py show ee "CPlanescape::GetNamelessRevivalReaction(" --all`.

## 2. Level-up

### R-11 Mage-to-12 bonus after another specialisation: INT +2 in EE, +1 in GemRB (`Specialist` 9)
- **Status:** V      **Severity:** 2      **By:** opus
- **EE:** `CPlanescape::HandleNamelessBonuses:95-440` (permanent effects on the base stats; `Specialist` GLOBAL):
  | class | first to 7 (others ≤ 6) | first to 12 (others ≤ 11), was this class's 7 | first to 12, another class had 7 |
  |---|---|---|---|
  | fighter | 1: STR +1 | 4: STR +1, CON +1, max HP and HP +3 | 7: STR +1 |
  | thief | 2: DEX +1 | 5: DEX +2, Luck +1 | 8: DEX +1 |
  | mage | 3: INT +1 | 6: INT +2, WIS +1, Lore +5 | **9: INT +2** |
  A class that jumps from ≤ 6 to ≥ 12 in one level-up gets both of its bonuses at once (`v51 && !KeyValue`).
- **GemRB:** `GUIREC.py HandleSpecializationBonuses`: same table except **9 = INT +1** (`grantFirstBonus(…, 6)`), and a
  jump from ≤ 6 to ≥ 12 gives only the first bonus (returns after it; the second comes at the next level-up).
- **Re-check:** `python tools/parity/dumps.py lines ee "CPlanescape::HandleNamelessBonuses(" 350 400`;
  `sed -n 905,925p gemrb/GUIScripts/pst/GUIREC.py`.

### R-12 Companion weapon points: Vhailor's second point at 13 instead of 14 (and EE's own bug)
- **Status:** V      **Severity:** 2      **By:** opus
- **EE:** `CPlanescape::AssignFighterProficienciesOnLevelUp`: by script name (`eeconst.py 0xED4DA0 --strptr 8`,
  index table `0xED4E00`): Annah and Morte FIST, Dakkon EDGED: +1 when the fighter level passes 4, 7, 10 (levels 5, 8,
  11); Nordom BOW at 8, 11, 13; Vhailor at 14, 17, 20 (passes 10, 13, 16 → 11, 14, 17); Grace, Ignus: nothing.
  **Vhailor's branch passes `PROFICIENCIES_AXE` (= 6, a BG category) instead of `PST_PROFICIENCIES_AXE` (92), and
  `SetActiveProficiency` ignores ids outside 89-134: in EE Vhailor gains nothing**, though the "+N Axe" text shows.
- **GemRB:** `GUIREC.py GainedWeapProfs` + `charprof.2da` (total points per fighter level): Annah, Morte, Dakkon,
  Nordom match EE; Vhailor's row reaches 4 at **level 13** (table comment says 14), 3 at 11, 5 at 17.
- **Decision for the owner:** EE's Vhailor branch is a Beamdog typo (the message shows the gain). Recommend keeping
  GemRB's gains and moving Vhailor's row-13 value to row 14.
- **Re-check:** `python tools/parity/eeconst.py "CGameSprite::*PROFICIENCIES_AXE"`;
  `cat gemrb/unhardcoded/pst/charprof.2da`.

## 3. Rest

### R-13 Rest in the 9 "permission" areas and AR0402
- **Status:** V      **Severity:** 2      **Uses:** 9 + 1 areas      **By:** opus
- **EE:** rest goes through `CGameArea::CanSaveGame(err, resting=1, …)` → `CGameArea::PSTCanRestParty` (PST only;
  the generic "enemies in the area" counters `this+1009/1010` are skipped for PST). EE's ARE files carry new flag bits
  (`pstres` scan, `+0x14`): original 2 → `0x80`, 4 → `0x100`, 6 → `0x180`, and `0x10` everywhere. Rules: `0x100` alone
  → refused; `0x80` or `0x20` → refused (other message); **`0x180` → refused only while a living creature outside the
  party is in the area** (three object lists, `IsCharacterInParty`, state bit `0x800`); else allowed.
- **GemRB:** `Game::CanPartyRest` (PST `AREA_OVERRIDE` branch) on the original flags: 6 → always refused
  (`PST_REST_PERM`, "you must obtain permission"), 2 → refused, 4 → refused.
- **Difference:** AR0102, AR0103, AR0107, AR0305, AR0503, AR0510, AR0602, AR0704, AR1500 (orig flags 6): EE lets the
  party rest once nobody else (alive, not in the party) is in the area; GemRB never does. **AR0402**: EE's data has flag
  `0x2` only (none of the rest bits), so EE allows rest there; GemRB (original data: 2) refuses (EE data change, WP9).
- **Unread:** the three error strings (`byte_F0073F/40/41` are decompiler labels, not resolved).
- **Re-check:** `python tools/parity/dumps.py show ee "CGameArea::PSTCanRestParty(" --all`;
  `sed -n '/bool Game::CanPartyRest/,/^}/p' gemrb/core/Game.cpp`.

## 4. Stealth and darkness

### R-14 Hiding: EE uses a flat stealth roll with a night bonus, GemRB scales by light level
- **Status:** V      **Severity:** 2      **By:** opus
- **EE:** `CGameSprite::Hide:47-152` (PST branches): roll = 1-100 with no armour penalty and no luck, 100 fails
  outright; the roll gets −20 (`HIDE_DARK_BONUS`; `HIDE_LIGHT_PENALTY` = 0) when `CPlanescape::IsSpriteInDark`; success
  if roll ≤ Stealth and no enemy is near (`GetNearest` enemy = none). `IsSpriteInDark`: only in areas with type bit
  `0x400` (`area+2177 & 4`), only at night (game time outside 27000-99000 of the day), and only where the area tint at
  the sprite is ≤ `RGB_NIGHT_COLOR` (100,100,200) in all channels.
- **GemRB:** `Actor::TryToHide`: `LuckyRoll(1,100, armour penalty)`, 1 fails outright, chance =
  (100 − light_diff) × Stealth / 100 with light_diff from `GetLightLevel` (0-50).
- **Difference:** Stealth 50 in a lit street by day: EE 50 %, GemRB about 25 %; at night in a dark spot EE 70 %, GemRB
  up to 50 %. Luck changes GemRB's roll; armour too.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hide(" 40 152`;
  `python tools/parity/eeconst.py "CGameSprite::HIDE_*" CInfinity::RGB_NIGHT_COLOR`.

### Casting path (`CGameSprite::SpellPST`): PST branches read, nothing new
- Casting drops the zombie disguise (`GetNamelessDisguise() == 1` → `SetNamelessDisguise(0,0)`): already A-290 (EE: same).
- SPIN108/SPPR502 (raise dead) skip the target/range/LOS checks; SPIN101/SPIN103 go straight to the ability by
  caster level; a fizzle shows `SE10FIZZ` + `MAGIC01`; an invisible caster targeting someone else gets op 136.
  Not compared line by line with GemRB's generic casting (S, sev 3).

## 5. Flavour (sev 3)

### R-15 Grace's first-ring joke and Morte's comments on moved items are missing
- **Status:** V      **Severity:** 3      **By:** opus
- **EE:** `CPlanescape::GetGraceRingJoke` (from `CInfGame::SwapItemPersonal`): the first time Grace equips a ring,
  one of two strings (random) and GLOBAL `Grace_Ring_Equipped` = 2 (created if missing).
  `CPlanescape::LetMorteBeCreepy` (from `CScreenInventory::SwapWithSlot`): moving `CHASTITY` or `AVEST` plays MRT582A/C/D/E
  at random; other branches play MRT223/MRT224 by chance (1 in 5 gate) when Grace is in the party.
- **GemRB:** none (`grep -rn "MRT582\|Grace_Ring_Equipped" gemrb/` = 0); `item_use.2da` covers only the usability texts.
  No script or dialogue reads `Grace_Ring_Equipped` (0 BCS, 0 DLG), so nothing observable beyond the line itself.

## 6. Casting path, continued

### R-16 Caster-level spell durations: GemRB's `spldurat.2da` matches EE except Litany, SPWI602, Blacksphere, op 301
- **Status:** V      **Severity:** 2 (Litany) / 3 (rest)      **By:** opus
- **EE:** `CGameSprite::SpellPST:538-564` passes every ability effect through `CGameAIBase::ApplyLevelBasedDurationMods`
  with key = 1000 (SPPR) / 2000 (SPWI) / 3000 (SPIN) + the resref's number and L = caster level. It overwrites the
  duration (`+0x28`, both copies) and for some the field `+0x48`, which GemRB's table calls the onset `DELAY`.
- **GemRB:** `Spell.cpp AdjustPSTDurations` + `gemrb/unhardcoded/pst/spldurat.2da` (BASE + PER_LEVEL × L, skip one
  effect index, DELAY, MAX; only timing modes 0/3, never op 195).
  | Spell | EE | GemRB `spldurat` | Verdict |
  |---|---|---|---|
  | SPIN101 Litany of Curses | 10 × L, no cap, every effect but op 45; save modifier −`Morte_Taunt` | 5 × L, max 30, skips effect 2; −`Morte_Taunt` in `GetSavingThrow` | **V**: level 12 → EE 120, GemRB 30 |
  | SPWI104 Fist of Iron | 5 × L + 5, delay 15 | 5 + 5 × L, delay 15 | P |
  | SPWI114 Friends | 5 × L + 5 + 0…15, delay 15, not op 8 | 15 + 5 × L, delay 15, skips effect 2 | V3 (EE random base 5-20, GemRB 15) |
  | SPWI214 Luck | 5 × L, delay 15 | 5 × L, delay 15 | P |
  | SPWI216 Blur | 5 × L + 15, delay 15 | 15 + 5 × L, delay 0 | V3 (delay) |
  | SPWI311 Zerthimon's Focus | 5 × L, delay 25; op 301 fixed 25 | 5 × L, delay 25 | V3 (op 301) |
  | SPPR104 Detect Evil | 25 × L + 50, max 300 | handled in `fx_detect_evil` (commented row) | not re-checked |
  | SPWI308 Tasha's | 5 × L, delay 160; op 373 → 5, op 174 → 1 with a time-based delay 27-42; ops 353/356 untouched | 5 × L, delay 7, all effects | V3 |
  | SPWI402 Confusion | L + 10, delay 25 | 10 + L, delay 25 | P |
  | SPWI401 Blacksphere | **op 39 only**: 10, delay 100 | all timing-0/3 effects: 10, delay 100 | V3 |
  | SPWI602 | no rule (SPL durations) | 5 × L | V3 (GemRB invention) |
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameAIBase::ApplyLevelBasedDurationMods(" 30 161`;
  `cat gemrb/unhardcoded/pst/spldurat.2da`; `sed -n '/static void AdjustPSTDurations/,/^}/p' gemrb/core/Spell.cpp`.
