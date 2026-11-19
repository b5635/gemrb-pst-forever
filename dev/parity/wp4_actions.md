# WP4: script actions, original vs GemRB

Progress (round 8): Ex actions, RestParty, IncrementGlobalOnce, Enemy, then by use: MoveToPoint, Wait, WaitRandom, SmallWait,
Face, Attack, SetGlobal, IncrementGlobal, BitSet. Next: the ledger's `todo` rows from the top (Continue 36, Help 17, CreateCreature 7).
Parameter distributions: `python tools/parity/actargs.py <id> [--dlg] [--where]`.
Tool: `python tools/parity/case.py action <id>` prints the original's handler (creature switch `sub_76A7EA` via
`byte_76D476`, else base `sub_44B099`). Current-action fields on the creature: int0 `+1132` (`this[283]`), int1 `+1136`
(`this[284]`), int2 `+1140`.

### A-125 DeactivateEx(O:Object, I:RenderMode): party members are immune, and the second parameter is passed on
- **Status:** V (party check) / S (RenderMode meaning)   **Severity:** 2   **Uses:** 82
- **Original:** base case 125. If the object is a creature **not in the party** (`sub_5B8B72` = portrait slot −1), send
  `CMessageSetActive` (vtable `off_8DC304`) with active = 0 and the **action's int0 (RenderMode)** as its second field.
  EE `CMessageSetActive::Run` passes that field to `CGameSprite::SetActiveAI`: the creature is deactivated, but whether
  its AI keeps running follows RenderMode. Party members are left alone.
- **GemRB:** `Actions.cpp:2790` `Deactivate`: any actor is hidden (`Hide()`); int0 ignored.
- **Difference:** 1) GemRB can deactivate party members 2) RenderMode is ignored.

