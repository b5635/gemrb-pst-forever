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

### A-17 Help()
- **Status:** P (sev 3 details)   **Uses:** 1,843
- **Original:** creature case 13 → `sub_79FB29`: every object of type ANYONE (`dword_96E410` is a CAIObjectType, not a
  range) within the creature's range (vfuncs +176 range, +168 terrain table; EE `CGameSprite::Help` → `GetAllInRange`
  with no line-of-sight check) gets a `Help` trigger (3) naming the caller. Done at once.
- **GemRB:** `Actions.cpp` `Help` → `Map::Shout(actor, 0, false)`: everyone within `WithinAudibleRange` (PST: the
  caller's visual range) except the caller gets `trigger_help`, `LastHelp` set.
- **Difference:** the original's list may include the caller itself (no exclusion seen in either version); range
  vfunc not identified (S). No PST script outcome found that depends on it.

### A-7 CreateCreature(S:NewObject, P:Location)
- **Status:** P   **Uses:** 2,385
- **Original:** base case 7 → `sub_4662B7`: no area → fail; point (−1,−1) → the caller's position (`sub_566452`);
  missing CRE → fail; nearest free spot by the creature's size (`sub_58A600`), placed with vfunc +8; its script name
  is entered in the area's name → id table (`sub_593599`). No facing parameter in PST's signature.
- **GemRB:** `CreateCreatureCore(CC_CHECK_IMPASSABLE|CC_CHECK_OVERLAP|CC_SCRIPTNAME)`: −1,−1 → caller (trap launch
  point for triggers), free-spot search, orientation int0 (always 0 here), `LastMarked` set. Same outcome.

### A-60 ChangeAIScript(S:ScriptFile, I:Level)
- **Status:** P   **Uses:** 887 (801 BCS: levels 7 ×206, 6 ×106, 0/1/5 rare; 86 DLG `DEFAULT`)
- **Original:** base case 60 → `sub_465501`: loads the script, creature vfunc +156 = SetScript (EE
  `CGameSprite::SetScript`: replaces the slot, empty name clears it, nothing else; the queue is not touched).
- **GemRB:** `Actions.cpp` `ChangeAIScript` → `Scriptable::SetScript`: replaces the slot (deferred if it is running),
  empty name clears. Same.

### A-164 AddexperienceParty / AddPartyExperience(I:XP)
- **Status:** V   **Severity:** 3   **Uses:** 579 (3 BCS, 725 DLG forms counted by `actargs.py --dlg`)
- **Original:** base case 164 → `sub_5C6278`: n = living party members (state 0x800 not set), share = XP / n, and the
  **remainder goes +1 to the first members**; each gets it through an op-104 effect; then sound `SPTR02`.
- **GemRB:** `Actions.cpp` `AddExperienceParty` → `Game::ShareXP(xp, SX_DIVIDE)`: XP / living members, remainder
  dropped; `AddExperience` directly.
- **Difference:** up to n−1 XP lost per call (`AddPartyExperience(250)` with 3 members: 84/83/83 vs 83/83/83). Op 104
  path not compared (S: if op 104 does more than add XP). Re-check: `python tools/parity/dumps.py show orig sub_5C6278 --all`.

### A-218 PlaySequence(I:Anim), A-200 SetAnimState(O:Object, I:Anim)
- **Status:** V   **Severity:** 2   **Uses:** 1,057 / 802 (271 BCS, 531 DLG)
- **Original:** creature cases 91 / 84 → `sub_78D52B` / `sub_78D6A7`: start the sequence (animation vfunc +180), then
  **return "running" every update until the sequence has played to its end** (`sub_78DBA8`: animation vfunc +132/+128,
  or another sequence replaced it). PlaySequence of a fidget (23-26) while a fidget plays is done at once.
  SetAnimState resolves its object first (missing → done) and waits on that creature's sequence.
- **GemRB:** `GSUtils.cpp` `PlaySequenceCore`: sets the stance; PST has `OneByteAnimationID = 1`, so it **returns
  before the `SetWait(duration)`**: the action never blocks. (The comment "the original didn't actually block" is
  about BG.)
- **Difference:** in PST, the next action after `PlaySequence(ANIM_TALK)` / `SetAnimState(x, ANIM_MIMEDIE)` starts
  only when the animation has finished; in GemRB at once. Cutscene and dialogue staging can overlap (e.g. a
  `SetAnimState(Myself, ANIM_MIMEDIE)` (34 DLG uses) followed by `DestroySelf` / movement).
- **Re-check:** `python tools/parity/dumps.py show orig sub_78D52B --all`; `sed -n 335,350p gemrb/core/GameScript/GSUtils.cpp`;
  `grep -n OneByteAnimationID gemrb/unhardcoded/pst/gemrb.ini`.

### A-215 FaceObject(O:Object)
- **Status:** P   **Uses:** 701. Original creature case 90 → `sub_790955`: object missing → fail; itself → fail;
  else direction to it (22.5° steps) → Face. GemRB `FaceObject`: same plus a one-tick wait.

### A-208 ReturnToSavedPlace()
- **Status:** V   **Severity:** 3   **Uses:** 593
- **Original:** creature case 89 → `sub_77ED40`: saved x or y < 1 → done; walk to it; when the walk ends, **face the
  saved orientation** (`+6900`, `sub_7472C5`).
- **GemRB:** `Actions.cpp` `ReturnToSavedLocation`: walks there, never restores `IE_SAVEDFACE` (only
  `MoveToSavedLocation`-family `Actions.cpp:622` does).
- **Difference:** NPCs back at their post face wherever they walked from. Re-check: `python tools/parity/dumps.py show orig sub_77ED40 --all`.

### A-140 GiveItemCreate(S:ResRef, O:Object, I:Usage1, I:Usage2, I:Usage3)
- **Status:** P (script level) / S (inventory-full detail)   **Uses:** 483 (2 BCS, 481 DLG, all to creatures)
- **Original:** base case 140 → `sub_46C019`: no object → fail; no ITM → fail; item made with charges int0/int1/int2
  (`sub_50B507`); a creature target gets it through message vtable `8DC56C` (party member: feedback 3 first); any
  other object type: the item is deleted.
- **EE:** `CMessageAddItem::Run`: stack onto a matching stack with room, else the first free inventory slot; when full,
  the new item goes in and a **droppable** item already there is swapped out to the ground (+ "inventory full" feedback
  and sound). The original's Run (slot past 5 of `8DC56C`) not read.
- **GemRB:** `Actions.cpp` `CreateItem`: `AddSlotItem(SLOT_ONLYINVENTORY)`; when full, the **new** item drops at the
  target's feet (+ voice/message). Containers accept it (no PST data does that).
- **Difference:** only which item ends on the ground when the inventory is full (EE; confirm in the original).

### A-117 TakePartyGold(I:Amount)
- **Status:** P   **Uses:** 363. Original base case 117 → `sub_46C3E3(0)`: amount = min(party gold, int0); a creature
  caller (type 49) gets the amount added to its gold (+1284, +3266); party gold −amount (message `8DC588`). GemRB
  `TakePartyGold`: same, but only a caller **not in the party** gets the gold (PST party members hold no gold of
  their own: no visible difference).

### A-61 StartTimer(I:ID, I:Time)
- **Status:** P   **Uses:** 345. Original base case 61 → `sub_465B25`: (re)sets timer byte ID to int1 in the creature's
  list (+926). EE `CGameAIBase::CheckTimers(1)` runs once every 15 AI updates (`ProcessAI`, phase by object id) and
  raises `TimerExpired(ID)` at ≤ 0: **seconds**. GemRB `Scriptable::StartTimer`: GameTime + int1 × ticks/s. Same.

### A-220 StartRandomTimer(I:ID, I:Min, I:Max)
- **Status:** V   **Severity:** 2   **Uses:** 268 (all BCS)
- **Original:** base case 220 (`44B099.c`, case 220): lo = min(int1, int2), hi = max(int1, int2), int1 ← lo +
  `sub_82015B(hi − lo + 1)` = **lo … hi**, then StartTimer.
- **GemRB:** `Actions.cpp` `StartRandomTimer`: `core->Roll(1, int2 − int1, int2 − 1)` = **int2 … 2·int2 − int1 − 1**.
- **Difference:** the timer never fires inside the given range: `StartRandomTimer(1,5,10)` (64 uses) → original 5-10 s,
  GemRB 10-14 s; `(1,15,30)` (54) → 15-30 vs 30-44 s; `(1,300,600)` (6) → 5-10 min vs 10-15 min. Ambient barks, wander
  and respawn loops run 1.5-2× slower. Re-check: `python tools/parity/actargs.py 220`;
  `grep -n "void GameScript::StartRandomTimer" -A4 gemrb/core/GameScript/Actions.cpp`.

### A-273 SetInternal, A-274 IncInternal(O:Object, I:Index, I:Value)
- **Status:** P   **Uses:** 470 / 386. Original base cases 273/274: object missing → nothing; index < 10, stored as a
  **16-bit** signed word (`sub_76840D`/`sub_76843A`, creature words +1932…). GemRB: index ≤ 15, 32-bit stat. Data uses
  indexes 0-9 and small values.

### A-204 FadeToBlack(), A-205 FadeFromBlack()
- **Status:** P (both instant)   **Uses:** 369 / 364. Original base cases 204/205: set the current area's fade flags
  (+1036 to-black, +1040 from-black, int0 bit at +1044) and finish at once. GemRB `FadeToColor`/`FadeFromColor` with
  point.x = 0 → last/default duration, released at once. Fade speed not compared (presentation).
- **Side rule found here (for A6):** while any of the area flags +1036 / +1040 / +1048 is 1, the original **holds
  `Dialogue` (action 8, base case 8 and creature case 5 return 0 = retry)** and disables the portrait buttons
  (`sub_43B89C`). GemRB starts a dialogue during a fade. Re-check: `python tools/parity/dumps.py lines orig sub_44B099 829 862`.

### A-306 GiveExperience(O:Object, I:Amount)
- **Status:** P   **Uses:** 246. Original base case 306: creature targets only; op-104 effect with int0 (no split),
  feedback 2, sound `SPTR02`. GemRB `AddXPObject`: `AddExperience(int0)`, message, sound. Same.

### A-111 DestroySelf()
- **Status:** P / S   **Uses:** 245. Original creature case 59: sets the "remove me" flag +9962, done. GemRB `DestroySelf`
  + a PST hack: if the creature runs the current cutscene, cutscene mode ends (`Actions.cpp` `DestroySelf`, "#532"). The
  original has nothing here; whether it ends cutscene mode when the runner disappears is an A5 question.

### A-248 RunToPoint(P:Point)
- **Status:** P   **Uses:** 274. Original creature case 93 → `sub_786E84` like MoveToPoint (run flag from the action id).
  GemRB `RunToPoint`. See A-23.

### A-312 PlaySoundNotRanged(S:Sound)
- **Status:** P   **Uses:** 285. Original base case 312: loads the sound and plays it unpositioned. GemRB same (presentation).

### A-217 PermanentStatChange(O:Object, I:Stat, I:Delta, I:Value)
- **Status:** V (MaxHP) / P (others) / S (LEVEL)   **Severity:** 3   **Uses:** 230 (all DLG: PICKPOCKET 49, TRAPS/STEALTH/
  LOCKPICKING 22 each, STR 21, CON 20, DEX 17, WIS 15, MAXHITPOINTS 11, INT 10, CHR/AC/fire resist 4, DAMAGEBONUS 3,
  LUCK 1, LEVEL 1)
- **Original:** base case 217 → `sub_459DD1` (1,813 lines, one case per stat): delta.ids 1 LOWER (value negated),
  2 RAISE, 3 SET; a value with bits 0xF000 is a dice code (`sub_4352A8`, unused by data). Each stat is clamped: max HP
  1-65535, AC −10…10 (case 2), thief skills 0-255 (cases 26-29), STR 1-25 (case 36)… **Max HP (case 1) also moves current
  HP by the same amount** (clamped ≥ 1) and prints a feedback line. LEVEL (case 34) recomputes XP for the class
  (the Nameless One's path through `+3342` and `sub_459D1F`; not followed).
- **GemRB:** `Actions.cpp` `PermanentStatChange`: Lower/Raise/Set on the base stat, clamped by GemRB's stat limits;
  feedback only on Raise for party members; current HP untouched.
- **Difference:** `PermanentStatChange(Protagonist, MAXHITPOINTS, Lower, 5)` at 50/80 HP → original 45/75, GemRB 50/75;
  Raise 3 at 50/80 → original 53/83, GemRB 50/83. LEVEL (1 use) not compared.
- Re-check: `python tools/parity/dumps.py lines orig sub_459DD1 460 503`; `python tools/parity/actargs.py 217 --dlg`.

### A-116 TakePartyItem(S:Item)
- **Status:** V   **Severity:** 1   **Uses:** 137 (133 DLG)
- **Original:** base case 116 → `sub_46B7E4` (`46B7E4.c:70-217`): party members in portrait order 0…n; the first slot
  holding the item: **if it is a stack of more than 1, one unit is removed** (usage 0 − 1) and the action ends
  (`:119-139`; the caller gets nothing); a single item is removed (message `8DC3B0`) and a copy goes to the caller.
  Fails (−2) when nobody has it. Action 193 (range variant) also needs the member within 10 search cells.
- **GemRB:** `Actions.cpp` `TakePartyItem` → `MoveItemCore(pc, Sender, res, …)` with count 0 →
  `Inventory::RemoveItem(slot, 0)` (`Inventory.cpp`, `!count` → `KillSlot`): **the whole stack** moves to the caller.
  Party is searched from the last member.
- **Difference / Breaks:** stackable quest items (ITM stack > 1): `Tail` (stack 99, 21 uses: DBARKING, DKNFGHL,
  DPHINEAS, DRATBONE each buy one cranium-rat tail), `PsCharm`, `Embalm`, `Needle` (stack 99). With 4 tails, the first
  buyer takes all 4 in GemRB and the other three trades can't be done (`PartyHasItem("Tail")` false).
- **Re-check:** `python tools/parity/dumps.py lines orig sub_46B7E4 113 141`; `sed -n 543,546p gemrb/core/Inventory.cpp`;
  `python tools/parity/actargs.py 116 --dlg`.

### A-222 DestroyPartyItem(S:Item, I:All)
- **Status:** P   **Uses:** 147. Original base case 222 → `sub_45D71A`: party in portrait order; All = 0 → one unit of a
  stack (or one item), then stop; All = 1 → every matching slot. GemRB `DestroyPartyItem`: count 1 / 0 through
  `Inventory::DestroyItem` (units of a stack). Same, except search order (last member first; only matters when two
  members carry it).

### A-118 GivePartyGold(I:Amount)
- **Status:** P   **Uses:** 180. Original base case 118 → `sub_46C5C3`: a creature caller gives min(amount, its own gold)
  and loses it; party gold + that. GemRB `GivePartyGold`: same.

### A-131 Kill(O:Object)
- **Status:** P   **Uses:** 155. Original base case 131: target not dead → op 13 (death) with p2 = 4 ("normal"), source =
  caller. GemRB `Kill`: op 13 with p2 = 0, no source. Death type 0 vs 4 only picks the damage type (crushing vs none);
  the killer is only used for XP when a party member calls Kill (none found).

### A-153 ChangeEnemyAlly, A-157 ChangeSpecifics, A-269 SetTeam
- **Status:** P   **Uses:** 157 / 156 / 135. Original base cases 153/157: object missing → nothing; the new value is
  written to all three object-type copies (live, base `+9792`, and the third) through vfunc +192, then a sync
  message. SetTeam (269) resolves with `sub_45E93F`, sets the team on any object (vfunc +80) and, for creatures,
  both base copies. GemRB: `SetBase(IE_EA / IE_SPECIFIC / IE_TEAM)` on actors. Only difference: a charmed creature's
  live EA in the original is overwritten too (GemRB keeps the charm's EA until it ends); not seen in PST data.

### A-281 TeleportParty(S:Area, P:Point, I:Face)
- **Status:** S   **Severity:** 2   **Uses:** 110
- **Original:** base case 281 → `sub_46E134`: copies the action as **LeaveAreaLUA (110)** and hands it to `sub_5B6821`:
  every party member's action queue is cleared (vfunc +100), flag `+956` = 1, `+9656` = 75, and the first member
  gets the area change through the message `8DB938` (`sub_5B6BDF`). The move happens as a queued action.
- **GemRB:** `Actions.cpp` `TeleportParty` → `Game::MovePCs` + `MoveFamiliars`, immediately; party queues kept.
- **Open:** whether keeping the party's queued actions across the jump changes anything (e.g. a member still
  walking); what `+9656 = 75` is. Re-check: `python tools/parity/dumps.py show orig sub_5B6821 --all`.

### A-108 EscapeArea()
- **Status:** S   **Severity:** 3   **Uses:** 208
- **Original:** creature case 57 → `sub_7AD135`: no travel-region search; a creature already **outside the viewport
  rectangle** is removed at once; otherwise it walks to the nearest viewport edge (`sub_472853` free-spot probes along
  the edges) and is removed when it leaves the rectangle. A party member also runs `sub_7A12F0`.
- **GemRB:** `EscapeArea` → `FindEscapePosition`: nearest **travel region** first (`AdjustNearestTravel`), the
  viewport edge only when none is found.
- **Difference:** where leaving NPCs walk (exit vs. off-screen); outcome (removal) the same. Not fully followed.

### A-104 MoraleDec(O:Target, I:Morale) (and the Karach hook GemRB adds to MoraleInc/MoraleSet)
- **Status:** V   **Severity:** 2   **Uses:** 189 (all DLG; Annah 75, Dakkon 48, Morte 11, Grace 10…)
- **Original:** creature case 54 (`76A7EA.c` case 54): an op-23 effect (morale, p1 = −int0, timing 1) sent to the target.
  Nothing else. The Karach blade swap lives only in **level-up**: `sub_5E6187` (level-up, called from `sub_5EF932`),
  `5E6187.c:643-658`: when the creature's script name maps to 7 (Dak'kon) and the level rose, `sub_5E985F` checks the
  crossing of level 4 / 7 / 10 and picks the variant by **current** morale (+1831: ≤ 5 B, 6-14 N, ≥ 15 G;
  `sub_5E99EF`, resrefs `BKarach`…`NKarach3`).
- **GemRB:** `Actions.cpp` `MoraleDec` (also `MoraleInc` `:3061`, `MoraleSet` `:3043`): `SetBase(IE_MORALE)` then
  `Game.CheckKarachUpgrade(pc, ±n, 0)` (`GUIScripts/pst/Game.py`). With levelDiff 0 it treats any level ≥ 4 as a
  crossing (suffix always set), and when the morale change crosses no threshold it falls to `prefix = "b"`, then
  `CreateItem(pc, "bkarach…", slot 10)`.
- **Difference / Breaks:** any MoraleDec/MoraleInc/MoraleSet on Dak'kon at level ≥ 4 that doesn't cross 6 or 15 gives
  him the **bad** blade (`bKarach`, `bKarach2`, `bKarach3`), e.g. `MoraleDec("Dakkon",1)` at morale 12 → bKarach in
  GemRB, unchanged in the original. In the original morale only matters at his next level-up.
- **Re-check:** `python tools/parity/dumps.py lines orig sub_5E6187 643 658`; `python tools/parity/dumps.py callers orig
  sub_5E985F`; `sed -n 19,60p gemrb/GUIScripts/pst/Game.py`; `grep -n CheckKarachUpgrade gemrb/core/GameScript/Actions.cpp`.

### A-103 MoraleInc, A-102 MoraleSet
- **Status:** V (A13)   **Uses:** 73 / 8. Original creature cases 53 / 52: op 23 with mode 0 (add) / 1 (set),
  timing 1, nothing else. GemRB: same stat change plus the Karach swap (A-104).

### A-150 StartStore(S:Store, O:Target)
- **Status:** P   **Uses:** 192. Original creature case 76 → `sub_7B2623`: opens the store GUI for the target
  object (customer), owner = caller; done at once. GemRB `StartStore`: opens for the caller, released at once.
  Store rules (prices, rent) are track C.

### A-286 SetCorpseEnabled(S:Name, I:State)
- **Status:** P   **Uses:** 238. Original base case 286 → `sub_46E3F4` → `sub_46E4B6` over two area object lists: an area
  animation (type 48) with that name (case-insensitive) gets bit 1 of +154 set/cleared; a creature (type 17) with that
  script name gets a flag in +1990. GemRB binds the name to `AmbientActivate` (animations, then ambients). All 238
  BCS uses name an area animation (checked against every ARE's animation list), so the creature branch is unused.

### A-279 EnablePortalTravel, A-278 ActivatePortalCursor(O:Object, I:Value)
- **Status:** P (sev 3 sound)   **Uses:** 127 / 122. Original base cases 279/278: the object must be a region (type 65)
  **of kind 2 (travel)**; sets/clears bit 2 / bit 1 of its flag word (`sub_4F6255` / `sub_4F6210`); enabling travel also
  plays `AM_VORTX`. GemRB: same bits (`PORTAL_TRAVEL` 2, `PORTAL_CURSOR` 1) on proximity or travel regions; **no
  `AM_VORTX` sound** (no reference to it anywhere in GemRB).

### A-120 StartCutScene(S:CutScene), A-121 StartCutSceneMode(), A-122 EndCutSceneMode()
- **Status:** P   **Uses:** 433 / 265 / 133. Original base case 120 → `sub_46A64E`: loads the BCS; per block, takes the
  first response, resolves the object of its first action, and sends that creature the response's actions (message
  `8DC550`); conditions are not evaluated. int0 ≠ 0 (StartCutSceneEx) sets a flag in the message and calls the actor's
  vfunc +152 (A8 in findings, open). Cases 121/122 send message `8DC2E8` with 1/0 (cutscene mode on/off). GemRB
  `StartCutScene` → `EvaluateAllBlocks(false)` follows the same rule; `StartCutSceneMode`/`EndCutSceneMode` toggle the
  mode. Who runs scripts in cutscene mode is A5.

## Round 9: the rest of A1 (by use count)

Original vtables are read straight from the exe now: `python tools/parity/exevt.py slots <VA> [N]` /
`exevt.py refs <addr>` (no IDA). Creature (sprite) vtable starts at `8F07BC` (ExecuteAction `sub_76A7EA` at +140,
trigger handler +148); the base AI-object vtable at `8DC1B0` (`sub_44B099` at +140). Message vtables: slot 6 is Run.

### A-210 FloatMessage, A-211 FloatMessageFixed, A-212 FloatMessageRnd, A-214 KillFloatMessage
- **Status:** V (sev 3)   **Uses:** 1,643 / 3 / 43 / 186
- **Original:** base cases 210-213 call the caller's vfunc +104, 214 vfunc +108. Creature: `sub_7B32EF`; other objects
  `sub_46E6D8`; both kill: `sub_46E9F5`. Nothing happens unless the **caller is in the area on screen**. 212/213 pick a
  random strref from the `.SRC` named by the string (`sub_58EC85`/`sub_58EB50`). 210/212 float over the object
  (missing → over the caller, creature version); 211/213 at the action point. Text only: the strref is fetched with its
  sound into a local (`sub_826200`) but no play call follows, and nothing goes to the message log. Done at once.
  KillFloatMessage removes the floating texts whose owner is the **caller** (`this[21]`); its object is not read.
- **EE:** `CGameAIBase::FloatMessage`/`KillFloatMessage` same (owner check against `this` id).
- **GemRB:** `DisplayStringHead` (DS_HEAD|DS_SPEECH: plays the strref's sound as speech), `FloatMessageRnd`
  (DS_CONSOLE|DS_HEAD: also logs to the message window), `FloatMessageFixed`, `KillFloatMessage` (clears the **object's**
  overhead text, missing → caller). Runs in any area.
- **Difference:** GemRB plays voiced strrefs and logs FloatMessageRnd lines; floats from off-screen areas; KillFloatMessage
  on another object (7 of 183 BCS uses: `"Fhjull"`, two object ids) clears that object's text, the original the caller's.
  Re-check: `python tools/parity/exevt.py slots 8F07BC 30`; `python tools/parity/dumps.py show orig sub_7B32EF --all`;
  `grep -n "void GameScript::KillFloatMessage" -A8 gemrb/core/GameScript/Actions.cpp`.

### A-270 ForceAttack(O:Attacker, O:Target) (finding A15)
- **Status:** V   **Severity:** 2   **Uses:** 531
- **Original:** base case 270: attacker = first object, creatures only; sends it message `8DC378` (Run `sub_5302D9` →
  object vfunc +100 = **clear its action queue**), then `8DB938` (add action) with a new `Attack` (3) on the second
  object. Done at once.
- **GemRB:** `Actions.cpp` `ForceAttack`: `AddAction(NIDSpecial3)` (doors/containers: `BashDoor`): **appended** to the
  attacker's queue, nothing cleared.
- **Difference:** a creature with queued actions (walking, waiting, a dialogue staging) finishes them first in GemRB; in
  the original it drops them and attacks now. Re-check: `python tools/parity/dumps.py case orig sub_44B099 270`;
  `python tools/parity/exevt.py slots 8DC378 7`; `python tools/parity/dumps.py show orig sub_5302D9 --all`.

### A-266 FloatRebus(O:Target)
- **Status:** P (sev 3)   **Uses:** 490 (all DLG). Original creature case 104 → `sub_7B32CC`: visual-effect helper
  `sub_748A99(this, 4, 0, 45)` on the **caller**, done. GemRB `FloatRebus`: DABUS1-5 VVC over the target (DLG uses are
  `FloatRebus(Myself)`-style on the speaking Dabus). Look only.

### A-251 RunningAttack(O:Target)
- **Status:** P   **Uses:** 284. Original creature case 95: `sub_77EEE0` (Attack, A-3) with the run flag; a party member
  whose target is missing re-resolves it once. GemRB `RunningAttack` → `AttackCore(AC_RUNNING)`.

### A-31 Spell(O:Target, I:Spell)
- **Status:** P (script level; casting rules are track B)   **Uses:** 308 (all BCS, wizard/priest numbers)
- **Original:** creature case 25 → `sub_787F90`: no target → fail; a creature target that is dead fails unless the spell
  is `SPPR502` (`sub_461378`); not facing → turn first; out of range → walk (`sub_785E47`). Then the spell must be
  **memorized and ready** in the level list for its type (wizard 1-9, priest 1-7, innate 1): the first ready copy is
  depleted (bit 1 cleared); none → fail (−2). `SPIN101`/`SPIN103` skip the memory check. Spell failure roll, fizzle
  `SE10FIZZ`.
- **GemRB:** `Spell` → `SpellCore(SC_DEPLETE…)` → `HandleCastingStance`: not memorized → stop; deplete one.
  Same rule; the SPIN101/103 exception is never hit (no `Spell()` of an innate in the data).

### A-267 StartSong(I:Song, P:Where, I:How)
- **Status:** P   **Uses:** 180 (all How = 0, point [0.0]). Original base case 267 → `sub_850957`: stores song, point and
  How in the mixer (only when music is on); the mixer switches later. GemRB `StartSong`: How = 1 forces, else
  scheduled. Same for the data.

### A-49 MoveViewPoint(P:Target, I:Speed), A-50 MoveViewObject(O:Target, I:Speed)
- **Status:** P   **Uses:** 140 / 53. Original base case 49 → `sub_464AC4` → `sub_464914`: centers the viewport on the point
  through a scroll message with the speed byte; **done at once** (does not wait for the scroll). GemRB `MoveViewPoint`:
  `SetMoveViewPort(point, speed×2)`, flag 0 (instant), cancels actor-centering. Scroll speed scale not compared
  (presentation).

### A-303 TimedMoveToPoint(P:Point, I:Time)
- **Status:** P   **Uses:** 128. Original creature case 107 → `sub_786E84` (A-23): int0 counted down per update, jump at
  0. GemRB `TimedMoveToPoint`: walk, int0 − 1 per tick, jump at ≤ 0; a walk that stops early ends the action without
  the jump (original: retry logic of A-23). Same in practice.

### A-8 Dialogue(O:Object)
- **Status:** S (A6)   **Severity:** 2   **Uses:** 138
- **Original:** creature case 5: holds (returns 0, retry) while the area fades (A-204); done when the caller is already in
  a dialogue (`sub_498F4F`); a creature caller clears flag +4164 of the game; target resolved through the area's
  object list (`sub_5A4864`); missing → fail; else `sub_7A2868` (walk up and talk).
- **GemRB:** `Dialogue` (AF_BLOCKING|AF_DIALOG) → `BeginDialog`. No fade hold.
- **Open (A6):** the walk/range rules inside `sub_7A2868`.

### A-259 Damage(O:Target, I:Delta, I:Modifier) (finding A14)
- **Status:** V   **Severity:** 1   **Uses:** 78 (4 BCS, 74 DLG)
- **Original:** base case 259 (`44B099.c`, case 259): amount = int1; **only when int1 has bits 0xF000** is it a dice code
  (`sub_4352A8`: (int1>>12) dice of size (int1>>4)&0xFF, + int1&0xF). Delta int0: 1 LOWER → negated, 3 SET → absolute,
  else added. A creature's **current HP word +1264 is changed directly** (`sub_461F80`): clamped to **1 … 65535**; a door
  (type 33) gets the same on its HP. No damage effect, no resistances, no death, no hit reaction. Other objects → fail.
- **GemRB:** `Actions.cpp` `Damage`: **always** decodes int1 as a dice code (`(int1>>12)&15` dice, `(int1>>4)&255` size,
  `int1&15` add), rolled through `LuckyRoll` (luck of the caller minus the target's, minimum 1) when the caller is
  another actor; then `Actor::Damage(dmg, type 0, …)`: resistances, can reach 0 HP and **kill**.
- **Difference:** 1) every plain amount ≥ 16 is misread: `Damage(Protagonist,Lower,25)` (14 DLG uses) → 9 damage (0x19 →
  size 1, +9), `20` (3) → 4, `50` (1 BCS) → 2. Only 1-15 come out right. 2) The original never takes a creature below
  1 HP; GemRB can kill the Nameless One (or an NPC) from dialogue. 3) Luck changes the amount in GemRB.
