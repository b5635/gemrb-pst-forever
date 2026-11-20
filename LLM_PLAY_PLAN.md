# LLM play-through: can a local model finish PST on this fork?

Status: plan only (2026-11-19). Nothing below is built yet.

## 0. Goal

Prove the game is **completable** on this fork (turn-based combat, parity fixes, EE UI) by having
an agent play it from the Mortuary to the ending, and catch every place where it can't go on:
a dialogue with no valid option, a script that never fires, a door that never opens, a fight that
stalls, a crash.

Two players use the same tool layer:

1. **Replay runner (deterministic, the real "unit test").** Plays a walkthrough written as data
   (section 4) step by step with no model. Fast, repeatable, runs in CI-like batches per chapter.
   If it fails, the game (or the walkthrough) is broken.
2. **LLM agent (exploratory).** A local model (llama.cpp / Ollama / LM Studio, OpenAI-compatible
   tool calls) gets the same tools plus the walkthrough as guidance text and plays. It finds what the
   replay can't: alternative dialogue paths, recovering from mistakes, unexpected states.

Build the replay runner first; the LLM agent is a thin loop on top of the same tools.

## 1. What already exists

| Piece | Where | Use for the agent |
|---|---|---|
| File-IPC Python console in the game (250 ms poll, `dev\cmd.py` → `dev\out.txt`) | `gemrb/GUIScripts/DevConsole.py`, started from `pst/Start.py` | transport for every tool |
| Driver: start/load save, py, click, key, shot, log, crash | `tools/dev.ps1` | process control, screenshots |
| Run a script action on a creature | `GemRB.ExecuteString`, `GemRB.ExecuteActionAt(actor, action, target)` | most "do" tools |
| Turn-based state | `GetTurnOrder`, `GetTurnBudget`, `GetCombatEvents`, `EndTurn`, `TurnMoveTo`, `CancelTurnMove` | combat tools |
| Party AI plays turn-based fights | var `Turn Based Party AI` (used by `tb_autotest.ps1`) | "auto-resolve combat" mode |
| Party / stats / inventory / spells | `GetPartySize`, `GetPlayerName`, `GetPlayerStat`, `GetSlotItem`, `GetItem`, `GetMemorizedSpell`, `UseItem`, `SpellCast`, `CreateItem` | character tools |
| Variables, journal, time | `CheckVar`, `GetGameVar`, `SetGlobal`, `GetJournalEntry`, `GetJournalSize`, `GetGameTime` | quest progress checks |
| Containers / stores | `GetContainer`, `GetContainerItem`, `ChangeContainerItem`, `GetStore*`, `EnterStore`, `LeaveStore` | loot / shop tools |
| Saves | `SaveGame`, `LoadGame`, `GetSaveGames` | checkpoints |
| Dialogue speaker | `GetDialogTarget` | partial dialogue state |
| Narration / cutscene | `IsNarrationPlaying`, `EndCutSceneMode` | "wait until idle" |
| Hang watchdog, crash dump | `crashes\last_hang.txt`, `crashes\last_crash.txt` | failure reporting |
| Effect / actor debug | `DebugEffects`, `DumpActor` | detail on demand |

## 2. What's missing (the gaps)

Ordered by how badly they block play. "Engine" = new C++ in `GUIScript.cpp` (or core);
"Py" = Python helpers on top of what exists.

### 2.1 Perception: the agent can't see the world as data  (blocker)

There is no Python call that lists what's in the current area. The agent would have to read
screenshots, which a local model can't do reliably.

- **Engine `GemRB.GetAreaObjects(flags)`**: every visible thing in the current area as dicts:
  - actors: global ID, scripting name, display name (strref text), position, distance to the
    protagonist, `IsPC`, hostile/neutral/ally (EA), dead/unconscious, has dialogue (DLG resref
    non-empty), visible/explored;
  - doors: name, position, open/closed, locked, key item, trapped (only if detected);
  - containers: name, position, locked, item count (no contents until opened), trapped (detected);
  - info points / triggers / travel regions: name, type, position, destination area for exits;
  - ground piles.
  Respect fog of war and visibility so the agent doesn't get information the player wouldn't
  (flag `ALL` for debug/replay use).
