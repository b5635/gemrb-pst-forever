# PST parity findings

What the investigation of 2026-11-18 found, ranked within each area. Sources and method are in
[README.md](README.md); the plan to fix them is [PARITY_PLAN.md](../../PARITY_PLAN.md).

**Status:** **V** = verified in the original or EE code *and* in GemRB's source. **S** = strong suspicion from
the code, still to confirm in game. **P** = parity already holds (written down so nobody "fixes" it).
**Sev:** 1 = gameplay is wrong or a feature does nothing, 2 = wrong numbers or wrong detail, 3 = looks or sounds only.

Every reference to the original game means Torment.exe 1.1 with Fixpack 4.13 and Unfinished Business 4.12, at
`C:\Program Files (x86)\Black Isle\Torment`. Addresses (`sub_…`) refer to that exe; `CPs…`/`CPlanescape::…` names
are PST:EE symbols.

---

## 1. Hardcoded spells (the biggest gap)

PST does a lot of its spellcasting in engine code rather than in data. The projectile decoder (original
`sub_559A5D`, 285 cases; EE `CProjectile::DecodeProjectile`) builds a dedicated object for 36 spells
(`CPsSpellIceKnife`, `CPsSpellPowerWordBlind`, …) plus `CPSTSpellMechanusCannon`, `CPSTSpellSpiritualHammer`
and `CPSTSpellCallLightning`. These objects choose targets, roll to hit, add effects that are not in the
SPL, and play their own animations and sounds. GemRB stands in for each one with a `.pro` in
`gemrb/unhardcoded/pst` plus helper SPLs. Per-spell detail is in [spells.md](spells.md).

| # | Finding | Status | Sev |
|---|---|---|---|
| S1 | **Abyssal Fury (SPWI912) does nothing.** Its SPL has no effects; everything lives in `CPsSpellAbyssalFury` (10 KB: picks creatures in range, moves them, applies a death effect and damage scaled by caster level, checks spell states). GemRB has no `fury.pro`; `gemprjtl.ids` lists `FURY`, but no file exists. | V | 1 |
| S2 | **Blacksphere (SPWI401) has no projectile.** `bsphere.pro` is missing (the `BSPHERE` row in `gemprjtl.ids` has no file). EE builds `CPsSpellBlacksphere` (`BLACK03`, `BLACK05`, `S041CAST`). The SPL's own effects (helpless, visuals) may still land, but without the projectile's timing. | V | 1 |
| S3 | **Power Word, Blind (SPWI805) is wrong and lands nothing in the suite.** Original logic (`CPsSpellPowerWordBlind::AIUpdate`): sort the creatures in range by current HP and spend a pool of 100 HP from the weakest up. Blindness (op 74) duration depends on the pool: ≤25 → 160–400 s, 26–50 → 80–200 s, >50 → 16–40 s (seconds; corrected in round 3, see spell_expect.md). A pulse glow (op 9) is added and a hit trigger is sent. GemRB's `PWB` helper applies blindness with no HP pool, and the suite saw no change (in both turn-based and real-time). | V (logic) / S (why nothing lands) | 1 |
| S4 | **Projectile spells skip the attack roll.** `CPlanescape::ProjectileRollToHit` rolls d20 + caster THAC0 + STR to-hit + DEX missile bonus against the target's AC. It is used by Ice Knife, Bladestorm, Elysium's Tears meteors and Vampiric Touch (`CPsSpellVampiricTouch`). GemRB applies these effects without an attack roll. | S | 1 |
| S5 | **Traps SPWI001–SPWI010 have no projectile in GemRB.** All of them point at projectile 271, but `gemprjtl.ids` has no row 270. EE gave them projectiles 271 and 291–299 (`spwi001`…`spwi010` in `projectl.ids`); in the original they are `sub_559A5D` cases. Combined with `CPlanescape::DoesTrapHitTarget` (EE), trap spells may not fire or hit correctly. | S | 1 |
| S6 | **Meteor Storm Bombardment's projectile is a placeholder.** `gemprjtl.ids` row 61 is `<stoned>`, and `mswarm` is GemRB's approximation. The original uses `CPsSpellMeteorStormBombardment` (`METEO02/05/06`, `S061BEAM`, `S061ROCK`). | V | 2 |
| S7 | **Strength spells: GemRB's cap is inverted.** `fx_overlay` case 17 (`PSTOpcodes.cpp:906`) caps with `bonus = Modified + bonus - limit`; it should be `limit - Modified`. For STR 16 with a +5 roll and a limit of 18 it gives +3 (STR 19). EE's `CPsSpellStrength/ImprovedStrength/PowerOfOne::Fire` rolls class-based dice (priests and thieves d6, others d8, with special cases) and limits against 18. GemRB uses `clssplab` dice. | V | 2 |
| S8 | **Effects that EE classes add in code, to check one by one in GemRB:** Howl of Pandemonium (stun 45 + screen tint), Stygian Ice Storm (confusion 128), Pacify (AC 0 + glow 8, and EE checks undead; GemRB uses hold 109), Ice Knife (THAC0 54), Conflagration (translucency 66), Shroud of Shadows (AC 0), Fire and Ice, Ignus' Fury (damage 12), Hold Undead (109 + undead check), Swarm Curse (op 215 visual). Some are already covered by GemRB helper spells or overlays (Strength is, through overlay 17), so the "code ops" column in spells.md is a to-do list, not a verdict. | S | 1–2 |
| S9 | **Celestial Host hangs the turn** (busy after 25 s, world clock frozen 6 s) and **Rune of Torment stops the game answering**. EE's classes are large state machines (`CPsSpellCelestialHost` 15 KB, `CPsSpellRuneOfTorment` 5 KB) with a background swap and screen flashes. GemRB's `chost`/`rotorm` versions do not end cleanly in turn-based mode. | V (suite) | 1 |
| S10 | **Many spell animations and sounds are never played.** Assets that EE classes reference and no GemRB file does: Celestial Host 25, Missile of Patience 19, Rune of Torment 8, Abyssal Fury 10, Fire and Ice 6, Chain Lightning Storm 9, Bladestorm 5, Death Bolt 5, among others (see spells.md). | V | 3 |
| S11 | **Wrong file names in GemRB's PST tables.** `damage.2da` asks for `T_FIRE1` (PST has `T_FIRE01`/`T_FIRE02`), so there is no burn animation on fire damage (8 spells in the suite). `arrow.pro`/`arrowhvy.pro` ask for `ARARROW` (not in PST), and `dbolt.pro` asks for a `DBOLT` BAM (PST has none). | V | 3 |
| S12 | `SPBOOM`/`SPRING` (in `areapro.2da`) are Baldur's Gate leftovers that the **original exe also names**: it misses them silently too. | P | — |
| S13 | `CANNON.2da`, `DRAGON.2da`, `CONFLAG.2da` "missing": harmless. `Interface::PlayMovie` looks for an optional subtitle table named after the movie. | P | — |

