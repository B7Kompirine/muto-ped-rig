"""Kullanici marker'lari -> iskelet eklem hedefleri (SKEL_*). Saf numpy.

Marker = sahnede surukelenen bos obje; her biri bir eklemi temsil eder. Zorunlu set videodaki akisla ayni
(kafa, boyun, kalca, omuz/dirsek/bilek, kalca eklemi/diz/ayak bilegi). Omurga, klavikula, ayak parmagi ve
parmaklar verilmezse vanilla oranlariyla govde cercevesinde turetilir.
"""
import numpy as np

LR = ("L", "R")

# marker anahtari -> kemik
DIRECT = {"pelvis": "SKEL_ROOT", "neck": "SKEL_Neck_1", "head": "SKEL_Head", "chest": "SKEL_Spine3"}
for _s in LR:
    DIRECT.update({
        f"{_s}_clavicle": f"SKEL_{_s}_Clavicle", f"{_s}_shoulder": f"SKEL_{_s}_UpperArm",
        f"{_s}_elbow": f"SKEL_{_s}_Forearm", f"{_s}_wrist": f"SKEL_{_s}_Hand",
        f"{_s}_hip": f"SKEL_{_s}_Thigh", f"{_s}_knee": f"SKEL_{_s}_Calf",
        f"{_s}_ankle": f"SKEL_{_s}_Foot", f"{_s}_toe": f"SKEL_{_s}_Toe0",
    })
    for _f in range(5):
        for _j in range(3):
            DIRECT[f"{_s}_f{_f}{_j}"] = f"SKEL_{_s}_Finger{_f}{_j}"

