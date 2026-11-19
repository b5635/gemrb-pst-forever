# Hardcoded spells: what the original engine does

Done: 39/39 (all hardcoded spell classes). Machine-readable version: spell_expect.json.

One entry per hardcoded spell class. Each entry: the original's code (from `dev/parity/maps/projectiles.tsv`,
read in `.re/orig/dump/dec/<addr>.c`), the EE class for names, GemRB today, and the differences. The machine-readable
version for `tools/tb_spell_suite.py` is `spell_expect.json`. Durations in effect records are in **seconds** (×15
= ticks) unless marked "ticks". "Pixels" are area coordinates. All numbers are from the original exe.

---

## SPWI912 Abyssal Fury
- **Engine:** projectile 234. Original ctor `sub_6BFEC3`, AIUpdate `sub_6C02F8`, Fire `sub_6C0210`. EE `CPsSpellAbyssalFury`.
- **SPL:** no effects at all (one header, target 1 creature, range 50). Everything happens in code.
- **Targets:** the one creature aimed at. While it runs, the game is frozen (`SetGameFreeze`) and every other
  creature within 1000 of the target has its AI switched off, switched back on at the end.
- **Roll:** saving throw vs death (type 4) through an op 13 (death) effect's save check: five d20 rolls and a d100
  magic-resistance roll.
- **Fail:** instant death (op 13 death, parameter2 = 8, the "chunks" death). Before dying, the victim is tossed
  3–4 times (random target positions on screen), then killed and left as body parts (`S077SPT2`).
- **Save (or the creature can't be killed outright, original creature +3342 set):** the victim is spat back out and
  takes a damage **pool of 5–50**, paid out as op 12 damage, parameter2 0x400000 (magic), 1–5 per hit
  (`min(5, 1..pool)`), one hit each time the victim isn't already playing its damage animation, until the pool is
  empty. Each hit faces the victim randomly and plays `S077SCRT` + `ABYSS06`.
  The SPL text claims 5–510; the code says 5–50.
- **Damage scaling:** EE calls `CheckForIncreasedSpellLevel` on every hit (plane warping, see finding R1).
- **Repeat:** at the end, if the caster has state bit 0x400000 (`STATE_EE_DUPLICATION` in `state.ids`) in both base and
  derived state, the caster force-casts SPWI912 (action 113 ForceSpell) at the same target again.
- **Timing:** zoom in for up to 75 ticks, rift opens (`S077CRVS`, `ABYSS02`), arm grabs (`S077BARM`, `ABYSS04`),
  16 ticks, victim pulled down; fail → 60 ticks then death; save → damage loop; zoom back over up to 75 ticks.
- **Visuals/sounds:** `S077CRVS` `S077BARM` `S077SCRT` `S077SPT2`, sounds `ABYSS02`–`ABYSS07`.
- **GemRB today:** projectile row 233 = `FURY`, but there is no `fury.pro` (suite: "Couldn't find 'fury.pro'").
  The spell does nothing.
- **Differences:** 1) nothing happens at all (finding S1) 2) no save-or-die 3) no 5–50 damage pool
  4) no repeat under state 0x400000.

## SPWI805 Power Word, Blind
- **Engine:** projectile 252. Original ctor `sub_6C8B5C`, AIUpdate `sub_6C8CCE`. EE `CPsSpellPowerWordBlind`.
- **SPL:** no effects (three headers, levels 16+, target 1, range 240).
- **Targets:** everything within **180** of the target point (search `sub_476177`), with HP > −10, not
  `STATE_DEAD` (0x800), and **HP < 100**. Sorted by current HP, lowest first.
- **Pool:** the sum of all those creatures' HP, capped at 100. Creatures are blinded in order while the running
  total of their HP stays within the pool. The first one that would go past it stops the spell (that one and everyone
  after it are untouched).
- **Duration:** picked **once from the pool** (not per creature): pool ≤ 25 → 160–400 s; 26–50 → 80–200 s;
  51–100 → 16–40 s.
- **Effects per target (in code):** op 74 blindness (`State:Blind`), power 8, that duration; op 51
  `Color:DarkenRGB` parameter1 0x40400000, same duration. A spell-hit notice per target (`sub_7BC70E`; EE sends a hit
  trigger).
- **Roll:** none. No saving throw, no magic-resistance roll.
- **Visuals/sounds:** `PWBLI03` (cast), `PWBLI05` (hit); screen flash.
- **GemRB today:** `pwblind.pro` → `PWB.spl`: op 194 FlashScreen, op 74 blindness through GemRB's p2 = 1 hook (duration in ticks from each target's HP), op 51 with
  duration 15. The pool, the HP-sorted order, the 100-HP limit and the random durations are missing.
- **Differences:** 1) no HP pool and no lowest-HP-first order: creatures over 100 HP are blinded too (finding S3)
  2) blindness lasts ticks instead of seconds (GemRB's p2 = 1 hook in `fx_set_blind_state`: 151–390 ticks ≈ 10–26 s instead of 160–400 s), and is chosen per target HP, not from the pool
  3) DarkenRGB lasts 15 s instead of matching the blindness 4) search radius should be 180.

## SPWI909 Power Word, Kill
- **Engine:** projectile 265. Original ctor `sub_6C947A`, AIUpdate `sub_6C9660`, Fire `sub_6C955E`. EE `CPsSpellPowerWordKill`.
- **SPL:** op 13 death (p2 4, delayed 30 s… timing 4 = delay), op 187 `S099HAND`, op 138 sequence, op 193, op 138, op 191 `S099EXPL`.
- **Targets:** **one** creature, the one aimed at.
- **Check:** at launch (Fire) the target's current HP is read: **HP > 120 → the spell fizzles** (`SE10FIZZ` animation,
  `MAGIC01` sound) and none of the SPL's effects are applied. HP ≤ 120 → the SPL's effects are applied to the target
  (vtable +152 after a spell-hit notice, `sub_7BC70E`). The HP is checked once, at launch, not on arrival.
- **Roll:** none.
- **Code effect:** op 205 MoveView (speed 8, p2 1, timing 4 delayed, 45) on the caster so the camera follows.
- **GemRB today:** `pwkill.pro` is an **area** projectile (radius 15, area flags 0x4481: visible, party flag, VVC,
  delay) whose success spell `PWK` (op 205 + op 174 `PWKIL05`) and the SPL effects hit everyone in the radius.
  No HP check.
- **Differences:** 1) no 120-HP limit: anything dies 2) area instead of single target: bystanders within 15 die too
  3) no fizzle path.

## SPWI207 Ice Knife
- **Engine:** projectile 221. Original ctor `sub_6B1129`, AIUpdate `sub_6B1972`, Fire `sub_6B180F`, effect transfer
  `sub_6B1296`, splash `sub_6B23B5`. EE `CPsSpellIceKnife` (`OnArrival`, `CheckForTargets`, `TransferEffects`).
