# Automatic scene data for PST backgrounds (GemRB fork): plan

Goal: zero manual asset authoring. An offline pipeline reads Planescape: Torment's pre-rendered
area backgrounds and game data, and generates per area: light sources with metadata, a height
(depth) map, a normal map, an ambient occlusion map and a main light direction. The engine's
existing lighting pass (NOTES.md "Phase 4" and "Phase 5") consumes them. Light occlusion (what
blocks a moving light) is computed live in the shader from the offline height map.

Read `CLAUDE.md`
first. Their rules apply to every step here. Then read this whole file once before starting.

---

## 0. Rules for whoever executes this plan

1. Work **one phase at a time**, in order. A phase is finished only when every item in its
   "Done when" list has been checked and the Progress section (section 14) is updated with what
   you ran and what you saw. Do not start the next phase in the same breath.
2. The decisions in section 1 are locked. Do not change them. If one looks wrong, write down
   why in your report and still do what it says, or stop and ask the owner.
3. Stop and ask the owner (and only then) in these cases:
   - before downloading **any** model or model weights (sections 7.1 and 10.1),
   - when a "Done when" check fails twice after real fixes,
   - when section 5 (the survey) finds something section 5 says to stop on.
4. Build exactly what is described. No extra effects, no extra particles, no "while I'm here"
   features. (Past failure: unrequested map sparkles.)
5. The working tree contains uncommitted work from other tasks (upscaling, fonts, turn-based).
   Never revert, reformat or commit files you didn't change for this plan. Do not commit at all
   unless the owner asks.
6. No em dashes in code comments, docs or reports (owner preference).
7. Engine changes: after each one, run `cmd /c "D:\gemrb\build_install.bat < NUL"` from
   PowerShell. A pause or non-zero exit is a failure; fix it and rerun.
8. Python changes: after each one, run the real command on real game data (`--only` one area is
   fine) and read the output.
9. Every number in this plan marked "start value" may be tuned. Record the final value and why in
   section 14. Numbers not marked that way are fixed.

---

## 1. Decisions already made (do not change them)

- **Offline for everything static, live only for occlusion.** Backgrounds never change, so all
  analysis runs once on the local GPU (RTX 4060 Ti, 16 GB). The engine loads files. The only live
  computation is per-light occlusion in the light shader, because lights move.
- **Original art only.** The pipeline analyses the original logical-resolution background (the
  stitched TIS), never the upscaled twins. Output maps are in area pixel coordinates (map units).
- **Tooling:** a new folder `tools/lighting/` that imports `ie_formats`, `extract` and `state`
  from `tools/upscale/` (add that folder to `sys.path`). It reuses the existing venv at
  `tools/upscale/.venv` (Python 3.12, torch 2.11 cu128). No second venv.