- **Data:** 18 distinct DLG forms, amounts 1, 3, 4, 5, 10, 15, 20, 25 (`actargs.py 259 --dlg`); BCS SET 1 / 5 / 50.
- **Breaks:** dialogue self-harm options (Lower 25 ×14) do a third of the damage; a low-HP Nameless One can die
  mid-dialogue in GemRB (he never can in the original).
- **Re-check:** `python tools/parity/dumps.py case orig sub_44B099 259`; `python tools/parity/dumps.py show orig sub_461F80 --all`;
  `python tools/parity/dumps.py show orig sub_4352A8 --all`; `grep -n "void GameScript::Damage" -A40 gemrb/core/GameScript/Actions.cpp`.

### A-143 OpenDoor(O:Object), A-144 CloseDoor(O:Object)
- **Status:** P / S (locked doors opened by non-creatures)   **Uses:** 105 / 43
- **Original:** base cases 143/144 → `sub_46D882` / `sub_46DA20`: object must be a door (type 33); already open (closed)
  → done; else toggle `sub_4A17F7` at once, no walking. The toggle on a **locked** door (flag +1278 bit 2) only opens
  when the caller is a creature and the key at +1394 is in its reach (`sub_763140`), else prints the locked text 19309
  and leaves it.
- **GemRB:** `OpenDoor`/`CloseDoor`: actor callers need `TryUnlock` (key); **non-actor callers (area/trigger scripts) open
  locked doors**. Instant in both.
