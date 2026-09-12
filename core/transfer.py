"""Referans vanilla govdeden agirlik aktarimi (insan benzeri karakterler icin).

1) Referans govde (vanilla agirlikli) hedef iskelete ESNETILIR: kemik basina afin
   A_b = P_W[b] . diag(olcek_b) . W0[b]^-1  (eklem konumlari birebir oturur, uzuv boyu olceklenir).
2) Hedef vertex -> esnetilmis referans yuzeyindeki AYNI YONE BAKAN en yakin ornekler -> barisentrik agirlik.
3) Referanstan uzak vertex (zirh, boynuz, pelerin): guvenilir komsu vertexlerden yayilir.

Olculen tuzak (2026-09-11): koltuk altinda govde yani ile kol ic yuzu 1-3 cm; en yakin 8 ornegin
hepsi ters yuzlu cikinca mesafeye dusup YANLIS uzvu secti (max 169 mm). Genis arama + yon filtresi.
"""
import numpy as np


def make_knn(points):
    """k-en-yakin: scipy (testler) -> mathutils KDTree (Blender, sorgu basina C cagrisi) -> numpy izgara.
    Olculdu: numpy izgara k=48'de scipy'den 240x yavas (yaricap hucreyi asinca kup katlanir) -> son care."""
    try:
        from scipy.spatial import cKDTree
        tree = cKDTree(points)

        def q(Q, k):
            d, i = tree.query(Q, k)
            return np.asarray(d).reshape(len(Q), k), np.asarray(i).reshape(len(Q), k)
        return q
    except ImportError:
        pass
    try:
        from mathutils.kdtree import KDTree
    except ImportError:
        from .knn import GridKNN
        return GridKNN(points).query
    kd = KDTree(len(points))
    for i, p in enumerate(points):
        kd.insert(p, i)
    kd.balance()

    def query(Q, k):
        D = np.full((len(Q), k), np.inf)
        I = np.zeros((len(Q), k), dtype=np.int64)
        for i, x in enumerate(Q):
            for j, (_, idx, dist) in enumerate(kd.find_n(x, k)):
                D[i, j] = dist
                I[i, j] = idx
        return D, I
    return query


def nearest_surface(Vr, Fr, spacing=0.004):
    """En yakin yuzey noktasi: Blender'da BVHTree.find_nearest (C), disarida yogun ornek + k=1."""
    try:
        from mathutils.bvhtree import BVHTree
        from mathutils import Vector
        bvh = BVHTree.FromPolygons(Vr.tolist(), Fr.tolist(), all_triangles=True)

        def q(Q):
            n = len(Q)
            d = np.full(n, np.inf)
            fi = np.zeros(n, dtype=np.int64)
            pts = np.zeros((n, 3))
            for i, x in enumerate(Q):
                co, _, idx, dist = bvh.find_nearest(Vector(x))
                if idx is not None:
                    d[i], fi[i], pts[i] = dist, idx, co
            return d, fi, pts
        return q
    except ImportError:
        tri, u, v, pts = sample_triangles(Vr, Fr, spacing)
        knn = make_knn(pts)

        def q(Q):
            d, I = knn(Q, 1)
            I = I[:, 0]
            return d[:, 0], tri[I], pts[I]
        return q


def barycentric(p, a, b, c):
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)
    den = np.maximum(d00 * d11 - d01 * d01, 1e-20)
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    return np.clip(np.stack([1 - v - w, v, w], 1), 0, 1)


def transfer_dominant(Vw, Vrd, Fr, WIr, WVr, n_bones, grp, n_groups=5):
    """Oy veren referans icin hafif aktarim: en yakin yuzey noktasinin agirligi -> baskin uzuv, mesafe, top-4.
    Reddedildi (olculdu 2026-09-11, 12 govde LOO): sorguyu normal tersine 1-2 cm iceri kaydirmak koltuk altini duzeltmedi
    (%95 ort 0.94 -> 0.93, max ort 145 -> 147) -> hata oylamada degil."""
    q = nearest_surface(Vrd, Fr)
    d, fi, pts = q(Vw)
    tri = Fr[fi]
    bw = barycentric(pts, Vrd[tri[:, 0]], Vrd[tri[:, 1]], Vrd[tri[:, 2]])
    N = len(Vw)
    W = np.zeros((N, n_bones), np.float32)
    bones = WIr[tri]                                         # (N,3,4)
    vals = (WVr[tri] * bw[..., None]).astype(np.float32)
    rows = np.broadcast_to(np.arange(N)[:, None, None], bones.shape)
    np.add.at(W, (rows.ravel(), bones.ravel()), vals.ravel())
    G = np.stack([W[:, grp == g].sum(1) for g in range(n_groups)], axis=1)
    idx = np.argpartition(-W, 3, axis=1)[:, :4]
    return G.argmax(1).astype(np.int8), d, (idx.astype(np.int32), np.take_along_axis(W, idx, 1))


