"""Eklem hedeflerinden GTA iskeleti oturtma.

Iki iskelet uretilir ve AYNI yerel otelemeleri paylasir:
  P : mesh'in kendi pozunda (T-pose, A-pose, ne gelirse) — agirliklandirma bunun uzerinde yapilir.
  G : vanilla ROTASYONLU cikis iskeleti — Sollumz'a giden budur.
Yerel otelemeler ortak oldugu icin P, G'nin bir POZUDUR; mesh P'den G'ye LBS ile yeniden pozlanir.

Kural (atlas /ped): kemik adi/tag/parent/sayi sabit, yalniz konum/boy degisir, rotasyon vanilla.
Rotasyonu vanilla birakip konumu T-pose'a tasimak animasyonda uzuvlari rest farki kadar saptirir;
bu yuzden cikis G'dir, P degil.
"""
import numpy as np
from .skeleton import Skeleton, compose

SIDES = ("L", "R")
NO_ROTATE = {"SKEL_ROOT", "SKEL_Pelvis", "SKEL_Spine_Root"}  # koordinat ceviriciler / kok (fit_skeleton no_rotate verilmezse)


def _primary_children():
    m = {"SKEL_Spine0": "SKEL_Spine1", "SKEL_Spine1": "SKEL_Spine2", "SKEL_Spine2": "SKEL_Spine3",
         "SKEL_Spine3": "SKEL_Neck_1", "SKEL_Neck_1": "SKEL_Head"}
    for s in SIDES:
        m[f"SKEL_{s}_Clavicle"] = f"SKEL_{s}_UpperArm"
        m[f"SKEL_{s}_UpperArm"] = f"SKEL_{s}_Forearm"
        m[f"SKEL_{s}_Forearm"] = f"SKEL_{s}_Hand"
        m[f"SKEL_{s}_Hand"] = f"SKEL_{s}_Finger20"
        for f in range(5):
            m[f"SKEL_{s}_Finger{f}0"] = f"SKEL_{s}_Finger{f}1"
            m[f"SKEL_{s}_Finger{f}1"] = f"SKEL_{s}_Finger{f}2"
        m[f"SKEL_{s}_Thigh"] = f"SKEL_{s}_Calf"
        m[f"SKEL_{s}_Calf"] = f"SKEL_{s}_Foot"
        m[f"SKEL_{s}_Foot"] = f"SKEL_{s}_Toe0"
    return m


PRIMARY = _primary_children()

# Birincil cocuk haritasi SABLONDAN (2026-09-13, hayvan iskeletleri): insan PRIMARY'si baska iskelette DOGRUDAN cocuk olmayan kemige
# bakiyordu (geyik Neck_1 -> Head, arada Neck_2; tL[Head] Neck_2'ye gore) -> tum SKEL kemiklerine gercek hedefle bile Head 67 derece,
# yuz kemikleri 373 mm (rottweiler 36 mm). Kural: PRIMARY girdisi sablonda dogrudan cocuksa AYNEN (insan sablonu birebir); degilse ya da
# girdi yoksa hedefli dogrudan cocuklardan alt agaci en buyuk olan. Olculdu: geyik / rottweiler / sempanze / mp_m tam hedefle 0,00 mm,
# 0,00 derece. False = eski davranis (A/B).
DERIVED_PRIMARY = True


def primary_map(tpl, tgt):
    """-> {kemik: birincil cocuk} (tgt: hedefli kemik indeksleri)."""
    size = {}

    def sub(i):
        if i not in size:
            size[i] = 1 + sum(sub(c) for c in tpl.children[i])
        return size[i]
    m = {}
    for i, n in enumerate(tpl.names):
        c = PRIMARY.get(n)
        if c is not None and c in tpl.index and tpl.parents[tpl.index[c]] == i:
            m[n] = c
            continue
        # yalniz SKEL_ -> SKEL_: insan akisinda yuz sablonu FB_ kemiklerine hedef verir; SKEL_Head'in FB cocuguna donmesi insan rig'ini
        # degistirirdi. Hayvan zincirleri (Neck_2, Toe1, Tail, Pelvis1) SKEL_.
        kids = [k for k in tpl.children[i] if k in tgt and tpl.names[k].startswith("SKEL_")] if n.startswith("SKEL_") else []
        if kids:
            m[n] = tpl.names[max(kids, key=sub)]
    return m