### A-29 RunAwayFromEx(O, I:Time, I:NoAttacks)
- **Status:** V   **Severity:** 2   **Uses:** 874
- **Original:** creature case 24 → `sub_78DEDF`. When the action's **int1 (NoAttacks) is 0**, each update the fleeing
  creature takes its equipped weapon (none, or a launcher/ammo type → skip), computes its reach (weapon range + both
  creatures' sizes, × 16), finds the nearest **enemy within that reach** (`sub_474047`, `GetEnemyOf`) and **attacks it**
  (`sub_78113D`). NoAttacks = 1 turns that off. (IESDP: "occasionally, fleeing creatures stop to attack".)
- **GemRB:** `Actions.cpp:1598` `RunAwayFrom` → `RunAwayFromCore`: never attacks while fleeing. `GSUtils.cpp:2646`
  reads int1 as **"don't interrupt"** (`RunAwayFlags::NoInterrupt`), a different meaning.
- **Difference:** 874 uses. In the original, fleeing creatures hit enemies in reach unless NoAttacks is set; GemRB never
  does, and gives the flag an unrelated meaning.

### A-305 FullHealEx(O)
- **Status:** V   **Severity:** 3   **Uses:** 3
- **Original:** base case 305: sets the target's current HP to its max (stats object `sub_462C50`, field +28 ← +1944).
  Nothing else.
- **GemRB:** `FullHeal` → `Actor::Heal(0)` (its comment wonders whether it cures conditions).
- **Difference:** only if `Heal(0)` also cures states; verify.

### A-310 StartCutSceneEx(S:CutScene, I:Value)
- **Status:** S   **Severity:** 2   **Uses:** 2
- **Original:** base case 310 → `sub_46A64E`: runs the cutscene script; when **int0 ≠ 0** it also sends a message
  (vtable `off_8DC550`, fields set to 0 / 1) to the object the cutscene names. Class not identified yet.
- **GemRB:** `Actions.cpp:851` `StartCutScene`: `EvaluateAllBlocks(int0)`: int0 is used as "test the conditions".
- **Difference:** GemRB gives int0 a different meaning; find what message 8DC550 does (EE: search the
  `CMessage*` classes with fields at the same offsets).

### A-19, A-22, A-146 (JoinPartyEx, MoveToObjectEx, PolymorphEx)
See findings section 9 (round 2): JoinPartyEx's flag calls `sub_4089DC`; MoveToObjectEx's int is a countdown timeout in
`sub_785E47`; PolymorphEx's int1 is stored at creature byte +1991.

### A-313 EscapeAreaRunning
See finding A1: handled (creature case 57), missing in GemRB.

### A-296 RestParty(I:SuggestedDream, I:HP, I:Renting)
- **Status:** V   **Severity:** 2   **Uses:** 20
- **Original:** base case 296 → `sub_5C68CC` → `sub_5C6A9E`. Each party member gets op 17 with p1 = HP and mode 0
  (add HP), **except the Nameless One, who gets mode 4 = full heal**. A rest dream/movie is chosen (1 in 3 chance to
  keep a tie), and `TIME` plays.
- **GemRB:** `Actions.cpp:5521` → `Game::RestParty(…, hp)` → `Heal(hp)` for everyone alike.
- **Difference:** with an HP limit, the Nameless One should still wake fully healed.

### A-202 IncrementGlobalOnce
- **Status:** P (corrected round 8; was V)   **Severity:** -   **Uses:** 1,693 (1 BCS, 1,692 DLG)
- **Original:** base case 202: looks both variables up **without creating them** (`sub_463F03`, a pure hash lookup
  `sub_59389B`); if either doesn't exist, nothing happens. Otherwise, if var1 is 0, set var1 = 1 and add int0 to var2.
- **GemRB:** `Actions.cpp` `IncrementGlobalOnce`: PST's `gemrb.ini` has `NoNewVariables = 1`, so `SetVariable`
  (`GSUtils.cpp` `SetVariable`, `UpdateOrCreate(..., NoCreate)`) never creates a variable either. Remaining
  difference: if var1 is missing and var2 exists, GemRB adds int0 to var2 on every call; the original does nothing.
- **Data:** every one of the 1,693 calls names two variables declared in `VAR.VAR` (checked, script in
  `.re/notes/undeclared_vars.txt` notes), so the case never happens. The round-3 claim "GemRB creates both" was wrong.

### A-10 Enemy()
- **Status:** P   Original `sub_7A0255`: EA = 255 in all three copies, removes op 5 (charm) from both effect lists. GemRB
  `Enemy` does the same.

## Round 8: by use count

### A-23 MoveToPoint(P:Point)
- **Status:** P (sev 3 detail)   **Uses:** 3,987
- **Original:** creature case 19 → `sub_786E84` (`.re/orig/dump/dec_all/786E84.c:46-243`). Done (-1) when already in the
  target's search cell (x/16, y/12); fails (-2) when the point is outside the area or the creature is too encumbered
  (byte `+3333` = 2, feedback 15; = 1 only gives feedback 14). When the walk is blocked, retries: counter `+1136`, give up
  after 4; a creature that is **not** a party member re-queues MoveToPoint plus `SmallWait(1d8 ticks)` (action 83,
  `sub_82015B(8,0)+1`) before giving up. TimedMoveToPoint (303) counts int0 down per update and turns into JumpToPoint at 0.
- **EE:** `CGameSprite::MoveToPoint(void)` same structure (`WALK_RETRY`).
- **GemRB:** `Actions.cpp` `MoveToPoint`: `WalkTo`, released when no path / arrived; blocked walking handled by the
  path code. No re-queue with a small wait.
- **Difference:** only how a blocked NPC retries (original: up to 4 retries with a 1-8 tick pause). Neither engine
  hangs the queue on an unreachable point. Re-check: `python tools/parity/dumps.py show orig sub_786E84 --all`.

### A-63 Wait(I:Time), A-83 SmallWait(I:Time)
- **Status:** P   **Uses:** 3,531 / (SmallWait in the ledger if used)
- **Original:** base case 63 → `sub_465DD1`: on first run int0 × 15 (seconds → AI updates), then −1 per update,
  done at ≤ 0. SmallWait `sub_465E95`: int0 updates, no × 15. Both: when a global flag (`dword_96E81C+13634` → byte
  +238) is set, they finish at once and store 15 × int0 in area field +1052 (EE: same, `ENGINE_MODE == 3` = multiplayer
  sync; not reachable in single player, so ignored).
- **GemRB:** `Actions.cpp` `Wait` (int0 × `defaultTicksPerSec`), `SmallWait` (int0 ticks). Same counts.
- Re-check: `python tools/parity/dumps.py show orig sub_465DD1 --all`; `grep -n "void GameScript::Wait(" -A14 gemrb/core/GameScript/Actions.cpp`.

### A-219 WaitRandom(I:MinTime, I:MaxTime)
- **Status:** V   **Severity:** 3   **Uses:** 1,398 (all BCS)
- **Original:** base case 219 (`44B099.c:2159-2182`): lo = min(int0, int1), hi = max(int0, int1), int0 ← lo +
  `sub_82015B(hi − lo + 1, 0)` (`82015B.c`: 0 … n−1), so **lo … hi inclusive**; then becomes a Wait (action 63).
- **GemRB:** `Actions.cpp` `WaitRandom`: width = int1 − int0; if width < 2 the wait is int0; else int0 + RAND(0, width−1),
  so **int0 … int1−1**: the maximum is never rolled, and a 1-wide range (`WaitRandom(1,2)`, 2 uses) is always int0.
- **Difference:** `WaitRandom(3,5)` (424 uses): original 3/4/5 s (mean 4), GemRB 3/4 s (mean 3.5). Every ambient loop runs
  ~10-15 % faster. Re-check: `python tools/parity/actargs.py 219`, `python tools/parity/dumps.py case orig sub_44B099 219`.

### A-84 Face(I:Direction)
- **Status:** P   **Uses:** 3,125 (all BCS)
- **Original:** creature case 36 → `sub_790813`: int0 < 0 → random 0-15; sets the facing, sends a sync message, done
  at once. **GemRB:** `Actions.cpp` `Face`: −1 → random, else clamped; one-tick `SetWait(1)`; BG2 cutscene explore hack
  (fog only). Data uses only 0-15 and −1 (214). Re-check: `python tools/parity/actargs.py 84`.

### A-3 Attack(O:Target)
- **Status:** P (script level; the swing itself is track B)   **Uses:** 2,812 (2,364 BCS, 448 DLG)
- **Original:** creature case 2 → `sub_77EEE0` (`77EEE0.c`): target missing or in another area → fails and raises
  `TargetUnreachable` (0x26) on the attacker; target = self → fail; target dead (state 0x800), or asleep (state 1) while the
  attacker uses the fist slot (10) → done; no weapon → fail; launcher without ammo → `Unusable` trigger, fail. First update:
  feedback 6; a party member gives a battle cry (sound 10) **1 time in 6**, others always. In reach → swing (`sub_78113D`),
  else move closer (`sub_785E47`).
- **GemRB:** `Actions.cpp` `Attack` → `GSUtils.cpp` `AttackCore`: no target / dead / invisible → release, adds
  `TargetUnreachable` only in the invisible/dead case. 
- **Difference:** none a PST script can see (no PST script tests `TargetUnreachable`, ledger events). Combat details for
  track B: unarmed attacks on sleeping targets end at once in the original; battle-cry chance (see `wp_voices.md`).

### A-30 SetGlobal, A-109 IncrementGlobal, A-244 BitSet (GlobalBOr)
- **Status:** P (sev 3 notes)   **Uses:** 2,763 / 1,098 / 132
- **Original:** base cases 30 `sub_464807`, 109 `sub_466198`, 244 inline. Scope = first 6 chars: GLOBAL
  (`dword_96EDC8`), KAPUTZ (`dword_96EDA4`), LOCALS (`dword_96EDB8`), else an area name; lookup `sub_463F03` **never
  creates**; a missing variable is left alone. Fallback: a GLOBAL name containing `_DEAD` or `KILL_` that isn't found is
  looked up in the KAPUTZ table, and the reverse (`463F03.c:134,161`). SetGlobal also compares the name against a
  5-entry `JOIN_*` table (`sub_43A21C`, `aJoinSensates`): the faction hook BALDUR.bcs stands in for (track A8).
- **GemRB:** `GSUtils.cpp` `SetVariable`/`CheckVariable`; PST `NoNewVariables = 1` → no creation either. No
  `_DEAD`/`KILL_` cross-table fallback.
- **Data:** written-but-undeclared variables (16) and read-but-undeclared (13) behave the same in both (no-op / 0):
  e.g. `AR0511_Visited`, `AR0513_Visited` (only read by the same block), UB's `AR0205` bar variables (if the ARE doesn't
  declare them: not checked), `SOLD_DAKKON/MORTE/NORDOM` (read, never written). Only cross-table case:
  `0202IVAN` `SetGlobal("EiVene_Dead","GLOBAL",1)` → the original sets the KAPUTZ variable, GemRB nothing; no script reads
  either, and the engine's own death variable covers it. **For A7:** DLG text with spaces inside variable names:
  `" KNOW_SIGIL"`, `"CW_STATUE_CURSED "`, `"PC_ANNAH_STEALTH "`, `"PILLAR "`, `"JUMBLE "`, `"PORPHIRON "`.
- Re-check: `python tools/parity/dumps.py show orig sub_463F03 --all`; `grep -n NoNewVariables gemrb/unhardcoded/pst/gemrb.ini`.