- **Open:** whether any area script opens a locked door (not counted).

### A-166 SetNumTimesTalkedTo(I:Num)
- **Status:** P   **Uses:** 101. Original creature case 78: message `8F0AE4` (Run `sub_53E0A3`) writes int0 to the caller's
  talk counter +6902. GemRB `SetNumTimesTalkedTo`: `TalkCount = int0` on the caller. Same.

### A-181 ReallyForceSpell(O:Target, I:Spell)
- **Status:** S (casting path, track B)   **Uses:** 92. Original base case 181 → `sub_46692D` (687 lines; no target → fail;
  int1 ≠ 0 moves the spell number to int0 first). GemRB `SpellCore(SC_NOINTERRUPT|SC_SETLEVEL|SC_INSTANT)`. The cast itself
  (level, instant, projectile cases 1-5) not compared.

### A-246 ForceAIScript(S:Script, O:Target, I:Level)
- **Status:** P   **Uses:** 89. Original base case 246 → `sub_465737`: target = caller → ChangeAIScript (A-60); missing → fail;
  else the target's vfunc +156 (SetScript) with level int0; queue untouched. GemRB `ForceAIScript`: actors only,
  `SetScript(level)`, queue untouched. Same for creature targets (all data).

### A-62 SendTrigger(O:Target, I:TriggerNum)
- **Status:** P   **Uses:** 86. Original base case 62 → `sub_465BEB`: object missing → fail; sends trigger 0x24 (`Trigger`)
  with int0 to it (any object, dead creatures too). GemRB `SendTrigger`: `trigger_trigger` with int0, `GA_NO_DEAD`
  (a dead creature gets nothing: no data case found).

