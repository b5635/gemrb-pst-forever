# A8: GemRB's BALDUR.bcs vs the original's hardcoded rules (round 11, 2026-11-19)

Done: 64/64 blocks (ledger `kind=baldur`). Source: `gemrb/unhardcoded/pst/source/baldur.baf` (compiled `BALDUR.bcs`,
not in the original game). Read it with `python tools/parity/bcs.py BALDUR --gemrb`.

Original code the blocks stand in for (EE names first, original address second):

| Rule family | EE | Original | GemRB blocks |
|---|---|---|---|
| leave-area redirects: Lady's maze, Fortress of Regrets entry, Sabotage foundry, shadow movie, party dismissals | `CPlanescape::PlanescapeLeaveAreaName` | `sub_799362` (same strings: `Fort_Port`, `Fortress_*`, `LimLim`/`D_LimLim`, `*EG.CRE` + `layout.ini`, `Maze_Exit_*`, `MAZE1`/`MAZE2`, `SS_MSLAB`, `AR3017`/`FR0502`, `AR1800`/`FR1700`) | 11-18, 43-63 |
| area first AI update: SIGIL movie, AR1203 slab, Soego | `CPlanescape::AreaFirstAIUpdate` | `sub_47735A` | 13 |
| game over by `Game_Over` | `CPlanescape::HandleGameOverConditions` | `sub_7DC3DD` (death text per value) | 5-10 |
| Nameless One's alignment from `GOOD`/`LAW` | `CGameSprite::GetAlignment` (computed live) | `sub_7DC18E` (each area update, called from `sub_7D1D1C`) | 19-42 |
| faction membership from `Join_*` | `CPlanescape::PushFactionInfo` (record screen) | `sub_5C007B` (flags at game `+10316`), used by item usability `sub_5C02D5` | 0-4 |

Global names: the original's `GOOD` is `dword_96EDD0`, `LAW` is `dword_96EDA8` (proved by the death-globals code
`sub_768466:180-200`: flag 0x400 adds to `96EDD0`, 0x800 to `96EDA8`, as EE `SetDeathGlobals` does to "GOOD"/"LAW").

## Differences (findings B1-B8, `findings.md` section 15)

### B2 `Game_Over` 7 does nothing in GemRB; 6 shows a death text (sev 1, V)
- **Original:** `sub_7DC3DD`: 1 → strref 44963, 2 → 48153, 3 → 48154, 4 → 48155, 5 → 41656, **7 → 67295**: death screen and
  game-over song. **6** sets a flag (`this+4840`, EE: the end-credits path) and nothing else; 6 is what the `QuitGame`
  action writes (`sub_44B099` case 309: `Game_Over` = 6, `End_Movie1..3` = its three ints).
- **GemRB:** blocks 5-10 cover 1-6, with **6 → `QuitGame(0,0,67295)`** and no block for 7.
- **Data:** `0500GGRD` `IsLocked("ar0500d1") Global("GLOBALUportal_Given",0) Allegiance(Myself,255)` →
  `SetGlobal("GLOBALGame_Over",7)`. In GemRB the game goes on. Nothing in BCS/DLG sets 6 (GemRB's `QuitGame` ends the
  game itself), so block 10 is dead but maps the wrong value.
- **Re-check:** `python tools/parity/ida.py show orig 7DC3DD`; `python tools/parity/bcs.py --grep 'Game_Over",[67]\)'`;
  `grep -n "game_over" gemrb/unhardcoded/pst/source/baldur.baf`.
- **Breaks:** the AR0500 guard's game-over (67295) never happens.

### B7 Fortress of Regrets entry counted at the wrong time, with an extra condition (sev 2, V)
- **Original:** `sub_799362:1149-1395` (EE `PlanescapeLeaveAreaName:471-721`), only when the **protagonist leaves AR0202
  through `Fort_Port`**: for every party member: the protagonist adds 1 to `Fortress_Party_Alive`, `_Roof`,
  `_Death_Counter`, `_Party`; each companion adds 1 to `_Party`, to `_Alive` and `_Death_Counter` only if not dead
  (base state 0x800), sets `Fortress_<Name>` = 1, adds 1 to `_Roof` except Ignus and Vhailor; every `LimLim` in any
  inventory becomes `D_LimLim`; `BSPHERE`, `NTOKEN`, `BLADEIM` move to the protagonist; each companion is saved to
  `<NAME>EG.CRE` (written to `layout.ini`) and **leaves the party**.
- **GemRB:** blocks 43-63 run whenever `Current_Area` = 202 and `Pharod_Quest` = 2 (mid-game): the protagonist's four
  variables are set then; each companion is counted only while the party holds `SkScrap` or `SkRegret` (an item the
  original never checks); counts are frozen at that moment (later deaths, joins and leaves are missed); nobody leaves
  the party; the LimLim block takes `d_limlim` (which nobody has) instead of swapping, so it does nothing.
- **Re-check:** `python tools/parity/dumps.py lines orig sub_799362 1276 1395`; `sed -n '/end of alignment system/,$p'
  gemrb/unhardcoded/pst/source/baldur.baf`.
- **Breaks (risk):** a companion who dies or leaves between the AR0202 visit and the portal is still counted alive
  (`Fortress_Party_Alive`, `Fortress_Death_Counter` drive the Fortress dialogues); LimLim stays alive.

