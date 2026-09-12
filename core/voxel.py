"""Kati voxel hacmi + hacim ici geodezik mesafe — saf numpy.

Neden voxel: AI/Tripo mesh'leri binlerce kopuk parca, acik kenar ve ic ice kabuktan olusur.
Blender'in bone-heat'i bu mesh'lerde "failed to find solution" verir (atlas yaratik-rig, olculdu).
Hacim uzerinden gecen mesafe kopuk parcalari birlestirir, birbirine yakin ama ayri uzuvlari ayirir.

Kati hacim: bilesen basina 3 eksenli isin paritesi + cogunluk oyu, bilesenler OR'lanir.
- Ic ice kabuk (tisort + govde) tek parite ile "disari" cikardi; bilesen basina parite bunu cozer.
- Acik kenar (yaka, kol agzi) bir eksende yanlis sonuc verir; 3 eksen cogunluk oyu duzeltir.
"""
import numpy as np

OFFSETS = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                    if (dx, dy, dz) != (0, 0, 0)], dtype=int)
COSTS = np.linalg.norm(OFFSETS, axis=1)


class Grid:
    """Voxel merkezi = lo + i*h."""

    def __init__(self, lo, h, dims):
        self.lo = np.asarray(lo, float)
        self.h = float(h)
        self.dims = np.asarray(dims, int)

    @classmethod
    def around(cls, pts, h, pad=3):
        lo = pts.min(0) - pad * h
        hi = pts.max(0) + pad * h
        dims = np.ceil((hi - lo) / h).astype(int) + 1
        return cls(lo, h, dims)

    def index(self, P):
        return np.clip(np.floor((P - self.lo) / self.h + 0.5).astype(int), 0, self.dims - 1)

    def center(self, ijk):
        return self.lo + np.asarray(ijk) * self.h