### A-15 GiveItem(S:Item, O:Target)
- **Status:** P   **Uses:** 78. Original creature case 12 → `sub_7A8820`: first slot of the caller with the item
  (`sub_763140`), missing → fail; the **whole slot** is removed; a creature target gets it (party target: feedback 3),
  any other target: the item is lost. GemRB `GiveItem` → `MoveItemCore(count 0)`: whole slot. Same.

### A-48 JumpToPoint(P:Target)
- **Status:** P   **Uses:** 78. Original creature case 33 → `sub_78FAB3` → `sub_78FAE7(x, y, 1)`. GemRB `JumpToPoint`:
  `SetPosition(point, true)` (free spot) + familiars follow the protagonist. Instant both.

### A-115 SetGlobalTimer(S:Name, S:Area, I:Time)
- **Status:** P   **Uses:** 78. Original base case 115 → `sub_46A41E`: existing variable only (`sub_463F03`, no creation);
  value = **15 × int0 + game time** (`+3748`), synced by message `8DC518`. GemRB: `int0 × defaultTicksPerSec (15) +
  GameTime`, no creation (`NoNewVariables`). Same units.

### A-291 SinisterPoof(S:Bam, P:Location, I:Iterations), A-292 StickySinisterPoof(S:Bam, O:Object, I:Iterations)
- **Status:** P (look only)   **Uses:** 107 / 72. Original base cases 291/292 → `sub_46EAA3`: a VEF/BAM effect at the
  point (291) or attached to the object (292, missing → fail); negative iterations = loop |n| times with a flag; done at
  once. GemRB `CreateVisualEffect` / `CreateVisualEffectObjectSticky`: same, instant.