- **Output location:** `<UpscalePath>/lighting/<WED>/`, default
  `D:\Games\GemRB\upscaled\lighting\<WED>\`. `<WED>` is the area's WED resref, upper case
  (`Map::WEDResRef` in the engine; `LM`, `SR`, `HT` bitmaps use the same stem). Never write into
  `C:\Program Files (x86)\Black Isle\Torment\`. `build_install.bat` already leaves `upscaled\` alone.
- **Review images** (previews, contact sheets, debug overlays) go to `tools/lighting/work/`,
  never into the game folder.
- **File formats** are exactly as in section 4. The engine depends on them.
- **Light sources come from three signals combined**, never from one: painted emitters in the
  background art, bright pools in the original `*LM` light map, and the existing glowing area
  animations (which stay owned by the engine and win any duplicate).
- **Height, not raw depth.** The model's depth is calibrated against game data (walkable floor
  from `*SR`, wall polygons from the WED) and stored as "height above the floor in screen
  pixels", which is exactly the quantity the existing light shader already uses
  (`h = ground - m.y` in `LightFS`).
- **Walkable floor has height 0 by definition.** The engine's world is flat: an actor's feet are
  at its screen y. So every walkable pixel not covered by a wall polygon is forced to h = 0.
- **Normals in the engine's frame:** x = right, y = toward the camera (down-screen on the
  ground), z = up. Floor = (0, 0, 1). A wall facing the camera = (0, 1, 0). (Same as `LightFS`.)
- **Camera elevation constant:** `sin(elev) = 0.75` (a search map cell is 16 x 12 pixels).
  So `T = tan^2(elev) = 0.5625 / 0.4375 = 1.285714` and `1 + T = 2.285714`. Use these exact
  constants in Python and GLSL. (The engine's older `0.72` squash stays where it is.)
- **Models:** no diffusion models anywhere (same rule as upscaling). Prefer `.safetensors`.
  Hugging Face downloads go to `tools/upscale/models/hf` (set `HF_HOME` to that folder in every
  script that loads a model). `tools/upscale/models/` is already git-ignored. Ask before
  downloading anything.
- **Ambient occlusion is applied to sprites only**, never to the background (the renders already
  contain baked occlusion; applying it again darkens corners twice).
- **SAM 2 is deferred** (section 11). It is only started if a later check proves it is needed.
- **Toggles** (all GL-only, all read live from `core->GetDictionary()` like `Lighting`, all on by
  default in `tools/dev_settings.ini`, all documented in `gemrb/GemRB.cfg.sample.in` next to the
  `Upscaled*` block):

  | Toggle | Default | Phase | Meaning |
  |---|---|---|---|
  | `BakedLights` | 1 | 1 | lights from `lights.txt` |
  | `BakedLightGain` | 100 | 1 | 0..200, scales baked light strength |
  | `LightHeightMap` | 1 | 2 | height map replaces the wall-line depth |
  | `LightOcclusion` | 1 | 2 | lights are blocked by the height map |
  | `LightOcclusionSteps` | 16 | 2 | 4..32 ray samples per pixel per light |
  | `LightNormalMap` | 1 | 3 | normal map replaces the luminance bump |
  | `SpriteAO` | 60 | 3 | 0..100, darkens the ambient on sprites in enclosed spots |
  | `AreaKeyLight` | 1 | 3 | per-area main light direction for sprite shadows and ambient tint |

  With all of them at 0 (or `Lighting=0`) the game must look exactly as it does today.

---

## 2. Background facts (verified on this machine)

- Game data: `C:\Program Files (x86)\Black Isle\Torment\` (KEY/BIF + `override\`). The resource
  index is `tools/upscale/ie_formats.py` `ResourceIndex(game, cache)` with `.names(ext)`,
  `.get(name, ext)`, `.has(name, ext)`.
- **The index only loads the types in `EXT_BY_TYPE`, and ARE is not one of them** (checked:
  `idx.names("are")` is empty). First step of phase 0: add `0x03F2: "are"` to `EXT_BY_TYPE`.
  The upscaler only asks for the extensions it uses, so this doesn't change its results. Confirm
  that by rerunning `run_upscale.bat --dry-run` and checking that the category counts are the same as before.
- PST has **123 WEDs and 125 TIS**. Every area has `<WED>LM.bmp` (light map, 8-bit paletted),
  `<WED>SR.bmp` (search map, 4-bit paletted) and `<WED>HT.bmp` (height map). 552 BMPs total.
  Example: `AR0202LM` and `AR0202SR` are both 272 x 320 cells.
- Light maps are hand-painted creature tint maps (see 6.1 C for what they look like). They carry
  real signal: 120 of 123 vary (median luma std 20.7 / 255). Flat (std < 3):
  `AR0613LM`, `AR0513LM`, `AR3006LM`. The most varied, e.g. `AR0508LM` (std 98) and `AR1101LM`
  (std 60), are good areas to check the light-map pool detection on.
- `LM`, `SR`, `HT` are on the search map grid: one cell = 16 x 12 area pixels
  (`SEARCHMAP_TILE_WIDTH/HEIGHT` in `gemrb/core/Region.h`). Grid size =
  `(areaW / 16, ceil(areaH / 12))`. Images can be a few pixels short (see the comment in
  `MakeTileProps`, `gemrb/plugins/AREImporter/AREImporter.cpp`): treat out-of-range cells as
  "unknown", never crash. GemRB does not treat HT as 3D floor height. `TileProps::QueryElevation`
  maps the palette red to an integer in -7..+7 (`value * 14 / 255 - 7`; 128 is 0). The only
  consumer is `Actor::GetElevation`, which shifts the drawn sprite and bbox by that many pixels
  (`drawPos.y -= elevation`). Lighting depth, pathfinding and scripts use `Pos.y` unshifted.
  Several HT values on walkable cells are stairs and ramps of a few pixels, not extra storeys.
- Walkable search map values come from `gemrb/unhardcoded/pst/terrain.2da` row `PASSABLE`
  (columns 0..f). A value is walkable when its PASSABLE entry is 1 or 3. Today that is
  `{1,2,3,4,5,6,7,9,11,14,15}`. Read the table; don't hard-code the set.
- Stitching already exists: `extract.read_wed(data) -> overlays`, `extract.decode_tis_tiles(data)
  -> tiles`, `extract.area_plan(tiles, overlays, tis_name)["image"]` returns the full RGBA area
  image (overlay 0 primary tiles, 64 x 64 each). `upscale._wed_map(index)` maps TIS -> overlays.
  For this plan, iterate **WEDs**: `tis = overlays[0]["tis"]`.
- Light map decode: `extract.decode_bmp(data)` gives RGBA (palette applied). Search map: open
  with Pillow; assert `image.mode == "P"`; `np.array(image)` gives the raw indices.
- WED wall polygons (verify against IESDP and `gemrb/plugins/WEDImporter/WEDImporter.cpp` before
  relying on them): WED header `0x14` = secondary header offset. Secondary header: `0x00`
  polygon count, `0x04` polygon offset, `0x08` vertex offset. Polygon record is 18 bytes:
  `0x00` first vertex index (u32), `0x04` vertex count (u32), `0x08` flags (u8), `0x09` height
  (u8), `0x0A..0x11` min x, max x, min y, max y (u16 each). Vertex = x, y (u16 each). The first
  `polygon count` polygons are the walls; door polygons come after them and are referenced from
  the door table (WED header `0x0C` door count, `0x18` door offset; door record 26 bytes:
  `0x0E` open polygon count, `0x10` closed polygon count, `0x12` open polygon offset, `0x16`
  closed polygon offset).
- ARE area animations (PST is `AREAV1.0`): ARE header `0x08` = WED resref, `0xAC` = animation
  count, `0xB0` = animation offset. Each animation is `0x4C` bytes: `0x20` x (u16), `0x22` y
  (u16), `0x28` BAM resref, `0x34` flags (u32). Flag `0x2` = BlendBlack (glowing, drawn
  additively; the engine already turns these into lights in `Map::CollectSceneLights`).
  Several AREs may share one WED: use all of them.
- Engine lighting today (`gemrb/core/Map.cpp` `Map::CollectSceneLights`, `gemrb/core/Video/Video.h`
  `SceneLight`/`SceneLighting`, `gemrb/plugins/GLVideo/GLVideo.cpp`
  `GLVideoDriver::DrawSceneLighting`, `gemrb/plugins/GLVideo/GLShaders.h` `LightFS`):
  - Light buffer cleared to the ambient colour (dungeon 0.66, outdoor 0.86, other 0.76, scaled by
    `LightingAmbient`), then each light is added (mode 0), then the scene is multiplied by it
    (mode 1). Wall polygon rows go into a wall depth texture (mode 2).
  - With geometry on, each pixel gets a ground line: sprites write theirs (`SetObjectDepth`);
    wall pixels use their polygon's base line; everything else is floor. `h = ground - m.y`.
  - Normals come from the luminance gradient of the drawn frame (`u_bump`).
  - Shader coordinates `m` are scene map units relative to the viewport origin. `AddLight`
    subtracts `viewport.x/y` from light positions. Area coordinates = `m + viewport.origin`.
  - `AddLight(out, vp, x, y, z, radius, r, g, b, cast)` (anonymous namespace in `Map.cpp`) culls and
    appends one light. `(x, y)` is the ground point, `z` the height above it.
  - Sprite shadows: `ScenePolish::DrawShadows` (`gemrb/core/ScenePolish.cpp`) casts one shadow
    along a fixed direction `project(0.0f, 1.0f, 0.85f, 0.62f)` plus one away from the strongest
    nearby light with `castsShadow`.
- The upscaled-art root is resolved by a file-static `Root()` in `gemrb/core/HiResArt.cpp`
  (`UpscalePath` or `<exe dir>/upscaled`).
- Unit tests: sources are listed in `gemrb/CMakeLists.txt` under `ADD_EXECUTABLE(Test_gemrb_core`
  (e.g. `tests/core/Test_HiResArt.cpp`). Run `build\gemrb\Release\Test_gemrb_core.exe` with
  `D:\Games\GemRB` on `PATH`.
- In-game driving: `tools\dev.ps1 start|py|click|key|shot|log|crash`. Inside `py`, `act('...')`
  runs a script action. Toggles flip live: `GemRB.SetVar('BakedLights', 0)`.
- `E:\GitHub\pst-forever` has no prior art for any of this (checked).

---

## 3. Coordinate conventions and the height formula (read twice)

Area pixel coordinates: x right, y down, origin top left of the stitched area image. Map units
equal area pixels.

Depth convention used everywhere in this plan ("floor units"): `d = -ground_y - h * T`, smaller
d = closer to the camera. For a floor pixel (h = 0) at screen y: `d = -y`.

For a pixel at screen y whose calibrated depth is d:

```
h = (-y - d) / (1 + T)          # height above its ground line, screen pixels
ground_y = y + h                # where it stands on the floor
```

Derivation (keep in the code as a short comment): for an orthographic camera at elevation
`elev`, moving up a floor changes depth by +1 per screen pixel (after normalising floor depth to
`-y`), and moving up a vertical surface changes it by `-T` per screen pixel.

3D position of a pixel for lighting (engine frame): `W = (x, ground_y, h)`.

Normal from the height map: `n = normalize(cross(dW/dx, dW/dy))` using screen-axis finite
differences of W. Check: floor gives `(0,0,1)`; a wall facing the camera (`h = g - y`) gives
`(0,1,0)`. Flip the sign if `n.z + n.y < 0`.

Occlusion depth of a 3D point `Q = (qx, qg, qh)` (ground y, height): drawn at screen
`(qx, qg - qh)`, depth `dQ = -qg - qh * T`. Depth of the background surface drawn at screen
`(sx, sy)` with height `hs`: `dS = -(sy + hs) - hs * T`.

---

## 4. Output files (the engine depends on these exactly)

All in `<UpscalePath>/lighting/<WED>/`. Little-endian. Area size = stitched image size.

### `lights.txt` (phase 1; `key` line added in phase 3)

```
# GemRB baked scene lights
version 1
size <areaW> <areaH>
key <dirX> <dirY> <strength> <ambR> <ambG> <ambB>
light <x> <y> <z> <radius> <r> <g> <b> <strength> <kind> <castsShadow>
```

- One `light` line per light, at most 64 per area (keep the highest scores).
- `x y`: ground point in area pixels. `z`: height above it (map units). `radius`: map units.
- `r g b`: colour normalised so the largest channel is 1.0. `strength`: 0..1.
- `kind`: `fire` | `magic` | `steady` | `pool`. `castsShadow`: 0 or 1.
- `key` (optional, phase 3): main light direction on the ground (`dirX, dirY`, unit vector,
  pointing **from** the light **toward** where shadows fall), `strength` 0..1, ambient colour
  normalised to luma 1.0.
- Lines starting with `#` and unknown keywords are ignored. Floats with `.` decimal point,
  written with Python `f"{v:.4f}"`.
- Also write `lights.json` with the same data plus debug fields (`score`, `source`, `emitter`
  pixel, `halo` profile) for review. The engine never reads it.

### `height.bin` (phase 2)

32-byte header, then `w * h` u16 values row-major from the top:

| offset | type | value |
|---|---|---|
| 0 | char[4] | `GLH1` |
| 4 | u32 | version = 1 |
| 8 | u32 | w = ceil(areaW / 2) |
| 12 | u32 | h = ceil(areaH / 2) |
| 16 | u32 | texel = 2 (area pixels per texel) |
| 20 | f32 | unit = 0.0625 (height in pixels = value * unit) |
| 24 | u32 | reserved 0 |
| 28 | u32 | reserved 0 |

Each texel is the **maximum** h over its 2 x 2 area pixels (keeps thin walls).

### `normal.bin` (phase 3)

Same header with magic `GLN1`, then `w * h * 3` bytes: `n * 0.5 + 0.5` scaled to 0..255, engine frame.

### `ao.bin` (phase 3)

Same header with magic `GLA1`, then `w * h` bytes: 255 = open, 0 = fully enclosed.

### `manifest.json`

`<UpscalePath>/lighting/manifest.json`: version, per-stage generator version, model names,
area count, failed areas. Rewritten at the end of each stage run.

---

## 5. Phase 0: tooling and data survey (no downloads)

### 5.1 Files

```
tools/lighting/
  scenegen.py        # CLI
  common.py          # paths, constants (ELEV_SIN, T), area loading, binary writers
  survey.py          # stage "survey"
  lights.py          # stage "lights"       (phase 1)
  depth.py           # stage "depth"        (phase 2)
  surface.py         # stage "surface": normals, AO, key light (phase 3)
  detect.py          # stage "detect"       (phase 4)
  requirements.txt   # scipy, opencv-python-headless (phase 2 adds transformers, huggingface_hub)
  setup_env.bat      # installs requirements.txt into tools\upscale\.venv
  run_scenegen.bat   # activates the venv, runs scenegen.py with this machine's defaults
  tests/             # python -m unittest discover tools/lighting/tests
```

- `setup_env.bat`: fail if `tools\upscale\.venv` is missing ("run tools\upscale\setup_env.bat
  first"). `pip install -r requirements.txt` **without** touching torch. End by printing
  `torch.cuda.is_available()` and failing if it is False (a dependency must never replace the
  cu128 torch; if one does, reinstall torch from the cu128 index as `tools\upscale\setup_env.bat`
  does).
- Add `tools/lighting/work/` to `.gitignore` next to the upscale lines.

### 5.2 CLI

```
python tools/lighting/scenegen.py --stage survey|lights|depth|surface|detect|all
       [--only WED[,WED]] [--limit N] [--force] [--review]
       [--game "C:\...\Torment"] [--out "D:\Games\GemRB\upscaled\lighting"]
```

- Resumable like the upscaler: `tools/lighting/work/state.json` via `state.State`, key
  `<stage>:<WED>`, digest = sha1 of (TIS bytes + WED bytes + LM + SR bytes + every ARE that names
  this WED + stage version string + model name). Use `atomic_write_bytes/json` for every output,
  so a killed run never leaves a half file. `--force` ignores the state.
- Errors: log to `tools/lighting/work/errors.log` with the traceback and continue with the next area.
- Progress line per area: stage, WED, n/total, seconds, key numbers (light count, residuals).
- `--review` writes the review images for the processed areas (each stage defines them).

### 5.3 `common.py` area loader

`load_area(index, wed) -> Area` with:
- `rgb` float32 (H, W, 3) 0..1, `alpha` uint8 (H, W) from the stitched image,
- `lm` float32 (gh, gw, 3) 0..1, `sr` uint8 (gh, gw) indices, `ht` uint8 (gh, gw),
- `walkable` bool (gh, gw) from terrain.2da,
- `walls`: list of polygons (N x 2 int arrays) and `doors`: list of polygons (open and closed),
- `wall_mask` bool (H, W): pixels inside any wall or door polygon (fill with `cv2.fillPoly`),
- `floor_mask` bool (H, W): walkable cell, eroded by 1 cell, AND not `wall_mask`, AND alpha 255,
- `anims`: list of `(x, y, bam, flags)` from all AREs naming this WED.

### 5.4 Survey stage

For every WED write one row of `tools/lighting/work/survey.csv`: WED, TIS, area size, LM size,
LM luma mean / std / p99, HT unique values and std, walkable fraction, floor_mask fraction,
wall polygon count, door count, BlendBlack animation count, transparent-pixel fraction.
Print a summary: how many areas have LM std below 3/255 (flat light map), how many have more
than one HT value, smallest floor fraction.

**Stop and ask the owner** if more than 10% of areas have a non-uniform HT map (it would mean
floors at several elevations that the h = 0 rule in section 1 doesn't cover). Phase 0 hit this
(107/123). The HT map is the original ±7 px avatar offset, not lighting height; the h = 0 rule
stands. See section 14.

### 5.5 Done when

- `ie_formats.EXT_BY_TYPE` includes ARE, `idx.names("are")` is non-empty, and the upscale
  `--dry-run` counts didn't change.
- `run_scenegen.bat --stage survey` processes 123 WEDs with 0 errors, and the summary is pasted
  into section 14.
- Unit tests in `tools/lighting/tests/test_common.py` pass: binary writer header round trip
  (all three magics), terrain.2da parse gives the set in section 2, polygon fill of a known
  square, `load_area("AR0202")` shapes match the survey row.

---

## 6. Phase 1: light sources and metadata (no downloads)

### 6.1 Pipeline: `lights.py`

All image operations on the stitched original. Precompute:
- `V = max(r,g,b)`, `S = (V - min) / max(V, 1e-4)`, hue in degrees, `L = 0.299r + 0.587g + 0.114b`.
- `Lbg = gaussian(L, sigma=24)`, `Lfar = gaussian(L, sigma=96)`, `RGBfar` = per-channel
  gaussian sigma 96. Gaussians ignore transparent pixels (normalised convolution: blur `L*a`
  and `a` separately, divide).

**A. Emitter cores** (start values):
1. Candidate pixel: alpha 255, `V >= 0.85`, `L - Lbg >= 0.12`, and either
   (`S >= 0.25` and hue in [0, 70] or [150, 330]) or `V >= 0.97`.
2. Morphological closing radius 2, then 8-connected components (`scipy.ndimage.label`).
3. Drop components with fewer than 6 or more than 4000 pixels, or whose bounding box is wider
   than 160 pixels (bright floors, sky, banners).

**B. Halo test** per component (the glow a light paints around itself):
1. Centroid `(ex, ey)` weighted by L. Radial profile of `excess = L - Lfar` over rings 2 px
   wide from r = 4 to r = 160, excluding the core pixels and transparent pixels.
2. `a8` = mean excess at r in [6, 10]. Require `a8 >= 0.05`.
3. `r10` = first radius where the ring excess falls below `0.1 * a8` (160 if never).
4. Halo colour = mean of `rgb - RGBfar` over rings r in [6, 40], clamped at 0. Core colour = mean
   rgb of the core. Require cosine similarity of the two chroma vectors (rgb minus its own mean)
   `>= 0.6`, unless the core is near white (`S < 0.15`).
5. Score = `mean core V * a8 * min(1, sqrt(core pixels / 20))`.

**C. Light map support.** What the `*LM` actually contains (checked on AR0202, AR1101, AR0508):
it is a hand-painted **creature tint** map, mostly near-white (lit, no tint), with grey strokes
where creatures should darken (under stairs, alcoves, behind pillars), occasional large tinted
regions (AR0508's green caves) and, in some areas, small warm spots at lamps (AR0202). Lights
are **tinted spots**, not cells brighter than the median (the median is already near white).
Definitions: `lm_ref` = 90th percentile LM luma of the area's non-black cells (the neutral lit
level). `chroma(cell) = max(rgb) - min(rgb)`. Black cells (luma < 0.05) are outside the map.
1. Cell of the emitter: `(ex // 16, ey // 12)`. Look at the cells within 3 cells of it:
   - any cell with `chroma >= 0.08`, `luma >= 0.7 * lm_ref` and hue within 40 degrees of the
     emitter's core hue: `boost = 1.5`,
   - else all those cells are shadow (`luma < 0.6 * lm_ref`): `boost = 0.6`,
   - else `boost = 1.0`.
   If the area's LM std is below 3/255 (survey), `boost = 1`.
2. `score *= boost`. Accept when `score >= 0.035` (start value).

**D. Merge and dedup:**
1. Merge accepted emitters closer than 24 px (one torch with two flames): keep the higher score,
   union the cores.
2. Drop an emitter when a BlendBlack area animation has `|ex - ax| <= 120` and
   `ay - 250 <= ey <= ay + 40` (the engine already lights that animation, and the art around it
   has its glow painted in).

**E. Light-map spots** (lamps or light the art doesn't show as a visible emitter):
1. Skip if LM std is below 3/255.
2. Blur the LM by sigma 1 cell. Spot cells: `chroma >= 0.08` and `luma >= 0.7 * lm_ref`.
   Connected components of 2 to 400 cells are spots. Components above 400 cells are **area
   tints, not lights**: record their mean colour and cell count in `lights.json` (`tints`) for
   the phase 3 ambient colour.
3. Drop a spot if any accepted emitter lies inside its bounding box grown by 3 cells.
4. Spot light: ground point = spot centroid in area pixels (`cx*16+8, cy*12+6`), `z = 120`,
   `radius = clamp(1.2 * sqrt(cells * 16 * 12 / pi) + 48, 80, 400)`, colour = mean LM colour of
   the spot normalised, `strength = clamp(mean chroma / 0.25, 0.15, 1)`, `kind = pool`,
   `castsShadow = 0`.
5. Review check: on AR0202 (Mortuary) the warm spots in the light map line up with lamps in the
   art. If they don't, report it before tuning.

**F. Emitter light metadata:**
- `x = ex`.
- Ground and height (phase 1 rule; phase 2 replaces it): scan down from `(ex, ey)` for the first
  `floor_mask` pixel within 200 px: `y = that row`, `z = y - ey`. None found: `y = ey + 60`,
  `z = 60`.
- `color` = 0.5 * normalised halo colour + 0.5 * normalised core colour, renormalised so the max
  channel is 1. Then limit saturation: `c = mix(c, vec(max(c)), 0.15)`.
- `radius = clamp(1.6 * r10, 60, 400)`.
- `strength = clamp(a8 / 0.35, 0.15, 1.0)`.
- `kind`: hue in [0, 60] and S >= 0.3 -> `fire`; S < 0.15 -> `steady`; otherwise `magic`.
- `castsShadow = 1` when kind is `fire` or `magic` and `strength >= 0.35`.

Write `lights.txt` and `lights.json` (section 4). An area with no lights still gets a file with
the header lines (so "processed, nothing found" differs from "not processed").

**G. Review (`--review`):** `tools/lighting/work/review/lights_<WED>.png`: the area downscaled to
at most 1600 px wide, each light drawn as a circle of its radius (scaled) in its colour, a cross
at the emitter, a dot at the ground point, kind letter next to it. Plus
`tools/lighting/work/review/lights_sheet.png`: 12 areas side by side (the 6 with the most
lights, the 6 with the most BlendBlack animations).

### 6.2 Python tests (`tests/test_lights.py`)

- Synthetic 512 x 512 dark image (0.15 grey, slight noise) with an orange 5 x 8 core and a
  gaussian orange halo of sigma 20: exactly 1 light, emitter within 2 px, kind `fire`,
  colour red channel 1.0 and blue < 0.5, radius in [60, 400].
- Same image with a large bright white rectangle 300 x 200: the rectangle gives no light.
- Two cores 10 px apart merge into one light.
- A BlendBlack animation placed at the core's position removes the light.

### 6.3 Engine: baked lights

1. `gemrb/core/HiResArt.h/.cpp`: make the root public: `static std::string Root();` (move the
   file-static function into the class; keep behaviour identical, including `SetRoot`).
2. New `gemrb/core/AreaSceneData.h/.cpp` (add to `gemrb/core/CMakeLists.txt` next to `HiResArt.cpp`):

   ```cpp
   struct BakedLight {
   	float x, y, z, radius, r, g, b, strength;
   	enum class Kind : uint8_t { Fire, Magic, Steady, Pool } kind;
   	bool castsShadow;
   };
   struct SceneMap {
   	int w = 0, h = 0, texel = 2;
   	float unit = 1.0f;
   	std::vector<uint8_t> data; // u16 for height, rgb8 for normals, u8 for ao
   };
   class GEM_EXPORT AreaSceneData {
   public:
   	std::vector<BakedLight> lights;
   	bool hasKey = false;
   	float keyDir[2] {}, keyStrength = 0, keyAmbient[3] { 1, 1, 1 };
   	SceneMap height, normal, ao; // empty when the file is missing (phase 2/3)
   	uint32_t generation = 0;     // changes whenever another area is loaded (GL re-upload)

   	// cached: loads <Root()>/lighting/<WED>/ on first use, keeps only the current area
   	static const AreaSceneData* ForArea(const ResRef& wed);
   	// exposed for the unit tests
   	static bool ParseLights(const std::string& text, AreaSceneData& out);
   	static bool ReadMap(const std::string& path, const char magic[4], int bytesPerTexel, SceneMap& out);
   };
   ```

   - `ParseLights`: line based, `std::istringstream`, ignores `#` lines and unknown keywords,
     skips malformed `light` lines (log once per file), rejects files without `version 1`.
     Clamps: radius 10..600, strength 0..1, colour 0..1.
   - `ForArea`: if the folder or `lights.txt` is missing, return a cached empty object (no
     repeated disk access per frame). Log once per area: `Log(MESSAGE, "AreaSceneData",
     "{}: {} baked lights, height {}, normals {}, ao {}", ...)`.
   - `ReadMap` (used from phase 2): validates magic, version 1, `w, h > 0`, file size =
     32 + w * h * bytesPerTexel; otherwise logs a warning and leaves `out` empty.
3. `Map::CollectSceneLights` (`gemrb/core/Map.cpp`), right after the party light block and
   **before** the `DynamicLights` early return:

   ```cpp
   if (vars.Get("BakedLights", 1)) {
   	const AreaSceneData* scene = AreaSceneData::ForArea(WEDResRef);
   	...
   }
   ```

   For each baked light:
   - `ambLuma = 0.299 * out.ambient[0] + 0.587 * out.ambient[1] + 0.114 * out.ambient[2]`.
   - `gain = clamp(BakedLightGain, 0, 200) / 100`.
   - Flicker from `GetMilliseconds()` (presentation clock, never the game RNG), `t` in ms, `i` =
     light index: fire `f = 0.88 + 0.12 * (0.5*sin(t*0.011 + i) + 0.3*sin(t*0.023 + i*2.1) +
     0.2*sin(t*0.047 + i*3.7))`; magic `f = 0.92 + 0.08 * sin(t*0.0021 + i)`; steady and pool `f = 1`.
   - `k = strength * gain * f * ((1 - ambLuma) + 0.1)`.
   - `AddLight(out, viewport, x, y, z, radius, r * k, g * k, b * k, castsShadow)`.

   Why this scale: at the centre of a strength-1 light the light buffer returns to about 1.0,
   so the painted glow comes back to its original brightness while the rest of the area keeps
   the ambient darkening, and sprites walking there get the same lift.
4. Config: `BakedLights=1` and `BakedLightGain=100` in `tools/dev_settings.ini` (under a comment
   `; automatic scene lights (LIGHTING_PLAN.md)`), and commented entries with one-line
   explanations in `gemrb/GemRB.cfg.sample.in`.
5. Unit test `gemrb/tests/core/Test_AreaSceneData.cpp` (add to the `Test_gemrb_core` list in
   `gemrb/CMakeLists.txt`): parses a valid file (2 lights, values and kinds correct); skips a
   malformed line but keeps the rest; rejects a file without `version 1`; `ReadMap` rejects a
   wrong magic and a truncated file and accepts a correct 3 x 2 file. Use `HiResArt::SetRoot`
   with a temp folder for any `ForArea` test.

### 6.4 Done when

- `run_scenegen.bat --stage lights` over all 123 WEDs: 0 errors. Paste into section 14: total
  lights, lights per kind, areas with 0 lights, the final thresholds.
- The review sheet has been looked at (embed it in the report). False positives on the sheet:
  fewer than 1 in 10 lights. Missed obvious torches/braziers/candles: fewer than 1 in 5. Tune the
  start values in 6.1 until this holds, rerun with `--force`, record the values.
- Python tests and `Test_gemrb_core` pass (`--gtest_filter=AreaSceneData*` plus the full run).
- In game (installed build): load an area whose review image shows painted lights (move there
  with `act('MoveBetweenAreas("<AREA>",[x.y],0)')` if no save is in it; ARE name, not WED, and
  check that the ARE uses that WED), stand the party next to a painted light, then take
  `tools\dev.ps1 shot` with `GemRB.SetVar('BakedLights', 1)` and with `0`:
  - with 1 the painted glow area is brighter than with 0, and a party member standing in it is
    visibly warmer/brighter than one standing in the dark,
  - a `fire` light flickers (two shots ~200 ms apart differ around it),
  - the party member's second shadow points away from the painted light,
  - `gemrb.log` has the `AreaSceneData` line for the area.
- `tools\tb_autotest.ps1` still passes.

---

## 7. Phase 2: calibrated height map and live occlusion

### 7.1 Model choice (ask before downloading)

Ask the owner to approve downloading these for a comparison (sizes from Hugging Face at the
time of asking; show the licence of each):
- `depth-anything/Depth-Anything-V2-Small-hf` (Apache-2.0),
- `depth-anything/Depth-Anything-V2-Large-hf` (CC-BY-NC-4.0; fine for a personal fork),
- at most one newer monocular depth model that is current on Hugging Face at that time, is not
  diffusion based, and loads through `transformers` (search first, say what you found).

Add `transformers` and `huggingface_hub` to `tools/lighting/requirements.txt`. Load with
`AutoImageProcessor` + `AutoModelForDepthEstimation`, `.cuda().eval()`, fp16, safetensors only.

**Comparison:** for 6 areas (2 dungeon, 2 city, 2 indoor by ARE area type, taken from the
survey), run the full section 7.2 calibration with each model and each `--depth-input` (518 and
1036). Write `tools/lighting/work/review/depth_compare.png`: per area, the original, then for
each candidate a shaded-relief image of h (section 7.2.6) and the held-out floor residual and
wall score printed on it. Show it to the owner and let them pick. Record the pick in section 14.
Default if the owner says "you pick": the candidate with the best wall score among those whose
held-out floor residual is below 4 px.

### 7.2 Pipeline: `depth.py`

1. **Tiles:** tile size 1036 area pixels, overlap 256, covering the stitched image. Pad edge
   tiles with edge replication; remember the valid region.
2. **Inference:** feed each tile at `--depth-input` size (1036: no resize; 518: Lanczos down by 2,
   upsample the prediction bilinearly by 2). The input side must be a multiple of 14. Disable
   the processor's own resize/crop (`do_resize=False`) and normalise exactly as the processor
   would. Output: `p` (relative inverse depth, larger = closer), float32, tile resolution.
3. **Per-tile calibration** against the floor (section 3: floor target `d = -y`):
   - Floor pixels = `floor_mask` inside the tile's valid region. Split floor **cells** 80/20 into
     fit and held-out sets (seed 0, by cell so neighbouring pixels don't leak).
   - Fit `d = a*p + c` by iteratively reweighted least squares, 3 rounds, Huber weights with
     delta = 4 px. Also fit `d = a*p + b*p^2 + c` the same way. Use the quadratic only if it lowers
     the held-out median |residual| by more than 10%.
   - Valid fit: at least 3% of the tile's pixels are fit pixels **and** `a < 0`. Otherwise mark
     the tile "unanchored".
4. **Unanchored tiles:** fit the same model so that its `d` matches the already calibrated `d` of
   anchored neighbours in the overlap regions (least squares on overlap pixels). Repeat
   breadth-first until no tile changes. A tile with no anchored neighbour after that keeps
   `h = 0` everywhere and is logged.
5. **Blend:** `h = (-y - d) / (1 + T)` per tile, then feather tiles together in the overlaps
   with linear weights (as `upscaler._axis_weight` does). Then:
   - clamp to `[0, 1024]`,
   - force h = 0 on `floor_mask`, with a 4 px linear feather from the mask edge outward
     (`cv2.distanceTransform` on the inverted mask),
   - transparent pixels: fill from the nearest valid pixel.
6. **Outputs:** `height.bin` (2 x 2 max, section 4). Review: `depth_<WED>.png` = shaded relief
   (light from the upper left on the 3D positions of section 3) side by side with the original,
   and `height_<WED>.png` = h as a colour map 0..256 px.
7. **Light heights:** rerun the light metadata step (6.1 F) with the height map: emitter ground
   `y = ey + h(ex, ey)`, `z = h(ex, ey)`; if `h < 8` (the emitter sits on the floor, e.g. a
   campfire) use `z = 20` and `y = ey + 20`. Bump the lights stage version so the state reruns it.
8. **Metrics** per area, printed and written to `tools/lighting/work/depth_metrics.csv`:
   - held-out floor residual: median |h| over held-out floor pixels before step 5 forces zeros,
   - wall score: fraction of `wall_mask` pixels (excluding door polygons) with h > 4,
   - seam score: the largest mean |difference| between two tiles' h over any overlap region,
   - unanchored tile count.

### 7.3 Python tests (`tests/test_depth.py`)

- Synthetic orthographic scene: floor plane plus a box 80 px tall, rendered to a fake `p` with a
  known affine relation and noise. Calibration recovers the box height within 10% and floor
  |h| < 1.
- The height-to-normal function gives (0,0,1) on the floor and (0,1,0) on the box front.
- Unanchored-tile propagation: a tile with no floor gets the same h as the ground truth within 5%.

### 7.4 Engine: height map and occlusion

1. `AreaSceneData::ForArea` also loads `height.bin` (`ReadMap(..., "GLH1", 2, height)`).
2. `SceneLighting` (`gemrb/core/Video/Video.h`) gets:

   ```cpp
   const AreaSceneData* scene = nullptr; // forward-declare struct AreaSceneData above
   float viewX = 0.0f, viewY = 0.0f;     // area coords of the viewport origin
   bool useHeight = false, occlusion = false, useNormals = false;
   int occlusionSteps = 16;
   float spriteAO = 0.0f;                // 0..1
   ```

3. `Map::CollectSceneLights`: when geometry is on, `LightHeightMap` is on and the scene has a
   height map: set `scene`, `viewX/viewY = viewport.x/y`, `useHeight = true`, `occlusion` and
   `occlusionSteps` from their toggles, and **skip** filling `wallSpans` (the height map replaces
   it). Otherwise behave exactly as today.
4. `GLVideoDriver` (`plugins/GLVideo/GLVideo.cpp/.h`):
   - A texture cache keyed by `(scene pointer, generation)`. Height: convert to float on the CPU
     (`value * unit`), upload as `GL_R32F`, `GL_NEAREST`, clamp to edge. Delete the old texture
     when the key changes. Check the area size against `GL_MAX_TEXTURE_SIZE` and skip the height
     map with a warning if it doesn't fit.
   - Bind it on texture unit 4 during the light pass (mode 0) and unbind it afterwards (the
     sprite program must never sample it).
   - New uniforms (locations looked up next to the existing `luni` ones): `u_hasHeight`,
     `u_height` (unit 4), `u_viewOrigin` (vec2), `u_sceneTexel` (float, = 2),
     `u_occlSteps` (int, 0 = off), `u_occlBias` (2.0), `u_occlThickness` (48.0, start value).
5. `LightFS` mode 0, geometry branch:
   - `float heightAt(vec2 scenePos)`: `area = scenePos + u_viewOrigin`;
     `texelFetch(u_height, ivec2(floor(area / u_sceneTexel)), 0).r`, clamped to the texture.
   - Replace the wall-depth lookup when `u_hasHeight == 1`: `ground = m.y + heightAt(m)`.
     Sprite depth still wins exactly as now (`if (sd.a > 0.5) ground = sd.r / sd.a;`).
   - Occlusion, only for non-sprite pixels (sprites keep today's behaviour) and only when
     `u_occlSteps > 0`:

     ```glsl
     const float T = 1.285714;
     float occlusion(vec3 P, vec3 Lp) // (x, ground y, height), scene map units
     {
     	float jitter = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
     	float hits = 0.0;
     	float len = length(Lp - P);
     	for (int i = 0; i < u_occlSteps; ++i) {
     		float s = (float(i) + jitter) / float(u_occlSteps);
     		if (s * len < 4.0) continue; // no self shadowing
     		vec3 Q = mix(P, Lp, s);
     		vec2 scr = vec2(Q.x, Q.y - Q.z);
     		float hs = heightAt(scr);
     		float dQ = -Q.y - Q.z * T;
     		float dS = -(scr.y + hs) - hs * T;
     		float diff = dQ - dS; // > 0: the surface drawn there is closer than Q
     		if (diff > u_occlBias && diff < u_occlThickness) hits += 1.0;
     	}
     	return 1.0 - clamp(hits / 2.0, 0.0, 1.0);
     }
     ```

     Multiply `att` by it. Keep `occlusion()` and `heightAt()` free of branches on `u_debug`.
   - `GEMRB_LIGHT_DEBUG=1` additionally shows occlusion: output red = vertical (as now),
     green = falloff * occlusion, blue = normal x (as now).
6. Config lines for `LightHeightMap`, `LightOcclusion`, `LightOcclusionSteps` (dev_settings.ini +
   cfg sample).
7. Unit tests: `ReadMap` for a `GLH1` file (values and unit), and a CPU `AreaSceneData::HeightAt
   (float areaX, float areaY)` helper (nearest texel, clamped) that the GLSL mirrors.

### 7.5 Done when

- All 123 areas processed with 0 errors. Over all areas: median held-out floor residual < 4 px,
  median wall score > 0.7, seam score < 3 px in at least 95% of areas, and every exception listed
  by name in section 14 with a one-line reason from its review image.
- The review images of 8 areas (the 6 comparison areas plus the 2 worst wall scores) are embedded
  in the report.
- Python tests and `Test_gemrb_core` pass.
- In game, with the party light (and a fire spell or projectile if one can be cast via
  `ExecuteActionAt`, see `CLAUDE.md`) next to a wall:
  - `LightOcclusion` 1 vs 0 screenshots: with 1, the floor on the far side of the wall/pillar
    stays dark; with 0 it is lit,
  - `LightHeightMap` 1: pillars, tables and arches that have no wall polygon now catch light on
    their faces like walls do (compare with 0),
  - `GEMRB_LIGHT_DEBUG=1` shot embedded in the report,
  - no visible slowdown with 16 steps while panning an area with many lights; if there is one,
    lower the default steps and record it,
  - zooming in/out (mouse wheel) keeps the lighting attached to the art (no sliding).
- `tools\tb_autotest.ps1` passes.

---

## 8. Phase 3: normals, ambient occlusion, main light direction

### 8.1 Pipeline: `surface.py`

1. **Normals** from the full-resolution h (before the 2 x 2 max): W per pixel (section 3),
   central differences, `n = normalize(cross(dW/dx, dW/dy))`, flipped if `n.z + n.y < 0`. Blur h
   first with a 1 px gaussian, **except** across `wall_mask` edges (blur inside and outside
   separately). Downsample to the half-resolution grid by averaging and renormalising. Write
   `normal.bin`.
2. **Ambient occlusion** (for sprites standing on the floor): for each half-res texel on or
   near the floor, cast 16 directions on the ground plane, up to 96 map units, and find the
   highest elevation angle of the height field seen from a point 30 units above the floor
   (`atan(h_sample - 30, distance)`, distances on the ground with the y axis divided by 0.75).
   `ao = 1 - mean(max(0, sin(maxAngle)))`, then gamma 0.7. Creatures are already darkened by
   the light map tint at their feet (kept from the original game), so don't darken twice: scale
   the AO by how lit the light map is there,
   `ao = 1 - (1 - ao) * clamp(lm_luma(cell) / lm_ref, 0, 1)`. Write `ao.bin`.
3. **Main light direction and ambient colour:**
   - Pixels used: `h > 6` (non-floor), not within `0.5 * radius` of any light from phase 1/2,
     alpha 255, `0.05 < L < 0.9`, normal confidence: the 3 x 3 neighbourhood normal variance below
     0.05.
   - Least squares fit `L ~ c0 + c1*nx + c2*ny + c3*nz`.
   - If `hypot(c1, c2) / c0 < 0.05`: no `key` line. Otherwise `key dir = -(c1, c2) / hypot(c1,
     c2)` (shadows fall away from the light), `strength = clamp(norm(c1,c2,c3) / c0, 0, 1)`.
   - Ambient colour = median rgb of `floor_mask` pixels farther than one radius from every
     light, normalised to luma 1.0. If phase 1 recorded light-map `tints` covering more than 30%
     of the map's non-black cells, mix 50% of their cell-weighted mean colour (normalised) in.
   - Append the `key` line to `lights.txt` (bump the lights file but not the lights themselves).
4. **Review:** `normal_<WED>.png` (normals as RGB), `ao_<WED>.png`, and the key direction drawn
   as an arrow on the lights review image.

### 8.2 Engine

1. Load `normal.bin` (`GLN1`, 3 bytes, `GL_RGB8`, linear) and `ao.bin` (`GLA1`, 1 byte, `GL_R8`,
   linear) into the same texture cache; units 5 and 6; uniforms `u_hasNormals`, `u_normalMap`,
   `u_ao`, `u_spriteAO`.
2. `LightFS` mode 0: when `u_hasNormals == 1` and the pixel is not a sprite pixel, take `n` from
   the normal map (`* 2 - 1`) instead of the luminance bump. Keep `u_normalStrength` as the mix
   with the flat normal exactly as today. Sprite pixels keep the luminance bump.
3. **Sprite AO:** a new mode 3 drawn right after clearing the light buffer to the ambient colour,
   one full quad, blend `glBlendFunc(GL_DST_COLOR, GL_ZERO)` (multiply). For sprite pixels
   (`sd.a > 0.5`): output `mix(1.0, ao(area of (m.x, sprite ground)), u_spriteAO)`. Every other
   pixel outputs 1.0. Skip the pass when `u_spriteAO == 0` or there is no AO map.
4. **Key light:** with `AreaKeyLight` on and a `key` line:
   - `ScenePolish::DrawShadows`: replace `project(0.0f, 1.0f, 0.85f, 0.62f)` with
     `project(keyDir[0], keyDir[1], 0.85f, 0.62f * clamp(keyStrength, 0.4, 1.0))`. Pass the data
     through `SceneLighting` (add `keyDir[2]`, `keyStrength`, `hasKey`), not through a global.
   - `Map::CollectSceneLights`: tint the ambient: `ambient[c] = mix(ambient[c], ambLuma *
     keyAmbient[c], 0.5)`. Brightness (luma) must not change.
5. Config lines for `LightNormalMap`, `SpriteAO`, `AreaKeyLight`.
6. Unit tests: `ReadMap` for `GLN1` and `GLA1`; `ParseLights` with and without a `key` line.

### 8.3 Done when

- All areas processed, 0 errors. Count of areas with a `key` line in section 14.
- Review images for the 8 areas from 7.5 embedded.
- In game: `LightNormalMap` 1 vs 0 next to a light: surfaces facing the light are brighter and
  surfaces facing away darker, with no speckle from painted texture (the old luminance bump
  made dark paint look like dents; check one such spot). `SpriteAO` 100 vs 0: a party member in a
  corner or under an arch gets darker, one in the open does not change. `AreaKeyLight` 1 vs 0 in
  2 areas with a key line: the main sprite shadow points along the arrow on the review image.
- Every toggle at 0 gives the same screenshot as before phase 1 (compare with a shot taken
  before starting phase 1; take that shot at the start of phase 1 and keep it in `shots/`).
- `tools\tb_autotest.ps1` passes.

---

## 9. Disk and time budget (expected, verify)

- Height (u16) + normals (rgb8) + AO (u8) at half resolution: 6 bytes per 4 area pixels. A big
  area of 4352 x 3840 is about 25 MB; all 123 areas roughly 1 to 2 GB. Report the real size.
  If it is above 3 GB, ask the owner whether to add zlib compression (GemRB already links zlib).
- Depth inference: about 25 tiles per big area at 1036 input; well under an hour for all areas.

---

## 10. Phase 4: open-vocabulary detector for light labels (ask before downloading)

### 10.1 Model

Ask the owner to approve `google/owlv2-base-patch16-ensemble` (Apache-2.0), loaded with
`Owlv2Processor` + `Owlv2ForObjectDetection`.

### 10.2 `detect.py`

1. Tiles of 960 area pixels, overlap 128. Prompts and the kind each maps to:

   | prompt | kind |
   |---|---|
   | "a burning torch", "a candle flame", "a brazier with fire", "a campfire", "a fireplace", "lava" | fire |
   | "a glowing lantern", "a lamp" | steady |
   | "a glowing magical crystal", "a glowing portal", "glowing runes" | magic |
   | "a glowing window" | pool |

2. Keep boxes with score >= 0.12 (start value); class-wise NMS at IoU 0.5 across tiles.
3. Use the boxes in the lights stage (bump its version):
   - an emitter inside a box takes the box's kind (`castsShadow` recomputed with 6.1 F's rule),
   - inside a `fire` or `magic` box, the acceptance score threshold (6.1 C) is multiplied by 0.6,
   - a `pool` box with LM support (`boost >= 1.2`) and no emitter makes a pool light at the
     box's bottom centre (`z = 120`, radius from the box width * 2, clamped 80..400).
   Boxes never create lights on their own beyond that rule.
4. Review: boxes with labels and scores drawn on the lights review images.

### 10.3 Done when

- On the same 12-area review sheet as phase 1: no lost true lights compared to phase 1, at
  least half of the misses noted in phase 1 now found, and kinds visibly right on the sheet.
  Numbers in section 14.
- In game: one relabelled light checked (for example a lantern that no longer flickers).

---

## 11. Phase 5 (deferred): SAM 2 masks

Start only if one of these is true, and write a short sub-plan and ask the owner first:
- in phase 2 or 3 review images, height edges bleed across object outlines in more than 1 of 8
  areas in a way the in-game shots show (light leaking onto the wrong object),
- the phase 4 sheet shows emitter extents merging separate objects.

Intended use if started: `facebook/sam2.1-hiera-large` automatic masks; inside each mask, fit a
plane to h and snap h edges to mask boundaries. Never used for anything else.

---

## 12. Phase 6 (later): other Infinity Engine games

The pipeline only depends on KEY/BIF, TIS, WED, ARE, `*LM`, `*SR`, `*HT`, and
`gemrb/unhardcoded/<game>/terrain.2da`, which every IE game has. Needed when the owner installs
one: a `--game-type` option choosing the terrain table; night tilesets (BG/IWD: the WED's night
TIS and `<WED>LN.bmp`) processed into `lighting/<WED>N/`, and the engine choosing that folder
when `Map::DayNight` is false. Don't build this until asked.

---

## 13. Reporting to the owner after each phase

First line: what is now true. Then, as bullets: what was checked in game (with embedded
screenshots), what was only unit-tested or compiled, what nobody has seen yet, the numbers from
the phase's "Done when", the files changed, and "nothing is committed".

---

## 14. Progress

- [x] Phase 0: tooling and survey
- [ ] Phase 1: light sources (pipeline + engine `BakedLights`)
- [ ] Phase 2: height map (model choice, calibration, engine height + occlusion)
- [ ] Phase 3: normals, sprite AO, key light
- [ ] Phase 4: detector labels
- [ ] Phase 5: SAM 2 (deferred, only on trigger)
- [ ] Phase 6: other games (not until asked)

Notes (survey summary, final thresholds, model pick, metrics, exceptions):

- Phase 0 tooling is in and the survey finished with 0 errors. Phase 1 is unblocked.
- Upscale dry-run before adding ARE: 5609 resources. gui 974 (bam 715, bmp 10, mos 249), areas 125 (tis 125), sprites 1871 (bam 1871), skip 5 (bam 5). After `0x03F2: "are"`: same four category counts, 5817 resources. The extra entries are ARE files. `idx.names("are")` is non-empty.
- `run_scenegen.bat --stage survey` on all 123 WEDs, 0 failures, no `errors.log`, about 2.5 minutes. Rows in `tools/lighting/work/survey.csv`. Summary below. Manifest: `D:\Games\GemRB\upscaled\lighting\manifest.json` (`survey-1`, 123 areas, failed empty).
- Survey summary (2026-11-14):

```
survey: 123 areas, 0 failed, version survey-1
flat light maps (luma std < 3/255): 3
  AR0513 AR0613 AR3006
median luma std: 20.72/255
non-uniform HT (more than one value): 107/123 (87.0%)
smallest floor fraction: 0.0072 AR3008
HT unique-value histogram: 1 values: 16, 2 values: 18, 3 values: 7, 4 values: 15, 5 values: 9, 6 values: 12, 7 values: 5, 8 values: 9, 9 values: 5, 10 values: 5, 11 values: 3, 12 values: 7, 14 values: 4, 15 values: 6, 16 values: 2
blend-black animations (engine bit 0x100): 86
  top: AR0202F1 39, AR0203F1 9, A0403_F1 4, A1201G1L 2, A1201G1R 2, A0110G01 1, ...
file bit 0x2 animations: 0
STOP: 107 of 123 areas (87.0%) have a non-uniform HT map.
```

  The full name list is in `tools/lighting/work/survey_summary.txt`.
- Flat light maps match the three names already in section 2. Median luma std 20.72/255 matches the earlier 20.7/255.
- Height values are the palette red channel, the same byte `MakeTileProps` stores. A follow-up on walkable cells only (SR passable, not the whole bitmap): 106 of 122 areas have more than one elevation on walkable cells. Median share of walkable cells off that area's most common value is 15.4%, 90th percentile 54%, maximum 98% (AR1400). The most common value is 98 in 103 areas, and 0, 32, 54, 128 or 239 in the rest. AR1204's HT is one row shorter than its SR (170 vs 171); the missing row is treated as unknown and the area still surveyed.
- BlendBlack for PST is file bit 0x100, not 0x2. `AREImporter::AdjustPSTFlags` copies 0x100 (`AreaAnimation::Flags::Background`) onto the runtime BlendBlack flag, and that is what `Map::CollectSceneLights` lights. Bit 0x2 is set on 0 animations. Bit 0x100 is set on 86, led by fire BAMs (`AR0202F1`, `AR0203F1`). The survey counts 0x100.
- Floor mask erosion is 8-connected: a kept cell is walkable together with all eight neighbours. Cells the search map does not cover stay unknown.
- Dependencies: `opencv-python-headless>=4.9,<5` and `scipy>=1.11` in the upscale venv. Installed OpenCV 4.11.0.86 and scipy 1.18.1. The 5.0 wheel download stalled, so 5.x is excluded. Torch package is still `2.11.0+cu128`. `torch.cuda.is_available()` did not return within 90 seconds; the GPU already had 12129 MiB of 16380 MiB in use. The boolean was not observed.
- Unit tests: `tools\upscale\.venv\Scripts\python.exe -m unittest discover tools/lighting/tests` : 9 tests, OK, including `load_area("AR0202")` against its survey row (LM/SR 272 x 320 cells).
- No engine change, so nothing was checked in game. Nothing is committed.
- Height-map decision (section 5 stop, 107/123 non-uniform HT): keep the locked rule. Walkable
  floor is lighting height 0. Do not read `*HT.bmp` into the lighting height map. GemRB only
  uses HT to nudge the actor sprite by -7..+7 pixels (`TileProps::QueryElevation`); lighting
  still keys off `Pos.y`. Multiple HT values are stairs, not storeys. The survey still records
  HT unique counts as a fact. Phase 2 calibrates against `floor_mask` and wall polygons only.
