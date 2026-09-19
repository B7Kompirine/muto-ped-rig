"""Yabanci iskeletli animasyon -> GTA ped rig'i (Blender tarafi). Yontem atlas scripts/blender_retarget_gta.py ile BIREBIR; olcumler orada:
  * "align" ofseti: kaynak kemigin rest YONU hedefin rest yonune dondurulur, sonra rest ofseti (T-pose / A-pose farki 57° kapanir, roll
    temizlenir; gidis-donus 0,000°). El iki eksenli (core/animmap.HAND_FRAME).
  * Sollumz GTA rig'inde kemikler 0,05 m ve yonsuz: anatomik yon = kendi basindan GERCEK cocugunun basina (yardimci kemik elenir).
  * dunya uzayi (FBX 90° X + 0,01 olcek), cikti yaw 180 (oyunda calisan klipler kare 0'da +Y'ye bakar), 30 fps.
  * mover: kalcanin yatay yolu SKEL_ROOT mover track'ine, kemik yerinde; olcek orani matrix_world ile.
"""
import math
import bpy
from mathutils import Matrix, Vector

from ..core import animmap as am

FPS = 30
OUT_YAW_DEG = 180.0
SRC_YAW_DEG = 0.0


def out_rot():
    return Matrix.Rotation(math.radians(OUT_YAW_DEG), 3, "Z")


def src_world_rot(src):
    return Matrix.Rotation(math.radians(SRC_YAW_DEG), 3, "Z") @ src.matrix_world.to_3x3().normalized()


def rest3(obj, name):
    return obj.data.bones[name].matrix_local.to_3x3()


def bone_dir(obj, name):
    """Anatomik rest yonu: helper / twist elenmis en uzak cocuga; yoksa ebeveynden gelen yon; o da yoksa None (align uygulanmaz)."""
    bones = obj.data.bones
    is_gta = "SKEL_ROOT" in bones
    helpers = ("MH_", "RB_", "SM_", "EO_", "SPR_", "FB_", "IK_", "PH_", "FACIAL_") if is_gta else ("ik_",)
    skips = () if is_gta else ("_twist_",)
    b = bones[name]
    kids = [c for c in b.children if not c.name.startswith(helpers) and not any(s in c.name for s in skips)]
    if kids:
        c = max(kids, key=lambda k: (k.head_local - b.head_local).length)
        d = c.head_local - b.head_local
        if d.length > 1e-6:
            return d.normalized()
    if b.parent:
        d = b.head_local - b.parent.head_local
        if d.length > 1e-6:
            return d.normalized()
    return None


def _head_world(obj, R, name):
    return R @ obj.data.bones[name].head_local


def hand_frame(obj, R, hand, idx, pky):
    d = bone_dir(obj, hand)
    if d is None:
        return None
    d = (R @ d).normalized()
    h = _head_world(obj, R, hand)
    n = (_head_world(obj, R, idx) - h).cross(_head_world(obj, R, pky) - h)
    if n.length < 1e-9:
        return None
    n = n - d * n.dot(d)
    if n.length < 1e-9:
        return None
    return d, n.normalized()


def frame_rot(src_f, tgt_f):
    ds, ns = src_f
    dt, nt = tgt_f
    Bs = Matrix((ds, ns, ds.cross(ns))).transposed()
    Bt = Matrix((dt, nt, dt.cross(nt))).transposed()
    return Bt @ Bs.inverted()


