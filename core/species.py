"""Insan disi iskelet aileleri: marker seti + sablondan genel hedef turetme. Saf numpy.

GTA custom iskelet kabul etmez -> hedef iskelet secilen hayvan ped'inin KENDI iskeletidir (ad/tag/sayi o ped'inki).
Olculdu (2026-09-13, atlas skeletons.tsv): rottweiler, retriever, husky, shepherd, coyote, mtlion, panther, boar, pig, cow, deer, chop
AYNI 39 SKEL_ kemigini tasir (yardimci kemik sayisi 72-82 degisir) -> tek dort ayakli marker seti hepsine uyar. Kucuk kopekler (westy,
poodle, pug: 36 SKEL, Neck0-2/Tail0-2) ve kedi (39, Tail0-5) ayri aileler.
"""
import numpy as np

LR = ("L", "R")

# Hedef hayvan ped'leri: eklenti data/animals (template_<ped>.json + ref_<ped>.npz + animal_templates.blend; tools/t_animal_ref.py,
# tools/t_animal_template_blend.py). Klip sayilari atlas yaratik-rig.md (benzersiz klip): rottweiler 228, retriever 80, coyote 64.
ANIMAL_PEDS = (
    ("a_c_rottweiler", "Rottweiler (most animations)"), ("a_c_retriever", "Retriever"), ("a_c_husky", "Husky"),
    ("a_c_shepherd", "Shepherd"), ("a_c_chop", "Chop"), ("a_c_coyote", "Coyote"), ("a_c_mtlion", "Mountain Lion"),
    ("a_c_panther", "Panther"), ("a_c_boar", "Boar"), ("a_c_pig", "Pig"), ("a_c_cow", "Cow"), ("a_c_deer", "Deer"),
    ("a_c_rottweiler_02", "Rottweiler 2 (DLC)"), ("a_c_chop_02", "Chop 2 (DLC)"), ("a_c_boar_02", "Boar 2 (DLC)"),
    ("a_c_coyote_02", "Coyote 2 (DLC)"), ("a_c_deer_02", "Deer 2 (DLC)"), ("a_c_mtlion_02", "Mountain Lion 2 (DLC)"),
)

QUAD_SKEL = frozenset(
    ["SKEL_ROOT", "SKEL_Spine_Root", "SKEL_Spine0", "SKEL_Spine1", "SKEL_Spine2", "SKEL_Spine3", "SKEL_Neck_1", "SKEL_Neck_2",
     "SKEL_Head", "SKEL_PelvisRoot", "SKEL_Pelvis1", "SKEL_Pelvis"] + [f"SKEL_Tail_0{i}" for i in range(1, 6)]
    + [f"SKEL_{s}_{b}" for s in LR for b in ("Clavicle", "UpperArm", "Forearm", "Hand", "Finger00", "Finger01",
                                               "Thigh", "Calf", "Foot", "Toe0", "Toe1")])

# marker anahtari -> kemik. Uzuv anahtarlari insanla ayni (Mirror / Update Linked ayni calisir): on bacak omuz-dirsek-bilek(karpus),
# arka bacak kalca-diz-ayak bilegi (topuk / hock).
QUAD_DIRECT = {"spine_mid": "SKEL_Spine0", "chest": "SKEL_Spine3", "hips": "SKEL_Pelvis", "neck": "SKEL_Neck_1", "head": "SKEL_Head",
               "tail": "SKEL_Tail_01", "tail_tip": "SKEL_Tail_05"}
for _s in LR:
    QUAD_DIRECT.update({
        f"{_s}_clavicle": f"SKEL_{_s}_Clavicle", f"{_s}_shoulder": f"SKEL_{_s}_UpperArm", f"{_s}_elbow": f"SKEL_{_s}_Forearm",
        f"{_s}_wrist": f"SKEL_{_s}_Hand", f"{_s}_paw": f"SKEL_{_s}_Finger00", f"{_s}_hip": f"SKEL_{_s}_Thigh",
        f"{_s}_knee": f"SKEL_{_s}_Calf", f"{_s}_ankle": f"SKEL_{_s}_Foot", f"{_s}_toe": f"SKEL_{_s}_Toe0"})
