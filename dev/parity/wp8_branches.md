# WP8: GemRB's own PST branches (track C)

Done: every `PST_STATE_FLAGS` / `pstflags` / `HAS_KAPUTZ` / `AUTOMAP_INI` branch in `gemrb/core` and `gemrb/plugins`
(`grep -rn "GFFlags::PST\|pstflags\|HAS_KAPUTZ\|AUTOMAP_INI\|PST_STATE_FLAGS" gemrb/core gemrb/plugins --include=*.cpp`):
110 hits in 22 files. Triage: each branch either already has a verdict elsewhere, is judged here, or is presentation.
Line numbers are from 2026-11-19 (they drift: function names given).

## Judged elsewhere
| Branch | Where judged |
|---|---|
| `Actor::Damage` PST criticals, `ModifyWeaponDamage` `STATE_CRIT_PROT`, `GetProficiencyBonus` `STATE_CRIT_ENH`, `UseItem` critical type | track B, C-2, C-11, C-12, C-13 (`wp10_combat.md`) |
| `GetDefense` Dead_Truce / tokens | C-7 |
| `ShouldModifyMorale` (PCs never break) | C-20 (EE: same) |
| `GetSavingThrow` Litany −`Morte_Taunt` | R-16 (EE: same direction) |
| `ModifyDamage` Armor spell (spwi102) pool | E-012 (`wp2_opcodes.md`) |
| `AddExperience` protagonist class XP pool | E-104 |
| `Die` → `NamelessBitTheDust`, `Game::EveryoneDead` → `RespawnNameless` | A3 events, R-7/R-8 |
| `Spell::GetEffectBlock` → `AdjustPSTDurations` (`spldurat.2da`) | R-16 |
| `EffectQueue` PST delays in ticks | P-5 (`wp11_effect_pipeline.md`: units match) |
| `Triggers.cpp` (13), `Actions.cpp` (7), `GSUtils` KAPUTZ, `GameScript` `HasKaputz` | A1/A2/A5 ledger rows |
| `GAMImporter` KAPUTZ variables (4) | A5 variable scopes |
| `Actor::PlaySelection/CommandSound` frequencies | V3-V5 (`wp_voices.md`) |
| `GUIScript StealFailed` / `Inventory` steal flag | ST-4 (`wp_items_stores.md`) |

## Judged here
| Branch | Verdict |
|---|---|
| `Actor::GetHpAdjustment` / `GetClassLevel`: the Nameless One (`SPECIFIC` 2) always uses the warrior CON bonus and F/M/T levels | S: EE `CRuleTables::GetHPCONBonus` takes the active class (`GetHitPoints:160,187`); for him as mage the EE bonus would be the non-warrior column. Check `GetHPCONBonusTotal` (PST branch listed by `dumps.py grep ee "ENGINE_MODE == 3"`) before deciding |
| `EffectQueue` save bonus: no specialist ±2 in PST | P (PST has no specialist mages) |
| `EffectQueue` `STATE_ANTIMAGIC` blocks effects | S: not compared with EE |
| `fx_charisma_modifier` / `fx_set_blur_state`: a second cast of Friends / Blur replaces the first | S: EE stacking rule for same-source effects not read |
| `GameScript` dialogue start range +160 px for PST (`BeginDialog`, comment: tuned for 1201csg3) | S: GemRB's empirical value; EE's dialogue distance not found by constant name (`eeconst.py "*DIALOG*RANGE*"` = none) |
| `Game` area-change runs `ProcessActions` instead of scripts (#2313) | P (GemRB scheduling) |
| `Game::GetGlobalTint` `AT_PST_DAYNIGHT` | P (presentation) |
| `CombatDirector`: the Nameless One excluded from one turn-based rule (`IE_SPECIFIC` 2) | fork-only, not a parity item |

## Presentation only (sev 3, not compared)
`PlayDamageAnimation` height, `CheckPuppet` no improved-invisibility flag, `PST_INVIS`/`PST_MIRROR` state bits in
`fx_set_invisible_state`/`fx_cure_invisible_state`/`fx_force_visible`/mirror image (PST's own bit layout), no armour
sounds, critical miss/hit sound lines, displayed long names, tooltip delay, `AREImporter` (12: PST animation flags,
automap notes), `WEDImporter`, `MapControl`/`WorldMapControl`, `Highlightable`, `Projectile` height, `Core.cpp`.