def face_normals(V, F):
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    a = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.maximum(a, 1e-20), a[:, 0] * 0.5


def vertex_normals(V, F):
    fn, area = face_normals(V, F)
    vn = np.zeros_like(V)
    for c in range(3):
        np.add.at(vn, F[:, c], fn * area[:, None])
    return vn / np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-20)


def sample_triangles(V, F, spacing):
    """Ucgen ustunde ~spacing aralikli barisentrik ornekler. Donus: tri, u, v, noktalar."""
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    L = np.max(np.stack([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1),
                         np.linalg.norm(A - C, axis=1)]), axis=0)
    ks = np.clip(np.ceil(L / spacing).astype(int), 1, 64)
    T, U, W = [], [], []
    for kk in np.unique(ks):
        sel = np.nonzero(ks == kk)[0]
        ii, jj = np.meshgrid(np.arange(kk + 1), np.arange(kk + 1), indexing="ij")
        m = ii + jj <= kk
        u, v = ii[m] / kk, jj[m] / kk
        T.append(np.repeat(sel, len(u)))
        U.append(np.tile(u, len(sel)))
        W.append(np.tile(v, len(sel)))
    tri, u, v = np.concatenate(T), np.concatenate(U), np.concatenate(W)
    pts = A[tri] + u[:, None] * (B[tri] - A[tri]) + v[:, None] * (C[tri] - A[tri])
    return tri, u, v, pts


def deform_reference(Vr, WIr, WVr, W0, P_W, scale):
    """Referans govdeyi hedef iskelete esnet. W0: vanilla dunya (B,4,4), P_W: hedef P, scale: (B,3)."""
    S = np.zeros_like(W0)
    S[:, 0, 0], S[:, 1, 1], S[:, 2, 2], S[:, 3, 3] = scale[:, 0], scale[:, 1], scale[:, 2], 1.0
    A = P_W @ S @ np.linalg.inv(W0)
    Ak = A[WIr]
    out = np.einsum("nkij,nj->nki", Ak[..., :3, :3], Vr) + Ak[..., :3, 3]
    return (out * WVr[..., None]).sum(1)


def transfer_weights(Vt, Ft, Vr, Fr, WIr, WVr, n_bones, spacing=0.004, k=48, cos_min=0.2, band=2.0):
    """Hedef vertex basina yogun agirlik (n_bones) + en yakin gecerli referans mesafesi."""
    tri, u, v, pts = sample_triangles(Vr, Fr, spacing)
    fn_r, _ = face_normals(Vr, Fr)
    nt = vertex_normals(Vt, Ft)
    knn = make_knn(pts)
    d, I = knn(Vt, k)
    T = tri[I]
    cos = (fn_r[T] * nt[:, None, :]).sum(-1)
    valid = cos > cos_min
    none_ok = ~valid.any(1)
    valid[none_ok] = True                      # hic ayni yone bakan yok: mesafeye dus
    dv = np.where(valid, d, np.inf)
    dnear = dv.min(1)
    valid &= dv <= dnear[:, None] * band + spacing  # en yakin gecerli ornegin bandi disini at
    ws = np.where(valid, np.clip(cos, 0.05, 1.0) / (d + spacing), 0.0)
    ws /= np.maximum(ws.sum(1, keepdims=True), 1e-20)
    bw = np.stack([1 - u[I] - v[I], u[I], v[I]], axis=-1)       # (N,k,3)
    corners = Fr[T]                                             # (N,k,3)
    coef = ws[..., None] * bw
    bones = WIr[corners]                                        # (N,k,3,4)
    vals = WVr[corners] * coef[..., None]
    N = len(Vt)
    W = np.zeros((N, n_bones))
    rows = np.broadcast_to(np.arange(N)[:, None, None, None], bones.shape)
    np.add.at(W, (rows.ravel(), bones.ravel()), vals.ravel())
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
    return W, dnear, none_ok


