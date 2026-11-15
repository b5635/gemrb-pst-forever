# Upscaled art for PST (GemRB fork): plan

Goal: AI-upscaled replacements for Planescape: Torment's art, made offline on the local GPU
(RTX 4060 Ti, 16 GB) and drawn by the engine at the original *logical* size. The art then
looks sharper when the window is bigger than the logical resolution or the map is zoomed in.
Game logic, hit tests and scripts must not change: only what gets drawn.

Three independent categories, each with its own toggle:

| Category  | Toggle (GemRB.cfg)  | Status now                         |
|-----------|---------------------|------------------------------------|
| GUI       | `UpscaledGUI=1`     | build and run in full              |
| Areas     | `UpscaledAreas=1`   | build and run in full              |
| Sprites   | `UpscaledSprites=0` | pipeline and engine hooks ready, not run |

Read `CLAUDE.md` first. Its rules apply here: run `build_install.bat` after every engine
change, and put each new toggle's "on" line in `tools/dev_settings.ini`.

---

## 0. Decisions already made (do not change them)

- **Upscaler:** Python + PyTorch (CUDA) + [`spandrel`](https://github.com/chaiNNer-org/spandrel),
  which loads ESRGAN, SwinIR, DAT and similar models from OpenModelDB. No chaiNNer, no ncnn.
- **Output scale: 2×.** Run a 4× model, then shrink the result to 2× with Pillow Lanczos.
  This looks better than a native 2× model and keeps VRAM and disk use sane: at 4× one big
  area would be about 600 MB of textures. The scale is a pipeline option (`--scale`); the
  engine reads it from each file's size, so 3× or 4× work later without engine changes.
- **Output format:** plain RGBA PNG files in a folder tree (layout in section 3). Every finished
  file marks that piece of work as done, which is what makes the run resumable.
- **Output location:** `D:\Games\GemRB\upscaled\`. It lives outside the repo and outside the
  game data. The engine reads the folder from `UpscalePath` (default `<GemRB exe dir>/upscaled`).
  Never write into `C:\Program Files (x86)\Black Isle\Torment\`.
- **Engine approach:** a sprite keeps its original low-res pixels (the engine reads them for
  hit tests, palettes and copies). It can additionally carry a hi-res RGBA twin. Only the
  OpenGL driver (`plugins/GLVideo`) draws the twin; the SDL driver ignores it.
- **Never upscale** data that isn't art: light maps, search maps and height maps (`*LM`, `*SR`,
  `*HT` BMPs), palettes, WED/ARE geometry, fonts (for now, see section 8).

## 1. Background facts (verified)

- The game is at `C:\Program Files (x86)\Black Isle\Torment\`: `CHITIN.KEY`, BIF files in the
  root plus `cd2\`, `cd3\`, `cd4\`, and an `override\` folder that beats the BIFs (Fixpack and UB
  are installed there). Resolve every resource the way the engine does: override first, then KEY/BIF.
- Logical resolution is 1280×720 (`Width`/`Height` in `D:\Games\GemRB\GemRB.cfg`). The GL driver
  renders at window resolution (`GLHighResolution=1`). `renderScale` is the window size over the
  logical size, clamped to 1..4 (`GLVideoDriver::UpdatePresentRect`, `plugins/GLVideo/GLVideo.cpp`).
  Mouse-wheel zoom is on. Both are why hi-res art pays off. At a 1280×720 window, the upscaled
  art only shows up when zoomed in.
- `GLSprite2D` (`plugins/GLVideo/GLSprite2D.{h,cpp}`) uploads paletted sprites as R8UI index
  textures (the shader applies the palette) and others as RGBA8. Texture coordinates are in
  texels of the sprite (`DrawSprite`: `u0 = src.x` and so on).
- Area tiles: `TISImporter::GetTile(int index)` (`plugins/TISImporter/TISImporter.cpp`) makes
  64×64 sprites. `TileOverlay::Draw` blits them with `BlitGameSprite`. Animated and door tiles
  are extra TIS indices referenced from the WED.
- MOS: `MOSImporter::GetSprite2D()` returns one sprite for the whole image.
- BAM: `BAMImporter::GetFrameInternal(const FrameEntry&, bool RLE)`. The frame's position comes
  from `Frame.x/y`, and the hi-res twin must keep it exactly (same logical rect).
- PNG loading exists (`IE_PNG_CLASS_ID`, `plugins/PNGImporter`); see how `core/Interface.cpp`
  (around line 2303) uses it.
- Python 3.13 is installed (`python` on PATH).
- File formats: IESDP (https://gibberlings3.github.io/iesdp/file_formats/) covers KEY, BIF
  (including BIFC/compressed), TIS, WED, MOS (including MOSC), BAM (including BAMC), CHU, ITM, SPL, ARE.
  - Inside a BIF, tilesets have **no** `TIS V1` header: each tile is a 1024-byte BGRA palette
    followed by 4096 index bytes. GemRB's `TISImporter::Open` handles both cases.
  - In TIS palettes, pure green (0,255,0) means transparent (used for overlay and water tiles).
  - In BAM v1, the palette entry used as the colour key is transparent (normally index 0;
    IESDP explains how to pick it). In creature/effect BAMs, index 1 is the shadow: semi-transparent black.

---

## 2. Phase A: Python environment (`tools/upscale/`)

1. Create `tools/upscale/` with: `requirements.txt`, `setup_env.bat`, `run_upscale.bat`,
   `upscale.py` (CLI), plus modules `ie_formats.py`, `classify.py`, `extract.py`,
   `upscaler.py` and `state.py`.
2. `setup_env.bat`: creates `tools/upscale/.venv`, installs PyTorch with CUDA
   (`pip install torch --index-url https://download.pytorch.org/whl/cu124`; pick the current CUDA
   wheel that supports Python 3.13), then `pip install -r requirements.txt` (`spandrel`,
   `pillow`, `numpy`, `tqdm`). It ends by printing `torch.cuda.is_available()` and the GPU name,
   and fails loudly if CUDA isn't available.
