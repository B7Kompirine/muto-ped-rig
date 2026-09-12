import time
import bpy
import numpy as np

from . import io
from ..core import markers as mk
from ..core.fit import fit_skeleton
from ..core import pipeline as pl
from ..core import weights as wt
from ..core.skeleton import lbs


def _meshes_or_fail(op, context):
    objs = io.selected_meshes(context)
    if not objs:
        op.report({"ERROR"}, "Select the character mesh first")
    return objs


def _poll_object_mode(cls, context, need_mesh):
    """Grey the button out instead of failing: Object Mode, plus a selected mesh for operators that work on meshes."""
    if context.mode != "OBJECT":
        cls.poll_message_set("Switch to Object Mode")
        return False
    if need_mesh and not any(o.type == "MESH" for o in (getattr(context, "selected_objects", None) or ())):
        cls.poll_message_set("Select the character mesh")
        return False
    return True


class _MeshOperator:
    @classmethod
    def poll(cls, context):
        return _poll_object_mode(cls, context, need_mesh=True)


class _ObjectModeOperator:
    @classmethod
    def poll(cls, context):
        return _poll_object_mode(cls, context, need_mesh=False)


class MPR_OT_markers_add(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_add"
    bl_label = "Add Markers"
    bl_description = "Create vanilla joint markers scaled to the selected mesh's bounding box (drag them to adjust)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        from ..core import autodetect as ad
        V, _, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V)
        if chk["problems"]:
            self.report({"ERROR"}, "; ".join(chk["problems"]) + " — run 'Fix Orientation/Scale' first")
            return {"CANCELLED"}
        lo, hi = V.min(0), V.max(0)
        pos = mk.initial_guess(io.template(), lo, hi, io.VANILLA_LO, io.VANILLA_HI)
        io.set_markers(pos, context.scene.mpr.marker_size)
        context.scene.mpr.mirror_x = float((lo[0] + hi[0]) / 2)
        self.report({"INFO"}, f"{len(pos)} markers created")
        return {"FINISHED"}


