"""Blender <-> numpy kopru: mesh, marker, armature, vertex grubu."""
import json
import os
import bpy
import numpy as np
from mathutils import Matrix

from ..core.skeleton import Skeleton, canon

ADDON_DIR = os.path.dirname(os.path.dirname(__file__))
DATA = os.path.join(ADDON_DIR, "data")
TEMPLATE_BLEND = os.path.join(DATA, "freemode_template.blend")
TEMPLATE_JSON = os.path.join(DATA, "template_mp_m.json")
MARKER_COLL = "MPR_Markers"
RIG_NAME = "MPR_Rig"
# vanilla erkek referans govdesinin sinir kutusu (ref_mp_m, olculdu)
VANILLA_LO = (-0.593, -0.204, -1.002)
VANILLA_HI = (0.593, 0.175, 0.816)


def template():
    return Skeleton.from_json(TEMPLATE_JSON)


# --- mesh ---------------------------------------------------------------------
def selected_meshes(context):
    return [o for o in context.selected_objects if o.type == "MESH" and not o.name.startswith("MPR_")]


def meshes_to_numpy(objs):
    Vs, Fs, ranges, off = [], [], [], 0
    for o in objs:
        me = o.data
        me.calc_loop_triangles()
        n = len(me.vertices)
        co = np.empty(n * 3)
        me.vertices.foreach_get("co", co)
        M = np.array(o.matrix_world)
        Vs.append(co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3])
        tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
        me.loop_triangles.foreach_get("vertices", tri)
        Fs.append(tri.reshape(-1, 3) + off)
        ranges.append((o, off, off + n))
        off += n
    return np.concatenate(Vs), np.concatenate(Fs), ranges


def set_world_verts(ranges, V):
    for o, a, b in ranges:
        inv = np.linalg.inv(np.array(o.matrix_world))
        loc = V[a:b] @ inv[:3, :3].T + inv[:3, 3]
        o.data.vertices.foreach_set("co", loc.astype(np.float32).ravel())
        o.data.update()


def world_bbox(objs):
    V, _, _ = meshes_to_numpy(objs)
    return V.min(0), V.max(0)


# --- marker -------------------------------------------------------------------
def marker_collection(create=True):
    c = bpy.data.collections.get(MARKER_COLL)
    if c is None and create:
        c = bpy.data.collections.new(MARKER_COLL)
    if c is not None and create and bpy.context.scene.collection.children.get(c.name) is None:
        # baska sahnede olusmus olabilir -> aktif sahneye de bagla (olculdu: cok sahneli dosyada Auto Markers'in marker'lari gorunmuyordu)
        bpy.context.scene.collection.children.link(c)
    return c


def set_markers(positions, size):
    coll = marker_collection()
    for key, p in positions.items():
        name = "MPR_" + key
        o = bpy.data.objects.get(name)
        if o is None:
            o = bpy.data.objects.new(name, None)
            coll.objects.link(o)
        o.empty_display_type = "SPHERE"
        o.empty_display_size = size
        o.show_in_front = True
        o["mpr_key"] = key
        o.location = [float(x) for x in p]


def remove_markers(keys):
    """Anahtari keys icinde olan marker nesnelerini sil (Auto Markers: kapatilan secenekten kalan eski hedefler). -> silinen sayi"""
    coll = marker_collection(create=False)
    if coll is None:
        return 0
    keys, n = set(keys), 0
    for o in list(coll.objects):
        if o.get("mpr_key") in keys:
            bpy.data.objects.remove(o, do_unlink=True)
            n += 1
    return n


def read_markers():
    coll = marker_collection(create=False)
    if coll is None:
        return {}
    return {o["mpr_key"]: np.array(o.matrix_world.translation) for o in coll.objects if "mpr_key" in o}


