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
| S3 | **Power Word, Blind (SPWI805) is wrong and lands nothing in the suite.** Original logic (`CPsSpellPowerWordBlind::AIUpdate`): sort the creatures in range by current HP and spend a pool of 100 HP from the weakest up. Blindness (op 74) duration depends on the pool: ≤25 → 160–400 ticks, 26–50 → 80–200, >50 → 16–40. A pulse glow (op 9) is added and a hit trigger is sent. GemRB's `PWB` helper applies blindness with no HP pool, and the suite saw no change (in both turn-based and real-time). | V (logic) / S (why nothing lands) | 1 |
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
