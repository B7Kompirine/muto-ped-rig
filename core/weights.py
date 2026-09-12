"""Otomatik agirlik: voxel-geodezik mesafe + eklem-oranli yumusak dusus + mesh duzeltme + roll bolme + GTA kurallari.

Mesafe (Dionne & de Lasa 2013 "geodesic voxel binding" fikri):
    d = alpha * d_geo + (1 - alpha) * d_oklid
Dusus en yakin kemige GORE oranla: r = d / d_min ; w = clamp(1 - (r-1)/(k-1), 0, 1)^2
  -> uzuv ortasi tek kemik (rijit), eklemde iki kemik esit; karisim bolgesi uzuv yaricapiyla olceklenir.

GTA kurallari (atlas /ped retarget §7, 7541 vertex olcumu): vertex basina <=4 kemik, toplam tam 1.0,
agirliksiz vertex yok, 1/255 adim.
"""
import numpy as np
from .fit import PRIMARY
from . import voxel as vx

EXCLUDE_DEFORM = {"SKEL_ROOT", "SKEL_Spine_Root"}   # vanilla'da 0 vertex

# Roll kemigi bolme profilleri — vanilla mp_m + mp_f ortalamasi (tests: rb_profil olcumu, 2026-09-11)
# (rb, skel, segment_bas, segment_son, [(t, rb_orani), ...])
def _roll_splits():
    out = []
    for s in ("L", "R"):
        out.append((f"RB_{s}_ArmRoll", f"SKEL_{s}_UpperArm", f"SKEL_{s}_UpperArm", f"SKEL_{s}_Forearm",
                    [(0.2, 1.0), (0.5, 0.6), (0.8, 0.25), (1.0, 0.0)]))
        out.append((f"RB_{s}_ForeArmRoll", f"SKEL_{s}_Forearm", f"SKEL_{s}_Forearm", f"SKEL_{s}_Hand",
                    [(0.1, 0.0), (0.3, 0.25), (0.5, 0.55), (0.7, 0.85), (0.9, 1.0)]))
        out.append((f"RB_{s}_ThighRoll", f"SKEL_{s}_Thigh", f"SKEL_{s}_Thigh", f"SKEL_{s}_Calf",
                    [(0.2, 1.0), (0.4, 0.72), (0.5, 0.38), (0.7, 0.08), (0.8, 0.0)]))
    out.append(("RB_Neck_1", "SKEL_Neck_1", "SKEL_Neck_1", "SKEL_Head", [(0.0, 0.4), (1.0, 0.4)]))
    return out


ROLL_SPLITS = _roll_splits()


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def default_deform(skel):
    return [n for n in skel.names if n.startswith("SKEL_") and n not in EXCLUDE_DEFORM]


def bone_segments(skel, names, tips=None):
    """Her deform kemigi icin (bas, son) dunya noktalari."""
    tips = tips or {}
    P = skel.pos
    I = skel.index
    segs = {}
    for n in names:
        b = I[n]
        a = P[b]
        c = PRIMARY.get(n)
        if n in tips:
            e = np.asarray(tips[n], float)
        elif c and c in I:
            e = P[I[c]]
        elif n == "SKEL_Pelvis":
            e = 0.5 * (P[I["SKEL_L_Thigh"]] + P[I["SKEL_R_Thigh"]])
        elif n == "SKEL_Head":
            neck = P[I["SKEL_Neck_1"]]
            e = a + unit(a - neck) * 1.3 * np.linalg.norm(a - neck)
        else:  # yaprak: ebeveyn yonunde, ebeveyn boyunun 0.75'i
            par = P[skel.parents[b]]
            e = a + (a - par) * 0.75
        segs[n] = (a, e)
    return segs


def point_segment(X, a, b):
    ab = b - a
    L2 = float(ab @ ab)
    t = np.clip(((X - a) @ ab) / L2, 0.0, 1.0) if L2 > 1e-12 else np.zeros(len(X))
    return np.linalg.norm(X - (a + t[:, None] * ab), axis=1), t


