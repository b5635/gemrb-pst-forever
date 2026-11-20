# A11: voice lines and CRE sound slots, original vs GemRB

Progress (round 12): **A11 done**. Earlier: done for the slot map and for select, action, attack, cast, damage, battle cry, hide, spell disrupted and set
trap. Next: location comments (events 14-19 and 41-45 vs GemRB `comment.2da` / `Actor::GetAreaComment`), the rest of
the cases (1-9, 24-40: morale, happy, banter, insult, compliment, dialogue), and `sub_73DB91` (count of filled slots).

Tools used (2026-11-19, first phase run on the full dumps): `dumps.py show/lines/grep`, the CRE data via `pstres`.

## How the original plays a voice line

- **Original:** `sub_73DEEF(sprite, event, a3, a4, force, -1)` is the one entry point (EE `CGameSprite::PlaySound(uchar,
  int,int,int)`, 009F7710). Events are reached through the play-sound message (vtable `off_8DC96C`, Run = `sub_53A01E`)
  or direct calls. `switch (event)`, 45 cases, `.re/orig/dump/dec_all/73DEEF.c:98`. The CRE's 100 strref slots sit at
  sprite `+1420 + 4*slot`. `sub_73DB91(start, n)` counts the filled slots in a range; `sub_82015B(n, 0)` is a random
  0..n−1. The slot numbers are **hardcoded per case** in the original; EE reads them from `SPEECH.2DA` instead
  (`CRuleTables::CRuleTables`, rows 0..49 = event number, columns OFFSET/NUM) and keeps the PST-only behaviour
  behind `CChitin::ENGINE_MODE == 3` (`engine.lua`: `engine_mode=3` in PST:EE).
- Event numbers (EE names from the `CGameSprite::SOUND_*` byte constants at ECE9CE..ECEA03, same numbers in the
  original: op 13 sends 13 dying / 12 damage in both, `4B5DCF.c:232/255`): 10 battle cry, 11 attack, 12 damage,
  13 dying, 14 hurt, 20 select, 21 select common, 22 select action, 23 select rare, 41-45 locations (slots 74..70).

**What PST's slots actually hold** (`MORTE`, `DAKKON` CRE text, read 2026-11-19): 1 morale, 2 happy, 3 annoyed,
4 serious, 7 tired, 8 bored, **14 "Damage 2"**, **16-17 "Spell-Casting"**, **18 "Damage"**, 19 dying, 20 hurt,
21-25 location comments, 26-31 common select, 32-34 action, 35-38 rare select, 44-52 insults, 61 hostile dialogue,
**70-74 location comments** (Negative Material Plane, Carceri, Curst, Cube, Lower Ward). Ignus, Nordom, Vhailor,
Grace, Annah fill 14/16/17/18 the same way. No companion fills 9-13 (battle cries) or 65-69.

### A11-1 Weapon swings speak the damage and spell-casting lines; casting a spell speaks nothing
- **Status:** V   **Severity:** 2   **Breaks:** every companion attack in combat sounds wrong (the reported bug)
- **Original:** event 11 ("attack") picks `rand(3) + 1 + 14` = slot **15-17**, the Spell-Casting lines
  (`73DEEF.c:411-425`), and it is sent by the spell-casting routine `sub_7A7911:70` when a spell with an ability is
  cast. No caller sends event 11 on a weapon swing (`dumps.py grep orig "sub_73DEEF\("`: 11 only from 7A7911).
  EE same: `PlaySound(SOUND_ATTACK)` only from `CGameSprite::ApplyCastingEffect`, and only in ENGINE_MODE 3.
- **GemRB:** `Actor::PlaySwingSound` (Actor.cpp:5036) plays `Verbal::Attack1..4` = slots **14-17** by stance on
  swings (5051-5060, once per round for party members, 5065), so Dak'kon slashing says "Damage 2" and jabbing says a
  Spell-Casting line. Nothing plays slots 15-17 when a spell is cast.