def compute_offsets(gta, src, pairs, mode="align"):
    """-> (ofsetler {GTA: 3x3}, align atlanan kemikler). Q_off = (kaynak referans yonelimi)^-1 @ (hedef rest yonelimi), dunya uzayinda."""
    offs, skipped = {}, []
    Rs = src_world_rot(src)
    Rg = gta.matrix_world.to_3x3().normalized()
    for g, s in pairs.items():
        tgt = Rg @ rest3(gta, g)
        if mode == "pose":
            ref = Rs @ src.pose.bones[s].matrix.to_3x3()
        else:
            ref = Rs @ rest3(src, s)
            if mode == "align":
                ds, dt = bone_dir(src, s), bone_dir(gta, g)
                if ds is not None:
                    ds = (Rs @ ds).normalized()
                if dt is not None:
                    dt = (Rg @ dt).normalized()
                hf = None
                if g in am.HAND_FRAME and all(k in pairs for k in am.HAND_FRAME[g]):
                    gi, gp = am.HAND_FRAME[g]
                    fs_ = hand_frame(src, Rs, s, pairs[gi], pairs[gp])
                    ft_ = hand_frame(gta, Rg, g, gi, gp)
                    if fs_ and ft_:
                        hf = frame_rot(fs_, ft_)
                if hf is not None:
                    ref = hf @ ref
                elif ds is None or dt is None:
                    skipped.append(g)
                else:
                    dot = max(-1.0, min(1.0, ds.dot(dt)))
                    if dot < 0.999999:
                        axis = ds.cross(dt)
                        if axis.length > 1e-8:
                            ref = Matrix.Rotation(math.acos(dot), 3, axis.normalized()) @ ref
        offs[g] = ref.inverted() @ tgt
    return offs, skipped


def action_fcurves(act):
    """Blender 4.4+ katmanli action (layers / strips / channelbags); eski surumde act.fcurves."""
    out = []
    try:
        for lay in act.layers:
            for st in lay.strips:
                for cb in st.channelbags:
                    out.extend(cb.fcurves)
    except AttributeError:
        out = list(act.fcurves)
    return out


def static_fingers(src, pairs, eps=1e-4):
    """Kaynakta hic oynamayan parmak eslemeleri (kanal yok ya da tum anahtarlar ayni). Kimodo gibi govde modelleri ele tek sabit poz yazar;
    tasinirsa GTA'nin el pozu ezilir, eller yassi / acik durur (olculdu 2026-09-09, oyunda gorunur)."""
    act = src.animation_data.action if src.animation_data else None
    if act is None:
        return []
    curves = action_fcurves(act)
    out = []
    for g, s in pairs.items():
        if "Finger" not in g:
            continue
        tag = f'"{s}"'
        moving = False
        for fc in curves:
            if tag in fc.data_path and "rotation" in fc.data_path:
                v = [kp.co[1] for kp in fc.keyframe_points]
                if v and max(v) - min(v) > eps:
                    moving = True
                    break
        if not moving:
            out.append(g)
    return out


def frame_count(f0, f1, time_scale=1.0):
    """Kaynak [f0, f1] araligindan cikan 30 fps hedef kare sayisi. time_scale = kaynak fps / 30."""
    return int((f1 - f0) / time_scale + 1e-6) + 1


def _frame_set(sc, t):
    i = math.floor(t + 1e-9)
    sc.frame_set(i, subframe=t - i)


def bake(gta, src, pairs, offs, f0, f1, action_name, time_scale=1.0, out_f0=None):
    """Delta transfer + quaternion anahtari. Kok -> yaprak sirasi zorunlu (ebeveyn ayarlanmadan cocugun dunya matrisi yanlis okunur).
    time_scale = kaynak fps / 30: hedef kare f0 + k, kaynak zamani f0 + k * time_scale (24 fps kaynak kare kare alinirsa klip %25 hizlanir,
    atlas ped/retarget.md §4). 1.0: kare kare, atlas betigiyle ayni yol. out_f0: hedefin ilk karesi (None = f0, atlas gibi; panel 0 verir:
    Sollumz klip zamanini start_frame / sure ile hesaplar, 0'dan baslamayan action'da klip kayar)."""
    for pb in gta.pose.bones:
        pb.rotation_mode = "QUATERNION"
    gta.animation_data_create()
    act = bpy.data.actions.new(action_name)
    gta.animation_data.action = act
    try:
        gta.animation_data.action_slot = act.slots[0]      # Blender 4.4+: atama yetmez, slot da baglanmali
    except Exception:
        pass
    order = sorted(pairs, key=lambda n: len(gta.data.bones[n].parent_recursive))
    sc = bpy.context.scene
    Rs = src_world_rot(src)
    Rg_inv = gta.matrix_world.to_3x3().normalized().inverted()
    Ro = out_rot()
    base = f0 if out_f0 is None else out_f0
    for k in range(frame_count(f0, f1, time_scale)):
        f = base + k
        _frame_set(sc, f0 + k * time_scale)
        want = {g: Rg_inv @ (Ro @ Rs @ src.pose.bones[s].matrix.to_3x3() @ offs[g]) for g, s in pairs.items()}
        for g in order:
            pb = gta.pose.bones[g]
            loc = pb.matrix.translation.copy()
            m = want[g].to_4x4()
            m.translation = loc
            pb.matrix = m
            bpy.context.view_layer.update()
        for g in order:
            gta.pose.bones[g].keyframe_insert("rotation_quaternion", frame=f)
    try:
        gta.animation_data.action_slot = act.slots[0]
    except Exception:
        pass
    return act


