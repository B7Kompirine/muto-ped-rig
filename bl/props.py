import bpy


class MPR_Settings(bpy.types.PropertyGroup):
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
        name="Fingers", default=True,
        description="Weight the 30 finger bones and find the fingertips on the mesh. Off: finger weights go to the hand bone "
                    "(fingers move with the hand as one piece); the finger bones still exist, so the skeleton stays valid")
    hand_template: bpy.props.BoolProperty(
        name="Hand Template", default=True,
        description="Auto Markers: place the 15 finger joints by fitting the vanilla GTA hand meshes to the character's hands "
                    "(takes a few seconds). Off: finger joints come from fingertip detection only")
    detail_face: bpy.props.BoolProperty(
        name="Face", default=True,
        description="Weight the 19 animated face bones (jaw, lips, eyes, lids, brows, cheeks, tongue) from the vanilla references "
                    "that carry face weights. Off: all face weights go to SKEL_Head (no facial animation); the face bones still exist")
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
    marker_size: bpy.props.FloatProperty(name="Marker Size", default=0.025, min=0.005, max=0.2)
    mirror_x: bpy.props.FloatProperty(name="Mirror Axis X", default=0.0,
                                      description="L markers are mirrored to R around this X")


def register():
    bpy.utils.register_class(MPR_Settings)
    bpy.types.Scene.mpr = bpy.props.PointerProperty(type=MPR_Settings)


def unregister():
    del bpy.types.Scene.mpr
    bpy.utils.unregister_class(MPR_Settings)