def mesh_edges(F):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.sort(e, axis=1)
    return np.unique(e, axis=0)


def load_radii(names, scale=1.0, path=None):
    """Kemik basina govde yaricapi (vanilla olcumu x olcek). Olculmeyen kemik: ebeveyn zinciri ortalamasi yerine 0.03."""
    import json, os
    path = path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "bone_radii.json")
    with open(path, encoding="utf-8") as fh:
        rad = json.load(fh)["radius"]
    return np.array([rad[n]["r50"] if n in rad else 0.03 for n in names], np.float32) * scale


def plausibility(W, names, V, skel, radii, k0=2.2, k1=3.4):
    """Kemik yaricapinin k0..k1 katindan uzak vertexte o kemigin agirligi soner.
    Vanilla GT: w>0.2 vertexlerde d/r50 %99 = 1.9-2.0, klavikula/basparmak %99 2.6 -> k0 2.2.
    Koltuk alti tuzagi: govde yanindaki vertex kola 11 cm, kol yaricapi 4 cm -> kol agirligi alamaz."""
    segs = bone_segments(skel, names)
    F = np.ones_like(W)
    for j, n in enumerate(names):
        if not W[:, j].any():
            continue
        a, e = segs[n]
        d, _ = point_segment(V, a, e)
        F[:, j] = np.clip(1.0 - (d / radii[j] - k0) / (k1 - k0), 0.0, 1.0) ** 2
    Wn = W * F
    s = Wn.sum(1, keepdims=True)
    keep = s[:, 0] < 1e-6                       # tum kemiklerden uzak (zirh vb.): dokunma
    Wn = np.where(keep[:, None], W, Wn / np.maximum(s, 1e-12))
    return Wn


def graph_fill(W, conf, edges, thresh=0.5, iters=80):
    """Guveni dusuk vertexler agirligi MESH YUZEYI boyunca guvenilir komsulardan alir (harmonik doldurma).
    Oklid komsulugu sirt vertexine bel agirligi tasidi (olculdu); yuzey baglantisi tasimaz."""
    fixed = conf >= thresh
    if fixed.all() or len(edges) == 0:
        return W
    active = np.nonzero(W.any(0))[0]
    X = W[:, active].copy()
    n = len(W)
    deg = np.bincount(edges.ravel(), minlength=n).astype(np.float64)
    free = (~fixed) & (deg > 0)
    for _ in range(iters):
        acc = np.zeros_like(X)
        np.add.at(acc, edges[:, 0], X[edges[:, 1]])
        np.add.at(acc, edges[:, 1], X[edges[:, 0]])
        X[free] = acc[free] / deg[free, None]
    t = np.clip(conf / thresh, 0.0, 1.0)[:, None]
    out = W.copy()
    out[:, active] = t * W[:, active] + (1 - t) * X
    s = out.sum(1, keepdims=True)
    return out / np.maximum(s, 1e-12)


def smooth_weights(W, edges, iters=4, lam=0.5):
    if iters <= 0 or len(edges) == 0:
        return W
    n = len(W)
    deg = np.bincount(edges.ravel(), minlength=n).astype(np.float32)
    has = deg > 0
    for _ in range(iters):
        acc = np.zeros_like(W)
        np.add.at(acc, edges[:, 0], W[edges[:, 1]])
        np.add.at(acc, edges[:, 1], W[edges[:, 0]])
        avg = np.where(has[:, None], acc / np.maximum(deg, 1)[:, None], W)
        W = (1 - lam) * W + lam * avg
    return W


def topk_normalize(W, k=4):
    if W.shape[1] > k:
        idx = np.argpartition(-W, k - 1, axis=1)[:, :k]
        val = np.take_along_axis(W, idx, 1)
        W = np.zeros_like(W)
        np.put_along_axis(W, idx, val, 1)
    s = W.sum(1, keepdims=True)
    return np.where(s > 0, W / np.maximum(s, 1e-12), W)