### B5 Lady's maze, second time: no death text (sev 2, V)
- **Original:** `sub_799362` (EE 254-281): `LADY` > 49 and `AR1900_Visited` > 0 and the protagonist takes a Sigil street
  exit (EE `sub_A998B0` list): first call plays `MAZE2`, the repeat call sets `Game_Over` = 1 → death text 44963.
- **GemRB:** block 15: `StartMovie("maze2")` then `QuitGame(0,0,0)`: no death text.

### B4 Lady's maze, first time: exit location not kept (sev 2, V)
- **Original:** same function (EE 885-1042): first call plays `MAZE1`; the repeat call makes every companion leave the
  party, stores `Maze_Exit_Location` (area number), `Maze_Exit_Xpos/Ypos` (the protagonist's position) and sends the
  protagonist to `AR1900` entrance `mazeentr`. Leaving `AR1900` later (EE 301-316) goes back to area `AR0<n>`/`AR<n>`
  of `Maze_Exit_Location` at `MAZESPECIAL` (the stored position) and sets `Modron_Cube` = 1.
- **GemRB:** block 14: `maze1`, companions `LeaveParty`, `TeleportParty("ar1900",[2559.1895])` (S: the coordinates are a
  guess of `mazeentr`); nothing stored. Block 16 (`CreatureInArea("ar1501") UsedExit("pcmaze",Protagonist)`) always
  returns to `ar0200 [289.3391]`; `Modron_Cube` is never set back to 1 (`AR1900`'s first block clears it on entry, as `AR0700`, `AR1200`, `AR0610` do; `AR0200` sets it), so the cube stays off after the maze until an area script sets it again.
- **Missing:** whether GemRB's `UsedExit("sigil",…)` covers the same exits as `sub_A998B0` (S).

### B1 Faction membership is one stat in GemRB, a set of flags read live in the original (sev 2, V)
- **Original:** `sub_5C007B`: bit 1 `Join_Sensates` = 1, 2 `Join_Dustmen` = 1, 4 `Join_Anarchists` = 1, 8 `Join_Chaosmen`
  = **1 or 3**, 0x10 `Join_Godsmen` = 6; several bits at once. Only item usability for the protagonist uses them
  (`sub_5C02D5:100-300`); nothing in BCS/DLG sets or tests a faction byte (`SetFaction`/`Faction` have 0 uses).
- **GemRB:** blocks 0-4 `ChangeFaction(Protagonist,X)` when `!Faction(Protagonist,X)` and the global is set (Chaosmen
  only 1; Anarchists win). Item usability reads `IE_FACTION` through `itemuse.2da`/`factions.2da`.
- **Difference:** with two `JOIN_*` globals set (e.g. Sensates 1 and Dustmen 1) blocks 1 and 2 fire on alternate passes
  and the faction flips every script pass; `Join_Chaosmen` = 3 is no membership in GemRB. The usability rule itself is
  track C (items).

### B3 Shadow movie on first visit instead of on arrival from the Mortuary (sev 3, V)
- **Original:** EE `PlanescapeLeaveAreaName:725-742`: `SS_MSLAB` when the protagonist travels to `AR0200` or `AR0206`
  **arriving at entrance `FR0201`**, once (`Played_Shadow_Movie`). `SIGIL` on AR0200's first AI update (`sub_47735A`).
- **GemRB:** blocks 11-12 on `AR0200_Visited`/`AR0206_Visited` = 1 (set by the area scripts on first entry), whatever
  the entrance; block 13 `SIGIL` on `AR0200_Visited`. Same order (shadow, then Sigil).

### B6 Foundry redirect (sev 3, V)
- **Original:** leaving `AR0502` by `to0512` with `Sabotage` 5 or 7 sends the party to `AR0513` (same entrance name).
- **GemRB:** blocks 17-18: after arriving in `AR0512` by `foundry`, `TeleportParty("ar0513",[1078.892])`. AR0512 loads
  for a moment (its scripts may run once).

### B8 Original leave-area and first-update rules BALDUR doesn't cover (sev 2, S)
Not found anywhere in GemRB (`grep -rni "AR1800\|AR3017\|Pregnant_Quest\|1203_Slab" gemrb/`):
- `AR1800` → `FR1700` (protagonist): every companion leaves the party (EE 321-458).
- `AR3017` → `FR0502` (protagonist): every companion leaves the party (EE 745-878).
- A Sigil street exit with `Pregnant_Quest` > 2 opens the world map instead (EE 284-298).
- `AR13*` areas other than `AR13FY/FD/WZ/EN` clear the leave flag `a12` (meaning unknown).
- `AR1203` first update: `1203_Slab` = 1, the protagonist faces direction 2 and gets message 36 (EE `AreaFirstAIUpdate:80-97`).
- `AR0201` first update after `AR0200_Visited`: "soego" AI off (covered by data: `0201SOEG` destroys itself).
Each needs an in-game check of what PST's own scripts already do there before it becomes a V.

## Parity (P)

| Blocks | Rule | Note |
|---|---|---|
| 5-9 | `Game_Over` 1-5 → death texts 44963, 48153, 48154, 48155, 41656 | same strrefs as `sub_7DC3DD`. GemRB resets the variable; the original keeps it (it blocks saving, `sub_47A7F2`) |
| 13 | `SIGIL` movie on the first AR0200 visit | see B3 for the order |
| 19-42 | alignment from `good`/`law` | same thresholds as `sub_7DC18E`: good > 14 / evil < −20, lawful > 14 / chaotic < −20. GemRB moves one step per pass (LG → LN → LE takes two passes and two "alignment changed" floats 29454); the original sets the target at once with one message (type 57) |