### A-263 PlaySequenceTimed(I:Anim, I:Seconds) (finding A16)
- **Status:** V   **Severity:** 2   **Uses:** 70 (all BCS: `0208SK12`-`SK19` skeleton workers, others)
- **Original:** creature case 102 → `sub_78D78D`: starts the sequence, remembers the game time (+1140), then each update
  **restarts the sequence whenever it ends** (`sub_78DBA8`) until `(now − start) / 15 ≥ int1`: int1 is in **seconds**,
  and the action blocks for that long.
- **GemRB:** `Actions.cpp` `PlaySequenceTimed`: `SetStance(int0)`, `SetWait(int1)`: int1 **ticks**, and no looping.
- **Difference:** `PlaySequenceTimed(25,4)` (9 uses) → original 4 s of looping animation; GemRB 4 ticks (0.27 s), so
  scripted work loops (the Mortuary skeletons) run 15× faster than intended.
- **Re-check:** `python tools/parity/dumps.py show orig sub_78D78D --all`; `grep -n "void GameScript::PlaySequenceTimed" -A16
  gemrb/core/GameScript/Actions.cpp`; `python tools/parity/actargs.py 263 --where`.

### A-262 ChangeColor(I:Range, I:Color)
- **Status:** V   **Severity:** 3   **Uses:** 75 (BCS; cutscenes `0610CUT6/7`, `1500CS9`, `1500DOUB`)
- **Original:** creature case 101 → `sub_7A94FC`: when int0 has bit 0x4000 (the most used form, 16384-16390), the caller's
  color byte for range `int0 & 7` (0-6) is set to int1 and a recolor is flagged (+2010-2012); otherwise the animation's
  vfunc +168 recolors range `int0 & 7`. Range > 6 → fail.