- **SPL:** header picked by caster level, **minimum level 3** (EE `TransferEffects`, original `sub_6B1296`).
  Header 0: op 187 `S025CICY` (caster), op 187 `D005DICE`, op 12 2d4 cold (0x20000). Effects with target "self" go to
  the caster; durations of timed effects are scaled by the caster's mage/priest duration percentage.
- **Roll:** an **attack roll** when the knife arrives (EE `CPlanescape::ProjectileRollToHit`, called with THAC0
  override −127 = use the caster's own THAC0): d20 + caster to-hit + STR to-hit + DEX missile bonus against
  THAC0 − target AC; natural 1 misses, natural 20 hits. Original: the arrival path through vtable +288; the roll
  function is not mapped in the original yet.
- **Hit:** the SPL's effects on the target, plus a **splash within 60** of the impact on every creature (not dead):
  op 12 **1d4 magic cold** (0x4000000), save vs spell (type 1); op 54 **THAC0 −2**, save vs spell, lasting
  **3 s × the level used** (45 ticks × max(3, caster level)). Both go through `CheckForIncreasedSpellLevel` (EE).
- **Miss:** the knife flies on 24 more and shatters with no effect.
- **Visuals/sounds:** `S025PROJ` knife, `S025COLD` ×2 at each splash target, `S025MELT`, `S025PTRZ`, `ICEKN04`–`ICEKN06`.
- **GemRB today:** `iknife.pro` is an area projectile (trigger 5, radius 5, VVC `ICEKN06`) casting `SPWI207` itself
  (2d4 cold). No attack roll, no splash, no THAC0 penalty, no level-3 minimum.
- **Extra knives:** the first cast gives the caster **min(4, (level − 4) / 2 + 1)** more knives (level ≥ 5), fired by
  clicking again (`CPlanescape::MultiFireSpell`, a counter on the caster: EE sprite +20748). SPL text: "1 additional
  dagger every 2 levels after 3rd, max 5".
- **Differences:** 1) no attack roll (finding S4): it always hits 2) no 1d4 splash in 60 3) no −2 THAC0
  4) header choice: GemRB uses the caster's level unclamped 5) no extra knives (GemRB has no multi-fire mechanic).

## SPWI702 Blade Storm
- **Engine:** projectile 232. Original ctor `sub_6BAC7D` (stores the caster level), AIUpdate `sub_6BB6F2`, Fire
  `sub_6BB0A5`. EE `CPsSpellBladestorm`.
- **SPL:** no effects (target 4 = point, range 75).
- **Targets:** **enemies of the caster** (ctor calls `sub_4128C8` = `GetEnemyOf`, EE the same) within **320** of the
  point (searched in 400, then filtered), sorted by distance.
  A ring of blades grows outward; each creature is struck when the ring reaches its distance.
- **Roll:** an attack roll per creature (original `sub_577BD4` = `ProjectileRollToHit`) with a **fixed THAC0 of 11**,
  bonus 0: d20 ≥ 11 − target AC hits, natural 20 always hits, natural 1 misses, helpless targets are always hit.
- **Hit:** op 12 **(caster level)d8 magic cold** (0x4000000), no save. **Critical** (natural 20, target not
  crit-protected): a second op 12 **2d10** magic cold. Miss: nothing.
- **Side effects:** game freeze, area background replaced by `S057BACK` during the spell, spell-hit notice per creature.
- **Visuals/sounds:** `S057BLAD` ×8, `S057FLSH`, `BLADE02`, `BLADE5A`–`C`, `EF01TPRT`.
- **GemRB today:** `bstorm.pro` area radius 400 → `BSTORM.spl`: op 12 **14d8** magic cold **save vs spell**, plus
  op 12 2d10 with a 5% probability.
- **Differences:** 1) saving throw instead of an attack roll against THAC0 11 (finding S4) 2) 14d8 fixed instead
  of caster-level d8 3) the 2d10 is a random 5% instead of a natural-20 critical respecting crit protection
  4) radius 400 instead of 320 (GemRB's enemy-only flag 0x40 matches the enemy filter).

## SPWI901 Celestial Host
- **Engine:** projectile 254. Original ctor `sub_6D7D4B`, AIUpdate `sub_6D83D5` (a ~30-state cutscene), Fire `sub_6D8226`.
  EE `CPsSpellCelestialHost`.
- **SPL:** op 12 **40d3 magic** (0x400000), no save.
- **Targets:** **enemies of the caster** (the caster's `GetEnemyOf` object type; anyone if the caster isn't a creature)
  within **400** of the point. **No enemy in range → the spell fizzles** (`SE10FIZZ`, `MAGIC01`, screen flash) and
  ends at once.
- **Roll:** none.
- **Effects:** late in the sequence (state 25, 14 ticks in) every target gets the SPL's effects through an instant
  projectile. Nothing else is created in code.
- **Side effects:** game freeze for the whole sequence; every other creature within 1000 has its AI switched off and
  back on at the end; camera zoom; the caster's brightness ramps to 255; the **DRAGON movie** plays (state 22,
  original `sub_7D46D0`). EE also swaps the area background to `TORMENT`.
- **Visuals/sounds:** `S091GATE` `S091DEVA` `S091DVAT` `S091SMHT` `S091RAIL` `S091PHNX` `S091HTCH` `S091ARRS`
  `S091ASUN` `S091APPR` `S091GRLY` `S091BLST`, `DBOLT03`, `MOP504`, sounds `CELH102`–`CELH406`.
- **GemRB today:** `chost.pro` area radius 1000, enemy-only flag (0x440), fail spell `FIZZLE`, success `CHOST`
  (op 152 PlayMovie DRAGON, op 197 TintScreen, op 194 FlashScreen), then the SPL's 40d3.
  The suite: the turn never frees (finding S9), and "Couldn't find DRAGON.2da" (the movie subtitle table, parity S13).
- **Differences:** 1) radius 1000 instead of 400 2) the fizzle when no enemy is near isn't modelled (GemRB's fail
  spell only runs on a projectile failure) 3) the hold/hang (S9) 4) bystander AI isn't paused (presentation).

## SPWI914 Rune of Torment
- **Engine:** projectile 255 (EE renumbered it to 300). Original ctor `sub_6D0857`, AIUpdate `sub_6D0AE0`, Fire
  `sub_6D0A6A`. EE `CPsSpellRuneOfTorment`.
- **SPL:** op 12 **14d6 + 16 magic** (p1 16, 0x400000), no save. Target 5 (caster), range 1.
- **Targets:** **enemies of the caster** within **400** of the caster: the factory passes the caster's object type and
  the ctor turns it into `GetEnemyOf` (original `sub_4128C8` in `sub_6D0857`; EE the same). Anyone only when there is
  no casting creature.