def gta_rules(W, k=4):
    """Yogun (N,B) -> (idx (N,k), val (N,k)); <=k etki, 1/255 adim, toplam tam 255/255, bos vertex yok."""
    n, B = W.shape
    k = min(k, B)
    idx = np.argsort(-W, axis=1)[:, :k]
    val = np.take_along_axis(W, idx, 1).astype(np.float64)
    val[val < 0.5 / 255] = 0.0
    s = val.sum(1, keepdims=True)
    empty = s[:, 0] <= 0
    val = np.where(s > 0, val / np.maximum(s, 1e-12), 0.0)
    val[empty, 0] = 1.0                                  # bos vertex: en guclu adaya tam agirlik
    q = np.rint(val * 255).astype(np.int64)
    q[np.arange(n), 0] += 255 - q.sum(1)                 # toplam tam 255
    bad = q[:, 0] < q[:, 1:].max(1) if k > 1 else np.zeros(n, bool)
    if bad.any():                                       # yuvarlama sirayi bozduysa yeniden sirala
        o = np.argsort(-q[bad], axis=1)
        q[bad] = np.take_along_axis(q[bad], o, 1)
        idx[bad] = np.take_along_axis(idx[bad], o, 1)
    return idx, q / 255.0


def _interp_profile(t, knots):
    ts = np.array([k[0] for k in knots]); rs = np.array([k[1] for k in knots])
    return np.interp(t, ts, rs)


def apply_roll_splits(W, names, skel, V):
    """SKEL agirliginin bir kismini vanilla profiline gore RB_ kemigine aktarir. Yeni sutunlar eklenir."""
    names = list(names)
    cols = {n: j for j, n in enumerate(names)}
    extra = []
    for rb, sk, a_n, b_n, knots in ROLL_SPLITS:
        if sk in cols and rb in skel.index and rb not in cols:
            extra.append(rb)
    if not extra:
        return W, names
    W = np.concatenate([W, np.zeros((len(W), len(extra)), W.dtype)], axis=1)
    for rb in extra:
        cols[rb] = len(names)
        names.append(rb)
    P = skel.pos
    for rb, sk, a_n, b_n, knots in ROLL_SPLITS:
        if rb not in cols or sk not in cols:
            continue
        j, jr = cols[sk], cols[rb]
        m = W[:, j] > 0
        if not m.any():
            continue
        a, b = P[skel.index[a_n]], P[skel.index[b_n]]
        ab = b - a
        t = ((V[m] - a) @ ab) / max(float(ab @ ab), 1e-12)
        r = _interp_profile(t, knots)
        moved = W[m, j] * r
        W[m, jr] += moved
        W[m, j] -= moved
    return W, names


