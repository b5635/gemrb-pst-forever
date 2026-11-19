# WP2: effect opcodes, original vs GemRB

Progress: 6, 12, 13, 39, 42, 44, 45, 73, 82, 98, 100, 120, 128, 129, 138, 146–148, 186–196, 201, 203–211 done. Next: the rest by use count (dev/parity/maps/opcodes.tsv). Original handler = ApplyEffect (vtable slot 2,
`dev/parity/maps/opcodes.tsv`), decompiled at `.re/orig/dump/dec/<addr>.c`. Effect fields: p1 `+8`, p2 `+12`, timing
`+16`, duration `+18`, resource `+24`. Creature derived stats start at `+3204` (state bits); `+3220` THAC0,
`+3222`–`+3226` the five saving throws, `+3245` to-hit bonus, `+3883` luck. Statuses as in AGENT_GUIDE section 4.1.

---

### E-203 Curse makes saving throws *better* in GemRB
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D6BAF`. Once (if derived state bit 0x10 isn't set yet): set bit 0x10, **add p1 to THAC0** (`+3220`)
  and to **all five saving-throw values** (`+3222`–`+3226`), and subtract p1 from derived byte `+3281` (the damage bonus, see E-073: curse is also −p1 damage).
  Higher THAC0 and save values are worse: the curse is a penalty to both.
- **GemRB:** `PSTOpcodes.cpp:1068` `fx_curse`: to-hit −p1 (right), but `STAT_SUB(IE_SAVEVS*, p1)`. GemRB's AD&D save
  stats are the number to roll (`Actor.cpp:3302` comment and `GetSavingThrow`), so subtracting **lowers the target**:
  cursed creatures save more easily.
- **Difference:** p1 2 → original saves 2 worse, GemRB saves 2 better. Byte `+3281` isn't modelled.
- **Data affected:** Curse SPL (2 uses) and every Prayer aura (E-204), which hands op 203 to enemies.

### E-204 Prayer: an aura, not a one-off
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D6CB1` creates an aura object (type 6, radius **720**, period **75 ticks**) on the caster for the
  effect's remaining duration. Its update (`sub_4D6DFE`) every 75 ticks gives **every creature within 720 of the
  caster** either op **203 Curse** (if it counts as an enemy of the caster: `sub_412872` on the caster's object type)
  or op **130 Bless**, p1 = Prayer's p1, power 3, **6 s** (75/15 + 1). Refreshed while the caster stays.
- **GemRB:** `PSTOpcodes.cpp` `fx_prayer`: once, at application, walks **every actor on the map**, picks bless/curse
  by comparing EA cutoffs (neutrals skipped), 60 s each.
- **Difference:** whole map instead of 720; one-off 60 s instead of a 6 s effect refreshed every 5 s around the caster
  (walk away and it ends); neutral-EA creatures: the original classifies by enemy-of-caster, GemRB skips them.
- **Data affected:** 21 uses (Prayer and items).

### E-208 Iron Fist: damage only, and only with the fist animation
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D7A9C` only sets creature flag `+3338` (unless dead). The damage effect (`sub_4B245B`, line ~429)
  reads it: when the *attacker* has the flag and its weapon animation id (low 12 bits) is **50** (the fist), the damage
  gets **+6**; in Carceri it also rolls maximum dice (finding R1). **No to-hit bonus.**
- **GemRB:** `PSTOpcodes.cpp:1174` `fx_iron_fist`: `IE_FISTHIT +3`, `IE_FISTDAMAGE +6`.
- **Difference:** GemRB adds +3 to hit that the original never gives; the Carceri max-dice rule is missing (R1).

### E-012a Effect damage dice ignore the target's luck
- **Status:** V   **Severity:** 2
- **Original:** `sub_4B245B` rolls each damage die separately as `clamp(rand % size − target luck, 0, size − 1) + 1`
  (`sub_82015B`; luck = target byte `+3883`). A lucky target takes less, an unlucky one more, per die. Max-dice mode
  (Carceri / Iron Fist) uses `size − luck`.
- **GemRB:** dice are resolved once when the effect is queued: `EffectQueue.cpp:702` `fx->Parameter1 = DICE_ROLL(...)`
  = `core->Roll`, no luck. (Weapon damage does use `LuckyRoll` with the opponent's luck, `Actor.cpp:11326`.)
- **Difference:** target luck +2 vs 6d6: original average 15 (each die 1–4 then flattened), GemRB 21.
- **Data affected:** every op 12 with dice (most damage spells).

### E-138 Animation sequence: GemRB rejects PST sequence numbers
- **Status:** V   **Severity:** 3
- **Original:** `sub_4CB10A`: unless creature `+3842 & 0x800`, set the animation sequence to p2 (`sub_747A06`), done.
- **GemRB:** `FXOpcodes.cpp:4510` `fx_animation_stance` → `SetStance(p2)`; the suite logs "Tried to set invalid stance
  id(27)" for Minor Embalming (p2 27).
- **Difference:** PST sequence ids above GemRB's stance range (27, used by Embalming) are dropped.

### E-100 Protection from creature type
- **Status:** ?   **Severity:** 2
- **Original:** `sub_4C5311` builds an object type with p1 written into one field chosen by p2 (2 EA, 3 general,
  4 race, 5 class, 6 specific, 7 gender, 8 alignment) and adds it to the creature's protection list.
- **GemRB:** `fx_generic_effect` (no logic in the opcode); the protection must be checked elsewhere.
- **Difference:** not determined: find where GemRB checks op 100 (3 uses).

### E-207 Freeze game
- Already E4. Original `sub_4D7A0E` calls `sub_7BB610(area, p2 == 0, p1, target id)` once = `SetGameFreeze`
  (EE). p2 0 = freeze on, else off; p1 is passed through (duration or source). **V** for the call; GemRB's TimeStop
  approximation remains E4.

### E-210 Detect Evil
- **Status:** V   **Severity:** 3
- **Original:** `sub_4D7ADA` creates an aura (type 7, period 75, length 4320) and a glow on the caster (op 9,
  `sub_4D7C2F`). The update `sub_4D7CD6` sets **derived state 0x1000000 (`STATE_DETECT_EVIL`)** on the caster every tick
  and every 75 ticks pulses evil creatures in a **cone in front of the caster** (facing-based).
- **GemRB:** `fx_detect_evil`: a circle around the target, duration rewritten to 50 + 25/level s (max 300).
- **Difference:** the state bit `STATE_DETECT_EVIL` (scripts can test it) isn't set; cone vs circle; GemRB's duration
  formula is its own (the original uses the effect's duration).

### E-211 Jumble Curse
- **Status:** S   **Severity:** 2
- **Original:** `sub_4D8764` creates an aura (type 9). Its update (`sub_4D8837`) every 75 ticks plays sequence 4 and
  shows string 46633 over the head. **It sets no spell failure.**
- **GemRB:** `fx_jumble_curse`: hiccup every 75 ticks (string from p1 or `PST_HICCUP`) and **dead magic + 100% spell
  failure**.
- **Difference:** GemRB blocks all casting; the original handler doesn't. Unless the original's casting code checks
  for op 211 elsewhere (not found yet), GemRB is harsher.

### E-193/194 Screen shake, flash
- **Status:** P   Original `sub_4D3442` (shake, once, p1 strength, using duration when timing ≠ 1) and `sub_4D3575`
  (flash, colour from p1 bytes, once) are presentation. GemRB `fx_screenshake`, `fx_flash_screen` do the same job.

### E-206 Embalm
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D7247`. Not cumulative (derived state 0x40000000 `STATE_EMBALMING`). Amount: **p2 ≠ 0 (Embalming):
  2 × caster level** of SPWI205; **p2 0 (Minor): 2d4**, each die adjusted by the target's luck. Plane rules for SPWI103 /
  SPWI205: **Carceri → amount halved**, **Negative Material Plane → amount 1** (`MAGIC02` plays); in **Baator** the target
  first gets a saving throw and on a success the effect is cancelled. Then **max HP + amount**, **current HP + amount only
  if below max**, **AC −1 (Minor) / −2 (Embalming)** (`+3210`).
- **GemRB:** `PSTOpcodes.cpp` `fx_embalm`: Minor **1d6 + 1** (2–7) instead of 2d4 (2–8); Embalming 2 × level; max HP and
  current HP always raised; AC 1 / 2. No plane rules.
- **Difference:** Minor's roll; current HP is raised even at full HP (harmless once max rises too, but at max HP the
  original leaves current HP); no plane rules.

