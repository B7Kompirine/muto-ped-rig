"""Sollumz hiyerarsisi + disa aktarim + test resource.

Olculmus yapi (vanilla mp_m_freemode_01 import'u, Sollumz 2.9, 2026-09-11):
  .yft : fragment ARMATURE -> tek DRAWABLE cocuk -> model. Collision yoksa Sollumz Physics YAZMAZ
         (yftexport: "Physics data doesn't do anything if no collisions are present and will cause crashes").
  .ydd : sozluk ARMATURE (dis iskelet) -> EMPTY cizimler (head_000_r, uppr_000_u, lowr_000_u) -> modeller.
         find_ydd_armature: sozluk armature ise deri iskeleti odur; EMPTY cizime .ydd'de Skeleton yazilmaz.
  model: sollumz_drawable_model, sz_lods.high.mesh dolu, UVMap 0/1, Color 1/2 (CORNER, BYTE_COLOR), ped.sps.
"""
import os
import bpy
import bmesh
import numpy as np

from . import io
from ..core import components as comp
from ..core.skeleton import canon

COLL = "MPR_Sollumz"

# GTA ped doku sozlesmesi — olculdu (2026-09-11, vanilla a_m_y_beach_01 geri okuma):
#  .ydd'de gomulu doku YOK; orneklayicilar kural adli: <bilesen>_diff_<cizim>_<harf>_<irk>, <bilesen>_normal_<cizim>,
#  <bilesen>_spec_<cizim>; dokular <ped>.ytd'de (41 doku: diffuse DXT1 512, spec DXT5 256). Oyun adi .ymt'den kurar:
#  cizim 000 doku a -> texId 0 (uni). Vanilla beach .ymt'de head texId 1 (whi) idi; /mpraddon'da SetPedDefaultComponentVariation
#  native istisnasi verdi (F8, 2026-09-11) -> calisan addon ped (sauron) gibi hepsi uni (tek varyasyonlu .ymt ile ayni).
#  Duz normal/spec = vanilla head/uppr/lowr _000 dokularinin kanal ortalamasi (Pillow): normal (0.50, 0.49-0.50, 0.99-1.0);
#  spec R .31-.57 G .14-.20 B .41-1.0 A .12-.29 -> ortalamalarin ortalamasi.
RACE = {"head": "uni", "uppr": "uni", "lowr": "uni"}
FLAT_NORMAL = (0.5, 0.5, 1.0, 1.0)
FLAT_SPEC = (0.40, 0.17, 0.68, 0.22)
NEUTRAL_DIFF = (0.5, 0.5, 0.5, 1.0)
# renk dokusu kenar siniri. Diffuse DXT1/DXT5 yazildigi icin 2048 (DXT5 mip'li ~5.6 MB ham); eskiden A8R8G8B8 icin 1024'tu.
# Tetik: kullanicinin sauron ped'i 4096 DXT5 -> kaynak DDS oldugu gibi kopyalaniyor ve uc cizime ayri yaziliyordu: .ytd 16 MB (2026-09-12).
TEX_MAX = 2048


# Sahne TXD'si (Scene.sz_txds) ve export_ytds_include ilk Sollumz 2.9.0'da; create_shader v2.3.0-v2.9.0 hep
# ydr/shader_materials.py'de (GitHub etiketleri tarandi, 2026-09-12).
SOLLUMZ_MIN = (2, 9, 0)


def _version_text(version):
    return ".".join(str(v) for v in version) if version else "?"


def sollumz_package():
    """Etkin Sollumz'un paket adi ve surumu. Ad kurulum yoluna gore degisir: eski addon 'Sollumz' (klasor adi; GitHub kaynak
    zip'inde 'Sollumz-main'), extension 'bl_ext.<depo>.sollumz' (user_default, blender_org, ozel depo). Sabit iki adla aramak
    uzak kullanicida (Blender 5.1 + Sollumz 2.9.0) 'Sollumz not found' verdi -> etkin eklentiler arasinda son ad parcasiyla aranir."""
    import sys
    import addon_utils
    for name in bpy.context.preferences.addons.keys():
        last = name.rsplit(".", 1)[-1].lower()
        if last == "sollumz" or last.startswith(("sollumz-", "sollumz_")):
            module = sys.modules.get(name)
            try:
                version = tuple(addon_utils.module_bl_info(module).get("version", ())) if module else ()
            except Exception:
                version = ()
            return name, version
    return None, ()