- **Roll:** none.
- **Effects:** each target gets the SPL's effects through an instant projectile, once, during the sequence.
- **Side effects:** game freeze for ~130 ticks after the movie, camera zoom; the **RUNE movie** is readied at the
  start (EE `CScreenWorld::ReadyMovie`, original string `aRune`).
- **Visuals/sounds:** `S914RUNE`, `S914BGBL` ×4 (random 0–3 variant), `S914HGBL`, sounds `RUNET03`–`RUNET06`, `CELH406`.
- **GemRB today:** `rotorm.pro` area radius 600, flags 0x50 (enemy + secondary). The suite stalls (finding S9).
- **Differences:** 1) radius 600 instead of 400 2) the hang (S9) 3) the RUNE movie isn't played. (Enemy filter matches.)

## SPWI401 Blacksphere
- **Engine:** projectile 242 (EE renumbered it to 301). Original ctor `sub_6DF730`, AIUpdate `sub_6DFA1E`, Fire
  `sub_6DF84B`. EE `CPsSpellBlacksphere`.
- **SPL:** op 189 PlayBAM3 `S041GLRP` 60 s, op 189 `S041BALL` delayed 15 s, op 39 `State:Helpless` 30 (timing 3),
  **save vs spell**, op 174 `BLACK06`.
- **Effect created in code (Fire):** op 12 damage, **caster level + 1d4 magic** (p1 = level, 0x400000, 1d4), power 4,
  delayed (timing 4) 15, added to the projectile's effect list so it lands with the SPL's effects.
- **Targets:** the projectile's target (single, target type 4 = point; the sphere hits the creature at the point).
- **Roll:** the save vs spell on the helpless effect only; the damage has no save.
- **Side effects:** game freeze while it plays; caster level ≥ 10: a screen shake whose strength is the level.
- **Visuals/sounds:** `S041CAST`, `BLACK03`, `BLACK05`.
- **GemRB today:** row 242 is `BSPHERE`, but there is no `bsphere.pro` ("Couldn't find 'bsphere.pro'"): the spell does
  nothing.
- **Differences:** 1) nothing happens (finding S2) 2) the level+1d4 damage exists only in code.

## SPWI113 Missile of Patience
- **Engine:** projectile 238. Original ctor `sub_6C3EB9`, AIUpdate `sub_6C5197`, Fire `sub_6C3FA4`. EE
  `CPsSpellMissileOfPatience` (`Fire`, `TransferEffects`, `OnArrival`).
- **SPL:** header by caster level: op 12 1 missile damage → op 12 2d10 magic → op 12 2d8 electricity (save vs spell)
  + op 187 `S113BLEX` (see the header levels in the SPL).
- **Targets:** the one creature aimed at. The SPL's creature effects are moved onto a second missile that flies
  the last stretch (45 ticks) to the target.
- **Roll:** none in code (only the SPL's own save on the top header).
- **Level tiers (code, `+1056` = caster level):** ≤ 7, 8–10 and > 10 pick different launch scenes (thrower, sling,
  giant archer). Above 10 the scene takes 375 ticks (675 if the caster has a flag at EE `+4074 & 0x40`), holds
  party input (`CInfGame::SetState 2`) and sets a global "big missile active" flag.
- **One at a time:** while that flag is set, casting another level > 10 Missile of Patience **fizzles** (no effect).
- **Visuals/sounds:** `MOP103`–`MOP905`, `S113BLAP` `S113BLAR` `S113BLDP` `S113BLFR` `S113BOWF` `S113BWAR` `S113SLBL`
  `S113SLNG` `S113SMO*`, `MAGIC01`, `SE10FIZZ`.
- **GemRB today:** `lmiss.pro` is a plain travelling missile (type 2, speed 60) that applies the SPL header for the
  caster's level.
- **Differences:** 1) the one-at-a-time rule above level 10 is missing 2) the long launch scenes (presentation).
  Damage itself matches.

## SPWI802 Meteor Storm Bombardment
- **Engine:** projectile 249. Original ctor `sub_6CA185`, AIUpdate `sub_6CA79D`, Fire `sub_6CA66F`. EE
  `CPsSpellMeteorStormBombardment` (+ `CMeteorStormBombardmentMeteor` for the falling rocks).
- **SPL:** op 12 **10d12** crushing, save vs spell (header 0).
- **Targets:** **enemies of the caster** within **400** of the point, not dead (the ctor `sub_6CA185` turns the caster's
  object type into `GetEnemyOf`, `sub_4128C8`).
- **Roll:** the SPL's save vs spell, nothing else.
- **Effects:** each target gets the SPL effects once, through an instant projectile (45 ticks), when the impact
  phase starts (state 5 → 6). The falling meteors are visual (spacing 8 + random).
- **Side effects:** game freeze while it plays; the **METEOR movie** plays at the start (`METEOR.mve`).
- **Visuals/sounds:** `METEOR`, `S061ROCK`, `S061BEAM`, sounds `METEO02` `METEO05` `METEO06`, `CELH406`.
- **GemRB today:** `mswarm.pro` area radius 256, flags 0x5050 (enemy, secondary, through walls, delay) plus a
  secondary-projectile placeholder `<stoned>` that fails ("Couldn't find '<stoned>.pro'", finding S6).
- **Differences:** 1) radius 256 instead of 400 2) the broken secondary projectile (S6) 3) the METEOR movie isn't played. (Enemy filter matches.)

## SPWI705 Stygian Ice Storm
- **Engine:** projectile 248. Original ctor `sub_6C80A1` (enemy filter `sub_4128C8`), AIUpdate `sub_6C825D`,
  Fire `sub_6C816F`. EE `CPsSpellStygianIceStorm`.
- **SPL:** op 12 8d8 cold (delayed 75), op 189 `S052HOWS`, op 191 `S075DROP`, op 193 (p1 30), op 109 hold (p2 2, 4),
  op 174 `STYGI05`.
- **Targets:** **enemies of the caster** within **400** of the point.
- **Effect created in code:** op 128 **confusion**, power 7, delayed (timing 3), **save vs spell**, duration
  **10–35 s** rolled per target, added to each target's copy of the SPL effects.
- **Roll:** the confusion's save; the SPL's own effects as written.
- **Side effects:** game freeze while it plays.
- **Visuals/sounds:** `S075WDSH`, `STYGI02`–`STYGI04`.
- **GemRB today:** `istorm.pro` area radius 400, enemies only (0x440), no helper spell: only the SPL's effects.
- **Differences:** 1) the confusion (10–35 s, save vs spell) is missing. Radius and filter match.

## SPWI603 Howl of Pandemonium
- **Engine:** projectile 231. Original ctor `sub_6B9DFE`, AIUpdate `sub_6BA295`, Fire `sub_6BA08E`. EE
  `CPsSpellHowlOfPandemonium`.
