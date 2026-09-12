"""Tam (exact) k-en-yakin komsu — saf numpy izgara. Blender'da scipy yok; mathutils KDTree sorgusu vertex basina
Python cagrisi (olculdu: 6251 vertex x 12 referans = 10.5 s). Bu surum vektorel, parca parca calisir.

Tamlik: sorgunun hucresi etrafinda r hucrelik kup tarandi ise, kup disindaki her nokta sorguya >= r*c uzaktadir.
k'inci aday mesafesi <= r*c ise sonuc kesin; degilse o sorgular r buyutulerek tekrar taranir."""
import numpy as np


class GridKNN:
    def __init__(self, points, cell=None, target_per_cell=6.0):
        self.P = np.asarray(points, dtype=np.float64)
        lo, hi = self.P.min(0), self.P.max(0)
        if cell is None:
            vol = float(np.prod(np.maximum(hi - lo, 1e-6)))
            cell = (vol * target_per_cell / max(len(self.P), 1)) ** (1 / 3)
            # yuzey orneklerinde hacim tahmini hucreyi buyuk verir; alan tabanli sinir
            span = np.sort(hi - lo)
            area_cell = np.sqrt(span[1] * span[2] * target_per_cell / max(len(self.P), 1) * 2.0)
            cell = min(cell, max(area_cell, 1e-4))
        self.c = float(cell)
        self.lo = lo
        ijk = np.floor((self.P - lo) / self.c).astype(np.int64)
        self.dims = ijk.max(0) + 1
        key = self._key(ijk)
        self.order = np.argsort(key, kind="stable")
        self.skey = key[self.order]

    def _key(self, ijk):
        return (ijk[..., 0] * self.dims[1] + ijk[..., 1]) * self.dims[2] + ijk[..., 2]

    def _query_r(self, Q, k, r):
        n = len(Q)
        qi = np.floor((Q - self.lo) / self.c).astype(np.int64)
        rng = np.arange(-r, r + 1)
        off = np.stack(np.meshgrid(rng, rng, rng, indexing="ij"), -1).reshape(-1, 3)      # (C,3)
        cells = qi[:, None, :] + off[None, :, :]                                          # (n,C,3)
        inside = np.all((cells >= 0) & (cells < self.dims), axis=2)
        keys = np.where(inside, self._key(np.clip(cells, 0, self.dims - 1)), -1)
        start = np.searchsorted(self.skey, keys, side="left")
        end = np.searchsorted(self.skey, keys, side="right")
        cnt = np.where(inside, end - start, 0)
        tot = cnt.sum(1)                                                                  # (n,)
        qrow = np.repeat(np.repeat(np.arange(n), off.shape[0]), cnt.ravel())
        st = np.repeat(start.ravel(), cnt.ravel())
        csum = np.cumsum(cnt.ravel()) - cnt.ravel()
        local = np.arange(cnt.sum()) - np.repeat(csum, cnt.ravel())
        cand = self.order[st + local]
        d2 = np.sum((self.P[cand] - Q[qrow]) ** 2, axis=1)
        o = np.lexsort((d2, qrow))
        qrow, cand, d2 = qrow[o], cand[o], d2[o]
        first = np.searchsorted(qrow, np.arange(n), side="left")
        rank = np.arange(len(qrow)) - first[qrow]
        keep = rank < k
        D = np.full((n, k), np.inf)
        I = np.zeros((n, k), dtype=np.int64)
        D[qrow[keep], rank[keep]] = np.sqrt(d2[keep])
        I[qrow[keep], rank[keep]] = cand[keep]
        exact = np.isfinite(D[:, -1]) & (D[:, -1] <= r * self.c)
        return D, I, exact

    def query(self, Q, k, chunk=2048, max_r=64):
        Q = np.asarray(Q, dtype=np.float64)
        k = min(k, len(self.P))
        D = np.full((len(Q), k), np.inf)
        I = np.zeros((len(Q), k), dtype=np.int64)
        todo = np.arange(len(Q))
        r = 1
        while len(todo) and r <= max_r:
            nxt = []
            # hucre sayisi (2r+1)^3 buyudukce parcayi kucult (bellek sabit kalsin)
            ch = max(16, int(chunk * 27 / (2 * r + 1) ** 3))
            for a in range(0, len(todo), ch):
                idx = todo[a:a + ch]
                d, i, ok = self._query_r(Q[idx], k, r)
                D[idx[ok]] = d[ok]
                I[idx[ok]] = i[ok]
                nxt.append(idx[~ok])
            todo = np.concatenate(nxt) if nxt else todo[:0]
            r *= 2
        if len(todo):  # cok uzak sorgular: kaba kuvvet
            for q in todo:
                d2 = np.sum((self.P - Q[q]) ** 2, axis=1)
                o = np.argpartition(d2, k - 1)[:k]
                o = o[np.argsort(d2[o])]
                D[q], I[q] = np.sqrt(d2[o]), o
        return D, I