def _create_shader(filename):
    import importlib
    name, version = sollumz_package()
    if name is None:
        raise RuntimeError("Sollumz is not enabled: Edit > Preferences > Add-ons / Get Extensions > enable Sollumz "
                           f"{_version_text(SOLLUMZ_MIN)}+")
    if version and version < SOLLUMZ_MIN:
        raise RuntimeError(f"Sollumz {_version_text(version)} is too old: Muto Ped Rig needs Sollumz {_version_text(SOLLUMZ_MIN)}+")
    try:
        create = importlib.import_module(name + ".ydr.shader_materials").create_shader
    except (ImportError, AttributeError) as e:
        raise RuntimeError(f"Sollumz found ({name} {_version_text(version)}) but create_shader could not be loaded: {e}") from e
    return create(filename)


def _base_color_image(mat):
    if mat is None or not mat.use_nodes:
        return None
    for n in mat.node_tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.name == "DiffuseSampler" and n.image:
            return n.image
    for n in mat.node_tree.nodes:
        if n.bl_idname == "ShaderNodeBsdfPrincipled":
            s = n.inputs.get("Base Color")
            if s and s.is_linked:
                src = s.links[0].from_node
                if getattr(src, "image", None):
                    return src.image
    for n in mat.node_tree.nodes:
        if n.bl_idname == "ShaderNodeTexImage" and n.image:
            return n.image
    return None


def _safe_tex_name(name):
    import re
    base = os.path.splitext(name)[0].lower()
    return (re.sub(r"[^a-z0-9_]", "_", base) or "tex")[:48]


def embed_as_dds(node, tex_dir):
    """Doku dugumunu gomulu DDS yap. Sollumz PNG cevirmez: gomulu doku ya 'DDS ' paketli veri ya diskte .dds olmali,
    doku adi dosya adindan turer (ytdexport.extract_texture_dds_data_source, get_texture_name)."""
    from ..core import dds
    img = node.image
    if img is None:
        return None
    fp = bpy.path.abspath(img.filepath) if img.filepath else ""
    if fp.lower().endswith(".dds") and os.path.isfile(fp):
        node.texture_properties.embedded = True
        return fp
    if img.packed_file is not None and bytes(img.packed_file.data[:4]) == b"DDS ":
        node.texture_properties.embedded = True
        return img.name
    os.makedirs(tex_dir, exist_ok=True)
    path = os.path.join(tex_dir, _safe_tex_name(img.name) + ".dds")
    dds.blender_image_to_dds(img, path)
    new = bpy.data.images.load(path, check_existing=True)
    new.colorspace_settings.name = img.colorspace_settings.name
    node.image = new
    node.texture_properties.embedded = True
    return path


PLACEHOLDER_TEX = "givemechecker"


def fill_empty_samplers(mat, skip=("DiffuseSampler", "TextureSamplerDiffPal")):
    """Bos doku ornekleyicilerine Rockstar yer tutucusu (givemechecker) — calisan addon ped (sauron) boyle.
    Olculdu (2026-09-12, tools/t_ped_probe.py): SetPedDefaultComponentVariation istisnasi veren muto_winter / muto_test_ped'de
    VolumeSampler BOS, hatasiz muto_sauron'da 'givemechecker'. TextureSamplerDiffPal sauron'da da bos (dokunulmaz)."""
    if mat is None or not mat.use_nodes:
        return 0
    n = 0
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeTexImage" and node.image is None and node.name not in skip:
            # Sollumz doku adini DOSYA YOLUNDAN alir (ytd/properties.get_texture_name: basename(image.filepath)) -> diskte olmayan
            # images.new() adi bos yazilir (olculdu: export'ta VolumeSampler yine None). Eklentiyle gelen 4x4 DDS yuklenir.
            node.image = bpy.data.images.load(os.path.join(_DATA, PLACEHOLDER_TEX + ".dds"), check_existing=True)
            if hasattr(node, "texture_properties"):
                node.texture_properties.embedded = False
            n += 1
    return n


def ped_material_for(src_mat, cache, tex_dir=None):
    """Sollumz ped shader'i olmayan materyali ped.sps'e cevir (renk dokusu DDS olarak gomulur)."""
    fname = src_mat.shader_properties.filename if src_mat is not None and \
        getattr(src_mat, "sollum_type", "") == "sollumz_material_shader" else ""
    if fname.startswith("ped") and "palette" not in fname:
        fill_empty_samplers(src_mat)
        return src_mat  # ped ailesi (ped, ped_default, ped_alpha...) zaten gecerli
    # Palet golgelendiricisi (ped_palette...) ped.sps'e cevrilir, diffuse korunur: tek varyasyonlu .ymt'de palet verisi yok.
    # Olculdu (2026-09-12): ped_palette tasiyan addon test ped'inde F8 "SetPedDefaultComponentVariation" native istisnasi;
    # ayni .ymt ve ayni client.lua ile yalniz ped.sps tasiyan sauron sorunsuz.
    key = src_mat.name if src_mat else "__none__"
    if key in cache:
        return cache[key]
    mat = _create_shader("ped.sps")
    mat.name = f"MPR_ped_{key}"[:60]
    img = _base_color_image(src_mat)
    node = mat.node_tree.nodes.get("DiffuseSampler")
    if img is not None and node is not None:
        node.image = img
        if tex_dir:
            embed_as_dds(node, tex_dir)
    fill_empty_samplers(mat)
    cache[key] = mat
    return mat


