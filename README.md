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
| 0 | **Fix Orientation/Scale** | If the character does not face -Y (most FBX/GLB files face +Y), turns it around Z in 90° steps based on the feet; flips an upside-down character; rescales centimeters/millimeters to meters and any other height outside 0.8–3 m to 1.8 m; applies the transform (Ctrl+Z undoes it). |
| 1 | **Auto Markers** (or *Add Markers*) | Checks orientation and height first and stops with the reason if something is off. Finds the joints; drag the spheres to adjust. *Mirror L > R* copies the left side to the right. |
| 2 | **Fit Skeleton** | Builds the 128-bone freemode skeleton in the character's own pose (names, tags, parents and count never change). |
| 3 | **Compute Weights** | Transfers vanilla ped weights to the character; 12 vanilla bodies vote on the limbs. |
| 4 | **Convert to GTA Rest Pose** | Moves the mesh and skeleton into the GTA rest pose with vanilla rotations (required for T-pose characters). |
| – | **Validate** | Skeleton signature + ≤4 influences / unweighted vertices + vertex color layer `Color 2` (wind/sweat; non-zero makes the ped jitter in game). |
| 5 | **Export to Sollumz + Test Resource** | Splits into head/uppr/lowr drawables and assigns ped materials; textures go into `<ped>.ytd` under GTA names (like vanilla peds), single-variation `.ymt`, physics-free `.yft` + `.ydd`; resource with a `/mprped` command (add-on ped: `/<ped name>`). |