### Plane checks have an exemption: the Spell Keys (extends R1, S34)
- **Status:** V   **Severity:** 2
- **Original/EE:** `sub_7BD15D` = `CPlanescape::IsInCarceri`, `sub_7BD264` = `IsInBaator`, `sub_7BD327` =
  `IsInNegativeMaterialPlane`. Each is true when the object is in that plane's areas, **except for a creature that
  carries the plane's Spell Key item**: `CARCERSK` "Carceri Spell Key", `BAATORSK` "Baator Spell Key", `NEGMATSK`
  "Negative Material Plane Spell Key" (EE `CGameSprite::FindItemPersonal`; original `sub_763140` & 0x8000 = not found).
- **Callers:** damage (`sub_4B245B`, `sub_4B2302`), TransferHP (`sub_4D1C49`), Overlay (`sub_4D4386`), Embalm, the three
  Strength spells.
- **GemRB:** none of the plane rules exist (R1), so neither does the exemption. When R1 is ported, check the caster's
  inventory for the key.

### E-201 Overlay (PST spell overlays): case by case
- **Original:** `sub_4D4386` (1,399 lines), switch on p2 at first application. GemRB `PSTOpcodes.cpp:760` `fx_overlay`.
  Durations below are seconds; L = caster level of the named spell (`sub_7B2F45`).

| p2 | Spell | Original | GemRB | Verdict |
|---|---|---|---|---|
| 0 | Cloak of Warding (SPWI304) | 5 × L s; counter 3–12 + L | 5 × L; P3 = 3–12 + L | P |
| 1 | Shield (SPWI111) | 25 × L s; op 0 AC 3 (p2 16); saves 33–37 +1 | same | P |
| 2 | Black Barbed Shield | 10–30 s; op 0 AC 2 | same | P |
| 3 | Pain Mirror (SPWI209) | 5 × L s; op 9 glow 0xFAFF7000/0x30000C; fizzle (`SE10FIZZ`, `MAGIC01`) when already active | same, no fizzle | P (fizzle presentation) |
| 4 | Guardian Mantle (SPWI704) | 750 ticks + 75 × L = 50 + 5 × L s | 50 + 5 × L | P |
| 5 | Shroud of Shadows | the effect's own duration | nothing (GemRB moved it to `sshadow.spl`) | see spell_expect SPWI408 |
| 6 | Duplication (SPWI504) | **in Carceri (no Spell Key) the effect is cancelled** with `MAGIC02` | plays `magic02` always, never cancels | **differs** (plane rule) |
| 7 | Armor (SPWI102) | op 8 colour 0x825A2800; op 0 AC 6 (p2 16) | same + damage absorb counter 8 + L | check the absorb in WP2 follow-up |
| 8 | Antimagic Shell (SPWI601) | visual `S061GLWB` for 6 × L; effect's own duration | dispel, miscast, protections, no duration change | ? |
| 11 | Flame Walk (SPPR302) | 10 × L + 10 s; op 50 glow; op 9 delayed 35; op 30 + op 84 fire resist 50 | same | P |
| 12 | Protection from Evil (SPPR106) | 10 × L s; op 0 AC 2; saves +2 | same | P |
| 13 | Conflagration | 50 s | 50 s | P |
| 14 | Infernal Shield (SPWI312) | 5 × L s; op 30 + op 84 fire resist 150; counter 3–12 + L (rolled, use not traced) | no counter | ? |
| 15 | Submerge the Will (SPWI119) | **12.5 × L s** (25 × L / 2); AC 2 (p2 16); saves +1 | **12 × L** | differs (−0.5 s/level) |
| 16 | Balance in All Things (SPWI314) | 5 × L s; op 9 glow 0x615AB400/0x30000C; fizzle when already active | same, P3 = L / 4 | P |
| 17 | (none) | — | GemRB's own strength extension | see S7 |

