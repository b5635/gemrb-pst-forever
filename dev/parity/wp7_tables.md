# WP7: rule tables, PST:EE vs what GemRB loads (track C)

Done: every 2DA both sides have (124), plus EE-only and GemRB-only names. IDs `TB-<n>`.
Method (scratch script, re-runnable): normalise both texts (`pstres.ee()` vs `pstres.gemrb()`, upper case, no comments,
whitespace collapsed) and compare; diffs per table with `difflib`.

## Result
- **95 of 124 shared tables are identical**, including every number table that decides combat and level-up:
  `THAC0`, `SAVEWAR/WIZ/ROG/PRS/CNDH/CNG`, `XPLEVEL`, `XPCAP`, `LVL21PLS`, `HPWAR/WIZ/ROG/PRS`, `HPINIT`, `STRMOD`,
  `STRMODEX`, `DEXMOD`, `INTMOD`, `WISXPBON`, `LORE`, `LOREBON`, `BACKSTAB`, `WSPATCK`, `PROFS`, `PROFSMAX`, `NPCLEVEL`,
  `RAISDEAD`, `FATIGMOD`, `INTOXCON/MOD`, `REPUTATI`, `MXSPLWIZ`, `INTERACT`, `BNTYCHNC`, `BANTTIMG`.
- 29 differ. Most are BG2-EE rows EE adds for classes and kits PST has no use for (`CLSWPBON`, `NUMWSLOT`, `CLSSPLAB`,
  `ABCLASRQ`, `STRTGOLD`, `MXSPLPRS`, `CLASTEXT`, `SPLPROT`, `ITEMTYPE`, `SNDCHANN`, `REVERB`, `MOVIDESC`, `WMAPLAY`,
  `EFFTEXT`): P for PST except the rows below. `HPCONBON`: EE adds `FATIGUE_BONUS` and `STARTING_HP` columns, the shared
  numbers are equal; `STARTING_HP` is only read for a character with no levels (`CRuleTables::GetHitPoints:209-222`,
  character creation): P. `HPCLASS`: GemRB's shared copy adds `*` multiclass rows, PST classes map the same: P.
- EE-only tables: `PSTCHAR` (race strings per companion), `NOCHARGE`, `SLTSTEAL`, `ITMSLOTS`, `HIDESPL`, `DMGTYPES`,
  `EXTSPEED`, `XPLIST`/`XPBONUS`/`ABCLSMOD` (EE campaign tables, all-zero or BG defaults for PST), `ITEMEXCL` (empty).
  Items/stores ones are judged in `wp_items_stores.md`.

### TB-1 Random loot (`RNDTRE01`-`05`): GemRB rolls a table of items PST doesn't have
- **Status:** V      **Severity:** 2      **Uses:** 884 CRE item slots (RNDTRE01 680, 02 177, 03 20, 04 6, 05 1)      **By:** opus
- **EE:** `RNDTREAS.2da` is a PST loot table: 5 rows × 20 columns of PST items (copper/silver/gold earrings, rings,
  bracelets, charms, `RUSTDAG`, `STILETTO`, scrolls `RNDSCR0x`) and gold entries written `N*M` (`10*10`, `40*50`,
  `20*500`, `50*1000`); every item exists. Read by `CItem::ResolveRandomItem` (`Find("RNDTRE")`).
- **GemRB:** `randitem.2da` (`gemrb/unhardcoded/pst`) → `RNDTREAS` from the original BIF (`Interface::ReadRandomItems`,
  `ReadItemTable(..., "RNDTRE")`): rows POOR…RICH full of BG names (`MISC19`, `AMUL05`, `RING12`, `RNDMAG01`…):
  **44 of the 60 item entries don't exist in PST** (`Interface::ResolveRandomItem` logs "Nonexistent random item" and
  drops the slot); the rest are 1-4 copper or other BG-random tables.
- **Difference:** in GemRB most `RNDTRE` corpses drop nothing or a few coppers; in EE they drop PST trinkets, scrolls
  and up to hundreds of coppers. EE's `N*M` gold form needs checking against EE's resolver before porting (GemRB reads
  `N*M` as item `N` with 1…M charges).
- **Re-check:** `python -c "import sys; sys.path.insert(0,'tools/parity'); import pstres; print(pstres.text(pstres.ee().res('rndtreas','2da')))"`;
  `sed -n '/bool Interface::ReadRandomItems/,/^}/p' gemrb/core/Interface.cpp`.
- **Next:** read `CItem::ResolveRandomItem` (EE) for the gold form and the column roll before the fix.

### TB-2 Non-proficiency penalty for mages: −5 in EE, −4 in GemRB
- **Status:** V      **Severity:** 2      **Uses:** the Nameless One as mage, Ignus      **By:** opus
- **EE:** `CLSWPBON.2da` `ZERO_SKILL_THAC0`: MAGE 5, MAGE_THIEF 5 (FIGHTER 2, THIEF 3); used by
  `CGameSprite::CheckCombatStatsWeapon:252-269` → `CRuleTables::ClassZeroSkillTHAC0Bonus` for a weapon with 0 skill.
- **GemRB:** `gemrb/unhardcoded/shared/clswpbon.2da` MAGE 4, MAGE_THIEF 4 → `Actor::GetNonProficiencyPenalty`
  (`noProfPenalty`, `Actor.cpp` ~1777).
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::CheckCombatStatsWeapon(" 250 270`;
  `head -5 gemrb/unhardcoded/shared/clswpbon.2da`. Fix as a PST override of the table, not the shared one.

### TB-3 Proficiency level 4 damage: +4 (GemRB) vs +5 (EE)
- **Status:** S      **Severity:** 2      **By:** opus
- **EE:** `WSPECIAL.2da` row 4 = hit 3, damage **5**; loaded by `CRuleTables::CRuleTables:3170` (`+6176`).
  Its reader was not traced (accessed through the rule-table base, no direct hit in `dumps.py grep`).
- **GemRB:** loads the install's `override/WSPECIAL.2da` (row 4: hit 3, damage 4) via `GameData::GetWSpecialBonus`.
- **To settle:** find EE's damage-bonus reader (`CGameSprite::CheckCombatStatsWeapon`, `GetStatBreakdown`), then V or P.

### TB-4 Thief starting skill points: 40 (GemRB) vs 0 (EE)
- **Status:** S      **Severity:** 2      **By:** opus
- **EE:** `THIEFSKL.2da` THIEF/FIGHTER_THIEF `START_POINTS` 0, `LEVEL_POINTS` 20 (`CRuleTables::THIEFSKILLS`,
  loaded at `CRuleTables::CRuleTables:3358`; EE's PST level-up UI is Lua, reader not traced).
- **GemRB:** `gemrb/unhardcoded/pst/thiefskl.2da` 40/20, used by `LUSkillsSelection.py` when the thief level was 0
  (the Nameless One's first thief level).
- **Difference (if EE reads it the same way):** 40 fewer points on his first thief level in EE. Needs a check in PST:EE.

### Data-only differences (WP9)
| Table | EE change |
|---|---|
| `DEATH` | Grace's `FFG045` moved from the Nameless One's row to her own; Morte's reaction to Dakkon `MRT182,MRT183` → `MRT183`; Vhailor gets `VHA040` for his own column (sev 3) |
| `HAPPY` | the reputation/alignment happiness table rebalanced (whether PST code reads it was not checked) |
| `RNDMAGIC`, `RNDSCROL` | rewritten for PST (feed TB-1) |
| `STARTARE` | EE's start point differs (character creation only) |
