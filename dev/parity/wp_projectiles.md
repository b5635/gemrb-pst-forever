# Plain projectiles (track C), PST:EE `.pro` vs GemRB `.pro`

Done: the 54 PRO files PST:EE ships, matched by projectile number. IDs `PR-<n>`.
Method: EE `projectl.ids` (EE id = SPL/ITM projectile field − 1) → EE `<name>.pro`; GemRB's PRO for the same field from
`maps/projectiles.tsv` (`gemrb_pro`); header fields `0x08` type, `0x0A` speed, `0x0C` sparkle, `0x2C` extended flags,
area part `0x200` flags, `0x204` trigger size, `0x206` explosion size, `0x210` frequency, `0x214` explosion projectile.
Scratch script: `pro3.py` in the session scratchpad (re-runnable: ~40 lines over `pstres.ee()`/`pstres.gemrb()`).

## Scope
- EE ships **54 PRO files** only, nearly all for spells (`SPWIxxx`, `SPINxxx`, `SPPRxxx`, `MAGICMIS`, `IMISS`, `AMISS`,
  `BOLT01`, `IGNUSFI`, `NTOKEN`). GemRB ships **213** (its own, written for PST). Projectiles without an EE PRO (arrows,
  bolts, daggers, …) are built in code by `CProjectile::DecodeProjectile` (generic EE path, `projectl.ids` lookup fails →
  default classes); they were **not compared** (?): reading `DecodeProjectile`'s 2,694 lines for PST numbers is a
  package of its own.
- EE filters area targets for PST in `CPlanescape::IsProjectileTargetAffected` (called from
  `CProjectile::DeliverEffects:156`): IDS type 2 EA ally test, 3 general, 4 race, 5 class (202-209 = class groups via
  `OfType`), 6 specific, 7 gender, 8 alignment, 9 faction/team word; the PRO's extended flag `0x2000000` inverts it,
  `0x8000000` switches to the second IDS pair.

## Results (matched 31; 19 of them identical in every field above)
Identical: SPWI207 ice knife, SPWI108 pacify, SPWI211, SPWI405, SPWI406, SPWI213 horror, SPWI307 hold undead, SPWI305
Elysium's tears, SPWI308, BOLT01, SPWI217, SPWI410, SPWI219, SPWI103 embalm (and SPWI305B where mapped).

### PR-1 `NTOKEN` (Hold Person token, projectile 190): radius 240 in EE, 64 in GemRB
- **Status:** V      **Severity:** 2      **By:** opus
- **EE:** `NTOKEN.pro`: area flags `0x40`, trigger and explosion size 240, speed 10, no secondary projectile.
- **GemRB:** `HOLD.pro`: area flags `0x50` (+ secondary projectile `0xC5`), sizes 64, speed 20.
- **Difference:** the hold area is 3.75× wider in EE. Same item as C-8 (NTOKEN animation ids): settle both together.

### PR-2 `SPIN106` fear aura (projectile 269): radius 360 vs 720, target filter differs
- **Status:** V (sizes) / S (filter)      **Severity:** 2      **By:** opus
- **EE:** area flags `0x40`, sizes 360, frequency 0, extended flags `0x04000008`.
- **GemRB:** `FEARAURA.pro`: area flags `0x80`, sizes 720, frequency 15, extended flags `0x02000000` (IDS invert);
  both carry IDS pair `0x3C` = 4/3.
- **Difference:** half the radius in EE; which side is excluded (allies or enemies) depends on how GemRB reads `0x40`
  vs `0x80` and the invert bit: check `Projectile.cpp` area flag constants before the fix.

### PR-3 Bless / Curse (SPPR101 256, SPPR103 257): area filter
- **Status:** S      **Severity:** 2      **By:** opus
- **EE:** Bless area flags `0`, Curse `0x40`; size 597; extended flags `0x8`.
- **GemRB:** `BLESSED.pro` `0xC0`, `CURSED.pro` `0x40`; size 600.
- **To settle:** GemRB's meaning of `0xC0` (both "not allies" and "not enemies") vs EE's 0 (everyone, then the effects'
  own targeting). Curse matches.

### Presentation only (sev 3)
| Projectile | Difference |
|---|---|
| 24 chromatic orb, 279 SPWI218 | EE type 2 (BAM, no area) with flag `0x20` (PST missile), speed 0; GemRB type 3 with an area part (GemRB's extension) |
| 205 MAGICMIS, 272 IMISS, 281 AMISS | EE extended flag `0x20` (PST missile class) |
| 214/276/285 multi-missiles | EE extra flag `0x200000` |
| 230 HOPAND | EE explosion projectile `0x3C`; GemRB area flag `0x2` (Howl is hardcoded: S14) |
| 271 IGNUSFI | speed 50 (EE) vs 40 |
| 60 GHOST, 61 STORMBLD, 290-298 SPWI001-010 | no GemRB PRO at that number (hardcoded spells, WP1 / phase 3) |