# --- armature -----------------------------------------------------------------
def get_or_append_rig():
    arm = bpy.data.objects.get(RIG_NAME)
    if arm is not None:
        if bpy.context.scene.objects.get(arm.name) is None:
            # baska sahnede olusmus: aktif sahneye bagla (olculdu: cok sahneli dosyada Fit Skeleton "ViewLayer does not contain MPR_Rig")
            bpy.context.scene.collection.objects.link(arm)
        return arm
    with bpy.data.libraries.load(TEMPLATE_BLEND, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if n.startswith("MPR_TEMPLATE_")]
    arm = dst.objects[0]
    arm.name = RIG_NAME
    arm.data.name = RIG_NAME
    bpy.context.scene.collection.objects.link(arm)
    arm.matrix_world = Matrix.Identity(4)
    arm.show_in_front = True
    return arm


def set_rest(arm, W, tpl):
    """Edit bone matrislerini yaz (bas konumu + yon + roll; boy korunur). Tag/bayrak Bone'da, dokunulmaz."""
    view_layer = bpy.context.view_layer
    prev = view_layer.objects.active
    prev_sel = list(bpy.context.selected_objects)       # secim geri yuklenir: sonraki operator mesh secimine bakar
    for o in prev_sel:
        o.select_set(False)
    view_layer.objects.active = arm
    arm.select_set(True)
    # mode_set cagiranin baglamindaki objeye uygulanir: disaridan temp_override(object=mesh) ile cagrilinca iskelet EDIT'te kaldi,
    # poz mesh'i hic deforme etmedi (olculdu 2026-09-12, MCP'den mpr.fit) -> baglam iskelete sabitlenir, cikis modu geri okunur.
    ov = dict(active_object=arm, object=arm, selected_objects=[arm], selected_editable_objects=[arm])
    with bpy.context.temp_override(**ov):
        bpy.ops.object.mode_set(mode="EDIT")
    ebs = arm.data.edit_bones
    raw = {canon(b.name): b.name for b in ebs}
    for i, n in enumerate(tpl.names):
        eb = ebs[raw[n]]
        eb.matrix = Matrix(W[i].tolist())
    with bpy.context.temp_override(**ov):
        bpy.ops.object.mode_set(mode="OBJECT")
    arm.select_set(False)
    for o in prev_sel:
        o.select_set(True)
    view_layer.objects.active = prev
    if arm.mode != "OBJECT":
        raise RuntimeError("MPR_Rig could not leave Edit Mode (the pose would not deform the mesh): switch to Object Mode and try again")