def surface_voxels(grid, V, F, S=None):
    """Ucgenlerin dokundugu voxeller (h/2 araliklı barisentrik ornekleme)."""
    if S is None:
        S = np.zeros(tuple(grid.dims), bool)
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    L = np.max(np.stack([np.linalg.norm(B - A, axis=1), np.linalg.norm(C - B, axis=1),
                         np.linalg.norm(A - C, axis=1)]), axis=0)
    k = np.clip(np.ceil(L / (grid.h * 0.5)).astype(int), 1, 256)
    for kk in np.unique(k):
        sel = np.nonzero(k == kk)[0]
        ii, jj = np.meshgrid(np.arange(kk + 1), np.arange(kk + 1), indexing="ij")
        m = ii + jj <= kk
        u = (ii[m] / kk)[None, :, None]
        v = (jj[m] / kk)[None, :, None]
        for chunk in np.array_split(sel, max(1, len(sel) * len(u[0]) // 400000 + 1)):
            a = A[chunk][:, None, :]
            P = a + u * (B[chunk] - A[chunk])[:, None, :] + v * (C[chunk] - A[chunk])[:, None, :]
            idx = grid.index(P.reshape(-1, 3))
            S[idx[:, 0], idx[:, 1], idx[:, 2]] = True
    return S


def _parity_axis(grid, V, F, axis):
    """Tek eksen boyunca isin paritesiyle icerisi (bool dizi)."""
    dims = grid.dims
    ua, va = [a for a in (0, 1, 2) if a != axis]
    X = (V - grid.lo) / grid.h                       # indeks uzayi
    A, B, C = X[F[:, 0]], X[F[:, 1]], X[F[:, 2]]
    umin = np.ceil(np.minimum(np.minimum(A[:, ua], B[:, ua]), C[:, ua])).astype(int)
    umax = np.floor(np.maximum(np.maximum(A[:, ua], B[:, ua]), C[:, ua])).astype(int)
    vmin = np.ceil(np.minimum(np.minimum(A[:, va], B[:, va]), C[:, va])).astype(int)
    vmax = np.floor(np.maximum(np.maximum(A[:, va], B[:, va]), C[:, va])).astype(int)
    umin = np.maximum(umin, 0); vmin = np.maximum(vmin, 0)
    umax = np.minimum(umax, dims[ua] - 1); vmax = np.minimum(vmax, dims[va] - 1)
    cu = umax - umin + 1
    cv = vmax - vmin + 1
    ok = (cu > 0) & (cv > 0)
    tri = np.nonzero(ok)[0]
    tot = (cu * cv)[ok]
    inside = np.zeros(tuple(dims), bool)
    if tot.sum() == 0:
        return inside
    t = np.repeat(tri, tot)
    starts = np.repeat(np.cumsum(tot) - tot, tot)
    r = np.arange(tot.sum()) - starts
    cur = np.repeat(cu[ok], tot)
    I = np.repeat(umin[ok], tot) + r % cur
    J = np.repeat(vmin[ok], tot) + r // cur
    # kenar/kose uzerinden gecen isin cift sayilmasin: sutun merkezini irrasyonel kaydir
    pu = I + 1.3e-6
    pv = J + 0.7e-6
    x0, y0, x1, y1, x2, y2 = A[t, ua], A[t, va], B[t, ua], B[t, va], C[t, ua], C[t, va]
    den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    good = np.abs(den) > 1e-12
    den = np.where(good, den, 1.0)
    l0 = ((y1 - y2) * (pu - x2) + (x2 - x1) * (pv - y2)) / den
    l1 = ((y2 - y0) * (pu - x2) + (x0 - x2) * (pv - y2)) / den
    l2 = 1.0 - l0 - l1
    hit = good & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
    if not hit.any():
        return inside
    t, I, J = t[hit], I[hit], J[hit]
    w = l0[hit] * A[t, axis] + l1[hit] * B[t, axis] + l2[hit] * C[t, axis]
    col = I.astype(np.int64) * dims[va] + J
    o = np.lexsort((w, col))
    col, w = col[o], w[o]
    n = len(col)
    first = np.r_[True, col[1:] != col[:-1]]
    gstart = np.maximum.accumulate(np.where(first, np.arange(n), 0))
    rank = np.arange(n) - gstart
    has_next = np.r_[col[1:] == col[:-1], False]
    enter = np.nonzero((rank % 2 == 0) & has_next)[0]
    k0 = np.ceil(w[enter]).astype(int)
    k1 = np.floor(w[enter + 1]).astype(int)
    k0 = np.maximum(k0, 0)
    k1 = np.minimum(k1, dims[axis] - 1)
    valid = k1 >= k0
    enter, k0, k1 = enter[valid], k0[valid], k1[valid]
    if len(enter) == 0:
        return inside
    ci = (col[enter] // dims[va]).astype(int)
    cj = (col[enter] % dims[va]).astype(int)
    shape = list(dims)
    shape[axis] += 1
    D = np.zeros(shape, np.int32)
    for kk, sgn in ((k0, 1), (k1 + 1, -1)):
        idx = [None, None, None]
        idx[axis], idx[ua], idx[va] = kk, ci, cj
        np.add.at(D, tuple(idx), sgn)
    csum = np.cumsum(D, axis=axis)
    sl = [slice(None)] * 3
    sl[axis] = slice(0, dims[axis])
    return csum[tuple(sl)] > 0


def mesh_components(n_verts, F):
    """Baglı bilesen etiketi (vertex basina)."""
    lab = np.arange(n_verts)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    while True:
        m = np.minimum(lab[e[:, 0]], lab[e[:, 1]])
        new = lab.copy()
        np.minimum.at(new, e[:, 0], m)
        np.minimum.at(new, e[:, 1], m)
        new = new[new]                       # isaretci atlama
        if np.array_equal(new, lab):
            break
        lab = new
    _, lab = np.unique(lab, return_inverse=True)
    return lab


def weld(V, F, tol=1e-5):
    """Ayni konumdaki vertexleri birlestir (GTA mesh'i UV dikisinde vertex cogaltir).
    Donus: Vu, Fu (dejenere ucgenler atilmis), inv (orijinal -> birlesik indeks)."""
    key = np.round(V / tol).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = np.asarray(inv).ravel()
    Fu = inv[F]
    keep = (Fu[:, 0] != Fu[:, 1]) & (Fu[:, 1] != Fu[:, 2]) & (Fu[:, 2] != Fu[:, 0])
    return V[first], Fu[keep], inv


def ray_votes(surf):
    """Her voxelden 6 eksen yonunde yuzeye carpan isin sayisi (0..6)."""
    votes = np.zeros(surf.shape, np.int8)
    for ax in range(3):
        votes += np.logical_or.accumulate(surf, axis=ax)
        votes += np.flip(np.logical_or.accumulate(np.flip(surf, ax), axis=ax), ax)
    return votes


def solid_volume(grid, V, F, comp=None, small_tris=200, min_votes=5):
    """Kati hacim = yuzey | (6 isinin >= min_votes'u yuzeye carpar) | (kapali bilesen paritesi & >=3 isin).

    Giysili oyun karakterinde govde ici KAPALI DEGIL (tisort altinda deri yok, yaka/bel acik) ->
    saf parite bos cikar (olculdu: Spine2/uyluk 'disarida'). Isin oyu kucuk aciklıga dayanikli:
    bir yon aciklıktan kacsa bile digerleri yuzeye carpar. V/F BIRLESIK (weld) verilmeli."""
    if comp is None:
        comp = mesh_components(len(V), F)
    surf = surface_voxels(grid, V, F)
    votes = ray_votes(surf)
    solid = surf | (votes >= min_votes)
    tri_comp = comp[F[:, 0]]
    counts = np.bincount(tri_comp)
    big = np.nonzero(counts >= small_tris)[0]
    groups = [np.nonzero(tri_comp == c)[0] for c in big]
    small = np.nonzero(np.isin(tri_comp, big, invert=True))[0]
    if len(small):
        groups.append(small)                 # kucuk parcalar nadiren ic ice, tek grupta
    par = np.zeros(tuple(grid.dims), bool)
    for g in groups:
        pv = np.zeros(tuple(grid.dims), np.int8)
        for ax in (0, 1, 2):
            pv += _parity_axis(grid, V, F[g], ax)
        par |= pv >= 2
    solid |= par & (votes >= 3)
    return solid, surf


def segment_voxels(grid, a, b):
    n = max(2, int(np.ceil(np.linalg.norm(b - a) / (grid.h * 0.5))) + 1)
    P = a[None, :] + np.linspace(0, 1, n)[:, None] * (b - a)[None, :]
    return np.unique(grid.index(P), axis=0)


def geodesic_from_segment(grid, solid, a, b, max_dist, snap_steps=3):
    """Kemik parcasindan kati hacim icinde geodezik mesafe (pencereli Jacobi gevsetmesi).
    Donus: (dist dizisi float32 pencere, pencere alt siniri ijk) — erisilmeyen inf."""
    h = grid.h
    lo_w = np.minimum(a, b) - max_dist
    hi_w = np.maximum(a, b) + max_dist
    i0 = np.clip(np.floor((lo_w - grid.lo) / h).astype(int), 0, grid.dims - 1)
    i1 = np.clip(np.ceil((hi_w - grid.lo) / h).astype(int), 0, grid.dims - 1) + 1
    sub = solid[i0[0]:i1[0], i0[1]:i1[1], i0[2]:i1[2]]
    seeds = segment_voxels(grid, a, b) - i0
    inb = np.all((seeds >= 0) & (seeds < np.array(sub.shape)), axis=1)
    seeds = seeds[inb]
    D = np.full(sub.shape, np.inf, np.float32)
    D[seeds[:, 0], seeds[:, 1], seeds[:, 2]] = 0.0
    passable = sub.copy()
    passable[seeds[:, 0], seeds[:, 1], seeds[:, 2]] = True
    # kemik mesh disinda kalmissa: tohumdan kati hacme birkac adim serbest gecis
    free = np.zeros_like(passable)
    free[seeds[:, 0], seeds[:, 1], seeds[:, 2]] = True
    for _ in range(snap_steps):
        g = free.copy()
        _dilate_into(g, free)
        free = g
    passable |= free
    costs = (COSTS * h).astype(np.float32)
    nx, ny, nz = D.shape
    iters = int(max_dist / h * 1.5) + 4
    for _ in range(iters):
        Dn = D.copy()
        for (dx, dy, dz), c in zip(OFFSETS, costs):
            tx = slice(max(dx, 0), nx + min(dx, 0)); sx = slice(max(-dx, 0), nx + min(-dx, 0))
            ty = slice(max(dy, 0), ny + min(dy, 0)); sy = slice(max(-dy, 0), ny + min(-dy, 0))
            tz = slice(max(dz, 0), nz + min(dz, 0)); sz = slice(max(-dz, 0), nz + min(-dz, 0))
            np.minimum(Dn[tx, ty, tz], D[sx, sy, sz] + c, out=Dn[tx, ty, tz])
        Dn[~passable] = np.inf
        Dn[Dn > max_dist] = np.inf
        changed = bool((Dn < D).any())
        D = Dn
        if not changed:
            break
    return D, i0


def _dilate_into(out, m):
    out[1:] |= m[:-1]; out[:-1] |= m[1:]
    out[:, 1:] |= m[:, :-1]; out[:, :-1] |= m[:, 1:]
    out[:, :, 1:] |= m[:, :, :-1]; out[:, :, :-1] |= m[:, :, 1:]


def sample_window(D, i0, ijk):
    """Pencere disi / erisilmeyen -> inf."""
    rel = ijk - i0
    ok = np.all((rel >= 0) & (rel < np.array(D.shape)), axis=1)
    out = np.full(len(ijk), np.inf, np.float32)
    out[ok] = D[rel[ok, 0], rel[ok, 1], rel[ok, 2]]
    return out
