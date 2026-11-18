# Turn-based combat: a new combat system for GemRB/PST

Status: rev. 3 (2026-11-13). C0–C5, C8, C10 built; C6/C7 partly; U2, dice panel, hover numbers built; see
"Progress" at the end.

**Decision (rev. 3):** stop bending GemRB's real-time action system into
turns. When a fight starts, a new **Combat Director** takes the creatures in
it over completely: it decides, moves, animates and resolves their turns
itself. GemRB keeps running everything else, and keeps supplying the
**rules** (to-hit, damage, saves, effects, spells) and the **scripts' decisions**.
When the fight ends, the creatures are handed back to GemRB as if nothing
unusual happened.

Kept from rev. 2: the AI reads the BCS scripts (section 4), the world
keeps running outside the fight (section 5), the UI revamp with PST's own
art (section 6).

Reference build: `E:\GitHub\pst-forever` (Godot rebuild): combat in
`game/scripts/combat/combat.gd`, HUD in `game/scripts/ui/hud.gd`, AI design in
`docs/COMBAT_AI.md` (a scan of every PST `.BCS`), turn rules in
`docs/FIDELITY.md`. pst-forever already works this way: its combat drives the
creatures itself and only uses the rules. That's why it looks clean.

The rule both projects use: **loose on presentation, exact on anything a
script, dialogue, item or spell can observe.**

**Priority (owner, 2026-11-13): turn-based combat comes first; real-time play is no longer a
priority.** Engine changes that make turn-based work well are fine even when they change
real-time behaviour (e.g. `Actor::AttackedBy` now records the party as `LastAttacker`).
"Byte-for-byte unchanged real time" (2.2) is a nice-to-have, not a constraint.

---

## 1. Why the current system glitches

Today's `TurnManager` freezes everyone but the active creature and then
lets GemRB's real-time machinery run that one creature — its script, its
action queue, its pathfinding, its attack timers — and tries to stop it at
the right moment. Every glitch comes from that mismatch:

