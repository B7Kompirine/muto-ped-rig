"""Yuz kemigi sablon kaydi: vanilla referans kafa mesh'i (SKEL_Head + FB_/FACIAL_ agirligi > 0,5) hedefin kafa bolgesine benzerlik
ICP (kirpmali, yaw coklu baslangic) ile oturtulur; secilen adaylarda goz L/R ve agiz gruplari kendi yerel yuzey parcasiyla ayrica ICP.
Secim: skor = kalinti x (1 + MU_SCALE |ln s/s0|), referans basina tek yaw, en iyi TOPK adayin eklem ortalamasi (agirlik 1/kalinti^POW).
Freemode <-> ambient yerlesim SOZLESMESI farkli 5 kemik (dudak koseleri, kas ortasi, dis kaslar; atlas dallar/ped/iskelet.md §2) ambient
referanstan TASINMAZ: sablonun (freemode) ortak kemiklerinden ortalanmis eklemlere benzerlik donusumuyle yerlestirilir.
Hiz: tarama TOPLU + ardisik yarilama (handreg._icp_batch; seyreltilmis kaynak/hedef) -> referans basina en iyi REFINE_N aday tum
noktalarla -> yerel grup ICP yalniz son TOPK adayda (secim global kalintiyla yapildigi icin sonuc ayni; olculdu v1 155 s/vaka).
Olcum: tests/an_head_icp.py + tests/an_head_select.py (12 vanilla x 3 poz, kafa ailesi disi, ORTAK 17 kemik: simdiki yol 2,33 cm,
LOBO secim 0,755), uctan uca tests/an_headreg.py. Blender'da scipy yok -> knn.GridKNN.nearest.
"""
import numpy as np
from .knn import GridKNN
from .fit import axis_angle
from .handreg import REFS, _icp, _icp_batch, _umeyama, _voxel_sub

YAW_DEG = (-20.0, -10.0, 0.0, 10.0, 20.0)
ITERS, TRIM = 30, 0.8
REG = 2.0                    # hedef bolge: FACIAL_facialRoot merkezli, REG x |Head -> FB_Brow_Centre| (fit) yaricap (1,6: yuzu keser, 2,48 cm)
LOCAL_CM, LOCAL_ITERS = 5.0, 15
MU_SCALE, TOPK, POW = 5.0, 3, 4.0
SCREEN_PTS, SCREEN_DST = 400, 2500
SCREEN_PLAN = ((8, 0.5), (8, 0.25), (8, 0.0))   # (iterasyon, tutulacak aday orani — tum adaylara gore; 0 = son)
REFINE_N, REFINE_ITERS = 5, 20
RES_GATE_MM = 13.0           # en iyi kafa kalintisi (1,8 m boya olcekli) ustundeyse sablon REDDEDILIR (yuz + head marker degismez):
                             # GTA vanilla 6-10 mm, yabanci insan kafasi 6,7-11,4, xbot robot kafa 16,7-17,5 (PLAN.md 'YUZ KAPISI')
NR_SIGMAS = ()               # bukulebilir inceltme (deneme): gauss RBF sigmalari (m, kabadan inceye); bos = kapali (yerel gruplar calisir)
NR_K, NR_ITERS, NR_LAMBDA = 40, 10, 0.05
GROUPS = (("FB_L_Eye", "FB_L_Lid_Upper", "FB_L_CheekBone", "FB_L_Brow_Out"),
          ("FB_R_Eye", "FB_R_Lid_Upper", "FB_R_CheekBone", "FB_R_Brow_Out"),
          ("FB_UpperLipRoot", "FB_UpperLip", "FB_L_Lip_Top", "FB_R_Lip_Top", "FB_LowerLipRoot", "FB_LowerLip", "FB_L_Lip_Bot",
           "FB_R_Lip_Bot", "FB_L_Lip_Corner", "FB_R_Lip_Corner", "FB_Tongue"))
CONV = ("FB_L_Lip_Corner", "FB_R_Lip_Corner", "FB_Brow_Centre", "FB_L_Brow_Out", "FB_R_Brow_Out")
EXCLUDE = set()              # test (LOO / kafa ailesi): atlanacak referanslar
LAST = {}
_CACHE = {}