def confidence(dist, scale, near=0.02, far=0.07):
    """Referans yuzeyine yakinlik -> 1, uzak -> 0 (olcekli metre)."""
    n, f = near * scale, far * scale
    return np.clip(1.0 - (dist - n) / (f - n), 0.0, 1.0)


def propagate_from_confident(V, W, conf, thresh=0.5, k=8):
    """Guveni dusuk vertex, guvenilir komsu vertexlerin agirligini (mesafe agirlikli) alir."""
    good = conf >= thresh
    if good.all() or not good.any():
        return W
    knn = make_knn(V[good])
    bad = np.nonzero(~good)[0]
    kk = min(k, int(good.sum()))
    d, I = knn(V[bad], kk)
    gi = np.nonzero(good)[0][I]
    w = 1.0 / (d + 1e-3)
    Wn = (W[gi] * w[..., None]).sum(1) / w.sum(1, keepdims=True)
    t = (conf[bad] / thresh)[:, None]
    out = W.copy()
    out[bad] = t * W[bad] + (1 - t) * Wn
    return out


_LIMB_KEYS = ("Thigh", "Calf", "Foot", "Toe", "UpperArm", "ArmRoll", "Forearm", "ForeArmRoll", "Hand", "Finger",
              "Knee", "Elbow", "CalfBack", "ThighBack")
_CHAINS = {"leg": ("Thigh", "Calf", "Foot", "Toe0"), "arm": ("UpperArm", "Forearm", "Hand", "Finger20")}


