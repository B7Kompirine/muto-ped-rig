# Muto Ped Rig — personal FiveM humanoid rigging add-on

Fits any humanoid character (AI-generated, Sketchfab, your own model) to the **real GTA V ped skeleton**, weights it,
converts it to the GTA rest pose and exports it to the game through Sollumz.
Written from scratch; contains no Auto-Rig Pro code.

- Requirements: Blender 4.2+ (tested with Blender 5.2) and [Sollumz](https://github.com/Sollumz/Sollumz) 2.9
  (tested with the legacy add-on install, `scripts/addons/Sollumz`).
- **Drag & drop install:** open https://b7kompirine.github.io/muto-ped-rig/ and drag the *Muto Ped Rig* link into a Blender window.
- **Updates inside Blender:** Edit → Preferences → Get Extensions → Repositories (top right) → **+** → *Add Remote Repository* →
  `https://b7kompirine.github.io/muto-ped-rig/index.json`. New versions then show up as updates.
- **Manual install:** download `muto_ped_rig-<version>.zip` from [Releases](https://github.com/B7Kompirine/muto-ped-rig/releases) →
  Blender → Edit → Preferences → Get Extensions → ⌄ (top right) → **Install from Disk…**
- Panel: 3D Viewport → **N** → **Muto Rig** tab → **Muto Ped Rig** panel. Buttons are greyed out outside Object Mode or when
  no mesh is selected; the tooltip tells you why.

## Workflow

| Step | Button | What it does |
|---|---|---|
| 0 | **Remove Existing Rig** (models that come with a rig) | Removes the old Mixamo / Unreal / Sketchfab rig: parent (world transform kept), armature modifier, vertex groups, shape keys; deletes the old armature if nothing uses it. Facial shape keys are lost; Ctrl+Z undoes it. Not needed for unrigged models. |
| 0 | **Fix Orientation/Scale** | If the character does not face -Y (most FBX/GLB files face +Y), turns it around Z in 90° steps based on the feet; rescales centimeters/millimeters to meters and applies the transform (Ctrl+Z undoes it). |
| 1 | **Auto Markers** (or *Add Markers*) | Checks orientation and height first and stops with the reason if something is off. Finds the joints; drag the spheres to adjust. *Mirror L > R* copies the left side to the right. |
| 2 | **Fit Skeleton** | Builds the 128-bone freemode skeleton in the character's own pose (names, tags, parents and count never change). |
| 3 | **Compute Weights** | Transfers vanilla ped weights to the character; 12 vanilla bodies vote on the limbs. |
| 4 | **Convert to GTA Rest Pose** | Moves the mesh and skeleton into the GTA rest pose with vanilla rotations (required for T-pose characters). |
| – | **Validate** | Skeleton signature + ≤4 influences / unweighted vertices + vertex color layer `Color 2` (wind/sweat; non-zero makes the ped jitter in game). |
| 5 | **Export to Sollumz + Test Resource** | Splits into head/uppr/lowr drawables and assigns ped materials; textures go into `<ped>.ytd` under GTA names (like vanilla peds), single-variation `.ymt`, physics-free `.yft` + `.ydd`; resource with a `/mprped` command (add-on ped: `/<ped name>`). |

The character must **stand upright, face -Y and be in meters** (in Blender's front view its face looks at you). Otherwise run
*Fix Orientation/Scale* first. A-pose gives the best result; T-pose is supported. A lying character is not fixed automatically.
A GTA ped is about **1.8 m** tall: scale smaller or larger characters (e.g. AI models normalized to 1 m) to that height and apply the transform first.

## Measured accuracy (against vanilla bodies)

- Auto markers: 12 different vanilla bodies × 3 arm poses (57° A, 35°, T), average **2.3 cm**, 90th percentile 4.7 cm (each body excluded from its own data).
- Characters with different proportions (legs ±20%, big head, long arms, wide shoulders/hips, cartoon proportions): average **2.6–3.1 cm**.
  Heights come from body landmarks (shoulder line, crotch thickness, back of the hips), not from height ratios.
- Full chain (auto markers → skeleton → weights) on characters with different proportions, 14 test poses, deformation 95th percentile:
  male body ~1.7 mm, heavy body ~1.4 mm (target body excluded from the references). Auto markers also place the middle finger chain (hand direction and length).
- Real non-GTA character (a Sauron add-on ped: long spiked crown + spiked armor, 50k vertices, 1.97 m; its own skeleton removed and
  used as reference): auto markers average **2.5 cm**, fitted skeleton average 2.3 cm; 88–100% of arm and leg weights on the same bone as the original rig.
  Thin protrusions (crown spikes, horns, antennas) are not taken for the neck.
- Rigged game rip (Winter Soldier, Unreal FBX: thick armored arms, hanging hands, 93k vertices, 1.81 m; own skeleton removed and used
  as reference): the arm tip is the point on the same arm farthest from the body (fingertip), not the outermost point of the arm (bracer)
  → hand/arm markers average **2.8 cm** (the wrist used to be 14 cm off, fingers 16–20 cm); vanilla and proportion tests unchanged.
  The shoulder marker differs by ~10 cm from Unreal's shoulder joint → check the shoulder sphere.
- 6 downloaded rigged characters (three.js Soldier/Xbot/Michelle/Ready Player Me, Khronos CesiumMan/BrainStem; own skeletons removed and
  used as reference): auto markers average **3.4–4.6 cm** on Xbot, Ready Player Me, Michelle and CesiumMan;
  80–91% of the vertices in the same body region as the original rig; deformation difference to the original rig over 9 test poses,
  95th percentile 35–64 mm. Segmented bodies (Xbot's separate joint shells) and T-poses with arms wider than the height (BrainStem robot) work.
- Non-GTA topology (synthetic humanoid built with the Skin modifier): limb markers average 3.5 cm in A-pose / 5.4 cm in T-pose;
  98–100% of the limb vertices away from joints on the correct bone. Same result for a copy facing +Y in centimeters after *Fix Orientation/Scale*.
- Weights: 12 vanilla bodies × 14 test poses, deformation error 95th percentile average **0.71 mm** (0.0–2.7 per body; target body excluded from the references).
- T-pose → GTA rest pose: 95th percentile **1.3 mm** (LBS ceiling 1.2 mm).
- Rules: ≤4 bones per vertex, sum exactly 1.0, 1/255 steps, zero weight difference across UV seams.
- Speed and memory (synthetic humanoid, weight step): 3.6k vertices 3.4 s / 0.5 GB · 15k 5.9 s / 0.7 GB · 58k 19 s / 1.8 GB ·
  233k 2.8 min / 5.8 GB; same quality (markers ~3.3 cm, 99% of the limbs on the correct bone). Reduce meshes with hundreds of thousands
  of vertices (AI-generated) with Decimate first: memory grows by ~25 KB per vertex.
- Sollumz splits parts at GTA's limit of 65,535 vertices per geometry by itself (22 geometries at 233k vertices, indices valid on read-back).
  A mesh without UVs cannot share corners and the file grows ~4× (233k vertices → 31 MB `.ydd`; with UVs 0.68 vertices per triangle) → unwrap UVs first.

## Options

- **Reference Body**: Automatic (best-matching male/female freemode body) · Male · Female.
- **Multi-Body Limb Voting** (on): a single body's wrong limb decision is outvoted.
- **Merge Face Bones into Head** (on): no weights on `FB_` bones; no facial animation, skeleton only.
- **Attach Hair/Hats to Head** (on): parts separate from the body that rise above the head (hair strands, hats, glasses) get Head/Spine3
  by height (ramp measured on Rockstar hair drawables). A separately modeled head object is left untouched.
- **Disable Roll Bones** (off): `RB_` twist distribution like vanilla. In game the `RB_` bones are driven by expressions — the ped's
  `ExpressionSetName` must be an ambient/freemode set.
- **Disable MH_ Bulge Bones** (off): no weights on the elbow/knee/hand bulge helpers.
- **Engine: Volume (Voxel Geodesic)**: fallback engine for non-human or very different bodies.
- **Textures** (export): *Texture Dictionary (.ytd)* by default — the game looks up ped textures by name (`head_diff_000_a_whi`,
  `uppr_diff_000_a_uni`, `lowr_diff_000_a_uni` + `_normal_000` / `_spec_000`); the add-on writes DDS files under these names into
  `<ped>.ytd` instead of embedding them in the `.ydd`. *Embedded (Legacy)*: the color texture is embedded in the `.ydd` under its own name, no `.ytd`.
- **Vertex colors** (export, automatic): missing `Color 1` / `Color 2` layers are created like on vanilla peds — `Color 1` = `FF8000`
  (lighting), `Color 2` = `0,0,0,0` (wind/sweat off). Existing layers are kept; *Validate* warns when `Color 2` is not zero.

## Testing in game

1. *Output Type*:
   - **Replace Vanilla Ped** (default): *Ped Name* must be a vanilla ped, e.g. `a_m_y_beach_01` — the game's own `peds.meta` / `.ymt`
     is used; every `a_m_y_beach_01` in the world becomes this character. The safest path for a single character. A non-vanilla name
     is refused (no `peds.meta` is written in this mode, so the game would never know the model).
   - **Add-on Ped (New Model)**: *Ped Name* is a new model name (e.g. `muto_character_01`; lowercase letters, digits, _; must not clash
     with a vanilla name). `peds.meta` + `<name>.ymt` are written and `fxmanifest` declares `data_file 'PED_METADATA_FILE'` →
     **several characters** side by side as separate resources. Templates come from game data: the `peds.meta` entry from DLC
     `A_M_Y_CarClub_02` (CIVMALE), the `.ymt` as a single variation of vanilla `a_m_y_beach_01` (drawable 000 + texture a per component, no props).
   - Both modes write a single-variation `.ymt`: the vanilla `.ymt` lists extra drawables/textures we don't have → a random pick would make parts invisible.
2. *Export to Sollumz* → creates `<output>/mpr_<ped>/` (`fxmanifest.lua`, `client.lua`, `stream/`).
3. Copy the folder into the server's `resources` folder, `ensure mpr_<ped>`.
4. **Disconnect from the server and reconnect** (a restart is not enough; asset cache).
5. In game run `/mprped` (add-on ped: the ped name is the command, e.g. `/muto_character_01`; several add-on peds can be on the server at once).

## Known limits

- ⚠️ Add-on peds from this add-on currently print an F8 script error when the client calls `SetPedDefaultComponentVariation`
  (the model still loads, animates and shows its textures). A hand-made add-on ped package does not → the cause is in the
  generated `peds.meta` / `.ymt`, still under investigation. *Replace Vanilla Ped* has no such error.
- Very heavy characters whose arms rest on the belly and are **connected** to the body in the mesh may get wrong waist-side weights → fix them by hand.
- Individual markers can be 6–11 cm off in the worst case → check the spheres visually. Measured worst cases: hip/pelvis ~11 cm and knee
  ~7 cm too low on a heavy body with long (+20%) legs; ankle/toe, knee, shoulder 6–9 cm. In T-pose the shoulder ~5 cm on a wide-shouldered body.
- Loose trousers/skirts merge the legs. In a synthetic test (separate trousers object 5 cm outside the body) the hip stays ~6.5 cm and
  the knee ~3.5 cm too low → check the hip/knee spheres. A separate clothing object moves with the body (same test: change of the
  clothing–body gap across poses, 95th percentile 4 mm, max 7 mm).
- On characters without a visible deltoid (straight tube arms, stylized/low-poly) the T-pose shoulder marker may stay ~8 cm inward
  horizontally (synthetic test) → in T-pose drag the shoulder sphere above the arm root.
- On characters whose thighs touch down to the knees (loose/armored trousers) with straps or holsters hanging between the legs, the hip
  may be found ~28 cm and the knee ~18 cm too low (Soldier test) → check the hip and knee spheres.
- On characters whose neck is hidden inside an armored collar or helmet, the neck and head markers may sit 10–14 cm too high → drag the neck/head spheres.
- The add-on reads the mesh without modifiers: apply any unapplied Mirror/Subdivision first.
- If the hair is part of the SAME connected mesh piece as the body, the hair rule does not work (the reference bodies have no hair →
  hair hanging down the back goes to Spine3 and stays in place when the head turns) → make the hair a separate piece or paint it to Head by hand.
- Color textures are DXT1 (DXT5 with alpha), at most 2048², with mips like vanilla; larger sources (e.g. 4096 DDS) are downscaled and
  re-encoded, and a texture shared by the three parts is encoded once (Sauron: `.ytd` 16 → 4.9 MB). *Embedded (Legacy)* mode uses
  uncompressed A8R8G8B8. Normal/spec maps are flat (average of the vanilla ped textures).
- The game looks up one color texture name per drawable (head/uppr/lowr): when a part has several textured materials, the add-on
  **bakes them into one atlas** (cells by surface area, at most 2048², UVs moved into the cells; untextured faces get a grey cell).
  Winter Soldier (11 textures): per-corner color difference average 2.3–3.3 / 255 (old single-texture path 7.7–52.6). With many textures
  each source shrinks (face 512 px in the head atlas); wide parts such as hair cards get bigger cells. Textures missing on disk become grey (warning).
- Drawables (head/uppr/lowr) are split per face, so giving the parts different textures shows a jagged edge at the border; it is not
  visible when the whole body uses the same texture.
- Verified in game: vanilla ped replacement (loading, walk/run/jump deformation, textures, no F8 error); add-on ped
  (loads, textures and deformation); `.ytd` texture path; texture atlas and the vertex color fix (no jitter).
- The ped `.yft` has no physics: no ragdoll or bullet collision (Sollumz ped physics crashes the game).

## Development

- `core/` runs without Blender (numpy only); `bl/` holds the Blender operators, panel and Sollumz export.
- Development tests and measurement tools live outside this repository. Code comments are in Turkish (ASCII).

## License and game data

- Code: GPL-3.0-or-later (see `LICENSE`), as required for Blender add-ons.
- `data/` contains skeleton, body and metadata values derived from Grand Theft Auto V files, included only so the add-on can produce
  compatible ped resources. Grand Theft Auto V and its assets belong to Rockstar Games / Take-Two Interactive; this project is not
  affiliated with or endorsed by them, and the GPL does not cover that data. You need a legitimate copy of the game.
- Not affiliated with Cfx.re / FiveM or the Sollumz project.
