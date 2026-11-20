# WP9: what PST:EE changed in SPL/ITM data (track C, lowest priority)

Done: all 734 files `opmap.json` lists as changed (original + Fixpack + UB vs PST:EE), sorted by the kind of change.
Script (re-runnable, ~30 lines): compare the effect lists per group (equipped/casting block, then each header) with
`pstres.orig()` vs `pstres.ee()`, ignoring added colour (op 7) and glow (op 9) effects.

## Sorting
| Kind | Files | Verdict |
|---|---|---|
| Item colour/glow effects added (op 7 with p2 21 location, op 9 on special weapons): 446 items + one colour per item group, the rest with weapon-specific colours | 593 | presentation (EE's inventory/paperdoll colouring). Leave out |
| op 319 (EE item usability) added with p1 0, p2 0, no resource | 102 items (quest items, keys, Spell Keys `BAATORSK`…, `BAGOCOIN`, `ACLUE`…) | no restriction with all-zero parameters as far as read (S): EE marker, not a PST rule |
| Opcode renumbering (PST op → EE op, `opmap.json` → `map`): 187 → 369 (21: charms, `SPWI402`), 192 → 383 (3: `BUTCHER`, `GKISS`, `IRON2`), 186 → 301 (2: `BOLT06`, `LENS11`); probably also 206 → 380 `EMBALM`, 209 → 355 `FANGMIRR`, 193 → 269 `SHARD`, 194 → 354 `BSIDER` (not checked value by value) | 26 + 4 | P for the 26; S for the 4 |
| Spells rebuilt with one header per caster level | 5: `SPPR301`, `SPWI108`, `SPWI214`, `SPWI216`, `SPWI307` | the data half of R-16 (EE scales these by header *and* by `ApplyLevelBasedDurationMods`); GemRB's `spldurat.2da` covers SPWI214/216 |
| Real effect changes | `SPWI101` (chromatic orb: ops 5/6/39/45 per colour), `SPIN103` (op 177 added), `IRON3` (confusion → stun), `BOLT01` (ops 45/186), `ITEETH` (header removed) | candidates for phase 7's optional "EE fixes" pack; read one by one there |
| Table changes | `DEATH`, `RNDTREAS`/`RNDMAGIC`/`RNDSCROL` (TB-1), `HAPPY`, area flags (R-13, AR0402) | see `wp7_tables.md`, `wp6_rules.md` |
| Dialogue text | 2,602 strings (D-8) | owner decision (phase 7) |

**Result:** of 734 changed files, about 5-10 carry gameplay changes beyond presentation, renumbering and the per-level
headers. Phase 7 ("EE data fixes") is small: the list in the "Real effect changes" row, TB-1's loot tables and D-8.