- **GemRB:** `ChangeColor`: only int0 9-14 (clownrge ids) are handled; **every 0x4000 form returns doing nothing**.
- **Difference:** the cutscene recolors (16384-16390, ~50 uses) never show in GemRB.

### A-224 TransformPartyItem(S:Old, S:New, I:Charge1-3)
- **Status:** V   **Severity:** 3   **Uses:** 48. Original base case 224 → `sub_45DCDB`: party in portrait order, **the first
  member holding the item, its first matching slot only** (action 308, the All variant, does every slot of every member);
  new item with the given charges (message `sub_541F69`). GemRB `TransformPartyItem`: one slot **per member**, last
  member first. Differs only when two members carry the item.

### A-171 CreatePartyGold(I:Amount)
- **Status:** P   **Uses:** 57. Original base case 171 → `sub_46C5C3` (shared with GivePartyGold; the caller's purse is only
  used when the action id is 118): party gold + int0 (message `8DC588`). GemRB `Game::AddGold(int0)`.

### A-216 FullHeal(O:Object)
- **Status:** P   **Uses:** 47. Original base case 216: creature target not dead (state 0x800) → current HP = max HP
  (+1264+1944 → +28), nothing else. GemRB `FullHeal` → `Heal(0)`: HP = modified max HP; no dead check (no data heals a
  corpse).

### A-126 Activate(O:Object)
- **Status:** P   **Uses:** 61. Original base case 126: creature **not in the party** → SetActive message (1,1); region →
  clear flag 0x100 (deactivated); container → clear 0x80; area animation → set bit 1. GemRB `Activate`: actor → `Unhide`
  (party members too: they are never deactivated, see A-125), container `CONT_DISABLED`, region `TRAP_DEACTIVATED`,
  missing object → area animation (`AmbientActivateCore`). Same.

### A-276 SetDoorLocked(O:Door, I:Locked)
- **Status:** P   **Uses:** 72. Original base case 276: door only; int0 ≠ 0 → lock (vfunc +188), 0 → clear locked bit 2.
  GemRB `Door::SetDoorLocked(int0 ≠ 0)`, `"FALSE"` (−1) read as 0 (two DLG states). Same.

### A-85 RandomWalk(), A-253 RunToObject(O:Target)
- **Status:** P   **Uses:** 69 / 48. Original creature cases 37 (random walk, party-member path flag first) / 96 (move to object
  `sub_785E47`, run). GemRB `RandomWalk` (blocking), `RunToObject` → `MoveToObjectCore(IF_RUNNING)`. Walk details not
  compared.

### A-287 DebugOutput(S:Message), A-26 PlaySound(S:Sound), A-167 StartMovie(S:Movie)
- **Status:** P   **Uses:** 58 / 56 / 50. DebugOutput: original base case 287 does nothing (GemRB logs). PlaySound
  (`sub_463C80`): the sound at the caller's position, channel 5, done at once (GemRB: spatial at the caller). StartMovie
  (`sub_46D56B`): fails when the movie resource is missing, else plays it; done. GemRB `PlayMovie`, released.