| Symptom | Cause (code) |
| --- | --- |
| **Running in place while waiting** | A creature's turn can end mid-walk (timeout, budget). It is then frozen (`Game::IsActorFrozen` → skipped in `Map.cpp`'s actor loop) with its walk stance and path still set; animations keep playing while position doesn't change. |
| **Running in place / stutter on its own turn** | When the budget is spent, `Actor::DoStep` clears the path and sets READY, but the script (or `AttackCore`'s `MoveNearerTo`) asks to move again the next tick: walk → ready → walk every tick. |
| **Pushing through frozen creatures** | GemRB's bumping (`Movable::BumpAway`, `FindBumpSpot`) gives a blocking creature a short path to step aside. A frozen creature can't take it, so it gets a walk stance it never walks, and the mover waits or repaths. |
| **Swings that don't look right** | `PerformAttack(…, turnBased)` skips GemRB's attack timing and the manager paces swings with a fixed `SWING_TICKS = 20`, unrelated to the attack animation's length. |
| **Turns that drag, or end halfway** | The manager can't know when a creature is "done", so it guesses: 10 idle ticks, 30 stuck ticks or an 8 s timeout (`TurnManager::IsTurnOver`). |
| **Enemies that loop or stand around** | Scripts re-run every tick of the turn; after the attack is spent, `Attack` is re-queued and released each tick; `Wait(6)` burns 90 ticks of the turn; `RunAwayFrom` waits on a game clock that is stopped. |
| **Guards that never come** | Frozen creatures run no scripts, so they never `See` the fight or answer `Help`. |

These aren't separate bugs to patch. They're what you get from running a
real-time engine one creature at a time.

---

## 2. Architecture: take over, then hand back

```
 real time (GemRB)          ──► fight starts ──►  Combat Director owns the combatants
   scripts, action queue,         takeover          turn order, budgets, our walker,
   pathing, attack timers                           our animation sequencing, AI
                                                    ── calls GemRB for rules & scripts ──
 real time (GemRB)          ◄── fight ends  ◄──   handback
```

New code in `gemrb/core/TurnBasedCombat/`: `CombatDirector.*` (owns the
fight; replaces `TurnManager`'s turn logic), `TurnSequence.*` (one turn as a
state machine), `CombatWalker.*` (our movement), `CombatRules.*` (thin calls
into GemRB's rules), `TurnAI.*` + `CombatAnalyzer.*` (section 4).

### 2.1 Takeover (when a creature enters the fight)

For each combatant:
- Mark it `IF_COMBAT_OWNED` (new internal flag). The map update loop skips
  its script and action processing (`Map.cpp` actor loop,
  `Scriptable::ProcessActions`), and `Movable::DoStep` does nothing for it.
  Its animation keeps updating.
- Stop it cleanly: clear path and action queue (`ClearPath`, `ClearActions`),
  stance READY, face the nearest enemy. Nothing it was doing in real time
  carries into the fight.
- Keep its triggers (`AttackedBy`, `Help`…) — the AI reads them at its turn.
- Exempt it from bumping: owned creatures never get bump paths; GemRB
  movers treat them as fixed obstacles.

### 2.2 What we do ourselves, what we call GemRB for

| Ours (presentation and flow) | GemRB's (rules and observable state) |
| --- | --- |
| Turn order, initiative, budgets, reactions | `Actor::GetToHit`, `GetDefense`, weapon headers, APR (`GetNumberOfAttacks`) |
| Movement: pathing with the budget, step-by-step walking, facing | `PathFinder::FindPath` (search only), `Map` walkability/LOS |
| Animation: stance, play once, wait for the sequence to end | Damage, criticals, resistances (`Actor::Damage`), saving throws |
| When each swing, cast or step happens | Spell casting and effects (`EffectQueue`, `Spell`/`Projectile`), items, charges |
| AI decisions (from the scripts, section 4) | Trigger evaluation, object selectors, instant script actions |
| Combat start/join/end | Death handling (`Actor::Die`, `CheckOnDeath`, KAPUTZ), XP, morale |

Rule of thumb: **extract, don't reimplement.** Where a GemRB function mixes
timing with rules (e.g. `Actor::PerformAttack` does the attack-round timing
*and* the roll, damage and triggers), split it: a `ResolveSwing(target)` with
the rules part, used by both real time and the Director. Real-time behaviour
stays byte-for-byte the same.

### 2.3 One turn = a sequence, not a timer

`TurnSequence` runs explicit steps, each finishing on an **event**, never on a
tick count:

```
 Begin ─► Decide ─► Move ─► Act ─► Resolve ─► (more attacks / move left?) ─► End
           │ AI or      │ walker     │ anim     │ rules, floaters,
           │ player     │ arrives    │ hits its │ log, triggers
           │ input      │            │ frame    │
```

- **Begin:** tick its effects one round (combat clock, section 5), skip if
  held/asleep/stunned, camera + banner.
- **Move:** `CombatWalker` follows a path clipped to the budget, sets walk
  stance at start and READY at the end, always. Arrival is the event.
- **Act:** play the attack/cast animation once; the "hit" frame (or the end
  of the sequence) is the event. Then **Resolve** through GemRB's rules.
- Multiple attacks per round: Act → Resolve per swing; 3/2 APR alternates
  as GemRB does.
- **End:** stance READY, no path, no queue. A creature never leaves its turn
  mid-walk.
- Player turns use the same steps; input fills in Decide.

### 2.4 Observable side effects we must raise ourselves

Because we bypass GemRB's actions, everything those actions would have told
the scripts must still happen, through GemRB's own functions:
- `Actor::AttackedBy` (→ `AttackedBy` trigger, `LastAttacker`), `HitBy`
  via `Actor::Damage`, `LastTarget`/`LastSpellTarget`, `SpellCast` triggers.
- Hostility: attacking a neutral makes it hostile as in GemRB
  (`Game::PartyAttack`, EA change), `Help`/`Shout` range.
- Death and kill variables, XP, morale changes, `Die` triggers.
- Sounds and voice lines GemRB plays on attack, hit and death (`VB_ATTACK`,
  `VB_DAMAGE`, `VB_DIE`), and combat music (`CombatCounter`).

A checklist test stages one attack, one cast and one kill in each mode
(real time vs Director) and compares the triggers and variables they leave.

### 2.5 Handback (fight ends, creature leaves, or dialogue/cutscene takes over)

- Clear `IF_COMBAT_OWNED`; stance READY → GemRB idles it.
- Empty path and action queue; leave triggers that haven't been read so its
  script reacts naturally on its next real-time tick.
- Rebase its timers and effect expiries from the combat clock to world time
  (section 5).
- Fleeing creatures that leave the fight (`EscapeArea`, out of sight) are
  handed back on their own.
- A dialogue or cutscene during combat: hand back the creatures it needs,
  take them over again afterwards (re-roll nothing; keep the order).

---

## 3. Why this fixes the glitches

| Symptom | Why it can't happen now |
| --- | --- |
| Running in place | Only our walker moves owned creatures, and it always ends with READY and no path. No bump paths, no frozen walkers. |
| Stutter | No script or action re-queues movement during the fight. |
| Odd swings | Each swing is its animation played once and waited for. |
| Dragging turns | Turns end when their steps end. |
| Enemy loops | The AI decides once per turn (section 4); nothing re-fires. |

---

## 4. The combat AI: a BCS interpreter that plans turns

PST has no AI engine. 1,068 of 1,134 placed creatures fight because their
`.BCS` says so (pst-forever scan). The scripts decide **whether** to fight,
**whom**, **when** to flee, call for help, summon or cast a scripted spell;
they never decide where to stand or how to approach. The AI reads the
scripts for the first, exactly, and supplies the second.

```
 .BCS ─► Analyzer ─► CombatProfile ─►  each turn: Decide ─► Intent ─► Tactics ─► TurnSequence
         (load time, cached)                    (dry-run      (what)     (how)      (does it)
                                                 triggers)
```

### 4.1 Analyzer (load time)

Walks GemRB's parsed `Script` → `ResponseBlock` → `Condition`/`ResponseSet`
and classifies blocks without running anything:
- **Roles:** engage (`Attack*`), cast (`Spell*`, `ForceSpell*`, `UseItem*`),
  flee (`RunAwayFrom*`), help (`Help`, `Shout`), turn hostile (`Enemy`,
  `ChangeEnemyAlly`), summon (`CreateCreature*`), talk/surrender
  (`Dialogue`, `StartDialogue*`), bark, state, behaviour swap (`ChangeAIScript`).
- **Gates:** `See`, `AttackedBy`, `Help`, `Die`, `HPPercentLT`, step counters
  (`Global`/`Internal`), `Allegiance`, timers.
- **Profile:** archetype (guard, coward, brute, fight-then-flee,
  caller/summoner, scripted caster), flee threshold, spell rotation, target
  selectors, can surrender, calls for help.
- **Unmapped list:** combat actions/triggers with no turn rule — logged and
  counted; each one is a bug to fix.

### 4.2 Decide (start of each AI turn)

Evaluates the script slots in GemRB order with GemRB's own trigger code, in a
**dry run** (triggers read, not consumed; no action runs). `Continue`,
weighted responses (`ResponseSet::Execute`'s choice), selectors and
variables stay exact.
- Context: triggers raised since its last turn.
- Same block still winning with an unfinished intent → keep the intent
  (that's how `Attack` chases across turns).
- The chosen response is split: **instant actions run now** through GemRB's
  action functions (`Enemy`, `Help`, `SetGlobal`, `CreateCreature`,
  `FloatMessage`, `ChangeAIScript`…); the **first time-taking action becomes
  the intent**; later ones wait for later turns.
- Then the triggers are consumed, as GemRB would after a script pass.

### 4.3 Intent → turn

| Script action | Turn (run by `TurnSequence`) |
| --- | --- |
| `Attack*`, `AttackReevaluate`, `AttackOneRound` | move toward the target within budget; full attack round if in reach; carries over |
| `Spell*`, `ForceSpell*`, `UseItem*` | cast/use if in range and line of sight, else move into range |
| `RunAwayFrom*` | spend movement fleeing (`Map::RunAway` picks the spot); lasts `ceil(t / 6)` rounds |
| `MoveTo*`, `RunTo*`, `EscapeArea*` | walk with the budget; `EscapeArea` hands the creature back on arrival |
| `Dialogue`, `StartDialogue*` | pause the fight, hand back the speakers, open the talk |
| `Wait`, `SmallWait`, `WaitRandom` | end the turn; longer waits skip `ceil(n / 6) − 1` more turns |
| `Polymorph`, `ChangeAIScript` | turn spent; re-decide next turn |
| no intent | tactics fallback |

### 4.4 Tactics (ours)

- **How:** standing spot around the target (pst-forever `approach_path`:
  16-point ring, five shortest paths), avoid attacks of opportunity, don't
  block allies, ranged attackers keep distance and line of sight.
- **`Turn Based Tactical AI` setting:** on an `Attack` intent a creature may
  use its own spells, abilities or items on the same target (damage or
  disable foes, heal an ally under 50 %); a hostile with no intent attacks
  what is in reach. Off = the original exactly.
- **Scriptless hostiles** (summons, plain monsters): a generic profile from
  the CRE — class, spells, items — through the same tactics.
- **Morale break / panic:** flee intent.
- Never starts a fight, changes sides or ends one.

### 4.5 Party and debugging

- Party members are the player's. Companion scripts (`PCMORTE`,
  `PCNORDOM`…) get a decide pass each round for barks; their intents are
  dropped unless party AI is on (which is also the autotest).
- Log per turn: `Round 3 / Harmonium Guard: block #4 (See([PC]) & …) → Enemy, Help; intent Attack(NearestEnemyOf) → move 28 ft, 2 swings`.
- Optional overlay: each enemy's intent above its head.
- Dump tool: profile and unmapped list for every PST script.

---

## 5. The world keeps running

Only owned creatures take turns; everyone else stays in real time
(townsfolk, area scripts, timers, ambient animations, music).

- **No more freezing the map.** `TurnManager::IsFrozen` and the stopped
  clock in `GlobalTimer.cpp` go away; owned creatures are simply skipped by
  GemRB (2.1).
- **Combat clock:** starts at `GameTime` when the fight starts, advances one
  round (`core->Time.round_size`) at each round end. Owned creatures'
  effects, timers and `Wait`s use it (new `Scriptable::LocalTime()`;
  `EffectQueue` duration checks and actor timers migrate to it). On
  handback, rebase by `GameTime − combat clock`.
- **Area effects and projectiles** from combatants tick on the combat clock.
- **Global variables and `GlobalTimer*`** stay world time.
- **Joining:** a non-combatant that targets a combatant, casts at one,
  gets caught in an area effect, or turns hostile toward the party is taken
  over and slotted into the order. Its scripts run in real time until then,
  so `See`/`Help` work naturally.
- **Non-combatants walking into the fight** treat owned creatures as fixed
  obstacles and route around.
- Party banter and area comments are off during a fight. Saving during
  combat stays refused.
- Risks: a full census of `GameTime` uses on actors is needed first, or
  effects will expire while a combatant waits.

---

## 6. UI and UX revamp

pst-forever's combat UI is a high-resolution layer of its own: real
fonts, panels, bars, animation, vector overlays (`hud.gd`, `overlay.gd`).
Ours is GemRB's stock 800×600-era widgets. The toolkit has to grow.

### 6.1 Gap

| Element | pst-forever | Ours |
| --- | --- | --- |
| Scale and type | UI sized for the screen, large outlined text | Laid out at game resolution, small bitmap fonts |
| Panels | Dark panels, bronze borders, rounded corners, shadow | Flat alpha-black rectangles |
| Timeline | 80 px portraits, 104 px current, HP bar and name under each, starts at whoever acts | 52×64 cards, HP as a border fill, fixed order |
| Character bar | Portrait, HP/AC/THAC0, movement bar in feet, ● Action ○ Reaction, attacks left | Eight icon buttons and one info line |
| Buttons | Few, large, hotkeys on them; spell hotbar always visible | Eight modes; casting through a menu |
| Feedback | Animated d20 with verdict, banners, floating damage/miss text, coloured log with roll breakdown | Stock message-window strings |
| Hover | Hit chance, roll needed, damage, distance, "needs X ft more", creature info | "Attack" / "Out of reach" |
| World overlay | Smooth path (gold/red), pulsing end ring, reach outline, dashed target line, range ring, AoE template | Dots and reticle from 2×2 rects |
| Motion | Rolling d20 numbers and pop, fades, banners (visual only; no dice sound) | Timeline slide and death fade |

### 6.2 Art: Planescape: Torment's own (owner's decision, 2026-11-12)

pst-forever's layout and behaviour, PST's graphics:
- **Action buttons:** the radial menu BAMs (`GUIWORLD` window 3, `FloatMenuWindow.py`).
- **Panels and frames:** PST's window art (`GUIWORLD`, `GUIINV`, `GUIREC`), cut into 9-slice pieces at load.
- **Portraits:** portrait panel art (`GUIWORLD` window 1); creature cards use bestiary pictures.
- **Spell and item icons:** from SPL/ITM headers.
- **Fonts:** `FONTDLG`, `TRMTFONT`, `EXOFONT` at the UI scale; TTF only as a fallback setting.
- **Colours:** picked from that art, set once in `Theme.py`.
- Read from the player's game files at run time; nothing shipped. Remove the
  borrowed `bar_*.png` icons ("war2 control panel icons").

### 6.3 How

1. **Kit** (`GUIScripts/pst/tbhud/`): `Theme.py` + `Widgets.py` (panel, bar,
   pips, portrait card, rich tooltip, banner, tween helper on `GemRB.SetTimer`).
2. **UI scale** independent of game resolution.
3. **Event feed:** the Director emits combat events (rolls with d20/needed/
   THAC0/AC, damage, saves, deaths, turn starts, intents) read through
   `GemRB.GetCombatEvents()`. Dice panel, log, floaters, banners read it.
   Natural now that the Director resolves everything itself.
4. **Overlay drawing** with proper primitives through the video driver
   (shared with the graphics overhaul).
5. **Fewer clicks:** click an enemy to move and attack; hotkeys on buttons;
   hotbar always visible; Space ends turn; right-click cancels a move with
   refund; banner and camera on turn change.

### 6.4 UI packages

- **U0.** Art inventory (`GUIWORLD` windows 1 and 3 and other packs → HUD elements); font readability at 1.5×/2×.
- **U1.** Kit: theme, fonts, scale, 9-slice panels, widgets, tweens; radial menu icons.
- **U2.** Event feed.
- **U3.** Timeline.
- **U4.** Character bar with hotbar.
- **U5.** Dice panel, log, floating text, banners.
- **U6.** Hover tooltips and overlay drawing, spell range/area/LOS/save chance.
- **U7.** UX pass, combat speed, "skip enemy animations", intent display.

---

## 7. Work packages (in order)

Each builds with `build_install.bat`, runs in game, and adds tests to
`tests/core/Test_TurnBasedCombat.cpp` where it's pure logic.

### C0. Groundwork
- Census of `GameTime` uses on actors; census of what `PerformAttack`,
  casting and `UseItem` do besides rules (for 2.4).
- Extract `ResolveSwing` (and the cast/use equivalents if needed) from the
  timed GemRB code; real time unchanged.

### C1. Director with takeover and handback
- `IF_COMBAT_OWNED`, skip in the map loop and `DoStep`, no bumping; clean
  takeover and handback; old freeze and stopped clock removed. Keep the
  existing initiative, budgets, party groups and UI wired to the Director.
- Done when: start a fight, nobody runs in place, end it, everyone behaves
  normally again.

### C2. TurnSequence, walker, animations
- Explicit steps (2.3); our walker; play-once animations with end events;
  multiple attacks per round; player turns on the same steps.
- Done when: swings line up with animations; turns never end mid-walk.

### C3. Rules and side effects
- Swings, casts and item use through GemRB's rules; every observable side
  effect from 2.4; the real-time vs Director comparison test.

### C4. Combat clock and the running world
- `LocalTime()`, migration, rebase on handback; joining from outside; banter off.
- Done when: in a Hive fight, townsfolk walk and talk; a 3-round spell lasts 3 rounds.

### C5. AI: analyzer and dump
- Classification, profiles, unmapped list; compare with pst-forever's scan
  (537 combat scripts, 1,873 blocks).

### C6. AI: decide, intent, tactics
- Dry-run decide, response split, intents, tactics, Tactical AI setting,
  scriptless profile, morale.
- Done when: `0403MAGE` casts its four spells in order, one per turn, then
  melees; `0704RUN` flees `ceil(t/6)` rounds; `0700ANAM` flees at low HP.

### C7. Start, join and end from scripts
- Start on hostile intent or `PartyAttack`; join through `Help`/targeting;
  end when no hostile intent and no one `See`s an enemy.
- Done when: `0702GARD` guards join through `Help`; `0504ALEK`'s summons join;
  a surrender dialogue ends the fight.

### C8. Reactions and 2e extras
- Attacks of opportunity (one reaction per round), surprise round,
  cancel move with refund, delay turn. Each a setting. Initiative stays once per combat.

### C9. UI — packages U0–U7 (section 6.4)

### C10. Autotest
- Party AI on + staged fights from saves (`GEMRB_AUTOLOAD`,
  `tools/pst_shot.ps1`), logging each turn; the five script cases above.

C0–C3 are what removes the glitches; C5–C7 the AI; C9 the look. The UI
track (U0–U2) can start alongside C0–C1.

---

## 8. Settings (GemRB.cfg / game options)

Existing: `Turn Based Combat`, `Turn Based Movement Percent`, `Turn Based
Weapon Speed`, `Turn Based Start On Sight`, `Turn Based Party Groups`,
`Turn Based Auto End Turn`, `Turn Based Camera Zoom`.
New: `Turn Based Tactical AI`, `Turn Based Opportunity Attacks`,
`Turn Based Surprise`, `Turn Based Combat Speed`,
`Turn Based Dice Panel`, `Turn Based Show Enemy Intent`,
`Turn Based Combat Vision` (default on: living enemies in the fight grant
the party vision and clear fog of war on them),
`Turn Based Camera Offset X` / `Turn Based Camera Offset Y` (map pixels;
positive Y puts the active character toward the bottom of the screen).

## 9. Open decisions

- "Tactical AI" default on or off.
- ~~Initiative once per combat or re-rolled each round~~: once per combat (owner, 2026-11-13).
- Show enemy intent to the player, or debug-only.
- Who joins: only creatures that act on the fight (planned), or everyone within a radius.
- Dice panel and log style once the graphics overhaul (NOTES.md) lands.

---

## 10. Progress (2026-11-13)

Built, in `gemrb/core/TurnBasedCombat/CombatDirector.*` (TurnManager renamed and rewritten):

- **Takeover/handback (C1):** `IF_COMBAT_OWNED`; the map loop gives owned creatures only
  timers, effects and animation (`Scriptable::UpdateWithoutActions`); `Actor::DoStep` does
  nothing for them; never bumpable. Takeover clears path/queue, READY, faces the nearest
  enemy. Handback on fight end, death (GemRB handles death), dialog/cutscene (retaken after).
  The world freeze and the stopped clock are gone.
- **Turn sequence (C2):** Begin → Act ↔ Walk / Swing → Over, ending on events. GemRB's own
  actions still decide *what* (so 2.4's side effects come for free); the director decides
  *when* they run (only the active creature's, via `ProcessActions`), owns movement and swings:
  - path requests of owned creatures (`Movable::ScheduleFindPath`) come to `RequestPath`: a
    synchronous path clipped to the budget (`ClipPath`), walked by our walker (GemRB's step
    code driven only from the director), always ending READY with no path.
  - `AttackCore` in reach calls `RequestAttackRound`: one round = InitRound, then per swing
    the attack animation plays once; melee resolves on the hit frame, ranged at once (GemRB
    fires the missile); next swing when the animation wraps.
- **Rules (C0/C3):** `Actor::ResolveSwing()` (the rules half of `PerformAttack`) plus
  `lastSwing` (roll, bonus, defense, hit, crit, damage) for the event feed.
- **Combat clock (C4):** each combatant has its own clock (`Combatant::clockTime`); while
  its effects are evaluated (`Actor::RefreshEffects`, `EffectQueue::ApplyEffect`) the game
  clock reads as that clock (`CombatClockScope`). `Map::UpdateEffects` skips combatants; at
  the start of each of its turns the director's upkeep runs its effects through one round tick
  by tick, so durations, regeneration (TNO's included), poison and other periodic effects
  follow its turns and happen at turn start. Handback rebases durations onto world time.
  Banter/area comments off during a fight. Outsiders that attack a combatant join on the spot.
- **Spells resolve in the caster's turn:** casting time is one play of the cast animation; the
  turn then holds until every projectile the caster fired has made its first hit or explosion
  (`CombatDirector::SpellInFlight`, at most 10 s); End Turn mid-spell ends it once the spell has
  landed. Lingering area effects (clouds, walls, repeating explosions) of a living combatant run on
  its caster's combat clock (`Projectile::HeldByCombatClock`): they pulse at the start of the
  caster's turns and last that many of its turns; world time again after the fight. The casting
  glow ends on the caster's combat clock too (it used to loop for many turns: its end was set in
  world time, which runs ahead of the combat clock).
- **AI (C6, partial):** one real script pass per AI turn (`ExecuteScript`), GemRB's own block
  choice; an unfinished Attack carries over (that's the chase). In a fight `Wait`,
  `WaitRandom`, `SmallWait` and `NoAction` only end the turn (no turns are skipped; the script
  decides afresh next turn), and the instant actions queued behind the wait (step counters,
  barks) run right away. "Turn Based Tactical AI" (default on): a hostile with no intent, or
  only idling, attacks the nearest enemy it sees, unless its scripts make it a coward or a
  caller.
- **Analyzer (C5):** `CombatAnalyzer` reads a parsed script without running it: combat blocks,
  roles, flee threshold (`HPPercentLT` guard), step-counter casts, spells, archetype, and the
  time-taking actions without a turn rule. `GemRB.AnalyzeCombatScript(resref)`;
  `tools\tb_analyze.ps1` dumps every script of the game to `dev\combat_profiles.md`
  (2,236 scripts, 1,258 with combat blocks: guard 321, fight-then-flee 269, brute 246, coward
  229, caster 87, caller 4; counted over all scripts, area ones included, so higher than
  pst-forever's 537 creature scripts). Unmapped list is empty after mapping `RunningAttack`
  (an attack through `AttackCore`, 203 uses) and short animation/facing actions.
- **Combat maneuvers:** `Attack of Opportunity!` floats over the reactor. Withdraw (action +
  half remaining movement, refused at 0 movement, AoO immune, walk, dust + `withdraw`); Run
  (action, remaining += max, smoke + `sprint`, AI closes distance); Block (fighters except
  Morte, spends the action, remaining attacks become block stacks, vs AC 4 then compare
  rolls, shield glow / parry sparks); Trip (fighters, first swing -2, no
  damage, save vs death or prone) and Knockdown (enemies THAC0 15-, same without the -2).
  Prone fall/rise uses the get-up BAM when the creature has one (reversed to fall, forward
  to stand); otherwise the death fall, reversed to stand.
  Sounds in `sounds/`, copied to `override/pst`.
- **Reactions and 2e extras (C8):** each a setting, all on in `dev_settings.ini`.
  `Turn Based Opportunity Attacks`: walking out of an enemy's melee reach gives it one swing
  (one reaction per round); the mover is held at the edge, then walks on.
  `Turn Based Surprise`: whoever sees no enemy as the fight starts loses round 1.
  Initiative is rolled once per combat (decided 2026-11-13; no per-round re-roll). Delay was removed
  (owner, 2026-11-18). Right click (or `GemRB.CancelTurnMove`) stops a walk; the unwalked movement stays.
- **Event feed (U2):** `GemRB.GetCombatEvents()` (CombatStart/End, RoundStart, TurnStart,
  Swing, Death, Intent, Reaction).
- **Pacing:** a beat after each swing before the next one of the round (6 ticks, 0.4 s at
  normal speed). Swings have no pause before the animation. A trip or knockdown plays that
  attack animation as a pull-back (half speed on the early frames) then a punch (2.2x).
  `Turn Based Combat Speed` (percent, 100 normal) scales the pause between swings. 3/2 APR alternates 2 and 1 attacks per attack round (GemRB's `InitRound`); the bar
  shows the coming round's count (`GetTurnBudget()['Attacks']`).
- **End Turn** (button and Space) ends the selected character's turn; the next party member
  adjacent in the order takes over (selected, camera on it), the last one passes the turn on.
- **Party switching, gear, voices:** clicking a party member's timeline card or portrait hands
  the turn to it if it is in the active party group (adjacent and not done); otherwise the
  selection snaps back with a message. Gear changes (equip/unequip, incl. the active weapon
  slot, dropping worn gear) take the main action; pack, quick item slots, quiver and spare
  weapon slots are free; putting an item back where it came from is free. The bar stays out of
  the way (hidden, no focus stealing) while the inventory or another full window is open. A
  turn passing to a party member plays a plain select line and resets the click streak;
  clicking an already selected character again talks, and the 4th click in a row on the same one
  gets the annoyed (rare select) lines. Alpha-channel windows clear their buffer before a full
  redraw (no trails from moving timeline cards).
- **Dice panel (U5):** drawn in C++ (`TurnBasedCombat/CombatHud.*`, fed from `PushEvent`): a shaded
  3D d20 (raw triangles, stroke numerals on the faces) spins from `SwingStart`, lands on the real
  roll when the swing resolves, then reveals step by step: `+ modifier`, `=`, result `vs` the total
  needed, HIT!/MISS! with damage. Natural 20/1 (and crits) skip the sum: CRITICAL HIT!/MISS! with a
  glow. Shown the friendly way round: d20 + (20 - THAC0) against 21 - AC. The director holds the
  next swing until the reveal is done (`CombatHud::Holding`). `Turn Based Dice Panel`.
- **Hover (U6, first part):** a hit panel beside the hovered enemy on your turn: chance (big),
  "d20 +N, needs T (a X+ on the die)", the THAC0 breakdown (base, Str/Dex, weapon, proficiency,
  armor, situational; `Actor::PredictHit`), target AC, damage, distance, in reach / walks N ft /
  out of reach. Hovering any creature (also in real time) shows a top bar: name, level, class,
  HP bar current/max, and buffs/debuffs (spells with timed effects, icon + name, hostile in red).
  `Hover HP Bar`.
- **Turn banner, timeline (U3, U5):** "Your Turn" panel with the names sharing the turn when it
  passes to the party (`Turn Based Turn Banner`). Timeline cards 60x76, the active one grows to
  80x101; lost HP fills cards and PST's party portraits red from the bottom; the dead fade and
  fall; the line under it shows the round and who acts with their level.
- **Saving throws:** each 2e save shows a small d20 over the creature for 0.2 s, then
  white "Saved"/"Save failed" combat text (same stay-and-drift floaters as damage/miss)
  and `tbsaveok`/`tbsavefl` (sounds from `sounds/`, in `override/pst`).
  `Turn Based Save Dice`. The WAV reader now skips LIST and other chunks before `data`.
- **Fonts:** the new HUD and the bar/timeline labels use FONTDLG; TRMTFONT dropped there.
- **Floating text:** `Turn Based Floating Text` draws white stay-and-drift numbers and
  labels at the old save-die height (80 map-px above the feet, on the crown; the d20 sits
  95 map-px up): Miss/Fumble over the attacker, damage / saves / trip results / Blocked
  over the creature they apply to.
  Everyone who joins a fight shows "Initiative: N". They sit a few seconds, drift a pixel
  or two, stack so a new one doesn't cover the last, then fade. No flying-up PST overhead.
  A trip/knockdown shows only the result, not "Trip!" as it starts. GemRB's attack-roll
  lines stay the combat log.
- **Tests:** `ClipPath` in `Test_TurnBasedCombat.cpp`. In game: `tools\tb_fight.ps1` (three
  Mortuary ghouls, save index 2), `tools\tb_flee_cast.ps1` (a fight-then-flee ghoul, a cast with
  `-Spell <spell.ids number>`), `tools\tb_flee_pc.py` (party members flee on their turn).
  `GemRB.ExecuteActionAt(actor, action, target)` aims a script action at a global ID (target
  written `[-1]`), for these tests and the autotest.

- **Hotbar (U4):** `pst/TurnOrder.py`, always up (real time too, `Hotbar` setting), just above PST's
  portrait strip. Everything at once: Attack, Talk, Inventory; the four weapon quick slots (click =
  take in hand and attack); the five quick items; thief skills, memorized spells and abilities
  (10x2, paged); Run, Withdraw, Block, Trip icons and a round End Turn button (turn based only, hidden out of a fight). Info line: name,
  HP/AC/THAC0, movement bar in feet, action pip, attacks; Cancel while an action is picked. Icons are
  PST's (radial menu BAMs `AMATTCK`/`AMTLK`/`AMINVNT`, slot art `AMGENS`, item and spell icons); the
  war2 `bar_*.png` are gone, as are the Move button (click the ground to move) and the radial menu
  (right click now cancels the picked action or the walk). Other turns show the selected character's
  bar greyed. The bar and the timeline never take the key focus (Escape/Space reach the game view).
  Click-twice move confirm off by default in `dev_settings.ini`. The aiming cursor of a spell/item
  shows no walking path.
- **Engine fix:** `Interface::Main` iterated its timer deque by iterator while callbacks add timers
  (push_back invalidates deque iterators): froze or crashed with self-rescheduling GUI timers. Now by index.

- **Autotest (C10):** `Turn Based Party AI` lets the AI play party members' turns (their
  scripts, then the nearest enemy). `tools\tb_autotest.ps1` stages fights from saves (cases:
  `mortuary`, `ghouls`), runs them to the end and fails on a crash, a fight that never starts
  or ends, or stalled turns. Both cases pass.

Verified in game: walking within the budget, full attack rounds swing by swing (3 APR ghouls),
joining mid-fight, deaths handed back, a cast (`ForceSpell`) inside the caster's turn, flee
walking (`RunAwayFrom`), TNO's regeneration only at his turn starts (HP flat through 16 s of
others' turns), End Turn for a party group, dice panel, hover numbers, the autotest.

Combat vision (2026-11-14): `Turn Based Combat Vision` (default on) makes living EA_EVIL
enemies in the fight grant party vision and clear fog of war on them (`Map::UpdateFog` via
`CombatDirector::RevealCombatVision`). Neutrals are ignored. Off restores the original fog.

Neutrals are not combatants (2026-11-14): only living EA_EVIL count as enemies. A still-neutral
NPC is not pulled in (even if the party hits it), is dropped from the order if its EA goes
neutral, and does not keep the fight going. `Enemy()` first, then they join as a real hostile.

Combat camera offset (2026-11-14): turn-start centering and the walk-follow camera use
`Turn Based Camera Offset X/Y` (map pixels, Y default 80) so the character sits below the
hover HP bar instead of under it. Combat HUD names (timeline, hover bar, hit panel, dice,
turn banner, hotbar) use `Actor::GetDisplayedName`, the same string mouseover shows
(PST long name / `GetDefaultName` elsewhere).

Found along the way (GemRB, not the director): `Actor::AttackedBy` records `LastAttacker` only
when neither side is a PC (since 2011). Scripts that flee from or retaliate against
`LastAttackerOf(Myself)` (e.g. `1700GUL7`'s flee block) therefore never resolve against the
party, in real time as well. Changing it is a GemRB-wide behaviour change; open.

Movement accuracy (2026-11-14): the preview line is the walk. `CombatDirector::PlanPath` is the one
path source for the preview and `RequestPath`; a confirmed move pins the clipped preview path
(`KeepPlan`), so the walk takes the drawn line. Synchronous paths read
`Map::GetFreshTraversabilityCacheData()`: the cache only refreshed through the real-time scheduler,
so turn based paths saw stale positions and bump states (a fighter could block itself: "no path"
everywhere). The reach shade uses FindPath's rules (creatures block, any-angle, `PF_EXACT`
unweighted search); `Path::partial` marks a goal that can't be reached ("Can't get there"); the
walker finishes its clipped path and bills `PathCost`; fighters don't stop each other's walks,
non-fighting bystanders step aside; the blocked latch only refuses the same destination.
Check: `tools	b_move_accuracy.ps1 -Save 3` (random click moves, each must end on the promised
pixel), `TurnMovement*` unit tests.

Not done yet: hotbar hotkeys and drag-to-arrange, overlay drawing with proper primitives (U6: smooth path, reach outline,
spell range/AoE), U7's UX pass, dry-run decide (scripts run for real once per turn), per-intent multi-turn flee
(`ceil(t/6)` rounds; now one flee walk per turn, re-decided each turn), the rest of the UI
revamp with PST's art (U0, U1: PST art panels, radial-menu icons), autotest cases
for the C6/C7 "done when" scripts (0403MAGE, 0704RUN, 0700ANAM, 0702GARD, 0504ALEK: need
saves there), modal states (bard song) on
world time. The UI attack click through a synthetic mouse event didn't register in testing
(the GUI action itself works); worth a check by hand.
