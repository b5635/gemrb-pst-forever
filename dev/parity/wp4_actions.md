# WP4: script actions, original vs GemRB

Progress: the overloaded Ex actions done (with findings section 9). Next: the most used actions by `scripting.md` count.
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
- **Status:** V   **Severity:** 3   **Uses:** 1,693
- **Original:** base case 202: looks both variables up **without creating them**; if either doesn't exist, nothing
  happens. Otherwise, if var1 is 0, set var1 = 1 and add int0 to var2.
- **GemRB:** `IncrementGlobalOnce` creates both (CheckVariable returns 0 for a missing one). Matters only for
  LOCALS/area variables that don't exist yet (PST predeclares its GLOBALs).

### A-10 Enemy()
- **Status:** P   Original `sub_7A0255`: EA = 255 in all three copies, removes op 5 (charm) from both effect lists. GemRB
  `Enemy` does the same.