def skew(v):
    return np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])


def axis_angle(axis, ang):
    axis = np.asarray(axis, float)
    axis = axis / np.linalg.norm(axis)
    K = skew(axis)
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def rot_between(a, b):
    """a yonunu b yonune goturen en kucuk rotasyon."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = float(np.linalg.norm(v))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        return axis_angle(axis, np.pi)
    K = skew(v)
    return np.eye(3) + K + K @ K * ((1 - c) / (s * s))


class FitResult:
    def __init__(self, tpl, t_local, P_W, G_W, scale, g):
        self.tpl, self.t_local, self.P_W, self.G_W, self.scale, self.g = tpl, t_local, P_W, G_W, scale, g

    @property
    def P(self):
        return self.tpl.with_W(self.P_W)

    @property
    def G(self):
        return self.tpl.with_W(self.G_W)

    def repose_matrices(self):
        """P pozundaki mesh'i G (GTA rest) pozuna goturen deri matrisleri."""
        return self.G_W @ np.linalg.inv(self.P_W)


def fit_skeleton(tpl: Skeleton, targets: dict, min_axis=0.005, no_rotate=None, aux_iso=False):
    """targets: {kemik_adi: dunya konumu (P pozunda)}. Hedefi olan kemikler 'ana', digerleri yardimci.
    no_rotate: donmeyen kemik adlari (varsayilan NO_ROTATE; dort ayakli hedef fit'i species.QUAD_TARGET_NO_ROTATE ekler).
    aux_iso: yardimci kemik otelemesi eksen olcegi yerine global g ile (hayvan REFERANS fit'i, pipeline.animal_transfer_pipeline).
    NEDEN (olculdu 2026-09-14, scratchpad scale_explode_eval / jaw_ref_eval): baska turun iskeleti hedefe oturunca cok cocuklu kemikte
    eksen olcegi min_axis'i az gecen bilesenden patliyor (rottweiler -> yaban domuzu Spine1 klavikula tL z 6 mm, hedef 124 mm -> z 20,71)
    ve alt zincire miras kaliyor -> yardimci FB_Jaw Head'e 4,69 kat (domuz 3,29, cakal 2,62) -> referans cene vertexleri hedefin
    gogsune -> yaban domuzu gogus alti FB_Jaw 1,00, GTA rest donusu max 30 cm. Hedef fit'te (kendi sablonu) oran 18 turde 1,00."""
    nr = NO_ROTATE if no_rotate is None else no_rotate
    B = len(tpl.names)
    tL = tpl.local_t()
    RL = tpl.local_R()
    R0 = tpl.rot
    tgt = {tpl.index[k]: np.asarray(v, float) for k, v in targets.items() if k in tpl.index}
    prim = primary_map(tpl, tgt) if DERIVED_PRIMARY else PRIMARY

    # kaba global olcek: ana zincir boy oranlarinin medyani
    ratios = []
    for b, c in prim.items():
        if b in nr:
            continue                    # koordinat cevirici kokler: insan PRIMARY'sinde yoktu (olcek birebir kalsin)
        bi, ci = tpl.index.get(b), tpl.index.get(c)
        if bi in tgt and ci in tgt and np.linalg.norm(tL[ci]) > 0.02:
            ratios.append(np.linalg.norm(tgt[ci] - tgt[bi]) / np.linalg.norm(tL[ci]))
    g = float(np.median(ratios)) if ratios else 1.0

    P_pos = np.zeros((B, 3))
    P_R = np.zeros((B, 3, 3))
    t_new = np.zeros((B, 3))
    done = np.zeros(B, bool)

    def place_main(b):
        name, p = tpl.names[b], tpl.parents[b]
        if p < 0:
            P_R[b] = R0[b]
            P_pos[b] = tgt[b]
            t_new[b] = P_pos[b]
            return
        t_new[b] = P_R[p].T @ (tgt[b] - P_pos[p])
        P_pos[b] = P_pos[p] + P_R[p] @ t_new[b]
        R = P_R[p] @ RL[b]
        if name not in nr:
            c = prim.get(name)
            ci = tpl.index.get(c) if c else None
            if ci is not None and ci in tgt:
                v0 = R @ tL[ci]
                v1 = tgt[ci] - P_pos[b]
                if np.linalg.norm(v0) > 1e-9 and np.linalg.norm(v1) > 1e-9:
                    R = rot_between(v0, v1) @ R
                    a = v1 / np.linalg.norm(v1)
                    z = 0j
                    for s in tpl.children[b]:
                        if s == ci or s not in tgt:
                            continue
                        u0 = R @ tL[s]
                        u1 = tgt[s] - P_pos[b]
                        u0p = u0 - a * np.dot(u0, a)
                        u1p = u1 - a * np.dot(u1, a)
                        n0, n1 = np.linalg.norm(u0p), np.linalg.norm(u1p)
                        if n0 < 1e-4 or n1 < 1e-4:
                            continue
                        ang = np.arctan2(np.dot(a, np.cross(u0p, u1p)), np.dot(u0p, u1p))
                        z += n0 * n1 * np.exp(1j * ang)
                    if abs(z) > 1e-12:
                        R = axis_angle(a, np.angle(z)) @ R
        P_R[b] = R

    # 1) ana kemikler (hepsinin atasi da ana olmali)
    for b in tpl.order:
        if b in tgt:
            p = tpl.parents[b]
            if p >= 0 and not done[p]:
                raise ValueError(f"main bone {tpl.names[b]}: its parent {tpl.names[p]} has no target")
            place_main(b)
            done[b] = True
    root = tpl.order[0]
    if not done[root]:
        raise ValueError("a SKEL_ROOT target is required")

    # 2) eksen olcekleri: ana cocuklardan, yoksa atadan
    scale = np.ones((B, 3))
    for b in tpl.order:
        p = tpl.parents[b]
        base = np.full(3, g) if p < 0 else scale[p]
        s = base.copy()
        for k in range(3):
            num = den = 0.0
            for c in tpl.children[b]:
                if done[c] and abs(tL[c][k]) > min_axis:
                    num += abs(t_new[c][k])
                    den += abs(tL[c][k])
            if den > 0:
                s[k] = num / den
        scale[b] = s

    # 3) yardimci kemikler: ikiz ana kardes varsa onu kopyala, yoksa ebeveyn olcegiyle
    for b in tpl.order:
        if done[b]:
            continue
        p = tpl.parents[b]
        twin = next((s for s in tpl.children[p] if done[s] and np.linalg.norm(tL[s] - tL[b]) < 1e-4), None)
        t_new[b] = t_new[twin] if twin is not None else tL[b] * (g if aux_iso else scale[p])
        P_pos[b] = P_pos[p] + P_R[p] @ t_new[b]
        P_R[b] = P_R[p] @ RL[b]
        done[b] = True

    # 4) G: vanilla rotasyon + ayni yerel otelemeler
    G_pos = np.zeros((B, 3))
    for b in tpl.order:
        p = tpl.parents[b]
        G_pos[b] = P_pos[b] if p < 0 else G_pos[p] + R0[p] @ t_new[b]
    return FitResult(tpl, t_new, compose(P_R, P_pos), compose(R0, G_pos), scale, g)