REQUIRED = ["pelvis", "neck", "head"] + [f"{s}_{k}" for s in LR for k in
                                         ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")]
BASIC = REQUIRED + ["chest"] + [f"{s}_{k}" for s in LR for k in ("clavicle", "toe")]

LABELS = {
    "pelvis": "Pelvis", "neck": "Neck", "head": "Head", "chest": "Chest",
    "clavicle": "Clavicle", "shoulder": "Shoulder", "elbow": "Elbow", "wrist": "Wrist",
    "hip": "Hip Joint", "knee": "Knee", "ankle": "Ankle", "toe": "Toe",
}
FINGER_NAMES = ("Thumb", "Index", "Middle", "Ring", "Pinky")


def label(key):
    if key in LABELS:
        return LABELS[key]
    side, rest = key.split("_", 1)
    if rest.startswith("f") and len(rest) == 3:
        return f"{side} {FINGER_NAMES[int(rest[1])]} {int(rest[2]) + 1}"
    return f"{side} {LABELS.get(rest, rest)}"


def mirror_key(key):
    if key.startswith("L_"):
        return "R_" + key[2:]
    if key.startswith("R_"):
        return "L_" + key[2:]
    return None


def vanilla_markers(tpl, keys=None):
    keys = keys or list(DIRECT)
    return {k: tpl.pos[tpl.index[DIRECT[k]]].copy() for k in keys if DIRECT[k] in tpl.index}


def _frame(m):
    """Govde cercevesi: yan (L-R), sirt (+Y yonu, ped -Y'ye bakar), yukari."""
    up = m["neck"] - m["pelvis"]
    lat = m["L_hip"] - m["R_hip"]
    up_n = up / np.linalg.norm(up)
    lat = lat - up_n * np.dot(lat, up_n)
    lat /= np.linalg.norm(lat)
    back = np.cross(up_n, lat)
    return np.stack([lat, back, up_n], axis=1)          # sutunlar


def expand_targets(tpl, markers):
    """markers {anahtar: konum} -> fit_skeleton hedefleri {SKEL_*: konum}."""
    m = {k: np.asarray(v, float) for k, v in markers.items() if v is not None}
    miss = [k for k in REQUIRED if k not in m]
    if miss:
        raise ValueError("missing markers: " + ", ".join(label(k) for k in miss))
    vm = vanilla_markers(tpl)
    Fv, Ft = _frame(vm), _frame(m)
    torso_v = np.linalg.norm(vm["neck"] - vm["pelvis"])
    torso_t = np.linalg.norm(m["neck"] - m["pelvis"])
    s_up = torso_t / torso_v
    s_sh = np.linalg.norm(m["L_shoulder"] - m["R_shoulder"]) / np.linalg.norm(vm["L_shoulder"] - vm["R_shoulder"])
    s_hip = np.linalg.norm(m["L_hip"] - m["R_hip"]) / np.linalg.norm(vm["L_hip"] - vm["R_hip"])

    def map_torso(p_v, lat_scale):
        rel = Fv.T @ (p_v - vm["pelvis"])
        return m["pelvis"] + Ft @ (rel * np.array([lat_scale, s_up, s_up]))

    T = {}
    root_v = tpl.pos[tpl.index["SKEL_ROOT"]]
    for bn in ("SKEL_ROOT", "SKEL_Pelvis", "SKEL_Spine_Root"):
        T[bn] = m["pelvis"] + Ft @ (Fv.T @ (tpl.pos[tpl.index[bn]] - root_v)) * s_up
    for k in REQUIRED + ["chest"] + [f"{s}_{x}" for s in LR for x in ("clavicle", "toe")]:
        if k in m:
            T[DIRECT[k]] = m[k]
    # omurga: gogus marker'i varsa iki parcali, yoksa govde cercevesinde vanilla oranlari
    for bn in ("SKEL_Spine0", "SKEL_Spine1", "SKEL_Spine2", "SKEL_Spine3"):
        if bn in T:
            continue
        T[bn] = map_torso(tpl.pos[tpl.index[bn]], 1.0)
    if "chest" in m:  # Spine0..2'yi pelvis->gogus arasina yeniden dagit
        v0, v3 = vm["pelvis"], vm["chest"]
        t0, t3 = m["pelvis"], m["chest"]
        for bn in ("SKEL_Spine0", "SKEL_Spine1", "SKEL_Spine2"):
            pv = tpl.pos[tpl.index[bn]]
            u = np.dot(pv - v0, v3 - v0) / np.dot(v3 - v0, v3 - v0)
            off = Fv.T @ (pv - (v0 + u * (v3 - v0)))
            T[bn] = t0 + u * (t3 - t0) + Ft @ (off * s_up)
    for s in LR:
        ck = f"SKEL_{s}_Clavicle"
        if ck not in T:
            T[ck] = map_torso(tpl.pos[tpl.index[ck]], s_sh)
        tk = f"SKEL_{s}_Toe0"
        if tk not in T:  # ayak bilegi -> parmak: vanilla ofseti govde cercevesinde, bacak oraniyla
            leg_v = np.linalg.norm(vm[f"{s}_hip"] - vm[f"{s}_knee"]) + np.linalg.norm(vm[f"{s}_knee"] - vm[f"{s}_ankle"])
            leg_t = np.linalg.norm(m[f"{s}_hip"] - m[f"{s}_knee"]) + np.linalg.norm(m[f"{s}_knee"] - m[f"{s}_ankle"])
            off = Fv.T @ (vm[f"{s}_toe"] - vm[f"{s}_ankle"])
            T[tk] = m[f"{s}_ankle"] + Ft @ off * (leg_t / leg_v)
        for f in range(5):
            chain = [f"{s}_f{f}{j}" for j in range(3)]
            if all(k in m for k in chain):
                for k in chain:
                    T[DIRECT[k]] = m[k]
            elif chain[0] in m:
                # yalniz kok (autodetect.palm_markers: isaret/serce koku) -> fit el donusunu bundan hesaplar
                T[DIRECT[chain[0]]] = m[chain[0]]
    for k, v in m.items():                               # yuz sablon kaydi (core/headreg): kemik adi = anahtar, tum alt agac birlikte
        if k.startswith(("FB_", "FACIAL_")) and k in tpl.index:
            T[k] = v
    return T


def initial_guess(tpl, lo, hi, vanilla_lo, vanilla_hi, keys=None):
    """Mesh sinir kutusuna olceklenmis vanilla marker'lari (baslangic; kullanici surukler)."""
    vm = vanilla_markers(tpl, keys or BASIC)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    vlo, vhi = np.asarray(vanilla_lo, float), np.asarray(vanilla_hi, float)
    s_h = (hi[2] - lo[2]) / (vhi[2] - vlo[2])
    c_t = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    c_v = np.array([(vlo[0] + vhi[0]) / 2, (vlo[1] + vhi[1]) / 2, vlo[2]])
    s_x = (hi[0] - lo[0]) / (vhi[0] - vlo[0])
    out = {}
    for k, p in vm.items():
        rel = p - c_v
        arm = any(x in k for x in ("elbow", "wrist", "f0", "f1", "f2", "f3", "f4"))
        sx = s_x if arm else s_h
        out[k] = c_t + rel * np.array([sx, s_h, s_h])
    return out
