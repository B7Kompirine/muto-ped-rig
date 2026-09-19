"""Tiklayarak yari otomatik marker yolu (kullanici secimi 2026-09-14): kullanici mesh'e 10 ana nokta tiklar, kalan marker'lar bu noktalardan dolar.

Derinlik: tiklama isini mesh'ten birkac kez gecer (cene, pacca, sac). Eklem secilen araligin k oraninda (0 on, 1 arka). Kural ve k VERIDEN
(scratchpad depth_rule_eval.py; onden isin GT eklemin x,z'sinden; 12 vanilla govde A-pose GTA GT govde-disarida-birak / 80 dokum, derinlik hatasi
ort cm). Kurallar: ilk aralik (ilk giris-cikis) · DIS (ilk giris - son cikis, Auto-Rig Pro) · en kalin aralik.
  boyun  DIS k 0,46: 1,12 / 1,47   (ilk aralik 1,83 / 3,20)
  bas    DIS k 0,57: 1,87 / 2,15   (ilk aralik 32,6 / 93,6; en kalin 10,0 / 6,2)
  omuz   DIS k 0,52: 0,90 / 1,05   (ilk aralik 1,99 / 3,17)
  bilek  EN KALIN k 0,50: 0,58 / 0,61   (DIS 0,32 / 0,99: A-pose'da isin arkadaki uyluga da carpar)
  kalca  DIS k 0,45: 2,35 / 1,05   (ilk aralik 6,14 / 4,97)
  ayak bilegi DIS k 0,64: 0,64 / 1,60   (ilk aralik 7,54 / 6,57)
Auto-Rig Pro sabitleri (omuz 0,40, diz 0,75; out/arp_study/BULGULAR.md) kalibre degil.

Doldurma (scratchpad keypoints_eval.py, 80 dokum, tiklanmayan GT eklemleri ort cm): otomatik algilama + ana noktalar + propagate_linked 3,74
(dirsek 3,14, diz 3,30, ayak parmagi 5,34, parmak 2,67) · algilamasiz sablon 4,49 (64 / 80 vaka kotu) -> algilama varsa o, basarisizsa sablon.
"""
import numpy as np

KEY_ORDER = ("head", "neck", "L_shoulder", "R_shoulder", "L_wrist", "R_wrist", "L_hip", "R_hip", "L_ankle", "R_ankle")
DEPTH = {"neck": ("outer", 0.46), "head": ("outer", 0.57), "shoulder": ("outer", 0.52), "wrist": ("thickest", 0.50),
         "hip": ("outer", 0.45), "ankle": ("outer", 0.64)}
# Leğen algilamadan degil sablondan (5 ana noktaya Umeyama): 80 dokum (16 oran varyanti dahil) 6,18 -> 3,73 cm; 12 vanilla x 3 poz GTA GT
# 3,03 -> 0,00 (vanilla ayni sablon orani: tanim geregi 0, ayirt edici degil; yon ayni). Dokumun "pelvis"i kaynak rig Hips'i (konvansiyon).
PELVIS_FROM_TEMPLATE = True
TORSO_ANCHORS = ("L_hip", "R_hip", "neck", "L_shoulder", "R_shoulder")


def _base(key):
    return key.split("_", 1)[1] if key[:2] in ("L_", "R_") else key


def interval_point(hit_ts, k, rule="outer"):
    """Isin boyunca carpma mesafeleri -> araligin k orani. rule: 'outer' ilk giris - son cikis, 'thickest' en kalin giris-cikis cifti,
    'first' ilk cift. Tek carpmada o nokta, carpma yoksa None."""
    ts = sorted(float(t) for t in hit_ts)
    if not ts:
        return None
    ts = [t for i, t in enumerate(ts) if i == 0 or t - ts[i - 1] > 1e-4]        # ayni yuzeyin tekrari (kenar) tek sayilir
    if len(ts) == 1:
        return ts[0]
    if rule == "outer":
        a, b = ts[0], ts[-1]
    elif rule == "thickest":
        a, b = max(((ts[i], ts[i + 1]) for i in range(0, len(ts) - 1, 2)), key=lambda pr: pr[1] - pr[0])
    else:
        a, b = ts[0], ts[1]
    return a + k * (b - a)


def click_point(origin, direction, hit_ts, key):
    """Tiklama -> eklem konumu. origin / direction: goruntu isini, hit_ts: mesh carpma mesafeleri (direction boyunca)."""
    o, d = np.asarray(origin, float), np.asarray(direction, float)
    d = d / max(np.linalg.norm(d), 1e-12)
    rule, k = DEPTH.get(_base(key), ("outer", 0.5))
    t = interval_point(hit_ts, k, rule)
    return None if t is None else o + t * d


def _umeyama(A, B):
    ma, mb = A.mean(0), B.mean(0)
    A0, B0 = A - ma, B - mb
    U, S, Vt = np.linalg.svd(B0.T @ A0 / len(A))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / max((A0 ** 2).sum(1).mean(), 1e-12))
    return s, R, mb - s * R @ ma


def template_fill(vanilla, keys):
    """Algilamasiz: govde (pelvis, chest, klavikula) vanilla marker'larindan 5 ana noktaya Umeyama benzerligi; uzuv ara / uc eklemleri eklem
    ciftinden benzerlik (dirsek, parmaklar omuz -> bilek; diz, ayak parmagi kalca -> ayak bilegi)."""
    from .species import sim_map
    out = {k: np.asarray(v, float) for k, v in keys.items()}
    if all(k in keys for k in TORSO_ANCHORS):
        s, R, t = _umeyama(np.array([vanilla[k] for k in TORSO_ANCHORS]), np.array([keys[k] for k in TORSO_ANCHORS]))
        for k in ("pelvis", "chest", "L_clavicle", "R_clavicle"):
            if k in vanilla:
                out[k] = s * R @ vanilla[k] + t
    for S in "LR":
        sh, wr, hp, an = (f"{S}_{x}" for x in ("shoulder", "wrist", "hip", "ankle"))
        if sh in keys and wr in keys:
            for k in [f"{S}_elbow"] + [f"{S}_f{f}{j}" for f in range(5) for j in range(3)]:
                if k in vanilla:
                    out[k] = sim_map(vanilla[k], vanilla[sh], vanilla[wr], out[sh], out[wr])
        if hp in keys and an in keys:
            for k in (f"{S}_knee", f"{S}_toe"):
                if k in vanilla:
                    out[k] = sim_map(vanilla[k], vanilla[hp], vanilla[an], out[hp], out[an])
    return out


def fill_markers(keys, vanilla, detected=None):
    """keys: tiklanan ana noktalar; detected: otomatik algilama (kalibre) ya da None. Donus: tum marker'lar."""
    from .markers import propagate_linked
    if detected is None:
        return template_fill(vanilla, keys)
    out = {k: np.asarray(v, float) for k, v in detected.items()}
    out.update({k: np.asarray(v, float) for k, v in keys.items()})
    out.update(propagate_linked(detected, out))
    if PELVIS_FROM_TEMPLATE:
        tf = template_fill(vanilla, keys)
        if "pelvis" in tf:
            out["pelvis"] = tf["pelvis"]
    return out
