import bpy
from . import io
from ..core import markers as mk


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

        b = L.box()
        b.label(text="1. Markers", icon="EMPTY_AXIS")
        b.operator("mpr.strip_rig", icon="TRASH")
        b.operator("mpr.fix_orientation", icon="ORIENTATION_GLOBAL")
        r = b.row(align=True)
        r.operator("mpr.markers_auto", icon="VIEWZOOM")
        r.operator("mpr.markers_add", icon="ADD")
        r = b.row(align=True)
        c = r.row(align=True)
        c.enabled = s.detail_fingers
        c.prop(s, "hand_template", icon="HAND")
        c = r.row(align=True)
        c.enabled = s.detail_face
        c.prop(s, "face_template", icon="USER")
        r = b.row(align=True)
        r.operator("mpr.markers_mirror", icon="MOD_MIRROR")
        r.prop(s, "mirror_x", text="X")
        b.prop(s, "marker_size")
        have = io.read_markers()
        miss = [mk.label(k) for k in mk.REQUIRED if k not in have]
        if miss:
            b.label(text="Missing: " + ", ".join(miss[:4]) + ("..." if len(miss) > 4 else ""), icon="ERROR")

        b = L.box()
        b.label(text="2. Skeleton", icon="ARMATURE_DATA")
        b.operator("mpr.fit", icon="BONE_DATA")
        if stage:
            b.label(text="Status: " + ("character pose (P)" if stage == "P" else "GTA rest pose (G)"))

        b = L.box()
        b.label(text="3. Weights", icon="MOD_VERTEX_WEIGHT")
        b.prop(s, "engine", text="")
        if s.engine == "TRANSFER":
            b.prop(s, "ref_body")
            b.prop(s, "use_votes")
        r = b.row(align=True)
        r.prop(s, "detail_fingers", toggle=True, icon="HAND")
        r.prop(s, "detail_face", toggle=True, icon="USER")
        b.prop(s, "merge_roll")
        b.prop(s, "merge_mh")
        b.prop(s, "head_parts")
        b.operator("mpr.weights", icon="WPAINT_HLT")

        b = L.box()
        b.label(text="4. GTA Rest Pose", icon="POSE_HLT")
        b.operator("mpr.to_gta_rest", icon="ARMATURE_DATA")

        L.operator("mpr.validate", icon="CHECKMARK")

        b = L.box()
        b.label(text="5. Sollumz Export / Game Test", icon="EXPORT")
        b.prop(s, "export_mode", text="")
        b.prop(s, "tex_mode", text="")
        b.prop(s, "ped_name")
        b.prop(s, "export_dir")
        b.operator("mpr.sollumz_export", icon="FILE_TICK")


classes = (MPR_PT_main,)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