### A-21 LeaveParty() (finding A17)
- **Status:** V   **Severity:** 2   **Uses:** 36 (28 DLG, 3 BCS cutscenes `1001CUT1/2`, `STLMRT3`)
- **Original:** creature case 17 → `sub_7A12F0` (440 lines): a leaver at 0 … −9 HP (not flagged dead) first drops its
  inventory (`sub_7A68DD`) and is placed on a free spot next to the protagonist; removed from the party
  (`sub_5C3169`); EA = 0x80 (NEUTRAL) in all three copies; then **script slots AREA (1), SPECIFICS (2), CLASS (4), RACE (5)
  and GENERAL (6) are set to an empty script** (vfunc +156 with the CString globals `dword_971690`-`9716A0`, which nothing
  writes: `grep -n 9716A0 .re/orig/Torment.exe.asm`), OVERRIDE and DEFAULT kept; every remaining party member gets the
  trigger `Leaves` (5) naming it.
- **EE:** `CGameSprite::LeaveParty` resets the same slots, but to the locale default / `WTASIGHT` (BG's DPLAYER rule).
- **GemRB:** `Game::LeaveParty`: EA NEUTRAL, `trigger_leaves` on the game; the script reset only runs with `HasDPLAYER`,
  which PST has **off**: all seven script slots stay.
- **Difference:** a companion who leaves keeps running its party-time area/specifics/class/race/general scripts in
  GemRB (follow, banter, combat AI); in the original only override and default remain. Which companion CREs fill those
  slots was not checked.
- **Re-check:** `python tools/parity/dumps.py lines orig sub_7A12F0 209 305`; `grep -n "int Game::LeaveParty" -A45
  gemrb/core/Game.cpp`; `grep -n HasDPLAYER gemrb/unhardcoded/pst/gemrb.ini`.

### A-247 ExploreMapChunk(P:Center, I:Radius, I:Mode)
- **Status:** V   **Severity:** 3   **Uses:** 33 (BCS: Fortress of Regrets `1201C*`, `0405CS10`/`CUT5/6`)
- **Original:** base case 247 → `sub_5987F2(x, y, int1, int2)` on the current area's explored map (32 px cells): radius
  int1 in **pixels**; **mode int2 = 1 clears the explored bit** (un-explores), 0 sets it.
- **GemRB:** `ExploreMapChunk(SearchmapPoint(point), int1, 0)`: radius in **search-map cells** (16 px each), mode ignored.
- **Difference:** `(…,600,1)` (8 uses in `1201CI*`) hides map in the original, reveals ~9,600 px around the point in
  GemRB; `(…,600,0)` reveals ~600 px vs most of the area.

### A-277 IncrementExtraProficiency(O:Target, I:Modifier), A-265 IncrementProficiency(O:Target, I:Slot, I:Modifier)
- **Status:** P (sev 3)   **Uses:** 43 / 41 (all DLG)
- **Original:** base case 277: creature target; free proficiency points (`sub_7B2CBE`/`sub_7B2CD6`) + int0, clamped
  0-255; when int0 > 0 a float text (font `TRMTFONT`, strref from `sub_5CF086`) and a sound. Case 265: proficiency slot
  int0 + int1, clamped −128…127, then stats recomputed (`sub_77C225`, `sub_7616CC`).
- **GemRB:** `IncrementExtraProficiency`: `IE_FREESLOTS += int0`, no clamp, no feedback. `IncrementProficiency`:
  `NewBase(IE_PROFICIENCYBASTARDSWORD + slot, int1, add)` for slot ≤ 31.
- **Difference:** the float text / sound is missing in GemRB (presentation). Slot mapping to PST's `wprof.ids` not compared.

### A-82 CreateItem(S:Item, I:Usage1-3)
- **Status:** P   **Uses:** 41. Original base case 82 → `sub_46B02E`: missing ITM → fail; a party caller puts it in the first
  free of 20 inventory slots, other creatures the first of 26, **no stacking**; full → dropped (`sub_46AF90`) and fail;
  a container caller → into the container. GemRB `CreateItem` → `AddSlotItem` (stacks onto a matching stack; full →
  dropped). Same outcome except stacking.

### A-293 SetNamelessClass(I:Class)
- **Status:** P / S   **Uses:** 39. Original base case 293 → `sub_46ED2F`: the protagonist's class in all three object-type
  copies, sync message, record screen refresh. GemRB: `SetBase(IE_CLASS)` + `EnforceUsability` (unusable equipped items
  moved to the backpack or the ground, PST strings `UnusableDroppedBag/Ground`). The original's item check was not seen
  in this path (S: it may live in the stat refresh).

### A-245 BitClear(S:Name, S:Area, I:Bits)
- **Status:** P   **Uses:** 36. Original base case 245: existing variable only (`sub_463E49`), value &= ~int0. GemRB same.

### A-113 ForceSpell(O:Target, I:Spell)
- **Status:** S   **Uses:** 35. Original base case 113 is **the same code as ReallyForceSpell** (181, `sub_46692D`).
  GemRB: ForceSpell `SC_NOINTERRUPT|SC_SETLEVEL` (casting time), ReallyForceSpell adds `SC_INSTANT`. If the shared
  original path is instant, ForceSpell takes longer in GemRB (casting path: track B).

### A-119 DropInventory()
- **Status:** P (S: flags)   **Uses:** 33 (death scripts `0101MF`, `0400RC`…). Original creature case 61 → `sub_7A68DD(0)`:
  **the protagonist never drops**; skips the fist slot; only droppable items (flag 4); a party member keeps critical
  items (flag 1); into the area's ground pile. GemRB `DropItem("",0)`. No data calls it on the protagonist.

### A-159 ChangeAlignment(O:Object, I:Align)
- **Status:** P   **Uses:** 33. Original base case 159: creature target; alignment int0 into all three object-type
  copies, sync message for party members. GemRB `SetBase(IE_ALIGNMENT)`.

### A-309 QuitGame(I:Movie1, I:Movie2, I:Movie3)
- **Status:** S (A8)   **Severity:** 2   **Uses:** 33
- **Original:** base case 309: GLOBAL `Game_Over` = 6, `EndMovie1/2/3` = int0/int1/int2; done. The ending runs from the
  engine's game-over check (EE `CPlanescape::HandleGameOverConditions`, case 6 sets a screen flag).
- **GemRB:** `QuitGame`: clears the caller's actions, stores QuitGame1-3, runs `QuitGame.py` at once (movies
  `["", T1DEATH, T1ABSORB, FINALE, CREDITS]`, QuitGame3 = death strref).
- **Open (A8):** the original's movie table for EndMovie values; GemRB never sets `Game_Over`/`EndMovie*`.