3. Add `tools/upscale/.venv/`, `tools/upscale/models/` and `tools/upscale/work/` to `.gitignore`.
4. **Models (ask the user before downloading anything).** Put them in `tools/upscale/models/`.
   Prefer `.safetensors`. If only `.pth` exists, load it with `torch.load(..., weights_only=True)`,
   because a `.pth` file can run code. Candidates, one per category, chosen with `--model-<category>`:
   - areas (pre-rendered 3D backgrounds): `4x-UltraSharp` or `4xNomos8kDAT`
   - gui (painted frames, small text-like art): `4x-UltraSharp`; compare with `4x-FatalPixels`
   - sprites, later: `4x-UltraSharp` (it's deterministic, so animations don't shimmer)

   Before the full run, upscale ~10 samples per category with each candidate and write a
   side-by-side contact sheet to `tools/upscale/work/compare/`. Show it to the user and let
   them pick the model.

## 3. Phase B: the pipeline

### CLI

```
python tools/upscale/upscale.py --categories gui,areas [--scale 2] [--limit N]
       [--only RESREF[,RESREF]] [--force] [--dry-run] [--game "C:\...\Torment"]
       [--out "D:\Games\GemRB\upscaled"] [--tile 512] [--fp16]
```

`run_upscale.bat` activates the venv and runs it with the defaults for this machine. It runs
fine in the background, and running it again continues where it stopped.

### Output layout (the engine depends on this exactly)

```
upscaled/
  manifest.json                      # version, scale, model per category, counts
  areas/<TIS>/<tileIndex>.png        # (64*s)x(64*s); index = TIS tile index
  gui/mos/<MOS>.png                  # (w*s)x(h*s)
  gui/bam/<BAM>/<frameIndex>.png     # (frame.w*s)x(frame.h*s); index = BAM frame table index
  sprites/bam/<BAM>/<frameIndex>.png # same, for the sprite category
```

Resource names are upper case, with no extension. A file must be exactly `s` times the
original size, or the engine ignores it and logs a warning.

### Steps