REFIT_TOL = 5e-4


def refit_from_rest(prev, P_W, tol=REFIT_TOL):
    """Kayitli fit'i (Fit anindaki P_W / G_W) GUNCEL rest matrislerine (rig dunya, nesne donusumu dahil) uyarlar -> (FitResult, sapma m).
    Neden: Weights ve Convert to GTA Rest kayitli fit'i kullanir; Fit'ten sonra kemik elle tasinir ya da rig + mesh olceklenirse eski
    iskeletle agirlik / GTA rest yapilir. En buyuk konum sapmasi tol altindaysa prev AYNEN doner. Degilse: P donusleri ortonormal
    (nesne olcegi atilir), t_local ebeveynin P cercevesinde, G_W fit_skeleton 4. adimiyla (vanilla donus + ayni yerel oteleme); g ve
    scale SKEL kemik boylarinin prev'e oraninin medyaniyla guncellenir (dirsek duzeltmesi ~1, x1,5 olcek 1,5)."""
    tpl = prev.tpl
    P_W = np.array(P_W, float, copy=True)
    dev = float(np.linalg.norm(P_W[:, :3, 3] - prev.P_W[:, :3, 3], axis=1).max())
    if dev < tol:
        return prev, dev
    U, _, Vt = np.linalg.svd(P_W[:, :3, :3])
    P_W[:, :3, :3] = U @ Vt
    B = len(tpl.names)
    R0 = tpl.rot
    t = np.zeros((B, 3))
    G_pos = np.zeros((B, 3))
    for b in tpl.order:
        p = tpl.parents[b]
        if p < 0:
            t[b] = G_pos[b] = P_W[b, :3, 3]
        else:
            t[b] = P_W[p, :3, :3].T @ (P_W[b, :3, 3] - P_W[p, :3, 3])
            G_pos[b] = G_pos[p] + R0[p] @ t[b]
    ratios = [np.linalg.norm(t[b]) / np.linalg.norm(prev.t_local[b]) for b in range(B)
              if tpl.names[b].startswith("SKEL_") and tpl.parents[b] >= 0 and np.linalg.norm(prev.t_local[b]) > 0.02]
    k = float(np.median(ratios)) if ratios else 1.0
    return FitResult(tpl, t, P_W, compose(R0, G_pos), np.asarray(prev.scale) * k, float(prev.g) * k), dev


