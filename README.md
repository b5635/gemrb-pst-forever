# Planescape: Torment Forever (a GemRB fork)

A heavily modified fork of [GemRB](https://gemrb.org) that turns classic
*Planescape: Torment* into a modern-looking game with turn-based combat, while the
game itself stays classic PST: the original data, rules, scripts and dialogue.

This is a **large deviation from upstream GemRB**. It is built for one game (PST), on
Windows, and it is not aiming to stay mergeable. Upstream GemRB is still the base
(see [Upstream](#upstream-gemrb)).

> You need your own copy of *Planescape: Torment*. No game data, upscaled art or
> Enhanced Edition files are in this repository.

**Compatibility, honestly:**

- **Classic PST only.** Other Infinity Engine games (Baldur's Gate, Icewind Dale, ...) probably
  do not work with this fork, or are entirely untested. Many changes are PST-specific.
- **No Enhanced Edition support.** The fork uses the EE *interface* (art and layouts, read from
  your own EE install by our tools), but the game it runs is the classic one, and the classic
  install is required. Running on EE data alone is not supported.
- **Pull requests welcome.** If you want to make it work on EE data without needing the
  original game, or on other IE games, you are free to send a pull request.

## What it does

| Area | What you get |
|---|---|
| **Turn-based combat** | Initiative, per-creature movement budget, full attack rounds swing by swing, opportunity attacks, surprise, delay, withdraw, run, block, trip, knockdown, a tactical AI that reads PST's own scripts. Spells resolve inside the caster's turn. |
| **Combat UI** | Turn timeline, d20 dice panel, hover hit-chance panel with the full THAC0 breakdown, enemy HP/buff bar, floating combat text, "Your Turn" banner, one hotbar for attacks, items, spells and abilities. PST's own art and bitmap fonts. |
| **Upscaled art** | AI-upscaled (ESRGAN, 2x) area backgrounds, GUI, and all creature/effect sprites, drawn at the original logical size. Hit tests and scripts still use the original pixels. Live palette recolouring works on upscaled sprites. |
| **Modern renderer** | OpenGL 3.3 driver: render at window resolution, smooth zoom and pan, frame-rate interpolation, sharpened filtering. |
| **Lighting** | Ambient and dynamic lights, spell and projectile glow, bloom, shadows, outlines, grading, vignette, ambient particles, screen shake. Light sources, height, normal and AO maps are generated automatically from PST's pre-rendered backgrounds, with no hand authoring. |
| **Enhanced Edition UI** | PST:EE's screen layouts and art (4K plates, remade buttons) rebuilt on GemRB's classic screen logic: main menu, popups, character creation, load/save, options, inventory, character record, spell books, journal, area and world map. |
| **Bestiary fixes** | Story-driven bestiary text, alphabetical lists, empty-list placeholder, remastered creature pictures. |
| **Party of 8** | The Nameless One plus all seven companions. |

Every visual feature has a `GemRB.cfg` toggle and falls back to the original look when off.

## Status

Legend: done, partial, not started.

### Done

- **Renderer** (OpenGL, hi-res, smooth camera, interpolation) and **lighting/polish** passes.
- **Upscaling pipeline** and engine support. All 1871 sprite BAMs, GUI and areas are
  upscaled (about 4.9 GB of sprites alone) and drawn by the GL driver.
- **Scene generation:** light sources (1384 over 123 areas), height maps, normals, sprite AO,
  key light.
- **Turn-based core:** director with takeover/handback, turn sequence, per-creature combat
  clock (durations, regeneration and poison follow turns), AI analyzer over all 2,236 PST scripts,
  tactical AI, reactions, maneuvers, dice panel, hover panel, timeline, hotbar, saving-throw
  dice, combat vision, movement accuracy (the preview line is the walk).
- **Regression tooling:** unit tests plus `tb_autotest.ps1`, which stages fights from saves and
  fails on a crash or stalled turn.
- **EE UI, phases 0 to 15:** reader/decoder for EE data, converter, layout runtime, and the
  screens listed above, with EE art drop-in twins for spell icons, world map and area maps.

### In progress / partial

- **EE options sub-pages** (sound, graphics, gameplay, keys) still use the classic windows.
- **EE screens that need more in-game checking:** several buttons and edge paths were built
  but not clicked through.
- **Turn-based AI:** scripts run for real once per turn rather than a dry-run decide; multi-turn
  flee is re-decided each turn; modal states such as bard song still run on world time.
- **In-game pass of upscaled GUI and areas** (sprites were checked; GUI and areas need a
  dedicated side-by-side pass).

### Not done yet

- EE stores, dialog, container, party pick and death screens (phases 16, 17).
- EE world HUD (phase 18, needs a written proposal first).
- Turn-based: hotbar hotkeys and drag-to-arrange, smooth path / reach outline / spell range and
  AoE overlays, UX polish pass, autotest cases for the scripted C6/C7 fights.
- **Spell and effect visuals overhaul**: written, not started.
- Cursors and paper dolls as hi-res art, cutscene (movie) upscaling, fonts at higher resolution.
- Linux and macOS support for the fork's additions (untested).

## Requirements

**To play**

- A legitimate install of the classic *Planescape: Torment* (GOG or original release), with
  these community patches and mods applied (the fork is developed against this setup):
  - [Official patches for Planescape: Torment](https://www.gibberlings3.net/files/file/1009-official-patches-planescape-torment/) (Gibberlings3), to bring the game to 1.1
  - [The Platter](https://sorcerers.net/Games/Torment/Platter/index.php) (Sorcerers.net), the Planescape: Torment Fixpack and Unfinished Business restoration
  - [Qwinn's PST Tweak Pack v4.12](https://www.moddb.com/games/planescape-torment/downloads/qwinns-pst-tweak-pack-v412) (ModDB)
- Windows 10 or 11, 64-bit.
- A GPU with OpenGL 3.3. Upscaled art needs disk space and VRAM: plan on **about 5 GB** of
  free disk for `upscaled\`, plus the optional `ee_ui\` folder (about 175 MB of PVRZ pages).
- A window larger than 1280x720, or the mouse-wheel zoom, is where the upscaled art pays off.
  The logical resolution is 1280x720 (1920x1080 is also supported by the EE UI).

**To build**

- Visual Studio 2019 Build Tools (Desktop C++ workload), CMake 3.25 or newer, Git.
- [vcpkg](https://vcpkg.io) in manifest mode (`platforms/windows/vcpkg.json`): zlib, SDL2,
  SDL2_mixer, Python 3, OpenAL Soft, libpng, ogg, vorbis, FreeType, libiconv, glew, gtest.

**To regenerate the art (optional, GPU)**

- Python 3.13, an NVIDIA GPU with CUDA (developed on an RTX 4060 Ti, 16 GB).
- PyTorch with CUDA, plus `tools/upscale/requirements.txt` (spandrel, pillow, numpy, tqdm,
  einops, safetensors). `tools/upscale/setup_env.bat` sets it up.
- An ESRGAN-family model such as `4x-UltraSharp` (not included; download it yourself).
- For the EE UI: your own install of *Planescape: Torment: Enhanced Edition*. It is read only by
  `tools/eeui/` and never mounted as game data.

## Building and running

```
build_install.bat          builds Release and installs to D:\Games\GemRB
build_install.bat run      same, then starts the game
```

The install folder and the game path are set at the top of `build_install.bat` and in
`tools/dev_settings.ini`, which is forced into the installed `GemRB.cfg` on every deploy.
Edit those two files for your machine before the first build. New features get their
"on" line in `dev_settings.ini`.

Tests:

```
cmake --build build --config Release --target Test_gemrb_core
build\gemrb\Release\Test_gemrb_core.exe --gtest_filter=CombatDirector*:TurnMovement*
```

(put the install folder on `PATH` first).

In-game regression run: `tools\tb_autotest.ps1`. Driving the installed game from scripts:
`tools\dev.ps1` (start, py, click, key, shot, log, crash).

## Generating the upscaled art

Output goes to `<install>\upscaled\` (outside the repo and the game data).

```
tools\upscale\Upscale.bat                 window with status, continue, redo stale
tools\upscale\run_upscale.bat --categories gui,areas,sprites
```

The pipeline is resumable: stop it any time and run it again.

EE-derived art and layouts: `tools\eeui\run_eeui.bat`.

## Key settings

All in `GemRB.cfg`.

| Setting | Effect |
|---|---|
| `VideoDriver=opengl`, `GLHighResolution=1` | Modern renderer at window resolution |
| `UpscaledGUI`, `UpscaledAreas`, `UpscaledSprites` | Draw upscaled art per category |
| `EEUI` | Enhanced Edition screen layouts (falls back to classic if `ee_ui\` is missing) |
| `Lighting`, `BakedLights`, `LightGeometry`, `Bloom`, `ColorGrading`, `Vignette` | Lighting and polish passes |
| `Turn Based Combat` and the other `Turn Based ...` keys | Turn-based combat and its options |
| `MaxPartySize=8` | Full party |

## Upstream GemRB

GemRB (Game Engine Made with preRendered Background) is a portable open-source
reimplementation of the Infinity Engine, covering Baldur's Gate, Icewind Dale,
Planescape: Torment and more. This fork builds on it and keeps its license (GPL, see
`COPYING`). Everything not mentioned above, including the other games, behaves as upstream and
is not a focus here.

- [GemRB homepage](https://gemrb.org) and [documentation](https://gemrb.org/Documentation)
- [Upstream repository](https://github.com/gemrb/gemrb), [bug tracker](https://github.com/gemrb/gemrb/issues/new/choose)
- [GemRB forum](https://www.gibberlings3.net/forums/forum/91-gemrb/), [Discord](https://discord.gg/64rEVAk) (Gibberlings3 server), [IRC](https://web.libera.chat/#GemRB) (#GemRB on Libera.Chat)
- [IESDP](https://gibberlings3.github.io/iesdp/), Infinity Engine file format documentation
- [Near Infinity](https://github.com/NearInfinityBrowser/NearInfinity/wiki), data file viewer and editor

Please do not report problems from this fork to upstream.