# Kose renkleri (Sollumz adla secer): "Color 1" -> Colour0 aydinlatma, "Color 2" -> Colour1 ruzgar (RGB) + ter/islaklik (alfa).
# Olculdu (2026-09-12, tools/t_vcolor_probe.py): vanilla a_m_y_beach_01 5 cizimde Colour0 B 0 / A 255 (R ~245, G ~120), Colour1 hep 0;
# ikisini beyaz (255,255,255,255) acan eski kod -> muto_winter oyunda siddetli titreme, Colour1 0 olan sauron/test ped titremiyor.
# Sollumz docs (basic-clothes-editing): Color 1 FF8000, Color 2 #000 alfa 0.
# Olculdu (2026-09-13, tools/t_ped_shader_flow.py, kullanici raporu "ped / ped_default shader ekleyince"): Sollumz 'Create Shader
# Material' mevcut kose rengini "Color 1"e YENIDEN ADLANDIRIR (WS: Unreal PSKVTXCOL_0) ve eksik "Color 2"yi DOLDURMADAN acar; Blender yeni
# BYTE_COLOR katmanini BEYAZ (1,1,1,1) baslatir -> eski export katmani korudugu icin head/uppr/lowr "Color 2" %100 beyaz = oyunda
# titreme. Tek duze (her kosede ayni) sifir olmayan "Color 2" boyanmamis varsayilandir -> 0'a cekilir; boyanmis (degisken) korunur.
LAYER_DEFAULT_SRGB = {"Color 1": (1.0, 128 / 255, 0.0, 1.0), "Color 2": (0.0, 0.0, 0.0, 0.0)}


def _uniform_srgb(ca):
    """Katmanin tum koseleri ayni sRGB degerdeyse o deger (4'lu), degilse ya da katman yoksa None."""
    if ca is None or len(ca.data) == 0:
        return None
    buf = np.empty(len(ca.data) * 4, dtype=np.float32)
    ca.data.foreach_get("color_srgb", buf)
    c = buf.reshape(-1, 4)
    return tuple(float(v) for v in c[0]) if np.all(c == c[0]) else None


def wind_layer_uniform(me):
    """"Color 2" tek duze ve sifir disi mi (boyanmamis varsayilan; export 0'a ceker -> Validate sorun saymaz)."""
    u = _uniform_srgb(me.color_attributes.get("Color 2"))
    return u is not None and any(v > 0.5 / 255 for v in u)


def prepare_mesh_layers(me):
    """Ped shader'inin bekledigi katmanlar. Donus: mesh'te hic UV yok muydu (bos UV acildi -> doku tek renk gorunur ve Face Corner
    export'ta kose paylasimi olmaz; olculdu 2026-09-11: 233k vertex'lik UV'siz mesh -> vertex = 3 x ucgen, .ydd 31 MB).
    Tek duze sifir olmayan "Color 2" (orn. Sollumz'un ped shader eklerken actigi beyaz katman) 0'a cekilir -> me["mpr_wind_reset"]."""
    no_uv = len(me.uv_layers) == 0
    if no_uv:
        me.uv_layers.new(name="UVMap 0")
    me.uv_layers[0].name = "UVMap 0"
    if "UVMap 1" not in me.uv_layers:
        me.uv_layers.new(name="UVMap 1")
    for cname in ("Color 1", "Color 2"):
        ca = me.color_attributes.get(cname)
        if ca is not None and (ca.domain != "CORNER" or ca.data_type != "BYTE_COLOR"):
            me.color_attributes.remove(ca)
            ca = None
        if ca is None:
            ca = me.color_attributes.new(cname, "BYTE_COLOR", "CORNER")
            ca.data.foreach_set("color_srgb", np.tile(np.array(LAYER_DEFAULT_SRGB[cname], dtype=np.float32), len(ca.data)))
        elif cname == "Color 2" and wind_layer_uniform(me):
            ca.data.foreach_set("color_srgb", np.tile(np.array(LAYER_DEFAULT_SRGB[cname], dtype=np.float32), len(ca.data)))
            me["mpr_wind_reset"] = 1
    return no_uv