# Zemin koku (2026-09-13, kullanici oyun ekrani: boyu degistirilmis karakter comelmis; tools/t_ground_contact.py, out/height_0913/):
# vanilla kliplerde SKEL_ROOT KONUM izi var ve koku ped boyundan bagimsiz ayni yere koyar (+0,952..+0,974). Eklenti ROOT'u lecen
# marker'ina koyuyordu; rest "taban - kok" oyun hipster -0,986 m, eklenti 1,4 m -0,816 / 1,86 m -1,084 / 2,4 m -1,399 -> klipte ayak
# 17 cm havada / 10 cm gomulu / 41 cm gomulu (oyunda bacak IK'si dizleri bukuyor). Kural: G'de ROOT (ve IK_Root) tabanin sablon
# yuksekligi kadar ustune; diger kemiklerin dunya matrisi DEGISMEZ (ROOT'ta agirlik yok -> mesh / deformasyon ayni).
GROUND_ROOT_CHILDREN = ("IK_Root",)


def ground_root(W, tpl, sole_z, root_above_sole):
    """W (B,4,4) dunya matrisleri; ROOT ve GROUND_ROOT_CHILDREN z'si sole_z + root_above_sole olur. -> (yeni W, uygulanan dz)."""
    W = np.array(W, float, copy=True)
    r = tpl.index["SKEL_ROOT"]
    dz = float(sole_z + root_above_sole - W[r, 2, 3])
    for n in ("SKEL_ROOT",) + GROUND_ROOT_CHILDREN:
        i = tpl.index.get(n)
        if i is not None:
            W[i, 2, 3] += dz
    return W, dz