- **SPL:** op 187 `S055SKLC`, op 138 sequence, op 89 missile resistance +100 on the caster (10 s), op 174 `HOWL05`.
- **Effects created in code (Fire):** op 45 **stun** and op 128 **confusion**, both **save vs spell**, duration
  **50–300 s** (one roll per cast), timing 0.
- **Who gets which (EE AIUpdate):** a target of **level ≤ 2** gets the stun (not the confusion); a target of level
  **3 up to one below the caster's level** gets the confusion (not the stun); higher levels get neither. A
  non-creature caster counts as level 11. Matches the SPL text ("2HD or less … incapacitated 10–60 minutes; greater
  than 2HD but less than the caster's … confused"). Original: the split was not located in `sub_6BA295`; it is
  probably in the skull missile's transfer. Status S for the split, V for the effects and duration.
- **Targets:** every creature within **400** (the ctor `sub_6B9DFE` has no enemy filter). Each gets a skull missile (the magic
  missile class `sub_6AB093`) carrying the effects; at least 8 skulls fly even with fewer targets.
- **Side effects:** op 195 TintScreen (color 0xB44040, 10) at the start; game freeze.
- **Visuals/sounds:** `S055CAST` `S055PSKL`, `HOWL03` `HOWL04`.
- **GemRB today:** `hopand.pro` area radius 400, flags 0x482 (inanimate, party, VVC `HOWL04`), no helper spell. Only
  the SPL's effects apply: **no stun and no confusion at all**.
- **Differences:** 1) the spell's whole purpose (stun/confusion by level, save vs spell, 50–300 s) is missing
  2) target filter: GemRB's flags differ from "everyone in 400".

## SPWI108 Pacify
- **Engine:** projectile 222. Original ctor `sub_6B2925`, AIUpdate `sub_6B2B9F`, Fire `sub_6B29BF`. EE `CPsSpellPacify`.
- **SPL:** op 187 `S013STAR` (caster), op 187 `S013SPKL`, op 194 flash, op 174 `PACIF03`.
- **Targets (Fire sets two filters):** include = **enemies of the caster** (`sub_4128C8`); exclude = object type
  general 4 (**undead**). In AIUpdate, within the projectile's radius, up to **2–8** creatures (one roll per cast),
  each one: a creature, not dead, not already pacified (derived state 0x400 clear), matching the filters, and of
  **level ≤ 6** (class level via `sub_446509`).
- **Effects created in code, per target, save vs spell (type 1), power 1:**
  op 109 hold (p2 2) for **5 × caster level + 40 s**; op 8 color glow (p1 0xC8000000, p2 = duration / 6) for the same time;
  op 186 SetStatus p1 1, p2 0x400 (the "pacified" bit that stops a second Pacify) for the same time;
  `I001ZZZZ` sleep animation over the creature until the effect ends.
- **No target:** fizzle (`SE10FIZZ`, `MAGIC01`).
- **Visuals/sounds:** `PACIF05`, `TRAVEL`.
- **GemRB today:** `pacify.pro` area radius 2160, flags 0x4040 (enemy, delay), fail `FIZZLE`, success `PACIFY`:
  op 109 + op 8 + op 187 `I001ZZZZ`, all 50 s, save vs spell.
- **Differences:** 1) fixed 50 s instead of 5 × level + 40 2) no 2–8 target cap 3) no level ≤ 6 limit 4) undead
  not excluded 5) no op 186 "already pacified" bit (re-casting stacks) 6) glow p2 2 instead of duration/6.

## SPWI307 Hold Undead
- **Engine:** projectile 237. Original ctor `sub_6C35A3`, area effect `sub_6C36EC` (EE `CPsSpellHoldUndead::AreaEffect`),
  Fire `sub_6A682F`; it is an area projectile (generic AIUpdate `sub_56B042`).
- **SPL:** no effects.
- **Targets:** only **undead** are listed (include filter: general 4) within **2160** of the point, closest first;
  at most **1–3** of them (rolled once in the ctor, `rand() % 3 + 1`), and only while the **sum of their levels stays
  ≤ the caster's level** (HD pool). Matches the SPL text ("1-3 undead … total HD ≤ caster level").
- **Effect created in code, per target:** op 109 hold, p1 4 / p2 3 (only GENERAL = UNDEAD is held), timing 3, special 15,
  duration **5 × caster level + 5–20 s** (one roll per cast). **Save vs spell only for targets of level ≥ 3**; level
  1–2 get no save.
- **Roll:** that save.
- **Visuals/sounds:** `S037HOLD`, `HOLDU03`, `HOLDU05`.
- **GemRB today:** `holdund.pro` area radius 2160, flags 0x8400 (**affect one target only**, VVC), success `HOLDUND`:
  op 109 p1 4 p2 3, 50 s, **no save**.
- **Differences:** 1) one target instead of 1–3 undead within an HD pool equal to the caster level 2) fixed 50 s
  instead of 5 × level + 5–20 3) no save for level ≥ 3 undead.

## SPWI506 Fire and Ice
- **Engine:** projectile 245. Original ctor `sub_6D3923`, AIUpdate `sub_6D3E4F`, Fire `sub_6D3BCE`. EE `CPsSpellFireAndIce`.
- **SPL:** no effects.
- **Effect created in code (ctor):** op 12 **3d6 magic fire** (0x2000000), power 5, **save vs spell**.
- **Sequence:** the fireball flies to the target and bursts: every creature within **360** of it **except the caster**
  (no enemy filter) gets a copy of the effect (plus a hit trigger). The ball then turns 120–240°, flies on, and
  bursts again with the same effect switched to **magic cold** (0x4000000): a second 3d6, save vs spell, to everyone
  within 360 of the second point.
- **Side effects:** game freeze while it plays.
- **Visuals/sounds:** `S056FRBL` `S056FTRL` `S056FEXP` (fire), `S056ICBL` `S056ICBM` `S056ITRL` (ice), `FIREA02`–`FIREA07`.
- **GemRB today:** `fireice.pro` area radius 256, flags 0x408, success `ICE`: op 12 3d6 **magic fire**, save vs spell.
  One burst.
- **Differences:** 1) the second (cold) burst is missing 2) radius 256 instead of 360 3) the caster isn't excluded.

## SPWI804 Ignus' Fury
- **Engine:** projectile 251. Original ctor `sub_6D6ECE` (enemy filter, stores the caster level), AIUpdate `sub_6D72E3`,
  Fire `sub_6D71A7`. EE `CPsSpellIgnusFury`.
- **SPL:** op 187 `S055BURN`, op 191 `S084CRAK`.
- **Targets:** **enemies of the caster** within **400** of the point.
- **Effect created in code:** op 12 **10d10 + caster level fire** (p1 = caster level, 0x80000), power 8, timing 4
  (delayed 15), **save vs spell**, through an instant projectile per target together with the SPL's effects.
