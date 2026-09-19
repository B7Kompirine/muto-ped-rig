"""Dort ayakli OTOMATIK MARKER: secilen hayvan ped'inin oyun mesh'i (ref npz + kendi sablonu) kullanici modeline ISKELET GUDUMLU ICP ile
kaydirilir, eklemler tasinir. Saf numpy (core/knn).

Yontem (C4): kaynak kontrol noktalari (1.200, en uzak nokta ornekleme) ped'in deri agirligiyla (SKEL atasina toplanmis) LBS ile tasinir;
asamalar tum govde benzerlik -> 7 grup (govde, boyun+bas, kuyruk, 4 bacak) benzerlik -> kemik basina donus + kemik ekseni boyunca / dik
ayri olcek. Eslesme iki yonlu en yakin nokta (hedef 3.000 nokta); patiler (kaynak tabaninin %2 bandi) z'de hedef tabanina sabit (agirlik 5);
kemik uclari mevcut eklem tahminine capa (grup agirliginin %10'u). Eklem = ebeveyn ve kendi donusumunun tahmini ortalamasi; sonuc sol/sag
simetrik (hedef kutu merkezi, x).

Olcum (2026-09-13, scratchpad animal_marker_*.py, out/animals/marker_*_0913.txt; B0 = species.initial_guess kutu tahmini):
- 88 oran varyanti (11 ped kendi mesh'i kendi iskeletiyle LBS esnetildi; bacak x1,25 / x0,75, govde x1,25, boyun x1,5, kafa x1,35, kuyruk
  x1,6, genislik x1,25, karma): ort / tek marker max / B0'dan 2 cm'den fazla kotu marker: B0 4,64 cm · Gauss alanli ICP 0,84 / 22,5 / 23 ·
  C4 0,75 / 18,3 / 8 (tabansiz 0,76 / 19,9 / 13).
- tur arasi 178 cift (GT = hedef ped'in eklemi; kalan hatanin cogu iskelet KURALI farki, coban kopegi Thigh cakala gore +21 cm): ayni grup
  B0 9,40 / C4 5,44 cm (deri agirligi ortalamasi C2 5,27) · farkli grup 21,00 / 12,04 (11,82).
- saglama (hedef = kaynak mesh): ort 0,06, max 0,18 cm.
Bilinen zayiflik: uzun kuyruk ucu (max 14 cm), arka pati ucu (ort 0,9 cm).
"""
import numpy as np

from .knn import GridKNN
from .species import QUAD_DIRECT

N_CTRL = 1200
N_TGT = 3000
ITS = (8, 8, 10)
FLOOR = 5.0
ANCHOR = 0.1
LAT = 0                                             # yanal eksen: hayvan -Y'ye bakar
GROUPS = {"core": ["SKEL_ROOT", "SKEL_Spine_Root", "SKEL_Spine0", "SKEL_Spine1", "SKEL_Spine2", "SKEL_Spine3", "SKEL_PelvisRoot",
                   "SKEL_Pelvis1", "SKEL_Pelvis"],
          "head": ["SKEL_Neck_1", "SKEL_Neck_2", "SKEL_Head"],
          "tail": [f"SKEL_Tail_0{i}" for i in range(1, 6)]}
for _s in "LR":
    GROUPS[f"{_s}_front"] = [f"SKEL_{_s}_{b}" for b in ("Clavicle", "UpperArm", "Forearm", "Hand", "Finger00", "Finger01")]
    GROUPS[f"{_s}_hind"] = [f"SKEL_{_s}_{b}" for b in ("Thigh", "Calf", "Foot", "Toe0", "Toe1")]


def skel_weights(tpl, WI, WV):
    """Referans top-k agirliklari (sablon indeksli) -> ((N, B) SKEL atasina toplanmis agirlik, satir toplami 1; kemik -> SKEL atasi)."""
    anc = np.arange(len(tpl.names))
    for i in tpl.order:
        if not tpl.names[i].startswith("SKEL_"):
            p = tpl.parents[i]
            anc[i] = anc[p] if p >= 0 else i
    wv = WV / np.maximum(WV.sum(1, keepdims=True), 1e-12)
    W = np.zeros((len(WI), len(tpl.names)))
    for c in range(WI.shape[1]):
        np.add.at(W, (np.arange(len(WI)), anc[WI[:, c]]), wv[:, c])
    return W, anc


