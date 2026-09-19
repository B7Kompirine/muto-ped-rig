"""Animasyon paneli operatorleri: yabanci iskeletli klip -> GTA ped iskeleti (bl/retarget.py; esdegerlik tools/t_retarget_equiv.py) ve klip
sozlugu export'u (Sollumz .ycd.xml + core/ycdcheck geri okuma; tools/t_clip_export.py, tools/t_retarget_fbx.py)."""
import os
import re
import bpy
from mathutils import Matrix

from . import io
from . import retarget as rt
from ..core import animmap as am
from ..core import ycdcheck as yc

CLIP_COLL = "MPR_Clips"


def source_actions(src):
    """Kaynagin kemiklerini suren action'lar (kemik kanallarinin yarisindan fazlasi kaynak kemik adi); retarget ciktilari haric."""
    names = {b.name for b in src.data.bones}
    out = []
    for a in bpy.data.actions:
        if "mpr_clip" in a:
            continue
        paths = [fc.data_path for fc in rt.action_fcurves(a) if 'pose.bones["' in fc.data_path]
        if paths and sum(p.split('"')[1] in names for p in paths) / len(paths) > 0.5:
            out.append(a)
    return sorted(out, key=lambda a: a.name)


class MPR_OT_retarget(bpy.types.Operator):
    bl_idname = "mpr.retarget"
    bl_label = "Retarget to GTA"
    bl_description = ("Transfer the Source armature's clip (or all its clips) to the GTA ped skeleton (MPR_AnimRig, the vanilla skeleton in "
                      "GTA rest pose; your character's MPR_Rig is not changed). Mixamo, Unreal, Biped, Rigify and NVIDIA SOMA bone names "
                      "are recognized. Rotations only on limbs, 30 fps, T-pose / A-pose difference corrected")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            cls.poll_message_set("Switch to Object Mode")
            return False
        if context.scene.mpr.anim_source is None:
            cls.poll_message_set("Pick the Source armature (the rig that carries the animation)")
            return False
        return True

    def execute(self, context):
        s = context.scene.mpr
        sc = context.scene
        src = s.anim_source
        if src is None or src.type != "ARMATURE" or src.name.startswith("MPR_"):
            self.report({"ERROR"}, "Source must be the armature that carries the animation (not MPR_Rig / MPR_AnimRig)")
            return {"CANCELLED"}
        if s.anim_all_clips:
            acts = source_actions(src)
            if not acts:
                self.report({"ERROR"}, f"No clip animates {src.name}'s bones")
                return {"CANCELLED"}
        else:
            act = s.anim_action or (src.animation_data.action if src.animation_data else None)
            if act is None:
                self.report({"ERROR"}, f"{src.name} has no animation: pick a Clip")
                return {"CANCELLED"}
            acts = [act]
        try:
            tgt = io.anim_rig()
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        pairs, missing, soma = am.build_pairs([b.name for b in tgt.data.bones], [b.name for b in src.data.bones])
        body_missing = [g for g in am.BONE_MAP if g not in pairs and g != "SKEL_Spine3"]
        if "SKEL_ROOT" in body_missing or len(body_missing) > 2:
            self.report({"ERROR"}, f"Source bones not recognized ({len(body_missing)} body bones missing: {', '.join(body_missing[:5])}) — "
                                   "supported names: Mixamo, Unreal, Biped, Rigify, NVIDIA SOMA")
            return {"CANCELLED"}
        # Kaynak kareleri IMPORT anindaki sahne fps'inde (FBX import'u sahneyi dosyanin fps'ine ceker: 60 fps UE paketi, olculdu
        # 2026-09-14). Retarget sahneyi 30'a ceker -> sonra retarget edilen eski klip 30 fps sanilir, sure iki katina cikar. Bu yuzden
        # fps klibe ILK dokunuldugunda kaydedilir, butun secili kliplere sahne degismeden once.
        cur = sc.render.fps / (sc.render.fps_base or 1.0)
        for a in acts:
            if "mpr_src_fps" not in a:
                a["mpr_src_fps"] = cur
        done, failed = [], []
        for a in acts:
            ok, msg = self.retarget_one(context, src, tgt, a, dict(pairs), missing, soma)
            (done if ok else failed).append(msg)
        sc.frame_set(0)
        if failed:
            self.report({"ERROR"}, " | ".join(failed[:3]) + (f" | {len(done)} other clips retargeted" if done else ""))
            return {"FINISHED"} if done else {"CANCELLED"}
        self.report({"INFO"}, done[0] if len(done) == 1 else f"{len(done)} clips: " + "; ".join(done))
        return {"FINISHED"}

    def retarget_one(self, context, src, tgt, act, pairs, missing, soma):
        s, sc = context.scene.mpr, context.scene
        src_fps = float(act["mpr_src_fps"])
        scale = src_fps / rt.FPS
        sc.render.fps, sc.render.fps_base = rt.FPS, 1.0
        src.animation_data_create()
        src.animation_data.action = act
        try:
            src.animation_data.action_slot = act.slots[0]        # Blender 4.4+: action atamasi yetmez, slot da baglanmali
        except Exception:
            pass
        f0, f1 = int(round(act.frame_range[0])), int(round(act.frame_range[1]))
        static = rt.static_fingers(src, pairs)
        for g in static:
            del pairs[g]
        for pb in tgt.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)             # onceki klipten kalan poz eslenmeyen kemiklerde (Spine3) kalmasin
        tgt.animation_data_clear()
        offs, _skipped = rt.compute_offsets(tgt, src, pairs)
        clip = am.clip_name(act.name)
        old = bpy.data.actions.get(f"GTA_{clip}")
        if old is not None and "mpr_clip" in old and old.users <= 1:
            bpy.data.actions.remove(old)                      # ayni klibi yeniden retarget: .001 kopyasi ciftlenmesin
        out = rt.bake(tgt, src, pairs, offs, f0, f1, f"GTA_{clip}", time_scale=scale, out_f0=0)
        out.use_fake_user = True
        out["mpr_clip"] = clip
        out["mpr_root_motion"] = s.anim_root_motion
        n = rt.frame_count(f0, f1, scale)
        mover = ""
        if s.anim_root_motion != "NONE":
            k, why = rt.transfer_mover(tgt, src, pairs, f0, f1, time_scale=scale, write_mover=s.anim_root_motion == "MOVER", out_f0=0)
            if k is None:
                mover = f", root motion skipped: {why}"
                out["mpr_root_motion"] = "NONE"
        sc.frame_start, sc.frame_end = 0, n - 1
        v = rt.validate(tgt, out, 0, n - 1)
        bad = [f"{k}: {', '.join(b[:3])}" for k, b in v["forbidden"].items() if b]
        notes = []
        if abs(scale - 1.0) > 1e-6:
            notes.append(f"{src_fps:g} -> 30 fps")
        if soma:
            notes.append("SOMA")
        if static:
            notes.append(f"{len(static)} still fingers at the GTA hand pose")
        if "SKEL_Spine3" not in pairs:
            notes.append("Spine3 at rest")
        extra = [g for g in missing if g != "SKEL_Spine3" and "Finger" not in g]
        if extra:
            notes.append("not mapped: " + ", ".join(extra[:4]))
        msg = f"'{clip}' {n} frames ({(n - 1) / rt.FPS:.2f} s), {len(pairs)} bones" + (f" ({', '.join(notes)})" if notes else "") + mover
        if bad:
            return False, msg + " — forbidden channels: " + "; ".join(bad)
        return True, msg