- **Engine `GemRB.GetAreaExits()`** (or part of the above): travel regions with destination
  area + entrance, so "leave towards X" is possible without guessing.
- **Py `look()`**: compact text summary of the above, sorted by distance, with short stable
  handles (`a3`, `d1`, `c2`, `x1`) mapped to IDs/names. This is what the LLM reads every turn.
- **Engine `GemRB.GetWorldMapAreas()`**: reachable world-map destinations (PST has the
  Sigil map); `UpdateWorldMap`/`MoveToArea` exist but there's no list for the agent.

### 2.2 Dialogue as data  (blocker)

Dialogue is the whole game in PST. Today the only way in is clicking the message window.

- **Engine `GemRB.GetDialogState()`**: `None` outside dialogue, else
  `{Speaker, SpeakerName, DLG, State, Text, Options:[{Index, Text}], Ended}`. The text is already
  built in `DialogHandler::DialogChoose` (`ds->StrRef`, `GetDialogOptions`); expose it instead of
  scraping the TextArea. Options must be only the ones that passed their triggers (what the player sees).
- **Engine `GemRB.DialogChoose(index)`**: calls `gc->dialoghandler->DialogChoose(idx)` the same
  way the TextArea select action does (`DialogHandler.cpp:455`), so trigger/action/journal side
  effects are identical to a click. Also handle the "end dialogue" / continue button state
  (`DF_OPENENDWINDOW`, `DF_OPENCONTINUEWINDOW`).
- **Py `talk(handle)`**: `ExecuteActionAt(protagonist, "Dialogue([-1])", target)` then wait for
  `GetDialogState()`.
- Verify the dev console still polls while a dialogue is open (`GemRB.SetTimer` callbacks vs.
  `DF_FREEZE_SCRIPTS`). `dev.ps1 py` already says it times out "in a modal"; if the timer stops
  in dialogue, move the poll to an engine-side hook that always runs (see 2.6).

### 2.3 "Wait until something happens"  (blocker)

Every action is asynchronous (walking, cutscenes, dialogue starting from a trigger, a fight
starting). Without a reliable wait the agent will spam actions.