- **Side effects:** game freeze while Ignus' head plays.
- **Visuals/sounds:** `S084IGHD`, `IGNFU05`.
- **GemRB today:** `ifury.pro` area radius 400, enemies (0x4440), success `IFURY`: op 12 10d10 **+16** fire, save vs spell.
- **Differences:** 1) flat +16 instead of + caster level (equal only at level 16).

## SPWI212 Swarm Curse
- **Engine:** projectile 218, secondary swarms projectile 219. Original ctor `sub_6AD801`, AIUpdate `sub_6ADBED`, Fire
  `sub_6ADB37`; secondary `sub_6AEE09` / `sub_6AEEC0` / `sub_6AEEE5`. EE `CPsSpellSwarmCurse`.
- **SPL:** op 188 swarm animations (`S030SWFM` caster, `S030SWEX`, `S030SWAT` 15 s), op 60 miscast magic +100 (p2 0 and
  p2 1) for 15 s.
- **Effect created in code (ctor):** op 12 **1d4 + level / 3 magic** (0x400000), power 2, **save vs spell** (original
  save type 1; EE dropped the save and ignores magic resistance instead).
- **Spread radius:** **36 × min(caster level, 13)** (original word +742, max 468).
- **Sequence:** the swarm flies to the target (hit trigger). On arrival, every creature within the spread radius
  is sorted by distance and gets its own swarm (projectile 219) carrying the SPL's effects plus the damage.
  Target side (EE): if the caster is evil-aligned (EA above GOODCUTOFF) the swarms go for the good side, otherwise for
  the not-good side. EE checks each new victim with a save (`CheckAdd`) before the swarm moves on to it.
- **Visuals/sounds:** `S030SWPR`, `S030SWEX`, `SWARM03`–`SWARM05`, `TRAVEL`.
- **GemRB today:** `iswarm.pro` single target (radius 0), success `ISWARM`: op 12 1d4 magic, no save.
- **Differences:** 1) no spread to nearby creatures 2) no + level/3 3) no save vs spell. (The suite reported "nothing
  happened" because 1d4 and the SPL's miscast effects are easy to miss.)

## SPWI604 Chain Lightning Storm
- **Engine:** projectile 246. Original ctor `sub_6CC30B` (enemy filter), AIUpdate `sub_6CD28D`, Fire `sub_6CC71A`. EE
  `CPsSpellChainLightningStorm`.
- **SPL:** op 12 **7d10 electricity**, save vs spell.
- **Targets:** **enemies of the caster** within **400** of the point, not dead, sorted by distance; the bolt jumps
  from one to the next. Every target gets the **full** SPL effects (no reduction per jump, no jump limit).
- **No enemy in range:** fizzle (`SE10FIZZ`, `MAGIC01`).
- **Roll:** the SPL's save.
- **Visuals/sounds:** `S064BGLT` `S064HGLT` `S064LORT` `S064UPLT`, `CHAIN03`–`CHAIN05`.
- **GemRB today:** `lstorm.pro` area radius 400, enemies (0x40), the SPL's effects.
- **Differences:** none in the numbers; only the fizzle-with-no-target path and the bolt visuals. **Parity (P).**

## SPWI803 Deathbolt
- **Engine:** projectile 250. Original ctor `sub_6CE6D9`, AIUpdate `sub_6CE927`, Fire `sub_6CE849`, Render `sub_6D0802`.
  EE `CPsSpellDeathBolt`.
- **SPL:** op 193 (p1 75), op 191 `S083DBHT`, op 13 death (p2 4, delayed 15) **save vs death**, op 12 **10d6
  electricity** (delayed 15). Plane warping adds to it in Carceri/Baator/Negative Material (finding R1).
- **Targets:** the one creature aimed at. The SPL effects are applied at the end of the sequence (vtable +144).
- **Side effects:** every other creature within 1000 has its AI paused for the sequence and resumed at the end;
  party input held (game state flag); screen sequence with the background bolt (`S083BGCL`).
- **Roll:** the SPL's save vs death.
- **Visuals/sounds:** `S083BOLT` `S083BGCL` `S083CLDS` `S083FLSH`, `DBOLT03` `DBOLT05` `DBOLT06`, `CHAIN03`.
- **GemRB today:** `dbolt.pro` area trigger/radius 5 (0x400 VVC), fail `FIZZLE`, success `DBOLT` (op 197 TintScreen),
  then the SPL. Error "Couldn't find 'DBOLT.bam'" (finding S11).
- **Differences:** effects match; the missing BAM (S11) and the sequence are presentation. Radius 5 can catch a
  second creature standing on the target (the original hits only the target).

## SPWI505 Desert Hell
- **Engine:** projectile 244 (factory: enemy filter `sub_4128C8`). Original ctor `sub_6C6AA4`, AIUpdate `sub_6C6ED9`,
  Fire `sub_6C6E12`. EE `CPsSpellDesertHell`.
- **SPL:** op 187 `S055BURN`; op 110 RetreatFrom (p2 7) delayed 30/60/90/120/150; op 12 **1d10 fire**, save vs spell,
  delayed 30/60/90/120 (four hits); op 174 `DESER05`.
- **Targets:** **enemies of the caster** within **400** of the point; each gets the SPL's effects through an
  instant projectile.
- **Side effects:** game freeze while the scene plays; area background replaced by `S055DSRT` and restored.
- **Visuals/sounds:** `S055DSRT`, `EF01TPRT`, `DESER03`, `MAGIC02`.
- **GemRB today:** `dhell.pro` area radius 2160, enemies (0x4440), success `DHELL`: op 207 (target 4), op 199
  ChangeBackground `S055DSRT` 10, op 195 TintScreen, op 207 again (delayed 10), op 188 `EF01TPRT`, op 174 ×2. Error
  "Couldn't find 'T_FIRE1.bam'" (finding S11).
- **Differences:** 1) radius 2160 instead of 400 2) GemRB uses op 207 (in the original op 207 is the game-freeze opcode,
  finding E4) to fake the freeze: check it is released.

## SPWI902 Conflagration
- **Engine:** projectile 270. Original ctor `sub_6D506D`, AIUpdate `sub_6D538D`, Fire `sub_6D51C8`. EE `CPsSpellConflagration`.
- **SPL:** op 201 Overlay **type 13 (conflagration)**, 10 s, `S092FLMD`: the overlay does the burning.
- **Targets:** the one creature aimed at.
- **Sequence:** the **CONFLAG movie** (`CONFLAG.mve`) plays; every other creature within 1000 is paused; at frame 6
  of the pillar animation the target gets op 66 **translucency 128** for the rest of the animation; at frame 50 the
  SPL's effects land (instant projectile, 45 ticks).