def _key_range(act):
    xs = [kp.co[0] for fc in rt.action_fcurves(act) for kp in fc.keyframe_points]
    return (int(round(min(xs))), int(round(max(xs)))) if xs else (0, 0)


def complete_body_coverage(arm, act):
    """Klibin surmedigi govde SKEL_ kemiklerine (Spine3 gibi) ilk ve son karede birim quaternion = GTA rest. Neden: surulmeyen kemik onceki
    animasyonun pozunda kalir (atlas Kimodo hatti; retarget 52 kemik yazar, vanilla klipler 71-101 surer). Parmaklar BILEREK disarida:
    kaynakta oynamayan parmak dusurulmustu, ped'in o anki el pozu kalsin. SKEL_Pelvis / SKEL_Spine_Root asla. Donus: eklenen kemik sayisi."""
    k0, k1 = _key_range(act)
    keyed = {fc.data_path.split('"')[1] for fc in rt.action_fcurves(act) if 'pose.bones["' in fc.data_path}
    arm.animation_data_create()
    arm.animation_data.action = act
    try:
        arm.animation_data.action_slot = act.slots[0]
    except Exception:
        pass
    n = 0
    for pb in arm.pose.bones:
        name = pb.name
        if not name.startswith("SKEL_") or name in keyed or name in am.NEVER_KEY or "Finger" in name:
            continue
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        for f in sorted({k0, k1}):
            pb.keyframe_insert("rotation_quaternion", frame=f)
        n += 1
    return n


