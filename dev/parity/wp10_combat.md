# Track B1: combat rules vs PST:EE (`wp10_combat.md`)

Judged against PST:EE `Torment64` (`.re/ee/dump/dec_all_named`). `CChitin::ENGINE_MODE == 3` is PST (set from
`engine_mode` in the game's Lua; `CBaldurChitin::GetScreenShotFilePrefix` picks the PLANESCAPE prefix for 3), so
every `ENGINE_MODE != 3` branch below is **off** in PST:EE. Static constants read with `tools/parity/eeconst.py`.

Done: attack roll, critical hits/misses, weapon damage, saving throw roll, magic resistance roll, death threshold,
save-for-half, morale, attacks per round, spell disruption, XP (C-1 to C-23). Track B1 done.

## How EE resolves a weapon attack (reference)
`CGameSprite::Swing` (9D7DB0) → `CGameSprite::Hit` (9A8270, the roll) → `CGameSprite::Damage` (9A96D0, builds the
damage) → an **op 12 damage effect** applied to the target (`CGameEffectDamage::ApplyEffect`, 6FD410).
- **Roll** (`Hit` :174-183): raw = d20 (`ATTACK_DICE` 20); lucky = clamp(raw + attacker luck, 1, 20).
- **Needed** (:172) = attacker THAC0 (derived +16) − target AC (derived +6), then +3 NTOKEN (:191), +4 Dead_Truce
  (:200), + target's DEX AC column when an invisible backstabber attacks (:452-472).
- **Total** = lucky + damage-type AC modifier of the target (:226-306, positive = worse AC) + sprite hit mod (:310) +
  weapon/hand THAC0 bonus (:410-441) + berserk 2 (:399) − `INVISIBILITY_MOD` (−4) when the attacker is invisible and
  the attack isn't ranged (:443-451) + `INVISIBILITY_MOD` when the target is invisible / improved-invisible and the
  attacker can't see it (:478-487) + range modifier for ranged attacks (:512-553) + hated race 4 (rangers; none in PST)
  + Iron Fist 3 (:572) + selective bonus vs the target + protections.
- **Hit** if needed ≤ total (:621), i.e. **lucky + AC + bonuses ≥ THAC0**.
- **Critical hit**: raw ≥ 20 − crit bonus (`CDerivedStats::GetCriticalValue`, :597): hits unless
  `ShouldAvertCriticalHit` (:626). **Critical miss**: raw ≤ crit-miss value + 1 (:605). Both on the **raw** roll.
- **Auto-hit**: target state 0x20 (`STATE_HELPLESS`, set by sleep, hold and web effects: `CGameEffectSleep`,
  `CGameEffectHoldCreature(Spell)`, `CGameEffectWebHold`) skips the roll: always a plain hit, no critical miss (:501).
- **Attack of opportunity +4 (melee vs a target holding a ranged weapon) is inside `ENGINE_MODE != 3`** (:356): off in PST.
- **Damage** (`Damage` :278-306, 359-401, 813-904): weapon dice, each die rolled with attacker luck + damage luck;
  + dice bonus; + derived damage mod + hand bonus; + 2 berserk; + STR damage (STR + STR-extra columns) when the
  ability flags `& 5`; + selective bonus; min 1 if the weapon has dice; **× 2** (`CRITICAL_HIT_MULTIPLIER`) on a
  critical. Damage type from the ability (1 piercing … 5 non-lethal; 6/7/8 pick the type the target resists less).
  In PST the critical damage effect carries a per-companion "special" value (128 … 0x2000, `Damage` :1005-1247),
  used for the critical-hit BAM (presentation).

---

### C-1 Attack roll needs one point more in GemRB (≥ vs >)
- **Status:** V   **Severity:** 2   **Uses:** every weapon attack   **By:** opus
- **EE:** `CGameSprite::Hit` (.re/ee/dump/dec_all_named/CGameSprite_Hit_CGameSprite_,CItem__,int,int__,int_.c:172, 621):
  hit when THAC0 − AC ≤ lucky roll + bonuses, i.e. roll + AC + bonuses **≥** THAC0.
- **GemRB:** `gemrb/core/Scriptable/Actor.cpp:7934` `PerformAttack`: `success = (roll + rollMod) > tohit` with
  `ReverseToHit` (rollMod = defense = AC, tohit = THAC0 − bonuses): roll + AC + bonuses **>** THAC0.
- **Difference:** THAC0 15 vs AC 5: EE hits on 10+ (55 %), GemRB on 11+ (50 %). Every non-critical attack in the game
  is 5 % less likely to hit, for both sides. The turn-based preview (`Actor.cpp` ~7529) copies the same formula.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 165 175` and `... 595 625`;
  `sed -n 7925,7936p gemrb/core/Scriptable/Actor.cpp`.

### C-2 Luck can't lift a roll to 20 in GemRB; luck feeds the critical range
- **Status:** V   **Severity:** 3   **By:** opus
- **EE:** `Hit` :174-187: lucky = clamp(raw + luck, 1, 20) is used for the hit sum; criticals use **raw** (:597, :605).
- **GemRB:** `Actor.cpp:11312` `LuckyRoll(..., LR_CRITICAL)`: a lucky result reaching 20 is cut to **19** (:11360);
  natural 1/20 are returned as 1/20. `PerformAttack` :7892 then uses this lucky roll for the critical test
  (`roll + IE_CRITICALHITBONUS + CriticalBonus ≥ 20`) and :7986 for the critical miss (`roll ≤ 1 + fx`).
- **Difference:** luck +3, raw 17: EE sums 20, GemRB 19. With a critical bonus of 1 (PST `STATE_CRIT_ENH`), raw 17 +
  luck 3 = 19 + 1 → critical in GemRB, not in EE (EE needs raw ≥ 19). Luck −1, raw 2 → 1 → critical miss in GemRB,
  plain roll in EE.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 174 189`; `sed -n 11356,11366p gemrb/core/Scriptable/Actor.cpp`.

### C-3 Auto-hit states: GemRB includes stunned/frozen/petrified, and still allows a critical miss
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `Hit` :501: only target state **0x20 `STATE_HELPLESS`** auto-hits; set by sleep (op 39), hold (op 109/175)
  and web (`grep "|= 0x20u"` over the effect handlers). Stun (0x8) is **not** helpless. The auto-hit returns before the
  critical tests: no critical miss, no critical hit.
- **GemRB:** `Actor.cpp:7929`: auto-hit when `Immobile()` (`Actor.cpp:6782`: caster hold, `IE_HELD`, `STATE_STILL` =
  stunned | frozen | petrified, time stop) or `STATE_SLEEP`; the critical-miss check at :7986 runs afterwards, so a
  natural 1 still misses a sleeping target.
- **Difference:** a stunned enemy (Howl, Power Word Stun, many PST stun effects) is hit automatically in GemRB, needs
  a roll in EE; a sleeping/held target can be critically missed in GemRB, never in EE. Whether GemRB's `STATE_HELPLESS`
  (0x20) is set by its sleep/hold opcodes the same way was not traced (GemRB tests `STATE_SLEEP`/`IE_HELD` instead).
- **Re-check:** `python tools/parity/dumps.py grep ee "\|= 0x20u" --in ApplyEffect`; `sed -n 6782,6800p gemrb/core/Scriptable/Actor.cpp`.

### C-4 GemRB gives +4 to melee attacks against targets holding a ranged weapon; PST:EE doesn't
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `Hit` :356 `if (CChitin::ENGINE_MODE != 3)` wraps the whole "Attack of Opportunity:4" block (same in
  `CGameSprite::Damage` around :423-491 for the damage log). Off in PST.
- **GemRB:** `Actor.cpp:7237-7240` `GetToHit`: `generic += 4` when we melee and the target's weapon is ranged, all games.
- **Difference:** every melee swing at an archer/thrower (PST has many thrown-weapon enemies and Annah/companions with
  thrown items) is +4 in GemRB.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 355 394`; `sed -n 7234,7241p gemrb/core/Scriptable/Actor.cpp`.

### C-5 Range modifiers for ranged attacks missing in GemRB (point blank −8)
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `Hit` :512-553, for ability type 2 (ranged) only: distance in search-map cells (16 × 12 px) squared, minus a
  size fudge from both personal spaces: < `MINIMUM_RANGE`² (4 cells) → **−8**; > `LONG_RANGE`² (64) → −5; >
  `MEDIUM_RANGE`² (32) → −2; else 0 (`eeconst.py "CGameSprite::*RANGE*"`). Not engine-gated.
- **GemRB:** no range modifier outside 3rd edition (`GetToHit` only has the IWD2 close-quarter penalty).
- **Difference:** shooting/throwing at an adjacent target (within ~64 px horizontally) is −8 to hit in EE, 0 in GemRB;
  very long shots −2/−5 (rare: PST missile ranges are short).
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 510 555`; `python tools/parity/eeconst.py "CGameSprite::*RANGE*"`.

### C-6 Invisible attacker gets no +4 in GemRB
- **Status:** V   **Severity:** 3   **By:** opus
- **EE:** `Hit` :443-451: attacker state 0x10 (invisible) and the attack isn't ranged → total −= −4 (**+4**); a
  backstabber (multiplier > 1) also takes away the target's DEX AC (:452-472). Target invisible / improved invisible and
  the attacker can't see invisible (vtable +376) → **−4** (:478-487).
- **GemRB:** `GetDefense` `Actor.cpp` ~7413-7431: invisible attacker → only the backstabber's DEX-loss part; target
  invisible → defense +4 (= EE's −4). No +4 for the invisible attacker. Invisibility usually breaks on attack, so this
  mostly matters for improved invisibility.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 442 494`; `sed -n 7408,7432p gemrb/core/Scriptable/Actor.cpp`.

### C-7 Dead_Truce: GemRB applies it to undead party members and any non-zero value
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `Hit` :200-214: needed +4 only when the attacker's general is `G_UNDEAD`, the attacker is **not** a PC
  (EA ≠ `EA_PC`) and the target **is** a PC, and `Dead_Truce` **== 1**.
- **GemRB:** `Actor.cpp:7434-7438` `GetDefense`: defense +4 whenever the attacker's general is undead and
  `CheckVariable("Dead_Truce")` is non-zero, whoever the target is.
- **Difference:** with `Dead_Truce` = 1 (set by 3 dialogue actions, read by AR1201's shadow spawns), **Morte and Vhailor
  (general 4 = undead)** attacking enemies give those enemies +4 AC in GemRB; in EE only hostile undead attacking the
  party are penalised.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::Hit(" 200 214`; `sed -n 7434,7448p gemrb/core/Scriptable/Actor.cpp`;
  Morte/Vhailor general: CRE byte 0x315 = 4.

### C-8 NTOKEN shadow check: EE tests animation ids, GemRB races 53-55
- **Status:** S   **Severity:** 3   **By:** opus
- **EE:** `Hit` :190-199: needed +3 when the attacker's **animation id** is 0x7703, 0xF04E or 0xF04F, the target is a
  PC, and the party has `NTOKEN`.
- **GemRB:** `Actor.cpp:7440-7446`: defense +3 when the attacker's race is 53-55 (`SHADOW_MARK_1-3`).
- **Open:** the 7 CREs with race 53-55 use animations 0xE039 (4), 0xE04E (1), 0xE04F (2) on disk; EE's in-memory id
  for these is not known (EE may remap PST animation ids). If EE's 0xF04E/0xF04F are the disk 0xE04E/0xE04F, the
  0xE039 shadows (4 CREs) get no NTOKEN bonus in EE. Needs EE's animation id mapping.

### C-9 Iron Fist to-hit: EE matches GemRB (corrects E-208)
- **Status:** P   **By:** opus
- **EE:** `Hit` :572: +3 to hit when `HasIronFist` (op 0x17E on the list and weapon animation low 12 bits = 50, the
  fist). The log line prints 0 but the bonus is applied. **E-208 said "no to-hit bonus" (original): EE: differs**,
  so GemRB's `IE_FISTHIT +3` (`PSTOpcodes.cpp:1174`) is right. E-208's damage part (+6 and Carceri max dice) stands.

### C-10 Berserk +2 to hit and +2 damage missing in GemRB
- **Status:** V   **Severity:** 3   **By:** opus
- **EE:** `Hit` :399 (+2 to hit) and `Damage` :819-822 (+2 damage) when derived state has 0x2 (`STATE_BERSERK`).
  `CGameEffectBerserk::ApplyEffect` (6BD0A0) :8: in PST only party members (portrait number) can go berserk.
- **GemRB:** `fx_set_berserk_state` (`FXOpcodes.cpp:1078-1100`) sets the state, party only outside 3E (same as EE);
  no +2/+2 anywhere (`grep -n STATE_BERSERK gemrb/core/Scriptable/Actor.cpp`: AI and attack-state uses only).
- **Difference:** a berserk companion hits and damages for 2 less in GemRB.

### C-11 Critical aversion: Vhailor rule missing
- **Status:** S   **Severity:** 3   **By:** opus
- **EE:** `CGameSprite::ShouldAvertCriticalHit` (00A?; `dumps.py show ee "CGameSprite::ShouldAvertCriticalHit"`):
  items with flag 0x2000000 in slot types 0,1,2,4,5,7,8 avert; slot type 6 items avert **unless** they have the flag
  (helmet rule); **script name `VHAILOR` with any item in slot type 20** averts; PST derived state bit 0x8000
  (`STATE_CRIT_PROT`) averts; the selected weapon with the flag averts.
- **GemRB:** `Inventory.cpp:2123` `ProvidesCriticalAversion` (armour/head/equipped items with the toggle flag, helmet
  rule) + `Actor.cpp:10123` `STATE_CRIT_PROT`. No Vhailor rule. Slot type 20 not mapped to a PST slot yet.

### C-12 Weapon damage: luck per die, STR, minimum, critical ×2
- **Status:** P   **By:** opus
- **EE:** `Damage` :283-306 dice with attacker luck + damage luck per die (clamped), :828-870 STR (+STR-extra column)
  when ability flags & 5, :899-904 minimum 1 and × 2 on a critical (`CRITICAL_HIT_MULTIPLIER` = 2).
- **GemRB:** `PerformAttack` :7913-7921 `LuckyRoll(..., LR_DAMAGELUCK)`, `WeaponDamageBonus` :8063, `ModifyWeaponDamage`
  :10134 `damage *= wi.critmulti`. Same rules; GemRB clamps to 1 before the STR/backstab bonuses, EE after all bonuses
  (only differs when bonuses are negative). Berserk +2: C-10.

### C-13 Weapon hits go through the op 12 damage effect in EE (E-012 rules apply to them)
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `Damage` :1005-1416 builds an op 12 effect (amount = final damage, p2 = damage type) and the target applies it
  with `CGameEffectDamage::ApplyEffect`. So everything in E-012 also applies to **weapon** hits: E-012f (party target:
  difficulty %, and **max HP ≤ 13 → damage capped at max HP − 1**: `CGameEffectDamage::ApplyEffect` :862-882, EE: same as
  the original), the absorb pools (:885-970, ops 348/351 counters in EE), Pain Mirror (:971-1058), mirror images and
  stoneskin (`CGameEffectDamage::CheckSave` :47-108, :135-176).
- **GemRB:** weapon damage goes `UseItem` → `Actor::Damage` directly; the E-012f low-HP rule exists nowhere.
- **Difference:** a level-1 Nameless One (max HP ≤ 13) hit by a 20-point blow survives at 1 HP in EE, dies (and
  respawns) in GemRB; see E-012f.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameEffectDamage::ApplyEffect" 862 884`.

### C-14 Save-for-half: every saved PST damage effect is halved unless its resource is `NEG`
- **Status:** V   **Severity:** 2   **Uses:** 27 op-12 effects with a save and no resource (`opuses.py 12 --full`)   **By:** opus
- **EE:** `CGameEffectDamage::CheckSave` (6D09E0) :113-121: in PST (`ENGINE_MODE == 3`), when the save **succeeds**,
  the effect has a save type and its resource (+48) is **not** `NEG`, the target type field (+20) is set to **255** and
  the effect still applies; `ApplyEffect` :1213-1219 then halves the damage (`>> 1`). This resolves round 5's "effect
  byte +6 = 255": it is the saved-for-half marker. An **empty** resource is "not NEG" → half.
- **GemRB:** `gemrb/core/EffectQueue.cpp:704-707` (`SAVE_FOR_HALF`, PST): save for half only when the resource is
  **non-empty** and doesn't start with `NEG`. An empty resource → the save negates the damage.
- **Difference:** 27 op-12 entries with a save and an empty resource: SPWI007, SPWI010, SPWI113, SPWI310, SPWI313,
  SPWI502, SPWI505, SPWI604, SPWI802, SPWI905, and items CELESTIA, CELESTI3, CFAXE, CFCLUB, CFDAGGER, CFFIST, CFHAMMER,
  FINGNAIL, GRINDER, IGNUSFI, JESTER, JUDGMENT, RAVEL1. A successful save takes half damage in EE, none in GemRB. (`NEG`
  is used by 9 entries, all Chromatic Orb.) SPL casting effects not counted (opuses.py skips them).
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameEffectDamage::CheckSave" 109 134`;
  `sed -n 700,712p gemrb/core/EffectQueue.cpp`; `python tools/parity/opuses.py 12 --full | awk -F'\t' '$9!="save=0x0" && $8=="res="'`.

### C-15 Saving throws: EE adds no luck; best save type; save 20 can't be made; improved invisibility +4
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** rolls: `CGameSprite::AIUpdate` :321-332 (also `ProcessEffectList` :582) store 5 save rolls of **1-20** and 2
  MR rolls of **0-99** on the sprite (+18824…+18830); every effect of one application shares them (`CGameSprite::AddEffect`
  :23 passes them to `CGameEffect::CheckAdd`). `CGameEffect::CheckSave` (6CFCF0) :345-456: among the flagged save
  types it uses the **lowest** (best) save value whose value is < 20 (death first, then wand, poly, breath, spell),
  success if roll + effect save bonus (+2 vs own specialist school, + the school save stat when the school ≤ 11, +
  selective bonus vs the caster) ≥ save + (−4 when the target has improved invisibility). **No luck term**: luck
  (derived +66) only feeds the attack roll and dice (`CDerivedStats` never adds it to saves; `CGameEffectLuck` only sets
  +66). A save value of 20 can't be made (start value v48 = 20, roll sum 0).
- **GemRB:** `Actor.cpp:3317` `GetSavingThrow`: roll + modifier **+ IE_LUCK** ≥ save stat; `EffectQueue.cpp` `CheckSaves`
  ~1031-1043 tries each flagged type with its own roll and succeeds on the first that passes.
- **Difference:** luck +2 (PST luck items, Bless-like effects) gives +2 on every save in GemRB, 0 in EE (negative luck
  the reverse). Multi-type saves get several rolls in GemRB (better odds). A creature with save 20 saves on a 20 in
  GemRB. Improved invisibility gives no save bonus in GemRB.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameSprite::AIUpdate(void)" 320 332`;
  `python tools/parity/dumps.py lines ee "CGameEffect::CheckSave(" 345 456`; `sed -n 3310,3320p gemrb/core/Scriptable/Actor.cpp`.

### C-16 Magic resistance roll
- **Status:** P   **By:** opus
- **EE:** `CGameEffect::CheckSave` :129-218: resisted when the effect may be resisted (resist flag & 1, not & 2) and MR
  (derived word 19) > the shared 0-99 roll; one roll per application (0x80 bit only rate-limits the feedback).
- **GemRB:** `EffectQueue.cpp:951` `CheckMagicResistance`: `fx->RandomValue < MR`. Same.

### C-17 Death threshold
- **Status:** P   **By:** opus
- **EE:** `CGameEffectDamage::ApplyEffect` :1346-1410: a minimum-HP value (v179) keeps HP at that value; otherwise HP ≤ 0
  → death effect; party members' HP is set to 0 when it is ≥ −19. PST death type: E-012h (always normal death).
- **GemRB:** `Actor::Damage` (`Actor.cpp:4392`) → `Die` at HP ≤ 0, `IE_MINHITPOINTS`. Same rule. The Nameless One's
  death/revival and game-over rules are R2 / track A.

## Round 14, part 2: morale, attacks per round, disruption, XP

### C-18 Morale recovers 15 times too fast in GemRB
- **Status:** V   **Severity:** 2   **Uses:** 1,082 of 1,095 PST CREs have recovery time 60 (CRE v1.2 word 0x242)   **By:** opus
- **EE:** `CGameSprite::CheckMorale` (A1C2C0) :46-79: when the creature's AI tick counter (`this+232`, counted up in
  `CGameSprite::ProcessAI`) is a multiple of **15 × recovery time**, morale moves one step toward 10. Recovery 0 →
  morale is held at 10. Morale is clamped to 0…20.
- **GemRB:** `Actor.cpp:3090-3101` `RefreshPCStats`: `GameTime % mrec`, i.e. every **mrec ticks**; `CREImporter.cpp`
  reads the value unscaled for PST (only IWD2 multiplies by 60).
- **Difference:** recovery 60 = one step per 60 s in EE, per 4 s in GemRB. An enemy whose morale fell to its break
  value (5) recovers in ~4-20 s instead of 1-5 min, so panicked enemies come back far sooner.
- **Re-check:** `python tools/parity/dumps.py show ee "CGameSprite::CheckMorale" --all | sed -n 55,80p`;
  `sed -n 3088,3102p gemrb/core/Scriptable/Actor.cpp`.

### C-19 Morale failure outcome: EE 10 % panic / 80 % run / 10 % berserk, GemRB a third each
- **Status:** V   **Severity:** 2   **By:** opus
- **EE:** `CGameSprite::DoMoraleFailure` (A6C830) :20-79: roll 0-99 (`ACTION_CHOICE_PROBABILITY` 100); < 10
  (`ACTION_CHOICE_PANIC_CUTOFF`) → PANIC, ≥ 90 (`ACTION_CHOICE_RUNAWAY_CUTOFF`) → BERSERK, else
  `RunAwayFromNoInterruptNoLeaveArea`. Plays the morale sound.
- **GemRB:** `Actor.cpp:858-860` `pcf_morale`: `RAND(1, 3)` → berserk, run away or random walk, equally likely (the
  comment there notes IWD2's 80/10/10).
- **Difference:** in EE a broken enemy almost always flees (80 %); in GemRB a third go berserk and a third wander.
- **Re-check:** `python tools/parity/eeconst.py "CGameSprite::ACTION_CHOICE*" --size 1`; `sed -n 855,861p gemrb/core/Scriptable/Actor.cpp`.

### C-20 Party members never break morale in PST
- **Status:** P   **By:** opus
- **EE:** `CheckMorale` :26: `ENGINE_MODE == 3` and EA_PC → no check. **GemRB:** `Actor.cpp:12266`
  `ShouldModifyMorale` (PST: EA ≠ PC). Same.

### C-21 The Nameless One's THAC0 and extra attacks use his best/fighter levels
- **Status:** S   **Severity:** 2   **By:** opus
- **EE:** `CRuleTables::GetTHAC0` (7F21B0) :33-40: when derived dword +100 is 1, THAC0 = **min** of the fighter, mage
  and thief THAC0 at the creature's level in each (`FindTHAC0`, table at `this+2312`), then the class THAC0 bonus,
  floored at 0. `CRuleTables::GetClassAPRBonus` (7EF870) :120-126: the same flag forces the **fighter** row and the
  fighter level for the proficiency extra-attack table (`GETS_PROF_APR`, level capped at 20).
- **GemRB:** THAC0: `GUIREC.py:1060-1064` / `:1137-1142` keep the best THAC0 seen at each level-up (`IE_TOHIT`), which
  equals EE's minimum as long as levels only go up. Extra attacks: `Actor.cpp:3029-3055` `GetStyleExtraAPR` checks
  `GETS_PROF_APR` for the **active** class and uses `GetHighestLevel()`.
- **Open:** what sets derived +100 (no direct writer found: `dumps.py grep ee "a2 \+ 1043\)"`); if it is the Nameless
  One's marker, a mage/thief Nameless One keeps his fighter extra attacks in EE and loses them in GemRB (needs
  `clswpbon.2da` MAGE/THIEF `GETS_PROF_APR` = 0 to matter).

### C-22 Spell disruption: any damage interrupts
- **Status:** P   **By:** opus
- **EE:** `CGameSprite::Spell` :860/:1017 and `SpellPoint` :796/:955: the cast fails if the caster was damaged
  (`this+4593`, set by op 12 `CGameEffectDamage::ApplyEffect` :1161) and `ConcentrationFailed` returns 1; it returns 1
  whenever the concentration mode (`CONCENTRATION_SETTINGS` table, `CRuleTables::CRuleTables` :3495-3502) is 0, and
  PST:EE ships no such table (`pstres.ee().res("concentr","2da")` → none) → always disrupted.
- **GemRB:** `Actor.cpp:4239` `CheckSpellDisruption`: PST has `SimplifiedDisruption = 0`, `HasEEEffects = 0`, not 3E →
  returns true. Same.

### C-23 XP per kill
- Covered by track A10: SE-5 (party XP remainder and difficulty, `wp_script_engine.md`). Nothing new here.
