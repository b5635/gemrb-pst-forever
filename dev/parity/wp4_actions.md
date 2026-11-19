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
- **Status:** V   **Severity:** 2   **Uses:** shared id with RunAwayFrom
- **Original:** creature case 24 → `sub_78DEDF`. When the action's **int1 (NoAttacks) is 0**, the fleeing creature
  looks for an enemy (`GetEnemyOf`) and may stop to attack it with its current weapon (IESDP: "occasionally, fleeing
  creatures stop to attack another creature"). NoAttacks = 1 turns that off.
- **GemRB:** `Actions.cpp:1598` `RunAwayFrom` → `RunAwayFromCore`: never attacks while fleeing.
- **Difference:** plain RunAwayFrom(…) in the original can counter-attack; GemRB behaves as if NoAttacks were always 1.

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
