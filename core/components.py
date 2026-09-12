"""Ped bilesen bolme: karakter mesh'ini agirliklara gore head / uppr / lowr cizimlerine ayir. Saf numpy.

Vanilla ambient ped sozlugu (ornek a_m_y_beach_01): head_000_r, uppr_000_u, lowr_000_u.
Vanilla ped DEGISTIRME yolunda cizim adlari o ped'in .ymt'sinin bekledigi adlarla ayni olmali.
"""
import numpy as np

DEFAULT_COMPONENTS = ("head_000_r", "uppr_000_u", "lowr_000_u")

_HEAD = ("SKEL_Head", "SKEL_Neck_1", "RB_Neck_1", "FACIAL_", "FB_", "MH_Hair", "IK_Head")
_LOWR = ("SKEL_Pelvis", "Thigh", "Calf", "Foot", "Toe", "Knee", "SM_", "EO_", "IK_L_Foot", "IK_R_Foot", "PH_L_Foot", "PH_R_Foot")


def bone_region(name):
    """0 = head, 1 = uppr, 2 = lowr."""
    if any(name.startswith(k) or k in name for k in _HEAD):
        return 0
    if any(k in name for k in _LOWR):
        return 2
    return 1


def vertex_regions(idx, val, names):
    """idx/val (N,k) kemik indeksleri/agirliklari -> vertex basina baskin bolge (agirlik toplami)."""
    reg = np.array([bone_region(n) for n in names])
    acc = np.zeros((len(idx), 3))
    for k in range(idx.shape[1]):
        np.add.at(acc, (np.arange(len(idx)), reg[idx[:, k]]), val[:, k])
    return acc.argmax(1)


def face_regions(polys_vertices, vreg):
    """Yuz basina bolge: kosesi en cok hangi bolgedeyse (esitlikte kucuk indeks = kafa onceligi yok, govde)."""
    out = np.empty(len(polys_vertices), dtype=np.int64)
    for i, vs in enumerate(polys_vertices):
        c = np.bincount(vreg[list(vs)], minlength=3)
        out[i] = int(np.argmax(c[[1, 0, 2]]))  # esitlikte uppr
        out[i] = (1, 0, 2)[out[i]]
    return out
