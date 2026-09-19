"""Animasyon retarget: GTA kemigi <- kaynak iskelet kemigi eslemesi (Blender'siz).

Kurallar atlas scripts/blender_retarget_gta.py'deki olculmus eslemeyle BIREBIR (eklenti ciktisi o betikle kiyaslanir):
  * kalca donusu SKEL_ROOT'a gider; SKEL_Pelvis / SKEL_Spine_Root rest'te +-90 cevirici, 84 klipte sapma 0,0° -> asla anahtarlanmaz
  * klipler uzuvlara konum / olcek yazmaz; MH_ / RB_ / SM_ / EO_ / SPR_ / FB_ / FACIAL_ expression ile surulur
  * SOMA (NVIDIA Kimodo) ayri sozluk: "LeftLeg" SOMA'da UYLUK, Mixamo'da BALDIR; takma ad olarak eklenirse Mixamo bozulur, SOMA dosyasinda
    bacaklar HATA VERMEDEN bozuk cikar (olculdu 2026-09-09). Imza "LeftShin" yalniz SOMA'da var.
  * SOMA parmaklari (basparmak haric) bir kaydirma: Index1 metakarpal -> GTA Finger10 = Index2
Bulanik (difflib) eslesme BILEREK yok: ARP Remap'in yolu; LeftLeg ornegi gibi sessiz yanlis eslesme uretir.
"""
import re

BONE_MAP = {
    "SKEL_ROOT":        ["Hips", "pelvis", "Bip01_Pelvis", "root", "Armature_Hips"],
    "SKEL_Spine0":      ["Spine", "spine_01", "Bip01_Spine"],
    "SKEL_Spine1":      ["Spine1", "spine_02", "Bip01_Spine1"],
    "SKEL_Spine2":      ["Spine2", "spine_03", "Bip01_Spine2"],
    "SKEL_Spine3":      ["Spine3", "spine_04", "chest", "Bip01_Spine3"],
    "SKEL_Neck_1":      ["Neck", "neck_01", "Bip01_Neck"],
    "SKEL_Head":        ["Head", "head", "Bip01_Head"],

    "SKEL_L_Clavicle":  ["LeftShoulder", "clavicle_l", "Bip01_L_Clavicle", "shoulder.L"],
    "SKEL_L_UpperArm":  ["LeftArm", "upperarm_l", "Bip01_L_UpperArm", "upper_arm.L"],
    "SKEL_L_Forearm":   ["LeftForeArm", "lowerarm_l", "Bip01_L_Forearm", "forearm.L"],
    "SKEL_L_Hand":      ["LeftHand", "hand_l", "Bip01_L_Hand", "hand.L"],
    "SKEL_R_Clavicle":  ["RightShoulder", "clavicle_r", "Bip01_R_Clavicle", "shoulder.R"],
    "SKEL_R_UpperArm":  ["RightArm", "upperarm_r", "Bip01_R_UpperArm", "upper_arm.R"],
    "SKEL_R_Forearm":   ["RightForeArm", "lowerarm_r", "Bip01_R_Forearm", "forearm.R"],
    "SKEL_R_Hand":      ["RightHand", "hand_r", "Bip01_R_Hand", "hand.R"],

    "SKEL_L_Thigh":     ["LeftUpLeg", "thigh_l", "Bip01_L_Thigh", "thigh.L"],
    "SKEL_L_Calf":      ["LeftLeg", "calf_l", "Bip01_L_Calf", "shin.L"],
    "SKEL_L_Foot":      ["LeftFoot", "foot_l", "Bip01_L_Foot", "foot.L"],
    "SKEL_L_Toe0":      ["LeftToeBase", "ball_l", "Bip01_L_Toe0", "toe.L"],
    "SKEL_R_Thigh":     ["RightUpLeg", "thigh_r", "Bip01_R_Thigh", "thigh.R"],
    "SKEL_R_Calf":      ["RightLeg", "calf_r", "Bip01_R_Calf", "shin.R"],
    "SKEL_R_Foot":      ["RightFoot", "foot_r", "Bip01_R_Foot", "foot.R"],
    "SKEL_R_Toe0":      ["RightToeBase", "ball_r", "Bip01_R_Toe0", "toe.R"],
}

FINGER_MAP = {}
for _s, _S in (("L", "Left"), ("R", "Right")):
    for _gi, _digit in ((0, "Thumb"), (1, "Index"), (2, "Middle"), (3, "Ring"), (4, "Pinky")):
        for _j in (0, 1, 2):
            FINGER_MAP[f"SKEL_{_s}_Finger{_gi}{_j}"] = [f"{_S}Hand{_digit}{_j + 1}", f"{_digit.lower()}_0{_j + 1}_{_s.lower()}",
                                                        f"f_{_digit.lower()}.0{_j + 1}.{_s}"]