def wind_layer_report(me):
    """Colour1 ("Color 2") sifir olmayan kose orani: ruzgar/ter etkisi acik -> oyunda titreme. None = katman yok."""
    ca = me.color_attributes.get("Color 2")
    if ca is None or len(ca.data) == 0:
        return None
    buf = np.empty(len(ca.data) * 4, dtype=np.float32)
    ca.data.foreach_get("color_srgb", buf)
    return float((buf.reshape(-1, 4) > 0.5 / 255).any(axis=1).mean())


def _as_model(obj, parent, arm, mat_cache, tex_dir=None):
    obj.parent = parent
    obj.matrix_parent_inverse.identity()
    obj.sollum_type = "sollumz_drawable_model"
    # obj.copy() kaynak nesnenin LOD isaretcilerini tasir: vanilla import'ta medium/low BOLUNMEMIS mesh'e bakar ve
    # Sollumz onlari her cizime yazar (olculdu: ped_default LOD geometrileri uppr+lowr ikisinde de). Yalniz high.
    for lvl in ("very_high", "medium", "low", "very_low"):
        lod = getattr(obj.sz_lods, lvl, None)
        if lod is not None and lod.mesh is not None:
            lod.mesh = None
    obj.sz_lods.high.mesh = obj.data
    if prepare_mesh_layers(obj.data):
        obj["mpr_no_uv"] = True
    for i, m in enumerate(obj.data.materials):
        obj.data.materials[i] = ped_material_for(m, mat_cache, tex_dir)
    if len(obj.data.materials) == 0:
        obj.data.materials.append(ped_material_for(None, mat_cache, tex_dir))
    mod = next((m for m in obj.modifiers if m.type == "ARMATURE"), None) or obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def _link(obj, coll):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    coll.objects.link(obj)


def _split_by_region(src, tpl, raw_names, coll):
    """Mesh'i baskin agirlik bolgesine gore head/uppr/lowr kopyalarina ayir."""
    V, F, ranges = io.meshes_to_numpy([src])
    idx, val = io.read_weights(ranges, raw_names)
    vreg = comp.vertex_regions(idx, val, tpl.names)
    polys = [p.vertices[:] for p in src.data.polygons]
    freg = comp.face_regions(polys, vreg)
    out = {}
    for r in range(3):
        if not (freg == r).any():
            continue
        o = src.copy()
        o.data = src.data.copy()
        o.name = f"{src.name}.{comp.DEFAULT_COMPONENTS[r].split('_')[0]}"
        coll.objects.link(o)
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if freg[f.index] != r], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        bm.to_mesh(o.data)
        bm.free()
        o.data.update()
        out[r] = o
    return out


def _placeholder(name, coll):
    me = bpy.data.meshes.new(name + "_high")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.01)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    vg = o.vertex_groups.new(name="SKEL_ROOT")
    vg.add(list(range(len(me.vertices))), 1.0, "REPLACE")
    return o


def build_hierarchy(ped_name, meshes, components=comp.DEFAULT_COMPONENTS, tex_dir=None):
    rig = bpy.data.objects.get(io.RIG_NAME)
    if rig is None or rig.get("mpr_stage") != "G":
        raise RuntimeError("MPR_Rig must be in the GTA rest pose (G): run 'Convert to GTA Rest Pose' first")
    tpl = io.template()
    raw_names = io.bone_raw_names(rig, tpl)
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
        bpy.context.scene.collection.children.link(coll)
    # onceki kurulumu temizle
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    mat_cache = {}

    # --- .yft: fragment ---
    frag = rig.copy()
    frag.data = rig.data.copy()
    frag.name = ped_name
    frag.data.name = ped_name + "_skel"
    frag.sollum_type = "sollumz_fragment"
    for k in ("mpr_fit", "mpr_stage"):
        if k in frag:
            del frag[k]
    coll.objects.link(frag)
    fdraw = bpy.data.objects.new(ped_name + ".mesh", None)
    coll.objects.link(fdraw)
    fdraw.parent = frag
    fdraw.sollum_type = "sollumz_drawable"
    ph = _placeholder("skel", coll)
    _as_model(ph, fdraw, frag, mat_cache, tex_dir)

    # --- .ydd: sozluk (armature = deri iskeleti) ---
    dic = rig.copy()
    dic.data = rig.data.copy()
    dic.name = ped_name
    dic.data.name = ped_name + "_dict_skel"
    dic.sollum_type = "sollumz_drawable_dictionary"
    for k in ("mpr_fit", "mpr_stage"):
        if k in dic:
            del dic[k]
    coll.objects.link(dic)
    draws = []
    for cname in components:
        d = bpy.data.objects.new(cname, None)
        coll.objects.link(d)
        d.parent = dic
        d.sollum_type = "sollumz_drawable"
        draws.append(d)
    counts = [0, 0, 0]
    for src in meshes:
        parts = _split_by_region(src, tpl, raw_names, coll)
        for r, o in parts.items():
            _as_model(o, draws[r], dic, mat_cache, tex_dir)
            counts[r] += len(o.data.polygons)
        src.hide_set(True)
    rig.hide_set(True)
    # bos cizimleri kaldir (yuzu olmayan bilesen)
    for r, d in enumerate(draws):
        if counts[r] == 0:
            bpy.data.objects.remove(d, do_unlink=True)
    return frag, dic, {components[r]: counts[r] for r in range(3)}


