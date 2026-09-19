import bpy
from . import io
from ..core import markers as mk
from ..core import species as sp


def _section(layout, idname, title, icon="NONE"):
    """Az kullanilan ayarlar icin acilir bolum, varsayilan kapali (Blender 4.1+ layout.panel). Kapaliyken None."""
    head, body = layout.panel(idname, default_closed=True)
    head.label(text=title, icon=icon)
    return body


class MPR_PT_main(bpy.types.Panel):
    bl_label = "Muto Ped Rig"
    bl_idname = "MPR_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muto Rig"

    def draw(self, context):
        s = context.scene.mpr
        L = self.layout
        arm = bpy.data.objects.get(io.RIG_NAME)
        stage = arm.get("mpr_stage") if arm else None
        animal = s.rig_type != "mp_m"

        b = L.box()
        b.label(text="1. Markers", icon="EMPTY_AXIS")
        b.prop(s, "rig_type", text="")
        b.operator("mpr.strip_rig", icon="TRASH")
        r = b.row(align=True)                            # hayvanda yalniz boya olcek (yon kontrolu insan govdesine gore olculdu)
        r.operator("mpr.fix_orientation", icon="ORIENTATION_GLOBAL", text="Scale to Height" if animal else "Fix Orientation/Scale")
        r.prop(s, "target_height", text="Height")
        r = b.row(align=True)
        r.operator("mpr.markers_auto", icon="VIEWZOOM")               # hayvanda ped'in oyun mesh'i oturtulur (core/animal_markers)
        if animal:
            r.operator("mpr.markers_add", icon="ADD")
        else:
            r.operator("mpr.markers_click", icon="RESTRICT_SELECT_OFF")   # yari otomatik: 10 ana nokta tikla, kalani algilama / sablon
            r = b.row(align=True)                        # parmak / yuz: marker + kemik gorunumu + agirlik ayni dugmeden
            r.prop(s, "detail_fingers", toggle=True, icon="HAND")
            r.prop(s, "detail_face", toggle=True, icon="USER")
        b.operator("mpr.markers_mirror", icon="MOD_MIRROR")
        label = sp.label if animal else mk.label
        have = io.read_markers()
        refs = io.read_marker_refs()
        pend = mk.propagate_linked({k: refs.get(k, p) for k, p in have.items()}, have) if refs else {}
        if pend:                                         # yalniz is varken gorunur
            b.operator("mpr.markers_update_linked", icon="LINKED")
            b.label(text="Moved: " + ", ".join(label(k) for k in sorted(pend)), icon="INFO")
        miss = [label(k) for k in (sp.QUAD_REQUIRED if animal else mk.REQUIRED) if k not in have]
        if miss:
            b.label(text="Missing: " + ", ".join(miss[:4]) + ("..." if len(miss) > 4 else ""), icon="ERROR")
        if arm is not None and io.rig_template(arm) != s.rig_type:
            b.label(text=f"MPR_Rig is {io.rig_template(arm)}: Fit Skeleton replaces it", icon="ERROR")
        body = _section(b, "mpr_more_markers", "More Marker Tools")
        if body:
            if not animal:
                body.operator("mpr.markers_add", icon="ADD")
                body.operator("mpr.markers_from_rig", icon="ARMATURE_DATA")   # hazir iskelet (Mixamo / Unreal): Remove Existing Rig'den ONCE
                r = body.row(align=True)
                c = r.row(align=True)
                c.enabled = s.detail_fingers
                c.prop(s, "hand_template", icon="HAND")
                c = r.row(align=True)
                c.enabled = s.detail_face
                c.prop(s, "face_template", icon="USER")
            body.prop(s, "mirror_x")
            body.prop(s, "marker_size")

        b = L.box()
        b.label(text="2. Skeleton", icon="ARMATURE_DATA")
        b.operator("mpr.fit", icon="BONE_DATA")
        if stage:
            b.label(text="Status: " + ("character pose (P)" if stage == "P" else "GTA rest pose (G)"))

        b = L.box()
        b.label(text="3. Weights", icon="MOD_VERTEX_WEIGHT")
        b.operator("mpr.weights", icon="WPAINT_HLT")
        if animal:
            b.label(text="Transferred from the game's four-legged animals", icon="INFO")
        else:
            body = _section(b, "mpr_weight_options", "Weight Options")
            if body:
                body.prop(s, "engine", text="")
                if s.engine == "TRANSFER":
                    body.prop(s, "ref_body")
                    body.prop(s, "use_votes")
                body.prop(s, "merge_roll")
                body.prop(s, "merge_mh")
                body.prop(s, "head_parts")

        b = L.box()
        b.label(text="4. GTA Rest Pose", icon="POSE_HLT")
        r = b.row(align=True)
        r.operator("mpr.to_gta_rest", icon="ARMATURE_DATA")
        r.operator("mpr.validate", icon="CHECKMARK")

        b = L.box()
        b.label(text="5. Sollumz Export / Game Test", icon="EXPORT")
        b.prop(s, "export_mode", text="")
        b.prop(s, "ped_name")
        b.prop(s, "export_dir")
        b.operator("mpr.sollumz_export", icon="FILE_TICK")
        body = _section(b, "mpr_export_options", "Export Options")
        if body:
            body.prop(s, "tex_mode", text="")
            body.prop(s, "export_lods")

        body = _section(L, "mpr_animation", "Animation (Retarget)", icon="ACTION")
        if body:
            c = body.column(align=True)
            c.label(text="Puts a Mixamo / Unreal animation", icon="INFO")
            c.label(text="on the GTA skeleton and exports it")
            body.prop(s, "anim_source")
            r = body.row(align=True)
            c = r.row(align=True)
            c.enabled = not s.anim_all_clips
            c.prop(s, "anim_action")
            r.prop(s, "anim_all_clips", toggle=True)
            body.prop(s, "anim_root_motion", text="")
            body.operator("mpr.retarget", icon="PLAY")
            r = body.row(align=True)
            r.prop(s, "anim_dict_name", text="")
            r.operator("mpr.export_clips", icon="EXPORT")

        body = _section(L, "mpr_batch", "Batch (Folder)", icon="FILE_FOLDER")
        if body:
            c = body.column(align=True)
            c.label(text="Rigs every model in a folder", icon="INFO")
            c.label(text="automatically, one by one")
            body.prop(s, "batch_src")
            body.prop(s, "batch_out")
            r = body.row(align=True)
            r.prop(s, "batch_prefix")
            r.prop(s, "batch_workers")
            body.operator("mpr.batch_run", icon="PLAY")
        if s.batch_status:                               # kapali bolumde de gorunsun (calisan is)
            L.label(text=s.batch_status, icon="INFO")


classes = (MPR_PT_main,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