def lr_resolve(W, names, V, skel):
    """Ayni vertex hem L hem R uzuv agirligi aliyorsa, uzuv eksenine yakin taraf kalir.
    Olculen tuzak: dizleri degen sisman ped'de orta hattaki ic diz vertexi R bacaga gitti (max 367 mm)."""
    L = [j for j, n in enumerate(names) if "_L_" in n and any(k in n for k in _LIMB_KEYS)]
    R = []
    Lk = []
    for j in L:
        rn = names[j].replace("_L_", "_R_")
        if rn in names:
            Lk.append(j)
            R.append(names.index(rn))
    if not Lk:
        return W
    wl, wr = W[:, Lk].sum(1), W[:, R].sum(1)
    both = np.nonzero((wl > 0) & (wr > 0))[0]
    if len(both) == 0:
        return W
    P = skel.pos
    I = skel.index

    def chain_dist(side):
        best = np.full(len(both), np.inf)
        for chain in _CHAINS.values():
            for a, b in zip(chain[:-1], chain[1:]):
                na, nb = f"SKEL_{side}_{a}", f"SKEL_{side}_{b}"
                if na in I and nb in I:
                    pa, pb = P[I[na]], P[I[nb]]
                    ab = pb - pa
                    t = np.clip(((V[both] - pa) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
                    best = np.minimum(best, np.linalg.norm(V[both] - (pa + t[:, None] * ab), axis=1))
        return best

    keep_left = chain_dist("L") <= chain_dist("R")
    W = W.copy()
    W[np.ix_(both[keep_left], R)] = 0.0
    W[np.ix_(both[~keep_left], Lk)] = 0.0
    s = W.sum(1, keepdims=True)
    return np.where(s > 0, W / np.maximum(s, 1e-12), W)


def skel_parent_map(skel):
    """Her kemik -> anatomik SKEL_ kemigi (RB_ThighRoll -> Thigh; digerleri en yakin SKEL atasi)."""
    out = np.zeros(len(skel.names), dtype=np.int64)
    for b, n in enumerate(skel.names):
        if n.startswith("SKEL_"):
            out[b] = b
            continue
        if n.startswith("RB_") and n.endswith("ThighRoll"):
            out[b] = skel.index[n.replace("RB_", "SKEL_").replace("ThighRoll", "Thigh")]
            continue
        p = skel.parents[b]
        while p >= 0 and not skel.names[p].startswith("SKEL_"):
            p = skel.parents[p]
        out[b] = p if p >= 0 else b
    return out


RADIUS_BONES = ("SKEL_Pelvis", "SKEL_Spine1", "SKEL_Spine2", "SKEL_Spine3", "SKEL_Head",
                "SKEL_L_Thigh", "SKEL_L_Calf", "SKEL_L_Foot", "SKEL_L_UpperArm", "SKEL_L_Forearm", "SKEL_L_Hand",
                "SKEL_R_Thigh", "SKEL_R_Calf", "SKEL_R_Foot", "SKEL_R_UpperArm", "SKEL_R_Forearm", "SKEL_R_Hand",
                "SKEL_L_Clavicle", "SKEL_R_Clavicle")


def measure_radii(V, Wfull, skel, bones=RADIUS_BONES, min_count=12, thresh=0.5):
    """Kemik basina govde yaricapi: anatomik agirligi > thresh olan vertexlerin segment mesafesi medyani."""
    from .weights import bone_segments, point_segment
    pm = skel_parent_map(skel)
    agg = np.zeros((len(V), len(skel.names)))
    np.add.at(agg.T, pm, Wfull.T)
    segs = bone_segments(skel, [b for b in bones if b in skel.index])
    out = {}
    for n, (a, e) in segs.items():
        m = agg[:, skel.index[n]] > thresh
        if m.sum() >= min_count:
            d, _ = point_segment(V[m], a, e)
            out[n] = float(np.median(d))
    return out


def width_factors(r_target, r_ref, skel, lo=0.6, hi=1.8):
    """Referansi hedef kalinligina getiren kemik basina y/z carpani (yardimci kemik SKEL atasindan alir)."""
    f = np.ones(len(skel.names))
    for n in r_target:
        if n in r_ref and r_ref[n] > 1e-4:
            f[skel.index[n]] = np.clip(r_target[n] / r_ref[n], lo, hi)
    # L/R ayna ortalamasi: tek tarafli olcum gurultusu asimetri uretmesin
    for n in r_target:
        if "_L_" in n:
            m = n.replace("_L_", "_R_")
            if m in skel.index:
                i, j = skel.index[n], skel.index[m]
                f[i] = f[j] = 0.5 * (f[i] + f[j])
    pm = skel_parent_map(skel)
    return f[pm]


GROUP_NAMES = ("govde", "kol_L", "kol_R", "bacak_L", "bacak_R")
_ARM = ("UpperArm", "ArmRoll", "Forearm", "ForeArmRoll", "Hand", "Finger", "Elbow")
_LEG = ("Thigh", "Calf", "Foot", "Toe", "Knee")


def bone_groups(names):
    g = np.zeros(len(names), dtype=np.int64)
    for j, n in enumerate(names):
        side = 0 if "_L_" in n else 1 if "_R_" in n else None
        if side is None:
            continue
        if any(k in n for k in _ARM):
            g[j] = 1 + side
        elif any(k in n for k in _LEG):
            g[j] = 3 + side
    return g


def group_votes(W_list, dists, names, sigma):
    """Coklu referans uzuv oylamasi. Donus: P (N,5) uzuv olasiligi, grp (B,) kemik->uzuv, uyum (R,N) bool."""
    grp = bone_groups(names)
    D = np.asarray(dists)
    om = np.exp(-((D - D.min(0)) / sigma) ** 2)          # en yakin govdeye gore yakinlik
    N = W_list[0].shape[0]
    P = np.zeros((N, len(GROUP_NAMES)))
    doms = []
    for r, W in enumerate(W_list):
        G = np.stack([W[:, grp == g].sum(1) for g in range(len(GROUP_NAMES))], axis=1)
        dom = G.argmax(1)
        doms.append(dom)
        P[np.arange(N), dom] += om[r]
    P /= np.maximum(P.sum(1, keepdims=True), 1e-12)
    win = P.argmax(1)
    agree = np.stack([d == win for d in doms])            # (R,N)
    return P, grp, agree, om


def votes_from_doms(doms, dists, sigma, n_groups=len(GROUP_NAMES)):
    """Akis surumu: referans basina yalniz baskin uzuv (R,N) ve mesafe (R,N) saklanir (bellek)."""
    D = np.asarray(dists)
    om = np.exp(-((D - D.min(0)) / sigma) ** 2)
    N = D.shape[1]
    P = np.zeros((N, n_groups))
    for r in range(len(doms)):
        P[np.arange(N), doms[r]] += om[r]
    P /= np.maximum(P.sum(1, keepdims=True), 1e-12)
    agree = np.stack([d == P.argmax(1) for d in doms])
    return P, agree, om


def consensus_from_sparse(sparse, agree, om, n_bones, rows):
    """Yalniz istenen satirlar icin konsensus (seyrek top-k referans agirliklarindan)."""
    W = np.zeros((len(rows), n_bones))
    for r, (idx, val) in enumerate(sparse):
        wr = (om[r, rows] * agree[r, rows])[:, None] * val[rows]
        np.add.at(W, (np.repeat(np.arange(len(rows)), idx.shape[1]), idx[rows].ravel()), wr.ravel())
    return W / np.maximum(W.sum(1, keepdims=True), 1e-12)


def consensus_weights(W_list, agree, om):
    """Cogunluk uzvunda oy veren referanslarin yakinlik agirlikli ortalamasi."""
    wr = om * agree
    W = np.einsum("rn,rnb->nb", wr, np.stack(W_list))
    return W / np.maximum(W.sum(1, keepdims=True), 1e-12)


def smooth_probs(P, edges, lam=0.9, iters=60):
    """Uzuv olasiligini MESH YUZEYI boyunca yay (yeniden baslamali difuzyon: P = (1-lam) P0 + lam komsu_ort).
    Temas bolgesinde (kol gobege dayali) yuzey yakinligi ayirt edemez; ama bel yani vertexi kenarlarla
    govdeye bagli, kola degil -> ince yanlis bant cevresinin uzvuna doner. Etki yaricapi ~ 1/(1-lam) kenar."""
    if len(edges) == 0:
        return P
    n = len(P)
    deg = np.bincount(edges.ravel(), minlength=n).astype(np.float64)
    has = deg > 0
    P0 = P.copy()
    X = P.copy()
    for _ in range(iters):
        acc = np.zeros_like(X)
        np.add.at(acc, edges[:, 0], X[edges[:, 1]])
        np.add.at(acc, edges[:, 1], X[edges[:, 0]])
        avg = np.where(has[:, None], acc / np.maximum(deg, 1)[:, None], X)
        X = (1 - lam) * P0 + lam * avg
    return X / np.maximum(X.sum(1, keepdims=True), 1e-12)


def gate_by_votes(W, P, grp, fallback=None, eps=1e-3):
    """Temel agirligi (freemode referansi) uzuv oyuyla suz: azinlikta kalan uzvun kemikleri soner."""
    Wg = W * P[:, grp]
    s = Wg.sum(1, keepdims=True)
    bad = s[:, 0] < eps
    Wg = Wg / np.maximum(s, 1e-12)
    if fallback is not None and bad.any():
        Wg[bad] = fallback[bad]
    return Wg


def _edge_components(n, e):
    lab = np.arange(n)
    if len(e) == 0:
        return lab
    while True:
        m = np.minimum(lab[e[:, 0]], lab[e[:, 1]])
        new = lab.copy()
        np.minimum.at(new, e[:, 0], m)
        np.minimum.at(new, e[:, 1], m)
        new = new[new]
        if np.array_equal(new, lab):
            return lab
        lab = new


def group_islands(W, edges, grp, mesh_lab, n_groups=len(GROUP_NAMES)):
    """Uzuv etiketi adaciklari: her mesh bileseninde her uzuv grubunun EN BUYUK bagli bolgesi disindaki bolgeler.
    Tuzak (olculdu): sisman govdede kola degen bel yani / koltuk alti gogus yani 'kol' etiketi alir ama yuzey boyunca
    gercek kola ayni etiketle baglanmaz. Donus: bool (N,) sahte adacik vertexi."""
    G = np.stack([W[:, grp == g].sum(1) for g in range(n_groups)], axis=1).argmax(1)
    e = edges[G[edges[:, 0]] == G[edges[:, 1]]]
    _, isl = np.unique(_edge_components(len(W), e), return_inverse=True)
    size = np.bincount(isl)
    key = np.zeros(len(size), dtype=np.int64)
    key[isl] = mesh_lab * n_groups + G
    order = np.lexsort((-size, key))
    first = np.r_[True, key[order][1:] != key[order][:-1]]
    keep = np.zeros(len(size), bool)
    keep[order[first]] = True
    return ~keep[isl]


def side_clamp(W, names, V, midline_x, margin=0.04):
    """L_ kemigi orta hattin R tarafinda (ve tersi) margin'den oteye agirlik veremez."""
    L = np.array(["_L_" in n for n in names])
    R = np.array(["_R_" in n for n in names])
    W = W.copy()
    far_r = V[:, 0] < midline_x - margin
    far_l = V[:, 0] > midline_x + margin
    W[np.ix_(far_r, L)] = 0.0
    W[np.ix_(far_l, R)] = 0.0
    s = W.sum(1, keepdims=True)
    return np.where(s > 0, W / np.maximum(s, 1e-12), W)
