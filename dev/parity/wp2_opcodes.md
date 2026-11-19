# WP2: effect opcodes, original vs GemRB

Progress: 82, 100, 138, 146, 186, 193, 194, 201, 203–211 done. Next: 147, 148, 187–192, 195, 196, then 12, 13, 0, 54, 73, 17, 39, 45, 109, 128 by use count. Original handler = ApplyEffect (vtable slot 2,
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