def _sampler_image(mat, node_name):
    if mat is None or not mat.use_nodes:
        return None
    n = mat.node_tree.nodes.get(node_name)
    return n.image if n is not None and n.bl_idname == "ShaderNodeTexImage" else None


def _image_readable(img):
    fp = bpy.path.abspath(img.filepath) if img.filepath else ""
    if fp and os.path.isfile(fp):
        return True
    if img.packed_file is not None:
        return True
    return img.size[0] > 0 and img.size[1] > 0      # uretilmis (generated) image


def _flat_dds(path, rgba, size=8):
    from ..core import dds
    dds.write_a8r8g8b8(path, np.tile(np.asarray(rgba, dtype=np.float32), (size, size, 1)))
    return path


def build_txd(name, images):
    """Sahne TXD'si (Sollumz 2.9). Ayni adli eski sozluk silinir; new_texture_dictionary yeni sozlugu TEK secili yapar."""
    txds = bpy.context.scene.sz_txds
    coll = txds.texture_dictionaries
    for i in reversed(range(len(coll))):
        if coll[i].name == name:
            coll.remove(i)
    txd = txds.new_texture_dictionary(name)
    for img in images:
        txd.new_texture(img)
    return txd


DIFFUSE_ATLAS = True        # bolumde birden cok renk dokusu -> tek atlas (False: eski yol, en cok yuz kaplayan doku)
_FLAT = "__duz_renk__"


def _image_pixels(img):
    """bpy Image -> (H, W, 4) float, ALTTAN USTE (Blender sirasi)."""
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)


def _atlas_diffuse(models, out_path, max_size):
    """Bolumdeki (head/uppr/lowr) renk dokularini tek atlasa pisir, modellerin UVMap 0'ini hucrelere tasi, DXT yaz.
    Hucre payi yuzey alani; UV 0-1 disina tasiyorsa hucre karo icerir (core/atlas.TILE_MAX). Dokusuz / okunamayan yuz -> gri hucre.
    Neden: oyun cizim basina TEK diffuse adi arar; Winter Soldier'da (UE ripi) 11 doku vardi, yuz ve kollar yanlis dokuyla cikiyordu.
    Donus: (bicim, {kaynak: hucre kenari px}, atlas kenari)."""
    from ..core import atlas as at, dds
    groups, per_model = {}, []
    for m in models:
        me = m.data
        n_p, n_m = len(me.polygons), len(me.materials)
        mi = np.zeros(n_p, dtype=np.int32)
        me.polygons.foreach_get("material_index", mi)
        area = np.zeros(n_p, dtype=np.float32)
        me.polygons.foreach_get("area", area)
        lt = np.zeros(n_p, dtype=np.int32)
        me.polygons.foreach_get("loop_total", lt)
        loop_poly = np.repeat(np.arange(n_p), lt)
        uv = np.zeros(len(me.loops) * 2, dtype=np.float32)
        me.uv_layers[0].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
        slot = []
        for i in range(n_m):
            img = _sampler_image(me.materials[i], "DiffuseSampler")
            slot.append(img.name if img is not None and _image_readable(img) else _FLAT)
        fk = np.array(slot, dtype=object)[np.clip(mi, 0, n_m - 1)] if n_m else np.full(n_p, _FLAT, dtype=object)
        lk = fk[loop_poly]
        for key in set(fk.tolist()):
            g = groups.setdefault(key, dict(area=0.0, uvs=[]))
            g["area"] += float(area[fk == key].sum())
            g["uvs"].append(uv[lk == key])
        per_model.append((m, uv, lk))
    items, caps = [], []
    for key, g in groups.items():
        U = np.concatenate(g["uvs"]) if g["uvs"] else np.zeros((1, 2), np.float32)
        g["range"] = (0.0, 0.0, 1, 1) if key == _FLAT else at.uv_range(U)
        if key == _FLAT:
            items.append(dict(key=key, pixels=None, color=NEUTRAL_DIFF, share=g["area"]))
            caps.append(64)
        else:
            img = bpy.data.images[key]
            nx, ny = g["range"][2], g["range"][3]
            items.append(dict(key=key, pixels=(lambda im=img: _image_pixels(im)), size=tuple(img.size), share=g["area"], tiles=(nx, ny)))
            caps.append(max(img.size[0] * nx, img.size[1] * ny))
    # atlas kenari: kaynaklarin toplam cozunurlugune yeten en kucuk 2'nin kuvveti (kucuk dokular 2048'e sisirilmez)
    S = int(min(max_size, at.next_pow2(np.sqrt(sum(float(c) ** 2 for c in caps)))))
    atlas, layout = at.build_atlas(items, S)
    for m, uv, lk in per_model:
        new = uv.copy()
        for key in set(lk.tolist()):
            sel = lk == key
            umin, vmin, nx, ny = groups[key]["range"]
            new[sel] = at.uv_to_cell(uv[sel], layout[key], S, umin, vmin, nx, ny)
        m.data.uv_layers[0].data.foreach_set("uv", new.astype(np.float32).ravel())
        m.data.update()
    top = np.ascontiguousarray(atlas[::-1])          # DDS ustten alta
    fmt = dds.pick_format(top)
    dds.write_dxt(out_path, top, fmt, S)
    return fmt, {k: int(v[2]) for k, v in layout.items()}, S


