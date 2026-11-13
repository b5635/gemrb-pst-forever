# PST graphics overhaul — working notes

Goal: graphics-only overhaul of GemRB for Planescape: Torment (rendering, camera, presentation).
Reference look: Godot remake at `E:\GitHub\pst-forever\game` (`shaders/tiles.gdshader`, `sprite.gdshader`, `post.gdshader`, ROADMAP "Presentation").
Rule: every visual feature has a `GemRB.cfg` toggle and falls back to the original look when off.

## Status

| Phase | State |
|---|---|
| 0. Windows build, run PST, baseline screenshot | done |
| 1. GPU renderer plugin, offscreen scene + composite, palette lookup in shaders | next |
| 2. Resolution / smooth zoom & pan / sharpened bilinear | — |
| 3. Frame-rate interpolation (camera, actors, projectiles) | — |
| 4. Lighting (ambient, point lights, actor tint, optional depth/normal maps) | — |
| 5. Polish (shadows, rings, outlines, bloom, grading, vignette, particles, shake, ambience) | — |

## Phase 0 — build on Windows

Toolchain: MSVC (VS 2019 Build Tools, x64) + vcpkg in manifest mode (`platforms/windows/vcpkg.json`), CMake 4.3.
Chosen over MSYS2 because the tree was already configured this way and vcpkg ships `sdl3` for phase 1.

Exact steps (fresh machine):

1. Install VS 2019 Build Tools (Desktop C++ workload), CMake ≥ 3.25, Git.
2. `git clone https://github.com/microsoft/vcpkg D:\vcpkg` then `D:\vcpkg\bootstrap-vcpkg.bat`.
3. Configure (vcpkg installs dependencies from the manifest on first configure):
   ```
   cmake -S D:\gemrb -B D:\gemrb\build -G "Visual Studio 16 2019" -A x64 ^
     -DCMAKE_TOOLCHAIN_FILE=D:/vcpkg/scripts/buildsystems/vcpkg.cmake ^
     -DVCPKG_MANIFEST_DIR=D:/gemrb/platforms/windows ^
     -DSDL_BACKEND=SDL2 -DCMAKE_INSTALL_PREFIX=D:/Games/GemRB
   ```
4. Build + install: `build_install.bat` (Release, `/m:1` to avoid compiler heap exhaustion; preserves the
   installed `GemRB.cfg`). `build_install.bat run` also starts the game.
5. `D:\Games\GemRB\GemRB.cfg`: `GameType=pst`, `GamePath=CD1=C:\Program Files (x86)\Black Isle\Torment\`.

## Screenshots / test harness

- `GEMRB_AUTOLOAD=<n>` env var: PST `Start.py` skips the menus and loads save slot *n* (dev only, no effect when unset).
- `tools\pst_shot.ps1 -Out shots\x.png -Save 0 -Wait 30` launches the installed game with that save,
  captures the client area, then kills the process. Same save/camera across phases for comparison.
- Baseline: `shots/phase0_baseline.jpg` (save 0 = "The Hive", original SDL2 renderer, 800×600 logical scaled to window).

## Decisions

- Keep the existing SDL2 software-ish renderer (`SDLVideo`) untouched as the fallback; the new renderer is a separate video plugin.

## Known shortcuts

- Screenshot capture is a desktop grab of the window (needs the window visible/unoccluded).