QUAD_REQUIRED = ["spine_mid", "chest", "hips", "head", "tail"] + [f"{s}_{k}" for s in LR for k in
                                                                   ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")]
QUAD_LABELS = {"spine_mid": "Mid Back", "chest": "Withers", "hips": "Hips", "neck": "Neck", "head": "Head", "tail": "Tail Root",
               "tail_tip": "Tail Tip", "clavicle": "Shoulder Blade", "shoulder": "Shoulder", "elbow": "Elbow", "wrist": "Front Wrist",
               "paw": "Front Paw", "hip": "Hip Joint", "knee": "Knee", "ankle": "Hock", "toe": "Hind Paw"}


def family(tpl):
    """-> 'quad' | None (insan ve bilinmeyen aileler None)."""
    skel = {n for n in tpl.names if n.startswith("SKEL_")}
    return "quad" if skel == QUAD_SKEL else None


def label(key):
    if key in QUAD_LABELS:
        return QUAD_LABELS[key]
    side, rest = key.split("_", 1)
    return f"{side} {QUAD_LABELS.get(rest, rest)}"


# Marker'dan kurulan HEDEF fit'inde donmeyen ek kemikler (fit_skeleton no_rotate = fit.NO_ROTATE | bu). SKEL_PelvisRoot / SKEL_Pelvis1
# sifir boylu yardimci zincir: donusleri yalniz kok hedefinden Pelvis eklemine kisa (cakal 9 cm) ofsete bakar -> leğen egimini hic gormez
# (dogru marker'la 10 derece egik leğen fit sonrasi yine 10 derece hatali) ama marker gurultusunu buyutur: 1 cm gurultude Pelvis donus
# hatasi cakal 9,05 / geyik 3,39 / yaban domuzu 3,13 derece -> 0 (scratchpad deney 2026-09-13); auto marker'la cakal arka bacak GTA rest
# donusu ort 2,26 -> 0,95 cm. YALNIZ HEDEF: referans hayvan fitlerinde (agirlik aktarimi) de uygulaninca 4 hayvan klibinde on kol bolgesi
# kotulesti (geyik otlama kol 30,6 -> 51,9 %, havlama 9,0 -> 17,6; fit donusleri ayni -> fark agirliktan).
QUAD_TARGET_NO_ROTATE = frozenset({"SKEL_PelvisRoot", "SKEL_Pelvis1"})

# Marker'dan ped boyuna olcek: eklem ciftlerinin boyu / sablondaki boyu; govde, on bacak, arka bacak gruplarinin MEDYANLARININ ortalamasi.
# Donus boyu degistirmez -> durustan bagimsiz. Veri (2026-09-13, tools/t_animal_auto_chain + t_emote_weights; scratchpad marker_size_eval):
# - durus: mesh boyu (panelin eski olcusu) cakal / geyik guclu durusta +20,3 / -22,1 % sapar; bu olcu GT ile 0, Auto Markers ile +13,6
#   (cokmus oturma; Auto Markers o durumda zaten uyarir) / +2,6, kutu marker'la -6,2...+3,1.
# - oran: cakal yalniz bacak x1,25, Sollumz 4 + 11 hayvan klibi en kotu kare kotu kenar toplami, carpan 1,00 / 0,95 / 0,90 / 0,86 / 0,83 /
#   0,80: 23,28 / 22,92 / 22,49 / 22,45 / 22,64 / 22,91 -> en iyi 0,86-0,90. Tum segmentlerin tek medyani bacaga kayar (0,80); grup 0,857.
SCALE_GROUPS = (
    (("neck", "head"), ("chest", "spine_mid"), ("spine_mid", "hips"), ("hips", "tail")),
    tuple((f"{s}_{a}", f"{s}_{b}") for s in LR for a, b in (("clavicle", "shoulder"), ("shoulder", "elbow"), ("elbow", "wrist"),
                                                           ("wrist", "paw"))),
    tuple((f"{s}_{a}", f"{s}_{b}") for s in LR for a, b in (("hip", "knee"), ("knee", "ankle"), ("ankle", "toe"))),
)
SCALE_MIN_SEGMENTS = 6


def marker_scale(tpl, markers, direct=QUAD_DIRECT):
    """-> (model / sablon eklem boyu orani ya da None, kullanilan segment sayisi). Grup (govde / on / arka bacak) medyanlarinin ortalamasi;
    en az 2 segmentli grup sayilir. SCALE_MIN_SEGMENTS'ten az segment ya da 2'den az grup -> None."""
    pos = lambda k: tpl.pos[tpl.index[direct[k]]]
    meds, n = [], 0
    for group in SCALE_GROUPS:
        r = [float(np.linalg.norm(np.asarray(markers[a], float) - np.asarray(markers[b], float)) / np.linalg.norm(pos(a) - pos(b)))
             for a, b in group
             if a in markers and b in markers and a in direct and b in direct and np.linalg.norm(pos(a) - pos(b)) > 1e-6]
        n += len(r)
        if len(r) >= 2:
            meds.append(float(np.median(r)))
    return (float(np.mean(meds)) if n >= SCALE_MIN_SEGMENTS and len(meds) >= 2 else None), n


def initial_guess(tpl, lo, hi, ref_lo, ref_hi, direct=QUAD_DIRECT):
    """Add Markers: sablon marker'lari hedef ped'in kendi mesh sinir kutusundan (ref_lo/hi) karakterin kutusuna eksen basina olceklenir.
    Hayvan ped'lerinde boy/yukseklik/genislik oranlari cok farkli (domuz 0,62 x 1,39 m, geyik 1,53 x 2,40) -> tek olcek yetmez."""
    lo, hi, rlo, rhi = (np.asarray(x, float) for x in (lo, hi, ref_lo, ref_hi))
    s = (hi - lo) / np.maximum(rhi - rlo, 1e-6)
    return {k: lo + (tpl.pos[tpl.index[b]] - rlo) * s for k, b in direct.items() if b in tpl.index}


def sim_map(p, a0, b0, a1, b1):
    """a0->b0 segmentini a1->b1'e goturen benzerlik (oran + en kucuk donus) ile p'yi tasir; sifir boyda oteleme."""
    from .fit import rot_between
    u0, u1 = b0 - a0, b1 - a1
    n0, n1 = np.linalg.norm(u0), np.linalg.norm(u1)
    if n0 < 1e-9 or n1 < 1e-9:
        return a1 + (p - a0)
    return a1 + (n1 / n0) * (rot_between(u0 / n0, u1 / n1) @ (p - a0))


def expand_generic(tpl, markers, direct, required, root_pair=("hips", "spine_mid")):
    """markers {anahtar: konum} -> fit_skeleton hedefleri {SKEL_*: konum}; marker'siz SKEL kemikleri sablondan turetilir.

    Kural (sablon sirasiyla, ebeveyn once): marker'i olan kemik = marker. Degilse ebeveyn hedefi -> alt agacindaki en yakin marker
    (marker iceren en buyuk alt agac yolu) segmentinin benzerligiyle. Alt agacinda marker yoksa (uc: pati ucu, kuyruk) dede -> ebeveyn
    segmentinin uzantisi. Kok: root_pair marker'lari (kalca -> sirt ortasi) segmentinin benzerligiyle; yoksa marker agirlik merkezi +
    ortalama olcek (donussuz).
    NEDEN (olculdu 2026-09-13, tools/t_animal_auto_chain pose=1 markers=oracle): agirlik merkezi kurali bas / kuyruk / bacak durusu
    degisince kaydi (kok hedefi 2,3 cm, PelvisRoot / Pelvis1 1,8 cm) -> sifir boylu PelvisRoot -> Pelvis1 zinciri Pelvis'i dogru
    marker'larla bile cakalda 11,3, geyikte 5,3 derece cevirdi; arka bacak / kuyruk GTA rest donusu ort 3,7-6,6 cm bozuldu."""
    miss = [k for k in required if k not in markers or markers[k] is None]
    if miss:
        raise ValueError("missing markers: " + ", ".join(label(k) for k in miss))
    M = {tpl.index[direct[k]]: np.asarray(v, float) for k, v in markers.items()
         if v is not None and k in direct and direct[k] in tpl.index}
    P0 = tpl.pos
    B = len(tpl.names)
    has = np.zeros(B, bool)
    size = np.ones(B, int)
    for i in reversed(tpl.order):
        has[i] |= i in M
        p = tpl.parents[i]
        if p >= 0:
            has[p] |= has[i]
            size[p] += size[i]
    ids = list(M)
    X0, X1 = P0[ids], np.array([M[i] for i in ids])
    c0, c1 = X0.mean(0), X1.mean(0)
    s = float(np.sqrt(((X1 - c1) ** 2).sum() / max(((X0 - c0) ** 2).sum(), 1e-12)))

    def desc_marker(i):
        j = i
        while True:
            kids = [c for c in tpl.children[j] if has[c] and tpl.names[c].startswith("SKEL_")]
            if not kids:
                return None
            j = max(kids, key=lambda c: size[c])
            if j in M:
                return j

    ra, rb = (tpl.index.get(direct.get(k, "")) for k in root_pair)
    T = {}
    for i in tpl.order:
        if not tpl.names[i].startswith("SKEL_"):
            continue
        if i in M:
            T[i] = M[i]
            continue
        p = tpl.parents[i]
        if p < 0 and ra in M and rb in M:
            T[i] = sim_map(P0[i], P0[ra], P0[rb], M[ra], M[rb])      # kok: yerel govde segmenti (durustan bagimsiz)
            continue
        if p < 0 or p not in T:
            T[i] = c1 + s * (P0[i] - c0)
            continue
        d = desc_marker(i)
        if d is not None:
            T[i] = sim_map(P0[i], P0[p], P0[d], T[p], M[d])
            continue
        g = tpl.parents[p]
        if g >= 0 and g in T:
            T[i] = sim_map(P0[i], P0[g], P0[p], T[g], T[p])
        else:
            T[i] = T[p] + s * (P0[i] - P0[p])
    return {tpl.names[i]: v for i, v in T.items()}