def transfer_mover(gta, src, pairs, f0, f1, time_scale=1.0, write_mover=True, out_f0=None):
    """Kaynak kalcanin YATAY yolu -> SKEL_ROOT mover track'i, kemik yerinde (dikey kalir). write_mover=False: yalniz dikey (yerinde klip,
    yol atilir). Donus: (kare sayisi, None) ya da (None, sebep metni)."""
    src_hips = pairs.get("SKEL_ROOT")
    if not src_hips:
        return None, "hips not mapped"
    root = gta.pose.bones.get("SKEL_ROOT")
    if root is None or (write_mover and not hasattr(root, "animation_tracks_mover_location")):
        return None, "Sollumz mover track property not found"
    sc = bpy.context.scene
    Rz = out_rot() @ Matrix.Rotation(math.radians(SRC_YAW_DEG), 3, "Z")
    Rg_inv = gta.matrix_world.to_3x3().normalized().inverted()

    def hips_world():
        return Rz @ (src.matrix_world @ src.pose.bones[src_hips].matrix).translation

    sc.frame_set(f0)
    base = hips_world().copy()
    n = 0
    fbase = f0 if out_f0 is None else out_f0
    for k in range(frame_count(f0, f1, time_scale)):
        f = fbase + k
        _frame_set(sc, f0 + k * time_scale)
        d = Rg_inv @ (hips_world() - base)
        if write_mover:
            root.animation_tracks_mover_location = (d.x, d.y, 1.0)
            root.keyframe_insert("animation_tracks_mover_location", frame=f)
        root.location = (0.0, 0.0, d.z)
        root.keyframe_insert("location", frame=f)
        n += 1
    return n, None


def validate(gta, act, f0, f1):
    """Yasak kanallar, dongu uyusmazligi (ilk / son kare), ayak anim-uzayi suruklenmesi."""
    sc = bpy.context.scene
    rep = dict(fps=sc.render.fps, frames=(f0, f1), duration_s=round((f1 - f0 + 1) / max(sc.render.fps, 1), 3))
    rep["forbidden"] = am.forbidden_channels([fc.data_path for fc in action_fcurves(act)])

    def pose_of(f):
        sc.frame_set(f)
        return {b.name: gta.pose.bones[b.name].matrix.to_3x3().to_quaternion().copy() for b in gta.data.bones if b.name.startswith("SKEL_")}

    a0, a1 = pose_of(f0), pose_of(f1)
    worst, wb = 0.0, None
    for k in a0:
        d = math.degrees(a0[k].rotation_difference(a1[k]).angle)
        d = 360 - d if d > 180 else d
        if d > worst:
            worst, wb = d, k
    rep["loop_mismatch_deg"] = (round(worst, 2), wb)

    def foot_drift(name):
        sc.frame_set(f0)
        p0 = (gta.matrix_world @ gta.pose.bones[name].matrix).translation.copy()
        sc.frame_set(f1)
        p1 = (gta.matrix_world @ gta.pose.bones[name].matrix).translation.copy()
        return round(Vector((p1.x - p0.x, p1.y - p0.y, 0.0)).length, 4)

    rep["foot_drift_m"] = {"L": foot_drift("SKEL_L_Foot"), "R": foot_drift("SKEL_R_Foot")}
    return rep


def upper_arm_drop_deg(obj, upper, fore):
    """Ust kolun yataydan asagi acisi (rest); GTA ~57 (A-pose), Mixamo T-pose ~0."""
    try:
        a, b = obj.data.bones[upper], obj.data.bones[fore]
    except KeyError:
        return None
    d = (b.matrix_local.translation - a.matrix_local.translation).normalized()
    return round(math.degrees(math.asin(max(-1.0, min(1.0, -d.z)))), 1)
