# A6/A7: the dialogue engine and the dialogue text parser (round 12, 2026-11-19), judged against PST:EE

EE: `CGameDialogSprite` (`StartDialog`, `EnterDialog`, `Load` → `sub_B35BC0` builds the state and reply lists),
`CGameDialogEntry::Display` (which replies show), `CGameDialogReply::Hold` / `Pick` / `ProcessInstants`,
`CGameSprite::Dialogue` (the `Dialogue`/`StartDialog` actions, talk counts). GemRB: `core/DialogHandler.cpp`,
`core/Dialog.cpp`, `plugins/DLGImporter/DLGImporter.cpp`.

## A6: the dialogue engine

### D-1 Which state starts a dialogue (P)
- EE `sub_B35BC0`: the start list holds the states that have a state trigger, sorted by **ascending trigger index**
  (states without one get `False()`); `CGameDialogSprite::StartDialog` takes the **first** whose condition holds
  (`CAICondition::Hold`). None true → the creature plays its default dialogue sound (`SOUND_DEFAULT_DIALOG`) and no
  dialogue opens.
- GemRB `DLGImporter` fills `Order[TriggerIndex] = state`; `Dialog::FindFirstState` walks `Order` and returns the
  first true. Same.

### D-2 Talk count (P)
- EE `CGameSprite::Dialogue:203-238`: when a dialogue starts, each participant that is not `EA_PC` (and not in the
  0x2000 state) gets its talk count (`+3608` dword, read by `NumTimesTalkedTo*`) raised by one, through a message
  that runs after the dialogue's start state was chosen (the first talk sees `NumTimesTalkedTo(0)`).
- GemRB `DialogHandler::DialogChooseInitial`: `TalkCount++` on the dialogue owner after the top-level state is
  chosen. Same for NPC↔PC dialogues; for an NPC↔NPC dialogue EE raises both counts, GemRB one (no PST case known).

### D-3 Reply actions (P)
- EE `CGameDialogReply::Pick`: a reply's actions (parsed from text on first use) are queued on the speaker
  wrapped in `SetInterrupt(FALSE)` … `SetInterrupt(TRUE)`, sent as a message (run after the click, not
  immediately); journal flags (0x10 with 0x40/0x80/0x100 sections) add the entry.
- GemRB `DialogHandler::DialogChoose`: same wrap (`SetInterrupt(FALSE)`, `BreakInstants`, actions,
  `SetInterrupt(TRUE)`), journal via `UpdateJournalForTransition`. P.
- PST only, presentation: EE plays a random talk animation (sequence 20-22) on the speaker at each pick unless it
  is in state 5 or 66. GemRB: not checked (sev 3).

### D-4 Which replies show, and "continue" links (S)
- EE `CGameDialogEntry::Display`: walks the reply array in index order: a pass for replies with flag 0x20,
  then all replies whose `CGameDialogReply::Hold` is true; with no visible reply it falls back to text-less links;
  nothing at all → "NO VALID REPLIES OR LINKS".
- GemRB `GetDialogOptions`: walks transitions from the **last** to the first; the first true text-less transition
  met (i.e. the highest index) becomes the continue link and stops the walk.
- **Open:** whether `sub_B35BC0` stores replies reversed (then EE also prefers the highest index). It decides which
  link wins when a state has several true text-less transitions. Blocked on reading `sub_B35BC0`'s reply loop
  (`dumps.py lines ee sub_B35BC0 260 380`).

### Other A6 items
- Tokens: EE `CScreenWorld::SetDialogTokens`; GemRB `Interface::GetString` token substitution. Not compared (sev 3).
- Dialogue with hostile/sleeping/far creatures, `StartDialogNoSet`, `Dialogue` range: action rows in A1 (P/V
  there), `NearbyDialog` T1 (fixed).
- `Dialogue` held during fades: A6 note from round 8 (A-204).

## A7: the text parser ("Parsing")

Strings: 5,637 distinct trigger texts and 4,011 action texts in the 814 DLG files GemRB loads (dumped to
`.re/notes/dlg_triggers.txt` / `dlg_actions.txt`).

### D-5 Whitespace (P)
- EE `CAIScriptFile::ParseOneLine` and the response-line parser (`sub_B0B1F0`) call `CAIUtil::RemoveAllWS` on the
  line before parsing: **every** space goes, inside quotes too. GemRB `DLGImporter` `GetStrings` drops every
  whitespace character the same way. So the 9 variable names with stray edge spaces (`"Pillar "`, `" Know_Sigil"`,
  `"Porphiron "`, `"Jumble "`, `"CW_Statue_Cursed "`, `"PC_Annah_Stealth "`; round 8 note) mean the plain variable in
  both engines. No DLG string literal has an interior space.

### D-6 Statements run together (P, checked on every string)
- EE parses **one statement per line** (no loop in `sub_B0B1F0`); Beamdog rewrote its own DLG files so each
  statement has its own line (the original data has 905 action strings with statements glued together, EE none).
- GemRB keeps the original data and splits by top-level parentheses (`GetStrings`, with special cases for
  `13.,` in DMEBBETH and the `;` in D300MER8).
- **Check:** `python tools/parity/dlgsplit.py` replays GemRB's splitter on every original string and compares it
  with EE's rewritten string at the same index: 4,426 action, 9,159 transition-trigger and 2,211 state-trigger
  strings split identically; **0 strings differ only in splitting**. Every remaining difference is content Beamdog
  changed (below).

### D-7 Names and IDS symbols (P)
- Every function name in the DLG texts exists in PST's `action.ids`/`trigger.ids` (0 unknown); the 2 lower-case
  names (`false()`, `enemy()`) are matched case-insensitively by both. Every symbolic integer argument resolves
  in the IDS file the signature names (`WPROF`, `ANIMSTAT`, `STATS`, … ; 0 unresolved). Negative numbers (626),
  points `[x.y]` (51), object brackets `[PC]` (14) are forms GemRB's `ParseText.cpp` reads.
- Not covered statically: GemRB's per-parameter parsing in `GenerateActionCore`/`GenerateTriggerCore` on each of the
  ~9,600 strings. A run-time harness (compile every string with GemRB, log `Invalid`/`Malformed scripting` errors)
  would close that; the splitting, names and symbols above remove most of the risk.

### D-8 EE rewrote the dialogue data (decision for the owner)
- With EE as the truth, its **data** differs too: 2,294 action, 248 transition-trigger and 60 state-trigger strings
  have different content, and 315 files have a different number of strings (`dlgsplit.py`, full list
  `.re/notes/dlg_ee_rewrites.txt`). Kinds: EE action/trigger names (`SetPortalCursor` for
  `ActivatePortalCursor`/`EnablePortalTravel`, `NumInParty` for `PartyCount`, `GlobalLT("BD_DAKKON_MORALE")` for
  `MoraleLT("Dakkon")`, OR() blocks for `GlobalOrGlobal`), engine-side additions (`ClearActions(Player1-6)` before
  cutscenes, `StartCutSceneEx`), and **quest fixes** (DADMINAS drops `Roberta_Betrayed`, DAETHEL drops the
  `2Devils` check, D0202P uses `Deionarra_Death_Truth`, DAGRIL adds a `SinisterPoof`).
- GemRB loads the original files. Following EE here means porting Beamdog's content fixes (PARITY_PLAN phase 7,
  "EE data fixes") as an optional data pack; the name rewrites need no port (GemRB runs the original names).
