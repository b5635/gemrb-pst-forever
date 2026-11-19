# WP2: effect opcodes, original vs GemRB

Progress: 82, 100, 138, 146–148, 186–196, 201, 203–211 done. Next: 12, 13, then 0, 54, 73, 17, 39, 45, 109, 128 by use count. Original handler = ApplyEffect (vtable slot 2,
`dev/parity/maps/opcodes.tsv`), decompiled at `.re/orig/dump/dec/<addr>.c`. Effect fields: p1 `+8`, p2 `+12`, timing
`+16`, duration `+18`, resource `+24`. Creature derived stats start at `+3204` (state bits); `+3220` THAC0,
`+3222`–`+3226` the five saving throws, `+3245` to-hit bonus, `+3883` luck. Statuses as in AGENT_GUIDE section 4.1.

---

### E-203 Curse makes saving throws *better* in GemRB
- **Status:** V   **Severity:** 2
- **Original:** `sub_4D6BAF`. Once (if derived state bit 0x10 isn't set yet): set bit 0x10, **add p1 to THAC0** (`+3220`)
  and to **all five saving-throw values** (`+3222`–`+3226`), and subtract p1 from derived byte `+3281` (unidentified).
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
