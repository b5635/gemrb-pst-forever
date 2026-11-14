# GemRB fork for Planescape: Torment

## Priorities

- **Turn-based combat comes first.** Real-time play is no longer a priority: change engine
  behaviour freely when it makes turn-based combat work well, even if real time changes
  too. The plan and its progress are in `TURN_BASED_PLAN.md` (section 10 "Progress").
- Turn-based rule: loose on presentation, exact on anything a script, dialogue, item or
  spell can observe.
- Turn-based code lives in `gemrb/core/TurnBasedCombat/` (`CombatDirector`, `CombatAnalyzer`).

## Build and deploy

- `build_install.bat` builds Release and installs to `D:\Games\GemRB`. From a shell run it as
  `cmd /c "D:\gemrb\build_install.bat < NUL"` (it pauses on failure). Run it after every change.
- New features get a toggle switched on in `tools/dev_settings.ini` (forced into the
  installed `GemRB.cfg` on deploy).
- Unit tests: target `Test_gemrb_core`, run `build\gemrb\Release\Test_gemrb_core.exe` with
  `D:\Games\GemRB` on `PATH`; turn-based ones: `--gtest_filter=CombatDirector*:TurnMovement*`.

## Testing in game

- `tools\dev.ps1` drives the installed game (start/py/click/key/shot/log/crash).
- `tools\tb_autotest.ps1`: turn-based regression run (party AI on, staged fights, exit 1 on
  crash or stall). `tools\tb_fight.ps1`, `tools\tb_flee_cast.ps1`: single staged fights.
- `tools\tb_analyze.ps1`: combat profile of every PST script (`dev\combat_profiles.md`).
- Aim script actions at a creature by global ID with
  `GemRB.ExecuteActionAt(actor, "Attack([-1])", target)`; PST spells go by spell.ids number.