def apply_ped_textures(dic, ped_name, tex_dir, max_size=TEX_MAX):
    """Vanilla ped gibi dis sozluk: her cizim icin kural adli diffuse/normal/spec DDS yazar, cizimdeki materyalleri kopyalayip
    bu dokulara baglar (gomulu DEGIL) ve <ped>.ytd icin sahne TXD'si kurar. Cizimde birden cok renk dokusu varsa en cok yuz
    kaplayani kullanilir (oyun cizim basina tek diffuse adi arar) -> rapor 'multi'. Donus: rapor {cizim: {...}}."""
    from ..core import dds
    import shutil
    ytd_dir = os.path.join(tex_dir, "ytd")
    os.makedirs(ytd_dir, exist_ok=True)
    images, rep, encoded = [], {}, {}
    for d in sorted((c for c in dic.children if c.sollum_type == "sollumz_drawable"), key=lambda o: o.name):
        comp_name, num = d.name.split("_")[:2]
        models = [c for c in d.children if c.sollum_type == "sollumz_drawable_model"]
        faces, missing = {}, set()
        for m in models:
            me = m.data
            mi = np.zeros(len(me.polygons), dtype=np.int32)
            me.polygons.foreach_get("material_index", mi)
            cnt = np.bincount(mi, minlength=len(me.materials))
            for i, mat in enumerate(me.materials):
                img = _sampler_image(mat, "DiffuseSampler")
                if img is None or not cnt[i]:
                    continue
                # diskte olmayan dosyaya bakan image (FBX/vanilla import) boyut 0 doner -> sessizce gri yerine raporla
                if _image_readable(img):
                    faces[img.name] = faces.get(img.name, 0) + int(cnt[i])
                else:
                    missing.add(img.name)
        names = {"diff": f"{comp_name}_diff_{num}_a_{RACE.get(comp_name, 'uni')}",
                 "normal": f"{comp_name}_normal_{num}", "spec": f"{comp_name}_spec_{num}"}
        paths = {k: os.path.join(ytd_dir, v + ".dds") for k, v in names.items()}
        fmt, atlas_cells, atlas_size = "A8R8G8B8", None, None
        if DIFFUSE_ATLAS and len(faces) > 1:
            fmt, atlas_cells, atlas_size = _atlas_diffuse(models, paths["diff"], max_size)
            fmt = f"{fmt} atlas {atlas_size}"
        elif faces:
            src = bpy.data.images[max(faces, key=faces.get)]
            fp = bpy.path.abspath(src.filepath) if src.filepath else ""
            if src.name in encoded:
                # ayni kaynak baska cizimde zaten kodlandi -> dosyayi kopyala (4096 dokuyu uc kez kodlama)
                shutil.copyfile(encoded[src.name][0], paths["diff"])
                fmt = encoded[src.name][1]
            else:
                wh = dds.dds_size(fp) if fp.lower().endswith(".dds") and os.path.isfile(fp) else None
                if wh is not None and max(wh) <= max_size:
                    shutil.copyfile(fp, paths["diff"])
                    fmt = "kaynak DDS"
                else:
                    # vanilla diffuse DXT1 (alfasiz); alfali kaynak DXT5 (DXT1 delikleri kapatir). Siniri asan DDS de buradan:
                    # Blender DDS'i cozer, sinira kucultulup yeniden kodlanir.
                    fmt = dds.blender_image_to_dds(src, paths["diff"], max_size=max_size, fmt="AUTO")[0]
                    if wh is not None:
                        fmt += f" (kaynak DDS {wh[0]}x{wh[1]} -> <= {max_size})"
                encoded[src.name] = (paths["diff"], fmt)
        else:
            _flat_dds(paths["diff"], NEUTRAL_DIFF)
        _flat_dds(paths["normal"], FLAT_NORMAL)
        _flat_dds(paths["spec"], FLAT_SPEC)
        imgs = {}
        for k, p in paths.items():
            img = bpy.data.images.load(p, check_existing=True)
            img.reload()        # ayni yol onceki export'tan yuklu kalmis olabilir
            img.colorspace_settings.name = "sRGB" if k == "diff" else "Non-Color"
            imgs[k] = img
            images.append(img)
        copies, merged = {}, 0
        for m in models:
            for i, mat in enumerate(m.data.materials):
                if mat is None:
                    continue
                if mat.name not in copies:
                    c = mat.copy()
                    c.name = f"{mat.name}.{comp_name}"[:60]
                    for key, node_name in (("diff", "DiffuseSampler"), ("normal", "BumpSampler"), ("spec", "SpecSampler")):
                        node = c.node_tree.nodes.get(node_name) if c.use_nodes else None
                        if node is not None and node.bl_idname == "ShaderNodeTexImage":
                            node.image = imgs[key]
                            node.texture_properties.embedded = False
                    fill_empty_samplers(c)
                    copies[mat.name] = c
                m.data.materials[i] = copies[mat.name]
            # Ayni golgelendiriciyi kullanan slotlar tek materyale: dokular artik bolumde ortak (atlas / tek doku), slotlar yalniz
            # geometri sayisini artirir. Calisan addon ped (sauron) cizim basina 1 slot; istisna veren muto_winter 3/8/6, test ped 4/1/4.
            me = m.data
            mats = list(me.materials)
            fns = {getattr(x.shader_properties, "filename", "") for x in mats
                   if x is not None and getattr(x, "sollum_type", "") == "sollumz_material_shader"}
            if len(mats) > 1 and None not in mats and len(fns) == 1:
                me.polygons.foreach_set("material_index", np.zeros(len(me.polygons), dtype=np.int32))
                while len(me.materials) > 1:
                    me.materials.pop()
                me.update()
                merged += len(mats) - 1
        rep[d.name] = {"diffuse": names["diff"], "format": fmt, "sources": sorted(faces), "multi": len(faces) > 1,
                       "missing": sorted(missing), "atlas": atlas_cells, "atlas_size": atlas_size, "slot_birlesti": merged}
    build_txd(ped_name, images)
    return rep