SOMA_MAP = {
    "SKEL_Spine0":  ["Spine1"],
    "SKEL_Spine1":  ["Spine2"],
    "SKEL_Spine2":  ["Chest"],
    "SKEL_Spine3":  [],             # SOMA'da yok -> eslesmez -> rest'te kalir
    "SKEL_Neck_1":  ["Neck1"],
    "SKEL_L_Thigh": ["LeftLeg"],
    "SKEL_L_Calf":  ["LeftShin"],
    "SKEL_R_Thigh": ["RightLeg"],
    "SKEL_R_Calf":  ["RightShin"],
}
SOMA_FINGER_MAP = {}
for _s, _S in (("L", "Left"), ("R", "Right")):
    for _gi, _digit in ((1, "Index"), (2, "Middle"), (3, "Ring"), (4, "Pinky")):
        for _j in (0, 1, 2):
            SOMA_FINGER_MAP[f"SKEL_{_s}_Finger{_gi}{_j}"] = [f"{_S}Hand{_digit}{_j + 2}"]
SOMA_SIGNATURE = "LeftShin"

EXPRESSION_DRIVEN_PREFIX = ("MH_", "RB_", "SM_", "EO_", "SPR_", "FB_", "FACIAL_")
NEVER_KEY = ("SKEL_Pelvis", "SKEL_Spine_Root")
# el iki eksenli hizalanir (yon + avuc normali = (isaret - el) x (serce - el)); tek eksende pronasyon ~28° kayik kaldi (olculdu 2026-09-04)
HAND_FRAME = {"SKEL_R_Hand": ("SKEL_R_Finger10", "SKEL_R_Finger40"),
              "SKEL_L_Hand": ("SKEL_L_Finger10", "SKEL_L_Finger40")}


_MIXAMO_PREFIX = re.compile(r"^mixamorig\d*_?")


def strip(name):
    """mixamorig:LeftArm -> LeftArm ; Armature|Hips -> Hips ; mixamorigHips / mixamorig_Hips (glTF / three.js adlari) -> Hips.
    Onek eki atlas betiginde yok (orada yalniz ':' / '|'); eklenti glTF'ten gelen Mixamo modellerini de esler."""
    for sep in (":", "|"):
        if sep in name:
            name = name.rsplit(sep, 1)[-1]
    return _MIXAMO_PREFIX.sub("", name)


def clip_name(action_name):
    """Oyunda TaskPlayAnim'in kullanacagi klip adi: kucuk harf, [a-z0-9_]; Blender'in .001 eki ve Mixamo 'Armature|' oneki atilir."""
    n = strip(re.sub(r"\.\d{3}$", "", action_name)).lower()
    n = re.sub(r"[^a-z0-9_]+", "_", n).strip("_")
    return n or "clip"


def is_soma(src_names):
    return any(strip(n) == SOMA_SIGNATURE for n in src_names)


def build_pairs(target_names, src_names, fingers=True):
    """-> (pairs {GTA: kaynak}, eslesmeyen GTA adlari, soma mu). Once tam ad, sonra onek siz, sonra kucuk harf; aday sirasi korunur."""
    full = dict(BONE_MAP)
    if fingers:
        full.update(FINGER_MAP)
    soma = is_soma(src_names)
    if soma:
        full.update(SOMA_MAP)                      # ezme, ekleme degil: "LeftLeg" aday listesinde kalirsa baldira uyluk donusu yazilir
        if fingers:
            full.update(SOMA_FINGER_MAP)
    by_exact = {n: n for n in src_names}
    by_strip, by_lower = {}, {}
    for n in src_names:
        by_strip.setdefault(strip(n), n)
        by_lower.setdefault(strip(n).lower(), n)
    tset = set(target_names)
    pairs, missing = {}, []
    for g, cands in full.items():
        if g not in tset:
            continue
        hit = None
        for c in cands:
            hit = by_exact.get(c) or by_strip.get(c) or by_lower.get(c.lower())
            if hit:
                break
        if hit:
            pairs[g] = hit
        else:
            missing.append(g)
    return pairs, missing, soma


def duplicate_sources(pairs):
    """Ayni kaynak kemigi birden cok GTA kemigine atanmis mi (ARP'nin cift atama kontrolu) -> {kaynak: [GTA...]}."""
    inv = {}
    for g, s in pairs.items():
        inv.setdefault(s, []).append(g)
    return {s: gs for s, gs in inv.items() if len(gs) > 1}


def forbidden_channels(data_paths):
    """Bake edilmis action'in fcurve data_path'leri -> GTA'da yasak kanallar (bos listeler = temiz)."""
    bad = dict(scale=set(), limb_location=set(), expression=set(), never_key=set())
    for dp in data_paths:
        if 'pose.bones["' not in dp:
            continue
        bone = dp.split('"')[1]
        prop = dp.rsplit(".", 1)[-1]
        if prop == "scale":
            bad["scale"].add(bone)
        if prop == "location" and bone != "SKEL_ROOT" and not bone.startswith(("IK_", "PH_")):
            bad["limb_location"].add(bone)
        if bone.startswith(EXPRESSION_DRIVEN_PREFIX):
            bad["expression"].add(bone)
        if bone in NEVER_KEY:
            bad["never_key"].add(bone)
    return {k: sorted(v) for k, v in bad.items()}