class MPR_OT_markers_auto(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_auto"
    bl_label = "Auto Markers"
    bl_description = ("Find the joints of the selected character automatically (upright humanoid facing -Y; A-pose works best). "
                      "Measured average error in A-pose is about 3-4 cm: drag the markers to adjust afterwards")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..core import autodetect as ad
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        V, F, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V)
        if chk["problems"]:
            self.report({"ERROR"}, "; ".join(chk["problems"]) + " — run 'Fix Orientation/Scale' first")
            return {"CANCELLED"}
        t0 = time.time()
        try:
            det, _info = ad.detect(V, F, io.template(), log=lambda *a: None)
        except ValueError as e:
            self.report({"ERROR"}, f"Automatic detection failed: {e} — place the markers by hand with 'Add Markers'")
            return {"CANCELLED"}
        H = float(np.ptp(V[:, 2]))
        xc = float(_info["xc"])         # algilamanin kullandigi orta hat (autodetect.CENTER_MODE)
        det = ad.apply_calibration(det, ad.load_calibration(), H, xc)
        s = context.scene.mpr
        notes = []                      # rapor: kapidan donen sablonlar (kullanici neden mesh tabanli sonucu gordugunu bilsin)
        if s.detail_fingers:
            # parmak uclari / orta zincir / avuc yonu / bogum (autodetect) + istege bagli el sablon kaydi (core/handreg)
            from ..core import handreg
            handreg.LAST.clear()
            det.update(ad.palm_markers(V, det, io.template(), F, hand_reg=s.hand_template))
            skipped = sorted(S for S, d in handreg.LAST.items() if d.get("rejected")) if s.hand_template else []
            if skipped:
                side = {"L": "left", "R": "right"}
                notes.append(f"Hand Template skipped for the {' and '.join(side[S] for S in skipped)} hand (it did not fit; mesh-based fingers kept)")
        if s.detail_face and s.face_template:
            from ..core import headreg
            headreg.LAST.clear()
            fm = headreg.head_markers(V, det, io.template())              # 22 yuz kemigi (FB_/FACIAL_) kafa sablon kaydindan
            if headreg.LAST.get("rejected"):
                notes.append("Face Template skipped (the head does not match the GTA heads)")
            det.update(fm)
            if "FACIAL_facialRoot" in fm:
                # GTA'da facialRoot = SKEL_Head konumu (12 sablon); kayit Head'i 2,03 -> 1,29 cm iyilestiriyor (tests/an_headreg.py head=1)
                det["head"] = fm["FACIAL_facialRoot"]
        is_face = lambda k: k.startswith(("FB_", "FACIAL_"))
        is_finger = lambda k: len(k) == 5 and k[0] in "LR" and k[1:3] == "_f" and k[3:].isdigit()
        # kapatilan secenekten kalan parmak/yuz marker'lari Fit'e eski hedef olmasin
        io.remove_markers([k for k in io.read_markers() if k not in det and (is_face(k) or is_finger(k))])
        io.set_markers({k: v for k, v in det.items() if not is_face(k)}, s.marker_size)
        io.set_markers({k: v for k, v in det.items() if is_face(k)}, s.marker_size * 0.3)   # yuz kemikleri 1-2 cm arali
        context.scene.mpr.mirror_x = xc
        msg = f"{len(det)} markers found ({time.time()-t0:.1f}s) — check them and drag to adjust" + "".join(f" | {n}" for n in notes)
        rigged = [o.name for o in objs if o.data.shape_keys is not None or any(
            m.type == "ARMATURE" and (m.object is None or m.object.name != io.RIG_NAME) for m in o.modifiers)]
        if rigged:
            self.report({"WARNING"}, msg + f" | existing rig/shape keys: {', '.join(rigged[:3])} — run 'Remove Existing Rig' before weighting")
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MPR_OT_fix_orientation(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.fix_orientation"
    bl_label = "Fix Orientation/Scale"
    bl_description = ("Turn the selected character in 90° steps around Z so the feet point to -Y; rescale centimeters/millimeters "
                      "to meters; apply rotation and scale (undo with Ctrl+Z)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from mathutils import Matrix
        from ..core import autodetect as ad
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        V, _, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V)
        if not chk["problems"]:
            self.report({"INFO"}, f"Orientation and scale are already fine (height {chk['height']:.2f} m)")
            return {"FINISHED"}
        if chk["rot_z_deg"] == 0.0 and chk["scale"] == 1.0 and chk.get("rot_x_deg", 0.0) == 0.0:
            self.report({"ERROR"}, "Cannot be fixed automatically: " + "; ".join(chk["problems"]))
            return {"CANCELLED"}
        lo, hi = V.min(0), V.max(0)
        rx = chk.get("rot_x_deg", 0.0)
        # bas asagi cevirmede donus merkezi yukseklik ortasi (tabandan cevirmek karakteri zeminin altina atar)
        pz = float((lo[2] + hi[2]) / 2) if rx else float(lo[2])
        pivot = Matrix.Translation((float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), pz))
        M = (pivot @ Matrix.Rotation(np.radians(chk["rot_z_deg"]), 4, "Z") @ Matrix.Rotation(np.radians(rx), 4, "X")
             @ Matrix.Scale(chk["scale"], 4) @ pivot.inverted())
        for o in objs:
            o.matrix_world = M @ o.matrix_world
        applied = True
        try:
            with context.temp_override(selected_editable_objects=objs, selected_objects=objs, active_object=objs[0], object=objs[0]):
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        except RuntimeError:
            applied = False                     # multi-user mesh: world placement is still right, only not applied
        V2, _, _ = io.meshes_to_numpy(objs)
        after = ad.orientation_check(V2)
        flip = " flipped upright," if rx else ""
        msg = f"Rotated{flip} {chk['rot_z_deg']:.0f}°, scale {chk['scale']}; height {after['height']:.2f} m" + ("" if applied else " (rotation/scale could not be applied)")
        if after["problems"]:
            self.report({"WARNING"}, msg + " — remaining: " + "; ".join(after["problems"]))
        else:
            self.report({"INFO"}, msg + " — ready")
        return {"FINISHED"}


