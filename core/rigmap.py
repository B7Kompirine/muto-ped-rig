"""Hazir iskeletli modelden (Mixamo / Ready Player Me / Tripo "Mixamo-ready", Unreal) marker baslangici.

Eslemeler tools/t_rigged_bench.py preset'lerinden (80 dokumun GT eklemleri bu tablolarla okundu: xbot, michelle, readyplayerme = mixamo;
winter_soldier = ue). Kaynak eklem OLDUGU GIBI alinir: konvansiyon farki govdeye gore isaret degistiriyor (2026-09-13 diz / kalca
ayristirmasi: ayni Mixamo'da diz ekseni michelle -11,4 / xbot -1,4 cm) -> sabit duzeltme yok. Rigify / CC (AccuRig) tablolari test
modeli olmadan yazilmadi.
"""

LR = ("L", "R")


def norm(name):
    """'mixamorig:LeftArm' / 'mixamorig1:LeftArm' / 'LeftArm' -> 'leftarm'."""
    n = name.split(":")[-1]
    low = n.lower()
    if low.startswith("mixamorig"):
        n = n[len("mixamorig"):].lstrip("0123456789_")
    return n.lower()


def _mixamo():
    m = {"pelvis": "hips", "neck": "neck", "head": "head", "chest": "spine2"}
    for S, s in (("L", "left"), ("R", "right")):
        m.update({f"{S}_clavicle": f"{s}shoulder", f"{S}_shoulder": f"{s}arm", f"{S}_elbow": f"{s}forearm", f"{S}_wrist": f"{s}hand",
                  f"{S}_hip": f"{s}upleg", f"{S}_knee": f"{s}leg", f"{S}_ankle": f"{s}foot", f"{S}_toe": f"{s}toebase"})
        for j in range(3):
            m[f"{S}_f2{j}"] = f"{s}handmiddle{j + 1}"
    return m


def _ue():
    m = {"pelvis": "pelvis", "neck": "neck_01", "head": "head", "chest": "spine_05"}
    for S, s in (("L", "l"), ("R", "r")):
        m.update({f"{S}_clavicle": f"clavicle_{s}", f"{S}_shoulder": f"upperarm_{s}", f"{S}_elbow": f"lowerarm_{s}", f"{S}_wrist": f"hand_{s}",
                  f"{S}_hip": f"thigh_{s}", f"{S}_knee": f"calf_{s}", f"{S}_ankle": f"foot_{s}", f"{S}_toe": f"ball_{s}"})
        for j in range(3):
            m[f"{S}_f2{j}"] = f"middle_0{j + 1}_{s}"
    return m


PRESETS = {"Mixamo": _mixamo(), "Unreal": _ue()}
# UE4 manken omurgasi spine_03'te biter (spine_05 UE5); gogus yedegi
CHEST_FALLBACK = {"Unreal": ("spine_03", "spine_02"), "Mixamo": ("spine1",)}
# dirsek / diz / kalca / omuz / bilek / ayak bilegi + govde: bunlar yoksa iskelet taninmis sayilmaz
CORE_KEYS = ("pelvis", "neck", "head") + tuple(f"{S}_{k}" for S in LR for k in ("shoulder", "elbow", "wrist", "hip", "knee", "ankle"))


def detect(bone_names):
    """-> (preset adi, {marker: kaynak kemik adi}) ya da (None, {}) ; zorunlu CORE_KEYS'in hepsi eslesmeli."""
    by_norm = {}
    for n in bone_names:
        by_norm.setdefault(norm(n), n)
    best = (None, {}, -1)
    for pname, table in PRESETS.items():
        got = {k: by_norm[b] for k, b in table.items() if b in by_norm}
        if "chest" not in got:
            alt = next((by_norm[b] for b in CHEST_FALLBACK.get(pname, ()) if b in by_norm), None)
            if alt:
                got["chest"] = alt
        if all(k in got for k in CORE_KEYS) and len(got) > best[2]:
            best = (pname, got, len(got))
    return best[0], best[1]


def markers_from_heads(mapping, heads):
    """mapping {marker: kaynak kemik}, heads {kaynak kemik: dunya konumu} -> {marker: konum}."""
    return {k: heads[b] for k, b in mapping.items() if b in heads}
