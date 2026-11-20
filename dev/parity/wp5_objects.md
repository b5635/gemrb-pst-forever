# A4: object selectors (round 11, 2026-11-19) — partial

Progress (round 12): decoder, resolver, visual range and IDS matcher read (EE + original); NearestEnemyOf and
name lookup decided. **EE is the truth from round 12** (AGENT_GUIDE rule 3).
Next: compare GemRB for `Player1-6`/`Protagonist` (party slot order), `LastAttackerOf`/`LastHelp`/`LastTrigger`
(which stored object, cleared when), `MostDamagedOf` (EE `CInfGame::GetCharacterCriteria` case for
GROUP_MOSTDAMAGED), the ids that fall back to `Myself` (below), and the PST fields `faction`/`team` in GemRB.
Note: `sub_412C7F`/`sub_412994`/`sub_4139BA` (the srcmap's `CAIObjectType` list) are only the class-matching
helpers (multi-class pairs), not the decoder.
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

## Round 12 (2026-11-19): the decoder, read in EE and the original

**Where:** EE `CAIObjectType::Decode` (switch on the object id) → `sub_ADDA10` (resolve) → `CGameArea::GetNearest`,
fallback `CGameArea::GetAllInRangeBack`. Original: `sub_40F77C` (decoder; its switch is on id − 1), `sub_411AA0`
→ `sub_411B7C` (resolve) → `sub_474047` (nearest), fallback `sub_476C01`; IDS match `sub_40F297`. Trigger
objects go through creature vtable slot +172 (`sub_460148`): decode, resolve with type mask 0x31.

**Object id map (original `sub_40F77C:326-792`):** functions nest up to 5 deep (object bytes +18…+22), applied
innermost first. Party slots: Player1-6 = party array slots 0-5 (`+8364 + 4·i` of the game object), Protagonist =
slot 0 too, LeaderOf = slot 0; Weakest/Strongest/MostDamaged/LeastDamaged/StrongestOfMale = party criteria
(`sub_5C468B(1…5)`); ProtectedBy/ProtectorOf/LastAttackerOf/LastTargetedBy/LastCommandedBy/LastHelp/LastTrigger/
LastSeenBy/LastTalkedToBy/LastHeardBy/Marked = an object stored on the caller, re-resolved; SelectedCharacter
= the selection. **GroupOf (3), Nearest (14), LastHitter (15) have no case: they resolve to the caller itself**
(EE's switch has no case 3 or 0xE either). PST uses Nearest 4 times; GemRB resolves it as a real nearest: check
those 4 scripts before calling it a finding.

### O-range Visual range grows with the Nameless One's fighter level (V, sev 2)
- **EE:** `CGameSprite::GetVisualRange` = 32 px × the sprite's range byte; in PST mode `CGameSprite::CheckVisualRange`
  sets it, on every stat change, to `CPlanescape::SetNamelessExploreRange` = **party slot 0's fighter level + 14**
  (`EXPLORED_RANGE_3`), the same for every creature. Original: same rule, `sub_5940BF` (level of class slot 2 + 14,
  stored in the area's visibility map word `+2068`, read ×32 by `sub_462B30`).
- **GemRB:** `Scriptable::GetVisualRange` returns the fixed `VOODOO_VISUAL_RANGE` = 34 for PST (`Interface.cpp`,
  `voodooconst.h` comment knows the formula and freezes it at fighter level 3); `WithinRange` scales 34 × 16 px
  horizontally, × 12 vertically: the same ellipse as EE (y × 4/3) at level 3.
- **Difference:** at fighter level 3 identical (544 px). Each extra fighter level adds 32 px in EE; a level-12
  fighter Nameless One sees (and is seen) at 26 × 32 = 832 px, GemRB still 544. Also applies to the fog of war
  reveal radius in EE (same field).
- **Data affected:** every `See(...)` and every range-limited object (NearestEnemyOf 2,325 uses), i.e. when
  enemies notice and engage the party. Turn-based: decides who joins a fight.
- **Re-check:** `python tools/parity/dumps.py show ee "CPlanescape::SetNamelessExploreRange"`,
  `... show ee "CGameSprite::CheckVisualRange(void)"`, `... show orig sub_5940BF`; GemRB
  `grep -n VOODOO_VISUAL_RANGE gemrb/core/Interface.cpp gemrb/core/Scriptable/Scriptable.cpp`.

### O-NearestEnemyOf (P apart from O-range)
- EE/original: caller EA ≤ 30 → look for EA ≥ 200, EA ≥ 200 → EA ≤ 30, otherwise nobody (orig returns the
  "nothing" object at once). Nearest within the visual range with line of sight, PST-invisible targets
  (`STATE_PST_INVIS` 0x2000000) skipped; if none, the first match within the same range and line of sight from the
  area's list (EE `GetAllInRangeBack`, orig `sub_476C01`, which also skips the dead).
- GemRB `XthNearestEnemyOf` + `DoObjectChecks`: same EA rule, visual range, LOS, invisibility. The fallback can
  only pick something the nearest pass rejected for its distance metric, so in practice the same result. P.

### O-name Name lookup (P)
- Original `sub_40F77C:218-294`: the caller's area table, then the game's global table, then the 6 party members
  by name, case-insensitive; not found, or the id no longer resolves → nothing. EE: area table then global table.
- GemRB: `Map::GetActor(name)` then `Game::FindPC`/`FindNPC`. Same set; which of two same-named creatures wins is
  still open (hash vs most recent), no PST script seen relying on it.

### O-IDS field matching (original `sub_40F297`; EE `CAIObjectType::IsEqual` not yet compared)
- EA: 0 = any; 30 = ≤ 30, 200 = ≥ 200, 31 = ≥ 31, 199 = ≤ 199, else exact. General, race, class, specific,
  gender, PST bytes +11/+12 (faction/team): 0 = any, else exact. Alignment: exact, or 1/2/3 match the low nibble,
  16/32/48 the high nibble. **Fields are only compared when one side has no name**; a named object matches by
  name (or global id).
- GemRB `ID_Allegiance` (`Objects.cpp`): same cut-offs (plus EA_NOTNEUTRAL, unused by PST); `ID_Alignment`:
  masks per nibble, same. Faction/team: not compared yet.

## Round 12, part 2: remaining functions (A4 done, ledger `kind=object` 24/24)

- **Player1-6, LeaderOf (P):** EE reads the game's character array (`+10362…`, join order), not the portrait array
  (`+10368…`, used for the visual range). GemRB `PlayerX` → `Game::GetPC(slot)` = join order. Protagonist: EE
  `CInfGame::GetProtagonist`, GemRB `GetPC(0)`: P.
- **LastAttackerOf, LastHelp, LastTrigger (P):** an object stored on the caller and re-resolved by global id in
  both. GemRB looks the id up in the caller's area only (`GetActorByGlobalID` on the area): an attacker that left
  the area resolves to nothing in GemRB, to the creature in EE (sev 3 edge).
- **O-mostdamaged MostDamagedOf (V, sev 2):** EE `CInfGame::GetCharacterCriteria` case 3: party members, dead
  (state 0x800) skipped, the one with the largest max HP − current HP **strictly above 0**; nobody hurt → nothing;
  no area check. GemRB `MostDamagedOf` (`Objects.cpp`): first party member in the caller's area even at full HP,
  **dead members included** (a corpse has the largest damage). PCGRACE (Fall-from-Grace's party AI, 11 uses) then
  casts its cure spells at a dead companion: `HPPercentLT(MostDamagedOf(Myself),90)` is true for a corpse.
  LeastDamagedOf (case 4) has the same dead skip (unused by PST).
- **IDS fields, team, faction (P):** GemRB `MatchActor` skips IDS fields when the object has a name (same as the
  original `sub_40F297`), then `ID_*` per field; `ID_Team`/`ID_Faction` exact, 0 = any.
