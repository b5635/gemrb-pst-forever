# PST parity plan

Goal: make GemRB run Planescape: Torment's game logic the way the original engine does. That covers
spells, effects, scripts and rules. The turn-based rule from CLAUDE.md applies here too: loose on
presentation, exact on anything a script, dialogue, item or spell can observe.

Evidence and per-item detail: [dev/parity/findings.md](dev/parity/findings.md) (finding ids S#, E#, A# below).
Method and tools: [dev/parity/README.md](dev/parity/README.md).

## 1. Ground rules

- **The original Torment.exe is the reference.** PST:EE's symbol-rich binary is the map: read the EE function to
  understand a feature, then check the matching original code (same asserts, same constants) before
  changing GemRB. Where EE deliberately differs, follow the original unless we decide otherwise and write that down.
- **Never commit decompiled code.** Port behaviour, not text: write GemRB code in GemRB's style from our
  description of what the original does.
- **Every fix gets a check:** a unit test where the logic is isolated (opcodes, formulas), or a staged
  in-game check (`tb_spell_suite.py`, a new script test for actions). The suite currently only asks
  "did something happen"; phase 1 adds "did the *right* thing happen".
- **Toggles:** behaviour that is new rather than a bug fix gets a toggle in `tools/dev_settings.ini`
  (CLAUDE.md). Plain bug fixes (wrong names, inverted caps, missing actions) don't.
- Combat-relevant work first (turn-based priority), then story and scripts, then presentation.

## 2. Phases

**Order (decided 2026-11-18): investigate everything first, then fix.** That means: phase 0, then the
investigation half of phases 1, 4, 5 and 6 (read the original and write the verdicts into findings.md), then
the fixes in phase 2, 4, 5 and 6, then phase 3 (porting the hardcoded spells) last, then phase 7.

### Phase 0: audit tooling (done 2026-11-18)
IDA databases for both exes, the decompile and dump scripts, and the data, opcode, scripting and spell
comparisons in `tools/parity/`, with generated tables in `dev/parity/`.

### Phase 1: expectations in the spell suite
For each hardcoded spell, write down what the original does: targets, roll, effects, durations
(`dev/parity/spell_expect.json`, from the `CPsSpell*` reading). Teach `tb_spell_suite.py` to check those
expectations instead of "something changed". Without this, phase 3 has no definition of done.

### Phase 2: quick, high-value fixes
| Item | Fix | Check |
|---|---|---|
| A1 | Implement `EscapeAreaRunning` (313): `EscapeArea` running, as in the original handler in `sub_76A7EA` (case index 57) | script test: a ghost from 0100GH* leaves running |
| E1 | Op 82: queue `Enemy()` on the target for the duration (the original's behaviour) and drop the `SetAIScript` hack | Litany of Curses on a neutral: it turns hostile, then reverts |
| S7 | Fix the Strength cap in `fx_overlay` case 17; compare the dice with `CPsSpellStrength::Fire` | unit test for the cap; a suite expectation |
| S5 | Add projectile row 270 for the traps; check `DoesTrapHitTarget` | trigger a Mortuary trap |
| S11 | `damage.2da` → `T_FIRE01`; fix the `ARARROW` and `DBOLT` BAM names (look up which BAMs the original uses) | the suite's error lines are gone |
| S9 | Celestial Host and Rune of Torment: find why the turn never frees (a hold that is never released, or the movie in `chost`) | the suite's hold/stall checks |
| E3 | Op 186: honour −1 = clear, ignore other values | unit test |

### Phase 3: hardcoded spells (the bulk)
36 `CPsSpell*` classes plus Mechanus' Cannon, Spiritual Hammer and Call Lightning. Two ways to port them:
- **Data** (`.pro` + helper SPL + GemRB's PRO extension fields) for spells whose class only sequences visuals
  and applies the SPL: Elysium's Tears, Embalming, Tasha's, Power of One…
- **Engine** for spells with logic: an HP pool (Power Word Blind and Kill), an attack roll (Ice Knife,
  Bladestorm, Elysium meteors, Vampiric Touch), creatures that move (Abyssal Fury, Celestial Host), state
  machines (Rune of Torment, Celestial Host, Missile of Patience). Proposal: a small "PST spell behaviour"
  hook on `Projectile`, keyed by projectile id, in `gemrb/core/` next to the existing PST projectile code.
  Each behaviour is a function that reads the same SPL the original does.

Order: the ones that do nothing first (S1 Abyssal Fury, S2 Blacksphere, S3 PW Blind), then the attack roll
(S4, which affects several spells), then each S8 item, then visuals and sounds (S10). Each spell is done when its
expectation passes in both turn-based and real-time modes.

### Phase 4: opcodes
Go through all 202 original handlers side by side with GemRB's `fx_` functions, most-used first
(opcodes.md has the use counts). PST-specific ones come first: 186–212, 82, 100, 138, 146–148. Then the ones
GemRB marks FIXME (E5). Then the ones EE renamed in surprising ways. For each: record the verdict in
opcodes.md (a hand-written column) and add a unit test for every behaviour change. E2 (Soul Exodus) and E4
(game freeze) are in this phase.

### Phase 5: scripting
- The overloaded ids (A2): read each original handler for the extra parameter (`JoinPartyEx(JoinGroup)`,
  `MoveToObjectEx(Timeout)`, `RunAwayFromEx(NoAttacks)`, `DeactivateEx(RenderMode)`, `PolymorphEx(RangeModes)`,
  `FullHealEx`, `StartCutSceneEx`) and implement it.
- Semantics of the most-used PST actions and triggers against `sub_76A7EA`, `sub_44B099`, `sub_453258` and
  `sub_778529`: start with ones GemRB has PST special cases for, and with the ones scripts use most
  (scripting.md has counts).
- A script test harness: run one action on a staged creature and check its state, like the spell suite.

### Phase 6: rules
Use [pst_functions.md](dev/parity/pst_functions.md) as the checklist: Nameless One death and revival,
level-up bonuses and proficiencies, the casting path (`SpellPST`), damage hit sounds, resting, darkness and
stealth, game-over conditions. Then the number tables EE moved out of the exe (XP, HP, THAC0, thief skills,
weapon slots); confirm each against the original exe before changing any GemRB table.

### Phase 7: EE data fixes (optional)
Sort EE's 734 changed SPL/ITM files into real bug fixes and redesigns. Offer the real fixes as an optional
data pack, off by default (Fixpack and UB already cover part of them).

## 3. Progress

| Date | What |
|---|---|
| 2026-11-18 | Phase 0 done: tools, IDA databases, findings S1–S13, E1–E6, A1–A4, rules checklist. |
| 2026-11-18 | Investigation round 2: R1–R6 (plane spell warping, Nameless One death and game-over rules, TransferHP), opcodes that are empty in the original, PST branches in generic effects, extra parameters of Ex actions. Still to investigate: per-spell expectations (phase 1), side-by-side reads of the section 8 branches, the remaining Ex actions, rule tables against the original. |