- **Fix direction:** PST: no CRE line on swings; on spell cast, a random filled slot of 15-17.
- **Re-check:** `python tools/parity/dumps.py lines orig 73DEEF 411 425`, `... lines orig 7A7911 66 72`,
  `grep -n "Verbal::Attack" gemrb/core/Scriptable/Actor.cpp`.

### A11-2 Being hit plays slot 14 or 18 (50/50); GemRB only 18
- **Status:** V   **Severity:** 3
- **Original:** event 12: `sub_82015B(2)`: slot 14 or slot 18 (`73DEEF.c:426-441`). EE dropped that (SPEECH.2DA
  DAMAGE = slot 18, 1): status S for EE.
- **GemRB:** `PlayPainSound` (Actor.cpp:4198) `VerbalConstant(Verbal::Damage, BEING_HIT_COUNT=1)`: slot 18 only.
- **Re-check:** `python tools/parity/dumps.py lines orig 73DEEF 426 441`, `cat gemrb/unhardcoded/shared/vcdetail.2da`.

### A11-3 Selection lines play in order, rare lines from the 10th click, and never at random
- **Status:** V   **Severity:** 3
- **Original:** event 20 (`73DEEF.c:586-666`). Per creature: common counter `+20544`, click counter `+20546`, rare
  counter `+20548`. While clicks ≤ 8: slot `26 + (common % filled)`, then both counters +1 (**in order**, not random).
  From the 10th click: rare slot `35 + rare`, rare +1; after the last rare (filled count of 35-38) rare and clicks go
  back to 0; the common counter is reset every rare click. No random rare chance. A new action resets the click
  counter (`sub_77B706:140`).
- **GemRB:** `Actor::PlaySelectionSound` (Actor.cpp:3808): random common line; rare after `ANNOYED_STREAK` = **4**
  clicks (3799), plus a **5 %** random rare chance outside combat (`RARE_SELECT_CHANCE`, miscrule.2da); rare line
  random of 35-38.
- **Re-check:** `python tools/parity/dumps.py lines orig 73DEEF 586 666`, `sed -n 3808,3862p gemrb/core/Scriptable/Actor.cpp`.

### A11-4 Frequency sliders: level 3 is 40 % (not 50 %), action level 2 is 20 % (not once per selection)
- **Status:** V   **Severity:** 3
- **Original:** select (option `+9090`) and action (`+9086`) share one table on a 0..4 roll: 1 never, 2 roll = 0
  (20 %), 3 roll < 2 (40 %), 4 roll ≠ 0 (80 %), 5 always; `force` plays regardless (`73DEEF.c:589-615`, `689-715`).
  The action line is a random filled slot of 32-34 (`723-744`).
- **GemRB:** pst value = option + 1: select 2 → 20 %, **3 → 50 %**, 4 → 80 % (Actor.cpp:3816-3832); action
  `CommandActor` (3885): **2 → once per selection then 50 %**, 3 → 50 %, 4 → 80 %, and only for the first selected PC.
- **Re-check:** as above, `sed -n 3885,3917p gemrb/core/Scriptable/Actor.cpp`.

### A11-5 Hiding, spell disruption and trap setting speak location comments
- **Status:** V   **Severity:** 2
- **Original:** slots 70-74 are only played by events 41-45, the location comments (`73DEEF.c:1259-1366`: 41 → 74,
  42 → 73, 43 → 72, 44 → 71, 45 → 70); nothing sends hide / disrupted / trap events with those slots. EE skips the
  hide line in PST mode (`CGameSprite::FeedBack`, `ENGINE_MODE == 3` guard at 619) but not trap / disrupted (S, an EE
  bug).
