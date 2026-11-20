# Planescape: Torment (PST) Parity Implementation Spec

Consolidated findings from the 2026-11-18/19 parity investigation (Rounds 1–15), ordered so foundational combat/roll math, opcodes, scripting, and global rules precede the spell implementations and store/audio subsystems.

* **Section flow:** `1. Combat & Saves` -> `2. Effect Opcodes & Pipeline` -> `3. Scripting Engine, Triggers & Actions` -> `4. Global Rules, Death/Revival & BALDUR.bcs` -> `5. Spells, Projectiles & Plane Warping` -> `6. Items, Stores, Loot & Audio` -> `7. Reference (F/P)`.
* **Reference docs:** [README.md](README.md) (sources/method), [PARITY_PLAN.md](../../PARITY_PLAN.md) (execution plan).
* **Binaries:** Original = `Torment.exe` 1.1 + Fixpack 4.13 + Unfinished Business 4.12 (`C:\Program Files (x86)\Black Isle\Torment`, symbols `sub_…`); EE = PST:EE (`CPs…` / `CPlanescape::…`).
* **Status:** **V** = verified in original/EE code & GemRB source; **S** = strong suspicion from code (confirm in game); **F** = already fixed; **P** = parity holds (do not modify).
* **Severity:** **1** = broken gameplay or feature does nothing; **2** = wrong numbers or mechanics; **3** = visuals or audio only.

---

## 1. Combat Mechanics & Saving Throws

*Foundational hit, saving-throw, and saved-damage rules used by both weapon attacks and the effect/spell pipeline.*

**Detailed ref:** [wp10_combat.md](wp10_combat.md)

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **C-1** | **Attack roll 1 point too hard:** EE hits when `roll + AC + bonuses >= THAC0`; GemRB requires `>` (5% fewer hits for everyone). | V | 2 |
| **C-14** | **Saved damage halved, not negated:** EE halves saved damage unless resource is `NEG`; GemRB halves only with a non-empty resource (27 op-12 entries—`SPWI502/505/802/905`, Celestial Fire weapons—wrongly negate on save). | V | 2 |
| **C-15** | **Saving throws:** EE adds **no luck**, uses the best flagged save once, cannot save on a save value of `20`, and gives `+4` for improved invisibility. GemRB adds luck and rolls each save type. | V | 2 |
| **C-3** | **Auto-hit & critical miss rules:** EE auto-hits only helpless targets (`sleep/hold/web`) with **no critical miss**; GemRB also auto-hits stunned/frozen/petrified and lets a natural 1 miss a sleeper. | V | 2 |
| **C-4** | **Melee vs ranged bonus:** Disable GemRB's `+4` bonus for meleeing a ranged-weapon user in PST (`ENGINE_MODE != 3`). | V | 2 |
| **C-5** | **Ranged range modifiers:** Add `-8` penalty within 4 cells and `-2`/`-5` at long range. | V | 2 |
| **C-7** | **`Dead_Truce` `+4` restriction:** EE applies `+4` only to hostile undead vs PCs when value is `1`; GemRB also penalizes Morte/Vhailor's own attacks. | V | 2 |
| **C-18** | **Morale recovery rate:** EE recovers 1 step per `15 x recovery ticks` (60 s) vs per `recovery ticks` (4 s) in GemRB. | V | 2 |
| **C-19** | **Morale failure distribution:** EE is `80%` run / `10%` panic / `10%` berserk vs GemRB `33%` each. | V | 2 |
| **C-21** | **Nameless One extra attacks:** EE uses his **fighter level** regardless of active class (flag at derived `+100`). | S | 2 |
| **C-2** | **Luck on attack rolls:** GemRB caps lucky roll at 19 and uses it for criticals; EE clamps at 20 and uses the raw roll for criticals. | V | 3 |
| **C-6** | **Invisible attacker bonus:** Add `+4` to hit for invisible attackers. | V | 3 |
| **C-10** | **Berserk bonuses:** Add `+2` to hit / `+2` damage when berserk. | V | 3 |
| **C-8, C-11** | **Special combat checks:** Verify `NTOKEN` shadow test (animation IDs vs races) and Vhailor critical aversion. | S | 3 |

---

## 2. Effect Opcodes & Effect Pipeline

*Depends on Section 1 (`C-14`, `C-15`) and Section 5A (`S42` plane/Spell Key checks). Hardcoded spells (Section 5B), script actions (`A7`), and death hooks (`4A`) invoke these opcodes.*

