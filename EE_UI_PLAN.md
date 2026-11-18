# Enhanced Edition UI for classic PST (GemRB fork): plan

Goal: rebuild this fork's UI on top of Planescape: Torment Enhanced Edition's interface. Use EE's
art (4K backgrounds, remade buttons, spell icons, area maps) and EE's screen layouts wherever they
fit, while the game itself stays classic PST: classic data, classic rules, GemRB's Python screen
logic. This is a big refactor on purpose. Classic CHU windows stay as the fallback for any screen
that has not been moved yet, and for anyone without an EE install.

Read `CLAUDE.md` first.
Their rules apply to every phase: build and install after each engine change, check the result in
game with `tools\dev.ps1`, report what was seen in game versus only compiled.

---

## 0. Decisions already made (do not change them)

- **Classic game, EE look.** `GamePath` stays the classic install
  (`C:\Program Files (x86)\Black Isle\Torment\`). The EE install
  (`D:\GOG Games\Planescape Torment - Enhanced Edition\`) is read only by our tools, never mounted
  as game data. Never merge EE's `chitin.key`: it would replace classic CREs, BAMs and scripts.
- **No EE files in git.** EE art, PVRZ pages, generated layouts and derived PNGs go to
  `D:\Games\GemRB\ee_ui\` and `D:\Games\GemRB\upscaled\`. Only our tools, engine code, Python and
  small tables we wrote go into the repo. Never write into Program Files or the GOG folder.
- **Fonts stay the classic bitmap fonts.** The owner tried EE's Exocet and rejected it. Do not load
  any EE TTF. EE text styles map to FONTDLG / TRMTFONT / EXOFONT through a table (section 5).
- **Logical resolution stays 1280×720** (`Width`/`Height` in `GemRB.cfg`). EE's UI is laid out in a
  1366×768 space with 3840×2160 art. Mapping: **layout scale `s = 720 / 768 = 0.9375`**, **art scale
  `k = 2160 / 720 = 3`**. A 3840×2160 EE background is exactly 3× a 1280×720 logical sprite, so it
  rides the existing hi-res twin system with an integer scale. Also support logical 1920×1080
  (`s = 1.40625`, `k = 2`). Refuse other heights with a clear error. Do not stretch 4:3 art to 16:9.
- **GemRB decides what, EE decides where.** Screen behaviour stays in GemRB's Python
  (`gemrb/GUIScripts/pst/*.py`): same functions, same strrefs, same script-visible effects. EE's
  Lua (`UI.menu` actions, `BGEE.lua`) is a reference for layout and intent only. Do not write a Lua
  interpreter or an Infinity UI runtime.
- **Only controls that have a classic function.** An EE control goes in when GemRB already has the
  behaviour (New Life, Load, Quit, stat +/-, ...). EE-only features stay out unless the owner says
  otherwise: cloud saves, cheat console, achievements, tablet layouts, quick loot, combat log,
  difficulty screen, "Continue" on the start screen, Options on the start screen. List them in the
  phase report so the owner can pick.
- **Turn-based first.** The world HUD (EE action bar, side bars, radial wedges) is the last phase
  and needs the owner's go-ahead (section 9). Nothing before it may change `GUIWORLD.py`,
  `FloatMenuWindow.py`, `PortraitWindow.py`, `TurnOrder.py` or `TurnBasedCombat/CombatHud.*`
  behaviour.
- **One toggle.** `EEUI=1` in `GemRB.cfg` (its "on" line goes in `tools/dev_settings.ini`). Off,
  or `ee_ui\` missing, means every screen uses the classic CHU path, exactly as today.

---

## 1. What EE has (verified 2026-11-14)

Numbers come from `tools/upscale/work/ee_inventory.py` and `ee_inventory2.py` (prototypes; phase 1
moves them into `tools/eeui/`). Their reports are `tools/upscale/work/ee-extract/inventory.txt` and
`inventory2.txt`; read them before starting.

| Kind | What EE has | Use |
|---|---|---|
| Screen backgrounds | 14 full-screen MOS V2 plates at 3840×2160: STARTBG, CGBACK, INVBG, RECBG, MGBG, JRNBG, LOADBG, OPTBG, STRBG, STRBG2, MAPBG, WIRESBG, BEASTBG, WELCSCRN | Yes: drawn behind EE-layout screens |
| Popups and bars | ~60 MOS V2: POPUP1-7, OPTPOP1-4, DIABG/CONVWING (dialog), CONBG/CONWINGL/R (container), MAINBG/MAINWING/ACTBG (HUD), LOADROWB/C, STRROW, ABLROW, ICGOLD, ICHPBG, ICMAGE, ICPRIEST, VERPLATE, ... | Yes, per screen |
| Paper dolls | IVPNO*/IVP* MOS V2 701×956 and 581×790 (classic: BMP 139×185) | Yes in EE inventory; twin for classic only after an owner look (aspect differs 2.4%) |
| Bestiary pictures | 87 JR*KN + DEFAULT, MOS V2 1124×1764 = exactly 4× the classic 281×441 BMPs in `jrnlpic.bif`, same paintings remastered | Yes: phase 2g (twins). Today none of them has a twin at all |
| Bestiary data and rules | `bestiary` table in `BGEE.lua`, journal BESTIARY mode in `UI.menu`, BEASTBG plate | Rules yes (phase 2h); data no, classic `beast.ini` is the fuller one (see 5.1) |
| New buttons | 88 EE-only BAM V2: STARTBUT, NORMBUTT, WIDEBUTT, SMLBUTT, XBUTT, POPUPIMG, CGATTR, CGACCEPT, SLOT*, TAB*, FOOT*, FORM*, RADWEDGE, CIRCBUTT, ... | Yes, per screen |
| Remade classic BAMs | 26 same-name BAM V2 at 4-10× size: IVSLOT, IVPI* (paper-doll slots), CGPLUS, CGMINUS, CGCANCEL, CGSCRL1, STALIGN, STFCTION, WMLOCAT, WMPICKL, WMTIME, WMCHRH, FILLBAR | In EE screens via aliases; as twins only when frame count and aspect match |
| Spell icons | 104 SP### BAM V2 at 256×256 (classic 32×32, same 2 frames) | Yes: drop-in 8× twins (phase 2) |
| Item icons | 475 of 480 identical to classic | No |
| Area maps | ~120 AR*.mos MOS V1 at up to 800×600 (classic 60×48 to 480×360, same aspect) | Yes: twins now, native in the EE map screen later |
| World map | WMWRLDB MOS V2 1920×1280 (classic 960×640, exactly 2×) | Yes: drop-in 2× twin (phase 2) |
| Cursors | CURS2X BAM V1, 2.5× classic, 50 frames in the same 54 cycles | Optional (phase 2e) |
| CHU files | 17 of 18 byte-identical to classic. GUIREC is a different 1024×768 pack EE does not seem to use | No: layouts come from `UI.menu` |
| Layouts | `UI.menu`: 94 menus (areas, bams, sequences, mosaics, styles, tooltips, hit polygons) | Yes: converted to JSON (phase 4) |
| Strings | `L_EN_US.lua` `uiStrings`: 344 keys → strrefs. 183 match the classic `dialog.tlk`, 106 differ, 55 are past its end | Converter rule in section 5 |
| Text styles | `BGEE.lua` `styles` (normal, title, label, button, list, gold, *_parchment) with colour letters in `fontcolors[]` | Colours yes, fonts no |
| Fonts | EXOCET, BOOKMANI, NANUM TTF. FONTDLG etc. identical to classic | No (decision above) |
| Movies | 33 WebM at 960×480 / 640×480 (classic MVE 640×480) | No: GemRB has no WebM decoder. Ask the owner before any work |
| Shaders | 40 GLSL/DX shaders for EE's renderer | No |

How EE draws a screen (verified on the start menu, see
`tools/upscale/work/ee-extract/STARTBG_boxes.png`): a `BACKGROUND_*` menu paints a 1366×768 plate
`align center center`; the screen menu on top has a 1024×768 bounding box, also centred. Button art
is drawn at `art_pixels / 2.8125` EE units (NORMBUTT 395×161 px in a 138×56 area). EE's START_MAIN
button boxes, centred this way, land exactly on the arcs of STARTBG. Classic START's buttons do not.

---

## 2. Engine facts the plan relies on (verified)

- `BAMImporter` loads BAM V2 (`GetV2Frame`, PVRZ pages `mos{:04d}`); `MOSImporter::GetSprite2Dv2`
  loads MOS V2; `PVRZImporter` decodes DXT1/DXT5. These produce full-resolution RGBA sprites.
- Hi-res twins: `Sprite2D::hiRes`, attached by `HiResArt::Attach` (`gemrb/core/HiResArt.cpp`).
  `ScaleOk` and `GLVideoDriver::PrepareSprite` (`plugins/GLVideo/GLVideo.cpp` ~line 799) accept
  only an integer scale ≥ 2, equal on both axes. BAM twins are looked up as
  `upscaled/gui/bam/{STEM}/{frameIndex}.png`, MOS twins as `upscaled/gui/mos/{STEM}.png`.
- `MapControl` (`gemrb/core/GUI/MapControl.cpp`) converts between map and game coordinates through
  `mosRgn` size, so a bigger small-map sprite keeps markers and notes in place.
- Python can build windows without CHU: `GemRB.CreateWindow`, `Window.CreateButton`,
  `CreateLabel`, `CreateTextArea`, `CreateMapControl`, `CreateWorldMapControl`, `CreateScrollBar`,
  `Button.SetSprites`, `Button.SetPicture` (`gemrb/GUIScripts/GUIClasses.py`).
- Classic PST screen scripts: `Start.py`, `NewLife.py` (chargen), `GUILOAD.py`, `GUISAVE.py`,
  `GUIOPT.py`, `GUIINV.py`, `GUIREC.py`, `GUIMG.py`, `GUIPR.py`, `GUIJRNL.py`, `GUIMA.py`
  (area and world map), `GUIWORLD.py` (dialog, container, stores live near here; check),
  `MessageWindow.py`, `PortraitWindow.py`, `FloatMenuWindow.py`, `QuitGame.py`, `LoadScreen.py`.
- `Interface.cpp` ~line 339 shows how `ModPath` directories become resource sources. Copy that
  for `EEUIPath`.

---

## 3. Phase 0: clean up the font experiment

1. `gemrb/core/Interface.cpp` `LoadFonts`: remove the "EXOCET.ttf is optional" fallback block. It
   is dead now that `fonts.2da` names only BAMs.
2. Delete `D:\Games\GemRB\override\pst\EXOCET.ttf`.
3. Keep the `Font.cpp` change (NEAREST only when the sheet has a hi-res twin); it is correct.
4. Build, run `Test_gemrb_core --gtest_filter=FontHiRes*`, start the game, confirm the log shows
   `Loaded Font: FONTDLG for ResRef FONTDLG`.

## 4. Phase 1: `tools/eeui/` (the EE reader)

Move the working prototypes out of `tools/upscale/work/` into a real tool. Reuse
`tools/upscale/ie_formats.py` for KEY/BIF; do not copy it.

- `tools/eeui/ee_data.py`: open the EE install by `chitin.key`; read any resource by name and
  type, including types 0x0404 PVRZ, 0x0408 MENU, 0x0409 LUA (the type map in
  `work/ee_pull.py` is the correct one; `ee_gui_survey.py`'s is wrong). PVRZ blobs start with a
  dword size, then zlib (`78 9c`), then a PVR3 header (52 bytes plus metadata); formats 7 (DXT1)
  and 11 (DXT5).
- `tools/eeui/pvrz.py`: full DXT1/DXT5 decode with numpy (vectorised, not per-pixel Python). The
  prototype in `work/ee_plate.py` only reads the first colour of each block; replace that.
- `tools/eeui/decode.py`: MOS V2 → RGBA array (compose blocks from pages), BAM V2 → frames with
  their centre offsets and cycle table, MOS V1/BAM V1 via `tools/upscale/extract.py`.
- `tools/eeui/inventory.py`: the inventory report (from `work/ee_inventory.py` and
  `ee_inventory2.py`), writing `D:\Games\GemRB\ee_ui\inventory.txt`.
- `tools/eeui/run_eeui.bat`: `python tools\eeui\build.py --ee "<EE path>" --out D:\Games\GemRB`.

Check: decode STARTBG and CGBACK to PNG and compare them with
`work/ee-extract/STARTBG_preview.png` / `CGBACK_preview.png` (same picture, now full detail).
Decode NORMBUTT, STARTBUT and SP001 frames to PNG and look at them.

## 5. Phase 2: drop-in twins (classic layouts, no engine change)

These improve today's classic screens straight away. All output goes to the existing hi-res tree,
and every file written is listed in `D:\Games\GemRB\upscaled\ee_twins.txt` (one relative path per
line). Change `tools/upscale/upscale.py` to skip any resource whose twin path is in that list,
including with `--force`, so the ESRGAN run never overwrites EE art.

Rule for every twin: equal frame count; each frame's aspect within 1.5% of the classic frame;
resize the EE frame with Pillow Lanczos to exactly `classic_size × n`, where
`n = max(2, round(ee_w / classic_w))`; keep the frame's position (BAM centre) by scaling it the
same way. Skip and log anything that fails the rule; never pad or crop to force a fit.

- **2a. Spell icons:** SP### (104) → `upscaled/gui/bam/SP###/{i}.png` (`n = 8`, no resize).
  Check: open the mage spell book in game, screenshot, icons are sharp and in the same place.
- **2b. World map:** WMWRLDB (MOS V2 1920×1280) → `upscaled/gui/mos/WMWRLDB.png`. First confirm
  the classic world map (`worldmap.wmp`) really uses WMWRLDB. Check: open the world map, screenshot.
- **2c. Area maps:** every AR*.mos where EE is bigger and the aspect rule passes →
  `upscaled/gui/mos/AR####.png`. Check: open the area map in the Mortuary (AR0200 range) and in the
  Hive; party markers must sit where the party is (compare the marker with the game view).
- **2d. Remade BAMs with the same layout:** apply the rule to the 26 remakes. Expect it to pass for
  STALIGN, STFCTION, WMPICKL, CGSCRL1, FILLBAR and fail for IVSLOT (40 vs 4 frames), WMLOCAT,
  WMTIME, CGPLUS, CGMINUS, CGCANCEL. The report lists which passed. Check each passed one on its
  screen.
- **2e. Cursors (optional, do last):** CURS2X as twins for CURSORS, mapped by cycle (the frame
  numbers differ). The logical size and hot spot stay classic. Skip if any cycle's aspect fails.
- **2f. Paper dolls:** do not ship. Write side-by-side PNGs (classic BMP / EE MOS resized) to
  `ee_ui/review/` and list them in the report for the owner.
- **2g. Bestiary pictures:** see 5.1.
- **2h. Bestiary behaviour in `GUIJRNL.py`:** see 5.1. This is ours, needs no EE file, and is
  committed with the rest of the code.

### 5.1 The bestiary (everything classic is missing)

Facts (checked 2026-11-14, scripts `work/ee_beasts.py`, `ee_bestiary_diff.py`,
`ee_beast_pics.py`, `ee_beast_compare.py`; sheet `work/ee-extract/beast_compare.png`):

- EE has no `beast.ini`. Its data is the `bestiary` table in `BGEE.lua` (same fields: `index`,
  `name`, `desc0..2`, `global`, `class`, `killvar`, `imageKnown`), plus a placeholder entry.
- Classic `beast.ini` (with Fixpack/UB) is the fuller list: 89 entries against EE's 88. EE lacks
  Alu-fiend (#88, UB) and has Giant Skeleton only once. Classic has 14 entries with story text
  (`global` + `desc1`/`desc2`), EE only 3 (Deionarra, Morte, Transcendent One). **Keep classic
  `beast.ini` as the only data source. Do not import EE's table.**
- Story text, as EE reads it (`getBestiaryDesc` in `UI.menu`): when an entry has `global`, the
  text is `desc<value of that global>`. Classic entries using it: Annah, Dak'kon, Deionarra,
  Dhall, Dustman (male and female), Fall-From-Grace, Ignus, Lothar (`Know_Ravel`), Morte,
  Nordom, Transcendent One, Trias (`Talk_To_Betrayer`), Vhailor. **Our `GUIJRNL.py` always shows
  `desc0`, so 14 classic strings (64131, 64143, 3525, 3528, 3527, 64144, 64196, 64197, 3526,
  64198, 64200, 31789, 64207, 64199) are never shown.** All are in classic `dialog.tlk`.
- Placeholder: when a list has nothing known, EE shows "No Known Creatures" (strref 3594) with
  text 3595 and the DEFAULT picture. Ours shows an empty list.
- Order: EE sorts entries by name (`sortBestiary`). Ours sorts by index, so the list is not
  alphabetical.
- Known/unknown and kill counts already work in GemRB (`Game::SetBeastKnown` from `Map.cpp`,
  `IncrementKillStat` reads `killvar`). Nothing to do there.
- Pictures: 87 of the 88 distinct `imageKnown` names plus DEFAULT exist in EE as MOS V2
  1124×1764 (4× classic). Missing in EE: JRALUKN (Alu-fiend, UB override BMP). `imageUnknown`
  (IMAGE, Gronk1) is used by neither engine; ignore it. JRSHTKN exists in both games but no
  entry uses it; do not add an entry for it.
- **Why there are no bestiary twins today:** `tools/upscale/classify.py` only queues BMPs named
  by portraits or scripts. The bestiary names live in `beast.ini`, so the ESRGAN run skipped all
  of them (only DEFAULT has a twin, from another reference).
- Classic BMPs mark the rounded corners with the transparent key colour; EE's MOS has dark
  corners there.

2g. Pictures (twins, classic layout):

1. In `tools/upscale/classify.py`, add every `imageKnown` name from `beast.ini` (game root, then
   override) to `gui_bmps`. Run the ESRGAN pipeline for those only; JRALUKN must come out of it.
2. `tools/eeui/twins.py` (phase 2 tool): for each `beast.ini` `imageKnown` name plus DEFAULT that
   EE has as MOS, decode the full 1124×1764 MOS, resize with Lanczos to exactly classic size × 4
   (DEFAULT is 281×440 in classic, so 1124×1760), take alpha from the classic BMP as
   `extract.decode_bmp` gives it (nearest-neighbour ×4), and write
   `upscaled/gui/bmp/<NAME>.png`. Add each path to `ee_twins.txt`, so it replaces the ESRGAN
   DEFAULT twin and is never overwritten.
3. Check in game: open the journal bestiary on a save that knows Morte, Annah and several
   monsters (staged with `GemRB.ExecuteActionAt`/game vars if needed). Screenshot. Pictures must
   be sharp at 2560×1440, in the same place, corners transparent. Select Alu-fiend (set it
   known) and confirm its ESRGAN twin shows. If a 4× twin shimmers before phase 3 mipmaps exist,
   note it in Progress and keep going.

2h. Behaviour (`gemrb/GUIScripts/pst/GUIJRNL.py`):

1. Description: when the entry has `global`, read `v = GemRB.GetGameVar(global)` and use the
   highest `desc<n>` key with `n <= v` (falls back to `desc0`). This matches EE for every value
   EE handles and never shows an empty text.
2. Sort each class list by the displayed name (`GemRB.GetString(name)`), case-insensitive.
3. When a class list is empty, show one row with strref 3594, text 3595 and picture DEFAULT.
   Selecting it does nothing else.
4. Check in game: Morte's text with `Morte` at 0 and at 1 (`act('SetGlobal("Morte","GLOBAL",1)')`), list in
   alphabetical order, the NPC list on a fresh Mortuary save showing the placeholder. Repeat with
   `EEUI=0` (2h does not depend on EEUI).

## 6. Phase 3: engine support for EE-layout screens

Every change behind `EEUI`. Add unit tests in `gemrb/tests/core/` next to `Test_FontHiRes.cpp`.

1. **Config.** `EEUI` (int, default 0) and `EEUIPath` (default `<GemRBPath>/ee_ui`) read in
   `InterfaceConfig.cpp` like the other keys; add `EEUI=1` to `tools/dev_settings.ini`. When on and
   the folder exists, register it as a directory resource source after the GemRB override (copy
   the `ModPath` code in `Interface.cpp`).
2. **Art scale for V2 art.** New helper `HiResArt::FromFullRes(Holder<Sprite2D> full, int k)` in
   `gemrb/core/HiResArt.cpp`. It pads the full sprite with transparent pixels on the right and
   bottom up to a multiple of `k`, builds the logical sprite by a `k×k` box filter with
   premultiplied alpha, and attaches the padded full sprite as `hiRes`. `k` comes from the
   logical height (720 → 3, 1080 → 2). Call it from `BAMImporter::GetV2Frame` (BAM centre offsets
   divided by `k`, rounded) and `MOSImporter::GetSprite2Dv2`, only when `EEUI` is on. Classic data
   has no V2 files, so classic art never takes this path. `AttachBamFrame` must not replace a twin
   that is already set.
3. **Mipmaps for big RGBA twins.** In `plugins/GLVideo/GLSprite2D.cpp`, RGBA textures used as
   twins get `glGenerateMipmap` and `GL_LINEAR_MIPMAP_LINEAR`. Without it a 3× texture drawn at
   the owner's 2× window shimmers. Indexed twins (fonts, classic GUI) stay as they are.
4. **Button hit polygons.** EE buttons overlap (the start-menu arcs) and come with
   `boundingPoints`. Add `Button.SetHitPolygon([(x, y), ...])` (logical coordinates relative to the
   button) to `GUIScript.cpp` / `GUIClasses.py`; `Button::HitTest` uses it when set. First read
   `Button::HitTest`: if it already tests the picture's alpha and that is enough for STARTBUT,
   say so in the report and skip the polygon.
5. **Map image fit.** `MapControl` draws the small map at its own size. Add a fit mode (Python
   `MapControl.SetFit(True)`) that scales `mosRgn` to the control, keeping aspect, and blits the
   sprite to that region. The coordinate functions already use `mosRgn`.
6. **Tests:** `FromFullRes` on a 7×5 sprite with k=3 (logical 3×2, twin 9×6, padding transparent,
   alpha averaged); BAM offset rounding; a twin with k=3 passes `ScaleOk`; hit polygon inside and
   outside; map fit keeps `ConvertPointToGame(ConvertPointFromGame(p)) ≈ p`.

Check in game: with `EEUI=1` nothing visible changes yet (no screen uses it). Run
`tools\tb_autotest.ps1`; it must stay green.

## 7. Phase 4: the converter (`tools/eeui/build.py`)

Generates everything EE screens need into `D:\Games\GemRB\ee_ui\`:

- **Art.** Every MOS/BAM referenced by `UI.menu` (except `lua`, which means set at run time), the
  plates in section 1, the paper dolls, and the JR*KN pictures, copied byte for byte with their
  PVRZ pages (`MOS####.pvrz`). Plus extra names listed in `tools/eeui/extra_art.txt`, which
  must at least hold the art `UI.menu` only names through Lua: BEASTBG and JRNBG (journal
  background by mode), DEFAULT and every JR*KN (bestiary picture by entry), save portraits.
- **Bestiary report.** `ee_ui/review/bestiary.txt`: per classic `beast.ini` entry, its name, EE
  picture yes/no, twin source (EE or ESRGAN), and whether EE's `bestiary` table has the same
  `name`/`desc*`/`global`. Any new difference from 5.1 goes to the owner.
- **Aliases.** A copied name that already exists in classic data, in `gemrb/override` or in
  `gemrb/unhardcoded` (IVSLOT, CGPLUS, SP###, ...) is saved as `EU` + a 4-digit number + an
  extension, such as `EU0001.bam`. Aliases are listed in `ee_ui/aliases.txt` (`EE_NAME ALIAS`).
  Layout files only ever name aliases or unique names, so a classic screen can never pick up an
  EE file by accident.
- **Layouts.** One JSON file per menu, `ee_ui/layout/<MENU>.json`. For each control: `type`
  (button, label, text, list, edit, slider, scrollbar, map, progressbar), `name`, logical `frame`,
  `bam` + `sequence` + `frame`, `mosaic`, `style`, `text`, `tooltip`, `hit` (scaled
  `boundingPoints`), and the raw `enabled` / `clickable` / `action` strings for reference.
  Coordinates: take the menu's bounding box over all `area`s, place it in 1366×768 by its
  `align` (left/center/right, top/center/bottom), then multiply by `s` and round. Background
  menus place their 1366×768 label the same way, so the plate covers the 1280×720 screen.
- **Strings.** A `text` / `tooltip` key looked up in `uiStrings` becomes `{"strref": N}` when the
  classic `dialog.tlk` has the same text at N (case and surrounding spaces ignored). Otherwise
  it becomes `{"text": "..."}` from the EE `lang\en_US\dialog.tlk`. Literal strings stay literal.
- **Styles.** `ee_ui/styles.json`: each `BGEE.lua` style's colour (resolved through
  `fontcolors[]`), point size and alignment.
- **Previews.** For every layout, `ee_ui/previews/<MENU>.png` at 1280×720: plate, then each
  control's art at its frame, plus a thin outline and the control name. This is how layouts are
  checked before any Python is written.

Check: run it, read the summary (menus, files, aliases, missing names), open
`previews/START_MAIN.png` and `previews/CHARGEN.png` and compare them with the owner's EE
screenshots (main menu and character generation, in the chat that wrote this plan). Buttons must
sit on the arcs and stat boxes on the wheel.

## 8. Phase 5: the Python layout runtime

- `gemrb/GUIScripts/pst/EEUI.py`:
  - `Available(menu)`: `EEUI` on and `ee_ui/layout/<menu>.json` present.
  - `Build(menu, windowId, plate=None)`: creates a 1280×720 window (plate as its background when
    given) and the controls from JSON; returns `(window, controls)` with controls keyed by EE
    `name`, plus unnamed ones by index.
  - Fonts and colours from `gemrb/unhardcoded/pst/eeuifont.2da` (new, committed, ours): one row
    per EE style, with columns FONT and COLOR. Default fonts: `title` and any style at 22 pt or
    more → EXOFONT; `button`, `label`, `label_parchment`, `list*` → FONTDLG; `normal*`, `parchment`,
    `edit*`, `white_parchment` → TRMTFONT; `gold` → NUMBER2 if it reads well, else FONTDLG.
    Colours come from `styles.json`.
- Each classic screen script splits its window code into `BuildClassic()` and `BuildEE()`. Both
  return the same named handles (for example `new`, `load`, `quit`), and one `Wire(handles)`
  attaches the existing classic logic. If `EEUI.Available(...)` is false, use `BuildClassic()`.
  Never fork the logic.

## 9. Phases 6-18: screens, one at a time

For each screen: build it, then in game check the layout against its preview, every button,
every cancel path (Escape, right click, pressing the same button again), and opening and closing
it twice. Turn `EEUI=0` and confirm the classic screen still works. Run `tools\tb_autotest.ps1`
after any screen that opens in game. Update section 11.

| Phase | Screen (classic script) | EE menus | Plate | Notes |
|---|---|---|---|---|
| 6 | Main menu (`Start.py`) | START_MAIN | STARTBG | STARTBUT seq 0 = New Life, seq 4 = Load (classic "Resume Life"), seq 5 = Quit. Keep `AutoLoad` and the version label (on VERPLATE). Continue (seq 1) and Options (seq 2) stay out by default |
| 7 | Popups (`Start.py` `QuitPress`, `NewLife.py`, `QuitGame.py`, and every other `GPMOS8`/`GPMOS9` confirm box; grep for them) | QuitMenu, POPUP_INFO, POPUP_TWOBUTTON, POPUP_THREEBUTTON | POPUP2 | One shared helper; later screens use it |
| 8 | Character generation (`NewLife.py`) | CHARGEN | CGBACK | Stat wheel, points, AC, HP, Accept/Cancel (CGACCEPT/CGCANCEL), portrait in the centre hole |
| 9 | Load / save (`GUILOAD.py`, `GUISAVE.py`) | LOAD, SAVE, SAVE_NEWSAVE | LOADBG | Save screenshots and portraits are set by script (`lua` mosaics) |
| 10 | Options (`GUIOPT.py`) | ESC_MENU, OPTIONS_* | OPTBG, OPTPOP1-4 | Keep GemRB's option set; EE sliders and checkboxes are only the look |
| 11 | Inventory (`GUIINV.py`) | INVENTORY, ITEM_DESCRIPTION, ITEM_ABILITIES, ITEM_IDENTIFY | INVBG | IVSLOT/IVPI* remakes via aliases; paper dolls IVPNO*/IVP* |
| 12 | Character record (`GUIREC.py`) | CHARACTER, CHARACTER_BIOGRAPHY, CHARACTER_INFORMATION | RECBG | STALIGN/STFCTION remakes |
| 13 | Spells (`GUIMG.py`, `GUIPR.py`) | SPELLS, SPELL_DESCRIPTION | MGBG | ICMAGE/ICPRIEST |
| 14 | Journal (`GUIJRNL.py`) | JOURNAL (one menu, three modes: quests, journal, bestiary) | JRNBG, and BEASTBG in bestiary mode | Tabs Quests/Journal/Bestiary (JRNBUTT) wire to the classic windows' code. JRNLOP picture in journal mode. Bestiary mode, EE areas: list 522,97 430×188; picture 107,79 316×492; text 532,306 420×174; PC/NPC buttons 562,526 and 683,526; Done JRNDONE 820,568. Data and rules stay the 5.1 ones (classic `beast.ini`, 2h logic shared through `Wire`). Draw the picture at its classic logical size 281×441 (4× twin from 2g) centred in the scaled picture area; no fractional scaling. Check the 2h items again on the EE screen |
| 15 | Area and world map (`GUIMA.py`) | AREA_MAP, NOTE_ADD, WORLD_MAP | MAPBG, WMAPBG | Area map: EE AR*.mos (copied, aliased) in a fit-mode MapControl; markers must land on the party |
| 16 | Stores | STORE_BUYSELL, STORE_IDENTIFY, STORE_ROOMS, STORE_HEALING, STORE_CHOOSER | STRBG, STRBG2 | STP* portraits |
| 17 | Dialog, container, party pick, death | WORLD_DIALOG, WORLD_CONTAINER, WORLD_PICKPARTY, WORLD_DEATH | DIABG/CONVWING, CONBG, REFBG | Dialog and container are world overlays: run a full staged fight afterwards (`tools\tb_fight.ps1`) |
| 18 | World HUD | WORLD_ACTIONBAR*, WORLD_SIDEBAR_*, WORLD_FORMATION, RADWEDGE | MAINBG, ACTBG | **Stop and ask the owner before starting.** The turn-based HUD (timeline, dice panel, portraits, radial menu) sits on the classic bars. Bring a written proposal first |

## 10. Ask the owner (stop and ask; do not guess)

- Phase 18, the world HUD, before any work.
- Start-menu Continue and Options buttons (default: out).
- Paper-doll twins for the classic inventory after the phase 2f review images.
- Movies: EE's WebM files need a new decoder plugin (libvpx or ffmpeg). Do nothing unless asked.
- Anything that would need EE data at run time from the GOG folder instead of `ee_ui\`.

What does not need asking: alias numbers, JSON field names, which classic function an EE button
wires to when the classic script already has it, the order of phases 7-17.

## 11. Progress

Update after every phase: what was built, what was checked in game (with screenshot paths), what
was only unit-tested or compiled, what is still unseen. Commit only when the owner asks; never
commit `ee_ui\`, `upscaled\`, screenshots or `tools/upscale/work/`.

- 2026-11-14: research done (this document). Prototypes and reports in `tools/upscale/work/`
  (`ee_inventory.py`, `ee_inventory2.py`, `ee_plate.py`, `ee_overlay.py`, `ee_tlk_check.py`,
  `ee-extract/`). Bitmap fonts restored; `EXOCET.ttf` still in the override (phase 0 removes it).
  Nothing is committed.
- 2026-11-14: bestiary researched (section 5.1, phases 2g, 2h, 14). Nothing built yet.
- 2026-11-14: Phase 0. Removed the `EXOCET.ttf` fallback from `Interface::LoadFonts`. Deleted
  `D:\Games\GemRB\override\pst\EXOCET.ttf`. Kept the `Font.cpp` NEAREST-on-twin draw. Built
  Release and installed to `D:\Games\GemRB`. `Test_gemrb_core --gtest_filter=FontHiRes*` passed
  (2/2). In game the log is `Loaded Font: FONTDLG for ResRef FONTDLG` (BAM, 255 hi-res frames);
  same for TRMTFONT, EXOFONT, POSTANT, NUMBER*, SYSFONT, NORMAL. No `EXOCET.ttf` was opened.
  HUD text is the classic bitmap face (`shots/eeui_phase0_fonts.png`). Nothing is committed.
- 2026-11-17: Phase 1 (partial). `tools/eeui/` has `ee_data.py` (KEY/BIF reader), `pvrz.py`
  (vectorised DXT1/DXT5), `decode.py` (MOS V2/V1, BAM V2), `dump.py`. STARTBG, CGBACK, NORMBUTT,
  STARTBUT, SP001 decode at the sizes in section 1; STARTBG and SP001 looked at (match the EE art).
  `inventory.py` and `run_eeui.bat` are not written yet (`build.py` is phase 4).
- 2026-11-17: Phase 2 (2a, 2b, 2c, 2d) via `tools/eeui/twins.py`. Written to
  `D:\Games\GemRB\upscaled` and listed in `ee_twins.txt` (337 files; log in `ee_twins.log`).
  2a 104/104 spell icons (n=8). 2b WMWRLDB 2x (classic worldmap.wmp confirmed to use it).
  2c 122/122 area maps (n up to 12 for tiny classic maps; EE art is upsampled when
  `round(ee/classic)*classic` exceeds it). 2d only WMPICKL passes the rule; IVSLOT, CGPLUS, CGMINUS,
  WMLOCAT, WMTIME, WMCHRH fail frame count, CGCANCEL, CGSCRL1, STALIGN, STFCTION, FILLBAR fail aspect.
  `upscale.py` now skips every resource in `ee_twins.txt`, even with `--force`.
  Seen in game: Hive area map (AR0400) opens, log shows twins attached for AR0400 and WMWRLDB
  (`shots/ee_p2_areamap.png`). Not looked at yet: spell book icons, world map screen, WMPICKL.
  Not done: 2e cursors, 2f paper-doll review images, 2g/2h bestiary. Nothing committed.
- 2026-11-17: 2g + 2h. `twins.py bestiary` wrote 88/89 JR*KN twins (EE 1124x1764 resized to classic x4,
  alpha from the classic BMP; DEFAULT included) into `upscaled/gui/bmp`, listed in `ee_twins.txt`.
  JRALUKN has no EE picture; `classify.py` now queues every `beast.ini` imageKnown, and the ESRGAN
  run produced its twin. `GUIJRNL.py`: description follows `global` (highest `desc<n>` <= value),
  lists sorted by displayed name, "No Known Creatures" placeholder (3594/3595) with DEFAULT picture.
  Seen in game (`shots/ee_bestiary2-4.png`): alphabetical lists; Morte text 3531 at Morte=0 and
  3526 at Morte=1; Morte picture sharp from the EE twin; placeholder shown for an emptied class.
  Not looked at: Alu-fiend picture, corner transparency, shimmer at 1x window, EEUI=0 (2h does not
  read EEUI). Nothing committed.
- 2026-11-17: Phase 3 (engine, behind `EEUI`). Built, installed, unit tests green (33/33 incl. new
  `Test_EEUIArt.cpp`: FromFullRes geometry/padding/alpha/colour average/offset rounding, FitRegion).
  3.1 `EEUI` / `EEUIPath` config; `ee_ui` is registered as source "EE UI" after mods (EEUI forced off
  with a warning when the folder is missing); `EEUI=1` is in `tools/dev_settings.ini` (GemRB.cfg
  section). 3.2 `HiResArt::EEScale()` (720 -> 3, 1080 -> 2, else logged error) and
  `HiResArt::FromFullRes`; hooked into `BAMImporter::GetV2Frame` (centre / k, rounded) and
  `MOSImporter::GetSprite2Dv2`; `AttachBamFrame`/MOS attach skip sprites that already have a twin.
  3.3 CHANGED FROM PLAN: GL mipmaps do nothing here (the shader reads with `texelFetch` and filters
  by hand), so `GLShaders.h` now averages four bilinear taps when a twin is minified (footprint >
  1.25 texels). 3.4 SKIPPED: `Button::HitTest` already tests the button picture's alpha and the
  STARTBUT frames are arc-shaped (67% opaque), so no hit polygon. 3.5 `MapControl.SetFit(True)`
  (Python + C++, `MapControl::FitRegion`), coordinates keep using `mosRgn`.
  Seen in game: with a scratch `ee_ui` holding STARTBG, the log shows `Found 'STARTBG.mos' in 'EE UI'`
  and the picture drew on the journal button with no error (`shots/ee_p3_startbg.png`; tiny, so
  sharpness not judged). `tb_autotest.ps1` mortuary passed twice (one earlier run failed to start
  the fight, ghouls passed; looks flaky, not tied to this change). Scratch `ee_ui` removed again.
  Not seen: the minify filter at a 2x window, SetFit on a real map screen (phase 15), 1080 mode.
  Nothing committed.
- 2026-11-17: Phase 4 (converter). `tools/eeui/build.py` (+ `menu_parser.py`, `extra_art.txt`,
  `run_eeui.bat`) writes `D:\Games\GemRB\ee_ui\` in ~16 s: 96 menus (94 with controls, 997 controls)
  as `layout/<MENU>.json`, 233 art files (165 MOS, 68 BAM) with 548 PVRZ pages (174 MB), 9 aliases
  (`EU0001..9`: STFCTION, STALIGN, CGSCRL1, CGPLUS, CGMINUS, GENBUT1, WMTIME, IVSLOT, CGCANCEL; kept
  stable across runs), `styles.json` (13 styles, 20 colours), 94 previews, `review/bestiary.txt`
  (89 rows). Layout JSON: `strref`/`text`(EE)/`literal` string objects (numeric keys are strrefs),
  `plate_menu` (background menu, also inherited from the menu that pushes it), `hit` polygons,
  `raw` Lua strings. Strings: 227 strref, 82 EE text, 15 literal/unknown (6 uppercase keys not in
  `uiStrings`: GODBOW/GIVE_GOLD/GIVE_XP/EXPLORE_LABEL, *_CHEATS_BUTTON, all EE-only).
  Seen: `previews/START_MAIN.png` (buttons on the STARTBG arcs, hit polygons match) and
  `previews/CHARGEN.png` (stat boxes on the wheel). Missing in EE and classic (dead BG1 leftovers):
  FUNC, GUIBUTNT, GUICONTB, GUIERR6, GUIOSTUR, GUIOSW, GUIPOPF, RES, START3EE, TITLE.
  Not done: V1 BAM art is outlined only in previews; save portraits not in `extra_art.txt` yet;
  bestiary report's "differs" column not reviewed. Committed with this entry.
- 2026-11-17: Phase 5 + 6. Engine: `GetSystemVariable` gained `SV_EEUI` (8) and `SV_EEUIPATH` (9);
  `Interface.cpp` stores the resolved `ee_ui` folder back into `config.EEUIPath`. New
  `gemrb/GUIScripts/pst/EEUI.py` (`Enabled`, `Available`, `Load`, `Find`, `Build(menu, windowId,
  plate, skip)`, `StyleFont/StyleColor/StyleFlags`, `Text`, `LUA_TEXT` for `text lua` labels) and
  `gemrb/unhardcoded/pst/eeuifont.2da` (8-char name; was planned as `eeui_fonts`). Windows are
  created in the existing `START` pack (an unknown pack makes `CreateWindow` log a CHU error). EE
  button cycles are frames 0 normal, 1 highlight, 2 pressed, 3 disabled; `SetSprites(bam, seq, 0,
  2, 0, 3)`. Types not built yet are logged once (`slot`, `slider`, `edit`, `map`, ...).
  `Start.py` split into `BuildClassic()`, `BuildEE()`, `Wire(handles)`. Skipped from EE START_MAIN:
  Continue (seq 1), Options (seq 2, 3), and the VERPLATE plate (tiny, blurred; the version text
  sits on the plate art, label widened to fit the run-time text).
  Seen in game: EE start screen with STARTBG and the three arcs (`shots/ee_p6_start2.png`); New Life
  opens character generation; The Abyss opens the classic quit popup (`shots/ee_p6_quit.png`);
  `EEUI=0` shows the classic start screen unchanged (`shots/ee_p6_classic.png`). The version text
  shows as `095 git` (the classic font has no `.` or `-`, same as classic).
  Not seen: Select Life (Load) from the EE screen; Escape (the dev key tool does not trigger
  `MakeEscape` even on the classic screen); `tb_autotest.ps1` not run (no in-game screen touched).
- 2026-11-17: Phase 7 (popups). `EEUI.Popup(text, [(label, handler, "de"), ...], image=None)` +
  `EEUI.PopupAvailable(n)` build a modal EE box from `POPUP_INFO` (1 button), `QuitMenu` (2),
  `POPUP_THREEBUTTON` (3), buttons listed left to right, handler None just closes. `Build` now
  makes popups a window the size of the menu's bbox and uses the backdrop label as window
  background (as a label it covered the other controls). Used by: `Start.QuitPress`,
  `NewLife.CancelPress` and the "points left" notice, `GUILOAD`/`GUISAVE` `DeleteGamePress`
  (each falls back to its CHU window when EEUI is off). Seen in game: start-screen quit box with
  text, No/Yes, image (`shots/ee_p7_quit.png`), No closes it and it reopens, NewLife cancel box
  over chargen (`shots/ee_p7_cancel.png`). Not seen: Yes button, 3-button box, info box, delete-
  save boxes, Escape (dev key tool does not reach `MakeEscape`), `EEUI=0` for these boxes
  (guarded by `PopupAvailable`, unchanged classic path).
- 2026-11-17: Phase 8 (character generation). `NewLife.py` split into `BuildClassic()`,
  `BuildEE()` and one `Wire(handles)` (stat labels, hover regions, +/- buttons, AC/HP/points,
  title, text area, portrait, Accept/Cancel). `BuildEE` finds controls in the CHARGEN layout by
  their EE meaning (ability numbers 1 STR, 2 DEX, 3 CON, 4 INT, 5 WIS, 6 CHA mapped to GemRB's
  STR INT WIS DEX CON CHA; `text lua` names like `chargen.AC`), skips the second title and the
  name label (no classic function). `EEUI.Build(..., override={index: 'button'|'textarea'})` builds
  the description box as a text area and the centre hole as the portrait button. `eeuifont.2da`:
  `normal*`, `parchment`, `white_parchment` now FONTDLG (TRMTFONT is unreadable at this size).
  Value labels use EXOFONT. Seen in game: the EE wheel with plate, art, portrait (`shots/ee_p8_a.png`,
  `ee_p8_c.png`), two STR `+` clicks: STR 11, points 21 -> 19, hover text updates; Accept with
  points left shows the EE info popup (`shots/ee_p8_e.png`). Not seen: `-` buttons, Cancel Yes/No
  from this screen, Accept with 0 points (enters the game), level-up use (`OpenLUStatsWindow(1)`),
  `EEUI=0` chargen (path unchanged: `BuildClassic` is the old code).
- 2026-11-17: Phase 9 (load / save). Converter: `list` controls now carry their row template as
  `columns[].controls` (children with frames relative to the row, `bitmap_lua`, `text_opts.lua`);
  `bitmap res` no longer counted as missing art; `extra_art.txt` adds LOADROWB/C, STRROW, ABLROW.
  `EEUI.BuildRows(win, menu, listIndex, count, sel_pictures)` builds N rows (transparent click
  catcher on top, content, row background label last: controls created first are drawn on top),
  `EEUI.Alias(name)` reads `aliases.txt` (EE name -> EU####). `GUILOAD.py` and `GUISAVE.py` now
  use `BuildClassic()` / `BuildEE()` handles with rows (preview, name, time, 6 portraits) and one
  scroll bar; EE has one Load/Delete (Save/Delete/New Save) button set acting on the selected row,
  5 rows instead of 4. `GUISAVE` EE window is shown modal (it covers the HUD). Scroll bar ID
  0x900 collided with an existing control ("null ref"); EE scrollbars use 0x5000.
  Seen in game: EE load screen with 5 rows, previews, names, dates, party portraits, selection
  highlight (`shots/ee_p9_b.png`); Load from it started the game (loading screen,
  `shots/ee_p9_loaded.png`); EE save screen in a running game incl. Empty slot, selection, Delete
  disabled on the empty slot, New Save opening the classic name box, Cancel closing it
  (`shots/ee_p9_save2.png`, `ee_p9_save3.png`). Not done: EE `SAVE_NEWSAVE` popup (the classic
  name window is used), alignment/faction icons per row (not in classic save data), the two empty
  portrait ring slots drawn in the row art, Delete confirm from these screens (uses the phase 7
  popup, not exercised), Save/overwrite actually writing a file, `EEUI=0` load/save, scrolling
  with more than 5 saves (8 saves here, bar drawn). Clicks via `dev.ps1` land unreliably when the
  game window is resized/alt-tabbed; screens were driven with `dev.ps1 py` (note: Python modules
  stay cached in a running game, use `importlib.reload`).