## 2. Effect opcodes

The original builds effects in `sub_4A5C21`: 202 opcodes, 0–212, with no 61 and no 176–185. Each opcode's
`ApplyEffect` is slot 2 of its vtable and has been decompiled. EE renamed and renumbered PST's own opcodes, and
aligning the same spell in both games shows what each one became. Full table: [opcodes.md](opcodes.md).

| # | Finding | Status | Sev |
|---|---|---|---|
| E1 | **Op 82 (Litany of Curses) is the wrong effect in GemRB.** Original `sub_4C2218` queues script action 10 (`Enemy()`) on the target for the effect's duration; EE calls it `CGameEffectInciteRunningAttack`. GemRB treats op 82 as `SetAIScript`, with a hack for `spin101` that permanently installs `SPIN101.bcs` in the target's override slot. | V | 1 |
| E2 | **Op 209 (Soul Exodus, `FANGMIRR.itm`) is not implemented.** GemRB's `fx_hostile_image` only logs "not implemented"; the original `sub_4D8A07` is 124 lines (skips dead creatures and creatures with state 0x800, spawns `SE10FIZZ`, …). | V | 1 |
| E3 | **Op 186 (SetStatus) mishandles −1.** Original `sub_4D08CA`: parameter1 of 1 sets the bits, −1 clears them, anything else does nothing; with timing 1 it changes both base and derived state. GemRB sets the bits for any non-zero parameter1. Latent: PST's data only uses 1. | V | 3 |
| E4 | **Op 207 (GemRB "StopAllAction")** is a game freeze in the original (`sub_4D7A0E` → `sub_7BB610`; EE `CGameEffectFreezeGame`, `CPlanescape::SetGameFreeze` 8.7 KB). GemRB uses `TimeStop` and has its own FIXME. Used by Tasha's Laughter, Desert Hell and Bladestorm. | S | 2 |
| E5 | Opcodes GemRB itself flags (TODO/FIXME/"not implemented") that PST data uses: ToHitModifier 54 (93 uses), Overlay 201 (25), Sparkle 41, FindTraps 150, Invisible 20, PlayMovie 152. Each needs a side-by-side read of the original handler. | S | 2 |
| E6 | Op 177 (ApplyEffect) is not in the original at all; only GemRB's own `stories.spl` uses it. | P | — |

## 3. Scripting

147 actions and 102 triggers are used by PST's scripts and dialogs. The original's action handlers come
from the creature switch `sub_76A7EA` (byte table at `0x76D476`, with 313 special-cased) plus the base switch
`sub_44B099`. **Every action the scripts use exists in the original.** Full lists: [scripting.md](scripting.md).