- **GemRB:** `VerbalConstant(Verbal::Hide)` = slot 70 (Actor.cpp:11608, successful hide), `Verbal::SpellDisrupted` =
  slot 71 (GSUtils.cpp:2219), `Verbal::TrapSet` = slot 72 (FXOpcodes.cpp:7111). `vcremap.2da` doesn't remap them, so
  e.g. Morte's slot 71 "Location, Carceri" plays when his spell is disrupted.
- **Fix direction:** add 70, 71, 72 → 97 (Noop) rows to `gemrb/unhardcoded/pst/vcremap.2da`.
- **Re-check:** `python tools/parity/dumps.py lines orig 73DEEF 1259 1366 | grep -E "case|v84 ="`.

### A11-6 Battle cries (round 12: GemRB side traced)
- **Status:** ?   **Severity:** 3
- **Original:** event 10 (`73DEEF.c:360-410`), sent by `sub_6DE2A2:256` next to a `SendHitTrigger` call (an attack
  start, by the look of it; the function was not read in full). Non-party creatures share
  a global timer (`+4804` on the world screen, set to random 0..44 when one plays); every creature needs the option
  `+9110` and its own cooldown `+20850` ≤ 0, then sets it to 90; slot `9 + rand(filled of 9-10)` (only **2** slots;
  EE SPEECH.2DA says 5). Companions have no battle-cry slots, so this only concerns monsters.
- **GemRB:** `Actor::PlayWarCry(5)`, called from `GSUtils.cpp` `AttackCore` when the attacker picks a new target;
  random among the 5 battle-cry slots (9-13), plus the monster's sound file. EE: `CGameSprite::Attack` and
  `AttackReevaluate` send the battle-cry event at the same moment (and `CPsAbilityLitanyOfCurses::Fire`). Same
  trigger; the shared non-party timer (0..44) and per-creature 90-tick cooldown of the original are not in GemRB
  (sev 3, monsters only). Status: V sev 3.

### Parity
- Critical hit / miss lines: original has no such event for PST; GemRB's `vcremap.2da` maps 65/66 to Noop. P.
- Dying: event 13 → slot 19 (`73DEEF.c:442-468`); GemRB `Verbal::Die` = 19. P.

## Round 12 (2026-11-19): the remaining cases, judged against PST:EE

EE `CGameSprite::PlaySound` is table-driven: every case takes `SPEECH.2DA`'s OFFSET/NUM row and plays a random filled
slot in it. GemRB's `Verbal` enum uses the same slot numbers for rows 0-74 (`INITIAL_MEETING` 0 … `AREA_LOWER_WARD`
74), with `vcremap.2da` moving the rare selects. Triggers of each line in EE: morale failure → `MORALE`
(`DoMoraleFailure`), happiness checks → `HAPPY`/`UNHAPPY_*` (`CheckHappiness`), party order swap → `LEADER`
(`SwapCharacters`), damage effect → `HURT`, idle → `BORED` (world screen timer); GemRB raises the same constants from
the matching places (`Actor.cpp` happiness/tired/hurt, `Game.cpp` leader/bored). P at this level.

### A11-7 The Lower Ward comment never plays (V, sev 3)
- **EE** `CScreenWorld::HandleAmbiance` (PST branch): every 600 ticks, 16 % chance, a random party member (the same
  one again only 1 time in 10), then by the area's type flags: 0x1 Hive (night line when 0x400 is set and it's
  night), 0x4 Clerk's Ward, **0x8 Lower Ward**, 0x10 Ravel, 0x20 Baator, 0x40 Cube, 0x80 Negative Material Plane,
  0x100 Curst, 0x200 Carceri.
- **GemRB** `Game::CheckAreaComment` copies the timing exactly; its `pst/comment.2da` maps the flags the same,
  except **LOWER = 0x2**. PST areas: AR0500 (the Lower Ward) carries 0x8; no area carries 0x2. So the Lower Ward line
  (slot 74) never plays in GemRB. Fix: `comment.2da` LOWER 0x2 → 0x8.
- Day/night: every Hive area also has 0x400, so GemRB's per-row SWITCH matches EE.