def export(frag, dic, directory, fmt="NATIVE", ytd_name=None):
    """ytd_name: build_txd ile kurulan sahne sozlugu -> ayni cagrida <ad>.ytd de yazilir (yalniz o sozluk secilir)."""
    os.makedirs(directory, exist_ok=True)
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in (frag, dic):
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = frag
    kw = {}
    if ytd_name:
        coll = bpy.context.scene.sz_txds.texture_dictionaries
        idx = [i for i in range(len(coll)) if coll[i].name == ytd_name]
        if not idx:
            raise RuntimeError(f"scene texture dictionary not found: {ytd_name}")
        coll.select(idx[0])
        # export_ytds varsayilan KAPALI: vermeden cagri .ytd yazmaz (olculdu, tools/t_ytd_probe.py)
        kw = dict(export_ytds=True, export_ytds_include="SELECTED")
    with bpy.context.temp_override(selected_objects=[frag, dic], active_object=frag):
        res = bpy.ops.sollumz.export_assets(directory=directory, direct_export=True, use_custom_settings=True,
                                            target_formats={fmt}, target_versions={"GEN8"},
                                            limit_to_selected=True, exclude_skeleton=False,
                                            apply_transforms=False, mesh_domain="FACE_CORNER", **kw)
    return res


_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PEDMETA_TEMPLATE = os.path.join(_DATA, "pedmeta_template_civmale.xml")
VARIATION_TEMPLATE = os.path.join(_DATA, "pedvariation_single.ymt")
# Addon ped: sablonlar OYUN verisinden (atlas yaratik-rig §11.8B: anahtarlar ezberden yazilmaz).
#  peds.meta girdisi = A_M_Y_CarClub_02 (mp2024_02 DLC peds.meta, CIVMALE, 70 alan); degerler .ymt'nin kaynagi a_m_y_beach_01'e
#  cekilir (atlas data/peds_meta.tsv.gz). .ymt = vanilla a_m_y_beach_01.ymt'den TEK varyasyon (tools/build_single_ymt.py:
#  availComp head/uppr/lowr, her bilesende cizim 000 + doku a, prop 0; meta_xml_to_bin 786 B, geri okuma XML'le ayni).
ADDON_OVERRIDES = {"CreatureMetadataName": "null", "MovementClipSet": "move_m@casual@a",
                   "PedVoiceGroup": "male_young_beach_r2pvg"}
