# Spell and effect visuals overhaul (GemRB fork, classic PST): plan

Goal: make spells and effects look modern without touching what they do. Effects become real
light sources, glow in HDR, darken the world around them instead of themselves, throw particles
from where their art actually glows, and bend the air with shockwaves and heat haze. Every piece
has a toggle, and with all toggles off the game looks exactly as it does today.

Read `CLAUDE.md`
first. Their rules apply to every step. Then read this whole file once before starting. Read
`NOTES.md` "Phase 4" and "Phase 5" (the lighting and polish passes this plan builds on).

---

## 0. Rules for whoever executes this plan

1. Work **one phase at a time**, in order. A phase is finished only when every item in its
   "Done when" list has been checked and section 15 "Progress" is updated with what you ran and
   what you saw. Do not start the next phase in the same breath.
2. The decisions in section 1 are locked. Do not change them. If one looks wrong, write down why
   in your report and still do what it says, or stop and ask the owner.
3. Stop and ask the owner (and only then) when:
   - a "Done when" check fails twice after real fixes,
   - anything would change what a spell **does** (damage, targets, duration, timing, which
     projectile spawns). Section 12 lists known cases; they are not part of this plan,
   - you would need to download anything (models, textures, libraries not already in vcpkg).
4. Build exactly what is described. No extra effects, no extra particles, no "while I'm here"
   features. (Past failure: unrequested map sparkles.)
5. The working tree has uncommitted work from other tasks (lighting plan, upscaling, EE UI,
   turn-based). Never revert, reformat or commit files you didn't change for this plan. Do not
   commit at all unless the owner asks.
6. No em dashes in code comments, docs or reports (owner preference).
7. Engine changes: after each one run `cmd /c "D:\gemrb\build_install.bat < NUL"` from
   PowerShell. A pause or non-zero exit is a failure; fix it and rerun.
8. Python changes: after each one run the real command on real game data and read the output.
9. Numbers marked "start value" may be tuned. Record the final value and why in section 15.
   Numbers not marked that way are fixed.
10. "Checked in game" means: the installed build, driven with `tools\vfx_lab.ps1` (phase 0),
    with the frames or sheets embedded in your report. A compile or a unit test is not that.

---

## 1. Decisions already made (do not change them)

- **Presentation only.** Nothing in this plan may change effect opcodes' results, projectile
  paths or timing, damage, durations, saving throws, which resources get created, or the game
  RNG. Visual code reads game objects and never writes them. Its randomness uses its own RNG
  (like `ScenePolish`). Spell timing stays tied to the game clock; only the extra visuals
  (particles, light smoothing, distortion) run on the presentation clock.
- **The original art stays the base.** PST's spell BAMs are always drawn exactly as today. Every
  addition goes on top (lights, emissive glow, particles, distortion). Never replace or hide a
  BAM. Never edit game files.
- **OpenGL driver only.** `VideoDriver=sdl` stays untouched. Everything here lives behind
  `SupportsSceneTransform()` and the toggles in section 2.
- **No full HDR scene.** The scene buffer stays RGBA8 (UI, fog, upscaled art and every existing
  pass depend on it). HDR lives in one new RGBA16F **emissive buffer** that effects write into
  while they are drawn. It drives the lit composite and the bloom. Do not convert the scene
  buffer.
- **One gather, many consumers.** One function enumerates every effect instance visible this
  frame (`VfxSystem::Gather`, section 6.2). Lights, particles, distortion and the debug overlay
  all read that list. Never write a second enumeration of VVCs or projectiles for one feature.
  (Past failure: preview and walk computed separate paths, so the preview lied.)
- **One anchor function.** Where a VVC is drawn is computed by one function
  (`ScriptedAnimation::DrawAnchor`, section 6.2) used by both `ScriptedAnimation::Draw` and
  `VfxSystem`. Particles and lights must sit exactly on the art.
- **Data in tables.** Per-effect tuning lives in 2DA tables in `gemrb/unhardcoded/pst/`
  (like `hitmat.2da`). Automatic defaults come from an offline scan of the game's BAMs
  (`vfxauto.2da`, generated). Hand-written tables override the automatic ones. Code holds no
  per-spell special cases.
- **Per-attachment blending needs `ARB_draw_buffers_blend`** (or GL 4.0). The driver checks it at
  start-up. Without it the emissive buffer is off (logged once), and the game looks as today.
- **Budgets per frame:** at most 48 effect lights (highest `intensity * radius` win), 3000 effect
  particles, 32 distortion shapes. Over budget, drop the weakest, never crash or stall.
- **Testing goes through the VFX Lab** (phase 0): scripted casts by name, frame bursts, contact
  sheets, animated GIFs, A/B comparisons and an HTML gallery. Saves are loaded by name.
- Spells are cast by spell.ids number (PST has no `SpellRES`): SPPR = 1000 + n, SPWI = 2000 + n,
  SPIN = 3000 + n where n is the 3 digits of the resref. Verify this against PST's `spell.ids`
  in phase 0 and record the result (`tools\tb_flee_cast.ps1` already uses 2119 for SPWI119).

---

## 2. Toggles

All read live from `core->GetDictionary()` (like `Lighting`), all on by default in
`tools/dev_settings.ini` under a comment `; spell and effect visuals (VFX_PLAN.md)`, all
documented in `gemrb/GemRB.cfg.sample.in` with one line each. Every feature checks
`Vfx != 0 && <its toggle> != 0`.

