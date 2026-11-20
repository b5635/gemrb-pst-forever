# PST graphics overhaul — working notes



Goal: graphics-only overhaul of GemRB for Planescape: Torment (rendering, camera, presentation).

Reference look: Godot remake at `E:\GitHub\pst-forever\game` (`shaders/tiles.gdshader`, `sprite.gdshader`, `post.gdshader`, ROADMAP "Presentation").

Rule: every visual feature has a `GemRB.cfg` toggle and falls back to the original look when off.



## Status



| Phase | State |

|---|---|

| 0. Windows build, run PST, baseline screenshot | done |

| 1. OpenGL 3.3 renderer plugin, offscreen composite, palette lookup in shaders | done |

| 2. Resolution / smooth zoom & pan / sharpened bilinear | done |

| 3. Frame-rate interpolation (camera, actors, projectiles) | done |

| 4. Lighting (ambient, point lights, actor tint, optional depth/normal maps) | done |

| 5. Polish (shadows, rings, outlines, bloom, grading, vignette, particles, shake, ambience) | done |



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

     -DSDL_BACKEND=SDL2 -DCMAKE_INSTALL_PREFIX=C:/Games/GemRB

   ```

4. Build + install: `build_install.bat` (Release, `/m:1` to avoid compiler heap exhaustion; preserves the

   installed `GemRB.cfg`). `build_install.bat run` also starts the game.

5. `C:\Games\GemRB\GemRB.cfg`: `GameType=pst`, `GamePath=CD1=C:\Program Files (x86)\Black Isle\Torment\`.



## Deploy: every feature on

`build_install.bat` ends by running `tools\apply_dev_settings.ps1`, which forces the keys in `tools\dev_settings.ini`
into the installed `GemRB.cfg` (and `pst_saves\gem-torment.ini`). Every new feature toggle gets its "on" line there in
the same change, so the installed game always runs with everything enabled.

## Screenshots / test harness



- `GEMRB_AUTOLOAD=<n>` env var: PST `Start.py` skips the menus and loads save slot *n* (dev only, no effect when unset).

- `tools\pst_shot.ps1 -Out shots\x.png -Save 0 -Wait 30` launches the installed game with that save,

  captures the client area, then kills the process. Same save/camera across phases for comparison.

- Baseline: `shots/phase0_baseline.jpg` (save 0 = "The Hive", original SDL2 renderer, 800×600 logical scaled to window).



## Phase 1 — GLVideo plugin



`gemrb/plugins/GLVideo` (driver name `opengl`). Enable with `VideoDriver=opengl` in GemRB.cfg; `VideoDriver=sdl`

(the default) is the untouched original renderer.



- SDL2 window/input + OpenGL 3.3 core via GLEW (both already in the vcpkg manifest). Input code is adapted from the

  SDL2 driver; gamepad helpers are compiled in from `plugins/SDLVideo`.

- One batched shader (`GLShaders.h`) draws everything. Paletted sprites (TIS, BAM, fonts) live on the GPU as

  `GL_R8UI` index textures; palettes go into a per-frame 256×2048 atlas keyed by the palette's content hash, so palette

  swaps, tints (COLOR_MOD/ALPHA_MOD), GREY/SEPIA and colour keys are all shader work, no re-uploads.

- Filtering happens after the palette lookup: 4-tap sharpened bilinear in premultiplied space (crisp at 1:1).

- Every VideoBuffer is an FBO; wall stencils are sampled per pixel (channel select + 50% dither like the GL backend).

  Window buffers are composited into a logical-screen FBO, which is presented to the window with the same sharp filter

  (letterboxed) plus brightness/contrast.

- Blend modes mirror the SDL2 driver's (BLENDED/ADD/MOD/MUL/SRC/DST/ONE_MINUS_DST, colour-key-0 hack included).

- Movies: YV12/RGB555/PAL8/RGBA8888 converted on the CPU into the buffer texture.

- Dev capture: `GEMRB_GL_SHOT="file.bmp;seconds"` writes the presented frame (used by `tools/pst_shot.ps1`, no window

  focus needed). `tools/crop.ps1` crops/zooms shots for comparison.



Bug worth remembering: `PixelFormat(bpp, masks…)` leaves shifts/loss at 0. The SDL sprite class silently rebuilt the

format from the SDL surface; ours must normalize it, or palette gradients read via `GetPixel` come out wrong (yellow

actor colours).



## Phase 2 — resolution, smooth zoom & pan

All GL-only; `VideoDriver=sdl` is unchanged (it keeps the old oversized scale buffer for EE zoom).

- **Render scale.** Window buffers (`DISPLAY`/`DISPLAY_ALPHA`) and the screen composite are allocated at the presented
  size (logical × fit scale, 1–4×) and rescaled when the window changes. Every vertex goes through a per-target
  transform (logical px → physical px), so the UI and map art are filtered once, at the final resolution.
  `GLHighResolution=0` in GemRB.cfg renders at the logical size and upscales at present time (phase 1 look).
- **Scene transform** (`Video::BeginScene/EndScene`, `SceneTransform` in `Video.h`). While GameControl draws the
  map, coordinates are map units relative to an integer origin; the driver maps them with a float zoom and a
  sub-pixel offset. The core draw code didn't change; `Video::DrawingClip()` gives clipping code (fonts, blits) the
  visible region in map units.
- **Wall stencils** stay in map units (`BufferFormat::MASK`, never scaled): the shader maps the fragment back to a
  stencil texel (`u_stencilA/B`), and the 50% dither checker is in stencil pixels so it keeps its original size.
  The screen stencil only grows (rounded to 64) so zoom animations don't recreate it every frame.
- **Camera** (`GameControl::Camera`). The logical viewport/zoom that scripts and game logic use is untouched; what is
  shown eases toward it (pan τ≈60 ms, zoom τ≈80 ms in log space). Mouse picking goes through the shown camera.
  Wheel zoom pins the map point under the cursor. Snaps on area change, big jumps and screen shakes.
  `SmoothCamera=0` disables easing (still sub-pixel/continuous-zoom capable).
- **Filtering.** Sharpened bilinear only while magnifying; plain bilinear when minifying (less shimmer zoomed out).
- Dev hook: `GEMRB_DEV_ZOOM=<25..160>` sets the zoom on game load (for `tools\pst_shot.ps1`).
  Shots: `shots/phase2_full.png` (1440p), `phase2_zoom60.png`, `phase2_zoom150.png`.
- Mouse-wheel zoom needs `Zoom Lock = 0` (PST defaults to locked).

## Phase 3 — frame-rate interpolation

Game state still advances in fixed ticks (`Time.ticksPerSec`, 15/s); frames are drawn at display rate. GL-only,
`FrameInterpolation=0` in GemRB.cfg turns it off.

- `core/Interpolation.*`: `TickInterpolation::BeginTick` runs right before every game update (`Interface::GameLoop`)
  and bumps a serial; `Map::CaptureDrawPositions` makes every actor and projectile of the current area remember its
  exact position (`Pos` + the walker's carried sub-pixel fraction). While drawing, an object captured on the current
  serial is shown at `prev + (now - prev) * alpha`, alpha = time since the tick / tick length.
- Applied through the scene's per-object offset (`Video::SetObjectOffset`) around `Actor::Draw` (sprite, circle,
  attached VVCs), the actor's overhead text and travelling projectiles. Wall stencils use the un-offset transform, so
  occlusion stays anchored to the world. Game logic, picking and scripts only ever see `Pos`.
- Snaps (no interpolation) on jumps over 64 map units (actors) / 256 (projectiles), area changes and objects that
  weren't there at the last tick. Cost: one tick (≈66 ms) of display latency on movement.
- Camera: already per-frame since phase 2 (eased toward the logical viewport; edge/key scrolling is per frame).

## Phase 4 — lighting

GL-only light pass, `Lighting=0` in GemRB.cfg turns it off (original look).

- `Map::DrawMap` calls `Map::CollectSceneLights` + `Video::DrawSceneLighting` after actors, animations, spells and
  weather, before fog and overhead text (text/fog/UI are never lit). Drivers without scene support ignore it.
- GL (`GLVideo.cpp` `DrawSceneLighting`, `LightFS` in `GLShaders.h`): a half-resolution RGBA16F light buffer is
  cleared to the ambient colour, every light is added as a soft ellipse (`(1-r²)²`, squashed 0.72 vertically for the
  isometric ground); the scene region is copied out and drawn back multiplied by it. Light above 1 rolls off softly
  to `maxLight`; very bright pixels (painted fires, spell glows) keep part of their brightness.
- Ambient by area type: dungeon 0.66, indoor/city 0.76, outdoor 0.86, slightly cool. `LightingAmbient=<0..200>`
  scales the darkening (0 = none).
- Lights: optional warm party light on every living PC (off by default, `PartyLight=1` on); `DynamicLights=0` turns off the rest:
  area animations with BlendBlack (fires, braziers, portals), additive/light-spot VVCs and flying projectiles (light
  spot from the PRO, or the frame colour of brighten/blend projectiles). Colour and strength come from the
  luminance-weighted average of the current frame (cached per sprite), so flickering fires flicker their light.
- Actor tint: the original lightmap tint at the feet is kept; actors also pick up point lights since the pass is
  per pixel over everything. Moving lights use the phase 3 interpolated positions.
- **Generated depth + normal maps** (`LightGeometry=1`, `LightNormalStrength=0..100`, default 80). The game has no
  such data, so both are built on the GPU every frame:
  - Depth = the ground line under every pixel. Sprites (actors, standing area animations, VVCs, projectiles) write
    their feet line (`Video::SetObjectDepth`) into a second colour attachment of the scene buffer while they are
    drawn (`SceneBegan`/`SceneEnding` attach/detach it; wall-stencilled pixels don't write). Wall polygons are
    rasterised into a wall depth map from their base lines (no baseline: polygon bottom), nearest wins.
    Pixels above their ground line are vertical surfaces at height = ground − y.
  - Normals = luminance gradient of the drawn art (one map unit apart), applied on top of the surface orientation
    (floor faces up, walls/sprites face the viewer).
  - Each light is evaluated per pixel in 3D (lights have a height: party 45, fires ~⅓ of their sprite), with
    wrapped Lambert shading taken relative to a flat floor, so the overall falloff matches the flat version.
    The light buffer is full resolution in this mode (half otherwise).
  - `GEMRB_LIGHT_DEBUG=1`: shows the light buffer instead (red = vertical surface, green = falloff, blue = normal x).
- Shots: `shots/phase4_on.png` (flat), `phase4_geom.png` (depth/normals), `phase4_off.png`, `phase4_debug.png` (save 0).

## Phase 5 — polish

GL-only (scene transform drivers); everything lives in `core/ScenePolish.*` plus three driver hooks in `Video.h`:
`DrawSoftShapes` (antialiased discs, soft blobs, glowing rings; shader texMode 3), `BlitSpriteQuad` (a frame on any
quad, per-corner colour) and `DrawScenePost`. Presentation only: own RNG, never touches game state or the game RNG.

- Order in `Map::DrawMap`: scene lights are now collected before objects (shadows need them) → per actor
  `Actor::DrawPolishShadows` before the sprite → weather → particles → lighting → fog → post pass → text.
- **Shadows**: soft oval under the feet (`ContactShadows`, default off). Silhouettes fall the same
  way from a fixed up-screen light, flattened onto the ground (`LightShadows`, needs `Lighting=1`).
  A nearby fire, spell or projectile adds a second cast away from itself. Party lights only brighten
  the scene. Skipped for the dead, lying stances, birds, invisible enemies.
  `SpriteShadows=0` clears the baked palette-index-1 oval on world sprites. A few creatures painted that
  oval in ordinary black (the abishai) and keep it. Spell effects and paperdolls are unchanged.
- **Rings** (`SelectionRings`): antialiased ellipse in the creature's colour with a dark backing ring; selected =
  thicker + glow, hovered = pulsing glow. Off = PST's bitmap circles.
- **Hover outline** (`HoverOutline`): outline pass in the sprite shader (12-direction alpha dilation in texels,
  grown quad under the sprite), wall-stencilled like the sprite. `Video::SetObjectOutline`.
- **Hits** (`HitParticles`): `Actor::Damage` → elemental damage gets sparks coloured by damage type (bounce once),
  plus a short impact light (flash) fed into the lighting pass. Crits are bigger. Physical hits no longer spark.
- **Material hits** (`CustomBlood`, `BloodLinger` seconds, default 30): replace the original blood BAMs
  (`Actor::PlayDamageAnimation` blood cases, incl. the generic gory death; PST personal crits stay).
  Material = PST resdata.ini `armor` (the hit sound set) via `unhardcoded/pst/hitmat.2da` (`ARMOR<n>` rows,
  `ANIM<id>` overrides): flesh/leather → blood spray that lands as floor stains (drawn before actors, dry
  darker, fade out), armoured → blood + sparks, armoured skeleton → sparks + bone, hollow armour (Vhailor) →
  sparks, bone → dust + chips that bounce and stay, stone → grit + chips, spirit → wisps, construct → sparks +
  metal bits, shadow → dark smoke, fire (Ignus) → embers. Other games: medium/heavy armour level = armoured.
- **Ambience** (`AmbientParticles`): floating dust (indoors, warm) / ash (outdoors, grey) at a fixed density over
  the view; embers rising from warm glowing area animations (needs `DynamicLights`).
- **Shake**: `SmoothShake=1` stops script shakes from jittering the logical viewport; the shown camera gets smooth
  noise with the same amplitude and an envelope instead. `ImpactShake`: party members losing ≥8% max HP and
  crits add trauma (decays in ~0.6 s). Picking always uses the steady camera.
- **Post** (`Bloom`, `BloomStrength=0..200` (55), `ColorGrading`, `Vignette=0..100` (35)): bright pass at half
  resolution with a soft knee, two widening separable gaussian rounds, screen-ish add; grading per area type
  (dungeon cool/desaturated, outdoor smoggy rust, indoor warm): saturation, contrast, lift/gain; vignette from the
  pst-forever `post.gdshader`.
- Dev: `tools\dev.ps1 move X Y` hovers; toggles can be flipped live with `GemRB.SetVar('Bloom', 0)` via `dev.ps1 py`.
- Shots: `shots/phase5_on.png`, `phase5_hover.png`, `phase5_hit.png` (save 0).
- Not done: per-area grading/ambience overrides from a table, particles behind walls aren't stencilled.

## Upscaled art

Offline 2x RGBA twins for GUI and area art (`UPSCALE_PLAN.md`, `tools/upscale`). The sprite keeps its
original pixels for hit tests, palettes and scripts. Only the OpenGL driver draws the twin, at the
original logical size, so a larger window or a zoomed map looks sharper. `UpscaledGUI`,
`UpscaledAreas` and `UpscaledSprites` are the toggles. Sprites are on for a trial of the
Nameless One's default body (`DNOFB`: walk, stand, attack, and the other stances).
Fonts are indexed pages, not colour bitmaps: the palette tint and the inverted pass still run,
on a 2× index image.
`UpscalePath` defaults to `<GemRB exe dir>/upscaled` and is never the game install. `build_install.bat`
does not touch that folder.

## Decisions



- Keep the existing SDL2 renderer (`SDLVideo`) untouched as the fallback; the new renderer is a separate video plugin.

- SDL2 + OpenGL 3.3 instead of the SDL3 GPU API: GemRB's whole input/window layer is SDL2 and reusable as is, GLSL compiles

  at runtime (no SPIR-V toolchain, no Vulkan-only limitation on Windows, shaders can be iterated without rebuilding),

  and GL 3.3 covers everything phases 1–5 need (FBOs, integer textures, palette lookups, post passes). SDL3 would

  have meant porting ~1000 lines of input code, a shader compiler in the build and two SDL versions in one process.

- Where the old core drawing path fights the new features (integer points, viewport maths spread over GameControl and

  Map, wall stencil hacks) it gets rebuilt rather than patched.



## Known shortcuts



- With `VideoDriver=sdl` the screenshot script falls back to a desktop grab (needs the window visible/unoccluded).



## Testing and crash tools

- `tools\dev.ps1` drives the installed game: `start [-Save N]`, `py "<python>"` (runs inside the game; helpers `here()`, `act(action, slot)`, `goto(area, x, y)`, `pc()`), `click X Y [-Right]`, `key Name`, `shot [out.png]`, `status`, `log`, `crash`, `stop`.
- In-game side: `GUIScripts/DevConsole.py` polls `dev\cmd.py` every 250 ms and answers in `dev\out.txt`; the GL driver writes a frame when `dev\shot.req` appears.
- Every run logs to `gemrb.log` in the game dir (previous run: `gemrb.prev.log`).
- Crashes (access violation, assert/abort, uncaught exception, CRT errors) write `crashes\crash-<time>.txt` with a symbolized stack, a `.dmp`, and `crashes\last_crash.txt`. Release builds emit PDBs (`/Zi`), which stay in `build\` and are found from there.
- Fixed: area loads crashed (0xc0000409) when started with a console window because fmt throws on invalid UTF-8 written to a Windows console (e.g. AR1500's garbage container script name), killing the logging thread. Log writers are now exception-safe (`Logger::WriteSafely`).