| # | Finding | Status | Sev |
|---|---|---|---|
| A1 | **`EscapeAreaRunning` (313) is missing in GemRB**: "Unknown Action", 103 uses in 63 scripts (ghosts, cutscene walkers). The original handles it in `sub_76A7EA`. Fixpack added the `action.ids` line; the engine always had the action. | V | 1 |
| A2 | **Overloaded ids.** PST gives these actions a second, longer form: `JoinPartyEx(JoinGroup)` 136 uses (73 with 1), `MoveToObjectEx(Timeout)` 113, `RunAwayFromEx(NoAttacks)` 874, `DeactivateEx(RenderMode)` 82, `PolymorphEx(RangeModes)` 23, `FullHealEx` 3 (GemRB: "not sure what's different"), `StartCutSceneEx` 2. GemRB maps both names to one function; `JoinParty`, `MoveToObject` and `Deactivate` read no extra parameter. | V (no parameter read) / S (effect) | 2 |
| A3 | Triggers 0x4070, `WatchMe` 0x4092, 0x40C0 and 0x40FF (UB's `BALDUR.bcs`, `0205POS*`) have no handler in the original's trigger code (`sub_453258`, `sub_778529`): they are always false there, as in GemRB. | P | — |
| A4 | `FollowPath` (37): GemRB has no function, but no PST script uses it. | P | — |

## 4. Rules and engine behaviour (not yet compared)

EE's PST-only functions are the list of hardcoded rules to compare with GemRB, 140 of them in
[pst_functions.md](pst_functions.md). The largest:

| Area | EE function | GemRB counterpart |
|---|---|---|
| Nameless One death and revival | `CGameArea::HandleNamelessDeath` (12 KB), `GetNamelessRevivalReaction` | `IniSpawn::SetNamelessDeath*` (much smaller) |
| Level-up bonuses | `CPlanescape::HandleNamelessBonuses` (5 KB), `AssignFighterProficienciesOnLevelUp` | GUIScripts `pst/LevelUp.py` |
| Casting | `CGameSprite::SpellPST`, `SpellPointPST`, `CGameAIBase::ForceSpellPST`, `ForceSpellPointPST`, `CPlanescape::MultiFireSpell` | core `Spell`/`Scriptable` casting |
| Projectiles | `ProjectileRollToHit`, `IsProjectileTargetAffected`, `DoesTrapHitTarget` | `Projectile.cpp` |
| Damage | `EffectDamageDecodeHitSound` | `fx_damage`, `damage.2da` |
| Rest | `CGameArea::PSTCanRestParty` | `Game::CanPartyRest` |
| Stealth and light | `CPlanescape::IsSpriteInDark` | — |
| Flavour | `LetMorteBeCreepy`, `GetGraceRingJoke` | — |

Rule tables EE moved out of the exe (`XPLIST`, `XPBONUS`, `HPCLASS`, `CLSWPBON`, `ABCLSMOD`, `SPLPROT`,
`NUMWSLOT`, `ITEMEXCL`, `PSTCHAR`, …) hold numbers to compare with GemRB's tables. EE's `THIEFSKL` starts
thieves at 0 where GemRB's starts them at 40, for example; which value the original uses still has to be
confirmed in the original exe, because some of EE's tables are BG2-EE defaults.

## 5. Data: what EE changed

734 SPL/ITM files carry different effects in EE than in the original + Fixpack + UB (`opmap.json` →
`changed`). Examples: `IRON3.itm` confusion → stun; Tasha's Laughter's to-hit moved to EE's op 278. These are
Beamdog data fixes, not GemRB engine gaps. Sorting them into "real bug fixes we want as an option" and
"EE redesign" is a separate pass.

---

# Round 2 (2026-11-18): opcode handlers, rules, actions

## 6. Engine rules GemRB lacks

| # | Finding | Status | Sev |
|---|---|---|---|
| R1 | **Spell warping by plane is missing.** The original damage effect (`sub_4B245B`; EE `CGameEffectDamage::ApplyEffect`) checks the *caster's* area. In **Carceri** (AR0900–0902, AR0904, AR3015, AR3016) Chromatic Orb, Fist of Iron and Elysium's Tears roll maximum dice, and Deathbolt gets +1. In **Baator** (AR1000, AR1001) Deathbolt gets +6. In the **Negative Material Plane** (AR1200–AR1204) Deathbolt gets +1. A caster under **Iron Fist** gets a flat bonus on every damage effect: 6 normally, 7 or 12 where Deathbolt is warped, and maximum dice in Carceri. Each case shows a "spell warped" feedback string. TransferHP (192) and Embalming (206) have their own plane rules. GemRB has no plane logic at all. | V (code) | 1 |
| R2 | **The Nameless One's death rules are missing.** In the original Death effect (`sub_4B5DCF`), when the protagonist dies in the Fortress of Regrets (AR1200/AR1201), `Death_Fortress` goes up by one and `Game_Over` becomes 4 once it passes `Fortress_Death_Counter`; dying in AR1203/AR1204 sets `Game_Over` 4 at once. If **Annah** (companion table index 1, not Pharod: corrected in round 5, E-013) dies while `Pharod_Dead` is 1 and `Know_Painted_Door` < 2, `Game_Over` becomes 3. GemRB's `baldur.bcs` *reacts* to `Game_Over` 1–6, but nothing *sets* 3 or 4: the area INIs don't (checked AR1200/1201/1203), and GemRB only reproduces `PM_KILLED`. So the Fortress death limit and the Pharod game-over never happen. | V (code) / S (game) | 1 |
| R3 | **TransferHP (op 192) is much simpler in GemRB.** The original/EE handler (`sub_4D1C49`, 793 lines) has modes 0–3 (mode 3 takes a percentage), special cases for Sensory Touch (SPIN104), Blood Bridge (SPWI204) and Vampiric Touch (SPWI309; HP above maximum become a temporary max-HP effect, op 18), plane warping, a saving throw and feedback strings. GemRB's `fx_transfer_hp` uses its own mode numbers (0/3, 1/4, 2) with none of those special cases. | V | 2 |
| R4 | **Pain Mirror / damage reflection** (spell state 0xB6 = 182) is handled inside the damage effect: random 1d5 rolls reflect damage back to the attacker. GemRB does Pain Mirror in `fx_overlay` case 3; whether the numbers match is unchecked. **Superseded by E24** (original: a reflection counter, every enemy within 120, magic damage). | V | 2 |
| R5 | `Game_Over` 7 exists in EE's `HandleGameOverConditions`; GemRB handles 1–6. Check that the original has no 7. | S | 3 |
| R6 | GemRB implements the Nameless One's specialist bonuses (`GUIREC.py:830 HandleSpecializationBonuses`) like `CPlanescape::HandleNamelessBonuses`; the numbers still need checking. | P? | — |

## 7. Opcodes that do nothing in the original

`ApplyEffect` of these is an empty "done" in the original (vtable slot 2; no other override does real work):
**150 FindTraps, 197 MultipleVVC, 198 ModifyGlobalVariable, 199 ChangeBackground, 212 SpeakWithDead**. In PST they
are data that the hardcoded projectile objects read (Speak with Dead lives in `CProjectileSpeakWithDead`). In
PST's own data only GemRB's helper files use them (`chost.spl`, `dbolt.spl`, `lstorm2.spl`, `bstorm2.spl`,
`dhell.spl`, `speak.eff`; `detect.spl`/`findtrap.spl` are GemRB's shared files), so GemRB treating them as live
effects is a GemRB design choice, not a parity bug. **P.** Keep this in mind when porting: a spell's SPL may list
these as data for its projectile.

## 8. PST-only branches inside generic effects

EE's effect classes have `ENGINE_MODE == 3` (PST) branches; each is PST behaviour to compare with GemRB
(`fxspecial.py`, `fxspecial.json`). All **S** until compared:

| Op | Effect | PST branch (EE) |
|---|---|---|
| 6 | CHR | dice-based amount (parameter dice) when the effect has a caster |
| 9 | ColorGlowPulse | PST-specific handling |
| 45/128 | Stun | PST sets only the state bit: no extra flag, no portrait icon 55 |
| 54 | THAC0 | PST limits (set mode capped at 25) |
| 73 | DamageMod | PST: *set*, capped at 20 |
| 86–89 | Resist slashing/crushing/piercing/missile | PST: no cap at 150 |
| 128 | Confusion | PST adds a glow (op 9) sub-effect |
| 130 | Bless | PST: on non-party creatures it also changes morale |
| 146/148 | CastSpell(Point) | PST casts through a PST-specific queue |
| 26 | RemoveCurse | PST mode 1: removes op 381 (Jumble Curse) effects as well |
| 39 | Sleep | PST adds op 162 sub-effect; `I001ZZZZ` animation |
| 134 | Petrification | `MULTIJ` handling |
| 17 | Heal | special case `SPIN822` |
| 196 | Special | Adder's Kiss (`SPWI201`), `S019ACID`, `S031DELC`, `SP62RDED` |
| 201 | AddAttachedObject (overlays) | per-spell special cases for 16 spells (Shield, Armor, Prot. from Evil, Flamewalk, …), Carceri warping |
| 203 | Curse | spell state 127 |
| 206 | Embalming | spell state 135, plane rules |

## 9. Scripting: the extra parameters, read in the original

| Action | Original behaviour of the extra parameter | GemRB |
|---|---|---|
| `MoveToObjectEx(Timeout)` (22) | `sub_785E47`: when the parameter is non-zero it is a countdown, lowered on each update; below 2 the action gives up | ignored: the move never gives up |
| `JoinPartyEx(JoinGroup)` (19) | `sub_7A0423`: when non-zero it calls an extra party-group join (`sub_4089DC`) | ignored |
| `PolymorphEx(..., RangeModes)` (146) | the second parameter is stored on the creature (byte +1991) | ignored |
| `RunAwayFromEx(NoAttacks)` (29), `DeactivateEx(RenderMode)` (125), `FullHealEx` (305), `StartCutSceneEx` (310) | not found yet in the handlers (305/310 go to the base switch) | — |

# Round 3 (2026-11-18): every hardcoded spell read in the original (WP1)

Full per-spell detail: [spell_expect.md](spell_expect.md) (human) and [spell_expect.json](spell_expect.json) (suite).
Address maps: [maps/projectiles.tsv](maps/projectiles.tsv). Corrections to round 1: S3's durations are seconds, not
ticks; S4 is now **V** (the original's roll is `sub_577BD4` / `sub_577E7C`, used by Ice Knife, Blade Storm, Elysium's
Tears, Spiritual Hammer); Vampiric Touch's roll is EE only (the original builds a plain projectile).

## 10. New spell findings

| ID | Finding | Status | Sev |
|---|---|---|---|
| S14 | **Howl of Pandemonium applies neither stun nor confusion.** The original creates op 45 stun (targets of level ≤ 2) and op 128 confusion (level 3 up to the caster's), save vs spell, 50–300 s, in code. GemRB's `hopand.pro` has no helper: only the SPL's visuals and the caster's missile protection. | V | 1 |
| S15 | **Globe of Invulnerability lasts 3 s and covers only the caster.** The original globe lives 5 s per level and every 51 ticks re-applies the SPL's 3-second protections to everyone within 120. | V | 1 |
| S16 | **Power Word, Kill has no 120-HP limit and hits an area.** The original checks the single target's HP at launch (> 120 → fizzle). GemRB's `pwkill.pro` is a radius-15 area with no HP check. | V | 1 |
| S17 | **Power Word, Blind's blindness is ~15× too short in GemRB.** `PWB.spl` op 74 uses GemRB's p2 = 1 hook (`fx_set_blind_state`), which adds 151–390 / 71–190 / 16–45 **ticks** by each target's own HP; the original uses **seconds** (160–400 / 80–200 / 16–40) chosen once from the pool. | V | 1 |
| S18 | **Hold Undead holds one creature, 50 s, no save.** Original: 1–3 undead, total HD ≤ caster level, 5 × level + 5–20 s, save only for HD ≥ 3. | V | 1 |
| S19 | **Pacify: fixed 50 s, no target cap, no level limit, undead not excluded, no "already pacified" bit.** Original: 2–8 enemies of level ≤ 6, not undead, 5 × level + 40 s, op 186 sets status 0x400 to stop repeats. | V | 1 |
| S20 | **Stygian Ice Storm lacks its confusion** (op 128, save vs spell, 10–35 s per target). | V | 1 |
| S21 | **Fire and Ice bursts once.** The original bursts twice: 3d6 magic fire, then 3d6 magic cold, radius 360, the caster excluded. | V | 2 |
| S22 | **Elysium's Fires hits one creature once.** Original: 8 fireballs at fixed offsets, radius 240 each, enemies only; a creature near the centre can take several. | V | 1 |
| S23 | **Elysium's Tears: one hit instead of min(level, 10) meteors**, each with its own attack roll and a 1-fire splash in 80. | V | 1 |
| S24 | **Shroud of Shadows: 150 s with a saving throw** against the caster's own buff, stealth 0 for 0 s. Original: no save, 10–20 s, stealth +10, AC +3, translucency, overlay 5. | V | 2 |
| S25 | **Ax of Torment's high-level table is missing** (level > 8: 5d8 fire, 6d8 cold, teleport, petrification, 8d8). GemRB's hold lasts 100 s instead of 3–10 s. | V | 2 |
| S26 | **Call Lightning: 2d8, radius 10, no save** instead of (level + 2)d8, radius 120, save vs spell. | V | 1 |
| S27 | **Ignus' Fury adds a flat +16** instead of + caster level. | V | 2 |
| S28 | **Swarm Curse doesn't spread** (original: radius 36 × min(level, 13), 1d4 + level/3, save vs spell). | V | 2 |
| S29 | **Blade Storm: 14d8 with a save** instead of (level)d8 with an attack roll vs THAC0 11 and a 2d10 critical. | V | 1 |
| S30 | **Tasha's Laughter hits women, undead and only enemies.** Original: males, not undead, any side; a creature with INT ≤ 4 ends the spell for the rest (a quirk in both games). | V | 2 |
| S31 | **Minor Embalming works on anyone.** Original: only undead or creatures with the immortal flag (+3342), else fizzle. GemRB also rejects op 138 sequence 27. | V | 2 |
| S32 | **Multi-fire spells give no extra casts.** Ice Knife (+min(4, (L−4)/2+1)) and Force Missiles / Elemental Strike (+min(6, (L−7)/2)) set a counter on the caster for extra clicks (`CPlanescape::MultiFireSpell`). | V (EE) / S (orig) | 2 |
| S33 | **Force Missiles have no level-damage splash** (72 radius, save vs spell negates), and no level-7 minimum header. Ice Knife has no 1d4 + THAC0 −2 splash and no level-3 minimum. | V | 2 |
| S34 | **Strength spells reverse in Carceri.** `sub_7BD15D`: in AR0900–0902, AR0904, AR3015, AR3016 the roll is subtracted (with a `CARCERSK` check). Extends R1. | V | 2 |
| S35 | **Radius and filter mismatches:** Celestial Host 1000 vs 400 and no fizzle when no enemy; Rune of Torment 600 vs 400; Meteor Storm 256 vs 400; Desert Hell 2160 vs 400. | V | 2 |
| S36 | **Movies the original plays and GemRB doesn't:** RUNE (Rune of Torment), METEOR (Meteor Storm), CONFLAG (Conflagration). DRAGON and CANNON are already played by GemRB helpers. | V | 3 |
| S37 | ~~Ball Lightning does nothing in the original~~ **Corrected in round 4 (E19):** its casting effect op 196 p2 1 fires 1–4 balls (4d12 / 5d4 / 2d6 / 2d4 electricity each); GemRB always fires one 4d12 ball. | V | 1 |
| S38 | **Chain Lightning Storm, Cloudkill, Mechanus' Cannon, Death Bolt, Missile of Patience damage:** match. | P | — |
| S39 | **Blood Bridge drains 2 HP instead of caster level + 2** (factory case 226 sets op 192's p1 to level + 2). | V | 2 |
| S40 | **Faerie Fire lasts 20 s instead of 20 s × caster level** (factory case 259). | V | 2 |
| S42 | **Plane warping has an exemption:** carrying the plane's Spell Key item (`CARCERSK`, `BAATORSK`, `NEGMATSK`) turns the Carceri / Baator / Negative Material checks off for that creature (`CPlanescape::IsInCarceri` etc.). Applies to R1, S34 and Embalm's plane rules. | V | 2 |
| S41 | **Acid Storm's damage lands after 2 s instead of 20 s** (factory case 247, op 12 delayed 20). Check GemRB's delay unit for timing 4. | S | 3 |

## 11. Opcode findings, round 3 (detail in [wp2_opcodes.md](wp2_opcodes.md))

| ID | Finding | Status | Sev |
|---|---|---|---|
| E7 | **Curse (op 203) improves saving throws in GemRB**: it subtracts p1 from the save target numbers; the original adds it (worse saves). Prayer hands this effect to every enemy. | V | 2 |
| E8 | **Effect damage dice ignore the target's luck.** The original rolls each die minus the target's luck (`sub_82015B`); GemRB rolls the dice once, unlucked, when the effect is queued. | V | 2 |
| E9 | **Prayer (op 204) is an aura in the original**: every 5 s, everyone within 720 of the caster gets Bless or Curse for 6 s. GemRB applies 60 s once to the whole map. | V | 2 |
| E10 | **Iron Fist (op 208) gives no to-hit in the original**: +6 damage on fist attacks only (animation 50), max dice in Carceri. GemRB adds +3 to hit. | V | 2 |
| E11 | **Embalm (op 206)**: Minor is 2d4 (GemRB 1d6+1); plane rules (Carceri half, Negative Material 1, Baator save) missing. | V | 2 |
| E12 | **Detect Evil (op 210) sets `STATE_DETECT_EVIL` (0x1000000)** on the caster in the original, and pulses evil creatures in a cone in front. GemRB sets no state and uses a circle. | V | 3 |
| E13 | **Jumble Curse (op 211)**: the original handler only plays the hiccup; GemRB also forces 100% spell failure. Unless casting checks op 211 elsewhere, GemRB is harsher. | S | 2 |
| E14 | **Op 138 sequence ids**: GemRB rejects PST sequence 27 (Minor Embalming). | V | 3 |
| E15 | **Heal (op 17) percent mode sets instead of adds** (Raise Dead SPPR502: original +50 % of max, GemRB = 50 %). Mode 4 = full heal in the original. | V | 2 |
| E16 | **Blindness duration for PW Blind** is ticks in GemRB's hook, seconds in the original (see S17). | V | 1 |
| E17 | **Scrolls cast at about half the caster level** (op 148, also op 146): the original casts at max(p1, the spell's first-header minimum level); GemRB uses p1, which PST scrolls set to the spell level (Blade Storm scroll 7 vs 14, Cloudkill 5 vs 9). | V | 2 |
| E18 | **Transfer HP (op 192)**: GemRB caps the drain at the receiver's missing HP and deals it as **acid** (mode 1) / **crushing** (mode 0) damage. Original: the target loses the full amount as **magic** damage; Vampiric Touch's excess becomes +max HP for 300 s; plane rules and luck apply. | V | 2 |
| E19 | **Ball Lightning / Adder's Kiss (op 196)**: original 1–4 balls with a damage table, and level / 3 + 1 acid hits of 2d4; GemRB one 4d12 ball and one 2d4 hit. | V | 1 |
| E20 | **Learn spell (op 147)** can fail in GemRB above Normal difficulty (INT learn roll); the original never rolls. 83 scrolls. | V | 2 |
| E21 | **Play BAM (ops 187–191)**: placement of "random"/detached animations, timed animations cut short, animations on corpses. Presentation. | V | 3 |
| E22 | **Tint screen (op 195)**: GemRB uses 50 % black instead of the colour, no one-at-a-time rule. Presentation. | P | 3 |
| E23 | **Damage on a petrified/frozen creature kills it** in the original (op 13); GemRB applies plain damage (PST never passes `CanGetChunked`). | V | 2 |
| E24 | **Pain Mirror / Balance in All Things** reflect to every enemy within 120 of the target as magic damage (× 2 in Carceri), 1 or L / 5 times; GemRB hits the last hitter with the original damage type. Resolves R4. | V | 2 |
| E25 | **Difficulty scaling** of effect damage applies to damage *taken by party members* in the original (and caps it at max HP − 1 when max HP < 14); GemRB scales damage *dealt by enemy-EA sources*. | V | 2 |
| E26 | **Op 12 plane bonuses:** Carceri max dice for Chromatic Orb, Fist of Iron, Elysium's Tears; Deathbolt +1 (Carceri, Negative Material) / +6 (Baator). Extends R1. | V | 2 |
| E27 | **Op 12 absorbers:** Guardian Mantle (source saves at −4) can cancel effect damage; Cloak of Warding / Infernal Shield pool absorbs it; the Armor pool doesn't. GemRB side not traced. | V/? | 2 |
| E28 | **Aid gives a fixed 8 HP per p1** in the original (p2 = 8 × p1, first application); GemRB rolls p1d8 (avg 4.5). SPPR201, 23 lines. (E-129) | V | 2 |
| E29 | **Op 13 Death ignores p1/p2** and has no level bands (Cloudkill's bands live in the spell); the companion rules in it are R2, corrected: the `Game_Over` 3 rule fires when **Annah** dies, not Pharod. (E-013) | V | 2 |
| E30 | **Curse also costs p1 damage** in the original (byte `+3281` is the damage bonus, shared with ops 73 and 129); GemRB `fx_curse` leaves damage alone. Extends E7. (E-073) | V | 2 |
| E31 | **Op 120 p2 = 5** is "non-silver, level 0" in the original, "silver, level 0" in GemRB (SILVMAG.itm). (E-120) | V | 3 |
| E32 | Ops 6, 39, 42, 44, 45, 73, 98, 128 compared: parity for PST data except presentation (sleep sets the extra sleep bit in GemRB; confusion pulse/text). | P | 3 |

## 12. Scripting findings, round 3 (detail in [wp4_actions.md](wp4_actions.md))

| ID | Finding | Status | Sev |
|---|---|---|---|
| A5 | **RunAwayFrom(Ex) never attacks in GemRB.** Original: with NoAttacks = 0 the fleeing creature attacks enemies within weapon reach. GemRB reads the flag as "no interrupt" (`GSUtils.cpp:2646`). 874 uses. | V | 2 |
| A6 | **DeactivateEx can't deactivate party members** in the original; its RenderMode goes to `SetActiveAI`. GemRB hides anyone, ignores RenderMode. 82 uses. | V/S | 2 |
| A7 | **RestParty fully heals the Nameless One** (op 17 mode 4) while companions get the HP amount. GemRB heals all alike. | V | 2 |
| A8 | **StartCutSceneEx's int0**: GemRB uses it as "test conditions"; the original sends an unidentified message (vtable 8DC550). | S | 2 |
| A9 | ~~IncrementGlobalOnce creates missing variables in GemRB~~: wrong, PST's `NoNewVariables = 1` stops creation in GemRB too, and all 1,693 calls use declared variables (round 8). | P | — |
| A10 | **PlaySequence / SetAnimState block in PST until the animation ends**; GemRB's PST path (`OneByteAnimationID`) returns before its wait, so the next action starts at once. 1,859 uses (cutscenes, dialogue mime animations). | V | 2 |
| A11 | **StartRandomTimer rolls outside its range**: GemRB `Roll(1, max−min, max−1)` gives max … 2·max−min−1 (5-10 → 10-14 s); the original rolls min … max. 268 uses (ambient loops 1.5-2× slower). Same family: **WaitRandom** never rolls its max (sev 3, 1,398 uses). | V | 2 |
| A12 | **TakePartyItem takes the whole stack in GemRB**; the original takes one unit. Cranium-rat `Tail` (stack 99) is sold one at a time to four NPCs (DBARKING, DKNFGHL, DPHINEAS, DRATBONE): GemRB's first buyer takes them all. Also `PsCharm`, `Embalm`, `Needle`. **Fixed in 97267f33d.** | F | 1 |
| A13 | **Dak'kon's Karach changes on MoraleDec/Inc/Set in GemRB** (`CheckKarachUpgrade`); with no morale threshold crossed it falls to the **bad** blade. The original swaps the blade only at level-up (levels 4/7/10, variant by current morale; `sub_5E6187` → `sub_5E985F`). 48+ Dakkon morale lines. | V | 2 |
| A14 | **Damage misreads every amount ≥ 16 and can kill.** GemRB decodes int1 as a dice code always (`Damage(Protagonist,Lower,25)` → 9, `20` → 4, `50` → 2) and routes it through `Actor::Damage` (resistances, luck, death). The original treats int1 as dice only with bits 0xF000 and edits current HP directly, clamped to ≥ 1: dialogue damage never kills. 78 uses (74 DLG). | V | 1 |
| A15 | **ForceAttack doesn't interrupt the attacker in GemRB.** Original clears the attacker's action queue, then queues `Attack`; GemRB appends the attack behind whatever it was doing. 531 uses. | V | 2 |
| A16 | **PlaySequenceTimed waits ticks instead of seconds.** Original loops the animation for int1 **seconds** and blocks; GemRB `SetWait(int1)` = int1 ticks, no loop: `PlaySequenceTimed(25,4)` lasts 0.27 s instead of 4 s. 70 uses (Mortuary skeleton workers `0208SK*`). | V | 2 |
| A17 | **LeaveParty keeps the companion's party scripts in GemRB.** The original sets script slots AREA, SPECIFICS, CLASS, RACE and GENERAL to empty and sends `Leaves` to each party member; GemRB resets scripts only under `HasDPLAYER` (off for PST). 36 uses (companions leaving). | V | 2 |
| A18 | **DestroyItem takes the item from the wrong creature.** All 20 PST uses are dialogue lines `DestroyItem("X", Protagonist, n)`; the original removes from the named object, GemRB from the caller (the dialogue NPC), ignoring the object and All. Nothing is removed: FalseCon (Copper, Mortai), loandoc (Deran), Cheese/Pcheese (Mantuok, 11 lines), Sohmien, Legclub (Ulthera). **Fixed in 97267f33d.** | F | 1 |
| A19 | **SavePlace does nothing in GemRB.** Bound to `SaveLocation` (a point variable named by a string it doesn't have); the creature's saved position/facing is never set, so `ReturnToSavedPlace` goes to the old spot. 15 uses (`0600AELN`, `0600NEME`, `0602FTDP`…). | V | 2 |
| A20 | **GlobalSetGlobal copies the wrong way.** Original: Name1 ← Name2 (`Previous_Area` takes `Current_Area`); GemRB: Name2 ← Name1. 4 uses (AR0201-0203 area scripts). Same batch: **FollowCreature** is a no-op in PST but blocks the queue forever in GemRB (1 use, `0600THUG`). | V | 2 |

## 13. Voice findings, round 7 (detail in [wp_voices.md](wp_voices.md))

| ID | Finding | Status | Sev |
|---|---|---|---|
| V1 | **Weapon swings speak the wrong lines.** PST slots 14-18 are damage and spell-casting lines; the original plays slots 15-17 when a **spell is cast** and nothing on swings. GemRB plays slots 14-17 by attack stance on swings (Dak'kon slashing says "Damage 2") and nothing on cast. (A11-1) | V | 2 |
| V2 | **Hide, spell disruption and trap setting speak location comments** (slots 70-72 hold Negative Plane / Carceri / Curst lines in PST); the original never plays them for those. One-line fix in `pst/vcremap.2da`. (A11-5) | V | 2 |
| V3 | Selection lines play **in order**, rare ones from the **10th** click in sequence; GemRB picks at random, goes rare after 4 clicks and adds a 5 % random rare. (A11-3) | V | 3 |
| V4 | Sound frequency sliders: level 3 = 40 % (GemRB 50 %), action level 2 = 20 % (GemRB once per selection). (A11-4) | V | 3 |
| V5 | Being hit plays slot 14 or 18 at 50/50; GemRB only 18. (A11-2) | V | 3 |


## 14. Trigger findings, rounds 10-11 (detail in [wp5_triggers.md](wp5_triggers.md))

| ID | Finding | Status | Sev |
|---|---|---|---|
| T1 | **NearbyDialog needed sight.** Original: any object with that dialog within 700 px (y ×4/3), no line of sight, no visual range; GemRB: the first actor with the dialog, then `CanSee` (visual range + LOS). Companion interjections went missing behind walls. 4,761 uses. **Fixed (PST).** | F | 2 |
| T2 | **MoraleLT/GT read the flee threshold.** Original: current morale (+1831, what MoraleInc/Dec change); GemRB `IE_MORALEBREAK`. All 51 dialogue uses gate Dak'kon/Annah/Morte/Grace lines on morale. **Fixed (PST).** | F | 2 |
| T3 | **NotStateCheck inverted.** Original: true when none of the bits is set; GemRB: true when another bit is set (false for a normal creature). Trias, Ravel. **Fixed (PST).** | F | 2 |
| T4 | **RandomNum/RandomNumLT roll 1…Range in GemRB, 0…Range in the original.** `RandomNum(2,0)` (dialogue) never fired; every other value had 1/R instead of 1/(R+1). 200 uses. **Fixed (PST).** | F | 2 |
| T5 | **GlobalTimerExpired: a timer at 0 is expired in the original** (`value < now`); PST's `ZeroTimerIsValid = 0` made it never expire. VAR.VAR starts `No_Gamble`, `Able_Timer_*`, `Bedai_Timer`, `Kiina_Return` at 0. **Fixed (ini).** | F | 2 |
| T6 | TimeGT/TimeLT used schedule masks half an hour early (`TimeGT(21)` 21:30-23:30 vs 22-24). **Fixed (PST).** | F | 3 |
| T7 | NearSavedLocation range is plain pixels in the original, search cells in GemRB (15 of 334 uses have a range). **Fixed (PST).** | F | 3 |
| T8 | NearLocation: GemRB subtracts the personal radius and doesn't use range + 1. | V | 3 |
| T9 | NumCreature(LT/GT) count only creatures the caller sees in the original, the whole area in GemRB (area scripts `AR1601`, `AR1401`). | S | 3 |
| T10 | LOS: GemRB adds visual range and hidden/invisible checks to the original's range + line-of-sight test. | V | 3 |
| T16 | **NullDialog is "not in dialogue" in GemRB, so true almost always.** Original: an event raised only when a creature without dialogue is asked to talk. AR0403: the duelling Painted Thugs (`0403GDUL`) and the barking thug (`0403PROP`) turn on the party at once. (A3) | V | 1 |
| T11 | **TimerExpired is eaten by the first block that tests it** (GemRB erases the timer); in the original the event lasts the whole pass. 8 scripts lose their fallback branch: 0605 `*3` NPCs never switch script, 0200 dustmen don't relocate. (A3) | V | 2 |
| T12 | **Unused events stay pending in GemRB** until some block runs; the original empties the list after every pass. Old `AttackedBy`/`OnCreation` can fire a block much later. (A3) | V | 2 |
| T14 | **A failed pickpocket doesn't count as AttackedBy** in GemRB; in the original a pending PickPocketFailed satisfies `AttackedBy` (1,060 hostile-reaction blocks). (A3) | V | 2 |
| T15 | Every op-12 damage effect raises `HitBy(source, type)` and `AttackedBy(source)` in the original; GemRB only for damage > 0, naming the first hitter, and AttackedBy only for hostile sources. (A3) | S | 2 |
| T13 | Negated events: `!Event(x)` is "an event of this id with other parameters is pending" in the original, "none matching pending" in GemRB. `AR1501`'s `!Vacant()` block never runs in the original, runs in GemRB. (A3) | V | 3 |


## 15. BALDUR.bcs findings, round 11 (detail in [wp_baldur.md](wp_baldur.md))

| ID | Finding | Status | Sev |
|---|---|---|---|
| B2 | **`Game_Over` 7 does nothing in GemRB** (original: death text 67295); BALDUR maps 6 to that text instead (6 is the `QuitGame` end path). `0500GGRD` sets 7. | V | 1 |
| B7 | **Fortress of Regrets party count** happens in GemRB on any AR0202 visit after `Pharod_Quest` = 2, only for companions while the party holds `SkScrap`/`SkRegret`; original: at the `Fort_Port` exit, no item check, companions leave the party (`*EG.CRE`), `LimLim` → `D_LimLim` (GemRB's swap is a no-op). | V | 2 |
| B4 | **Lady's maze** exit location not stored (`Maze_Exit_*`); GemRB always returns to AR0200 and never sets `Modron_Cube` back to 1. | V | 2 |
| B5 | Lady's maze second time: original `Game_Over` 1 (text 44963), GemRB `QuitGame(0,0,0)` with no text. | V | 2 |
| B1 | Faction joins: original keeps every `Join_*` membership (Chaosmen 1 or 3) as flags; GemRB one faction stat that flips every pass when two are set. | V | 2 |
| B8 | Original rules BALDUR doesn't cover: companions leave at `AR1800`→`FR1700` and `AR3017`→`FR0502`, `Pregnant_Quest` > 2 world map on Sigil exits, `AR1203` slab facing. | S | 2 |
| B3 | Shadow movie on first AR0200/AR0206 visit, not on arrival at `FR0201`. | V | 3 |
| B6 | Foundry redirect after AR0512 loads instead of straight to AR0513. | V | 3 |