def strip_foreign_rig(meshes):
    """Hazir iskeletli modeli (Mixamo/Unreal/Sketchfab) iskeletsiz hale getir: parent (dunya konumu korunur), MPR_Rig disi ARMATURE
    modifier'lari, GTA sablonunda olmayan vertex gruplari, shape key'ler. Bos kalan yabanci iskelet objeleri silinir. Donus: sayac.
    Neden: bind ilk ARMATURE modifier'ini yeniden kullanir, eski gruplar ve parent kalir (Winter Soldier UE ripi, 2026-09-12 elle
    temizlendi); shape key varsa GTA rest vertices.co'yu yazar ama degerlendirilmis mesh basis key'den gelir (tools/t_strip_rig.py)."""
    names = set(template().names)
    cnt = dict(parent=0, modifier=0, grup=0, shape_key=0, iskelet_silindi=0, uc_kemik_empty=0)
    arms = set()
    for o in meshes:
        if o.parent is not None and o.parent.name != RIG_NAME:
            p = o.parent
            while p is not None:
                if p.type == "ARMATURE":
                    arms.add(p)
                p = p.parent
            mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = mw
            cnt["parent"] += 1
        for m in [m for m in o.modifiers if m.type == "ARMATURE" and (m.object is None or m.object.name != RIG_NAME)]:
            if m.object is not None:
                arms.add(m.object)
            o.modifiers.remove(m)
            cnt["modifier"] += 1
        for vg in [vg for vg in o.vertex_groups if canon(vg.name) not in names]:
            o.vertex_groups.remove(vg)
            cnt["grup"] += 1
        if o.data.shape_keys is not None:
            cnt["shape_key"] += len(o.data.shape_keys.key_blocks)
            o.shape_key_clear()
    bpy.context.view_layer.update()
    def descends(o, anc):
        p = o.parent
        while p is not None:
            if p == anc:
                return True
            p = p.parent
        return False

    for a in arms:
        if a.name == RIG_NAME:
            continue
        # glTF import'u uc kemikleri (HeadTop_End, parmak/ayak ucu) kemige bagli bos EMPTY olarak birakir (Soldier: 16 adet, iskelet
        # silinmiyordu) -> yalniz EMPTY torunlari varsa onlarla birlikte silinir; mesh/prop torunu ya da modifier kullanicisi varsa kalir
        desc = [x for x in bpy.data.objects if descends(x, a)]
        if any(x.type != "EMPTY" for x in desc) or \
                any(any(m.type == "ARMATURE" and m.object == a for m in x.modifiers) for x in bpy.data.objects):
            continue
        for x in desc:
            bpy.data.objects.remove(x, do_unlink=True)
        data = a.data
        bpy.data.objects.remove(a, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.armatures.remove(data)
        cnt["iskelet_silindi"] += 1
        cnt["uc_kemik_empty"] += len(desc)
    bpy.context.view_layer.update()
    return cnt


def bone_raw_names(arm, tpl):
    raw = {canon(b.name): b.name for b in arm.data.bones}
    return [raw[n] for n in tpl.names]


def store_fit(arm, fit, stage):
    arm["mpr_fit"] = json.dumps({"P_W": fit.P_W.tolist(), "G_W": fit.G_W.tolist(), "t": fit.t_local.tolist(),
                                 "scale": fit.scale.tolist(), "g": fit.g})
    arm["mpr_stage"] = stage


def load_fit(arm, tpl):
    from ..core.fit import FitResult
    d = json.loads(arm["mpr_fit"])
    return FitResult(tpl, np.array(d["t"]), np.array(d["P_W"]), np.array(d["G_W"]), np.array(d["scale"]), d["g"])


# --- vertex gruplari -----------------------------------------------------------
def write_weights(ranges, raw_names, idx, val):
    names_set = set(raw_names)
    for o, a, b in ranges:
        for vg in list(o.vertex_groups):
            if vg.name in names_set:
                o.vertex_groups.remove(vg)
        I, Wv = idx[a:b], val[a:b]
        for j in np.unique(I[Wv > 0]):
            vg = o.vertex_groups.new(name=raw_names[j])
            rows, cols = np.nonzero((I == j) & (Wv > 0))
            ws = Wv[rows, cols]
            for w in np.unique(ws):
                vg.add(rows[ws == w].tolist(), float(w), "REPLACE")


def read_weights(ranges, raw_names, k=4):
    col = {n: j for j, n in enumerate(raw_names)}
    N = ranges[-1][2]
    idx = np.zeros((N, k), np.int64)
    val = np.zeros((N, k))
    for o, a, b in ranges:
        gmap = {g.index: col.get(g.name, -1) for g in o.vertex_groups}
        for v in o.data.vertices:
            ws = sorted(((g.weight, gmap[g.group]) for g in v.groups if gmap.get(g.group, -1) >= 0 and g.weight > 0),
                        reverse=True)[:k]
            for t, (w, j) in enumerate(ws):
                idx[a + v.index, t] = j
                val[a + v.index, t] = w
    s = val.sum(1, keepdims=True)
    return idx, np.where(s > 0, val / np.maximum(s, 1e-12), 0)


def bind(ranges, arm):
    for o, a, b in ranges:
        mod = next((m for m in o.modifiers if m.type == "ARMATURE"), None)
        if mod is None:
            mod = o.modifiers.new("MPR_Armature", "ARMATURE")
        mod.object = arm