- **Py/engine `wait_idle(timeout)`**: returns when the party has no queued actions, no
  cutscene, no narration, no pending dialogue start, no fight in progress — or when one of those
  starts (that's an event to report). Returns *why* it stopped.
- **Engine `GemRB.GetGameState()`**: one call with the mode flags: `InDialogue`, `InCutscene`
  (`GameControl::InCutSceneMode`), `InCombat` (turn order not None), `IsPaused`, `IsLoading`,
  `OpenWindow` (inventory/store/container/rest/level-up/death screen), `PartyBusy`
  (any PC with actions queued).
- **Engine event queue `GemRB.GetEvents()`** like `GetCombatEvents` but for the whole game:
  area changed, dialogue started/ended, journal entry added, item gained/lost, XP gained,
  level-up available, PC died/unconscious, global variable changed (optional, filterable),
  door/container opened, trap triggered, message-window lines (feedback text). The LLM needs
  this as its "what just happened" log.

### 2.4 Movement and interaction  (high)

- **Py `walk_to(handle | x,y)`**: `MoveToPoint`/`MoveToObject` on the selected party, then
  `wait_idle`. Report "can't reach" (path failure) instead of hanging; needs a check that
  pathfinding found a route (engine: expose `Movable::GetPath()` empty after a request).
- **Py `use(handle)`**: open door (`OpenDoor`), open container (`ShowContainer`-equivalent
  via GUI), use info point / travel region (`MoveToObject` then trigger), pick up ground item.
- **Py `travel(exit_handle)`** and `worldmap(dest)`.
- **Py `pick_lock / disarm / pickpocket / steal`** (PST has thieving): `PickLock`, `RemoveTraps`,
  `PickPockets` script actions.
- Locked door with key, "door needs a script" etc. come back as feedback text: needs the
  message-window lines in `GetEvents()` (2.3).

### 2.5 Party, inventory, character  (high)

Mostly exists; needs wrapping into compact tools and a few missing actions.

- **Py `party()`**: name, HP/max, level, class, XP, conditions, equipped weapon, gold.
- **Py `inventory(slot)`**, `equip(slot, item)`, `unequip`, `give(item, from, to)`,
  `drop`, `use_item(item, target)` (e.g. the PST tattoos, the journal, keys, quest items).
  Equip/move between slots needs a non-drag API: today it goes through `DragItem`/`DropDraggedItem`
  (GUI). **Engine `GemRB.MoveItem(pc, fromSlot, toPC, toSlot)`** that runs the same checks.
- **Level-up**: PST level-ups are automatic but stat points on level are chosen in the
  record screen (GUIREC). **Engine/Py `level_up(pc, choices)`** or "auto choose" toggle.
- **Rest**: `RestParty` exists → `rest()` tool; report "can't rest here".
- **Party join/leave**: comes via dialogue; `LeaveParty` for kicking.
- **Death screen**: PST the Nameless One "dies" and wakes in the Mortuary — check this is
  handled as a normal area change, and true game over is reported as an event.

### 2.6 Transport hardening  (high)

The file poll is fine for tests, not for thousands of agent steps.

- Keep the file IPC as the fallback; add a **localhost TCP/JSON-RPC socket** (Python `socket` in
  `DevConsole.py`, or engine side) with request IDs, so calls don't race and replies are
  structured JSON instead of printed text.
- Poll must run in every state: main menu, loading, dialogue, store, cutscene, death screen.
  Move it from a GUI timer to a per-frame engine hook if the timer stops anywhere.
- A **"fast mode"**: no movies (`SkipIntroVideos`, movie skip), max game speed, no
  wait for sounds/voice in dialogue, optional hidden window. Needed to make a full replay run in
  hours, not days.
- Movies block everything: **engine toggle to auto-skip movies** under the harness
  (`PlayMovie` returns at once).

### 2.7 Combat for the agent  (medium — party AI already covers it)

- Default: `Turn Based Party AI = 1`, the agent only sees a `combat_summary` event at the end.
- Optional manual mode tools: `combat_state()` (= `GetTurnOrder` + `GetTurnBudget`),
  `attack(handle)`, `cast(spell, handle)`, `move_turn(x,y)`, `end_turn()`. All exist as engine
  calls; only wrappers and handles are missing.
- If the party loses: reload last checkpoint, count it, don't loop forever.

### 2.8 Checkpoints and assertions  (needed for "completable")

- **Py `checkpoint(name)`**: `SaveGame` into a named slot; `restore(name)`.
- **Py `check(expr)`**: evaluate a game condition with the engine's own trigger parser
  (`GemRB.EvaluateString` exists — confirm it takes triggers like
  `Global("Morte_Joined","GLOBAL",1)`), plus `HasItem`, `InParty`, `AreaCheck`, journal entry.
- A run log (JSONL): every tool call, result, events, game time, area, wall time. Failures
  attach a screenshot, the last 100 log lines and the hang/crash file.

### 2.9 Data lookups the walkthrough author needs (offline, no game)

- **`tools/pst_dlg_dump.py`**: dump a DLG to text (states, options, triggers, actions) so
  walkthrough steps can name options by text and checks can name the variables they set.
- **`tools/pst_globals.py`**: list globals set by each DLG/BCS (which variable means "quest X
  done"). `tb_gamedata.py` already reads game data — extend it.
- Area/creature name index (scripting name ↔ display name ↔ area) for stable handles.

## 3. Tool surface for the LLM (target)

Keep it small; local models handle ~15 tools well, 40 badly. Every result is short text/JSON.

| Tool | Args | Returns |
|---|---|---|
| `look` | – | area, time, nearby objects with handles, exits |
| `state` | – | mode (explore/dialogue/combat/store/...), party summary, new events |
| `walk_to` | handle or x,y | arrived / blocked / interrupted-by-event |
| `talk` | handle | dialogue text + numbered options |
| `say` | option number | next dialogue text + options, or "dialogue ended" + events |
| `use` | handle | opened / locked / travelled / picked up / message |
| `travel` | exit handle or world-map destination | new area |
| `inventory` | party member | items with handles |
| `item` | action (equip/give/drop/use), item, target | result |
| `loot` | container handle, item or "all" | moved items |
| `shop` | buy/sell/list, item | result |
| `rest` | – | rested / can't |
| `combat` | `auto` or a manual sub-action | summary when the fight ends |
| `journal` | – | latest N entries |
| `checkpoint` / `restore` | name | ok |
| `wait` | seconds | events while waiting |

Replay-only (not for the model): `check`, `set_global`, `teleport` (`goto`), `give_item_cheat`.

## 4. Walkthrough format

Our own walkthrough, written as data in `dev/walkthrough/` (one YAML file per chapter/area
group), not copied text from published guides. Each step is something the replay runner can
execute and the LLM can read as a hint:

```yaml
chapter: mortuary
start_save: new_game          # or a named checkpoint
steps:
  - id: wake
    do: [{talk: Morte}, {say: "*first option*"}]   # option by number or by text match
    expect: Global("Morte_Mortuary_Walkthrough","GLOBAL",1)
  - id: scalpel
    do: [{walk_to: "<container>"}, {loot: ["<item>"]}]
    expect: PartyHasItem("<item>")
  - id: leave_mortuary
    do: [...]
    expect: AreaCheck("<area>")
    checkpoint: mortuary_done
```

- `expect` uses engine trigger syntax so the check is exactly what the game scripts see.
- Variable / item / area names come from the DLG/BCS dumps (2.9), not guessed.
- Each chapter starts from the previous chapter's checkpoint, so chapters run and fail
  independently ("unit tests" per chapter); a full run chains them.
- Cover at least one ending path end-to-end; add branches (alternate joins, alignment-locked
  options, Morte/Annah/Grace quests) as separate files once the main path passes.

## 5. Runners

- **`tools/llm/bridge.py`**: Python client for the socket (2.6) implementing every tool in
  section 3. Shared by both runners. Unit-tested against a fake game.
- **`tools/llm/replay.py chapter.yaml`**: runs steps, checks `expect`, retries a step once after
  `restore`, writes `dev/llm_runs/<date>/report.md` (pass/fail per step, failures with evidence).
  Exit code 1 on any failure, like `tb_autotest.ps1`.
- **`tools/llm/agent.py --model <ollama model> --chapter mortuary`**: loop: system prompt
  (rules of the tools, the chapter's walkthrough as hints, the goal = next `expect`), feed
  `state`+`look`, let the model call tools, stop at goal / step budget / stuck. Stuck detection:
  same area + no new events/variables for N calls → restore checkpoint, give a hint, count it.
  Summarise old turns to stay inside a small context (8–32k).
- **`tools/llm_run.ps1`**: start the game in fast mode, load save, run replay or agent, collect
  the report.

## 6. Milestones

| # | Work | Done when |
|---|---|---|
| L0 | `GetDialogState`/`DialogChoose`, `GetGameState`, poll works in dialogue | a script talks to Morte and picks options with no clicks |
| L1 | `GetAreaObjects` + `look()` with handles, `walk_to`/`use`/`loot` | a script walks the first Mortuary room and loots it |
| L2 | `GetEvents`, `wait_idle`, socket transport, fast mode, movie skip | 500 tool calls in a row without a timeout or race |
| L3 | `MoveItem`, inventory/equip/give, rest, travel/world map, level-up choice | every tool in section 3 works by hand from `bridge.py` |
| L4 | DLG/globals dump tools, Mortuary walkthrough YAML, `replay.py` | Mortuary replays start→exit, green, repeatable |
| L5 | Walkthrough for the main path, chapter by chapter | full main-path replay reaches an ending |
| L6 | `agent.py` with a local model on the Mortuary, then further | model clears the Mortuary with the walkthrough as hints; report lists where it got stuck |

Each engine call gets a toggle-free unit test where possible (dialogue choose on a test DLG) and
a line in `tools/dev_settings.ini` only if it changes play (fast mode, movie skip).

## 7. Risks / open questions

- Does the GUI timer run during dialogue, store and death screen? (decides 2.6 scope)
- `EvaluateString` semantics (trigger vs. action string) — check before building `check`.
- PST dialogue options sometimes hide behind stat checks (INT/WIS/CHA); the replay needs a
  fixed character build (set stats at the start, recorded in the walkthrough).
- Random encounters and combat outcomes: fix the RNG seed in harness mode, or accept retries.
- Small local models lose the plot in PST's long dialogues: keep dialogue history to the current
  conversation plus the journal, not the whole transcript.
- Some quest steps need real-time waiting (time-of-day NPCs): `wait` must advance game time
  quickly (rest or a time skip action).