### E-146 Cast spell: who casts
- **Status:** S   **Severity:** 2
- **Original:** `sub_4CC591` builds action **113 ForceSpell** whose target is the effect's target itself, at level
  **max(p1, the spell's first header level)**, and sends it as an add-action message from the effect's source to the
  target creature (`off_8DC3CC`): the **target** casts the spell (on itself). p2 isn't read.
- **GemRB:** `FXOpcodes.cpp:4743` `fx_cast_spell`: p2 0 → the **effect's owner** (the original caster) queues
  `ForceSpellRES(res, target, p1)` in front of its own actions; p2 1/2 → the owner casts instantly.
- **Difference:** in the original the target is the caster of the sub-spell, which changes enemy filters, caster-level
  scaling and kill credit for 98 uses of op 146 in PST data. The level floor (first header level) is also missing.
  Needs one in-game check (which creature shows the casting) before calling it V.

### E-074 Blindness
- **Status:** P (penalties) / V (PW Blind duration, see below)   **Severity:** 1
- **Original:** `sub_4C1656`: state 0x40000, **THAC0 +4 and AC +4** (both worse), base fields too when permanent.
- **GemRB:** `fx_set_blind_state` with PST's `ReverseToHit = 1`: AC −4, to-hit −4 (same thing). **But** GemRB's own
  PW Blind hook (p2 == 1, used by `PWB.spl`): duration from the *target's* HP, `< 25 → 151–390`, `< 50 → 71–190`,
  `< 100 → 16–45` **ticks** added to GameTime. The original's are **seconds** (160–400 s etc.) and chosen from the
  **pool**. GemRB's blindness is ~15× too short (10–26 s instead of 160–400 s).

### E-054 THAC0 modifier
- **Status:** P?   Original `sub_4BE69D`: p2 0 = bonus (THAC0 − p1), 1 = set THAC0 to p1, 2 = percent of base; the result is
  clamped to **1–25** in every mode. GemRB `fx_to_hit_modifier` has the three modes; the 1–25 clamp isn't visible there
  (check `ToHit` limits).

### E-000 AC vs damage type
- **Status:** P?   Original `sub_4AF5A2`: per-type AC modifiers clamped to **±20** when permanent. GemRB
  `fx_ac_vs_damage_type_modifier`: check the clamp.

### E-109 Hold creature (by IDS)
- **Status:** P   Original `sub_4C61EB`: skips dead targets; holds (helpless flag + state 0x20) only if the target matches
  p1 in the IDS field chosen by p2 (2 EA … 8 alignment; p1 0 = anyone; class uses the active class of dual-classes).
  GemRB `fx_hold_creature_no_icon` does the same IDS match.

### E-017 Heal (current HP)
- **Status:** V   **Severity:** 2
- **Original:** `sub_4B8281`. Does nothing at full HP. Dice rolled per die minus the target's luck (as E-012a). At HP ≤ 0
  only p2 high word 0x10000 (raise) proceeds, through op 32 first. Modes (p2 low word): **0 add** (capped at max),
  **1 set** (capped), **2 add p1 % of max HP** (no cap), **4 full heal**; 3 does nothing; 10/11 special. Party members get
  floating green heal numbers.
- **GemRB:** `fx_current_hp_modifier`: mode 2 **sets** HP to p1 % of max; mode 4 falls into GemRB's "special heal amount"
  (lay on hands etc.).
- **Difference:** SPPR502 (Raise Dead, p1 50, p2 2): original adds 50 % of max, GemRB sets 50 %. Mode 4 (used by RestParty,
  below) isn't a full heal in GemRB.

---
## Round 4 (2026-11-18): 147, 148, 187–196

Data counts come from `python tools/parity/opuses.py <op>` (SPL + ITM of the original game with Fixpack/UB; it reads
header and equipped effects, not SPL casting effects: those were checked by hand for 195/196).

### E-147 Learn spell
- **Status:** V   **Severity:** 2
- **Original:** `sub_4CCA02`. The spell level is **the fifth character of the resref** (`SPWI305` → 3), not the SPL
  header. p2 picks the list: **0 mage** (`sub_760FD6`, known-spell type 1), **1 priest** (`sub_760FA6`, type 0),
  **2 innate** (`sub_761006`, type 2). `sub_760F37` adds the spell unless that list already has it. **No ability roll,
  no class check, no message, no XP.**
- **GemRB:** `FXOpcodes.cpp:4789` `fx_learn_spell` → `Actor::LearnSpell(res, p1 ^ LS_STATS)` (`Actor.cpp:6523`). With
  p1 0 that is `LS_STATS`: **above Normal difficulty a luck-adjusted d100 must be ≤ the INT learn chance or learning
  fails** (`Actor.cpp:6543`). Type and level come from the SPL; p2 is ignored.
- **Difference:** on hard difficulties GemRB can fail to teach a scroll; the original never fails. The type/level
  sources differ but agree for all PST data.
- **Data affected:** 83 uses, all p1 0, p2 0, `SPWIxxx` (mage scrolls: `BBSEED`, `BREAST1`–`4`, `CIRCLE02`–`04` …).

### E-148 Cast spell at a point: level floor missing
- **Status:** V (level) / S (who casts)   **Severity:** 2
- **Original:** `sub_4CCBBE`, the same pattern as E-146: builds action **114 ForceSpellPoint** at the effect's target point
  (effect +180/+184), level **max(p1, the spell's first-header minimum level)** (`sub_58C884(0) + 16`), and sends it from
  the effect's source to **the target creature**, which does the casting. p2 isn't read.
- **GemRB:** `FXOpcodes.cpp:4800` `fx_cast_spell_point`: p2 0 → the **effect's owner** queues
  `ForceSpellPointRES(res, pos, p1)`: the level is **p1 alone**.
- **Difference:** PST scrolls set p1 to the spell's *level*, so GemRB casts them at about half the original caster
  level: Cloudkill (`C_2501`) 5 vs 9, Chain Lightning Storm (`MANACLE`) 6 vs 12, Acid Storm (`ACID`) 7 vs 14, Blade
  Storm 7 vs 14 (its damage is level × d8, S29: half), Meteor Storm (`METEOR`) 8 vs 16, Celestial Host / Rune of Torment
  9 vs 18. The caster swap only matters for items not used on oneself (none confirmed in data).
- **Data affected:** 40 uses: every mage/priest scroll and charms (`CFLYCHRM`, `LENS11`, `MURK`, `RATCHARM`, `TT*`).
- **Op 146 has the same floor** (E-146): that part of E-146 is **V** by the same reading.

### E-187 Play BAM (blended)
- **Status:** V   **Severity:** 3
- **Original:** `sub_4D09F4`. Skips dead targets (HP ≤ −10 or state 0x800). p1 = colour (tint if non-zero). **p2 bit 0
  = two-part animation** (front/back halves: the cycle count is halved and part i plays cycle i). **p2 bit 1 =
  detached:** placed in the area at a **random spot inside the target's sprite box** (x ± half width, y up to the full
  height) and doesn't follow it; without bit 1 it is **attached to the creature** (`sub_7662B4`). Lifetime: timing
  permanent (1) → plays its sequence; any other timing → lives for the effect's duration (+774).
- **GemRB:** `PSTOpcodes.cpp:152` `fx_play_bam_blended`: bit 1 → at `fx->Pos` (the effect's point), not a random spot on
  the creature; bit 0 → loops for one sequence length when the timing is limited; otherwise **plays once**, so a timed
  animation (timing 0, e.g. SPWI804 ×9) ends early. No dead-target skip.
- **Difference:** presentation only: bit-1 placement, bit-0 meaning, timed animations cut short, animations on corpses.
- **Data affected:** 269 uses (p2 0: 160, p2 1: 32, p2 2: 21).

### E-188–191 Play BAM (not blended)
- **Status:** P (mostly)   **Severity:** 3
- **Original:** `sub_4D1224`, one handler for all four. p2 flags: 1 random spot inside the target's sprite box, 0x10
  (passed to the animation ctor, unidentified), 0x100 another animation class (`sub_69CC37`), 0x1000 sticky (follows the
  creature), 0x30000 layer (0x30000 = both halves), 0x300000 blending, 0x100000 = fade from effect byte +36 instead of a
  p1 colour. Same dead skip and lifetime rule as op 187.
- **GemRB:** `PSTOpcodes.cpp:219` `fx_play_bam_not_blended` reads the same flags. Random placement is **0–31 px up-left of
  `fx->Pos`** instead of anywhere in the sprite box; 0x10 and 0x100 aren't read; non-limited timings play once.
- **Data affected:** 188: 3, 189: 41, 191: 111 (190 unused).

### E-192 Transfer HP (Vampiric Touch, Kiss, Sensory Touch, draining weapons)
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D1C49`. Nothing if the target's HP ≤ 0. Amount = p1 + dice, **each die minus the target's luck**
  (`sub_82015B`, as E-012a). Plane rules: Sensory Touch (`SPIN104`) and Blood Bridge (`SPWI204`): Carceri → half, Baator →
  the target saves and a success cancels it (`MAGIC02`), Negative Material → 1; Vampiric Touch (`SPWI309`): Carceri or
  Negative Material → half (Spell Key exemption as usual). Modes (p2 low word):
  - **0, target receives:** stops if the target is at full HP; target HP + amount, capped at its max; the **caster** takes
    op 12 **magic** damage (p2 0x400000) equal to what was actually given.
  - **1, caster receives:** stops if the caster is at full HP. Caster HP + amount, capped; **for SPWI309 only, the excess
    becomes an op 18 max-HP bonus for 300 s**. The **target takes the full amount** as op 12 **magic** damage, however
    much the caster could absorb.
  - **2** swaps the two HP values; **3**: target + p1 % of its max, caster − amount % of its max; anything else: no transfer.
  - Floating numbers over both creatures (green for party members).
- **GemRB:** `PSTOpcodes.cpp:322` `fx_transfer_hp`: amount = **min(p1 + dice, receiver's missing HP)** in both modes; the
  donor takes `Damage(amount, p2, …)`, so the damage type **is p2: 0 crushing, 1 acid** (`includes/damages.h`). Mode 3
  acts as 0, mode 4 as 1. No luck, no plane rules, no temporary max HP.
- **Difference:** 1) Vampiric Touch at level 5 (4d6, avg 14), caster missing 5 HP: original 14 damage to the target,
  caster +5 HP and +9 max HP for 300 s; GemRB 5 damage, +5 HP. 2) GemRB deals **acid** (mode 1) or **crushing** (mode 0)
  damage, so acid/physical resistance applies instead of magic resistance. 3) No plane rules (R1), no luck (E8).
- **Data affected:** 16 uses: SPWI309 (11 headers, 2d6–12d6), SPIN107 Kiss (2d4), SPIN104 Sensory Touch (1d10), `BUTCHER`
  (1d2), `GKISS`, `IRON2` (1d6).

### E-195 Tint screen
- **Status:** P   **Severity:** 3
- **Original:** `sub_4D364E`. Ignored while another tint runs, unless p2 is 200 (which ends the current tint). p2 100: fade
  to the p1 colour over "dice thrown" steps; other values: bit 0 sign, bits 1–2 mode (`dword_8DCB20`), bit 3 additive;
  lasts the effect's duration unless permanent.
- **GemRB:** `PSTOpcodes.cpp:448` `fx_tint_screen`: on non-EE PST it **replaces the colour with 50 % black**; no "one
  tint at a time" rule, no p2 200 cancel.
- **Data affected:** 28 uses p2 100 (SPWI410 ×19, SPWI116 ×9), SPIN011 p2 5, and casting effects of SPWI301, SPPR502,
  SPIN108.

### E-196 Special effect: Adder's Kiss and Ball Lightning
- **Status:** V   **Severity:** 1 (Ball Lightning) / 2 (Adder's Kiss)
- **Original:** `sub_4D3BF2`. Skips dead targets unless p2 2. The users are **SPL casting effects**: `SPWI201` Adder's Kiss
  has op 196 p2 0, `SPWI301` Ball Lightning has op 196 p2 1 (plus an op 195 tint).
  - **p2 0, Adder's Kiss:** projectile 220 carrying op 9 glow and op 51 for 5 × N s, the `S019ACID` visual, and **N acid
    hits of 2d4** delayed 75 × i (i = 0 … N − 1), **N = caster level / 3 + 1** (level of SPWI201, `sub_7B2F45`).
  - **p2 1, Ball Lightning:** projectile 224 (`CPsSpellBallLightning`, a `CProjectileMulti`, EE ctor takes the count)
    with **1–4 balls at random**; each carries `S031DELC` and op 12 **electricity** damage set by the ball count
    (`dword_8DCB28` / `dword_8DCB38`): **1 ball 4d12, 2 balls 5d4, 3 balls 2d6, 4 balls 2d4** (each).
  - **p2 2, Raise Dead:** the `SP62RDED` animation at the target.
- **GemRB:** `PSTOpcodes.cpp:603` `fx_special_effect` casts `ADDER` / `BALL` / `RDEAD` (`gemrb/unhardcoded/pst`).
  `BALL.spl`: **always one ball, 4d12**. `ADDER.spl`: **one 2d4 hit per cast**, delayed 0/5/10 … s by header (level 3,
  6, 9 …), instead of N hits.
- **Difference:** Ball Lightning never splits; Adder's Kiss hits once instead of level / 3 + 1 times (level 9: 4 hits,
  ~20 total, vs one, ~5). The factory's delay unit (`sub_4A56EB`, 75 × i) isn't settled: 5 s steps if it's ticks.
- **Corrects S37:** Ball Lightning works in the original, through this casting effect.

### E-012 Damage, in full
`sub_4B245B` (1,262 lines). Read in order of what it does; E-012a (luck on dice), E-208 (Iron Fist) and R1 (Carceri) are
not repeated. Creature fields learnt here: **+21266** word = Cloak of Warding / Infernal Shield absorb pool (set by op 201
case 0/14 to 3–12 + L), **+21268** Shield flag, **+21269** Black Barbed Shield flag, **+21270** byte = reflections left
(Pain Mirror 1, Balance in All Things L / 5), **+21271** Guardian Mantle flag, **+21272** word = Armor pool (L + 8).
All data uses mode 0 (172 uses: fire 51, magic 50, piercing 19, electricity 15, acid 9, crushing 9, cold 6, …).

#### E-012b Damage on a petrified or frozen creature kills it
- **Status:** V   **Severity:** 2
- **Original:** first thing after the immunity checks: base state 0x80 (`STONE_DEATH`) → applies op 13 Death p2 0x40;
  state 0x40 (`FROZEN_DEATH`) → op 13 p2 0x80; the damage itself is dropped.
- **GemRB:** `Actor.cpp` `Actor::Damage`: the "instant death if petrified or frozen" branch needs `CanGetChunked`, which
  returns false for every PST creature (`Actor.cpp:4382`). The damage is applied normally.
- **Difference:** a petrified creature (Ax of Torment's level > 8 outcome, op 134) shatters at the next damage effect in
  the original and survives in GemRB.

#### E-012c Plane bonuses by spell (extends R1)
- **Status:** V   **Severity:** 2
- **Original:** for the effect's source spell: in **Carceri**, Chromatic Orb (`SPWI101`), Fist of Iron (`SPWI104`) and
  Elysium's Tears (`SPWI305`) roll **maximum dice**; Deathbolt (`SPWI803`) gets **+1**. In **Baator** Deathbolt gets
  **+6**; on the **Negative Material Plane** Deathbolt gets **+1**. `MAGIC02` plays when any bonus applied.
- **GemRB:** none (R1).

#### E-012d Damage absorbers and Guardian Mantle
- **Status:** V (original) / ? (GemRB)   **Severity:** 2
- **Original:** before resistances, unless the damage was cancelled:
  - **Guardian Mantle** (+21271): unless the damage type is in 0x6400000, the **source** makes a saving throw at −4
    (an op 0 effect's save check with fresh d20 rolls); depending on the result the **whole damage is ignored**.
    The direction of the check (save succeeds → blocked or the reverse) still needs one look at the save method.
  - **Cloak of Warding / Infernal Shield pool** (+21266): absorbs up to 127 per hit; the damage is reduced by the pool.
  - **Armor pool** (+21272): counted down by min(damage, 127) but **does not reduce effect damage** (it only absorbs
    elsewhere, presumably weapon hits).
  - `S034DMG2` plays on the target when Shield, Black Barbed Shield, Guardian Mantle or a pool is active.
- **GemRB:** Cloak of Warding is a stoneskin count (`fx_overlay` case 0, `IE_STONESKINS`); Guardian Mantle is
  `IMM_GUARDIAN` immunity; whether either touches effect damage in `Actor::Damage` wasn't traced.

#### E-012e Pain Mirror reflects to every enemy around the target (resolves R4)
- **Status:** V   **Severity:** 2
- **Original:** while the target's reflection counter (+21270) is above 0 and it has an attacker: plays `S013SMSH` and
  `PAINM05`, and **every enemy of the target within 120** (`sub_4128C8` + `sub_47699E`) takes op 12 **magic** damage
  equal to the damage taken (**× 2 in Carceri**). The counter drops by one per damage event; at 0 the op 9 glow
  (0x30000C) is removed. Pain Mirror sets 1 (one reflection), Balance in All Things L / 5. The target still takes its
  damage.
- **GemRB:** `PSTOpcodes.cpp:1000` `fx_overlay` case 3/16: `DamageLastHitter(target->LastDamage, LastDamageType)`: only the
  **last hitter**, the **original damage type**, no count limit beyond the effect's life, no Carceri doubling.
- **Difference:** a fireball reflected by Pain Mirror: original hits all enemies within 120 once with magic damage;
  GemRB hits the last attacker with fire damage (fire resistance applies), possibly several times.

#### E-012f Difficulty scaling: party members, not enemy sources
- **Status:** V   **Severity:** 2
- **Original:** mode 0 only, after resistances: **if the target is a party member**, damage += damage × difficulty % / 100
  (one of two game-option percentages, `+9122` / `+9126` of the options object, chosen by a flag at `+3586`). Then, for
  a party member with **max HP < 14**, damage above max HP is cut to **max HP − 1** (a low-level character can't be
  killed outright by one big effect).
- **GemRB:** `Actor.cpp` `Actor::Damage`: damage += difficulty % **when the hitter's EA is above GOODCUTOFF** (enemy
  source), whatever the target; no low-HP rule.
- **Difference:** an enemy's spell hitting another enemy is scaled in GemRB, not in the original; a trap/environment
  damage with no hostile source hits the party unscaled in GemRB; a level-1 Nameless One (max HP < 14) can be one-shot
  in GemRB.

#### E-012g Modes other than 0
- **Status:** V   **Severity:** 3 (no PST data uses them; only matters for ports)
- **Original:** p2 low word **0** subtract, **1** set HP to the amount (capped at max), **2** HP = **current HP × p1 / 100**,
  **4** lose p1 % of **max** HP, 3 and others: nothing. Resistances and difficulty apply to mode 0 only.
- **GemRB:** `FXOpcodes.cpp:1377` `modtype = p2 & 3`: 1 sets (no cap), **2 loses p1 % of max HP** (the original's mode
  4), mode 4 → 0 (flat p1 damage). Resistance applies in every mode.

#### E-012h Smaller points
- **Status:** P/S   **Severity:** 3
- Effect byte +6 == 255 halves the damage before anything else (meaning of the byte not identified).
- Resistances: percent per damage type from derived bytes (+3865 … +3875, +3973, +3974), integer truncation; same idea as
  GemRB's `ModifyDamage`. Not compared value by value.
- Death from effect damage is always op 13 **p2 4 (normal death)**, whatever the damage type; GemRB never chunks in PST
  (`CanGetChunked`). P.
- Non-poison damage has a 1-in-10 chance of a "hurt" sound-set line (`off_8DC96C`, entry 12); floating damage numbers
  (party colour differs); the creature plays the damage sequence (4) unless its current sequence is in a skip list
  (4, 6, 9, 10, 12–14, 29–31, 35). Presentation.
- **Mirror images:** GemRB lets an image absorb effect damage (`Actor::Damage`, unless `SF_BYPASS_MIRROR_IMAGE`); no
  mirror-image check was seen in the original op 12 (S).

---

### E-013 Death: no level bands, p2 ignored, companion game-over rules
- **Status:** V (code) / S (game)   **Severity:** 2 (1 for the game-over part, see R2)
- **Original:** `sub_4B5DCF`. Skips the target if its animation object says it is already dead (vtable slot +120) or
  creature flag `+20958` is set. Otherwise: already-dead state (0x800) only plays sequence 6. Parameters are **never
  read**: p1 and p2 are ignored, there is **no level band and no HP threshold** in this effect (the "bands" of Cloudkill
  are in the spell itself, SPWI501 header levels, not in op 13). The save (SPWI501/803 = spell save 0x4, SPWI909 none)
  is handled before the handler, as for any effect.
  Steps: companion game-over rules (below); clear two state bits on the creature (`+1288` 0x80/0x40);
  remove the creature's own **op 109 (Hold) and op 162** effects; mark everything in its list at `+9624` as done unless its
  type is 5 or 9; clear derived/base bits 0x4000 and 0x80000; **HP = 0**, set base and derived state **0x800 (dead)**; play
  sequence 6; select the next party leader if the dead one was the leader; remove it from the party formation; send the
  death event to scripts. The effect is not kept (returns done).
- **Companion rules** (name table `off_9607A0`/`dword_9607C4`, matched on the script name at `+1172`): NAMELESS 0,
  ANNAH 1, IGNUS 2, GRACE 3, NORDOM 4, VHAIL 5, MORTE 6, DAKKON 7, others −1.
  - Any companion (not 0, not −1): `PM_KILLED` = 1 when a check on the current area/object holds (`sub_40F297`, S).
  - **ANNAH (1): if `Pharod_Dead` == 1 and `Know_Painted_Door` < 2, `Game_Over` = 3.**
  - **NAMELESS (0):** the game's death UI is raised (death window); in AR1200/AR1201 `Death_Fortress` += 1 and
    `Game_Over` = 4 once it exceeds `Fortress_Death_Counter`; in AR1203/AR1204 `Game_Over` = 4 at once.
- **GemRB:** `FXOpcodes.cpp:1418` `fx_death`: maps p2 to a damage type (p2 4 and 0 → crushing / acid, flags for
  chunk/petrify/freeze that no PST data uses), cures frozen/petrified bits, morale 10, then `Actor::Damage(0)` +
  `Actor::Die` (`Actor.cpp:5725`): cures poison/hold/stun, sets dead, triggers, XP, `PM_KILLED` when a **party member is
  killed by a party member** (`Actor.cpp:5826`).
- **Difference:** (1) the p2 switch is dead code for PST data (only p2 0 and 4 are used: P). (2) The companion game-over
  rules (`Game_Over` 3 and 4, `Death_Fortress`) are not reproduced: **R2 stands, but the Game_Over 3 rule is about Annah,
  not Pharod** (corrected in findings). (3) `PM_KILLED`: original condition unknown, GemRB sets it for party-kills-party.
  (4) Original removes the creature's own Hold effects only; GemRB's Cure:Hold/Poison/Stun are broader (harmless).
- **Data affected:** Cloudkill SPWI501 (3 headers), Deathbolt SPWI803 (10), Power Word Kill SPWI909 (5). Scripts can also
  kill through `Kill()` / `ApplySpell` with these.

---

### E-129 Aid: fixed 8 HP per p1, not 1d8 per p1
- **Status:** V   **Severity:** 2
- **Original:** `sub_4C9A26`. Guard: derived state **0x8000000** (= GemRB `STATE_AID`); if set, nothing (non-cumulative). Else set
  it, then: damage bonus byte `+3281` += p1, THAC0 `+3220` −= p1, all five saves `+3222..+3226` −= p1. **First application
  only:** p2 = **8 × p1** (a plain loop adding 8, no dice); current HP += p2 if below max. Every pass: max HP (`+3208`) += p2.
  No morale change, no icon.
- **GemRB:** `FXOpcodes.cpp:4214` `fx_set_aid_state`: `p2 = Roll(p1, 8, 0)` = **p1d8**, rest the same (state, max HP, saves,
  to-hit, damage bonus); adds a portrait icon and colour pulse in enhanced-effects games.
- **Difference:** Aid (p1 = 1) gives **8 HP every cast** in the original, **1–8 (avg 4.5)** in GemRB.
- **Data affected:** SPPR201 Aid (23 effect lines, all p1 = 1, p2 = 0).

### E-073 Damage bonus (also the unidentified byte in E-203)
- **Status:** P   **Severity:** 3
- **Original:** `sub_4C15F9`: derived signed byte `+3281` += p1, clamped to **−20..+20**; p2 ignored. This byte is the
  **damage bonus**, so E-203 Curse (`−p1`) and E-129 Aid (`+p1`) both change damage, not an "unidentified" stat.
- **GemRB:** `FXOpcodes.cpp:3010` `STAT_MOD(IE_DAMAGEBONUS)` (p2 0 add / 1 set / 2 percent): same for PST data (every use p2 = 0,
  p1 from −4 to +8). No ±20 clamp (not reachable with the data).
- **Difference:** none for data. **E-203 addendum:** original Curse also gives **−p1 damage**; GemRB `fx_curse` does not touch
  `IE_DAMAGEBONUS`. Aid's +p1 damage is in GemRB.
- **Data affected:** 15 uses (LENS*, TTDECEIV, SPWI308, SPIN101).

### E-039 Sleep (State:Helpless)
- **Status:** S   **Severity:** 3
- **Original:** `sub_4BC71E`. Dead target: nothing. Timing 1 (permanent): base+derived state **0x20 (helpless)** and flag `+3292` = 1.
  Otherwise derived 0x20 and `+3292` = 1; **first application:** builds a delayed **op 162** (wake-up) after the remaining
  duration, an **op 8** and an **op 191** ("I001ZZZZ" Zzz bam) lasting the remaining seconds, interrupts the creature and plays
  sequence 8. Op 162 (`sub_4CDCBB`) clears `+3292`, clears derived 0x20 and removes the target's op 109 effects. It does **not**
  set the sleep bit (0x1).
- **GemRB:** `FXOpcodes.cpp:2207`: sets `STATE_HELPLESS | STATE_SLEEP`, a stance effect (sleep) and a delayed get-up stance;
  outside EE also `SS_NOAWAKE` ("doesn't wake on damage") and a sleep icon.
- **Difference:** extra `STATE_SLEEP` bit; GemRB's get-up is an animation stance, the original's wake-up also drops hold effects
  (109). Whether damage wakes a sleeper in the original: no reference to `+3292` or 0x20 in op 12 (`sub_4B245B`), so likely not (S).
- **Data affected:** SPWI401 (Sleep, 2 lines).

### E-045 Stun
- **Status:** P   **Severity:** 3
- **Original:** `sub_4BDD35`: timing 1 → base state 8 and done; always derived state **8**. Nothing else (no immunity checks,
  no animation, no duration roll).
- **GemRB:** `FXOpcodes.cpp:2399`: derived `STATE_STUNNED` + icon; extra branches are IWD/BG2 only (Eye of Fortitude, Bloodrage,
  p2 = 2 power-word stun); the cutscene skip is GemRB-only, harmless.
- **Data affected:** SPIN101, DDMACE (p2 0, timing 0): parity.

### E-128 Confusion
- **Status:** P/S   **Severity:** 3
- **Original:** `sub_4C971E`. First application: a colour-pulse effect (op 9, p1 `0x180018`) for the effect's duration, a floating
  string (text 28081, font TRMTFONT) over the target; then derived state **0x80000000**; timing 1 also sets the base bit and ends.
- **GemRB:** `FXOpcodes.cpp:4190`: `STATE_CONFUSED` (base only for timing 4), icon only if enhanced effects.
- **Difference:** presentation only (pulse, floating text) for data (timing 0 ×4, timing 3 ×1). GemRB base-sets at timing 4 where
  the original does at timing 1 (no data uses either). How the confused creature then acts is AI code, not read here.
- **Data affected:** IRON3, JESTER, NETTLES, TTANARCH, SPWI402.

### E-006 / E-044 Charisma and Strength modifiers
- **Status:** P   **Severity:** 3
- **Original:** `sub_4B0EDC` (CHR, derived byte `+3257`, base `+1830`) and `sub_4BD6D1` (STR, derived `+3251`, base `+1824`):
  p2 **0 add, 1 set, 2 percent**, result clamped **1..25**; p2 ≥ 3 is an error (assert). Timing 1 writes the base and ends.
  CHR only: on first application with p1 = 0 the amount is rolled as `dice count (+32)` × (1..`sides (+36)`), luck-adjusted
  (Friends, SPWI114). STR has no dice mode, no STR-extra handling.
- **GemRB:** `FXOpcodes.cpp:1264` / `:2342`: same modes; STR keeps a p2 = 3 dice branch (Power of One comment) that no PST data
  reaches; the PST rule that SPWI114 replaces its previous cast is a GemRB addition (`SourceType == 2`): the original handler
  does not do it, a spell-level rule might (not found, S).
- **Data affected:** CHR 21 lines (p2 0/1), STR 17 lines (p2 0/1, p1 −1 mostly): parity.

### E-042 Wizard spell slot modifier
- **Status:** P   **Severity:** 3
- **Original:** `sub_4BD2B4`. p2 ≠ 0: p2 is a **bitmask of levels** (bit 0 = level 1 … bit 8 = level 9); for each set level where
  the creature already has slots (`+3568 + 16*i` ≠ 0) add p1 to both slot counts (`+3568`, `+3570`). p2 = 0: **double** the
  slots of the first p1 levels.
- **GemRB:** `FXOpcodes.cpp:2293` + `Spellbook.cpp:714`: same rules (no slots at a level → no bonus; p2 = 0 doubles the first p1
  levels); extra HoW p2 = 0x200 branch unused by PST.
- **Data affected:** 27 lines (Karach items, ZERO, TTMAGE): parity.

### E-098 Regeneration
- **Status:** P   **Severity:** 3
- **Original:** `sub_4C2F70`, for timing 2 (equipped): p2 **0** heal (`+1294`) HP per second, **1** p1 % of that per second,
  **2** p1 HP per second, **3** 1 HP every p1 seconds (15 × p1 ticks); heals only while HP < derived max (`+3846`). Other
  timings build a separate aura-like object (not read).
- **GemRB:** `FXOpcodes.cpp:3480`: same four modes (p2 3 → 1 HP every p1 seconds, scaled by game speed).
- **Data affected:** all 19 lines use p2 = 3 (p1 4..20); BLOODFLY uses timing 0 (the unread branch).

### E-120 Protection from weapons
- **Status:** V (one item)   **Severity:** 3
- **Original:** `sub_4C7F50` builds an immunity record (flag value, flag mask, enchantment level) by p2: 0 level p1; 1 magical (flag
  64), 2 non-magical, 3 silver (256), 4 non-silver, **5 non-silver and level 0**, 6/7 two-handed (2), 8/9 cursed (16), 10/11 cold
  iron (512); record added on every pass.
- **GemRB:** `FXOpcodes.cpp:3924` same table, **except p2 = 5 means *silver* and level 0** (value = silver flag).
- **Difference:** p2 5 is "not silver" in the original; GemRB makes it "silver". Data: SILVMAG.itm (1 line). The check that uses
  the record (op 12, `sub_4B245B`) was not compared here.
- **Data affected:** P1SF…P3SFCF (p2 0/4/11), PLUS1IM…PLUS6IM (p2 0), SILVMAG (p2 5).
