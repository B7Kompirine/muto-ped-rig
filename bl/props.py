import bpy
from ..core.species import ANIMAL_PEDS


def _detail_changed(self, context):
    from . import io
    io.apply_detail_visibility(self)


class MPR_Settings(bpy.types.PropertyGroup):
    rig_type: bpy.props.EnumProperty(
        name="Skeleton",
        items=[("mp_m", "Human (GTA Freemode)", "Humanoid characters: the GTA freemode ped skeleton")]
              + [(k, f"Animal: {lbl}", f"Four-legged animal on the {k} ped skeleton (its own bones, tags and game animations)")
                 for k, lbl in ANIMAL_PEDS],
        default="mp_m")
    engine: bpy.props.EnumProperty(
        name="Engine",
        items=(("TRANSFER", "Vanilla Body Transfer", "Humanoid characters: vanilla ped weights are fitted and transferred (best result)"),
               ("VOXEL", "Volume (Voxel Geodesic)", "Non-human or very different bodies: bone distance is measured through the volume")),
        default="TRANSFER")
    ref_body: bpy.props.EnumProperty(
        name="Reference Body",
        items=(("auto", "Automatic (Best Match)", "Pick the male or female freemode body closest to the character"),
               ("mp_m", "Male (mp_m_freemode_01)", ""), ("mp_f", "Female (mp_f_freemode_01)", "")),
        default="auto")
    use_votes: bpy.props.BoolProperty(
        name="Multi-Body Limb Voting", default=True,
        description="12 vanilla bodies vote on the limb of each vertex, so one body's wrong limb choice is outvoted "
                    "(measured: the 95th percentile error dropped on all 6 targets)")
    detail_fingers: bpy.props.BoolProperty(
        name="Fingers", default=True, update=_detail_changed,
        description="Find the finger joints and weight the 30 finger bones. Off: no finger markers, finger bones are hidden and their "
                    "weights go to the hand (fingers move with the hand). The bones stay in the exported skeleton: every GTA human "
                    "ped has them and animations expect them")
    hand_template: bpy.props.BoolProperty(
        name="Hand Template", default=True,
        description="Auto Markers: place the 15 finger joints by fitting the vanilla GTA hand meshes to the character's hands "
                    "(takes a few seconds). Off: finger joints come from fingertip detection only")
    detail_face: bpy.props.BoolProperty(
        name="Face", default=True, update=_detail_changed,
        description="Place and weight the animated face bones (jaw, lips, eyes, lids, brows, cheeks, tongue). Off: no face markers, "
                    "face bones are hidden and all face weights go to SKEL_Head (no facial animation). The bones stay in the exported "
                    "skeleton, like vanilla peds")
    face_template: bpy.props.BoolProperty(
        name="Face Template", default=True,
        description="Auto Markers: place the 22 face bones by fitting the vanilla GTA head meshes to the character's head "
                    "(takes several seconds). Off: the face bones follow the head with the template's offsets")
    merge_roll: bpy.props.BoolProperty(
        name="Disable Roll Bones", default=False,
        description="Do not weight RB_ twist bones. Off by default: distributed like vanilla; "
                    "in game RB_ bones are driven by expressions (peds.meta ExpressionSetName required)")
    merge_mh: bpy.props.BoolProperty(
        name="Disable MH_ Bulge Bones", default=False,
        description="Do not weight the elbow/knee/hand bulge helper bones")
    head_parts: bpy.props.BoolProperty(
        name="Attach Hair/Hats to Head", default=True,
        description="Parts separate from the body that rise above the head (hair strands, hats, glasses) get Head/Spine3 "
                    "weights by height. A separately modeled head object is left untouched")
    export_mode: bpy.props.EnumProperty(
        name="Output Type", default="REPLACE",
        items=[("REPLACE", "Replace Vanilla Ped",
                "Ped name must be a vanilla ped (a_m_y_beach_01: head/uppr/lowr). The game's own peds.meta/.ymt is used; "
                "every copy of that ped in the world becomes this character"),
               ("ADDON", "Add-on Ped (New Model)",
                "New model name: peds.meta + .ymt are written (templates from game data). "
                "Use it for several characters side by side")])
    export_lods: bpy.props.BoolProperty(
        name="Generate LODs", default=True,
        description="Write simplified Medium and Low versions of every drawable like vanilla peds (humans ~600 / ~100 triangles "
                    "per part, animals ~1100 / ~300). Without them the ped can look broken at a distance")
    tex_mode: bpy.props.EnumProperty(
        name="Textures", default="YTD",
        items=[("YTD", "Texture Dictionary (.ytd, like vanilla)",
                "GTA-named textures per drawable (head_diff_000_a_whi, uppr_diff_000_a_uni...) + flat normal/spec, all in <ped>.ytd. "
                "Vanilla peds work this way; several color textures in one part are baked into one atlas"),
               ("EMBED", "Embedded (Legacy)",
                "The color texture is embedded in the .ydd under its own name, no .ytd. "
                "May not match the texture name the game builds from the .ymt")])
    ped_name: bpy.props.StringProperty(
        name="Ped Name", default="a_m_y_beach_01",
        description="Replace vanilla ped: the ped to replace. Add-on ped: the new model name (lowercase letters, digits, _; "
                    "must not clash with a vanilla name, e.g. muto_character_01). Used as the file names")
    export_dir: bpy.props.StringProperty(name="Output Folder", subtype="DIR_PATH", default="//mpr_export/")
    target_height: bpy.props.FloatProperty(
        name="Target Height", default=0.0, min=0.0, max=10.0, subtype="DISTANCE",
        description="Fix Orientation/Scale scales the character to this height in meters (0 = keep its own height; centimeter/"
                    "millimeter models and heights outside 0.8-3 m are still fixed). Skeleton, weights and export follow the new size")
    marker_size: bpy.props.FloatProperty(name="Marker Size", default=0.025, min=0.005, max=0.2)
    mirror_x: bpy.props.FloatProperty(name="Mirror Axis X", default=0.0,
                                      description="L markers are mirrored to R around this X")
    batch_src: bpy.props.StringProperty(
        name="Models Folder", subtype="DIR_PATH",
        description="Folder with .glb / .gltf / .fbx / .obj characters (subfolders are not scanned)")
    batch_out: bpy.props.StringProperty(
        name="Batch Output", subtype="DIR_PATH", default="//mpr_batch/",
        description="Each model gets <output>/<ped name>/ with the add-on ped resource, a rigged .blend and batch_report.json")
    batch_prefix: bpy.props.StringProperty(
        name="Name Prefix", default="muto_",
        description="Ped names are prefix + file name (lowercase letters, digits, _; at most 32 characters; made unique)")
    batch_workers: bpy.props.IntProperty(
        name="Parallel", default=1, min=1, max=4,
        description="Models processed at the same time; each is a separate background Blender process (more uses more memory)")
    batch_status: bpy.props.StringProperty(name="Batch Status", default="")
    anim_source: bpy.props.PointerProperty(
        name="Source", type=bpy.types.Object, poll=lambda self, o: o.type == "ARMATURE" and not o.name.startswith("MPR_"),
        description="The armature that carries the animation (Mixamo / Unreal / Biped / Rigify / NVIDIA SOMA)")
    anim_action: bpy.props.PointerProperty(
        name="Clip", type=bpy.types.Action,
        description="Animation to transfer (empty: the Source's current animation)")
    anim_all_clips: bpy.props.BoolProperty(
        name="All Clips", default=False,
        description="Retarget every clip that animates the Source's bones (Clip is ignored)")
    anim_root_motion: bpy.props.EnumProperty(
        name="Root Motion", default="MOVER",
        items=(("MOVER", "Root Motion (Mover)", "Walking / running: the hips' horizontal path goes to the GTA mover track like vanilla "
                                                "locomotion, the body stays in place in the clip"),
               ("IN_PLACE", "In Place", "The horizontal path is dropped (the ped does not travel); up-down hip motion is kept"),
               ("NONE", "Rotations Only", "No root position at all (emotes, upper-body clips)")))
    anim_dict_name: bpy.props.StringProperty(
        name="Dictionary", default="muto_anims",
        description="Clip dictionary name = the .ycd file name and the dictionary used in TaskPlayAnim (lowercase, digits, _ and @)")


def register():
    bpy.utils.register_class(MPR_Settings)
    bpy.types.Scene.mpr = bpy.props.PointerProperty(type=MPR_Settings)


def unregister():
    del bpy.types.Scene.mpr
    bpy.utils.unregister_class(MPR_Settings)