class MPR_OT_markers_mirror(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_mirror"
    bl_label = "Mirror L > R"
    bl_description = "Copy the left (L_) markers to the right (R_) side across the mirror axis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mx = context.scene.mpr.mirror_x
        m = io.read_markers()
        out = {}
        for k, p in m.items():
            mk_ = mk.mirror_key(k)
            if k.startswith("L_") and mk_:
                out[mk_] = np.array([2 * mx - p[0], p[1], p[2]])
        io.set_markers(out, context.scene.mpr.marker_size)
        self.report({"INFO"}, f"{len(out)} markers mirrored")
        return {"FINISHED"}


class MPR_OT_fit(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.fit"
    bl_label = "Fit Skeleton"
    bl_description = "Build the GTA skeleton from the markers in the character's own pose (bone names, tags and count stay fixed)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        tpl = io.template()
        try:
            T = mk.expand_targets(tpl, io.read_markers())
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        fit = fit_skeleton(tpl, T)
        arm = io.get_or_append_rig()
        io.set_rest(arm, fit.P_W, tpl)
        io.store_fit(arm, fit, "P")
        self.report({"INFO"}, f"Skeleton fitted: {len(T)} targets, scale {fit.g:.3f}")
        return {"FINISHED"}


class MPR_OT_weights(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.weights"
    bl_label = "Compute Weights"
    bl_description = "Weight the selected meshes by GTA rules (at most 4 bones per vertex, sum 1, 1/255 steps)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.mpr
        objs = _meshes_or_fail(self, context)
        arm = bpy.data.objects.get(io.RIG_NAME)
        if not objs:
            return {"CANCELLED"}
        if arm is None or "mpr_fit" not in arm:
            self.report({"ERROR"}, "Run 'Fit Skeleton' first")
            return {"CANCELLED"}
        if arm.get("mpr_stage") != "P":
            self.report({"ERROR"}, "Weights are computed in the character's own pose, but the skeleton is in GTA rest pose. Fit the skeleton again first")
            return {"CANCELLED"}
        tpl = io.template()
        fit = io.load_fit(arm, tpl)
        V, F, ranges = io.meshes_to_numpy(objs)
        t0 = time.time()
        msgs = []
        if s.engine == "TRANSFER":
            W, _ = pl.transfer_pipeline(V, F, tpl, fit, s.ref_body, not s.detail_face, s.merge_roll, s.merge_mh,
                                        use_votes=s.use_votes, head_parts=s.head_parts, merge_fingers=not s.detail_fingers, log=msgs.append)
        else:
            W, _ = pl.voxel_pipeline(V, F, tpl, fit, s.merge_roll, log=msgs.append)
            if not s.detail_fingers:
                W = pl.apply_remap(W, tpl, pl.remap_rules(tpl.names, merge_face=not s.detail_face, merge_fingers=True))
        idx, val = pl.finalize(W, tpl)
        raw = io.bone_raw_names(arm, tpl)
        io.write_weights(ranges, raw, idx, val)
        io.bind(ranges, arm)
        used = len(np.unique(idx[val > 0]))
        self.report({"INFO"}, f"Weights: {len(V)} vertices, {used} bones, {time.time()-t0:.1f}s")
        for m in msgs:
            print("[muto_ped_rig]", m)
        return {"FINISHED"}


class MPR_OT_to_gta_rest(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.to_gta_rest"
    bl_label = "Convert to GTA Rest Pose"
    bl_description = ("Move the mesh and skeleton into the GTA rest pose with vanilla bone rotations (required for T-pose "
                      "characters: otherwise limbs drift in game by the rest pose difference)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        arm = bpy.data.objects.get(io.RIG_NAME)
        if not objs or arm is None or "mpr_fit" not in arm:
            self.report({"ERROR"}, "Skeleton and weights are required")
            return {"CANCELLED"}
        if arm.get("mpr_stage") != "P":
            self.report({"WARNING"}, "Already in GTA rest pose")
            return {"CANCELLED"}
        sk = [o.name for o in objs if o.data.shape_keys is not None]
        if sk:
            # with shape keys, writing vertices.co does not reach the evaluated mesh — the GTA rest pose would silently do nothing
            # (tools/t_strip_rig.py, Blender 5.2.1: written offset 1.0, evaluated 0.0)
            self.report({"ERROR"}, f"Shape keys found ({', '.join(sk[:3])}): the GTA rest pose cannot be applied — run 'Remove Existing Rig' first")
            return {"CANCELLED"}
        tpl = io.template()
        fit = io.load_fit(arm, tpl)
        V, F, ranges = io.meshes_to_numpy(objs)
        raw = io.bone_raw_names(arm, tpl)
        idx, val = io.read_weights(ranges, raw)
        empty = int((val.sum(1) == 0).sum())
        if empty:
            self.report({"ERROR"}, f"{empty} vertices have no weights; compute weights first")
            return {"CANCELLED"}
        Vg = lbs(V, idx, val, fit.repose_matrices())
        for o, a, b in ranges:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.show_viewport = False
        io.set_world_verts(ranges, Vg)
        io.set_rest(arm, fit.G_W, tpl)
        arm["mpr_stage"] = "G"
        for o, a, b in ranges:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.show_viewport = True
        moved = np.linalg.norm(Vg - V, axis=1)
        self.report({"INFO"}, f"GTA rest pose: mesh moved at most {moved.max()*100:.1f} cm")
        return {"FINISHED"}


class MPR_OT_validate(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.validate"
    bl_label = "Validate"
    bl_description = ("Check the skeleton signature (names, tags, parents, count), the GTA weight rules and the "
                      "wind/sweat vertex color layer")
    bl_options = {"REGISTER"}

    def execute(self, context):
        arm = bpy.data.objects.get(io.RIG_NAME)
        if arm is None:
            self.report({"ERROR"}, "MPR_Rig not found")
            return {"CANCELLED"}
        tpl = io.template()
        problems, notes = [], []
        bones = {b.name: b for b in arm.data.bones}
        if len(bones) != len(tpl.names):
            problems.append(f"bone count {len(bones)} != {len(tpl.names)}")
        from ..core.skeleton import canon
        by = {canon(n): b for n, b in bones.items()}
        for i, n in enumerate(tpl.names):
            b = by.get(n)
            if b is None:
                problems.append(f"missing bone {n}")
                continue
            if b.bone_properties.tag != tpl.tags[i]:
                problems.append(f"tag {n}: {b.bone_properties.tag} != {tpl.tags[i]}")
            p = tpl.parents[i]
            if (canon(b.parent.name) if b.parent else None) != (tpl.names[p] if p >= 0 else None):
                problems.append(f"parent {n}")
        objs = io.selected_meshes(context)
        if objs:
            raw = io.bone_raw_names(arm, tpl)
            _, _, ranges = io.meshes_to_numpy(objs)
            for o, a, b in ranges:
                over, empty = 0, 0
                gset = {g.index for g in o.vertex_groups if g.name in set(raw)}
                for v in o.data.vertices:
                    n = sum(1 for g in v.groups if g.group in gset and g.weight > 0)
                    over += n > 4
                    empty += n == 0
                if over:
                    problems.append(f"{o.name}: {over} vertices with more than 4 bones")
                if empty:
                    problems.append(f"{o.name}: {empty} vertices without weights")
            from .sollumz_setup import wind_layer_report, wind_layer_uniform
            for o in objs:
                wind = wind_layer_report(o.data)
                if wind and wind_layer_uniform(o.data):
                    # one flat value = unpainted default (Sollumz 'Create Shader Material' adds it white); export resets it (2026-09-13)
                    notes.append(f"{o.name}: 'Color 2' is one flat value (e.g. added by Sollumz with a ped shader) — export resets it to 0")
                elif wind:
                    # painted "Color 2" is kept by the export; non-zero means wind/sweat in game -> jitter (measured 2026-09-12)
                    problems.append(f"{o.name}: 'Color 2' is non-zero on {wind * 100:.0f}% of corners (wind/sweat) -> jitter in game")
        tail = "".join(f" | {n}" for n in notes)
        for n in notes:
            print("[muto_ped_rig] NOTE:", n)
        if problems:
            for p in problems[:20]:
                print("[muto_ped_rig] PROBLEM:", p)
            self.report({"WARNING"}, f"{len(problems)} problems (first: {problems[0]})" + tail)
        else:
            self.report({"INFO"}, "Clean: signature matches, weight rules OK" + tail)
        return {"FINISHED"}


class MPR_OT_sollumz_export(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.sollumz_export"
    bl_label = "Export to Sollumz + Test Resource"
    bl_description = ("Split the character into head/uppr/lowr drawables, assign ped materials, write a physics-free .yft + .ydd "
                      "and create a resource folder to test in game (/mprped). Disconnect from the server and reconnect")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import sollumz_setup as sz
        import os
        s = context.scene.mpr
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        import re
        name = s.ped_name.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", name):
            self.report({"ERROR"}, "Ped name must be 3-32 characters: lowercase letters, digits, underscore (starting with a letter)")
            return {"CANCELLED"}
        vanilla_like = re.match(r"(a_[mfc]_|s_[mf]_|u_[mf]_|g_[mf]_|mp_[mfg]_|csb_|cs_|ig_|hc_|player_)", name)
        if s.export_mode == "ADDON" and vanilla_like:
            self.report({"ERROR"}, f"Add-on ped name looks like a vanilla ped name ({name}); avoid a clash, e.g. muto_character_01")
            return {"CANCELLED"}
        if s.export_mode == "REPLACE" and not vanilla_like:
            # replace mode writes no peds.meta: a non-vanilla name is never registered -> in game "[mprped] <name> not found"
            # (measured 2026-09-12, mpr_robot)
            self.report({"ERROR"}, f"'{name}' is not a vanilla ped name, but Output Type is 'Replace Vanilla Ped' (e.g. a_m_y_beach_01). "
                                   "For a new model choose 'Add-on Ped (New Model)'")
            return {"CANCELLED"}
        out = bpy.path.abspath(s.export_dir)
        tex_dir = os.path.join(out, "_textures")
        use_ytd = s.tex_mode == "YTD"
        try:
            frag, dic, counts = sz.build_hierarchy(name, objs, tex_dir=None if use_ytd else tex_dir)
            tex_rep = sz.apply_ped_textures(dic, name, tex_dir) if use_ytd else {}
        except (RuntimeError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        stream = os.path.join(out, "_sollumz")
        res = sz.export(frag, dic, stream, "NATIVE", ytd_name=name if use_ytd else None)
        files = [os.path.join(stream, f"{name}.{ext}") for ext in (("yft", "ydd", "ytd") if use_ytd else ("yft", "ydd"))]
        missing = [f for f in files if not os.path.exists(f) or os.path.getsize(f) == 0]
        if "FINISHED" not in res or missing:
            self.report({"ERROR"}, f"Sollumz export incomplete: {missing or res}")
            return {"CANCELLED"}
        rdir = sz.write_test_resource(out, f"mpr_{name}", name, files, s.export_mode)
        addon = s.export_mode == "ADDON"
        extra = " + peds.meta (add-on ped)" if addon else ""
        msg = (f"Written: {rdir}{extra} (faces per drawable: {counts}). Copy it to the server, reconnect, "
               f"then run {'/' + name if addon else '/mprped'}")
        notes = []
        atl = [f"{k.split('_')[0]} {len([t for t in v['atlas'] if not t.startswith('__')])} textures" for k, v in tex_rep.items() if v.get("atlas")]
        if atl:
            msg += " | texture atlas: " + ", ".join(atl)
        multi = [k for k, v in tex_rep.items() if v["multi"] and not v.get("atlas")]
        if multi:
            notes.append(f"several color textures: {', '.join(multi)} — only the largest was used")
        lost = sorted({n for v in tex_rep.values() for n in v["missing"]})
        if lost:
            notes.append(f"textures not found on disk: {', '.join(lost[:4])}{' ...' if len(lost) > 4 else ''}")
        reset = sorted({re.sub(r"\.(head|uppr|lowr)$", "", o.name) for o in dic.children_recursive
                        if o.type == "MESH" and o.data.get("mpr_wind_reset")})
        if reset:
            msg += (f" | 'Color 2' reset to 0 on {', '.join(reset[:4])}{' ...' if len(reset) > 4 else ''} "
                    "(it was one flat value, e.g. added by Sollumz; wind/sweat off, no jitter)")
        no_uv = sorted({re.sub(r"\.(head|uppr|lowr)$", "", o.name) for o in dic.children_recursive if o.get("mpr_no_uv")})
        if no_uv:
            notes.append(f"no UVs: {', '.join(no_uv[:4])}{' ...' if len(no_uv) > 4 else ''} — the texture shows as one color and the file grows ~4x; unwrap UVs first")
        if notes:
            self.report({"WARNING"}, msg + " | " + " | ".join(notes))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MPR_OT_strip_rig(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.strip_rig"
    bl_label = "Remove Existing Rig"
    bl_description = ("Remove the previous rig (Mixamo/Unreal/Sketchfab) from the selected meshes: parent (world transform kept), "
                      "armature modifier, vertex groups, shape keys; delete the old armature if nothing uses it anymore. "
                      "Facial shape keys are lost (undo with Ctrl+Z)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        c = io.strip_foreign_rig(objs)
        self.report({"INFO"}, f"{len(objs)} meshes: parent {c['parent']}, armature modifier {c['modifier']}, vertex groups {c['grup']}, "
                              f"shape keys {c['shape_key']} | old armatures deleted {c['iskelet_silindi']}")
        return {"FINISHED"}


classes = (MPR_OT_markers_add, MPR_OT_markers_auto, MPR_OT_fix_orientation, MPR_OT_markers_mirror, MPR_OT_fit,
           MPR_OT_weights, MPR_OT_to_gta_rest, MPR_OT_validate, MPR_OT_sollumz_export, MPR_OT_strip_rig)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