| Toggle | Default | Phase | Meaning |
|---|---|---|---|
| `Vfx` | 1 | 1 | master switch for everything below |
| `VfxEmissive` | 1 | 1 | effects write the emissive buffer: lit composite keeps them bright, bloom uses it |
| `VfxEmissiveBloom` | 100 | 1 | 0..200, bloom strength of the emissive buffer |
| `VfxSmoothEffects` | 1 | 1 | additive effect sprites get a soft filter instead of the sharpened one |
| `VfxSpellDarken` | 1 | 2 | spell screen darkening dims the world's light instead of drawing a black rectangle |
| `VfxSpellDarkenStrength` | 85 | 2 | 0..100, how much of the original darkening goes into the light pass |
| `VfxFlashAsLight` | 1 | 2 | spell screen flashes light the world instead of covering the screen |
| `VfxLights` | 1 | 3 | effect lights from the gather list (replaces today's VVC and projectile light code) |
| `VfxLightGain` | 100 | 3 | 0..200, scales every effect light |
| `VfxParticles` | 1 | 4 | particles thrown by effects |
| `VfxParticleDensity` | 100 | 4 | 0..200, scales emission rates |
| `VfxDistortion` | 1 | 5 | shockwaves and heat haze |
| `VfxDistortionStrength` | 100 | 5 | 0..200 |
| `VfxChroma` | 1 | 5 | slight colour split inside shockwave rings |
| `VfxAura` | 1 | 6 | glowing rim on creatures under colour glow or pulse effects |
| `VfxDebug` | 0 | 1 | dev only, not in dev_settings: 1 emissive buffer, 2 distortion offsets, 3 effect lights overlay, 4 particle spawn points |

With `Vfx=0` the game must look exactly as before phase 1 (checked at the end of every phase,
section 13).

---

## 3. Background facts (verified on this machine; re-check line numbers, they drift)

### 3.1 Game data (from `tools/vfx/work/pst_spell_visuals.md`, generated by `survey.py`)

- **Classic PST ships no PRO and no VVC files.** Torment.exe hardcoded its projectiles. All 213
  PROs and 20 VVCs GemRB uses are GemRB's own, in `gemrb/unhardcoded/pst` (164 PRO, 19 VVC) and
  `gemrb/unhardcoded/shared` (49 PRO, 1 VVC), plus 43 helper SPLs that projectiles fire as
  payload. Projectile numbers map through `gemrb/unhardcoded/pst/gemprjtl.ids` (SPL value N ->
  line N-1). 94 PROs are reachable from spells and items.
- 177 SPL, 728 ITM, 2591 BAM. 152 distinct BAMs are reachable from spells.
- Visual opcodes in PST (names from `gemrb/unhardcoded/pst/effects.ids`):
  - `0xBB` PlayBAM1 = `fx_play_bam_blended` (always additive). **282 uses, the most used opcode
    in the game.**
  - `0xBC`-`0xBF` PlayBAM2-5 = `fx_play_bam_not_blended` with p2 bits: `0x1` random offset,
    `0x1000` sticky on target, `0x10000` background / `0x20000` foreground / `0x30000` twin,
    `0x100000` fade, `0x300000` blend. 160 uses. Foreground/background is done by adding or
    subtracting **9999 to both `ZOffset` and `YOffset`** (`PSTOpcodes.cpp` around line 265).
  - `0xC3` TintScreen (62 uses in 36 spells), `0xC2` FlashScreen (44), `0xC1` ScreenShake (36),
    `0x09` Color:PulseRGBGlobal (46), `0x08` Color:SetRGBGlobal (4), `0xC9` Overlay (25),
    `0xC5` MultipleVVC (GemRB only; plays `chost.2da`, `rune.2da`, `lstorm.2da`), `0xCD` MoveView.
- Projectile light spots: 30 PROs set travel flag `PTF_LIGHT` (0x40) and draw a light sprite.
- The big cinematics are 640-wide BAMs designed for a 640x480 screen: `S091PHNX` (Celestial
  Host, 132 frames 640x480), `S052CONE` (Cone of Cold, 200 frames), `S087BLST` (Mechanus' Cannon,
  96 frames 640x408), `S914RUNE` (Rune of Torment), `S092CONF` (Conflagration), `S083BGCL`
  (Deathbolt, 640x231 horizontal bolt), `S075WDSH` (Stygian Ice Storm).
- VVC transparency `IE_VVC_GLOWING` (0x200000) is set on `IGNUSORB`, `S075WDSH`, `S914HGBL` and is
  a TODO in GemRB (`ScriptedAnimation.h`). Phase 1 implements it as extra emissive gain.
- Party casters (CRE known spells): Dak'kon SPWI118-121, SPWI219; Fall-From-Grace SPPR101-401,
  SPIN104, SPIN107; Ignus SPWI116-117, SPWI217-218, SPWI312-313, SPWI410; Morte SPIN101 (Skull
  Mob SPIN102 is granted in play). TNO learns mage spells in play. Annah, Nordom, Vhailor: none.

### 3.2 How effects are drawn today

- Order in `Map::DrawMap` (`gemrb/core/Map.cpp`, around 938-1240): background, reticles, wall
  stencil, `CollectSceneLights`, `ScenePolish::BeginFrame`, background area animations, ground
  decals, then one depth-sorted pass over actors (with their attached VVCs inside
  `Actor::Draw`), area animations, map VVCs (`vvcCells`, `VEFObject`), projectiles and
  `Particles` (sparkles), then weather, `ScenePolish::DrawParticles`, **`DrawSceneLighting`**,
  fog, **`DrawScenePost`** (bloom, grading, vignette), overhead text.
- **Spell glows are drawn before the light pass, so it darkens them** with the ambient (dungeon
  0.66). Only `highlightKeep` (very bright pixels keep part of their brightness, `LightFS` mode
  1) rescues the hottest pixels.
- The scene buffer is RGBA8. Bloom (`PostFS` mode 0) thresholds plain brightness (0.72), so a
  bright floor blooms like a spell, and nothing can be brighter than white.
- Blended VVCs draw with `BlitFlags::ONE_MINUS_DST` (screen blend), projectiles with
  `ONE_MINUS_DST` / `DST` / `SRC` from their travel flags (`Projectile.cpp` ~2004),
  `ScenePolish` sparks and embers with `ADD`. GL mapping: `BlendForFlags` and the switch in
  `GLVideoDriver::Flush` (`GLVideo.cpp` ~560-610).
- Effect lights today (`Map::CollectSceneLights`, ~1313-1431): party light, `ScenePolish`
  impact flashes, `BlendBlack` area animations, **map** VVCs that are blended or have a light
  spot, and **flying** projectiles via `Projectile::GetGlow`. Colour and strength come from the
  luminance-weighted average of the current frame (`GetSpriteGlow`, cached per sprite).
- **Not lit today:** VVCs attached to actors (`Actor::vfxQueue`: casting glows from
  `fx_casting_glow`, sticky PlayBAMs, overlays, hit animations), and **exploding** projectiles:
  `GetGlow` returns false outside TRAVELLING/HIT/AWAITING_TRIGGER, and the spreading flames are
  child projectiles stored inside the parent (`std::list<Projectile> children`,
  `Projectile.h` ~298), not in the map's list. A fireball-style explosion casts no light.
- **Spell screen darkening** (`fx_tint_screen`, `PSTOpcodes.cpp` ~447) and **flash**
  (`fx_flash_screen`, ~378) set `WindowManager::FadeColor` (non-EE PST: black at alpha 0x80) and
  start `GlobalTimer` fades. `WindowManager.cpp` ~658 then draws one blended rectangle over the
  whole screen, effects and UI included. Script fades (`FadeToColor`, cutscenes) use the same
  timer and rectangle and are script-visible (actions wait on them): never change their timing.
- Casting glow: `Scriptable::SpellCast` -> `Spell::AddCastingGlow` -> `fx_casting_glow`
  (`FXOpcodes.cpp` ~4561) loads `castingGlows[cg]` (PST `cgtable.2da`) as a VVC on the caster.
- VVC phases onset/hold/release, `Phase`, `anims[phase * MAX_ORIENT + orient]`,
  `DrawingRegion()`, offsets `XOffset/YOffset/ZOffset`, `IE_VVC_HEIGHT`: `ScriptedAnimation.h`.
  Draw position today: `Pos.x - vp.x + XOffset, Pos.y - vp.y - ZOffset + YOffset` (minus height
  with `IE_VVC_HEIGHT`) in `ScriptedAnimation::Draw` (~628).
- Explosion state machine: `Projectile::GetNextExplosionState`, `InitExplodingPhase1`,
  `SpawnChildren`, `DrawExplosion` (~1490-1840). Fragments spawn only with area flag
  `PAF_SECONDARY` (~1785).
- `ScenePolish` (`core/ScenePolish.*`): presentation particle system with `DrawSoftShapes`
  (texMode 3: Disc, Blob, Ring), impact flashes, own RNG, dt from `GetMilliseconds` capped at
  100 ms. Copy its style.
- Turn-based combat reads `Turn Based Combat` live (`CombatDirector.cpp` ~111), so the lab can
  switch it off for a session with `GemRB.SetVar`.

### 3.3 Prior art

`E:\GitHub\pst-forever` has **no** spell VFX (no VVC or PRO playback, no particles, no effect
lights, no bloom); its D2 package is unbuilt. Nothing to copy beyond what `NOTES.md` phase 5
already took. Do not spend time there.

### 3.4 Tools that exist

- `tools\dev.ps1 start|py|pyfile|click|move|key|shot|log|crash|stop`. `py` runs Python inside the
  game through `GUIScripts/DevConsole.py` (helpers `here()`, `act()`, `goto()`, `pc()`).
- The GL driver writes a frame when `dev\shot.req` appears (`GLVideoDriver::DevScreenshot`,
  polled every 10 frames). One frame only.
- In-game console: Ctrl+Space with `EnableCheatKeys=1` runs Python with `GemRB` in scope.
- `GemRB.LearnSpell(pc, resref, LS_MEMO)` (flags in `GUIScripts/ie_spells.py`),
  `GemRB.SaveGame`, `GemRB.ExecuteActionAt(actor, action, targetGlobalID)`,
  `GemRB.ExecuteString(action, slot)`.
- Saves in `C:\Games\GemRB\pst_saves\save` (today: Auto-Save, 002 The Hive, 009 Warrens of
  Thought, 011 Drowned Nations Catacombs, 11, 12, wererat).
- Python venv for tools: `D:\gemrb\tools\upscale\.venv` (Python 3.12, numpy, Pillow).
- Survey scripts written during planning: `tools/vfx/work/pst_data.py` (layered resource
  reader over `ie_formats`, resolves resources the way GemRB searches), `survey.py`,
  `survey.json`, `pst_spell_visuals.md`.

---

## 4. Phase 0: the VFX Lab (test harness) and the baseline

Nothing visual changes in this phase. It builds the way every later phase is checked, and it
records how the showcase spells look today.

### 4.1 Tooling layout

```
tools/vfx/
  pst_data.py        # moved from tools/vfx/work/ (resource reader)
  survey.py          # moved from tools/vfx/work/ (writes work/pst_spell_visuals.md, work/survey.json)
  vfxscan.py         # phase 3: offline BAM scan -> gemrb/unhardcoded/pst/vfxauto.2da
  make_sheet.py      # frames -> contact sheet, GIF, A/B compare sheet
  make_gallery.py    # all spells -> shots/vfx/index.html
  measure.py         # numeric checks on two frame sets (section 4.6)
  tests/             # python -m unittest discover tools/vfx/tests
  work/              # git-ignored scratch and review images
tools/vfx_lab.ps1    # the lab driver (section 4.4)
gemrb/GUIScripts/VfxLab.py   # in-game side (section 4.3)
```

- Move `pst_data.py` and `survey.py` out of `work/`, fix their imports, keep writing their output
  into `work/`. Rerun `survey.py` and check `pst_spell_visuals.md` is regenerated unchanged
  (apart from the timestamp, if any). Delete `work/smoke.py` after reading it (scratch).
- Add `tools/vfx/work/` and `shots/vfx/` to `.gitignore` next to the upscale lines.

### 4.2 Engine dev hooks (GL driver, `GLVideoDriver::DevScreenshot`)

1. **Burst capture.** When `dev\burst.req` exists (check every 2 frames), read
   `<prefix>;<count>;<intervalMs>;<downscale>` (downscale 1 or 2), delete the file, then write
   `count` frames of the presented image to `<prefix>_000.bmp`, `<prefix>_001.bmp`, ... at least
   `intervalMs` apart (use `GetMilliseconds()`; write on the first presented frame after the
   interval). Downscale 2 = 2x2 box filter before writing. When done write `<prefix>_done.txt`
   with one line per frame: `index ms_since_first`. Reuse the existing BMP writer of the single
   shot. A new request while a burst runs is ignored (log it).
2. **Frame timing.** When `dev\perf.req` exists, read `<frames>`, delete it, record the CPU frame
   time (time between consecutive `SwapBuffers`) for that many frames, then write
   `dev\perf.txt` and log `[Perf] frames N avg X ms p95 Y ms max Z ms`.
3. **Actor IDs for scripts.** The lab needs the global ID of a spawned dummy. Find whether the
   Python API already returns area actors with global IDs (search `GUIScript.cpp`). If not, add
   `GemRB.GetAreaActors()` returning a list of dicts `{ "ID", "Name", "ScriptName", "X", "Y",
   "Party" }` for the current area (pattern: `GemRB_GetTurnOrder` added by this fork).

Unit test: none for the hooks (they are I/O). They are checked by the lab run in 4.7.

### 4.3 `gemrb/GUIScripts/VfxLab.py` (in-game side)

Importable from `dev.ps1 py` and from the Ctrl+Space console. Functions:

- `SpellNumber(res)`: the section 1 rule, after checking it against `spell.ids`.
- `Slot(name)`: party slot of a companion by name (compare `GemRB.GetPlayerName`).
- `Setup()`: `GemRB.SetVar("Turn Based Combat", 0)` (remember the old value), heal the party,
  remove dummies left from earlier calls, spawn one dummy at a fixed offset (start value: 180
  map units east of TNO) with `CreateCreatureAtFeet`-style actions, center the viewport on TNO
  (find the PST-accepted action in `GameScript.cpp`'s action table, e.g. a `MoveView*` action).
  The dummy CRE is chosen in phase 0 (a creature that exists in PST, stands still, has no
  dialogue; check by spawning it) and written as a constant at the top of the file.
- `Restore()`: puts `Turn Based Combat` back.
- `Cast(res, caster=None, target="dummy")`: `caster` defaults to the showcase caster (section
  4.5). `target` is `"dummy"`, `"self"`, `"party"` (slot 2) or `"point"` (dummy's position).
  Uses `GemRB.ExecuteActionAt(casterID, "ForceSpell([-1],N)", targetID)` or
  `GemRB.ExecuteString("ForceSpellPoint([x.y],N)", slot)`. Prints what it cast.
- `Grant()`: for every showcase spell, `GemRB.LearnSpell(slot, res, LS_MEMO)` on its caster;
  print each return value. If memorizing fails for lack of slots, raise the caster's memorizable
  count with the existing Python API for that (search `SetMemorizableSpellsCount`) and retry.
  This is for the owner to cast spells normally from the hotbar.
- `Off()` sets `Vfx` to 0, `On()` to 1, `Set(name, value)` any toggle, `Reload()` reloads the VFX
  tables (phase 3 adds the engine call; until then it prints "not yet").
- `Next()`: casts the next showcase spell (cycles), for quick looking in game.

### 4.4 `tools/vfx_lab.ps1` (developer side)

```
vfx_lab.ps1 setup   [-Save vfxlab]                       # start the game on the save, wait for DevConsole, Setup()
vfx_lab.ps1 cast    -Spell SPWI107 [-Target dummy] [-Label on] [-Set "VfxLights=0,VfxParticles=0"]
                    [-Frames 36] [-Interval 66] [-Downscale 2] [-Save vfxlab]
vfx_lab.ps1 compare -Spell SPWI107 [-A "Vfx=0"] [-B "Vfx=1"] [-Save vfxlab]
vfx_lab.ps1 gallery [-Save vfxlab] [-Compare]            # every showcase spell, then make_gallery.py
vfx_lab.ps1 perf    -Spell SPWI901 [-Frames 240]         # cast and measure frame time (dev\perf.req)
vfx_lab.ps1 play    [-Save vfxlab]                       # for the owner: start, Setup(), Grant(), print how to play
```

- `cast`: if the game isn't running on that save, run `setup`. Apply `-Set` toggles with
  `GemRB.SetVar`, call `VfxLab.Cast`, immediately write `dev\burst.req` with prefix
  `shots\vfx\<SPELL>\<Label>`, wait for `_done.txt` (timeout 60 s), convert BMPs to PNG and
  delete the BMPs, then run `make_sheet.py`. Wait 4 s after the burst (start value) so the spell
  finishes before the next command. Print the output paths.
- `compare`: `cast` with `-Label A -Set <A>`, then with `-Label B -Set <B>`, then
  `make_sheet.py --compare`. Default A is `Vfx=0` (today's look), B is `Vfx=1`.
- `gallery`: `compare` for every showcase spell (section 4.5), on `vfxlab`, plus the four marked
  "dark" on `vfxlab_dark`, then `make_gallery.py`. Output `shots\vfx\index.html`.
- `play`: start, `Setup()`, `Grant()`, set `EnableCheatKeys=1` live if possible
  (otherwise say it must be in `GemRB.cfg`), and print: "select a caster and cast from the
  hotbar; Ctrl+Space opens the console: VfxLab.Next(), VfxLab.Off(), VfxLab.On(),
  VfxLab.Set('VfxLights', 0), VfxLab.Reload() after editing C:\Games\GemRB\unhardcoded\pst\vfx*.2da".
- All scripts use `D:\gemrb\tools\upscale\.venv\Scripts\python.exe` for the Python tools.

`make_sheet.py`: `--dir shots/vfx/SPWI107 --label on` writes `on_sheet.png` (grid of 6 columns,
each frame downscaled to 480 wide, time in ms printed on it from `_done.txt`) and `on.gif`
(960 wide, real frame durations). `--compare A B` writes `compare.png`: one row per frame
index, A left, B right, labels on top. `--crop x,y,w,h` (physical pixels) crops before
everything; the lab passes a default crop of 1600 x 900 centred on the screen centre (start
value).

`make_gallery.py`: one HTML page, one section per spell: name, resref, caster, the A and B GIFs
side by side, links to the sheets. Plain HTML, no scripts, relative paths.

### 4.5 Lab saves and the showcase list

- `vfxlab`: load save "002 The Hive" by name, check the party. Make sure TNO, Morte,
  Dak'kon, Fall-From-Grace and Ignus are in it (spawn missing ones with
  `act('CreateCreatureAtFeet("<cre>",0)')` + `act('ActionOverride("<cre>",JoinParty())')`; find
  the CRE names in the data, e.g. `GRACE`, `IGNUS`, `DAKKON`, `MORTE`). Stand them on open floor
  with room for a dummy to the east. Save with `GemRB.SaveGame` under the name `vfxlab`.
- `vfxlab_dark`: the same from save "011 Drowned Nations Catacombs" (a dungeon area: darkest
  ambient, where lights matter most), saved as `vfxlab_dark`. Confirm the area type is dungeon
  (`AreaType & AT_DUNGEON`) and say so in the report.
- Move any other save the lab creates out of the save folder. Always load by name.

Showcase (from the survey; "dark" = also run on `vfxlab_dark`):

| # | Resref | Name | Caster | Target | What it exercises |
|---|---|---|---|---|---|
| 1 | SPWI107 | Magic Missile | TNO | dummy | curved multi-missiles with light spots, hit BAMs, FlashScreen, ScreenShake (dark) |
| 2 | SPWI218 | Infernal Orb | Ignus | dummy | orb projectile, `IGNUSORB` VVC with the GLOWING flag |
| 3 | SPWI313 | Fiery Rain | Ignus | point | falling bombs, `S070BOOM` explosions, 300x480 cast column, TintScreen (dark) |
| 4 | SPWI502 | Cone of Cold | TNO | point | 640x480 cone VVC, TintScreen, cold |
| 5 | SPIN102 | Skull Mob | Morte | point | cone of fragment projectiles |
| 6 | SPPR301 | Call Lightning | Grace | point | tall 300x420 strike, electric |
| 7 | SPWI803 | Deathbolt | TNO | dummy | 640x231 horizontal bolt, ScreenShake |
| 8 | SPWI219 | Power of One | Dak'kon | self | sticky buff BAMs, colour pulse |
| 9 | SPPR303 | Prayer | Grace | self | party buff, PlayBAM5 layers |
| 10 | SPWI901 | Celestial Host | TNO | point | full-screen cinematic via `chost.2da` (dark) |
| 11 | SPWI914 | Rune of Torment | TNO | point | second cinematic, `rune.2da`, freeze/loop VVCs |
| 12 | SPWI807 | Mechanus' Cannon | TNO | dummy | fast projectile into a 640x408 blast (dark) |

Frame bursts: 36 frames at 66 ms (one per game tick, about 2.4 s) by default; Celestial Host
and Rune of Torment use 60 frames at 100 ms (start values).

### 4.6 `measure.py`

`measure.py --dir shots/vfx/SPWI107 --a A --b B` prints, over all frames of each label:
- `p99`: the 99th percentile luma (effect cores),
- `bg`: mean luma of the darkest 60% of pixels (background proxy),
- `glow`: mean luma of pixels within 24 px of a pixel above the p99 value (halo).
And the B/A ratios. Phases use these numbers in "Done when". Unit test with two synthetic frame
sets (a dark field with and without a bright disc).

### 4.7 Done when

- `survey.py` reruns from its new place and regenerates the report.
- spell.ids rule verified for all 12 showcase spells (numbers listed in section 15).
- Both lab saves exist, load by name, and the party is right (area name and party names printed
  by `VfxLab` in the report).
- `vfx_lab.ps1 gallery` runs all 12 (+4 dark) with A = B = today's look, with 0 timeouts. Every
  GIF shows the spell (look at each; if a spell shows nothing in GemRB, see section 12 and list
  it as "no visual in GemRB", do not fix it).
- `vfx_lab.ps1 perf -Spell SPWI901` prints a frame time line; record it as the baseline.
- `vfx_lab.ps1 play` leaves the game running with the showcase spells memorized; one spell cast
  from the hotbar by hand through `dev.ps1 click` works (screenshot).
- Python tests pass. Keep `shots\vfx\` from this run as `shots\vfx_baseline\` (copy) for
  section 13.

---

## 5. Phase 1: emissive buffer, lit composite, emissive bloom

### 5.1 Video interface (`gemrb/core/Video/Video.h`)

- `SceneTransform` gets `float objectEmissive = 0.0f;`.
- `Video` gets `void SetObjectEmissive(float gain)` and `void ClearObjectEmissive()` next to
  `SetObjectDepth`, storing into `scene.objectEmissive`.
- `ScenePost` gets `float emissiveBloom = 0.0f;` (0 = off) and `bool emissiveLit = false;`.
- `SceneLighting` gets `bool emissive = false;` (composite uses the emissive buffer).

### 5.2 Who sets emissive gain (core)

`gain` meaning: 0 = not emissive (the draw occludes emissive behind it), > 0 = emissive with that
gain. Default gains (start values), all multiplied by the table `GLOW` column from phase 3 when
present:

| Draw | Where | Gain |
|---|---|---|
| map VVC with `IE_VVC_BLENDED` (PlayBAM1, `SetBlend`, blended VVC files) | `Map::DrawMap` SCRIPTED case, around `sca->Draw` | 1.0 |
| same with `IE_VVC_GLOWING` | same | 1.6 |
| actor-attached VVC, same rules | `Actor::Draw`, around each `vfxQueue` VVC draw (both the under and over loops) | same as above |
| projectile with travel flags `PTF_TRANS`, `PTF_BLEND`, `PTF_BRIGHTEN` or a light spot; and its explosion children | `Map::DrawMap` PROJECTILE case | 1.0 |
| `Particles` (`Map::Sparkle`) | SPARK case | 1.0 |
| `BlendBlack` area animations (painted fires, portals) | `DrawAreaAnimation` lambda | 0.6 |
| `ScenePolish` additive kinds (Spark, Ember, Wisp, Shield) | `ScenePolish::DrawParticles` | 1.0 |

Set before the draw, clear right after (same pattern as `SetObjectDepth` / `ClearObjectDepth`).
Everything else keeps gain 0. A VVC's twin is drawn by its own `Draw` call; it uses its own
flags.

### 5.3 GL driver

1. **Capability.** In `CreateResources`: `drawBuffersBlend = GLEW_VERSION_4_0 ||
   GLEW_ARB_draw_buffers_blend`. Log once: `Log(MESSAGE, "GLVideo", "per-buffer blending: {}")`.
   Use `glBlendFunci` (4.0) or `glBlendFunciARB`.
2. **Emissive target.** New `emissiveTex/emissiveFbo/emissiveSize`, `GL_RGBA16F`,
   `GL_LINEAR`, size = scene target physical size, created with `EnsureTarget`.
   `EmissiveWanted()` = `drawBuffersBlend && Vfx && VfxEmissive`.
3. **Attach.** In `SceneBegan`, attach it as `GL_COLOR_ATTACHMENT2` to the scene FBO whenever
   `EmissiveWanted()`, independent of the depth map. `glDrawBuffers` with three entries:
   `{ COLOR0, depth ? COLOR1 : GL_NONE, emissive ? COLOR2 : GL_NONE }`. Clear it to 0. Detach in
   `SceneEnding`. Keep `depthAttachedFbo` logic as is; add `emissiveAttachedFbo`. Restructure
   `SceneBegan` so either attachment can exist without the other (today it returns early when
   lighting is off).
4. **Batch state.** `GLBatchState` gets `float emissive = 0.0f;` (compare it in `operator==`).
   `TargetState()` copies `scene.objectEmissive` while the scene applies to the target.
5. **Per-batch emissive blending in `Flush`** (only when the emissive buffer is attached to
   `st.fbo`), after the existing `glBlendFuncSeparate`:
   - `st.emissive > 0 && st.texMode != 0`, or texMode 3 (soft shapes) with `st.emissive > 0`:
     `glColorMaski(2, all true)`, `glBlendFunci(2, GL_ONE, GL_ONE)`. Uniform `u_emissive =
     st.emissive`.
   - else if `st.blend` is `Alpha` or `Premultiplied` and `texMode != 0`: occluder.
     `glColorMaski(2, all true)`, `glBlendFunci(2, GL_ZERO, GL_ONE_MINUS_SRC_ALPHA)`,
     `u_emissive = -1`.
   - else `glColorMaski(2, all false)`, `u_emissive = 0`.
   - When blending is disabled for the batch (`GLBlend::None`) the mask must be off.
   Sprites behind a creature stop glowing through it, and wall-stencilled pixels (their alpha is
   reduced by `stencilCover()`) occlude like they hide.
6. **Sprite shader** (`SpriteFS`): add `uniform float u_emissive;` and
   `layout(location = 2) out vec4 o_emissive;`. Every return path writes it:

   ```glsl
   // c: final straight-alpha colour of this fragment (after stencil cover)
   vec4 emissiveOut(vec4 c)
   {
   	if (u_emissive > 0.0) {
   		float l = max(c.r, max(c.g, c.b));
   		float hot = 1.0 + 0.6 * smoothstep(0.7, 1.0, l); // start value: cores run hotter
   		return vec4(c.rgb * c.a * u_emissive * hot, 0.0);
   	}
   	if (u_emissive < 0.0) return vec4(0.0, 0.0, 0.0, c.a);
   	return vec4(0.0);
   }
   ```

   Soft shapes use their `o_color`; the outline pass writes `vec4(0.0)` (phase 6 changes that).
7. **Smooth filter for effects** (`VfxSmoothEffects`): when `st.emissive > 0`, set
   `u_smooth = 2`. In `SpriteFS`, `u_smooth == 2` means: plain bilinear (`f` unchanged) averaged
   over four taps at `v_uv +- (0.35, 0.35)` texels (premultiplied, like the existing taps). It
   removes stair steps on blurry glow art when zoomed in. Sharp art (creatures, tiles) is
   unchanged.
8. **Lit composite** (`LightFS` mode 1): new sampler `u_emissive` (unit 4, the emissive texture,
   physical scene coordinates) and `uniform int u_hasEmissive`. Right after reading `c` and `l`:

   ```glsl
   vec3 e = vec3(0.0);
   if (u_hasEmissive == 1) {
   	ivec2 pp = ivec2(floor(v_uv)) + ivec2(u_regionOrigin);
   	e = min(texelFetch(u_emissive, pp, 0).rgb, c.rgb); // the part of this pixel the effect added
   }
   // (existing shoulder code on l)
   vec3 lit = (c.rgb - e) * l + e;
   float hi = smoothstep(0.72, 1.0, max(c.r, max(c.g, c.b)));
   lit = mix(lit, max(lit, c.rgb - e), hi * u_keep); // highlightKeep stays for painted highlights
   ```

   Why: an additive effect adds `e` on top of the background, so `c = bg + e`. Lighting the
   background and adding the effect back gives `bg * l + e`: the world darkens, the effect does
   not. For the screen blend it is `bg * (1 - s) * l + s`, also right. Set `u_regionOrigin` in
   mode 1 too (today only mode 0 sets it). Bind unit 4 only during this draw and unbind after.
9. **Emissive bloom** (`PostFS` mode 0): new sampler `u_emissive` and uniforms
   `u_emissiveBloom`, `u_regionPhys` (vec4: region x, y and the scene target's physical w, h).
   Bright pass becomes:

   ```glsl
   vec3 c = texture(u_src, v_uv / u_srcSize).rgb;
   // existing knee on c ...
   vec3 bright = c * w;
   if (u_emissiveBloom > 0.0) {
   	vec2 phys = u_regionPhys.xy + v_uv;             // v_uv is in region texels here
   	vec3 em = texture(u_emissive, phys / u_regionPhys.zw).rgb;
   	float seen = smoothstep(0.0, 0.08, max(c.r, max(c.g, c.b))); // fog of war hides it
   	bright += em * u_emissiveBloom * seen;
   }
   o_color = vec4(bright, 1.0);
   ```

   Check the coordinate mapping against how mode 0 is drawn (`PushLightQuad` uses region texels
   0..R.w as uv); fix the formula if needed and say so. With `VfxEmissive` on, raise
   `ScenePost::bloomThreshold` from 0.72 to 0.85 (start value) in `ScenePolish::BuildPost`, so
   bright floors bloom less and effects carry the bloom. `emissiveBloom = 1.4 *
   VfxEmissiveBloom / 100` (start value).
10. **Debug.** `VfxDebug=1`: in the lit composite output `vec4(texelFetch(u_emissive, pp,
    0).rgb, 1.0)` instead of the scene (works with `Lighting=1`; with lighting off, draw the
    emissive texture over the scene region in `DrawScenePost` instead).

### 5.4 Unit tests (`gemrb/tests/core/Test_Vfx.cpp`, add to `Test_gemrb_core`)

Put the math in `gemrb/core/VfxMath.h` (header only, no GL) and mirror it in GLSL:
- `CompositeLit(c, l, e)`: `c = bg + e` gives `bg * l + e` (3 cases); `e > c` is clamped.
- `EmissiveHot(l)`: 1.0 at 0.5, 1.6 at 1.0.

### 5.5 Done when

- Build, install, `Test_gemrb_core` (full run and `--gtest_filter=Vfx*`) pass.
- `gemrb.log` shows the per-buffer blending line (true on this machine).
- `vfx_lab.ps1 compare -Spell SPWI107 -A "VfxEmissive=0" -B "VfxEmissive=1"` on `vfxlab_dark`:
  `measure.py` B/A `p99 >= 1.10` and `glow >= 1.15`, `bg` within 0.97..1.03 (start values;
  record the real numbers). Embed `compare.png`. The missiles are visibly brighter and have a
  halo; the floor is not.
- Same for SPWI313 Fiery Rain and SPWI218 Infernal Orb (the GLOWING VVC glows more than PlayBAM1
  effects of similar brightness; say how you checked).
- Occlusion: cast SPPR303 Prayer with a party member standing between camera and the effect
  (walk them south of the caster first). `VfxDebug=1` shot: the creature's silhouette is dark
  inside the emissive glow. Find a spot where an effect plays behind a wall polygon (or move
  the dummy behind one): the `VfxDebug=1` shot shows no emissive through the wall.
- `VfxSmoothEffects` 1 vs 0 at zoom 150 (`GEMRB_DEV_ZOOM=150`): the effect's pixel stair steps
  are gone with 1, creature sprites look identical (crop both, embed).
- Section 13 checks pass. `tools\tb_autotest.ps1` passes.

---

## 6. Phase 2: spell darkening and flashes go through the light pass

Small change, big effect: during PST's spell darkening the world dims but the spell keeps
blazing and lights its surroundings.

### 6.1 Engine

1. `gemrb/core/GlobalTimer.h/.cpp`: `enum class FadeSource : uint8_t { Script, Spell };`, member
   `FadeSource fadeSource = FadeSource::Script;`, `void SetFadeSource(FadeSource s)`,
   `FadeSource GetFadeSource() const`. `SetFadeToColor` and `SetFadeFromColor` reset it to
   `Script` (their callers that are spells set it back right after). When the fade alpha
   returns to 0 in the timer update, reset to `Script`. **Fade timing must not change.**
2. `PSTOpcodes.cpp`: in `fx_tint_screen` and `fx_flash_screen`, after every `SetFadeToColor` /
   `SetFadeFromColor` call and every direct `FadeColor` write, call
   `core->timer.SetFadeSource(FadeSource::Spell)`.
3. `GameScript::SetGlobalTint` and every script fade action reset the source to `Script` (they
   go through the timer setters, check each).
4. New `gemrb/core/VfxSystem.h/.cpp` (add to `gemrb/core/CMakeLists.txt` next to
   `ScenePolish.cpp`), a singleton like `ScenePolish`. This phase adds:

   ```cpp
   // spell screen darkening / flash routed into the light pass instead of the overlay
   struct SpellScreen {
   	float darken = 0.0f; // 0..1, ambient multiplier = 1 - darken
   	float flash[3] = { 0, 0, 0 }; // added to the ambient
   	float overlayKeep = 1.0f; // how much of the WindowManager rectangle is still drawn
   };
   SpellScreen ScreenState() const; // from WindowManager::FadeColor + timer source + toggles
   static bool SceneLightingActive(); // GL scene driver + Lighting=1 + Vfx=1
   ```

   - Active only when `SceneLightingActive()` and the source is `Spell`.
   - Darkening (FadeColor near black, i.e. luma < 0.2): `darken = a/255 * VfxSpellDarkenStrength
     /100 * 0.9` (0.9 start value), `overlayKeep = 1 - VfxSpellDarkenStrength/100`.
   - Flash (`VfxFlashAsLight`, FadeColor luma >= 0.2): `flash = rgb/255 * a/255 * 0.9` (start
     value), `overlayKeep = 0.3` (start value).
5. `WindowManager.cpp` (~658): draw the fade rectangle with `alpha * overlayKeep` when the
   state is active. Script fades are untouched.
6. `Map::CollectSceneLights`: after computing the ambient, apply `ambient *= (1 - darken)` and
   `ambient += flash` (cap each channel at `maxLight`). Scale the party light and `BlendBlack`
   area lights by `(1 - 0.7 * darken)` (start value). Effect lights (phase 3) are not scaled.

### 6.2 Unit tests

`VfxMath.h`: `SpellScreenFrom(fadeColor, source, strengthPct, flashOn)` pure function used by
`ScreenState()`; tests: script source -> no change; spell black a=128 strength 85 -> darken
0.383, overlayKeep 0.15; spell white flash a=255 -> flash 0.9, overlayKeep 0.3.

### 6.3 Done when

- Tests pass.
- `vfx_lab.ps1 compare -Spell SPWI502 -A "VfxSpellDarken=0" -B "VfxSpellDarken=1"` (Cone of
  Cold, TintScreen p2=5): in B the cone is as bright as before the darkening and the world is
  darker than in A; in A the cone is dimmed with everything else. Measure: B/A `p99 >= 1.15`
  over the frames where the darkening is active (say which frames). Embed the sheets.
- Same for SPWI313 Fiery Rain on `vfxlab_dark`.
- Flash: SPWI107 Magic Missile `VfxFlashAsLight` 1 vs 0: with 1 the world brightens for the flash
  frames and the UI is not washed white. Embed two frames.
- Script fades unchanged: `dev.ps1 py "act('FadeToColor([20.0],0)')"` then a shot mid-fade is
  black exactly like with `Vfx=0`; `act('FadeFromColor([20.0],0)')` returns to normal. A
  cutscene that waits on a fade still continues (pick one from the scripts, or check that
  `GlobalTimer` fade counters are byte-identical in a debugger/log print with the toggle on and
  off).
- Section 13 checks, `tb_autotest.ps1` pass.

---

## 7. Phase 3: effect lights from one gather list, with data tables

### 7.1 The gather (`VfxSystem::Gather`)

```cpp
struct EffectInstance {
	const void* id;        // ScriptedAnimation*, Projectile*, or a child projectile
	enum class Src : uint8_t { MapVvc, ActorVvc, Projectile, Explosion, AreaAnim } src;
	ResRef key;            // ScriptedAnimation::ResName / PRO name (primary key) ...
	ResRef bam;            // ... and the BAM actually drawn (fallback key)
	Point ground;          // map units, where it stands on the floor (interpolated for actors/projectiles)
	float z;               // height of its anchor above the ground
	Holder<Sprite2D> frame;// current frame (nullable)
	bool mirrored;         // drawn with MIRRORX
	int phase;             // P_ONSET/P_HOLD/P_RELEASE, -1 for projectiles
	float emissive;        // the phase 1 gain (0 = not an emissive effect)
	bool isNew;            // not seen last frame
	const VfxEntry* entry; // table row (7.3), may be null
};
const std::vector<EffectInstance>& Gather(const Map& map, const Region& viewport);
```

- Called once per frame from `Map::DrawMap` right after `ScenePolish::BeginFrame` is moved
  **before** `CollectSceneLights` (keep the current order otherwise). Cache the list for the
  frame.
- Sources: map `vvcCells` (each `VEFObject`'s active `ScriptedAnimation`s, twins included),
  `Actor::vfxQueue` of every actor in the viewport (add a const accessor if missing), map
  `projectiles` in TRAVELLING/HIT/AWAITING_TRIGGER, and projectiles in EXPLODING/BURNING_DOWN as
  one `Explosion` instance each (centre = explosion position, frame = the centre VVC's frame or
  the first child's frame; add a const accessor `Projectile::GetExplosionInfo(Point&, int&
  radius, Holder<Sprite2D>& frame, int& children) const`), `BlendBlack` area animations.
- Viewport culling with a 400 unit margin.
- **`ScriptedAnimation::DrawAnchor(int height) const`** returns the map point the frame origin
  is drawn at: `(Pos.x + XOffset, Pos.y - ZOffset + YOffset - (IE_VVC_HEIGHT ? height : 0))`.
  `ScriptedAnimation::Draw` uses it (subtract `vp.origin`), and the gather uses it. The ground
  point is `(Pos.x + XOffset, Pos.y)`; the anchor's height is
  `z = clamp(ZOffset - YOffset, 0, 400)` plus the `IE_VVC_HEIGHT` height. The `- YOffset`
  matters: PST's foreground/background trick adds 9999 to both (section 3.1), which must cancel.
- Actor-attached VVCs use the actor's `DrawOffset` (interpolation) like the actor sprite.
- `isNew` and smoothing state live in `std::unordered_map<const void*, Track>` with the frame
  number last seen; drop entries not seen for 2 frames. A pointer that reappears after a gap is
  new.

### 7.2 Offline scan: `tools/vfx/vfxscan.py` -> `gemrb/unhardcoded/pst/vfxauto.2da`

For every BAM reachable from spells, items, PROs and VVCs (use `survey.json` / `pst_data.py`
to list them; also include every BAM named in `cgtable.2da` and the area-animation BAMs with
`BlendBlack`):

1. Decode all frames (palette applied, index 0 transparent; `ie_formats` has the BAM decoder).
2. Per frame: `lum` = mean luma over the frame's bounding box, `bright` = pixels with luma >=
   0.55 (start value).
3. Peak frame = highest `lum * bright_count`. On it: luminance-weighted mean colour (normalised
   so the max channel is 1), luminance-weighted centroid of `bright` pixels relative to the frame
   origin (`CX`, `CY` in BAM pixels, `CY` negative = above the anchor), bright area `A`.
4. `RADIUS = clamp(1.4 * sqrt(A / pi) + 60, 60, 420)`, `INTENSITY = clamp(mean luma of bright
   pixels * min(1, sqrt(A / 400)), 0.15, 1.0)`, `PEAK` = `lum` of the peak frame.
5. `KIND` from the peak colour (start values; hue in degrees, S, V of the normalised colour,
   `cv` = coefficient of variation of `lum` over frames):
   - `DARK`: mean luma of non-transparent pixels < 0.18,
   - `ELEC`: hue 180..280, S >= 0.25, `cv` >= 0.35,
   - `FIRE`: hue 0..50 or 340..360, S >= 0.35, V >= 0.5,
   - `ACID`: hue 70..160, S >= 0.35,
   - `COLD`: hue 170..240, S >= 0.12,
   - `ARCANE`: hue 240..330, S >= 0.25,
   - `HOLY`: S < 0.35 and V >= 0.8 (white, gold),
   - `BLOOD`: hue 340..15, S >= 0.5, V < 0.6,
   - else `NEUTRAL`.
6. `SHAPE`: `VLINE` if the bright bounding box is taller than 2.5x its width and taller than 200
   px, `HLINE` if wider than 2.5x its height and wider than 300 px, else `POINT`.
7. Write the 2DA (format below), rows sorted by name, floats with 3 decimals. Write
   `tools/vfx/work/review/kinds.png`: per kind, a strip of peak frames with names, so
   misclassifications are visible.

```
2DA V1.0
*
         COLOR   INTENSITY RADIUS PEAK  CX   CY   KIND  SHAPE
S070BOOM FFB050  0.820     180    0.412 2    -61  FIRE  POINT
SP31CLLT D0E0FF  0.900     260    0.380 0    -190 ELEC  VLINE
```

Python tests: synthetic BAM-like frames: an orange disc gives `FIRE`, `POINT`, the right
centroid; a tall blue-white strip gives `VLINE`; a dark smoke frame gives `DARK`.

### 7.3 Hand tables and the loader (`gemrb/core/VfxTables.h/.cpp`)

- `vfxlight.2da` (hand-written overrides, starts with a header only):

  ```
  2DA V1.0
  *
           COLOR INTENSITY RADIUS HEIGHT FLICKER SHAPE SHADOW
  ```
  Any cell `*` means "use vfxauto". `COLOR` is `RRGGBB`. `HEIGHT` overrides the light height
  above the anchor. `FLICKER`: `NONE`, `FIRE`, `MAGIC`, `ELEC`. `SHAPE`: `POINT`, `VLINE`,
  `HLINE`. `SHADOW`: 0/1 (cast shadows, `SceneLight::castsShadow`).
- `vfxkind.2da`: per `KIND` defaults: `FLICKER`, `EMIT` (phase 4), `HEAT` (phase 5), `GLOW`
  (emissive gain multiplier, 1.0). Rows `FIRE COLD ELEC HOLY DARK ACID ARCANE BLOOD NEUTRAL`.
  Start values: FIRE flicker FIRE; ELEC flicker ELEC; ARCANE and HOLY flicker MAGIC; others NONE.
  `DARK` lights have intensity 0 (dark smoke does not light anything).
- `vfxattach.2da` (phase 4/5 columns, created now with header only).
- Keys: try `EffectInstance::key` first (VVC/PRO name), then `bam`. Upper case.
- `VfxTables::Get().Find(key, bam)` returns a merged `VfxEntry` (vfxauto, then vfxkind
  defaults, then vfxlight / vfxattach overrides). Load lazily with `gamedata->LoadTable(name,
  true)`. `Reload()` drops the merged cache and the GameData table cache entries for these
  tables (find how GameData caches tables; add an eviction method if there is none).
- Python binding `GemRB.VfxReload()` in `GUIScript.cpp` calls `VfxTables::Get().Reload()`;
  `VfxLab.Reload()` calls it. Also add `tools/vfx/sync_tables.ps1` that copies
  `gemrb/unhardcoded/pst/vfx*.2da` to `C:\Games\GemRB\unhardcoded\pst\` (no build needed for
  table edits).

### 7.4 Lights from the gather (`VfxSystem::CollectLights`)

Replaces, when `VfxLights` is on, the VVC and projectile blocks at the end of
`Map::CollectSceneLights` (keep the party light, `ScenePolish::AddLights` and the `BlendBlack`
block; with `VfxLights=0` the old blocks run exactly as today).

For each instance with `emissive > 0` or a table row, and `INTENSITY > 0`:
- `ratio = clamp(GetSpriteGlow(frame).strength / PEAK, 0, 1.5)` (move `GetSpriteGlow` from the
  anonymous namespace in `Map.cpp` into `VfxSystem` and call it from both). No table row:
  today's `AddGlowLight` numbers.
- Phase envelope: onset `* min(1, t_phase / 0.15 s)`, release `* (1 - t_release / 0.4 s)`
  clamped (start values; `t_phase` from the track's first-seen time in this phase).
- Flicker (presentation clock `t` ms, `i` = hash of `id`): FIRE `0.88 + 0.12 * (0.5*sin(t*0.011
  + i) + 0.3*sin(t*0.023 + i*2.1) + 0.2*sin(t*0.047 + i*3.7))`; MAGIC `0.92 + 0.08 *
  sin(t*0.0021 + i)`; ELEC: a new value in [0.45, 1.3] from the own RNG every 50 ms; NONE 1.
- `k = INTENSITY * ratio * envelope * flicker * VfxLightGain/100 * 1.1` (1.1 start value),
  smoothed per track with tau 50 ms (exponential, presentation dt) so frame-to-frame jumps don't
  strobe (ELEC skips the smoothing).
- Position: ground `(ground.x + CX * (mirrored ? -1 : 1), ground.y)`, height `z + max(0, -CY)`
  (or `HEIGHT`). Projectiles: their position and `GetZPos()` as today.
- `SHAPE` `VLINE`: a line light from height `z` to `z + bright box height`; `HLINE`: from
  `x - w/2` to `x + w/2` at the centroid height (w = bright box width, from vfxauto: add `BW`,
  `BH` columns to the scan output for this).
- Explosions: one light at the centre, `radius = max(table radius, explosion radius * 1.3)`,
  intensity from the frame as above; plus, on `isNew`, an impact flash through
  `ScenePolish::AddFlash(x, y, z, radius * 1.4, r, g, b, 0.35 s)` (make the existing flash
  spawning a public method).
- Keep the 48 strongest by `k * radius`.

### 7.5 Line lights (`SceneLight` + `LightFS`)

- `SceneLight` gets `bool line = false; float x2 = 0, y2 = 0, z2 = 0;` (scene coordinates like
  `x, y, z`). `AddLight` gets an overload for lines; culling uses the bounding box of both ends.
- `DrawSceneLighting`: the light's quad covers both endpoints' footprints. New uniform
  `u_lightPos2` (vec4: x2, y2, z2, line flag).
- `LightFS` mode 0, both branches: replace the light position with the closest point of the
  segment in the same metric as the falloff:

  ```glsl
  vec3 lightPoint(vec3 P)
  {
  	if (u_lightPos2.w < 0.5) return u_lightPos.xyz;
  	vec3 A = u_lightPos.xyz, B = u_lightPos2.xyz;
  	vec3 s = vec3(1.0, 1.0 / 0.72, 1.0);
  	vec3 ab = (B - A) * s, ap = (P - A) * s;
  	float t = clamp(dot(ap, ab) / max(dot(ab, ab), 0.0001), 0.0, 1.0);
  	return mix(A, B, t);
  }
  ```
  Flat branch: same in 2D on `(x, y - z)`. Mirror it in `VfxMath.h` as `ClosestOnSegment` and
  test it (both ends, middle, degenerate segment).

### 7.6 Debug (`VfxDebug=3`)

After the post pass (before overhead text), draw every effect light as a ring (`DrawSoftShapes`
Ring) of its radius in its colour, lines as two dots and a line, and the instance key as text
next to it (use the overhead text font path or `DrawString` the debug overlays use).

### 7.7 Unit tests

`VfxTables` merge order (auto < kind < hand), `*` cells fall through, unknown key returns null,
`ParseColor`. `VfxMath`: flicker ranges, envelope, `ClosestOnSegment`, anchor height with the
9999 trick (`ZOffset = 9999 + 20, YOffset = 9999` gives 20).

### 7.8 Done when

- `vfxscan.py` runs over all reachable BAMs with 0 errors; counts per kind in section 15; the
  kinds sheet looked at (embed): fewer than 1 in 8 misclassified on the sheet, tune and rerun
  until true, record thresholds.
- Unit and Python tests pass.
- Lab, each with `-A "VfxLights=0" -B "VfxLights=1"` and `VfxDebug=3` single shots, embedded:
  - SPWI107: the floor under each missile is lit along the path; hit flashes light the dummy.
  - SPWI313 on `vfxlab_dark`: every bomb explosion lights the floor and the party around it,
    flickering as fire.
  - SPPR301 Call Lightning: a vertical line light; the wall or tall objects next to the strike
    are lit along its height (with `LightGeometry=1`), strobing.
  - SPWI803 Deathbolt: a horizontal line light along the bolt.
  - Casting glow: any cast; the caster is lit by their own casting glow (actor-attached VVCs are
    now lights). Check a party buff (SPPR303) lights each buffed member.
  - SPWI901 Celestial Host on `vfxlab_dark`: the scene is lit by the cinematic.
- `vfx_lab.ps1 perf -Spell SPWI901` with everything on: average frame time at most 25% above the
  phase 0 baseline and under 16.7 ms (start values). If not, lower the light budget and record.
- A real-time fight and `tb_autotest.ps1` pass; no light stays behind after an effect ends
  (`VfxDebug=3` shot 3 s after SPWI313 shows no effect lights).
- Section 13 checks.

---

## 8. Phase 4: particles thrown by effects

### 8.1 Soft shape profiles (`Video.h` `SoftShape`, `SpriteFS` texMode 3)

- `SoftShape` gets `float angle = 0.0f;` (radians, rotates the quad around its centre; ellipse
  space is unchanged) and two profiles: `Streak` (a blob stretched along x: alpha
  `(1 - x^2)^2 * (1 - y^2)^4`, use with `rx` = length, `ry` = width) and `Smoke` (blob times a
  value noise `0.6 + 0.4 * noise(v_uv * 2.5 + seed)`, `seed` in `v_param.y`). Rotation in
  `GLVideoDriver::DrawSoftShapes` when building the quad.

### 8.2 Presets (`gemrb/unhardcoded/pst/vfxpreset.2da`, start values)

```
2DA V1.0
*
            PROFILE BLEND RATE BURST LIFE LIFEVAR SPEED SPEEDVAR SPREAD UP   GRAVITY DRAG SIZE0 SIZE1 COLOR0 COLOR1 ALPHA EMISSIVE
EMBERS      BLOB    ADD   40   12    1.20 0.40    30    20       360    60   -20     0.8  2.5   0.8   FFC060 FF4010 0.95  1.2
SPARKS      STREAK  ADD   0    24    0.45 0.20    220   90       360    120  400     2.0  3.0   1.0   FFF0C0 FF9030 1.00  1.4
FROST       BLOB    ADD   30   10    1.40 0.50    25    15       360    10   30      1.5  2.0   3.5   E0F4FF 80B0FF 0.70  0.8
ARCS        STREAK  ADD   60   16    0.12 0.05    300   150      360    40   0       0.0  4.0   2.0   FFFFFF A0C0FF 1.00  1.8
MOTES_HOLY  BLOB    ADD   25   10    1.60 0.60    18    10       360    35   -10     1.0  2.0   1.0   FFF4D0 FFD080 0.80  1.0
MOTES_ARC   BLOB    ADD   25   10    1.40 0.50    22    12       360    25   0       1.2  2.0   1.0   E0B0FF 8040FF 0.80  1.0
SMOKE       SMOKE   ALPHA 12   6     2.20 0.80    14    8        360    25   -6      0.6  6.0   18.0  302830 101010 0.45  0.0
ACID        BLOB    ADD   20   14    0.90 0.30    40    20       360    20   260     1.0  2.0   1.2   A0FF60 40C020 0.85  0.9
```

Meaning: `RATE` particles/s while the source is visible, `BURST` once when it appears, `LIFE` s,
`SPEED` map units/s, `SPREAD` degrees around a random direction on the ground, `UP` initial
upward speed, `GRAVITY` (positive falls), `DRAG` per second, `SIZE0`/`SIZE1` radius at birth and
death, colours lerp over life, `ALPHA` at birth (fades to 0), `EMISSIVE` gain for the emissive
buffer (0 = alpha blended, not emissive). `vfxkind.2da` `EMIT` start values: FIRE `EMBERS`,
COLD `FROST`, ELEC `ARCS`, HOLY `MOTES_HOLY`, ARCANE `MOTES_ARC`, DARK `SMOKE`, ACID `ACID`,
BLOOD and NEUTRAL `*`.

### 8.3 Attachments (`vfxattach.2da`)

```
2DA V1.0
*
          EMIT  WHERE  PHASE RATE IMPACT GLOW SHOCK HEAT
```
`EMIT` preset (overrides the kind default, `NONE` disables), `WHERE`: `BRIGHT` (default: from
the frame's bright texels), `FEET`, `CENTER`, `TRAIL` (projectiles: behind the travel
position), `PHASE`: `ALL`/`ONSET`/`HOLD`/`RELEASE`, `RATE` percent, `IMPACT` preset burst when
a projectile explodes or hits (default `SPARKS` for FIRE/ELEC kinds, `*` otherwise), `GLOW`
emissive gain multiplier (phase 1 gain * this), `SHOCK` and `HEAT` (phase 5).

### 8.4 Emission (`VfxSystem::Emit`, `VfxSystem::DrawParticles`)

- Bright texels: `BrightTexels(frame)` cached per `Sprite2D*` like `GetSpriteGlow`: sample a grid
  (step `max(1, max(w, h) / 48)`), keep texels with luma >= 0.55 (start value), at most 96, as
  offsets from the frame origin. Mirror x for mirrored instances. Spawn point = anchor -
  frame origin + texel, on a random texel each time. The particle's ground point is the
  instance's ground point plus the texel's x, its height `z + (anchor.y - spawn.y)`.
- Emission count per frame = `RATE * RATE% * VfxParticleDensity/100 * dt` (carry the fraction
  per track), `BURST` on `isNew`. `TRAIL` spawns along the segment between last and current
  position.
- Simulate like `ScenePolish::Simulate` (ground point + height, gravity on height, drag).
  Particles with `GRAVITY > 0` that reach height 0 die (no decals; the material hit decals stay
  `ScenePolish`'s job).
- **Clock:** presentation dt (capped 100 ms), **0 while the game is paused** (find the pause
  predicate the GUI uses; turn-based combat is not "paused" and plays normally). Area change
  clears everything.
- Draw after `ScenePolish::DrawParticles`, before the light pass, as soft shapes: ADD presets
  with `SetObjectEmissive(EMISSIVE)`, ALPHA presets without. Wall stencils like
  `ScenePolish` particles (today they aren't stencilled; same behaviour, do not add it here).
- Budget 3000; when full, new particles replace the oldest of the same source first.
- `VfxDebug=4`: draw each instance's bright texels as 1 px dots in the effect's colour.

### 8.5 Unit tests

Bright texel selection on a synthetic frame (count, mirror), emission accounting (rate * dt with
carried fraction over 100 frames within 1 particle), budget replacement order.

### 8.6 Done when

- Tests pass.
- Lab A/B (`VfxParticles` 0/1) and `VfxDebug=4` shots, embedded:
  - SPWI313: embers rise from each explosion's bright area, not from the frame's empty corners;
    SPARKS burst on impact.
  - SPWI502: frost drifts from the cone's bright area.
  - SPPR301: arcs crackle along the strike.
  - SPWI219 / SPPR303: holy or arcane motes around the buffed creatures, following them when
    they walk (walk one with `act('MoveToPoint([x.y])')` during the effect).
  - Shroud of Shadows SPWI408 or any DARK kind: smoke, alpha blended, darker than the floor.
- Pause (`dev.ps1 key Space`) mid-spell: two shots 1 s apart, particles identical.
- `perf -Spell SPWI901`: within the phase 3 budget.
- Section 13, `tb_autotest.ps1` pass.

---

## 9. Phase 5: shockwaves and heat haze

### 9.1 Data and collection

- `ScenePost` gets `std::vector<DistortShape> distort;`:

  ```cpp
  struct DistortShape {
  	enum class Type : uint8_t { Ring, Heat } type;
  	float x, y;       // centre, drawing units (scene)
  	float rx, ry;     // radii, drawing units
  	float t;          // ring: 0..1 progress; heat: time in s
  	float amp;        // max offset in drawing units
  	float seed;
  };
  ```
- `VfxSystem::BuildDistortion(ScenePost&)` from the gather:
  - Ring on `isNew` explosions and on `isNew` instances whose row has `SHOCK=1`, plus every
    explosion of a projectile with explosion radius >= 100 (start value): ground ellipse at the
    ground point, `rx` from 0.2 to `max(radius, 160)` over 0.55 s (ease out), `ry = 0.72 * rx`,
    `amp` = 6 map units * `(1 - t)` (start values). Rings live in `VfxSystem` with their own
    age.
  - Heat for instances whose kind row has `HEAT=1` (FIRE start value) while visible: ellipse
    over the bright box (centre at the bright centroid, `rx = BW/2`, `ry = BH/2 * 1.3`, shifted
    up by `BH * 0.2`), `amp` = 1.2 map units (start value).
  - All scaled by `VfxDistortionStrength/100`; at most 32 shapes (largest first).

### 9.2 GL driver (`DrawScenePost`)

1. Do not return early when only distortion is wanted.
2. After copying the scene to `postTex`: if shapes exist, render them into `distTex` (`GL_RG16F`,
   half the region size, linear), cleared to 0, additive (`GL_ONE, GL_ONE`), with a new
   `PostFS` mode 4. Each shape is one quad (corners from `baseXf`), `v_uv` in ellipse space
   (-1..1), `v_param = (type, t, amp in physical pixels, seed)`:

   ```glsl
   // mode 4: distortion offsets (physical pixels) into distTex
   vec2 off = vec2(0.0);
   float d = length(v_uv);
   if (v_param.x < 0.5) { // ring
   	float r = v_param.y, w = 0.18;
   	float prof = exp(-((d - r) * (d - r)) / (w * w)) * (1.0 - r);
   	off = (d > 0.0001 ? v_uv / d : vec2(0.0)) * prof * v_param.z;
   } else { // heat: rising wobble
   	float mask = 1.0 - smoothstep(0.3, 1.0, d);
   	float n = vnoise(v_uv * 4.0 + vec2(v_param.w, -v_param.y * 1.5)) - 0.5;
   	off = vec2(n * 0.3, n) * v_param.z * mask;
   }
   o_color = vec4(off, 0.0, 1.0);
   ```
   `vnoise` = standard 2D value noise with a hash (write it in the shader, mirror in
   `VfxMath.h` for a test of its range).
3. Mode 3 (apply): read `postTex` at `v_uv + off` (off from `distTex`, scaled from half to full
   resolution), into `postTex2` (same format as `postTex`). With `VfxChroma` and `length(off) >
   0.5`: red from `v_uv + off * 1.12`, blue from `v_uv + off * 0.88` (start values). Then use
   `postTex2` as the source for the bright pass and the composite.
4. `VfxDebug=2`: show `abs(off) / 8` as red/green over the scene.

### 9.3 Done when

- Tests (noise range, ring profile at r = 0, 0.5, 1) pass.
- Lab A/B `VfxDistortion` 0/1, embedded frames:
  - SPWI807 Mechanus' Cannon and SPWI313: a ring rolls out over the floor from the blast and
    fades; straight lines in the floor art visibly bend under it.
  - Fire effects (SPWI313 cast column, SPWI117 Seeking Flames or Ignus' own fire): heat shimmer
    above the flames, moving upward, nothing below them.
  - `VfxDebug=2` shot.
- The UI, overhead text and fog edge are not distorted (UI is drawn after; check one frame
  with a ring near the screen edge).
- `perf -Spell SPWI807` within budget. Section 13, `tb_autotest.ps1` pass.

---

## 10. Phase 6: creature auras, showcase tuning, owner review

### 10.1 Aura (`VfxAura`)

- Actors with an active colour glow or pulse (opcodes 0x08, 0x09 and the other `RGBModifier`
  sources in `CharAnimations`; find the accessor for the active modifier and its colour and
  phase) get the existing hover outline pass drawn **additively** in that colour, radius 2.5
  logical px, with emissive gain 0.8 and the outline's alpha following the pulse (start
  values).
- `GLVideoDriver`: allow the outline pass with `GLBlend::Add` and a soft edge: in the outline
  branch of `SpriteFS`, weight the 12 samples by `1 - distance/radius` instead of `step`
  when the batch is additive (keep the hover outline exactly as is).
- The hover outline still wins when the creature is hovered.

### 10.2 Showcase tuning

For each of the 12 showcase spells, look at its gallery entry and write `vfxlight.2da` /
`vfxattach.2da` rows only where the automatic result is wrong (wrong colour, light too weak or
too strong, particles on the wrong kind, a ring where none belongs). Record each row and its
reason in section 15. No code changes for a single spell.

### 10.3 Done when

- SPWI219 Power of One and SPPR105 Halo of Lesser Revelation: aura visible and pulsing on the
  target (frames embedded); hovering still shows the normal outline.
- `vfx_lab.ps1 gallery` (A = `Vfx=0`, B = `Vfx=1`) regenerated; `shots\vfx\index.html` written.
- Ask the owner to open the gallery (give the path) and to try `vfx_lab.ps1 play`. Their notes
  go into section 15 and are fixed through tables where possible.
- Final `perf` on SPWI901 and SPWI914 within budget. Section 13 checks. `tb_autotest.ps1`
  passes. A real-time fight with spells (`tb_flee_cast.ps1` with `Turn Based Combat=0` or the
  staged-fight script) shows no stuck lights, particles or rings afterwards.

---

## 11. Files touched (summary)

New:
- `gemrb/core/VfxSystem.h/.cpp`, `gemrb/core/VfxTables.h/.cpp`, `gemrb/core/VfxMath.h`
- `gemrb/tests/core/Test_Vfx.cpp`
- `gemrb/unhardcoded/pst/vfxauto.2da` (generated), `vfxlight.2da`, `vfxkind.2da`,
  `vfxattach.2da`, `vfxpreset.2da`
- `gemrb/GUIScripts/VfxLab.py`
- `tools/vfx_lab.ps1`, `tools/vfx/*.py`, `tools/vfx/sync_tables.ps1`, `tools/vfx/tests/`

Changed:
- `gemrb/core/Video/Video.h` (emissive gain, `ScenePost` fields, `SceneLight` line, `SoftShape`
  angle and profiles, `DistortShape`)
- `gemrb/plugins/GLVideo/GLVideo.h/.cpp`, `GLShaders.h` (emissive attachment, per-buffer blend,
  composite, bloom, smooth filter, line lights, distortion, outline aura, burst/perf hooks)
- `gemrb/core/Map.cpp` (gather call, emissive gains, light collection switch, particles,
  distortion, debug), `gemrb/core/ScriptedAnimation.h/.cpp` (`DrawAnchor`),
  `gemrb/core/Projectile.h/.cpp` (`GetExplosionInfo`), `gemrb/core/Scriptable/Actor.h/.cpp`
  (vfxQueue accessor, emissive gains, aura), `gemrb/core/Particles.cpp`,
  `gemrb/core/ScenePolish.h/.cpp` (`AddFlash`, emissive for additive kinds, `BuildPost`
  threshold), `gemrb/core/GlobalTimer.h/.cpp`, `gemrb/core/GUI/WindowManager.cpp`,
  `gemrb/plugins/PSTOpcodes/PSTOpcodes.cpp` (fade source only),
  `gemrb/plugins/GUIScript/GUIScript.cpp` (`VfxReload`, maybe `GetAreaActors`)
- `gemrb/core/CMakeLists.txt`, `gemrb/CMakeLists.txt` (test list), `gemrb/GemRB.cfg.sample.in`,
  `tools/dev_settings.ini`, `.gitignore`, `NOTES.md` (add a "Spell visuals" section at the end
  of the work, like the phase notes)

---

## 12. Out of scope: known broken spell visuals (ask the owner, do not fix here)

The survey found visuals that never play in GemRB because of GemRB's reconstructed data. Fixing
them changes what spells do (fragments carry damage payloads), so they need the owner's
decision and their own plan:

- `LSTORM` (Chain Lightning Storm), `BSTORM` (Blade Storm), `FIREICE` (Fire and Ice: the ice
  half), `ISWARM`, `CHROMORB`, `IGNUSORB` name fragment projectiles but lack `PAF_SECONDARY`, so
  `Projectile.cpp` (~1785) never spawns them.
- `DBOLT.SPL` (Deathbolt payload) plays MultipleVVC `DBOLT`, which doesn't exist.
- `BSPHERE` (Blacksphere), `FURY` (Abyssal Fury), `<STONED>` (Meteor fragments) have no PRO file.
- `FIREBALL`, `GOINVUL`, `SKMOB`, `TLAUGH` use `areapro.2da` explosion type 0 whose animations
  don't exist in PST.

In reports, a showcase spell affected by these is marked "partly missing in GemRB". Not fixing
them is correct for this plan.

Also deferred, ask first, not part of this plan:
- Upscaling spell BAMs with the `UPSCALE_PLAN.md` pipeline.
- Scaling the 640x480 cinematics up to fill the larger viewport (they were drawn for a 640x480
  screen and look small at 1280x720).

---

## 13. Checks at the end of every phase

1. `Vfx=0`: `vfx_lab.ps1 cast -Spell SPWI107 -Label off0 -Set "Vfx=0"` and the same for SPWI313.
   Their sheets look the same as the phase 0 baseline in `shots\vfx_baseline\` (side by side
   with `make_sheet.py --compare`, embed). An idle frame with no effect playing (same save,
   same camera, party not moving): mean absolute difference to a phase 0 idle frame below
   1/255 per channel (`measure.py --diff`, add the option in phase 0).
2. Every toggle of the phase at 0 turns off only its feature (one shot each, look).
3. `Test_gemrb_core` full run passes.
4. `tools\tb_autotest.ps1` passes.
5. `gemrb.log` has no new errors or warnings from the new code during the lab runs.

---

## 14. Reporting to the owner after each phase

First line: what is now true. Then bullets: what was checked in game (embedded sheets, GIF
paths, measure numbers), what was only unit-tested or compiled, what nobody has seen yet, the
files changed, and "nothing is committed".

---

## 15. Progress

- [ ] Phase 0: VFX Lab, lab saves, baseline gallery and perf
- [ ] Phase 1: emissive buffer, lit composite, emissive bloom, smooth effects, GLOWING
- [ ] Phase 2: spell darkening and flashes through the light pass
- [ ] Phase 3: gather, vfxscan, tables, effect lights, line lights, explosion lights
- [ ] Phase 4: particles from bright texels, presets, attachments
- [ ] Phase 5: shockwaves, heat haze, chroma
- [ ] Phase 6: auras, showcase tuning, owner review

Notes (spell numbers, final start values, measure numbers, kind counts, table rows and reasons,
perf numbers, owner feedback):

- (none yet)
