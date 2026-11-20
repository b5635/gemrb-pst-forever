# A4: object selectors (round 11, 2026-11-19) — partial

Progress: usage counted, name lookup and `NearestEnemyOf` compared (EE + GemRB), original not yet confirmed.
Next: confirm in the original (`CAIObjectType` = `sub_412C7F`, `sub_412994`, `sub_4139BA`; the decoder is the
original of EE `CAIObjectType::Decode`), then `LastAttackerOf`, `LastHelp`, `Protagonist`/`Player1-6`,
`MostDamagedOf`, `Nearest`, `LastTrigger`, and IDS field matching (EA cut-offs, `specific`, `team`, `faction`).
Ledger: object rows are not in `script_ledger.tsv` yet (`script_ledger.py` only builds the four known kinds; add a
`kind=object` source to it rather than hand rows, which a rebuild would drop).

## What PST uses (`python tools/parity/bcs.py --objects`, DLG text counted separately)

| Object | BCS | DLG text |
|---|---|---|
| `Myself` | 8,693 | 1,323 |
| by name (`"Morte"`) | 2,632 | most of the rest |
| `NearestEnemyOf` | 2,325 | 0 |
| `LastAttackerOf` | 1,377 | 0 |
| `LastHelp` | 606 | 0 |
| `Protagonist` | 137 | 5,450 |
| `Player1`…`Player6` | 62 / 24 / 24 / 22 / 22 / 20 | 17 / 2 / 2 / 2 / 2 / 2 |
| `MostDamagedOf`, `Nearest`, `LastTrigger` | 11 / 4 / 3 | 0 |
| IDS fields | ea 3,281, specific 618, team 361, gender 189, race 159, align 153, general 66, faction 17 | `[PC]` 49, `[Enemy]` 6 |

No other `object.ids` function is used anywhere (no `LastTalkedToBy`, `LastSeenBy`, `Gabber`… in PST data).

## Findings so far

### O-name Name lookup (P, sev 3 details; S until the original is read)
- **EE** `CAIObjectType::Decode:186-264`: the name is upper-cased and looked up in the caller's area name table
  (area `+4016`; for an area caller the viewed area), then in the game's global table (`+52016`); not found → `NOONE`;
  an id that no longer resolves → `NOONE`. One object per name (a hash).
- **GemRB** `Matching.cpp` `EvaluateObject`: `Map::GetActor(name, flags)`: the **most recently created** actor with
  that name that passes the trigger's flags, then doors, containers, info points (`GetActorObject`);
  `GetScriptableFromObject` also tries `Game::FindPC`/`FindNPC` (the global part).
- **Open:** which creature the original's hash keeps when two share a name (first or last registered), and whether a
  dead creature stays in it (GemRB skips actors failing the flags, e.g. dead ones for `GA_NO_DEAD` callers).

### O-NearestEnemyOf (P, sev 3 details; S until the original is read)
- **EE** `Decode` case 0xC: caller EA ≤ 30 (GOODCUTOFF) → nearest of EA ≥ 200 (EVILCUTOFF); EA ≥ 200 → nearest of EA ≤ 30;
  otherwise nobody. `CGameArea::GetNearest(int,…)`: skips dead (state 0x800) and inactive sprites, plain squared
  distance, line of sight only when asked (`a6`), no visual-range limit seen.
- **GemRB** `XthNearestEnemyOf` (`Matching.cpp`): same EA rule; `DoObjectChecks` also drops invisible targets and
  anything **outside the caller's visual range**, and unscheduled actors.
- **Open:** confirm in the original whether `NearestEnemyOf` is limited to visual range / line of sight (2,325 uses:
  `Attack(NearestEnemyOf(Myself))`, mostly after `See(NearestEnemyOf(Myself))`, which has its own range).