- **Roll:** none in code (the overlay's own rules).
- **Visuals/sounds:** `S092CONF`, `A010SPIN`, `AURA_11A`, `CONFL05`.
- **GemRB today:** `conflag.pro` is a plain missile (type 2) applying the SPL. GemRB's `fx_overlay` case 13 handles the
  burn. "Couldn't find 'CONFLAG.2da'" is the movie subtitle lookup (parity S13).
- **Differences:** effects match if `fx_overlay` case 13 matches the original overlay (check in WP2); movie and
  translucency are presentation.

## SPWI905 Elysium's Fires
- **Engine:** projectile 233. Original ctor `sub_6BE9A4` (builds 8 fireballs `sub_6BF4DD`), AIUpdate `sub_6BEE11`,
  Fire `sub_6BED2E`; fireball class AIUpdate `sub_6BF705`. EE `CPsSpellElysiumsFires`.
- **SPL:** op 191 `S095CAST` (caster), op 12 **5d4 fire**, save vs spell.
- **Sequence:** **8 fireballs**, launched 15 ticks apart starting from a random one, land at fixed offsets around the
  target point: (0,−150) (120,−75) (240,0) (120,75) (0,150) (−120,75) (−240,0) (−120,−75). Each explodes with
  radius **240** and applies the SPL's effects to every **enemy of the caster** in it (`sub_4128C8`). Overlapping
  explosions hit the same creature again: up to 8 × 5d4 near the centre.
- **Roll:** the SPL's save, per fireball.
- **Visuals/sounds:** `S095PROJ`.
- **GemRB today:** `elyfire.pro` area radius 256, flags 0x8008 (**one target only**, delayed): one 5d4 to one creature.
  Error "Couldn't find 'T_FIRE1.bam'" (finding S11).
- **Differences:** 1) one hit on one creature instead of 8 explosions of radius 240 on all enemies 2) no
  multi-hit near the centre.

## SPWI305 Elysium's Tears (+ CPsSpellElysiumsTearsMeteor)
- **Engine:** projectile 239 (and 280, the same class in another colour). Original ctor `sub_6BD34B` (builds the
  meteors `sub_6BDE3A`), AIUpdate `sub_6BD6D5`, Fire `sub_6BDD57`; meteor AIUpdate `sub_6BDF3C`. EE
  `CPsSpellElysiumsTears`, `CPsSpellElysiumsTearsMeteor`.
- **SPL:** op 191 `S070CSTR` (caster), op 12 **1d2 crushing**, op 12 **1d4 fire**.
- **Meteors:** **min(caster level, 10)**, launched 15 ticks apart, all at the target creature (enemy filter of the
  caster on the main object).
- **Roll per meteor:** an attack roll (original `sub_577E7C` with THAC0 −127 = the caster's own THAC0; EE
  `ProjectileRollToHit`). **Hit:** the SPL's effects on the target, and a **splash of op 12 1 fire** (flat, no dice)
  on every other creature within **80** except the caster. **Miss:** the meteor lands 30–60 below / ±10 beside the
  target and fizzles (`SE10FIZZ`, `MAGIC01`); no damage.
- **Visuals/sounds:** `S070BOMB`, `S070BOOM`, `ELYST04`, `ELYST05`, screen flash in the meteor colour.
- **GemRB today:** `elytear.pro` area radius 1 (flags 0x108): the SPL once.
- **Differences:** 1) one hit instead of up to 10 meteors 2) no attack roll per meteor (finding S4) 3) no 1-fire
  splash in 80.

## SPWI501 Cloudkill
- **Engine:** projectile 230. Original ctor `sub_6B84CD` (enemy filter of the caster), AIUpdate `sub_6B8C20`, Fire
  `sub_6B86C2`. EE `CPsSpellCloudKill`.
- **SPL:** op 13 death with the dice fields used as level bands (3d0 → no save; 5d4 → save vs death −4; 6d6 → save vs
  death), op 12 **1d10 poison**.
- **Targets:** **enemies of the caster** within **400** of the cloud's start point, sorted by distance; the cloud
  rolls over them in that order and each gets the SPL's effects when it is reached.
- **Roll:** the SPL's saves.
- **Visuals/sounds:** `S056CKLL`, `CLOUD03`, `TRAVEL`; the camera follows the cloud.
- **GemRB today:** `cloudkil.pro` area radius 400, enemies (0x40), VVC `CLOUD03`: the SPL to every enemy at once.
- **Differences:** none in effects (**P**). The original hits nearer enemies first as the cloud moves; GemRB hits all at
  once. Check that GemRB reads op 13's dice fields as level bands the way the original does (WP2, op 13).

## SPWI309 Vampiric Touch
- **Engine:** projectile 263. Original: a generic projectile built inline in `sub_559A5D` case 263 (vtable `off_8DF4B0`,
  Fire slot = the empty default `sub_579700`): **no special code in the original**. EE `CPsSpellVampiricTouch::Fire`
  adds an exclude filter for undead (`G_UNDEAD`) and a **touch attack roll** (`ProjectileRollToHit`, THAC0 = the
  caster's): miss → `SE10FIZZ` + `MAGIC01`, no effect.
- **SPL:** op 189 `S039VRUP`/`S039VRDN`/`S039VPRP` visuals, op 192 **TransferHP 2d6** (p2 1, delayed 60), op 194
  flash.
- **Targets:** the creature touched (range 1).
- **Roll:** original none found (status **S** for EE's roll and undead exclusion: EE only so far); the TransferHP
  rules are finding R3.
- **GemRB today:** `vtouch.pro` missile (type 2, speed 40) with fail `FIZZLE`; the SPL applies on arrival.
- **Differences:** against the original none found in projectile code; against EE: no touch roll, undead not excluded.
  Decide which to follow (PARITY_PLAN ground rule: the original, unless the EE change is a fix we want).

## SPWI308 Tasha's Unbearable Derisive Laughter
- **Engine:** projectile 240. Original ctor `sub_6C3A8C`, area effect `sub_6C3C6E` (EE `CPsSpellTashasLaughter::AreaEffect`),
  generic area AIUpdate/Fire.
- **SPL:** op 0 AC −2, op 73 damage −2, op 54 THAC0 −2, all **save vs spell**, timing 3, 25; op 191 `S038TSHA`; op 9
  glow; op 174 `TASHA03`.
- **Targets:** creatures within **600** of the point matching the include filter **gender 1 (male)** and not the
  exclude filter **general 4 (undead)**. Each gets the SPL's effects through an instant projectile.
- **Quirk (both games):** the creatures are walked in list order and the **first one with INT ≤ 4** (derived stat byte
  +49 in the original) **ends the spell**: it and everyone after it are skipped. The SPL text says such creatures are
  merely immune.
- **Roll:** the SPL's saves.
- **GemRB today:** `tlaugh.pro` area radius 600, enemies only (0x40). "Couldn't find SPBOOM/SPRING" (parity S12).
- **Differences:** 1) GemRB affects female creatures too, and undead 2) GemRB filters to enemies; the original
  doesn't (party males are hit too) 3) no INT check (decide whether to copy the quirk or the SPL text).

