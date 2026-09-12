"""GTA ped iskeleti — saf numpy.

Konvansiyon: W[b] = kemigin armature uzayindaki 4x4 matrisi (Sollumz'un yazdigi
bone.matrix_local; rotasyon GTA'dan donusumsuz alinir, uzunluk ekseni yerel +X).
Yerel oteleme t[b] = R[parent]^T (p[b] - p[parent]); yerel rotasyon L[b] = R[parent]^T R[b].
"""
import json
import re
import numpy as np

_FB_SUFFIX = re.compile(r"_\d{3}$")


def canon(name):
    """Yuz kemigi ad eki dosyaya gore degisir (.ydd _000, .yft _045, bazi ambient ped _001); tag ayni."""
    if name.startswith("FB_"):
        return _FB_SUFFIX.sub("", name)
    return name


def map_to_canon(ref, canon_skel):
    """ref kemik indeksi -> ortak sablon indeksi. Sablonda olmayan kemik en yakin (sablonda olan) atasina gider."""
    out = np.zeros(len(ref.names), np.int64)
    for i in range(len(ref.names)):
        j = i
        while j >= 0 and ref.names[j] not in canon_skel.index:
            j = ref.parents[j]
        out[i] = canon_skel.index[ref.names[j]] if j >= 0 else canon_skel.index["SKEL_ROOT"]
    return out


def compose(R, p):
    """(B,3,3) + (B,3) -> (B,4,4)"""
    B = len(R)
    W = np.zeros((B, 4, 4))
    W[:, :3, :3] = R
    W[:, :3, 3] = p
    W[:, 3, 3] = 1.0
    return W


class Skeleton:
    def __init__(self, names, parents, W, tags=None, flags=None):
        self.raw_names = list(names)
        self.names = [canon(n) for n in names]
        self.index = {n: i for i, n in enumerate(self.names)}
        self.parents = np.asarray(parents, dtype=np.int64)
        self.W = np.asarray(W, dtype=np.float64).copy()
        # Blender matrix_local float32 gelir; rotasyon tam ortonormal degil (R^T != R^-1, ~1e-6).
        # Polar ayrisimla temizle: sonraki tum yerel/dunya donusumleri tutarli kalir.
        U, _, Vt = np.linalg.svd(self.W[:, :3, :3])
        self.W[:, :3, :3] = U @ Vt
        n = len(self.names)
        self.tags = list(tags) if tags is not None else [0] * n
        self.flags = list(flags) if flags is not None else [[] for _ in range(n)]
        self.children = [[] for _ in range(n)]
        for i, p in enumerate(self.parents):
            if p >= 0:
                self.children[p].append(i)
        self.order = self._topo()

    # --- yukleme -------------------------------------------------------
    @classmethod
    def from_json(cls, path):
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        bones = d["bones"]
        names = [b["name"] for b in bones]
        pos = {n: i for i, n in enumerate(names)}
        parents = [pos[b["parent"]] if b["parent"] else -1 for b in bones]
        W = [b["matrix_local"] for b in bones]
        return cls(names, parents, W, [b["tag"] for b in bones], [b["flags"] for b in bones])

    def _topo(self):
        order, seen = [], set()

        def visit(i):
            if i in seen:
                return
            p = self.parents[i]
            if p >= 0:
                visit(p)
            seen.add(i)
            order.append(i)

        for i in range(len(self.names)):
            visit(i)
        return order

    # --- erisim --------------------------------------------------------
    def i(self, name):
        return self.index[canon(name)]

    @property
    def pos(self):
        return self.W[:, :3, 3]

    @property
    def rot(self):
        return self.W[:, :3, :3]

    def local_t(self):
        t = np.zeros((len(self.names), 3))
        for b in self.order:
            p = self.parents[b]
            t[b] = self.pos[b] if p < 0 else self.rot[p].T @ (self.pos[b] - self.pos[p])
        return t

    def local_R(self):
        L = np.zeros((len(self.names), 3, 3))
        for b in self.order:
            p = self.parents[b]
            L[b] = self.rot[b] if p < 0 else self.rot[p].T @ self.rot[b]
        return L

    def fk(self, t_local, R_local):
        """Yerel oteleme + yerel rotasyondan dunya matrisleri."""
        B = len(self.names)
        R = np.zeros((B, 3, 3))
        p = np.zeros((B, 3))
        for b in self.order:
            q = self.parents[b]
            if q < 0:
                R[b] = R_local[b]
                p[b] = t_local[b]
            else:
                R[b] = R[q] @ R_local[b]
                p[b] = p[q] + R[q] @ t_local[b]
        return compose(R, p)

    def with_W(self, W):
        s = Skeleton(self.raw_names, self.parents, W, self.tags, self.flags)
        return s


def complete_skeleton(ref, target):
    """Baska ped iskeletini (ornek: 98 kemikli ambient) hedef sablonun kemik sirasina ve agacina getir.
    Referansta olmayan kemik: hedef sablonun yerel donusumuyle referans ebeveynine eklenir
    (o kemiklerin referans agirligi zaten 0; yalniz agac butun kalsin diye)."""
    tL, RL = target.local_t(), target.local_R()
    B = len(target.names)
    W = np.zeros((B, 4, 4))
    missing = []
    for b in target.order:
        n = target.names[b]
        if n in ref.index:
            W[b] = ref.W[ref.index[n]]
            continue
        missing.append(n)
        p = target.parents[b]
        L = np.eye(4)
        L[:3, :3] = RL[b]
        L[:3, 3] = tL[b]
        W[b] = (W[p] @ L) if p >= 0 else target.W[b]
    out = target.with_W(W)
    return out, missing


def skin_matrices(W_target, W_bind):
    return W_target @ np.linalg.inv(W_bind)


def lbs(verts, wi, wv, M):
    """Linear blend skinning. verts (N,3), wi/wv (N,K), M (B,4,4)."""
    Mk = M[wi]                                   # (N,K,4,4)
    out = np.einsum("nkij,nj->nki", Mk[..., :3, :3], verts) + Mk[..., :3, 3]
    return (out * wv[..., None]).sum(1)