# PropsName YAZILMAZ (oge silinir). Veri (2026-09-12): ayni .ydd/.yft/.ytd/.ymt ile REPLACE (/mprped; oyunun peds.meta'si,
# PropsName A_M_Y_Beach_01_p) hatasiz, ADDON (bizim peds.meta, PropsName "null") uc ped'de de (sauron, winter, test_ped) F8
# "SetPedDefaultComponentVariation" native istisnasi; iki kip arasinda kalan tek anlamli alan farki bu (ExpressionSet, capsule,
# hareket seti, CreatureMetadata ayni). Kullanicinin calisan sauron paketinde PropsName satiri YOK. Hipotez: "null" metni bos degil,
# "null" adli prop sozlugu sayilir. OYUNDA DOGRULANACAK.
ADDON_REMOVE = ("PropsName",)


def write_peds_meta(path, ped_name):
    import xml.etree.ElementTree as ET
    tree = ET.parse(PEDMETA_TEMPLATE)
    item = tree.getroot().find("InitDatas/Item")
    if item is None or item.find("Name") is None:
        raise RuntimeError("peds.meta template is broken (no InitDatas/Item/Name)")
    item.find("Name").text = ped_name
    for key, val in ADDON_OVERRIDES.items():
        el = item.find(key)
        if el is not None:
            el.text = val
    for key in ADDON_REMOVE:
        el = item.find(key)
        if el is not None:
            item.remove(el)
    ET.indent(tree, space="  ")
    # bildirim oyun dosyalariyla birebir (cift tirnak); ElementTree'nin kendi bildirimi tek tirnak yaziyor
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(fh, encoding="unicode", xml_declaration=False)
        fh.write("\n")
    return path


def write_test_resource(root_dir, resource, ped_name, stream_files, mode="REPLACE"):
    """mode REPLACE: vanilla ped'i degistirir (oyunun peds.meta'si). ADDON: yeni model — peds.meta yazilir ve fxmanifest'te
    PED_METADATA_FILE bildirilir (oyunda henuz dogrulanmadi). Iki kipte de tek varyasyonlu <ad>.ymt akar: vanilla .ymt
    *_001 cizimini ve _b.._e dokularini listeler, bizde yalniz 000/a var -> rastgele varyasyon bileseni gorunmez yapardi."""
    import shutil
    rdir = os.path.join(root_dir, resource)
    sdir = os.path.join(rdir, "stream")
    os.makedirs(sdir, exist_ok=True)
    for f in stream_files:
        shutil.copy2(f, sdir)
    addon = mode == "ADDON"
    shutil.copy2(VARIATION_TEMPLATE, os.path.join(sdir, f"{ped_name}.ymt"))
    if addon:
        write_peds_meta(os.path.join(rdir, "peds.meta"), ped_name)
    with open(os.path.join(rdir, "fxmanifest.lua"), "w", encoding="utf-8") as fh:
        fh.write("fx_version 'cerulean'\ngame 'gta5'\n\nauthor 'muto'\n")
        if addon:
            fh.write(f"description 'muto_ped_rig addon ped: {ped_name}'\n\nfiles {{\n    'peds.meta',\n}}\n\n"
                     "data_file 'PED_METADATA_FILE' 'peds.meta'\n\n")
        else:
            fh.write(f"description 'muto_ped_rig test: {ped_name} replacement'\n\n")
        fh.write("client_script 'client.lua'\n")
    # her resource kendi komutu: vanilla degistirme /mprped, addon ped /<ped adi>. Tek /mpraddon komutu birden cok addon ped
    # sunucudayken son yuklenen resource'a gidiyordu (test ped + sauron, 2026-09-12).
    cmd = ped_name if addon else "mprped"
    with open(os.path.join(rdir, "client.lua"), "w", encoding="utf-8") as fh:
        fh.write(f"""local MODEL = '{ped_name}'

RegisterCommand('{cmd}', function()
    local hash = joaat(MODEL)
    if not IsModelInCdimage(hash) then
        print(('[mprped] %s not found'):format(MODEL))
        return
    end
    RequestModel(hash)
    local t = GetGameTimer()
    while not HasModelLoaded(hash) do
        if GetGameTimer() - t > 10000 then
            print('[mprped] model could not be loaded (timeout)')
            return
        end
        Wait(50)
    end
    SetPlayerModel(PlayerId(), hash)
    SetModelAsNoLongerNeeded(hash)
    SetPedDefaultComponentVariation(PlayerPedId())
    print(('[mprped] model applied: %s'):format(MODEL))
end, false)
""")
    return rdir
