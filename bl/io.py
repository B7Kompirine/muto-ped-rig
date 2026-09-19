"""Blender <-> numpy kopru: mesh, marker, armature, vertex grubu."""
import json
import os
import re
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


ANIMAL_DATA = os.path.join(DATA, "animals")                 # insan referanslari data/ kokunde; hayvanlar ayri (insan oylamasina karismaz)
ANIMAL_BLEND = os.path.join(ANIMAL_DATA, "animal_templates.blend")


def rig_type():
    s = getattr(bpy.context.scene, "mpr", None)
    return s.rig_type if s is not None else "mp_m"


def animal_ref_bbox(key):
    """Hayvan ped'inin kendi oyun mesh'inin sinir kutusu (ref npz; Add Markers baslangic olcegi)."""
    V = np.load(os.path.join(ANIMAL_DATA, f"ref_{key}.npz"))["V"]
    return V.min(0), V.max(0)


def template(key=None):
    key = key or rig_type()
    if key == "mp_m":
        return Skeleton.from_json(TEMPLATE_JSON)
    return Skeleton.from_json(os.path.join(ANIMAL_DATA, f"template_{key}.json"))


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
        o["mpr_p0"] = [float(x) for x in p]      # yerlestirme referansi: Update Linked kullanicinin neyi surukledigini bundan anlar


def read_marker_refs():
    """{anahtar: eklentinin son yazdigi konum (mpr_p0)}; bu ozellikten onceki dosyalarda yoktur."""
    coll = marker_collection(create=False)
    if coll is None:
        return {}
    return {o["mpr_key"]: np.array([float(x) for x in o["mpr_p0"]]) for o in coll.objects if "mpr_key" in o and "mpr_p0" in o}


def commit_markers(moved, current):
    """moved marker'larini tasi; tum marker'larin referansini simdiki konuma cek (ikinci basis bir sey degistirmesin). Gorunuse dokunmaz."""
    coll = marker_collection(create=False)
    if coll is None:
        return
    for o in coll.objects:
        k = o.get("mpr_key")
        p = moved.get(k, current.get(k))
        if p is None:
            continue
        if k in moved:
            o.location = [float(x) for x in p]
        o["mpr_p0"] = [float(x) for x in p]


def scale_markers(pivot, f):
    """Marker konumlarini pivot etrafinda f kat (mpr_p0 referansi da: bekleyen Update Linked kaybolmasin; bos nesne boyu degismez).
    -> tasinan marker sayisi"""
    coll = marker_collection(create=False)
    if coll is None:
        return 0
    c, n = np.asarray(pivot, float), 0
    for o in coll.objects:
        if "mpr_key" not in o:
            continue
        o.location = [float(x) for x in c + f * (np.array(o.location, float) - c)]
        if "mpr_p0" in o:
            o["mpr_p0"] = [float(x) for x in c + f * (np.array([float(v) for v in o["mpr_p0"]]) - c)]
        n += 1
    return n


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
def rig_template(arm):
    """Rig'in kuruldugu sablon anahtari (bu ozellikten onceki rig'ler insan)."""
    return arm.get("mpr_template", "mp_m")