1. **Index** (`ie_formats.py`): parse `CHITIN.KEY` and the BIFs (support BIFC and compressed
   `BIF V1.0`, and the `cd*` folders), then overlay the `override\` folder. The result is a
   map `(resref, type) -> bytes loader`.
2. **Classify** (`classify.py`) every TIS, MOS and BAM into gui, areas, sprites or skip:
   - areas: every TIS that a WED refers to (and so every TIS). Area minimaps (MOS named by an
     ARE/WED) go to **gui**.
   - gui: every MOS; BAMs used by CHU controls (buttons, sliders, scrollbars, progress bars);
     item inventory/description icons (ITM); spell icons (SPL); portraits; and BAM/MOS names
     quoted in `gemrb/GUIScripts/pst/*.py` and `gemrb/GUIScripts/*.py` (scan the string
     literals for names that exist as BAM/MOS).
   - skip: font BAMs (named in `gemrb/unhardcoded/pst/fonts.2da`), cursors (keep their hot
     spots exact; revisit later), and anything under 8×8.
   - sprites: every other BAM (creatures, VVC/spell effects, projectiles, area animations,
     ground item icons).
   - Write `tools/upscale/work/classification.json` and print counts per category.
     `--dry-run` stops here.
3. **Extract to RGBA:**
   - BAM frame: decode (with RLE) to RGBA. The colour key becomes alpha 0, shadow index 1
     becomes alpha 128 black. Keep the original size.
   - MOS: assemble the blocks (MOSC is zlib) into one RGBA image.
   - TIS for areas: **stitch, don't upscale tile by tile, or the tile edges show as seams.**
     Read the WED: overlay 0 has the width and height in tiles plus a tile map (cell ->
     primary tile index, alternate index, animation frame list); doors have extra tile lists.
     - Build the full area image from each cell's primary tile and upscale it in chunks of
       `--tile` px with 32 px overlap, blending the overlaps with linear feathering.
       Then cut it back into 64·s tiles, named by TIS index.
     - Every TIS index not covered that way (animation frames, door tiles, alternates, other
       overlays): make a 3×3 tile patch from that cell's neighbours with this tile in the
       middle, upscale it, keep the middle.
     - Tiles never placed anywhere: upscale alone with 16 px edge-replicate padding, then crop.
4. **Upscale** (`upscaler.py`):
   - Load a model once per category with spandrel, `.cuda().eval()`, fp16 when `--fp16`.
     Process in batches.
   - Transparency: before upscaling, fill the colour of fully transparent pixels from the
     nearest opaque one (dilate a few px) so no dark halos appear. Upscale the RGB and the
     alpha separately; the alpha goes through the model as greyscale. Then:
     - colour-keyed art (GUI BAMs): threshold alpha at 128 to 0/255
     - shadow pixels: keep 128
     - otherwise: clamp
   - Downscale to `s`× with Lanczos and save as PNG (optimize off, compress level 6).
   - Catch CUDA out-of-memory errors: halve the chunk size and retry that item.
5. **Resumable state** (`state.py`):
   - Write every output to `<name>.png.tmp`, then `os.replace` it to the final name.
     A finished `.png` means done.
   - `work/state.json` holds a sha1 of each source resource plus the model name and scale.
     When the source or settings change, that resource is redone; otherwise existing outputs
     are skipped. At start-up, delete leftover `*.tmp` files.
   - The unit of work is one resource (a whole TIS, MOS or BAM). Flush the state after each one.
   - Ctrl+C, a crash or a reboot loses at most the item in progress. `--force` ignores the state.
   - Progress line: category, done/total, items per minute, ETA. Errors are logged to
     `work/errors.log`, and the run carries on with the next item.
6. When a category finishes, write `manifest.json`.

**Phase B is done when:** `--dry-run` prints sensible counts; `--only AR0202 --categories areas`
(any PST area TIS) produces tiles of exactly 128×128; and killing the run halfway and starting
it again neither redoes nor corrupts anything.

## 4. Phase C: engine support

1. **Core, `core/Sprite2D.h/.cpp`:** add `Holder<Sprite2D> hiRes;` (a public member is fine;
   null means none). The copy constructor and `copy()` share it (it's a holder, so it isn't
   deep-copied). Any write lock of the pixels (`LockSprite()` non-const) or `ConvertFormatTo`
   clears `hiRes`, because the art changed and the twin is stale.
   - Check `GLSprite2D`'s own copy constructor too (it currently copies fields by hand).
2. **Core, new `core/HiResArt.h/.cpp`** (a static helper; add it to the core CMake source list):
   - `enum class HiResCategory { GUI, Areas, Sprites };`
   - `static bool Enabled(HiResCategory)`: reads `UpscaledGUI`, `UpscaledAreas` and
     `UpscaledSprites` from `core->GetDictionary()` (default 0), and only when the video driver
     is the GL one. Expose that through a `Video` virtual such as `SupportsHiResArt()`, true
     only in GLVideo.
   - `static void Attach(const Holder<Sprite2D>& spr, const path_t& relPath)`: builds
     `<UpscalePath>/<relPath>`. If the file exists, it loads the PNG through the PNG importer
     into an RGBA sprite, checks that width and height are the same integer multiple (≥2) of
     `spr->Frame.w/h`, and sets `spr->hiRes`. A wrong size logs a warning once and is skipped.
     A missing file is silent: that's the normal fallback.
   - The hi-res sprite's `Frame` must be `(0, 0, w*s, h*s)`; the logical position stays on the
     low-res sprite.
   - Cache the existence check per folder: list `areas/<TIS>/` once and keep a set, so a missing
     area doesn't cost thousands of failed `stat` calls.
   - Log once per area/resource how many twins were attached (`Log(MESSAGE, "HiResArt", ...)`).
3. **Hooks:**
   - `TISImporter::GetTile(int index)`: if `Enabled(Areas)`, call `Attach(sprite, "areas/<RESREF>/<index>.png")`.
     The resref is the stream's `filename` without the extension, upper case. Leave `badTile` alone.
   - `MOSImporter::GetSprite2D()`: `Enabled(GUI)` → `gui/mos/<RESREF>.png`.
   - `BAMImporter` (where frames are made, i.e. `GetFrameInternal` and the callers that know the
     frame index): try `gui/bam/<RESREF>/<i>.png` if `Enabled(GUI)`, else
     `sprites/bam/<RESREF>/<i>.png` if `Enabled(Sprites)`. The pipeline puts a resource in
     only one category.
4. **GLVideo (`plugins/GLVideo/GLVideo.cpp`):**
   - In `PrepareSprite`, when `spr->hiRes` is set, bind the twin's texture instead
     (`texMode = 1` RGBA, `pal = -1`, `ckey = -1`) and return the texel scale
     `k = hiRes->Frame.w / spr->Frame.w` (add an out parameter).
   - Every caller multiplies its texel coordinates by `k`: `DrawSprite` (`u0..v1` and the
     outline's `texPerUnit`/`outlineRadius`), `BlitSpriteQuad`, and any other caller. Grep for
     `PrepareSprite(` and `GetTexture(` and handle each one.
   - Tints (`COLOR_MOD`), alpha, grey and sepia already work in RGBA mode; check that the
     shader's grey path runs for `texMode 1`.
   - Blend modes that need palette index 0 to be black (`ONE_MINUS_DST`/`DST`/`SRC`): with the
     twin, alpha 0 already gives that. Test one such effect when sprites get turned on.
   - Use linear sampling for the twin when its texel density is above the target's. The current
     shader filters manually (`smooth`), so make sure RGBA texture sampling stays correct with
     `k > 1`.
   - **Lighting / `LightGeometry`:** find out whether the generated depth/normal maps read tile
     or sprite pixels (grep `LightGeometry` and the depth/normal generation). If they do, keep
     them reading the low-res sprite. Lighting output must look the same with the toggle on or off.
5. **Anything that copies pixels drops the twin. That's fine; it just shows the original.**
   Known cases: font glyph pages, palette-recoloured creature sprites (`SetPalette` with a new
   palette on an indexed sprite whose twin was baked with the old one: clear `hiRes` in that
   path when the palette really differs), and sprite blending into buffers. Don't try to make
   those work now.
6. **Config:** add `UpscaledGUI`, `UpscaledAreas`, `UpscaledSprites` and `UpscalePath` to the
   GemRB.cfg sample/docs the way other fork options are, and add these lines to
   `tools/dev_settings.ini` under `[GemRB.cfg]`:
   ```
   ; upscaled art (UPSCALE_PLAN.md): GL driver draws tools\upscale output at logical size
   UpscaledGUI=1
   UpscaledAreas=1
   UpscaledSprites=0
   ```
   Leave `UpscalePath` unset, so the default `D:\Games\GemRB\upscaled` is used.
   `build_install.bat` must never delete or copy over `upscaled\`.
7. **Unit test** (`Test_gemrb_core`): `HiResArt::Attach` accepts a 2× PNG, rejects a 1.5× one,
   and ignores a missing file. A write lock on the sprite clears `hiRes`.

## 5. Phase D: run it

1. Run `setup_env.bat`, pick the models (section 2, step 4, with the user), then do a
   `--dry-run` and save the counts.
2. Run a test batch: `--categories areas --only <two areas>` plus `--categories gui --limit 50`.
   Check it in game (section 6) **before** the full run.
3. Full run in the background: `tools\upscale\run_upscale.bat --categories gui,areas`.
   Expect hours. Report progress from the log, and restart with the same command after any stop.
4. Tell the user the final disk size of `upscaled\` and how many items failed (`errors.log`).

## 6. Phase E: check it in game

Use `tools\dev.ps1` (start / shot / log).

- Make the window bigger than 1280×720 (fullscreen, or a larger window) so `renderScale > 1`,
  and check `gemrb.log` for `Render scale` and the `HiResArt` attach counts.
- Take screenshots of the same view with each toggle on and off (Mortuary start area, a Hive
  area, the main GUI, inventory, a dialogue): the art must line up pixel for pixel, with no
  offsets, seams at tile edges, halos, or missing door/animated tiles. Zoom in with the mouse
  wheel and compare.
- Open and close doors, check animated tiles (water, fires), the minimap, the world map and the
  inventory icons.
- Hovering and clicking creatures and containers works exactly as before (hit tests use the low-res pixels).
- Area load time and VRAM: log the area load time with the toggle on vs off. If load time goes
  up by more than ~1 s, make `Attach` lazy (store the path, load on first draw in GLVideo) or
  load in a worker thread.
- `tools\tb_autotest.ps1` still passes.

## 7. Later: sprites (`UpscaledSprites`)

Already covered by the hooks above. To turn it on:

1. Run `--categories sprites`, on a small sample first.
2. Recoloured creatures: the engine recolours some PST creature animations through the palette
   (colour ranges). A baked RGBA twin can't follow that. Choose one:
   - (a) skip the twin when the palette was modified (step 5 already falls back), or
   - (b) for those BAMs, also emit a hi-res **index** image (upscale, then map each pixel to its
     nearest palette entry) and draw it as an indexed texture, so palette swaps keep working.

   Start with (a).
3. Shadows (index 1) and effect BAMs drawn with additive blending: check each looks right.
4. Shimmer across animation frames: compare a walk cycle; if it shimmers, try another model.

## 8. Gaps (not covered by gui/areas/sprites)

- **Fonts:** the engine copies BAM glyphs into a palette page, then draws that page twice
  (once inverted). A photo model fills the counters of these 8px faces and drops the
  punctuation, so each glyph is Scale2x of the original indices (still an indexed PNG).
  The page is drawn nearest-neighbour: the grey ramp is already the antialiasing.
  `NORMAL` is an alias of `FONTDLG`.
- **Cursors:** easy to add to gui, but the hot spot must scale. Left out for now.
- **Movies** (MVE/BIK cutscenes): needs a video upscale pipeline (frames, upscale, re-encode)
  plus playback of a replacement file. A separate task.
- **BMP images** (some PST GUI pieces and portraits are BMP): add a `gui/bmp/` path and a hook
  in `BMPImporter` if the GUI scan finds any.
- **Paperdolls and PLT:** PST has none.
- **Data maps** (light, search and height maps): deliberately never upscaled.

## 9. Progress

- [ ] A: environment + model choice
- [ ] B: pipeline (index, classify, extract, upscale, resume)
- [x] C: engine (Sprite2D twin, HiResArt, hooks, GLVideo, toggles, unit test)
- [ ] D: run gui + areas
- [ ] E: in-game check
- [ ] Sprites (later)