### A-160 ApplySpell(O:Target, I:Spell)
- **Status:** P (S: details)   **Uses:** 26. Original base case 160 → `sub_469917`: creature target (missing → the
  action's spell-id object fallback), spell applied directly without casting; wizard spells scale by the caller's level
  byte. GemRB `ApplySpell` → `core->ApplySpell(…, int1 level)`. Level rule not compared.

### A-169 DestroyItem(S:Item, O:Target, I:All) (finding A18)
- **Status:** V   **Severity:** 1   **Uses:** 20 (all DLG: `DCOPPER`, `DMORTAI` FalseCon; `DDERAN` loandoc; `DMANTUOK`
  Cheese/Pcheese ×11; `DSOHMIEN` Sohmien; `DULTHERA` Legclub; `DTEST`)
- **Original:** base case 169 → `sub_45D71A` (`45D71A.c:43-94`, the action-169 branch): the item is taken from the
  **object** (creature resolved with `sub_45E41B(49)`; every use names `Protagonist`): first matching slot; All = 0 →
  one unit of a stack (or the single item), then stop; All = 1 → every matching slot; party feedback 4 once; removal by
  message `8DC3B0`.
- **GemRB:** `Actions.cpp` `DestroyItem`: `GetInventory(Sender)->DestroyItem(res, 0, 1)`: the **caller's** inventory
  (the dialogue NPC: `DialogHandler.cpp` queues transition actions on `target`), object and All ignored.
- **Difference / Breaks:** every PST use removes nothing in GemRB: the Nameless One keeps the false contract
  (Copper/Mortai), Deran's loan document, Mantuok's cheese (11 lines), Sohmien's item, Ulthera's leg club. Quests can be
  repeated or show stale options (`PartyHasItem` stays true).
- **Re-check:** `python tools/parity/dumps.py lines orig sub_45D71A 39 95`; `grep -n "void GameScript::DestroyItem" -A7
  gemrb/core/GameScript/Actions.cpp`; `grep -n "AddAction(tr->actions" gemrb/core/DialogHandler.cpp`.

### A-207 SavePlace() (finding A19)
- **Status:** V   **Severity:** 2   **Uses:** 15 (BCS `0600AELN`, `0600NEM2`, `0600NEME`, `0602FTDP`…)
- **Original:** creature case 88 → `sub_77ED03`: saved x/y (+6892/+6896) = current position, saved facing (+6900) =
  current facing. ReturnToSavedPlace (A-208) walks back there.
- **GemRB:** the name `saveplace` is bound to `SaveLocation` (`GameScript.cpp`), which writes a **point variable named by
  string0** (empty here, so nothing) and never touches `IE_SAVEDXPOS/YPOS/FACE`. (`SetSavedLocation` with no point
  would do the right thing.)
- **Difference:** SavePlace does nothing; a later `ReturnToSavedPlace()` walks to the creature's old saved spot (or
  stops if none). Aelwyn/Nemelle (`0600*`) and `0602FTDP` return to the wrong place.
- **Re-check:** `python tools/parity/dumps.py show orig sub_77ED03 --all`; `grep -n '"saveplace"' gemrb/core/GameScript/GameScript.cpp`;
  `grep -n "void GameScript::SaveLocation" -A7 gemrb/core/GameScript/Actions.cpp`.

### A-272 ChangeDialog(O:Object, S:Dialog), A-138 SetDialog(S:Dialog)
- **Status:** V (sev 3 timing) / P   **Uses:** 25 / 23
- **Original:** base case 272: a creature target gets **`SetDialog(dialog)` appended to its own action queue** (message
  `8DB938`), so the change happens when it reaches that action; a door / region / container gets its dialog string set at
  once. SetDialog (creature case 68 → `sub_7A5DF8`): sets the caller's dialog through message `sub_7B39B0`.
- **GemRB:** `ChangeDialogue`: sets the actor's dialog at once (actors only); `SetDialogue` same on the caller.
- **Difference:** a busy target (e.g. `ChangeDialog(Myself…)` is most data; `"Morte"` 1 use) switches immediately in GemRB.
  No outcome found that depends on it.

### A-295 CreateCreatureAtFeet(S:NewObject)
- **Status:** V   **Severity:** 3   **Uses:** 24 (all DLG: `BTrelon` 6, `Pet_Lim` 4, `Geherl`, `BoxDmn1`…)
- **Original:** base case 295 → `sub_46F3AB`: the creature is placed at the nearest free spot to the **centre of the
  viewport** (`sub_5D846F` viewport origin + half the view rect, `+1244`), script name registered (`sub_593599`).
- **GemRB:** `CreateCreatureCore(CC_OFFSET…)`: at the caller's feet.
- **Difference:** placement only; during a dialogue the view is normally on the speakers, so both land near them.

### A-132 VerbalConstant(O:Object, I:Constant)
- **Status:** P (A11)   **Uses:** 23. Original base case 132: creature target; message `sub_463410` with the sound-slot
  constant int0 (played by the voice code of A11). GemRB `DisplayStringCoreVC(Verbal(int0), DS_CONSOLE)`. Slot mapping is
  `wp_voices.md`.

### A-221 DestroyPartyGold(I:Amount)
- **Status:** P   **Uses:** 21. Original base case 221 → `sub_46C3E3(1)`: party gold − min(gold, int0); the caller gets
  nothing (flag 1). GemRB `DestroyPartyGold`: same.

### A-298 DisableSpriteDither, A-299 EnableSpriteDither, A-300 DisableFogDither, A-301 EnableFogDither
- **Status:** P (presentation)   **Uses:** 21 each. Original: flags +10300 / +10304 of the game object set to 0/1.
  GemRB: `DitherSprites` and the fog debug flag. Look only.

### A-123 ClearAllActions(), A-133 ClearActions(O:Object)
- **Status:** P   **Uses:** 18 / 13. Original base case 133 → `sub_46B450`: object missing → fail; message `8DC378`
  (queue cleared, vfunc +100). Case 123 → `sub_46B4F1`: every object of the area (type 1 or creature) except the caller
  gets the same clear plus one queued action (`sub_4049AA`, id not identified). GemRB `ClearActions` (`Stop`, modal off)
  and `ClearAllActions` (every living actor but the caller, plus the game script in master areas). The extra queued
  action in the original was not identified (S).

### A-226 GenerateModronMaze()
- **Status:** S (generator not compared)   **Uses:** 15. Original base case 226 → `sub_46FB37`: reads the
  `MazeDifficulty` variable and calls the generator `sub_548AB0(difficulty)`. GemRB: `EF_CREATEMAZE` →
  `GUIScripts/pst/Maze.py`. The maze generator itself is a track C item.
