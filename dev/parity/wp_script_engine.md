# A5: the script engine (round 12, 2026-11-19), judged against PST:EE

EE entry points: `CGameAIBase::ProcessAI` (`.re/ee/dump/dec_all_named/CGameAIBase_ProcessAI_.c`), the same logic
again in `CGameAIBase::ProcessPendingTriggers(int)`, `CAIScript::Find` → `CAIResponseSet::Choose`, response
execution `sub_65A2C0`, `CAICondition::Hold` (OR counting), `CGameAIBase::SetTrigger` (raises the "new trigger"
flag). GemRB: `Scriptable::Update` / `Scriptable::ExecuteScript` (`core/Scriptable/Scriptable.cpp`),
`GameScript::Update`, `Condition::Evaluate`, `ResponseSet::Execute` (`core/GameScript/GameScript.cpp`).
Creature field names below are EE dword indexes into `CGameAIBase` (no names in the binary).

## Slot order, Continue, stopping (P)
- EE: override slot (`+94` qword) first, then six slots `+95…+100` (area, specifics, class, race, general,
  default) in order. The first slot whose chosen response is non-empty and does **not** end in `Continue()`
  stops the pass; responses ending in `Continue()` are accumulated (`CAIResponse::Add`) and run together with the
  next slot's, so **Continue chains across slots** in EE (round 11's note said the original keeps it inside one
  script: EE decides).
- GemRB `ExecuteScript`: slots 0…n in order, `continuing` passed from slot to slot, stops at the first block that
  doesn't continue. Same. P.

## Same block still running (P)
- EE `sub_65A2C0`: if the chosen response has the same (slot, block) as the one that queued the current actions,
  nothing happens; else the queue is cleared (vtable +248) and the response's actions are queued; non-creatures
  get `SetInterrupt(FALSE)` first.
- GemRB `GameScript::Update`: `lastResponseBlock == a` → leave the queue, otherwise `Stop()` and execute. P.

### SE-1 How often scripts are evaluated (V, sev 2)
- **EE** `ProcessAI:104-171`: a creature evaluates its scripts once every **16 AI ticks**, staggered by its object
  id (`(id ^ counter) & 0xF`), timers every 15 ticks. While it has an action queued it skips evaluation unless a
  trigger arrived since the last pass (`SetTrigger` sets `+302`) or it has skipped 15 passes in a row (`+570`
  counter, i.e. about 16 s), or a 5-pass window opened by `+224` (`+571`) is running.
- **GemRB** `Scriptable::Update`: evaluates **every tick** when the creature has no current action, has pending
  triggers (5-tick countdown) or idled 16 ticks, and every tick for any creature on screen in an explored spot,
  busy or not.
- **Difference:** idle creatures run their scripts up to 16 times as often in GemRB. Blocks gated only by
  `RandomNum`/`!TimerActive`-free conditions fire far more often (ambient barks, random walks, `RandomNum`
  ambushes). A busy on-screen creature in GemRB re-checks every tick, so any other block that turns true
  interrupts its current action at once (`Stop()`); in EE it keeps going until a trigger arrives or ~16 s pass.
- **Re-check:** `python tools/parity/dumps.py lines ee "CGameAIBase::ProcessAI(void)" 104 171`;
  `sed -n 225,297p gemrb/core/Scriptable/Scriptable.cpp`.
- Turn-based note: the CombatDirector drives combat turns itself; this matters for creatures outside the fight
  and for how quickly a fight starts.

### SE-2 Cutscene mode does not stop scripts in PST (V, sev 2)
- **EE** `ProcessAI:201` and `ProcessPendingTriggers:77`: the cutscene flag (`CInfGame` dword 11817, set by
  `CMessageCutSceneModeStatus::Run`) blocks the non-override slots **only when the engine is not PST**
  (`ENGINE_MODE != 3`). In PST every creature keeps evaluating its scripts during `StartCutSceneMode`; only a
  creature with interrupts off (`+294`, `SetInterrupt(FALSE)`, which cutscene scripts put in front of their
  actions) or the `+304/+305` states runs the override slot alone.
- **GemRB** `Scriptable::ExecuteScript:304`: in cutscene mode no script runs at all (only area/proximity scripts
  with `CutsceneAreascripts`, not set for PST).
- **Difference:** creatures not taking part in a cutscene stand frozen in GemRB and act in EE (ambient scripts,
  guards reacting to triggers). Risky in both directions; check cutscenes where bystanders matter before fixing.
- **Re-check:** `python tools/parity/dumps.py grep ee "11817\)" --max 60 | grep ENGINE_MODE`.

