# Track B2: the generic effect pipeline vs PST:EE (`wp11_effect_pipeline.md`)

Judged against PST:EE. Path of one effect in EE: `CGameEffect::CGameEffect(Item_effect_st*, …)` (6EC970, copies the
SPL/ITM feature block) → `CGameSprite::AddEffect` (9A7290) → `CGameEffect::CheckAdd` (6FA720: probability, immunities,
bounces, level range, save via vtable +64 = `CheckSave`) → `CGameEffect::ResolveEffect` (6BD170: timing) →
`ApplyEffect`. GemRB: `EffectQueue::AddAllEffects` / `AddEffect` / `ApplyEffect` (`gemrb/core/EffectQueue.cpp`).

Done: feature-block fields, rolls (shared per application), probability, level range, MR, saves (C-14/C-15/C-16 in
`wp10_combat.md`), timing modes and units, dice timing (E8), save-for-half (C-14). Stacking, dispel and effects on
death: see "Not covered" at the end.

### P-1 Feature block fields
- **Status:** P   **By:** opus
- **EE:** `CGameEffect::CGameEffect(Item_effect_st…)` :149-188: opcode +0, target +2, power +3, p1 +4, p2 +8, timing +12
  (low byte; resist bits 0x100/0x200 go to the resist flags +92), duration +14, probability high +18 / low +19, resource
  +20, dice count/sides +28/+32 **or** min/max level when the opcode has no dice (`a6`), save type +36, save bonus +40,
  special +44.
- **GemRB:** `EffectQueue.cpp:697` `EFFECT_DICED` decides dice vs level range the same way.

### P-2 One set of rolls per application, shared by all its effects
- **Status:** P (different refresh point)   **By:** opus
- **EE:** `CGameSprite::AIUpdate` :321-332 / `ProcessEffectList` :582: 5 save rolls 1-20, MR roll 0-99 (+18829),
  probability roll 0-99 (+18830), refreshed every AI update; `AddEffect` passes them to `CheckAdd`.
- **GemRB:** `EffectQueue.cpp:662-669` `AddAllEffects`: one `Roll(1,100,-1)` per application, `RollSaves` per target.

### P-3 Probability and magic resistance use the same roll in GemRB
- **Status:** V   **Severity:** 2   **Uses:** 78 SPL/ITM effects with a probability band, in 31 files   **By:** opus
- **EE:** `CheckAdd` :129-131: the effect applies only if the **probability** roll (+18830) is within [low, high];
  magic resistance compares MR with a **separate** roll (+18829) in `CGameEffect::CheckSave` :133.
- **GemRB:** `EffectQueue.cpp:662-669` sets `fx.RandomValue` once for the whole application and uses it for both
  `CheckProbability` (:741) and `CheckMagicResistance` (:983, `RandomValue < MR`).
- **Difference:** the two are correlated in GemRB. Against a target with MR 30, an effect in the band 0-49 applies
  only for rolls 30-49 (20 %) instead of 50 % × 70 % = 35 %; a band 0-25 effect never lands (0 % instead of 17.5 %).
  Bands used: 0-50 (18), 0-25 (15), 0-33 (8), 0-5 (7), 0-75 (6), 0-35 (6), 33-66/66-100 splits, … in AXOFT, BSTORM,
  BSTORM2, DHELL, RUNE, SHADOW1-3, SPWI107, SPWI116, SPWI121, weapons (GRINDER, JESTER, NETTLES, VTEETH…). Only matters
  for resistible effects on targets with MR.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameEffect::CheckAdd(" 126 132`; `sed -n 660,670p gemrb/core/EffectQueue.cpp`;
  `sed -n 980,986p gemrb/core/EffectQueue.cpp`.

### P-4 Level range (non-dice opcodes)
- **Status:** P   **By:** opus
- **EE:** `CheckAdd` :475-505: the target's highest level must be ≤ max (if set) and ≥ min (min > 0xFFFF → 0).
- **GemRB:** `EffectQueue.cpp` ~720-733 min/max affected level. Same.

### P-5 Timing modes and units in PST
- **Status:** P   **By:** opus
- **EE:** `CGameEffect::ResolveEffect` (6BD170): mode 0 → duration × 15 ticks (cap 143,165,576 s) → absolute 4096;
  10 → already ticks. **PST only** (`ENGINE_MODE == 3`): mode **3** waits `special` (+72) **ticks**, or the duration
  value as ticks when special is 0, then (case 6) runs for the saved duration (+284) × 15; mode **4** waits the duration
  value **in ticks** (other games × 15); mode 5 × 15 in all games. Modes 7/8 switch to 1/2 when the delay ends.
- **GemRB:** `EffectQueue.cpp:1217-1240`: PST delays (modes 3 with `IsVariable`, 4, and everything except
  INSTANT_LIMITED and absolute) are taken **in ticks**; mode 0 via `PrepareDuration` in seconds. PST data uses modes 0
  (374), 1 (825), 2 (489), 3 (63), 4 (490), 8 (1), never 5. Same result for every mode PST uses.
- Note: S41 (Acid Storm "2 s instead of 20 s") is about the unit: `ASTORM` op 12 is mode 4 with duration 2 → 2 ticks
  in EE as in GemRB; EE: same as GemRB.

### P-6 Damage dice timing
- E8 / E-012a stand (EE: same): EE rolls op 12 dice when the effect is applied, each die minus the **target's** luck
  (`CGameEffectDamage::ApplyEffect` :747 `UtilRandInt(sides, -target luck)`); GemRB rolls once when queued, no luck.

### Not covered (left for track C / later)
- Stacking and refresh of the same effect twice (EE: `CGameEffect::Compare` 6FBAB0, used by the removal opcodes; PST's
  non-cumulative variants, e.g. `CGameEffectNon_CumulativeEmbalming`, are covered per opcode in `wp2_opcodes.md`).
- Dispel (op 58 isn't used by PST data: `maps/opcodes.tsv` uses column) and effects on death (EE: E-013 Death clears
  the list at `+9624` except types 5/9).