class MPR_OT_export_clips(bpy.types.Operator):
    bl_idname = "mpr.export_clips"
    bl_label = "Export Clip Dictionary"
    bl_description = ("Write every retarget clip into one clip dictionary (<Dictionary>.ycd.xml in the Output Folder) with Sollumz and read "
                      "it back. Sollumz writes clip dictionaries only as XML: open the .ycd.xml in CodeWalker (or its RPF Explorer "
                      "import) to get the .ycd for your resource's stream folder")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        if context.mode != "OBJECT":
            cls.poll_message_set("Switch to Object Mode")
            return False
        if not hasattr(bpy.types.Object, "sollum_type"):
            cls.poll_message_set("Sollumz is not enabled")
            return False
        return True

    def execute(self, context):
        s = context.scene.mpr
        acts = sorted((a for a in bpy.data.actions if "mpr_clip" in a), key=lambda a: a["mpr_clip"])
        if not acts:
            self.report({"ERROR"}, "No retarget clips yet: run Retarget to GTA first")
            return {"CANCELLED"}
        dname = s.anim_dict_name.strip().lower()
        if not re.fullmatch(r"[a-z0-9_@]{1,63}", dname):
            self.report({"ERROR"}, "Dictionary name: lowercase letters, digits, _ and @ only (e.g. muto_anims)")
            return {"CANCELLED"}
        names = [a["mpr_clip"] for a in acts]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            self.report({"ERROR"}, f"Two clips share a name ({', '.join(dup)}): they would overwrite each other — delete one GTA_ action")
            return {"CANCELLED"}
        out_dir = bpy.path.abspath(s.export_dir)
        os.makedirs(out_dir, exist_ok=True)
        tgt = io.anim_rig()
        sc = context.scene
        coll = bpy.data.collections.get(CLIP_COLL)
        if coll is None:
            coll = bpy.data.collections.new(CLIP_COLL)
        if sc.collection.children.get(coll.name) is None:
            sc.collection.children.link(coll)
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        clash = bpy.data.objects.get(dname)
        if clash is not None:
            self.report({"ERROR"}, f"An object is already named '{dname}': Sollumz names the file after the dictionary object — rename it")
            return {"CANCELLED"}

        def empty(name, typ, parent=None):
            o = bpy.data.objects.new(name, None)
            o.sollum_type = typ
            o.empty_display_size = 0
            coll.objects.link(o)
            o.parent = parent
            return o

        d = empty(dname, "sollumz_clip_dictionary")
        an = empty(dname + "_Animations", "sollumz_animations", d)
        cl = empty(dname + "_Clips", "sollumz_clips", d)
        expected = {}
        prev = tgt.animation_data.action if tgt.animation_data else None
        for act in acts:
            clip = act["mpr_clip"]
            complete_body_coverage(tgt, act)
            k0, k1 = _key_range(act)
            if k0 != 0:
                self.report({"ERROR"}, f"clip '{clip}' starts at frame {k0}: run Retarget to GTA again for it")
                return {"CANCELLED"}
            a = empty("anim_" + clip, "sollumz_animation", an)
            a.animation_properties.hash = clip + "_anim"
            a.animation_properties.target_id_type = "ARMATURE"
            a.animation_properties.target_id = tgt.data           # armature DATA; Object verilirse 0 kemik kanali yazilir (atlas)
            a.animation_properties.action = act
            c = empty("clip_" + clip, "sollumz_clip", cl)
            cp = c.clip_properties
            cp.hash = clip                                         # bos kalirsa klibin adi yok, TaskPlayAnim bulamaz
            cp.name = clip + ".clip"                               # Sollumz "pack:/" onekini kendi ekler
            cp.duration = k1 / rt.FPS
            it = cp.animations.add()
            it.animation = a
            it.start_frame, it.end_frame = k0, k1
            expected[clip] = dict(frames=k1 + 1, root_motion=act.get("mpr_root_motion") == "MOVER")
        tgt.animation_data.action = prev
        for o in context.view_layer.objects:
            if o is not None and o.select_get():
                o.select_set(False)
        d.select_set(True)
        context.view_layer.objects.active = d
        if list(context.selected_objects) != [d]:                   # select_set cagrisi secimin kaniti degil (atlas)
            self.report({"ERROR"}, f"Could not select the dictionary object (is '{CLIP_COLL}' hidden or excluded?)")
            return {"CANCELLED"}
        path = os.path.join(out_dir, dname + ".ycd.xml")
        if os.path.exists(path):
            os.remove(path)
        try:
            bpy.ops.sollumz.export_assets(directory=out_dir, limit_to_selected=True, target_formats={"NATIVE"}, direct_export=True)
        except RuntimeError as e:
            self.report({"ERROR"}, "Sollumz export failed: " + str(e).strip().splitlines()[-1])
            return {"CANCELLED"}
        if not os.path.exists(path):
            self.report({"ERROR"}, f"Sollumz reported no error but {os.path.basename(path)} was not written")
            return {"CANCELLED"}
        rep = yc.check_clip_dictionary(path, expected)
        if rep["problems"]:
            self.report({"ERROR"}, f"{os.path.basename(path)} written but the read-back failed: " + "; ".join(rep["problems"][:3]))
            return {"CANCELLED"}
        clips = ", ".join(f"{n} ({v['seconds']:.2f} s{', mover' if v['root_motion'] else ''})" for n, v in rep["clips"].items())
        self.report({"INFO"}, f"{os.path.basename(path)} ({os.path.getsize(path) / 1024:.0f} KB): {clips} | TaskPlayAnim dict "
                              f"'{dname}' | convert the .ycd.xml to .ycd with CodeWalker, then reconnect to the server")
        return {"FINISHED"}


classes = (MPR_OT_retarget, MPR_OT_export_clips)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
