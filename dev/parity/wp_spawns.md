# A9: area INI spawns (round 12, 2026-11-19), judged against PST:EE

EE: `CSpawnFile` (`Execute` from `CGameArea::AIUpdate`, `EnterSpawn`, `ExitSpawn`), `CSpawnList` (one `[event]`
group: `interval`, `critters`, `control_var`, `spawn_time_of_day`), `CSpawn` (one critter: `Read`, `ExecuteSpawn`,
`SelectSpawnPoint`), `CSpawnPoint`, `CSpawnVar`; key names in `ctor_019`. EE's `CGameSpawning` is the ARE
random-monster spawn point, not this. GemRB: `core/IniSpawn.cpp`.

## What the data uses
188 INI files load in GemRB (7 differ from EE's copies). Spawn keys by use: `spec` 1,052, `cre_file` 1,052,
`spawn_point` 1,049, `script_default` 985, `spec_var` 777, `ai_specifics` 682, `find_safest_point` 461,
`check_view_port` 412, `point_select` 395, `script_name` 374, `spec_qty` 326, `create_qty` 305, `script_general`
250, `ignore_can_see` 217, `facing` 166, `dialog` 150, `ai_team` 140, `check_crowd` 135, `critters` 95,
`spawn_select` 90, `interval` 83, `enter` 42, `events` 31, `detail_level` 29, `death_scriptname` 23,
`ai_general` 17, `ai_ea` 11, `save_selected_point` 3, `spawn_point_global` 3, `ai_race/class/gender/faction` 1
each; `[nameless]` `destare`/`point`/`state` 166. Not used at all: `control_var`, `spec_area`,
`spawn_time_of_day`, `check_by_view_port`, `do_not_spawn`, `disable_renderer`, `time_of_day`.

## SP-0 Keys GemRB ignores (P)
GemRB skips `control_var`, `spec_area`, `check_crowd`, `spawn_time_of_day`, `check_view_port`, `check_by_view_port`
(`IniSpawn.cpp` comment before `ReadCreature`). EE: `CSpawnPoint::IsCrowded` is an empty stub (always "not
crowded"), so `check_crowd` (135 uses) does nothing in EE either; EE's key is spelled **`check_by_view_port`**, so
PST's 412 `check_view_port` lines are ignored by EE too; `control_var`/`spawn_time_of_day`/`spec_area` are read by
EE but no PST file uses them. Parity.

## SP-1 First pass of a timed event (V, sev 3)
- EE `sub_9340D0` (called by `CSpawnFile::Execute` each area AI update): the first call only records the game time;
  the group spawns once `interval` ticks (minimum 15, `CSpawnList::CSpawnList`) have passed since, then restarts the
  clock after every attempt.
- GemRB `IniSpawn::SpawnGroup`: `lastSpawndate` starts at 0, so the first `CheckSpawn` after the area loads
  spawns the group at once; the clock only restarts when a critter passes its schedule.
- Effect: a timed group spawns one interval early on entering an area; `spec`/`spec_qty` caps keep most groups
  from growing, so mostly invisible.

## SP-2 How many creatures one pass makes (S, sev 2)
- EE `CSpawn::ExecuteSpawn:124-175`: counts creatures matching `spec` in the area (or in range / skips counting
  by flags), and when the count is below `spec_qty` spawns `create_qty` creatures (flag 0x40: the difference;
  flag 0x10: a count read from a global); then `sub_92F910` picks the spawn point.
- GemRB `SpawnCreature`: re-counts before **each** creature and stops at `spec_qty`, so `spec_qty` 3, `create_qty` 3
  with 2 alive → GemRB 1 new, EE (if `sub_92F910` doesn't clamp) 3 new.
- **Open:** read `sub_92F910` and the flag bits set in `CSpawn::Read` before calling this V.

## Other items (P or covered elsewhere)
- `spec_var` gate: EE flag 2 → spawn only if the variable is > 0; GemRB: only if non-zero (`specvar` unsigned) or
  the `spec_var_operation` compare. P. `spec_var_inc` added after each spawn in both.
- Spawn point choice: EE `CSpawn::SelectSpawnPoint` walks points from the selected index, preferring ones outside
  the viewport or not visible (unless the ignore flag); GemRB: `find_safest_point` = first point in fog, then refuses
  a visible point unless `ignore_can_see`. Same intent; exact tie order not compared.
- Nameless One respawn (`[nameless]` `destare`/`point`/`state`, `SetNamelessDeath`): round 2 R2 (Nameless death
  rules); EE `CGameArea::HandleNamelessDeath` vs GemRB `IniSpawn::RespawnNameless` not re-read here.