def get_or_append_rig():
    """-> (armature, degistirilen eski sablon anahtari ya da None)."""
    key = rig_type()
    arm = bpy.data.objects.get(RIG_NAME)
    replaced = None
    if arm is not None and rig_template(arm) != key:
        # iskelet turu degisti: eski rig baska ped'in kemiklerini tasir -> kaldirilir, secilen sablon eklenir
        replaced, data = rig_template(arm), arm.data
        bpy.data.objects.remove(arm, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.armatures.remove(data)
        arm = None
    if arm is not None:
        if bpy.context.scene.objects.get(arm.name) is None:
            # baska sahnede olusmus: aktif sahneye bagla (olculdu: cok sahneli dosyada Fit Skeleton "ViewLayer does not contain MPR_Rig")
            bpy.context.scene.collection.objects.link(arm)
        return arm, None
    return append_template(key, RIG_NAME), replaced


def append_template(key, name):
    """Sablon iskeleti (vanilla GTA rest, Sollumz kemik tag'leri) sahneye `name` adiyla ekler."""
    blend, want = (TEMPLATE_BLEND, None) if key == "mp_m" else (ANIMAL_BLEND, "MPR_TEMPLATE_" + key)
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        dst.objects = [n for n in src.objects if (n == want if want else n.startswith("MPR_TEMPLATE_"))]
    if not dst.objects:
        raise RuntimeError(f"Skeleton template '{key}' not found in {os.path.basename(blend)}")
    arm = dst.objects[0]
    arm.name = name
    arm.data.name = name
    bpy.context.scene.collection.objects.link(arm)
    arm.matrix_world = Matrix.Identity(4)
    arm.show_in_front = True
    arm["mpr_template"] = key
    return arm


ANIM_RIG_NAME = "MPR_AnimRig"


def anim_rig():
    """Animasyon hedefi: vanilla insan sablon iskeleti GTA rest'inde. Karakterin MPR_Rig'ine action atanmaz (karakter temiz kalir); klip
    kemik basina yalniz donus tasir, her ped'de ayni oynar."""
    arm = bpy.data.objects.get(ANIM_RIG_NAME)
    if arm is None:
        return append_template("mp_m", ANIM_RIG_NAME)
    if bpy.context.scene.objects.get(arm.name) is None:
        bpy.context.scene.collection.objects.link(arm)
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
    # W DUNYA matrisleri (rig_world_matrices, Fit / GTA rest dunya uzayinda hesaplar), edit bone armature uzayinda. Rig nesnesi tasinmis
    # ya da olceklenmisse (karakter rig'den sonra olceklendi) dunya degeri yerel diye yazilinca donusum IKI KEZ uygulanir: export
    # sonrasi sahnede bas kemigi 1,49 -> 2,73 m (tools/t_scale_export_check.py obj_feet 1.5, 2026-09-13). Edit bone olcek tasimaz.
    L = np.linalg.inv(np.array(arm.matrix_world)) @ np.asarray(W, float)
    U, _, Vt = np.linalg.svd(L[:, :3, :3])
    L[:, :3, :3] = U @ Vt
    for i, n in enumerate(tpl.names):
        eb = ebs[raw[n]]
        eb.matrix = Matrix(L[i].tolist())
    with bpy.context.temp_override(**ov):
        bpy.ops.object.mode_set(mode="OBJECT")
    arm.select_set(False)
    for o in prev_sel:
        o.select_set(True)
    view_layer.objects.active = prev
    if arm.mode != "OBJECT":
        raise RuntimeError("MPR_Rig could not leave Edit Mode (the pose would not deform the mesh): switch to Object Mode and try again")


def foreign_armatures(meshes):
    """Secili mesh'lerin MPR_Rig disi iskeletleri: ebeveyn zinciri + ARMATURE modifier nesnesi (strip_foreign_rig ile ayni tanim)."""
    arms = []
    for o in meshes:
        p = o.parent
        while p is not None:
            if p.type == "ARMATURE" and p.name != RIG_NAME and p not in arms:
                arms.append(p)
            p = p.parent
        for m in o.modifiers:
            if m.type == "ARMATURE" and m.object is not None and m.object.name != RIG_NAME and m.object not in arms:
                arms.append(m.object)
    return arms


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


_FINGER_BONE = re.compile(r"^(SKEL|MH)_[LR]_Finger")


def detail_hidden_bone(name, fingers, face):
    """Kapali parmak / yuz secenegi bu kemigi gizler mi (SKEL_ / MH_ parmak, FB_ / FACIAL_ yuz)."""
    n = canon(name)
    return (not fingers and _FINGER_BONE.match(n) is not None) or (not face and n.startswith(("FB_", "FACIAL_")))


def apply_detail_visibility(s, arm=None):
    """Parmak / Yuz kapali -> o kemikler ve marker'lari yalniz GORUNUMDE gizlenir, iskelette KALIR: 1070 insan ped'in 1070'inde 30 parmak
    kemigi var ve klip yalniz var olan kemigi surer (atlas ped/iskelet.md §6); Fit kemik adi / tag / sayisini sabit tutar. Agirliklari
    Compute Weights el / kafa kemigine toplar. Donus: gizli kemik sayisi."""
    from ..core import markers as mk
    arm = arm or bpy.data.objects.get(RIG_NAME)
    hidden = 0
    if arm is not None and rig_template(arm) == "mp_m":
        for b in arm.data.bones:
            h = detail_hidden_bone(b.name, s.detail_fingers, s.detail_face)
            if b.hide != h:
                b.hide = h
            hidden += h
    coll = marker_collection(create=False)
    if coll is not None and s.rig_type == "mp_m":
        for o in coll.objects:
            k = o.get("mpr_key", "")
            h = (not s.detail_fingers and mk.is_finger_key(k)) or (not s.detail_face and mk.is_face_key(k))
            try:
                o.hide_set(h)                           # goz ikonu: nesne depsgraph'ta kalir, matrix_world okunmaya devam eder
            except RuntimeError:
                pass                                    # bu view layer'da degil
    return hidden


def rig_world_matrices(arm, tpl):
    """Armature'in su anki rest kemik matrisleri (dunya, sablon sirasinda) -> (B,4,4)."""
    M = np.array(arm.matrix_world)
    raw = bone_raw_names(arm, tpl)
    return np.array([M @ np.array(arm.data.bones[r].matrix_local) for r in raw])


def root_above_sole(rig_type, tpl):
    """Sablonun ayak tabani -> SKEL_ROOT yuksekligi: insan sablon koku - VANILLA_LO, hayvan kendi oyun mesh tabani."""
    root_z = float(tpl.pos[tpl.index["SKEL_ROOT"]][2])
    sole = float(VANILLA_LO[2]) if rig_type == "mp_m" else float(animal_ref_bbox(rig_type)[0][2])
    return root_z - sole


def store_fit(arm, fit, stage):
    arm["mpr_fit"] = json.dumps({"P_W": fit.P_W.tolist(), "G_W": fit.G_W.tolist(), "t": fit.t_local.tolist(),
                                 "scale": fit.scale.tolist(), "g": fit.g})
    arm["mpr_stage"] = stage


def load_fit(arm, tpl):
    from ..core.fit import FitResult
    d = json.loads(arm["mpr_fit"])
    return FitResult(tpl, np.array(d["t"]), np.array(d["P_W"]), np.array(d["G_W"]), np.array(d["scale"]), d["g"])


def current_fit(arm, tpl):
    """Kayitli fit GUNCEL rig kemiklerine uyarlanmis -> (fit, en buyuk sapma m). Degistiyse yeni fit saklanir (core.fit.refit_from_rest).
    Olculdu (2026-09-13, tools/t_edit_after_fit.py, hipster P): kayitli fit kullanilinca elle +5 cm tasinan dirsekte agirlik gecisi ESKI
    dirsekte kaldi (guncele gore -2,1 cm, taban +2,9) ve GTA rest ust kolu eski boya dondurdu (34,6 -> 29,6 cm); rig + mesh x1,5 olceklenince
    gecis bolgesi 19 -> 4 vertex (+43,9 cm), GTA rest iskeleti eski boyda (bas - taban 1,66 m, mesh 2,79 m)."""
    from ..core.fit import refit_from_rest
    prev = load_fit(arm, tpl)
    fit, dev = refit_from_rest(prev, rig_world_matrices(arm, tpl))
    if fit is not prev:
        store_fit(arm, fit, arm.get("mpr_stage", "P"))
    return fit, dev


def skel_mesh_ratio(arm, tpl, objs):
    """SKEL kemik yuksekligi (kok ve kuyruk haric) / mesh yuksekligi, dunya uzayinda. Weights'te saklanir (arm['mpr_skel_ratio']); sonra
    degismesi rig ile mesh'in AYRI olceklendigini gosterir. Iskelet mesh icinde kucuk kalinca kutu disi kontrolu yakalamaz (x1,5 mesh + eski
    iskelet: hicbir kemik disarida degil)."""
    V, _, _ = meshes_to_numpy(objs)
    W = rig_world_matrices(arm, tpl)
    z = [W[i, 2, 3] for i, n in enumerate(tpl.names) if n.startswith("SKEL_") and n != "SKEL_ROOT" and not n.startswith("SKEL_Tail")]
    h = float(np.ptp(V[:, 2]))
    return float((max(z) - min(z)) / h) if h > 1e-6 else None


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