def compute_distances(V, F, skel, deform=None, h=None, tips=None, log=print):
    """Pahali kisim (voxel + geodezik). Parametre taramasi icin bir kez hesaplanir."""
    import time
    T0 = time.time()
    # Ayni konumdaki vertexler AYNI agirligi almali (aksi halde UV dikisinde mesh yirtilir):
    # tum hesap birlesik mesh'te yapilir, sonda orijinal indekslere acilir.
    n_orig = len(V)
    V, F, inv = vx.weld(V, F)
    names = list(deform or default_deform(skel))
    segs = bone_segments(skel, names, tips)
    height = float(np.ptp(V[:, 2]))
    scale = height / 1.82
    h = h or max(height / 160.0, 0.004)
    seg_pts = np.array([p for ab in segs.values() for p in ab])
    grid = vx.Grid.around(np.vstack([V, seg_pts]), h)
    comp = vx.mesh_components(len(V), F)
    solid, surf = vx.solid_volume(grid, V, F, comp)
    vox = grid.index(V)
    log(f"  voxel h={h*1000:.1f}mm dims={tuple(int(x) for x in grid.dims)} kati={int(solid.sum())} bilesen={comp.max()+1} ({time.time()-T0:.1f}s)")
    N, nb = len(V), len(names)
    Deuc = np.empty((N, nb), np.float32)
    Dgeo = np.full((N, nb), np.inf, np.float32)
    T1 = time.time()
    for j, n in enumerate(names):
        a, e = segs[n]
        de, _ = point_segment(V, a, e)
        Deuc[:, j] = de
        L = float(np.linalg.norm(e - a))
        max_dist = max(0.30 * scale, 2.5 * L)
        D, i0 = vx.geodesic_from_segment(grid, solid, a, e, max_dist)
        Dgeo[:, j] = vx.sample_window(D, i0, vox) + 0.5 * h
    log(f"  geodezik {nb} kemik ({time.time()-T1:.1f}s), birlesik vertex {N}/{n_orig}")
    return dict(names=names, V=V, F=F, inv=inv, comp=comp, edges=mesh_edges(F),
                Deuc=Deuc, Dgeo=Dgeo, h=h, scale=scale, segs=segs)


def compute_weights(V, F, skel, deform=None, h=None, tips=None, log=print, **kw):
    """V (N,3) P pozunda mesh, skel = P iskeleti. Donus: (names, W yogun (N,B) toplam 1)."""
    D = compute_distances(V, F, skel, deform, h, tips, log)
    return weights_from_distances(D, skel, log=log, **kw)


def weights_from_distances(D, skel, alpha=0.8, ratio_k=2.0, power=2.0, smooth_iters=4,
                           rigid_diam=0.0, roll_split=True, radius_norm=False, log=print):
    names = list(D["names"])
    V, comp, inv, Deuc, Dgeo = D["V"], D["comp"], D["inv"], D["Deuc"], D["Dgeo"]
    nb = len(names)
    if alpha <= 0:
        Dc = Deuc.copy()
    else:  # 0*inf = NaN tuzagi: erisilmeyen kemik inf kalir
        Dc = np.where(np.isinf(Dgeo), np.inf, alpha * Dgeo + (1 - alpha) * Deuc).astype(np.float32)
    if radius_norm:  # genis govde kemikleri ince uzuvlara ham mesafede hep kaybeder -> yaricapa oranla
        Dc = Dc / load_radii(names, D["scale"])[None, :]
    unreached = np.isinf(Dc).all(1)
    if unreached.any():                                  # hacim disi kalan parca: oklide dus
        Dc[unreached] = Deuc[unreached]
    dmin = np.maximum(Dc.min(1, keepdims=True), 1e-4)
    r = Dc / dmin
    W = np.clip(1.0 - (r - 1.0) / (ratio_k - 1.0), 0.0, 1.0) ** power
    W[~np.isfinite(W)] = 0.0
    W = topk_normalize(W, 4)
    W = smooth_weights(W, D["edges"], smooth_iters)
    if rigid_diam > 0:
        ncomp = comp.max() + 1
        lo = np.full((ncomp, 3), np.inf); hi = np.full((ncomp, 3), -np.inf)
        np.minimum.at(lo, comp, V); np.maximum.at(hi, comp, V)
        diam = np.linalg.norm(hi - lo, axis=1)
        small = diam[comp] < rigid_diam
        if small.any():
            acc = np.zeros((ncomp, nb))
            np.add.at(acc, comp[small], W[small])
            best = acc.argmax(1)
            W[small] = 0.0
            W[np.nonzero(small)[0], best[comp[small]]] = 1.0
    W = topk_normalize(W, 4)
    if roll_split:
        W, names = apply_roll_splits(W, names, skel, V)
    if unreached.any():
        log(f"  hacim disi (oklide dusen) vertex: {int(unreached.sum())}")
    return names, W[inv]