def face_names(tpl):
    return [n for n in tpl.names if n.startswith(("FB_", "FACIAL_"))]


def _ref_head(tpl, key):
    """-> dict(P kafa vertexleri, J eklemler (Head + yuz), R/h Head cercevesi, H govde boyu, patches [(indeksler, parca)])."""
    ck = (key, len(tpl.names), LOCAL_CM)
    if ck in _CACHE:
        return _CACHE[ck]
    from .pipeline import load_reference
    Vr, _, WI, WV, rs = load_reference(key, tpl)
    names = ["SKEL_Head"] + face_names(tpl)
    cols = np.array([rs.index[n] for n in names])
    P = np.asarray(Vr[(WV * np.isin(WI, cols)).sum(1) > 0.5], float)
    J = np.array([rs.W[rs.index[n], :3, 3] for n in names])
    patches = []
    for grp in GROUPS:
        gi = [names.index(n) for n in grp if n in names]
        patches.append((gi, P[np.linalg.norm(P - J[gi].mean(0), axis=1) < LOCAL_CM / 100.0]))
    hb = rs.index["SKEL_Head"]
    out = dict(P=P, J=J, R=rs.W[hb, :3, :3], h=rs.W[hb, :3, 3], H=float(np.ptp(Vr[:, 2])), patches=patches)
    _CACHE[ck] = out
    return out


def _fps(P, k):
    idx = [0]
    d = np.linalg.norm(P - P[0], axis=1)
    for _ in range(1, min(k, len(P))):
        j = int(np.argmax(d))
        idx.append(j)
        d = np.minimum(d, np.linalg.norm(P - P[j], axis=1))
    return np.array(idx)


def _nonrigid(X, J, knn, dst, trim):
    """Kaba -> ince gauss RBF yer degistirme alani (kontrol noktalari X'ten FPS, duzenlilestirmeli en kucuk kareler); X hedefe cekilir,
    eklemler ayni alanla tasinir."""
    X, J = X.copy(), J.copy()
    for sig in NR_SIGMAS:
        C = X[_fps(X, NR_K)]
        Phi = np.exp(-np.sum((X[:, None] - C[None]) ** 2, -1) / (2 * sig * sig))
        PhiJ = np.exp(-np.sum((J[:, None] - C[None]) ** 2, -1) / (2 * sig * sig))
        W = np.zeros((len(C), 3))
        for _ in range(NR_ITERS):
            Xc = X + Phi @ W
            d, i = knn.nearest(Xc)
            keep = d <= np.quantile(d, trim)
            A = Phi[keep]
            AtA = A.T @ A
            lam = NR_LAMBDA * np.trace(AtA) / len(C)
            W += np.linalg.solve(AtA + lam * np.eye(len(C)), A.T @ (dst[i[keep]] - Xc[keep]))
        X, J = X + Phi @ W, J + PhiJ @ W
    return J


def _score(res, sr):
    return res * (1.0 + MU_SCALE * np.abs(np.log(np.maximum(sr, 1e-6))))