## SPWI408 Shroud of Shadows
- **Engine:** projectile 229. Original ctor `sub_6B77BF` (rolls N = **3–6**), AIUpdate `sub_6B7FAA`, Fire `sub_6B78E7`.
  EE `CPsSpellShroudOfShadows`.
- **SPL:** no effects.
- **Effects created in code (Fire), on the target (the caster, range 1), no save, timing 0, duration
  **51 × N / 15 s** = 10, 13, 17 or 20 s:** op 0 **AC +3** (p1 3, p2 0); op 59 **stealth +10**; op 66 translucency 128;
  op 201 overlay **type 5** `S048SPHR`.
- **Visuals:** 2N − 1 shadow sprites circling (random start angles), `S048CRTR`, sounds `SHROU03`, `SHROU05`.
- **GemRB today:** `sshadow.pro` missile, success `SSHADOW`: op 0 AC 3 for 150 s **with a save vs spell**; op 59 with
  **p1 0, duration 0**; op 66 128 with **duration 0**; op 201 type 5 for 150 s **with a save vs spell**.
- **Differences:** 1) 150 s instead of 10–20 s 2) the caster can "save" against their own AC bonus and overlay
  3) stealth bonus 0 instead of +10, and stealth/translucency last no time.

## SPWI602 Globe of Invulnerability
- **Engine:** projectile 266. Original ctor `sub_6C9C06`, AIUpdate `sub_6C9D26`, Fire `sub_6C9C7A`. EE
  `CPsSpellGlobeOfInvulnerability`.
- **SPL (one header, level 12):** op 102 protection from spell levels 1, 2, 3 and 4, **3 s** each; op 9 glow 4 s.
- **How it works:** the globe is an object at the caster that lives **75 × caster level ticks (5 s per level)**. Every
  **51 ticks** it gives **every creature within 120** (no filter: allies, enemies and the caster) a fresh copy of the
  SPL's 3-second protections. Stepping out of the globe ends the protection within 3 s; stepping in gains it.
- **Visuals/sounds:** `S062GLOB`, `S034DSPR`, `SHIEL06`, `GLOBE03`–`GLOBE05`.
- **GemRB today:** `goinvul.pro` radius 0: the SPL **once, on the caster only**, so the protection lasts **3 s**;
  helper `GOINVUL` plays the visuals.
- **Differences:** 1) protection lasts 3 s instead of 5 s per level 2) only the caster instead of everyone within 120
  of the globe 3) no refresh.

## SPWI103 Minor Embalming (also SPWI205 Embalming)
- **Engine:** projectile 289. Original: generic class built inline (ctor `sub_578200`), Fire `sub_6DF340`. EE
  `CPsSpellEmbalming::Fire`.
- **SPL (SPWI103):** op 187 `S013MINR`, op 138 sequence **27**, op 206 Embalm 150 s, op 174 `MINEM05`.
- **Check (Fire):** the target must be a creature, not dead, and **either undead (general 4) or flagged at creature
  +3342** (original; EE +4172: the flag that also stops Abyssal Fury's instant death, i.e. the immortal Nameless One).
  Otherwise the spell **fizzles** (`SE10FIZZ`, `MAGIC01`) and nothing is applied.
- **GemRB today:** `embalm.pro` missile with fail `FIZZLE`; no target-type check, so living creatures get embalmed
  too. Suite: "Tried to set invalid stance id(27)": GemRB rejects op 138's sequence 27.
- **Differences:** 1) the undead-or-immortal check is missing 2) op 138 sequence 27 isn't supported (WP2, op 138).

## SPWI211 Strength, SPWI219 Power of One, SPWI406 Improved Strength
- **Engine:** projectiles 223 / 287 / 228. Original Fire `sub_6B351C` / `sub_6B3EDB` / `sub_6B4AA5` (no AIUpdate of
  their own). EE `CPsSpellStrength` / `CPsSpellPowerOfOne` / `CPsSpellImprovedStrength::Fire`.
- **SPL:** visuals and sounds only (`S029GLOW`, `S029STMN`, `S046ISTM`, `STREN05`, `ISTREN05`).
- **Effect created in code:** op 44 Strength in **set** mode (p2 1) to the target's current STR + a roll, timing 0,
  and op 9 glow. Nothing happens if the target's STR is already above 18.

  | | Mage (class 1) | Cleric (3) / Thief (4) | Others (fighters) | Duration |
  |---|---|---|---|---|
  | Strength | +1d4 | +1d6 | +1d8 | **300 s × caster level** |
  | Power of One | +1d4+1 | +1d6+1 | +1d8+1 | **150 s × caster level** |
  | Improved Strength | +1d4+4 | +1d6+4 | +1d8+4 | **5 s × caster level** |

  The result is clamped to 1–18. For "others" only, the part above 18 becomes **exceptional strength** (op 97,
  10 points per STR point over 18, capped at 100). Improved Strength also has per-class ceilings 21 / 23 / 25 (mage /
  cleric-thief / others), and afterwards op 93 **fatigue +100**, delayed (timing 3) by 510 × 1–3 ticks.
- **Carceri warping (`sub_7BD15D`):** in AR0900, AR0901, AR0902, AR0904, AR3015 and AR3016, when the target isn't a
  creature or a check named `CARCERSK` (flag 0x8000) passes, the roll is **subtracted** (multiplier −1) and `MAGIC02`
  plays. Strength spells weaken there. Not in finding R1 yet.
- **GemRB today:** `strength.pro` / `poone.pro` / `istr.pro` missiles → `STR` / `POO` / `IMPSTR`: op 9 glow + op 201
  overlay **type 17** (GemRB's own extension in `PSTOpcodes.cpp:906`): 1d(class die from `clssplab.2da`) + 0 / 1 / 4,
  a STR limit from the duration field, durations hour × level, ×½, 5 × level.
- **Differences:** 1) the cap logic is inverted (finding S7): e.g. STR 17 + 1 gives no gain 2) no exceptional-strength
  overflow for fighters 3) no Improved Strength fatigue afterwards and no 21/23/25 ceilings (unless `clssplab.2da` has
  them) 4) no Carceri reversal 5) check GemRB's hour (`Time.hour_sec`) equals 300 s.

## SPWI405 Force Missiles, SPWI410 Elemental Strike
- **Engine:** projectiles 227 (Force) and 281 (Elemental), one class. Original ctor `sub_6B6A9D`, AIUpdate `sub_6B75B0`,
  Fire `sub_6B6C7F`, impact callback `sub_6B6DF8`. EE `CPsSpellForceMissile` (`TransferEffects`, `CallBack`).
