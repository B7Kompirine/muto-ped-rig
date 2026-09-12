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
NO_ROTATE = {"SKEL_ROOT", "SKEL_Pelvis", "SKEL_Spine_Root"}  # koordinat ceviriciler / kok


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


def fit_skeleton(tpl: Skeleton, targets: dict, min_axis=0.005):
    """targets: {kemik_adi: dunya konumu (P pozunda)}. Hedefi olan kemikler 'ana', digerleri yardimci."""
    B = len(tpl.names)
    tL = tpl.local_t()
    RL = tpl.local_R()
    R0 = tpl.rot
    tgt = {tpl.index[k]: np.asarray(v, float) for k, v in targets.items() if k in tpl.index}

    # kaba global olcek: ana zincir boy oranlarinin medyani
    ratios = []
    for b, c in PRIMARY.items():
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
        if name not in NO_ROTATE:
            c = PRIMARY.get(name)
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
        t_new[b] = t_new[twin] if twin is not None else tL[b] * scale[p]
        P_pos[b] = P_pos[p] + P_R[p] @ t_new[b]
        P_R[b] = P_R[p] @ RL[b]
        done[b] = True

    # 4) G: vanilla rotasyon + ayni yerel otelemeler
    G_pos = np.zeros((B, 3))
    for b in tpl.order:
        p = tpl.parents[b]
        G_pos[b] = P_pos[b] if p < 0 else G_pos[p] + R0[p] @ t_new[b]
    return FitResult(tpl, t_new, compose(P_R, P_pos), compose(R0, G_pos), scale, g)