**Detailed refs:** [opcodes.md](opcodes.md), [wp2_opcodes.md](wp2_opcodes.md), [wp11_effect_pipeline.md](wp11_effect_pipeline.md), [wp8_branches.md](wp8_branches.md)

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **E1** | **Op 82 (Litany of Curses):** Original `sub_4C2218` (`CGameEffectInciteRunningAttack`) queues script action 10 (`Enemy()`) on the target for the effect's duration. GemRB treats op 82 as `SetAIScript` with a hack that permanently installs `SPIN101.bcs` in the override slot. | V | 1 |
| **E2** | **Op 209 (Soul Exodus, `FANGMIRR.itm`):** Implement `fx_hostile_image` per original `sub_4D8A07` (124 lines: skips dead creatures and state `0x800`, spawns `SE10FIZZ`, etc.). Currently a stub. | V | 1 |
| **P-3** | **Separate probability & MR rolls:** GemRB uses a single roll for both probability and magic resistance (so a `0–25%` effect never lands on an `MR 30` target). EE rolls probability and MR separately. | V | 2 |
| **E4** | **Op 207 (`StopAllAction` / `CGameEffectFreezeGame`):** Original `sub_4D7A0E` -> `sub_7BB610` (`CPlanescape::SetGameFreeze`, 8.7 KB) is a game freeze, not `TimeStop`. Used by Tasha's Laughter, Desert Hell, and Bladestorm. | S | 2 |
| **E5** | **Audit GemRB TODO/FIXME opcodes used by PST:** Compare against original handlers for `ToHitModifier` 54 (93 uses), `Overlay` 201 (25), `Sparkle` 41, `FindTraps` 150, `Invisible` 20, `PlayMovie` 152. | S | 2 |
| **E7 / E30** | **Op 203 (Curse) sign & damage penalty:** GemRB subtracts `p1` from save targets (making saves *better*) and ignores damage. Original adds `p1` to save targets (worse saves) and subtracts `p1` from damage (`byte +3281`, shared with ops 73/129). Affects Prayer. | V | 2 |
| **E8** | **Target luck on effect damage dice:** Original (`sub_82015B`) rolls each damage die minus the target's luck. GemRB rolls dice once, unlucked, when the effect is queued. | V | 2 |
| **E9** | **Op 204 (Prayer) aura behavior:** Original pulses every 5 s, applying Bless or Curse for 6 s to everyone within 720 px of the caster. GemRB applies 60 s once map-wide. | V | 2 |
| **E10 / C-9 / E-208** | **Op 208 (Iron Fist) damage restriction:** `+6` damage applies to **fist attacks only** (animation `50`), with max dice in Carceri. (EE re-check confirmed GemRB's `+3` to-hit matches EE). | V | 2 |
| **E11** | **Op 206 (Embalm) dice & plane rules:** Minor Embalm is `2d4` (GemRB `1d6+1`). Add plane rules: half in Carceri, 1 in Negative Material Plane, saving throw in Baator (respecting S42 Spell Keys). | V | 2 |
| **E13** | **Op 211 (Jumble Curse) spell failure:** Original handler only plays the hiccup; GemRB also forces 100% spell failure (check if casting checks op 211 elsewhere). | S | 2 |
| **E15** | **Op 17 (Heal) percent mode & mode 4:** Percent mode adds `+50%` of max HP (e.g. Raise Dead `SPPR502`), whereas GemRB sets current HP to `50%`. Mode 4 = full heal in original. | V | 2 |
| **E17** | **Scroll / cast-spell caster level (`op 148`, `op 146`):** Original casts at `max(p1, spell's first-header minimum level)`. GemRB uses `p1` directly, causing PST scrolls (where `p1` = spell level) to cast at ~half level (Blade Storm 7 vs 14, Cloudkill 5 vs 9). | V | 2 |
| **E18 / R3** | **Op 192 (Transfer HP):** Implement full original/EE behavior (`sub_4D1C49`, 793 lines): modes 0–3 (mode 3 = percentage), special cases for Sensory Touch (`SPIN104`), Blood Bridge (`SPWI204`), and Vampiric Touch (`SPWI309`, where HP above max becomes temporary `+max HP` op 18 for 300 s), full **magic** damage (not capped at receiver's missing HP, not acid/crushing), plane rules, luck, save, and feedback strings. | V | 2 |
| **E20** | **Op 147 (Learn Spell) never rolls INT:** Original never fails spell learning; GemRB rolls INT check above Normal difficulty (affects 83 scrolls). | V | 2 |
| **E23** | **Op 13 (Death / Damage on petrified or frozen):** Damage on a petrified/frozen creature kills it in original; GemRB applies plain damage because PST never passes `CanGetChunked`. | V | 2 |
| **E24 / R4** | **Pain Mirror / Balance in All Things (`state 0xB6 = 182`):** Reflects damage to **every enemy within 120 px** of the target as **magic damage** (`x 2` in Carceri), `1` or `L / 5` times. GemRB hits only the last attacker with the original damage type. | V | 2 |
| **E25 / C-13** | **Difficulty scaling & low-HP protection:** Original scales effect damage *taken by party members* and caps damage at `max HP - 1` when `max HP <= 13` (`< 14`). Because weapon hits are op 12 effects in EE, both rules apply to weapon hits too. GemRB scales damage *dealt by enemy-EA sources* and lacks the low-HP cap. | V | 2 |
| **E27 / E-012d** | **Op 12 damage absorbers:** Guardian Mantle cancels damage if source fails save at `-4` (EE exempts magic damage); Cloak of Warding / Infernal Shield soaks **any** damage type point-for-point and lets excess through (GemRB soaks physical only and absorbs the breaking hit whole); Armor pool does not absorb op 12. | V | 2 |
| **E28 / E-129** | **Op 129 (Aid, `SPPR201`):** Grants fixed `8 x p1` HP on first application (confirmed in EE); GemRB rolls `p1d8`. | V | 2 |
| **E-134** | **Op 134 (Petrification) party retention:** PST:EE keeps petrified companions in the party and sends no death notice; GemRB removes them. | V | 2 |
| **E-104** | **Op 104 (XP, 8 tattoos):** EE adds protagonist's WIS bonus and adds XP to the current class's XP pool; GemRB adds plainly to `IE_XP`. | V | 2 |
| **E-025** | **Op 25 (Poison) mode 3 tick rate:** "1 HP every `p1` seconds" runs every `5 x p1` s in GemRB (multiplied by `round_sec`); affects `VTEETH`, `WIDMKR`, `JESTER`, `TPUNCH`, `SPWI002`. | V | 2 |
| **WP8** | **Remaining `ENGINE_MODE == 3` effect branches:** Complete comparison of GemRB's `fxspecial.py`/`fxspecial.json` against EE's PST-specific branches (ops 6, 9, 45/128, 54, 86–89, 128, 146/148, 26, 39, 134, 17, 196, 201, 203, 206). | S | 2–3 |
| **E3** | **Op 186 (`SetStatus`) `-1` handling:** Original `sub_4D08CA` sets bits when `p1 == 1`, clears bits when `p1 == -1`, does nothing otherwise (and timing 1 updates both base and derived state). GemRB sets bits for any non-zero `p1` (latent: PST data only uses `1`). | V | 3 |
| **E12** | **Op 210 (Detect Evil) state & cone:** Original sets `STATE_DETECT_EVIL` (`0x1000000`) on caster and pulses evil creatures in a **cone** in front. GemRB sets no state and uses a circle. | V | 3 |
| **E21** | **Play BAM (`ops 187–191`):** Fix placement of "random"/detached animations, timed animations cut short, and animations on corpses. | V | 3 |
| **E31** | **Op 120 `p2 = 5`:** Means `"non-silver, level 0"` in original vs `"silver, level 0"` in GemRB (`SILVMAG.itm`). | V | 3 |
| **E-130** | **Op 130 (Bless) bonuses:** EE also grants `+p1` damage and non-PC morale; GemRB grants neither. | V | 3 |
| **E-073** | **Op 73 (`DamageMod`) mode:** PST:EE **sets** the damage mod (last one wins); GemRB adds. | V | 3 |

---

## 3. Scripting Engine, Actions, Triggers & Objects

*Ordered bottom-up: Script Engine & Object resolution (`3A`) -> Event Queue & Triggers (`3B`) -> Script Actions (`3C`, which also depends on `E15` for `A7` and feeds `BALDUR.bcs` in Section 4C).*

**Detailed refs:** [scripting.md](scripting.md), [wp4_actions.md](wp4_actions.md), [wp5_triggers.md](wp5_triggers.md), [wp5_objects.md](wp5_objects.md), [wp_script_engine.md](wp_script_engine.md), [wp_dialog.md](wp_dialog.md), [wp_spawns.md](wp_spawns.md)

### 3A. Script Engine, Objects, Dialogue & Spawns

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **O-range** | **Dynamic visual range:** Visual range is `(Nameless One's fighter level + 14) x 32 px` for every creature in EE/original (recomputed on stat change); GemRB fixes it at level-3 value (`544 px`), breaking `See` and `NearestEnemyOf` (2,325 uses) once he levels as a fighter. | V | 2 |
| **O-mostdamaged** | **`MostDamagedOf` dead filter:** GemRB can pick a dead party member (EE skips dead and returns nobody when no one is hurt; Grace's `PCGRACE` AI casts cures at corpses). | V | 2 |
| **SE-1** | **Script evaluation rate:** EE runs every 16 ticks per creature (staggered), busy creatures only on a new trigger or after ~16 s; GemRB runs every tick when idle/on-screen (ambient `RandomNum` blocks fire up to 16x too often; busy creatures get interrupted). | V | 2 |
| **SE-2** | **Cutscene script execution:** Cutscene mode does not stop scripts in PST (EE skips that check for PST only; GemRB freezes all scripts during cutscenes). | V | 2 |
| **D-4** | **True text-less dialogue link priority:** GemRB picks the highest index; verify EE's `sub_B35BC0` reply order. | S | 2 |
| **D-8** | **EE dialogue content fixes:** 2,602 string differences (quest fixes like `DADMINAS`, `DAETHEL`, `D0202P`, `DAGRIL`, `ClearActions` before cutscenes) — implement as an optional data pack (Phase 7). | V | 2 |
| **SP-2** | **Single spawn pass:** EE spawns `create_qty` when `spec` count `< spec_qty` (unless `sub_92F910` clamps); GemRB stops at `spec_qty`. | S | 2 |
| **SE-4** | **Death counters:** EE prefixes faction/team kill counters with `KILL_` and lacks creature-type counter (CRE flag `0x20`, 929 CREs; `Kill_Githyanki` depends on it). Keep GemRB's type counter until EE's mechanism is located. | S | 2 |
| **O-self** | **`GroupOf`, `Nearest`, `LastHitter`:** Resolve to caller in EE/original; GemRB computes a real nearest (`Nearest`: 4 uses). | S | 3 |
| **SP-1** | **Timed `[event]` spawn groups:** EE waits one `interval` after area load before first spawn; GemRB spawns at first check. | V | 3 |
| **SE-5** | **Party XP remainder:** EE adds difficulty percentage and distributes the remainder; GemRB drops the remainder. | V | 3 |

### 3B. Triggers & Event Queue

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **T16** | **`NullDialog` semantics:** GemRB evaluates it as "not in dialogue" (true almost always) instead of an event raised only when a creature without dialogue is asked to talk (causes `AR0403` duelling Painted Thugs `0403GDUL` and barking thug `0403PROP` to turn hostile immediately). | V | 1 |
| **T11** | **`TimerExpired` consumption:** GemRB erases the timer on the first block that tests it; original keeps the event alive for the entire script pass (8 scripts lose fallback branches: `0605` `*3` NPCs, `0200` dustmen). | V | 2 |
| **T12** | **Pending event lifetime:** GemRB leaves unused events pending until a block runs; original clears the event list after every pass (stale `AttackedBy`/`OnCreation` can fire later). | V | 2 |
| **T14** | **Failed pickpocket as `AttackedBy`:** In original, a pending `PickPocketFailed` satisfies `AttackedBy` (1,060 hostile-reaction blocks); GemRB does not trigger `AttackedBy`. | V | 2 |
| **T15** | **`HitBy` / `AttackedBy` on op-12 damage:** Original raises `HitBy(source, type)` and `AttackedBy(source)` on every op-12 damage effect; GemRB raises only for `damage > 0` (naming first hitter) and `AttackedBy` only for hostile sources. | S | 2 |
| **T8** | **`NearLocation` distance:** GemRB subtracts personal radius and omits `range + 1`. | V | 3 |
| **T9** | **`NumCreature(LT/GT)` scope:** Counts only creatures the caller sees in original vs the whole area in GemRB (`AR1601`, `AR1401`). | S | 3 |
| **T10** | **`LOS` checks:** GemRB adds visual range and hidden/invisible checks to original's range + line-of-sight test. | V | 3 |
| **T13** | **Negated events (`!Event(x)`):** Means `"an event of this id with other parameters is pending"` in original vs `"none matching pending"` in GemRB (`AR1501` `!Vacant()` block). | V | 3 |

### 3C. Script Actions

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **A1** | **`EscapeAreaRunning` (313) missing:** Emits "Unknown Action" (103 uses in 63 scripts: ghosts, cutscene walkers). Implement per original `sub_76A7EA`. | V | 1 |
| **A14** | **`Damage` action misreads amounts `>= 16` & can kill:** GemRB always decodes `int1` as a dice code (`25 -> 9`, `20 -> 4`, `50 -> 2`) and routes through `Actor::Damage` (resistances, luck, death). Original treats `int1` as dice only when bits `0xF000` are set and modifies current HP directly, clamped to `>= 1` (dialogue damage never kills; 78 uses, 74 DLG). | V | 1 |
| **A2 / Sec 9** | **Overloaded `*Ex` action extra parameters:**<br>- `MoveToObjectEx(Timeout)` (22, 113 uses): `sub_785E47` decrements non-zero parameter per update and gives up below 2; GemRB never gives up.<br>- `JoinPartyEx(JoinGroup)` (19, 136 uses, 73 with `1`): `sub_7A0423` calls extra party-group join (`sub_4089DC`) when non-zero; GemRB ignores.<br>- `PolymorphEx(..., RangeModes)` (146, 23 uses): stores 2nd parameter on creature (`byte +1991`); GemRB ignores.<br>- `RunAwayFromEx(NoAttacks)` (29), `DeactivateEx(RenderMode)` (125), `FullHealEx` (305), `StartCutSceneEx` (310): audit remaining handlers. | V / S | 2 |
| **A5** | **`RunAwayFrom(Ex)` never attacks:** Original attacks enemies within weapon reach when `NoAttacks == 0`; GemRB reads the flag as "no interrupt" (`GSUtils.cpp:2646`; 874 uses). | V | 2 |
| **A6** | **`DeactivateEx` party filter & `RenderMode`:** Original cannot deactivate party members and passes `RenderMode` to `SetActiveAI`; GemRB hides anyone and ignores `RenderMode` (82 uses). | V / S | 2 |
| **A7** | **`RestParty` Nameless One heal:** Original fully heals the Nameless One (op 17 mode 4) while companions receive the specified HP amount; GemRB heals all alike. | V | 2 |
| **A8** | **`StartCutSceneEx` `int0`:** GemRB uses it as "test conditions"; original sends a message (`vtable 8DC550`). | S | 2 |
| **A10** | **`PlaySequence` / `SetAnimState` blocking:** Original blocks until the animation finishes; GemRB's PST path (`OneByteAnimationID`) returns before its wait, starting the next action immediately (1,859 uses). | V | 2 |
| **A11** | **`StartRandomTimer` & `WaitRandom` bounds:** GemRB `Roll(1, max-min, max-1)` rolls `max … 2*max-min-1` instead of `min … max` (268 uses, ambient loops 1.5–2x slower); `WaitRandom` never rolls its max (sev 3, 1,398 uses). | V | 2–3 |
| **A13** | **Dak'kon's Karach blade upgrade timing:** GemRB swaps on `MoraleDec/Inc/Set` (`CheckKarachUpgrade`), dropping to the bad blade when no threshold is crossed. Original swaps only at **level-up** (levels 4/7/10, variant by current morale; `sub_5E6187` -> `sub_5E985F`). | V | 2 |
| **A15** | **`ForceAttack` queue clearing:** Original clears the attacker's action queue before queuing `Attack`; GemRB appends behind existing actions (531 uses). | V | 2 |
| **A16** | **`PlaySequenceTimed` units & looping:** Original loops the animation for `int1` **seconds** and blocks; GemRB waits `int1` **ticks** without looping (`PlaySequenceTimed(25,4)` lasts 0.27 s instead of 4 s; 70 uses in `0208SK*`). | V | 2 |
| **A17** | **`LeaveParty` script cleanup:** Original clears `AREA`, `SPECIFICS`, `CLASS`, `RACE`, and `GENERAL` script slots and sends `Leaves` to each party member; GemRB resets only under `HasDPLAYER` (off for PST; 36 uses). | V | 2 |
| **A19** | **`SavePlace` implementation:** Bound to `SaveLocation` without a string arg, so saved position/facing is never stored and `ReturnToSavedPlace` goes to the old spot (15 uses). | V | 2 |
| **A20** | **`GlobalSetGlobal` direction & `FollowCreature`:** Original copies `Name1 <- Name2` (`Previous_Area <- Current_Area`); GemRB copies `Name2 <- Name1` (4 uses in `AR0201`–`0203`). `FollowCreature` is a no-op in PST but blocks the queue forever in GemRB (1 use, `0600THUG`). | V | 2 |

---

## 4. Global Rules, Progression, Death/Revival & `BALDUR.bcs`

*Death/Revival rules (`4A`) hook into Op 13 (`sub_4B5DCF`) and set `Game_Over` flags consumed by `BALDUR.bcs` (`4C`), which also relies on `LeaveParty` (`A17`).*

**Detailed refs:** [wp_baldur.md](wp_baldur.md), [wp6_rules.md](wp6_rules.md), [wp7_tables.md](wp7_tables.md), [pst_functions.md](pst_functions.md)

### 4A. Death, Revival & Game Over Rules

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **R2 / E29** | **Nameless One & companion death triggers (`sub_4B5DCF`):**<br>- Dying in Fortress of Regrets (`AR1200`/`AR1201`) increments `Death_Fortress` and sets `Game_Over = 4` once it exceeds `Fortress_Death_Counter`; dying in `AR1203`/`AR1204` sets `Game_Over = 4` immediately.<br>- If **Annah** (companion index 1) dies while `Pharod_Dead == 1` and `Know_Painted_Door < 2`, set `Game_Over = 3`. | V / S | 1 |
| **R-7** | **`Death` global counter:** Increment `GLOBAL "Death"` by 1 at every protagonist death (read by `DTRANS`, `DSERE`, `DAWAIT`, `DNORDOM`, `D0202P`, `DSKSCRAP`, and `AR1201` Fortress shadows). | V | 1 |
| **B2 / R5** | **`Game_Over == 7`:** Original displays death text `67295` (GemRB `BALDUR` maps 6 to `67295` instead of `QuitGame` end path). `0500GGRD` sets 7. Also verify original has no 7 in `HandleGameOverConditions`. | V / S | 1 |
| **R-8** | **`partyarea`/`partypoint` (`AR1800`):** GemRB dismisses the party on area load; EE uses those keys only on death (supersedes `B8`'s `AR1800` note). | V | 2 |
| **R-9, R-10** | **Revival presentation:** Play revival animation for state `35` and revival voice lines. | V | 3 |

### 4B. Progression, Rest, Stealth & Rule Tables

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **R-11** | **Mage-to-12 specialization:** After another specialization (`Specialist 9`), EE grants `INT +2` (GemRB `+1`), and jumping `6 -> 12` grants both bonuses in EE. | V | 2 |
| **R-12** | **Vhailor's 2nd weapon point:** Fighter level 13 in GemRB vs 14 in EE (EE itself has a Beamdog typo that never applies Vhailor's points — owner decision). | V | 2 |
| **R-13** | **Resting in "permission" areas:** In the 9 permission areas (original flags `6`), EE allows resting once no living non-party creature remains in the area; GemRB never allows it (`AR0402`: EE data allows rest). | V | 2 |
| **R-14** | **Hiding in shadows:** EE uses `Stealth vs d100` (`-20` at night in dark spots, no armor/luck penalty); GemRB scales by light level (~half chance by day). | V | 2 |
| **TB-2** | **Mage non-proficiency penalty (`CLSWPBON`):** EE `-5` vs GemRB `-4`. | V | 2 |
| **TB-3, TB-4** | **Proficiency & thief tables:** Proficiency rank 4 damage `+5` vs `+4`; Thief starting skill points `0` vs `40` (`THIEFSKL`, verify against original exe). | S | 2 |
| **Sec 4** | **Remaining PST-only engine rules & tables:** Audit `XPLIST`, `XPBONUS`, `HPCLASS`, `ABCLSMOD`, `SPLPROT`, `NUMWSLOT`, `ITEMEXCL`, `PSTCHAR`, `CPlanescape::IsSpriteInDark`, `LetMorteBeCreepy`, `GetGraceRingJoke`, and `R6` (`HandleSpecializationBonuses`). | S | 2 |

### 4C. `BALDUR.bcs` & Area Transitions

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **B7** | **Fortress of Regrets party dismissal:** GemRB runs it on any `AR0202` visit after `Pharod_Quest = 2` only for companions while holding `SkScrap`/`SkRegret`; original triggers at the `Fort_Port` exit with no item check, removes companions (`*EG.CRE`), and swaps `LimLim` -> `D_LimLim` (currently a no-op in GemRB). | V | 2 |
| **B4** | **Lady's Maze exit location:** Store `Maze_Exit_*` coordinates and reset `Modron_Cube` back to `1` on exit (GemRB always returns to `AR0200`). | V | 2 |
| **B5** | **Lady's Maze second entry:** Original sets `Game_Over = 1` (text `44963`); GemRB calls `QuitGame(0,0,0)` with no text. | V | 2 |
| **B1** | **Faction memberships:** Original keeps every `Join_*` membership (Chaosmen 1 or 3) as independent flags; GemRB uses one faction stat that flips every pass when two are set. | V | 2 |
| **B8** | **Missing `BALDUR` rules:** Companions leave at `AR3017 -> FR0502`, `Pregnant_Quest > 2` world map on Sigil exits, and `AR1203` slab facing. | S | 2 |
| **B3** | **Shadow movie trigger:** Play on first `AR0200`/`AR0206` visit, not on arrival at `FR0201`. | V | 3 |
| **B6** | **Foundry redirect:** Transition straight to `AR0513` instead of loading after `AR0512`. | V | 3 |

---

## 5. Spells, Projectiles & Plane Warping

*Depends on Sections 1 & 2. Plane Warping & Spell Keys (`5A`) is placed first because opcodes (`R1/E26`, `E11`, `E18`, `E24`) and spells (`S34`) depend on `S42`.*

**Detailed refs:** [spells.md](spells.md), [spell_expect.md](spell_expect.md), [spell_expect.json](spell_expect.json), [maps/projectiles.tsv](maps/projectiles.tsv), [wp_projectiles.md](wp_projectiles.md)

### 5A. Plane Warping & Spell Keys

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **R1 / E26** | **Spell warping by plane (`sub_4B245B` / `CGameEffectDamage::ApplyEffect`):** Check the *caster's* area and display the "spell warped" feedback string:<br>- **Carceri** (`AR0900`–`0902`, `AR0904`, `AR3015`, `AR3016`): Chromatic Orb, Fist of Iron, and Elysium's Tears roll **max dice**; Deathbolt gets `+1`; Iron Fist casters get max dice on all damage effects.<br>- **Baator** (`AR1000`, `AR1001`): Deathbolt gets `+6`; Iron Fist casters get `+12` flat bonus (instead of `+6`).<br>- **Negative Material Plane** (`AR1200`–`1204`): Deathbolt gets `+1`; Iron Fist casters get `+7` flat bonus. | V | 1–2 |
| **S34** | **Strength spells reverse in Carceri:** `sub_7BD15D` subtracts the Strength roll in `AR0900`–`0902`, `AR0904`, `AR3015`, `AR3016`. | V | 2 |
| **S42** | **Spell Key exemption (`CPlanescape::IsInCarceri` etc.):** Carrying `CARCERSK`, `BAATORSK`, or `NEGMATSK` disables the corresponding plane's warping checks for that creature (applies to R1, E26, S34, and Embalm E11). | V | 2 |

### 5B. Hardcoded Spells & Projectiles

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **S1** | **Abyssal Fury (`SPWI912`) does nothing:** SPL has no effects; logic lives in `CPsSpellAbyssalFury` (10 KB: picks creatures in range, moves them, applies death effect + caster-level-scaled damage, checks spell states). `gemprjtl.ids` lists `FURY`, but `fury.pro` is missing. | V | 1 |
| **S2** | **Blacksphere (`SPWI401`) missing projectile:** `bsphere.pro` is missing (`BSPHERE` row in `gemprjtl.ids` has no file). EE builds `CPsSpellBlacksphere` (`BLACK03`, `BLACK05`, `S041CAST`), providing projectile timing for the SPL's helpless/visual effects. | V | 1 |
| **S3 / S17 / E16** | **Power Word, Blind (`SPWI805`) broken & lands nothing:** Original (`CPsSpellPowerWordBlind::AIUpdate`) sorts creatures in range by current HP and spends a 100-HP pool from weakest up. Blindness (op 74) duration is chosen **once** from the pool in **seconds**: `<= 25` -> 160–400 s, `26–50` -> 80–200 s, `> 50` -> 16–40 s, plus pulse glow (op 9) and hit trigger. GemRB's `PWB.spl` (op 74 `p2 = 1`, `fx_set_blind_state`) uses **ticks** (151–390 / 71–190 / 16–45) per target's own HP and lands nothing in the suite. | V / S | 1 |
| **S4** | **Projectile spells skip attack roll:** Original (`sub_577BD4` / `sub_577E7C`; EE `CPlanescape::ProjectileRollToHit`) rolls `d20 + caster THAC0 + STR to-hit + DEX missile bonus` vs target AC for **Ice Knife, Bladestorm, Elysium's Tears meteors, and Spiritual Hammer** (Vampiric Touch roll is EE-only; original uses a plain projectile). GemRB skips the roll. | V | 1 |
| **S5** | **Traps `SPWI001`–`SPWI010` lack projectiles:** All point to projectile 271, but `gemprjtl.ids` has no row 270. EE assigns projectiles 271 and 291–299 (`spwi001`…`spwi010` in `projectl.ids`; `sub_559A5D` cases in original) alongside `CPlanescape::DoesTrapHitTarget`. | S | 1 |
| **S9** | **Celestial Host & Rune of Torment hang turn-based mode:** `CPsSpellCelestialHost` (15 KB) and `CPsSpellRuneOfTorment` (5 KB) are state machines with background swaps and screen flashes. GemRB's `chost`/`rotorm` hang the turn (Celestial Host busy after 25 s, world clock frozen 6 s; Rune of Torment stops game responding). | V | 1 |
| **S14** | **Howl of Pandemonium applies no stun or confusion:** Original creates op 45 stun (targets level `<= 2`) and op 128 confusion (level 3 up to caster's level), save vs spell, 50–300 s in code. GemRB's `hopand.pro` has no helper (only SPL visuals + caster missile protection). | V | 1 |
| **S15** | **Globe of Invulnerability duration & radius:** Original lasts `5 s x caster level` and every 51 ticks re-applies the SPL's 3-second protections to everyone within 120 px. GemRB lasts 3 s total and covers only the caster. | V | 1 |
| **S16** | **Power Word, Kill HP cap & targeting:** Original checks single target's HP at launch (`> 120` -> fizzle). GemRB's `pwkill.pro` is a radius-15 AoE with no HP check. | V | 1 |
| **S18** | **Hold Undead targeting, duration & saves:** Original affects 1–3 undead with `total HD <= caster level`, duration `5 x level + 5–20 s`, save allowed only for `HD >= 3`. GemRB holds 1 creature for 50 s with no save. | V | 1 |
| **S19** | **Pacify caps, filters & state tracking:** Original affects 2–8 enemies of `level <= 6`, excludes undead, lasts `5 x level + 40 s`, and uses op 186 to set status `0x400` so already-pacified targets aren't re-targeted. GemRB lasts 50 s with no target cap, level limit, undead check, or status bit. | V | 1 |
| **S20** | **Stygian Ice Storm missing confusion:** Original applies op 128 confusion (save vs spell, 10–35 s per target). | V | 1 |
| **S22** | **Elysium's Fires multi-burst:** Original spawns 8 fireballs at fixed offsets, radius 240 each, enemies only (targets near center take multiple hits). GemRB hits 1 creature once. | V | 1 |
| **S23** | **Elysium's Tears meteor count & splash:** Original fires `min(level, 10)` meteors, each with its own attack roll and a 1-fire-damage splash in radius 80. GemRB does 1 hit. | V | 1 |
| **S26** | **Call Lightning damage, radius & save:** Original deals `(level + 2)d8`, radius 120, save vs spell. GemRB deals `2d8`, radius 10, no save. | V | 1 |
| **S29** | **Blade Storm damage & attack roll:** Original deals `(level)d8` using an attack roll vs THAC0 11 with a `2d10` critical. GemRB deals `14d8` with a saving throw. | V | 1 |
| **S37 / E19** | **Ball Lightning & Adder's Kiss multi-hit (`op 196`):** Original Ball Lightning (`p2 = 1`) fires 1–4 balls (`4d12` / `5d4` / `2d6` / `2d4` electricity each); Adder's Kiss fires `level / 3 + 1` acid hits of `2d4`. GemRB fires one `4d12` ball and one `2d4` acid hit. | V | 1 |
| **S6** | **Meteor Storm Bombardment projectile:** `gemprjtl.ids` row 61 is `<stoned>` and `mswarm` is a placeholder; original uses `CPsSpellMeteorStormBombardment` (`METEO02/05/06`, `S061BEAM`, `S061ROCK`). | V | 2 |
| **S7** | **Strength spell cap inverted:** `fx_overlay` case 17 (`PSTOpcodes.cpp:906`) computes `bonus = Modified + bonus - limit` instead of `limit - Modified` (giving STR 19 on STR 16 + 5 with limit 18). EE's `CPsSpellStrength/ImprovedStrength/PowerOfOne::Fire` rolls class dice (priests/thieves `d6`, others `d8`, plus special cases) capped against 18 (GemRB uses `clssplab`). | V | 2 |
| **S8** | **Per-spell hardcoded effects audit:** Verify in GemRB whether helper SPLs/overlays cover EE's code-added ops: Howl of Pandemonium (stun 45 + tint), Stygian Ice Storm (confusion 128), Pacify (AC 0 + glow 8 + undead check vs GemRB hold 109), Ice Knife (THAC0 54), Conflagration (translucency 66), Shroud of Shadows (AC 0), Fire and Ice, Ignus' Fury (damage 12), Hold Undead (109 + undead check), Swarm Curse (op 215 visual). | S | 1–2 |
| **S21** | **Fire and Ice double burst:** Original bursts twice (`3d6` magic fire, then `3d6` magic cold), radius 360, excluding caster. GemRB bursts once. | V | 2 |
| **S24** | **Shroud of Shadows stats & save:** Original has no save, lasts 10–20 s, grants stealth `+10`, AC `+3`, translucency, and overlay 5. GemRB lasts 150 s with a saving throw against the caster's own buff and gives stealth 0 for 0 s. | V | 2 |
| **S25** | **Ax of Torment high-level table & hold duration:** Missing `level > 8` table (`5d8` fire, `6d8` cold, teleport, petrification, `8d8`); hold lasts 100 s instead of 3–10 s. | V | 2 |
| **S27** | **Ignus' Fury scaling:** Adds flat `+16` instead of `+ caster level`. | V | 2 |
| **S28** | **Swarm Curse spread:** Doesn't spread; original uses radius `36 x min(level, 13)`, `1d4 + level / 3`, save vs spell. | V | 2 |
| **S30** | **Tasha's Laughter target filter & INT cutoff:** Original targets males, non-undead, on **any** side, and a creature with `INT <= 4` terminates the spell for remaining targets. GemRB hits females, undead, and only enemies. | V | 2 |
| **S31 / E14** | **Minor Embalming target restriction & sequence:** Original fizzles unless target is undead or has the immortal flag (`+3342`). GemRB also rejects op 138 sequence `27`. | V | 2 |
| **S32** | **Multi-fire extra casts (`CPlanescape::MultiFireSpell`):** Ice Knife (`+min(4, (L-4)/2+1)`) and Force Missiles / Elemental Strike (`+min(6, (L-7)/2)`) set a counter on the caster for extra clicks. Missing in GemRB. | V / S | 2 |
| **S33** | **Force Missiles & Ice Knife splash / min headers:** Force Missiles lack level-damage splash (radius 72, save vs spell negates) and level-7 min header. Ice Knife lacks `1d4 + THAC0 -2` splash and level-3 min header. | V | 2 |
| **S35** | **Spell radius & filter mismatches:** Celestial Host (`1000` vs `400` px + no fizzle when no enemy), Rune of Torment (`600` vs `400` px), Meteor Storm (`256` vs `400` px), Desert Hell (`2160` vs `400` px). | V | 2 |
| **S39** | **Blood Bridge drain amount:** Drains 2 HP instead of `caster level + 2` (factory case 226 sets op 192 `p1 = level + 2`). | V | 2 |
| **S40** | **Faerie Fire duration:** Lasts 20 s instead of `20 s x caster level` (factory case 259). | V | 2 |
| **R-16** | **Caster-level spell durations (`spldurat.2da`):** Litany of Curses is `10 x L` uncapped in EE vs `5 x L` max 30 in GemRB; also align small discrepancies in Friends, Blur, Tasha's, Blacksphere, Zerthimon op 301, and `SPWI602`. | V | 2 |
| **PR-1, PR-2** | **Projectile radii:** `NTOKEN` hold area radius is 240 in EE (64 in GemRB); `SPIN106` fear aura is 360 in EE (720 in GemRB). | V | 2 |
| **PR-3** | **Bless area filter:** Verify area target filter against EE. | S | 2 |

### 5C. Spell Visuals, Movies & Tables

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **S10** | **Unplayed spell animations/sounds:** Assets referenced by EE spell classes but absent from GemRB's `.pro`/helper files: Celestial Host (25), Missile of Patience (19), Rune of Torment (8), Abyssal Fury (10), Fire and Ice (6), Chain Lightning Storm (9), Bladestorm (5), Death Bolt (5), etc. (see `spells.md`). | V | 3 |
| **S11** | **Wrong asset filenames in GemRB PST tables:** `damage.2da` requests `T_FIRE1` (PST has `T_FIRE01`/`T_FIRE02`, breaking burn visuals on 8 fire spells); `arrow.pro`/`arrowhvy.pro` request `ARARROW` (not in PST); `dbolt.pro` requests `DBOLT` BAM (not in PST). | V | 3 |
| **S36** | **Missing spell movies:** Play `RUNE` (Rune of Torment), `METEOR` (Meteor Storm), and `CONFLAG` (Conflagration). (`DRAGON` and `CANNON` already play). | V | 3 |

---

## 6. Items, Stores, Loot & Audio/Voices

*Standalone data, store, and audio subsystems (note `ST-4` interacts with `AttackedBy` in Section 3B).*

**Detailed refs:** [wp_items_stores.md](wp_items_stores.md), [wp9_ee_data.md](wp9_ee_data.md), [wp_voices.md](wp_voices.md)

### 6A. Items, Stores & Loot Tables

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **TB-1** | **Random loot (`RNDTRE01`–`05`, 884 CRE slots):** GemRB rolls original BIF's BG-style `RNDTREAS` (44 of 60 items don't exist in PST); replace with PST loot table (trinkets, charms, scrolls, gold). | V | 2 |
| **ST-1** | **Infinite-stock store sell cap:** Selling an item the store stocks infinitely pays at most `20%` in EE vs full `80%` in GemRB (275 entries across 34 stores). | V | 2 |
| **ST-4** | **Failed store theft:** EE (PST only) sends `ATTACKEDBY` to the store owner; GemRB only sends `StealFailed` (`StealIsAttack = 0`). | V | 2 |
| **IT-1** | **Anarchist faction usability (`factions.2da`):** Set bit `0x200` (currently `0` in GemRB; 12 items an Anarchist cannot use in EE). | V | 2 |
| **WP9** | **EE data differences:** Triage remaining ~5 real data changes among EE's 734 modified SPL/ITM files (593 color-only, ~30 renumbered, 5 per-level spells). | V | 2–3 |
| **ST-2, ST-3** | **Store pricing formulas:** Charisma `x` vs `+` modifier on store prices, and charged-item pricing. | V | 3 |
| **R-15** | **Companion item quips:** Implement Grace and Morte item quips. | V | 3 |

### 6B. Voices & Audio

| ID | Issue & Target Behavior | Status | Sev |
|---|---|---|---|
| **V1** | **Weapon swings vs spell casting voice lines (`A11-1`):** PST slots `14–18` are damage/spell-casting lines; original plays slots `15–17` when a **spell is cast** and nothing on weapon swings. GemRB plays `14–17` by attack stance on swings and nothing on cast. | V | 2 |
| **V2** | **Location comments on actions (`A11-5`):** Hide, spell disruption, and trap setting play slots `70–72` (Negative Plane / Carceri / Curst lines in PST); original never plays them for those actions (1-line fix in `pst/vcremap.2da`). | V | 2 |
| **V3** | **Selection line ordering (`A11-3`):** Play selection lines **in order**, with rare lines starting at the **10th** consecutive click (GemRB picks randomly, goes rare after 4 clicks, plus `5%` random rare). | V | 3 |
| **V4** | **Sound frequency sliders (`A11-4`):** Level 3 = `40%` (GemRB `50%`), action level 2 = `20%` (GemRB once per selection). | V | 3 |
| **V5** | **Hit reaction slots (`A11-2`):** Taking damage plays slot `14` or `18` at `50/50` (GemRB only plays `18`). | V | 3 |
| **A11-7** | **Lower Ward (`AR0500`) area comment:** GemRB `pst/comment.2da` uses flag `0x2`, while `AR0500` has `0x8` (`EE HandleAmbiance`). | V | 3 |
| **A11-6** | **Monster battle cry cooldown:** Add original's shared timer and 90-tick cooldown for monsters. | V | 3 |

---

## 7. Reference: Already Fixed (`F`) & Confirmed Parity (`P`)

Do not re-implement or revert the items below:

* **Already Fixed (`F`):** `A12` (`TakePartyItem` takes 1 unit, commit `97267f33d`), `A18` (`DestroyItem` target object, commit `97267f33d`), `T1` (`NearbyDialog` 700 px no-LOS check), `T2` (`MoraleLT/GT` current morale `+1831`), `T3` (`NotStateCheck` inversion), `T4` (`RandomNum/LT` `0..Range`), `T5` (`GlobalTimerExpired` expired at `0`), `T6` (`TimeGT/LT` schedule hours), `T7` (`NearSavedLocation` plain pixel range).
* **Confirmed Parity / Keep As-Is (`P`):** `S12` (`SPBOOM`/`SPRING` missing in original too), `S13` (`CANNON`/`DRAGON`/`CONFLAG.2da` optional subtitles), `S38` (Chain Lightning Storm, Cloudkill, Mechanus' Cannon, Death Bolt, Missile of Patience damage), `E6` (Op 177 GemRB-only `stories.spl`), `E22` (Op 195 Tint screen), `E32` (Ops 6, 39, 42, 44, 45, 73, 98, 128), `Sec 7` (Ops 150, 197, 198, 199, 212 data-only in original), `A3` (Triggers `0x4070`, `WatchMe`, `0x40C0`, `0x40FF` always false), `A4` (`FollowPath` unused), `A9` (`IncrementGlobalOnce` `NoNewVariables = 1`), `SE-3` (Response weights exact in GemRB), `D-5/6/7` (Dialogue whitespace, statement splitting, symbols), `SP-0` (Ignored spawn keys), `C-9, C-12, C-16, C-17, C-20, C-22` (Iron Fist to-hit, weapon damage, MR roll, death threshold, PC morale immunity, spell disruption), `P-1, P-2, P-4, P-5` (Feature-block fields, shared rolls, level range, timing modes/units).