The character must **stand upright, face -Y and be in meters** (in Blender's front view its face looks at you). Otherwise run
*Fix Orientation/Scale* first. A-pose gives the best result; T-pose is supported. A lying character is not fixed automatically.
*Fix Orientation/Scale* turns the character to face -Y, converts centimeters/millimeters, flips an upside-down character, and scales any
other height outside 0.8–3 m (e.g. a 51 m Sketchfab export) to **1.8 m**, the height of a GTA ped. Characters inside that range keep their size.
Select only the body: a weapon or prop that sticks out (e.g. an axe held over the head) changes the height and can confuse the detection.

## Measured accuracy (against vanilla bodies)

- Auto markers: 12 different vanilla bodies × 3 arm poses (57° A, 35°, T), average **2.3 cm**, 90th percentile 4.5 cm (each body excluded from its own data).
- Characters with different proportions (legs ±20%, big head, long arms, wide shoulders/hips, cartoon proportions; 4 bodies × 6 types × 3 arm poses):
  average **2.8–3.0 cm**, 90th percentile 5.6–6.3 cm, worst 9.4 cm.
  Heights come from body landmarks (shoulder line, crotch thickness, back of the hips), not from height ratios.
- Full chain (auto markers → skeleton → weights) on characters with different proportions, 14 test poses, deformation 95th percentile:
  male body ~1.7 mm, heavy body ~1.4 mm (target body excluded from the references). Auto markers also place the middle finger chain (hand direction and length);
  when the thumb clearly sticks out of the hand, the thumb, index, ring and pinky tips are found on the mesh and their chains are placed toward
  them, and on straight (not curled) fingers the middle finger chain is placed toward the middle fingertip found on the mesh. The middle
  knuckle is placed where the fingers separate on the mesh surface, and the other fingers' bone lengths follow the middle finger.
- Hands measured against the GTA skeleton itself (12 vanilla bodies × 2 arm poses, hands reshaped with their own GTA bones and weights:
  straight, curled, spread, longer, shorter fingers and a bigger hand): finger joints on straight fingers **2.4 → 2.0 cm**, curled 3.5 → 3.2 cm,
  longer 1.8 → 1.5 cm, shorter 1.7 → 1.5 cm, bigger hand 2.3 → 2.2 cm, unchanged vanilla hands 1.40 → 1.38 cm; finger bone lengths
  closer to the real ones (longer fingers 81% → 90% of the true length, shorter 113% → 104%). Measured relative to the hand bone, the error
  grows slightly (vanilla 1.52 → 1.59 cm, bigger hand 3.4 → 4.2 cm) because the fingers no longer shift together with a misplaced hand.
- **Hand Template** (vanilla GTA hand meshes fitted to the hand; honest test: the target body and every body sharing its hand mesh are
  excluded from the references; 12 vanilla bodies × 3 arm poses): finger joints **1.38 → 0.28 cm**. Hands reshaped with their own GTA
  bones: straight fingers 2.19 → 0.56 cm, curled 3.38 → 0.98, spread 1.80 → 0.63, longer 1.67 → 0.94, shorter 1.40 → 0.58, bigger hand
  2.55 → 1.25 (17 of 432 reshaped hands worse, 10 of them by more than 0.1 cm, at most +0.44 cm; no vanilla hand worse). The safety check below skipped 2 of the
  504 GTA hands, both where the template was worse. With both templates on, Auto Markers takes 3–18 s longer on the real characters
  below (8-core CPU; nearest-point search on up to 8 threads).
  10 rigged non-GTA characters (Xbot, Michelle, Ready Player Me, Soldier, CesiumMan, Winter Soldier and 4 Sketchfab characters; own
  skeletons removed and used as reference — those rigs place joints by their own convention, so these are differences, not GTA errors):
  a safety check skips the template for a hand whose fitted finger joints fall outside the hand mesh (the source rigs' joints are always
  inside), and on a symmetric character the other hand with it. Only one hand ended up further from the source rig than without the template: Michelle's left hand, by 0.1 cm (1.22 → 1.32 cm).
  Skipped on Xbot, Ready Player Me, sf_dune_dweller, sf_goblin, Winter Soldier's left glove and Soldier's right hand; used on sf_eric
  3.94 → 2.03 cm, sf_wendiir 9.74 → 5.93, Soldier's left hand 3.64 → 2.41, Winter Soldier's right hand 1.99 → 1.93, Michelle 1.24 → 1.28.
  Finger bending against the source rig (average vertex difference): sf_eric 12.7 → 8.4 mm, sf_wendiir 37.5 → 27.0, Winter Soldier
  8.0 → 7.8, Michelle 5.6 → 6.1, Soldier 15.1 → 17.0. Turn *Hand Template* off if a character's fingers still look wrong.
- **Face Template** (vanilla GTA head meshes fitted to the head; the target's head family excluded): the 17 face bones that sit the same
  way on freemode and ambient peds (eyes, lids, cheeks, lips, jaw, tongue) **2.33 → 0.71 cm**. GTA places the lip corners and brows
  differently on freemode and ambient peds; these 5 bones are placed the freemode way (freemode bodies 1.98 → 0.68 cm, optimistic: both
  freemode bodies share one head). The fit also moves the head bone closer (2.03 → 1.29 cm).
  When the head does not match the GTA heads (e.g. Xbot's robot head), the face template is skipped and the head marker is left as detected
  (no vanilla body rejected). GTA itself places these face bones 0.43 cm apart on the male and female freemode rigs, which share one head
  mesh, so face accuracy below ~0.5 cm cannot be measured against vanilla peds.
- Real non-GTA character (a Sauron add-on ped: long spiked crown + spiked armor, 50k vertices, 1.97 m; its own skeleton removed and
  used as reference): auto markers average **2.5 cm**, fitted skeleton average 2.3 cm; 88–100% of arm and leg weights on the same bone as the original rig.
  Thin protrusions (crown spikes, horns, antennas) are not taken for the neck.
- Rigged game rip (Winter Soldier, Unreal FBX: thick armored arms, hanging hands, 93k vertices, 1.81 m; own skeleton removed and used
  as reference): the arm tip is the point on the same arm farthest from the body (fingertip), not the outermost point of the arm (bracer)
  → hand/arm markers average **2.8 cm** (the wrist used to be 14 cm off, fingers 16–20 cm); vanilla and proportion tests unchanged.
  The shoulder marker differs by ~10 cm from Unreal's shoulder joint → check the shoulder sphere.
- 6 downloaded rigged characters (three.js Soldier/Xbot/Michelle/Ready Player Me, Khronos CesiumMan/BrainStem; own skeletons removed and
  used as reference): auto markers average **3.1–4.6 cm** on Xbot, Ready Player Me, Michelle and CesiumMan;
  80–91% of the vertices in the same body region as the original rig; deformation difference to the original rig over 9 test poses,
  95th percentile 35–64 mm (region and deformation figures from the earlier full-chain run). Segmented bodies (Xbot's separate joint
  shells) and T-poses with arms wider than the height (BrainStem robot) work.
- Resized skeletons (5 rigged models: Xbot, Michelle, Ready Player Me, CesiumMan, Winter Soldier; each model's own skeleton reshaped and
  the mesh deformed with its own weights, so the true joints stay known): unchanged models average **4.1 cm**; legs ±30%, arms ±30%,
  torso +30%, neck +50%, head ×1.4, height +20%, wider hips, shoulders moved up or out average **3.8–5.1 cm**; one arm 35% longer
  **4.3 cm** (8.6 cm with the old bounding-box body center); ×1.5 giant / ×0.6 dwarf 6.2 / 2.5 cm (the error scales with size).
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
- **Fingers** (on): weights the 30 finger bones and places the finger joints from the mesh. Off: finger weights go to the hand bone (the
  fingers move with the hand as one piece); the finger bones still exist, so the skeleton stays valid.
- **Hand Template** (on, needs *Fingers*): *Auto Markers* fits the vanilla GTA hand meshes to the character's hands and takes the 15
  finger joints from the best fit (a few extra seconds). A hand whose fitted finger joints fall outside the hand mesh (more of them than
  with the mesh-based fingers) keeps the mesh-based fingers; on a symmetric character the other hand does too. Off: finger joints come
  from fingertip detection only.
- **Face Template** (on, needs *Face*): *Auto Markers* fits the vanilla GTA head meshes to the character's head and places the 22 face
  bones from the best fits (several extra seconds). Off: the face bones follow the head with the template's offsets.
- **Face** (on): weights the 19 animated face bones (jaw, lips, eyes, lids, brows, cheeks, tongue) from the vanilla references that carry
  face weights. Off: all face weights go to `SKEL_Head` (no facial animation); the face bones still exist.
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
- Characters with one leg longer than the other (feet at different heights) are not supported: the markers end up far off or detection
  stops with "leg cross-section not found" → place the markers by hand (resized-skeleton test, 5 models).
- Shoulder joints moved well outside the torso outline (e.g. arms mounted wide on a robot) are not followed: with the shoulders moved out
  by 5% of the height, Xbot's marker average went 3.1 → 4.7 cm, the shoulder markers ~15 cm off in the earlier full-chain run → check the shoulder spheres.
- A very large head on a low-poly body can pull the hip and pelvis markers up (CesiumMan with a 1.4× head: marker average 8.3 cm, mostly
  hips/pelvis ~19 cm in the earlier full-chain run) → check the hip spheres.
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
- Auto-marker detection gives identical marker positions inside Blender and in a plain Python install (checked to 6 decimal places):
  candidate end points are sorted with stable tie-breaking, because the default numpy sort orders equal values differently between
  numpy versions. Tests run outside Blender therefore measure exactly what the add-on does.
- Development tests and measurement tools live outside this repository. Code comments are in Turkish (ASCII).

## License and game data

- Code: GPL-3.0-or-later (see `LICENSE`), as required for Blender add-ons.
- `data/` contains skeleton, body and metadata values derived from Grand Theft Auto V files, included only so the add-on can produce
  compatible ped resources. Grand Theft Auto V and its assets belong to Rockstar Games / Take-Two Interactive; this project is not
  affiliated with or endorsed by them, and the GPL does not cover that data. You need a legitimate copy of the game.
- Not affiliated with Cfx.re / FiveM or the Sollumz project.