def head_markers(V, markers, tpl, log=None):
    """markers (govde) -> gecici fit -> kafa sablon kaydi -> {FACIAL_facialRoot, FB_*: konum} ya da {}."""
    from . import markers as mk
    from .fit import fit_skeleton
    try:
        fit = fit_skeleton(tpl, mk.expand_targets(tpl, markers))
    except (ValueError, KeyError):
        return {}
    V = np.asarray(V, float)
    P = lambda n: fit.P_W[tpl.index[n], :3, 3]
    hb = tpl.index["SKEL_Head"]
    hP, Rf = P("SKEL_Head"), fit.P_W[hb, :3, :3]
    rad = REG * float(np.linalg.norm(P("FB_Brow_Centre") - hP))
    near = np.sum((V - P("FACIAL_facialRoot")) ** 2, axis=1) < rad ** 2
    if near.sum() < 100:
        return {}
    dst = V[near]
    knn = GridKNN(dst, cell=0.06 * rad)
    dst_s = dst if len(dst) <= SCREEN_DST else _voxel_sub(dst, SCREEN_DST, 0.01 * rad)
    knn_s = knn if dst_s is dst else GridKNN(dst_s, cell=0.06 * rad)
    Ht = float(np.ptp(V[:, 2]))
    names = ["SKEL_Head"] + face_names(tpl)
    refs = {k: _ref_head(tpl, k) for k in REFS if k not in EXCLUDE}
    items, A, Rs, ts = [], [], [], []
    for key, r in refs.items():
        s0 = Ht / r["H"]
        sub = r["P"][np.linspace(0, len(r["P"]) - 1, SCREEN_PTS).astype(np.int64)]
        for yaw in YAW_DEG:
            R0 = axis_angle([0, 0, 1], np.radians(yaw)) @ Rf @ r["R"].T
            items.append((key, yaw, s0))
            A.append(sub)
            Rs.append(R0)
            ts.append(hP - s0 * R0 @ r["h"])
    if not items:
        return {}
    A, R, t = np.stack(A), np.stack(Rs), np.stack(ts)
    s_ref = np.array([it[2] for it in items])
    s = s_ref.copy()
    act = np.arange(len(items))
    for iters, frac in SCREEN_PLAN:
        s[act], R[act], t[act], res = _icp_batch(A[act], knn_s, dst_s, s[act], R[act], t[act], iters, TRIM, s_ref[act])
        act = act[np.argsort(_score(res, s[act] / s_ref[act]))]
        if frac > 0:
            act = act[:max(REFINE_N * 2, int(np.ceil(frac * len(items))))]
    seen, pick = set(), []                              # referans basina en iyi yaw
    for c in act:
        if items[c][0] not in seen:
            seen.add(items[c][0])
            pick.append(c)
        if len(pick) == REFINE_N:
            break
    fin = []
    for c in pick:
        key, yaw, s0 = items[c]
        r = refs[key]
        s1, R1, t1, r1 = _icp(r["P"], knn, dst, float(s[c]), R[c], t[c], REFINE_ITERS, TRIM)
        fin.append((float(_score(r1, s1 / s0)), r1, key, yaw, s1, R1, t1))
    fin.sort(key=lambda f: f[0])
    if not fin or min(f[1] for f in fin) * (1.8 / max(Ht, 1e-6)) > RES_GATE_MM / 1000.0:
        LAST.clear()
        LAST.update(rejected=True, res_mm=[round(f[1] * 1000, 2) for f in fin[:TOPK]], n_cand=len(items))
        if log:
            log("face template rejected: the head does not match the vanilla GTA heads")
        return {}
    top, Js = fin[:TOPK], []
    for _, r1, key, yaw, s1, R1, t1 in top:
        r = refs[key]
        J = r["J"] * s1 @ R1.T + t1
        if NR_SIGMAS:
            Js.append(_nonrigid(r["P"] * s1 @ R1.T + t1, J, knn, dst, TRIM))
            continue
        for gi, patch in r["patches"]:
            if len(patch) < 40:
                continue
            sl, Rl, tl, _ = _icp(patch, knn, dst, s1, R1, t1, LOCAL_ITERS, TRIM)
            J[gi] = r["J"][gi] * sl @ Rl.T + tl
        Js.append(J)
    w = np.array([1.0 / max(f[1], 1e-6) ** POW for f in top])
    J = sum(wi * Ji for wi, Ji in zip(w, Js)) / w.sum()
    com = [i for i, n in enumerate(names) if n != "SKEL_Head" and n not in CONV]
    conv = [i for i, n in enumerate(names) if n in CONV]
    T = np.array([tpl.W[tpl.index[n], :3, 3] for n in names])
    sc, Rc, tc = _umeyama(T[com], J[com])               # freemode sablonu ortak kemiklerden -> sozlesmeye bagli 5 kemik
    J[conv] = T[conv] * sc @ Rc.T + tc
    LAST.clear()
    LAST.update(ref=[f[2] for f in top], yaw=[f[3] for f in top], res_mm=[round(f[1] * 1000, 2) for f in top], n_cand=len(items))
    if log:
        log(f"face template: {', '.join(LAST['ref'])}")
    return {n: J[i] for i, n in enumerate(names) if n != "SKEL_Head"}