### SE-3 Response weights (V, sev 3; recommendation: leave GemRB)
- **EE** `CAIResponseSet::Choose`: r = (rand15 × total) >> 15 (0…total−1), the first response whose running sum
  is **≥ r** wins: response 1 gets w1+1 chances, the last gets w_last−1. A last response of weight 1 never runs.
- **GemRB** `ResponseSet::Execute`: r in 0…total−1, first with weight > r: exact weights.
- **Data:** 460 multi-response sets in PST BCS; 16 (all in `AR0600`) end in a weight-1 response that EE never picks.
  Following EE here only removes content; noted, not recommended.

## Other items
- **Instant actions (S, sev 3):** both engines take the list from `INSTANT.IDS`; GemRB loads the original's
  (177 lines). EE's own `INSTANT.IDS` is renumbered for EE's action ids; by name EE adds `StartStore`, `RestParty`,
  `LeaveAreaLUA`, `ReallyForceSpell` and the dither actions, and drops `SetTeam` (keeps `ChangeTeam`). EE in PST mode
  also treats `Wait`, `SmallWait`, `Face`, `GlobalSHR` as instant while a counter at `g_pBaldurChitin[563]+275+168` is
  positive (not identified). Instant actions in a queue run back to back in one tick in both.
- **OR(n) (P):** `CAICondition::Hold` counts the next n triggers, one true one is enough; GemRB
  `Condition::Evaluate` the same (`EFFICIENT_OR` is IWD2 only).
- **Negated event triggers:** see T13 (A3). **Variable scopes / KAPUTZ:** A9 (P, round 8). **Timer units:** A1
  (StartTimer, StartRandomTimer A11). **ActionOverride:** A1 ledger row.

## A10: things scripts observe indirectly

### SE-4 Death counters (V/S, sev 2)
- **EE** `CGameSprite::SetDeathGlobals` (called once per death by `CGameEffectDeath::ApplyEffect`, guarded by flag
  0x40000000), driven by the CRE attribute flags (0x2E0): 0x10 → `<death variable>_Dead_Kaputz` +1 (EE's stand-in
  for KAPUTZ `<name>_DEAD`); 0x80 → `KILL_<FACTION.IDS name>` +1; 0x100 → `KILL_<TEAM.IDS name>` +1, **always with
  the `KILL_` prefix**; 0x400/0x800/0x1000/0x2000 → `GOOD`/`LAW`/`LADY`/`MURDER` += the CRE's mod bytes. All go to
  the game's global table (`CInfGame` +52000, the one holding `Game_Over`). **There is no case for 0x20 (count the
  creature-type variable at 0x2BC) or 0x40 (`KILL_` prefix for it).**
- **GemRB** `Actor::Die` (`HAS_KAPUTZ` branch): 0x20 → `<type>` or `KILL_<type>` (0x40) +1 in KAPUTZ; 0x80/0x100 →
  faction/team name, `KILL_` only when 0x40 is set; 0x10 → KAPUTZ `<scriptname>_DEAD`; the four counters the same.
- **Data:** 929 CREs set 0x20 (all with 0x40: `KILL_townsperson` 167, `KILL_hive_townsperson` 148, `KILL_thug` 81,
  …), 7 set faction/team without 0x40 (MOCHAI, SMITH…SMITH6). Dialogues read `Kill_Githyanki`, `Kill_Githzerai`,
  `Kill_Special_Abashai` in KAPUTZ: the githyanki soldiers (`GITHSOL*`, flags 0x60) feed `Kill_Githyanki` **only**
  through the 0x20 path, which EE doesn't have.
- **Status:** V for the prefix rule (7 CREs, sev 3); **S** for 0x20: either EE dropped the type counter (then EE
  never counts githyanki kills and GemRB matches the original design) or it lives elsewhere (`CGameSprite::Die`
  path not found). Recommendation: keep GemRB's 0x20 handling until that is settled.

### SE-5 Party XP (V, sev 3; same as round 8's AddexperienceParty note)
- EE `CInfGame::AddPartyXP`: adds the difficulty XP percentage (`CInfGame` +11851, multiplayer +11852), divides by
  the living party members, and gives the remainder out one point each to the first members.
- GemRB `Game::ShareXP`: divides by the living members, drops the remainder, no difficulty percentage there.
- Not confirmed: that kill XP goes through `AddPartyXP` in EE (its callers: script actions, `ApplyTriggers`,
  lock picking, trap removal).

### Other A10 items
- `Dead("name")`: EE reads `<name>_Dead_Kaputz`, GemRB KAPUTZ `<name>_DEAD`: same variable in each engine's own
  storage. P.
- Rest: `RestParty` (A1, round 2 A-RestParty), `PSTCanRestParty` (track C, WP6).
- Item use-ups that quests test (`PartyHasItem` after charges run out) and store transactions: track C items/stores.