- **SPL:** SPWI405: op 191 visuals, op 12 **2d4 magic**, no save. SPWI410: op 12 **2d4 fire**, op 195 tint, visuals.
  Header by caster level, **minimum level 7**.
- **Impact splash (callback):** every creature (not dead) within **72** of the impact, the target included, takes op 12
  **damage = the level used** (flat, magic 0x400000), power 4, **save vs spell** negates; spell-hit notice each.
- **Extra missiles:** the first cast gives the caster **min(6, (level − 7) / 2)** more missiles (multi-fire counter,
  as Ice Knife). SPWI410's text says "every 3rd level"; the EE code uses the same /2 formula for both. Original: not
  checked yet.
- **Roll:** none on the missile; save vs spell on the splash.
- **Visuals/sounds:** `S045FMSL`, `S045FCST`, `S045DFRC`, `FORCE03`, `FORCE05`.
- **GemRB today:** `fmiss.pro` / `estrike.pro` plain missiles applying the SPL.
- **Differences:** 1) no level-damage splash in 72 (save negates) 2) no extra missiles 3) no level-7 minimum for the
  header.

## SPWI301 Ball Lightning
- **Engine:** EE has `CPsSpellBallLightning` / `CBallLightningSphere` (factory cases 224/225, original ctors `sub_6B54C0`,
  `sub_6B5B4E`), but **no SPL uses projectile 224 or 225** in either game. SPWI301 has one header (level 5),
  **projectile 1 and no effects**, identical in the original, EE and GemRB.
- **Result:** the spell does nothing in the original either (cut content). **Parity (P).** Don't "fix" it.

## SPWI310 Ax of Torment
- **Engine:** projectile 241. Original ctor `sub_6C5975`, AIUpdate `sub_6C5CAA`, Fire `sub_6C5AB7`. EE `CPsSpellAxOfTorment`.
- **SPL:** op 12 1d8 missile, save vs spell; op 187 `S031EXPL`.
- **Effect created in code: one random outcome on the target**, power 3, resource `NEG`, save vs spell unless noted:
  - caster level ≤ 8 (one in three each): op 12 **1d8 missile**; op 12 **2d8 missile**; op 109 **hold** (p2 2) for
    1–3 rounds (original 51 × (1–3) / 15 = 3, 6 or 10 s).
  - caster level > 8 (one in five each): op 12 **5d8 fire**; op 12 **6d8 cold**; op 124 **teleport** to a random point
    within ±300 of the target; op 134 **petrification**, **save vs death**; op 12 **8d8 missile**.
- **Side effects:** screen shake of strength ±2 × level; game freeze while the ax swings.
- **Visuals/sounds:** `S031AXST`, `S031GRRN`, `S031LSRN`, `AXOFT03`–`AXOFT06`; fizzle `SE10FIZZ` + `MAGIC01` if the target
  is gone.
- **GemRB today:** `aotorm.pro` missile → `AXOFT`: 1d8 / 2d8 / hold **100 s**, 33% each, no save on the hold.
- **Differences:** 1) the level > 8 table (5d8 fire, 6d8 cold, teleport, petrify, 8d8) is missing 2) hold lasts 100 s
  instead of 3–10 s 3) no save on GemRB's outcomes.

## SPWI807 Mechanus' Cannon
- **Engine:** projectile 253. Original ctor `sub_6D2652`, AIUpdate `sub_6D27E5`, Fire `sub_6D26FE`. EE `CPSTSpellMechanusCannon`.
- **SPL:** op 12 **20d4 + 10 electricity**.
- **Sequence:** the **CANNON movie** (`CANNON.mve`) plays, then the cannon fires at the target (`S087BLST`, `MECHA04`,
  `MECHA05`) and the SPL's effects land. Camera zoom and game freeze while it plays. No code-made effects.
- **GemRB today:** `mcannon.pro` missile → `MCANNON` helper: op 152 PlayMovie CANNON, flash, `S087BLST`, op 193, sound;
  then the SPL.
- **Differences:** none in effects (**P**).

## SPPR204 Spiritual Hammer
- **Engine:** projectile 260. Original ctor `sub_6D1D4E`, AIUpdate `sub_6D1F52`, Fire `sub_6D1E11`. EE `CPSTSpellSpiritualHammer`.
- **SPL:** no effects.
- **Hammer:** enchantment **+min(3, level / 6 + 1)**; **(level + 2) / 3 attacks**. Each attack is an attack roll
  (original `sub_577E7C`, THAC0 = the caster's, to-hit bonus = the enchantment). Each hit: op 12 **2d4 + enchantment + 2
  crushing**, power 2, delayed (timing 4). The last attack missing shows a fizzle (`SE10FIZZ`, `MAGIC01`).
- **Visuals/sounds:** `SP24SPHM`, `SPIRI02`, `SPIRI05`.
- **GemRB today:** `shammer.pro` missile with fail `FIZZLE`, success `SHAMMER`.
- **Differences:** check `SHAMMER.spl` against the above: number of attacks, the attack roll per blow and the
  enchantment bonus are code-only in the original (GemRB has no roll, finding S4).

## SPPR301 Call Lightning
- **Engine:** projectile 261. Original ctor `sub_6DEB14`, AIUpdate `sub_6DECB2`, Fire `sub_6DEBE5`. EE `CPSTSpellCallLightning`.
- **SPL:** no effects.
- **Strike:** at frame 5 of the bolt, every creature within **120** of the point (no enemy filter) gets op 12
  **(caster level + 2)d8 electricity**, power 3, **save vs spell**. Screen flash and shake.
- **Visuals/sounds:** `CALLL03`, `CHAIN04`.
- **GemRB today:** `callih.pro` area radius 10, success `LIGHTNIN`: op 12 **2d8** electricity, no save, delayed 15.
- **Differences:** 1) 2d8 instead of (level + 2)d8 2) radius 10 instead of 120 3) no save vs spell.

---

## Plain projectiles with effects added by the factory (`sub_559A5D`)

Three ordinary projectiles get effects in code, in the original's factory itself:

| Projectile | Spell | Original (case in `sub_559A5D`) | GemRB helper | Difference |
|---|---|---|---|---|
| 226 BBRIDGE | SPWI204 Blood Bridge | op 192 TransferHP **p1 = caster level + 2** | `BBRIDGE`: op 192 p1 **2** | fixed 2 instead of level + 2 |
| 247 ASTORM | SPWI701 Acid Storm | radius 400, enemies; op 9 glow 30 (delayed); op 186 status 0x4000, 30; op 12 **1d6 acid**, save vs spell, **delayed 20** | `ASTORM`: same ops, op 12 delayed **2** | damage lands 2 s instead of 20 s after |
| 259 FFIRE | SPPR105 Faerie Fire | radius 480; op 9 glow and op 0 **AC −2** for **20 s × caster level** (delayed, special 15) | `FAERIE`: op 9 + op 0 −2 for **20 s** | duration not scaled by level |