def fps(P, n, seed=0):
    """En uzak nokta ornekleme (deterministik)."""
    if len(P) <= n:
        return np.arange(len(P))
    idx = [int(np.random.default_rng(seed).integers(len(P)))]
    d = np.linalg.norm(P - P[idx[0]], axis=1)
    for _ in range(n - 1):
        i = int(d.argmax())
        idx.append(i)
        d = np.minimum(d, np.linalg.norm(P - P[i], axis=1))
    return np.array(idx)


def _similarity(X0, X1, w):
    sw = max(w.sum(), 1e-12)
    c0, c1 = (w[:, None] * X0).sum(0) / sw, (w[:, None] * X1).sum(0) / sw
    A0, A1 = X0 - c0, X1 - c1
    U, sg, Vt = np.linalg.svd((w[:, None] * A1).T @ A0)
    dm = np.array([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ np.diag(dm) @ Vt
    s = min(max(float((sg * dm).sum() / max((w * (A0 ** 2).sum(1)).sum(), 1e-12)), 0.5), 2.0)
    M = np.eye(4)
    M[:3, :3] = s * R
    M[:3, 3] = c1 - s * R @ c0
    return M


def _bone_fit(X0, X1, w, u):
    """Olceksiz donus (Umeyama) + hedef cercevede eksen (u) boyunca / dik ayri olcek."""
    sw = max(w.sum(), 1e-12)
    c0, c1 = (w[:, None] * X0).sum(0) / sw, (w[:, None] * X1).sum(0) / sw
    A0, A1 = X0 - c0, X1 - c1
    U, sg, Vt = np.linalg.svd((w[:, None] * A1).T @ A0)
    dm = np.array([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ np.diag(dm) @ Vt
    B0 = A0 @ R.T
    ur = R @ (u / max(np.linalg.norm(u), 1e-12))
    pa, qa = B0 @ ur, A1 @ ur
    pp, qp = B0 - pa[:, None] * ur, A1 - qa[:, None] * ur
    sa = min(max(float((w * pa * qa).sum() / max((w * pa * pa).sum(), 1e-12)), 0.5), 2.0)
    sp_ = min(max(float((w * (pp * qp).sum(1)).sum() / max((w * (pp * pp).sum(1)).sum(), 1e-12)), 0.5), 2.0)
    Lin = (sp_ * np.eye(3) + (sa - sp_) * np.outer(ur, ur)) @ R
    M = np.eye(4)
    M[:3, :3] = Lin
    M[:3, 3] = c1 - Lin @ c0
    return M


def register_joints(tpl, Vs, Ws, anc, Vt, n_ctrl=N_CTRL, n_tgt=N_TGT, its=ITS, floor=FLOOR, anchor=ANCHOR):
    """Kaynak (ped oyun mesh'i Vs, SKEL agirliklari Ws) -> hedef Vt. Donus: ({SKEL kemik adi: tahmini eklem konumu}, bilgi)."""
    skel = [i for i, n in enumerate(tpl.names) if n.startswith("SKEL_")]
    col = {b: k for k, b in enumerate(skel)}
    lo_s, hi_s, lo_t, hi_t = Vs.min(0), Vs.max(0), Vt.min(0), Vt.max(0)
    sc = (hi_t - lo_t) / np.maximum(hi_s - lo_s, 1e-6)
    ids = fps(Vs, n_ctrl)
    S0 = lo_t + (Vs[ids] - lo_s) * sc
    Wc = Ws[ids][:, skel]
    Wc = Wc / np.maximum(Wc.sum(1, keepdims=True), 1e-12)
    J0 = lo_t + (tpl.W[skel, :3, 3] - lo_s) * sc
    par = np.array([col[int(anc[tpl.parents[b]])] if tpl.parents[b] >= 0 and int(anc[tpl.parents[b]]) in col else -1 for b in skel])
    size = np.ones(len(tpl.names), int)
    for i in reversed(tpl.order):
        if tpl.parents[i] >= 0:
            size[tpl.parents[i]] += size[i]
    child = np.full(len(skel), -1)
    for k, b in enumerate(skel):
        kids = [c for c in tpl.children[b] if c in col]
        if kids:
            child[k] = col[max(kids, key=lambda c: size[c])]
    axis = np.array([J0[child[k]] - J0[k] if child[k] >= 0 else (J0[k] - J0[par[k]] if par[k] >= 0 else np.array([0, 1.0, 0]))
                     for k in range(len(skel))])
    T = Vt[fps(Vt, n_tgt)]
    kT = GridKNN(T)
    band = (S0[:, 2] <= lo_t[2] + 0.02 * (hi_t[2] - lo_t[2])).astype(float) * floor
    M = np.repeat(np.eye(4)[None], len(skel), 0)
    P = J0.copy()
    S = S0.copy()
    name_col = {tpl.names[b]: k for b, k in col.items()}
    stages = [[list(range(len(skel)))], [[name_col[n] for n in g if n in name_col] for g in GROUPS.values()],
              [[k] for k in range(len(skel))]]
    for stage, parts in enumerate(stages):
        for _ in range(its[stage]):
            _, i = kT.query(S, 1)
            fwd = T[i[:, 0]] - S
            dn = np.linalg.norm(fwd, axis=1)
            w = (dn <= 3 * np.median(dn) + 1e-9).astype(float)
            _, j = GridKNN(S).query(T, 1)
            j = j[:, 0]
            bwd = np.zeros_like(S)
            cnt = np.zeros(len(S))
            np.add.at(bwd, j, T - S[j])
            np.add.at(cnt, j, 1.0)
            num = fwd * w[:, None] + bwd
            den = w + cnt
            Q = S + num / np.maximum(den, 1e-12)[:, None]
            if floor:
                Q[:, 2] = S[:, 2] + (num[:, 2] + band * (lo_t[2] - S[:, 2])) / np.maximum(den + band, 1e-12)
            conf = den + band
            for part in parts:
                om = conf * Wc[:, part].sum(1)
                if om.sum() < 1e-6:
                    continue
                X0, X1, ww = S0, Q, om
                if anchor and stage > 0:
                    ends = sorted(set(part) | {int(child[k]) for k in part if child[k] >= 0})
                    aw = np.full(len(ends), anchor * om.sum() / max(len(ends), 1))
                    X0, X1, ww = np.vstack([S0, J0[ends]]), np.vstack([Q, P[ends]]), np.r_[om, aw]
                M[part] = _bone_fit(X0, X1, ww, axis[part[0]]) if stage == 2 else _similarity(X0, X1, ww)
            pred = np.einsum("kij,kj->ki", M[:, :3, :3], J0) + M[:, :3, 3]
            predp = np.array([M[par[k], :3, :3] @ J0[k] + M[par[k], :3, 3] if par[k] >= 0 else pred[k] for k in range(len(skel))])
            P = 0.5 * (pred + predp)
            S = np.einsum("nb,bij,nj->ni", Wc, M[:, :3, :3], S0) + Wc @ M[:, :3, 3]
    res, _ = kT.query(S, 1)
    info = dict(surface_residual_median=float(np.median(res[:, 0])), n_ctrl=len(ids), n_target=len(T))
    return {tpl.names[b]: P[k] for k, b in enumerate(skel)}, info


def symmetrize(markers, lo, hi, lat=LAT):
    """Sol / sag markerlari hedef kutu merkez planina gore ortalar; orta hat markerlari o plana konur."""
    c = 0.5 * (lo[lat] + hi[lat])
    out = {k: np.array(v, float) for k, v in markers.items()}
    for k in list(out):
        if k.startswith("L_") and "R_" + k[2:] in out:
            r = out["R_" + k[2:]].copy()
            r[lat] = 2 * c - r[lat]
            avg = 0.5 * (out[k] + r)
            out[k] = avg
            m = avg.copy()
            m[lat] = 2 * c - m[lat]
            out["R_" + k[2:]] = m
        elif not k.startswith(("L_", "R_")):
            out[k][lat] = c
    return out


def auto_markers(tpl, ref_V, ref_WI, ref_WV, V, direct=QUAD_DIRECT):
    """Hayvan Auto Markers: ped'in kendi oyun mesh'i (ref_V + top-k agirlik, tpl indeksli) -> kullanici mesh'i V (dunya, -Y'ye bakar).
    Donus: ({marker anahtari: konum}, bilgi)."""
    Ws, anc = skel_weights(tpl, np.asarray(ref_WI, np.int64), np.asarray(ref_WV, float))
    joints, info = register_joints(tpl, np.asarray(ref_V, float), Ws, anc, np.asarray(V, float))
    mk = {k: joints[b] for k, b in direct.items() if b in joints}
    V = np.asarray(V, float)
    return symmetrize(mk, V.min(0), V.max(0)), info
