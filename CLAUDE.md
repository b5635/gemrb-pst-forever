# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# GemRB fork for Planescape: Torment

## Priorities

- **Turn-based combat comes first.** Real-time play is no longer a priority: change engine
  behaviour freely when it makes turn-based combat work well, even if real time changes
  too. The plan and its progress are in `TURN_BASED_PLAN.md` (section 10 "Progress").
- Turn-based rule: loose on presentation, exact on anything a script, dialogue, item or
  spell can observe.
- Turn-based code lives in `gemrb/core/TurnBasedCombat/` (`CombatDirector`, `CombatAnalyzer`).

## Build and deploy

- `build_install.bat` builds Release and installs to `C:\Games\GemRB`. From a shell run it as
  `cmd /c "D:\gemrb\build_install.bat < NUL"` (it pauses on failure). Run it after every change.
- Commit as soon as a change is built, tested and works (in game or in the tests): don't wait to
  be asked. Commit only that change's files, with a message that says what it fixes or adds.
- New features get a toggle switched on in `tools/dev_settings.ini` (forced into the
  installed `GemRB.cfg` on deploy).
- Unit tests: target `Test_gemrb_core`, run `build\gemrb\Release\Test_gemrb_core.exe` with
  `C:\Games\GemRB` on `PATH`; turn-based ones: `--gtest_filter=CombatDirector*:TurnMovement*`.

## Testing in game

- `tools\dev.ps1` drives the installed game (start/py/click/key/shot/log/crash).
- `tools\tb_autotest.ps1`: turn-based regression run (party AI on, staged fights, exit 1 on
  crash or stall). `tools\tb_fight.ps1`, `tools\tb_flee_cast.ps1`: single staged fights.
- `tools\tb_analyze.ps1`: combat profile of every PST script (`dev\combat_profiles.md`).
- Spells: `python tools\tb_spell_audit.py` (data audit, `dev\spell_audit.md`, no game) and
  `python tools\tb_spell_suite.py [SPWI502 ...]` (casts every spell in a staged fight, checks
  playout, rounding, clock, hold; `dev\spell_report.md`). By hand: `tools\tb_spell_lab.py` (dev
  console helpers, `GemRB.DebugEffects`), `tools\tb_lab_step.ps1`, `tools\tb_lab_seq.ps1`.
- Hangs: a watchdog writes the main thread's stack to `crashes\last_hang.txt` (30 s unanswered).
- Aim script actions at a creature by global ID with
  `GemRB.ExecuteActionAt(actor, "Attack([-1])", target)`; PST spells go by spell.ids number.
- Python tool tests: `python -m pytest tools\tests`. `tools\lighting\tests` needs the venv from
  `tools\lighting\setup_env.bat` (cv2 etc.).

## Architecture

- `build\` is already configured (MSVC, vcpkg toolchain `D:\vcpkg`, `CMAKE_INSTALL_PREFIX=C:\Games\GemRB`,
  tests on); just build, don't reconfigure. Game data comes from the original install at
  `C:\Program Files (x86)\Black Isle\Torment\` (set in `tools/dev_settings.ini`).
- `gemrb/core/`: engine (`Game`, `Map`, `Scriptable/Actor`, `EffectQueue`, `GameScript/` actions
  and triggers, `GUI/GameControl`). `gemrb/plugins/`: file-format importers, video/audio drivers,
  opcode sets (`FXOpcodes`, `PSTOpcodes`) and `GUIScript` (the C++ → Python `GemRB` module).
- `gemrb/GUIScripts/pst/`: PST screens in Python (EE UI: `EEUI.py`, `EEHud.py`; turn order:
  `TurnOrder.py`). `gemrb/unhardcoded/pst/`: tables that replace hardcoded original-engine rules.
- Turn-based combat: `Game` owns one `CombatDirector` (`Game::combat`). While a fight runs it takes
  its creatures away from the real-time action system; code in `Map`, `Actor`, `Movable`,
  `PathFinder`, `Projectile`, `EffectQueue`, `GameScript/Actions` checks
  `CombatDirector::Owns(actor)` / `IsCombatant` and defers to it. `CombatAnalyzer` profiles creature
  scripts; `CombatHud` draws the turn-based overlays.
- Core unit tests live in `gemrb/tests/core/` (gtest; `LiveGameFixture.h` boots real game data).

## Other workstreams

Each has its own plan doc at the repo root; read it before working in that area.

- `PARITY_PLAN.md`: match PST game logic. PST:EE (`D:\GOG Games\Planescape Torment - Enhanced Edition`)
  is the truth; the original exe only when EE is unclear. Start a session with
  `dev/parity/HANDOFF.md`, evidence in `dev/parity/findings.md`, tools in `tools/parity/`.
- `EE_UI_PLAN.md` (EE art and layouts over classic PST, tools in `tools/eeui/`),
  `LIGHTING_PLAN.md` (`tools/lighting/`), `VFX_PLAN.md` (`tools/vfx/`), `UPSCALE_PLAN.md`
  (`tools/upscale/`; never delete `C:\Games\GemRB\upscaled`), `NOTES.md` (graphics overhaul phases),
  `LLM_PLAY_PLAN.md` (play-through harness, plan only).
