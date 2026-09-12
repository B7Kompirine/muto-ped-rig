"""Tam (exact) k-en-yakin komsu — saf numpy izgara. Blender'da scipy yok; mathutils KDTree sorgusu vertex basina
Python cagrisi (olculdu: 6251 vertex x 12 referans = 10.5 s). Bu surum vektorel, parca parca calisir.

Tamlik: sorgunun hucresi etrafinda r hucrelik kup tarandi ise, kup disindaki her nokta sorguya >= r*c uzaktadir.
k'inci aday mesafesi <= r*c ise sonuc kesin; degilse o sorgular r buyutulerek tekrar taranir."""
import os
from concurrent.futures import ThreadPoolExecutor
import numpy as np

WORKERS = min(8, os.cpu_count() or 1)   # nearest parcalari is parcaciklarinda (numpy GIL'i birakir); sonuc parcalamadan bagimsiz; 1 = seri
_POOL = None


def _map(fn, items):
    """fn(item) her parca icin (sonucu kendi dizisine yazar); hata cagirana gecer. Tek parca ya da WORKERS <= 1 -> seri."""
    global _POOL
    items = list(items)
    if WORKERS <= 1 or len(items) <= 1:
        for it in items:
            fn(it)
        return
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=WORKERS)
    for _ in _POOL.map(fn, items):
        pass


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

    def _nearest_r(self, Q, r):
        n = len(Q)
        qi = np.floor((Q - self.lo) / self.c).astype(np.int64)
        rng = np.arange(-r, r + 1)
        off = np.stack(np.meshgrid(rng, rng, rng, indexing="ij"), -1).reshape(-1, 3)
        cells = qi[:, None, :] + off[None, :, :]
        inside = np.all((cells >= 0) & (cells < self.dims), axis=2)
        keys = np.where(inside, self._key(np.clip(cells, 0, self.dims - 1)), -1)
        start = np.searchsorted(self.skey, keys, side="left")
        end = np.searchsorted(self.skey, keys, side="right")
        cnt = np.where(inside, end - start, 0).ravel()
        tot = cnt.reshape(n, -1).sum(1)
        D = np.full(n, np.inf)
        I = np.zeros(n, dtype=np.int64)
        has = tot > 0
        if not has.any():
            return D, I, has
        qrow = np.repeat(np.repeat(np.arange(n), off.shape[0]), cnt)           # sorgu sirasinda gruplu
        st = np.repeat(start.ravel(), cnt)
        csum = np.cumsum(cnt) - cnt
        cand = self.order[st + np.arange(cnt.sum()) - np.repeat(csum, cnt)]
        d2 = np.sum((self.P[cand] - Q[qrow]) ** 2, axis=1)
        tot_h = tot[has]
        mins = np.minimum.reduceat(d2, np.cumsum(tot_h) - tot_h)
        grp = np.repeat(np.arange(len(tot_h)), tot_h)
        hit = np.flatnonzero(d2 == mins[grp])
        _, pos = np.unique(grp[hit], return_index=True)                       # grup basina ilk minimum
        D[has] = np.sqrt(mins)
        I[has] = cand[hit[pos]]
        return D, I, np.isfinite(D) & (D <= r * self.c)

    def _nearest_brute(self, Q, budget=100_000):
        """Kaba kuvvet k=1 (matmul, merkezli koordinat; parca <= budget eleman, parcalar _map ile paralel). Mesafe secilen noktadan
        tam hesaplanir. Yerinde -2M + PP == PP - 2M (IEEE: 2 ile carpma ve isaret degistirme tam) -> eski yolla ayni sonuc.
        Olculdu (michelle kafa taramasi, 2293 nokta x 24k sorgu): 2M parca seri 1,53 s -> 100k parca 8 is parcacigi 0,14 s, mesafe ve
        secilen nokta birebir (Auto Markers'in %87-90'i bu cagri: xbot el, michelle yuz profili)."""
        if not hasattr(self, "_Pc"):
            self._Pc = self.P - self.lo
            self._PP = np.einsum("ij,ij->i", self._Pc, self._Pc)
        D = np.empty(len(Q))
        I = np.empty(len(Q), dtype=np.int64)
        ch = max(64, int(budget // max(len(self.P), 1)))

        def job(a):
            q = Q[a:a + ch] - self.lo
            M = q @ self._Pc.T
            M *= -2.0
            M += self._PP
            j = np.argmin(M, axis=1)
            I[a:a + ch] = j
            D[a:a + ch] = np.linalg.norm(self._Pc[j] - q, axis=1)
        _map(job, range(0, len(Q), ch))
        return D, I

    def nearest(self, Q, chunk=1024, max_r=64, brute=5e7, brute_p=4096):
        """k=1 hizli yol (ICP): query(Q, 1) ile ayni tam sonuc, lexsort yerine grup-ici minimum. -> (D (n,), I (n,))
        Nokta kumesi <= brute_p ise dogrudan kaba kuvvet (olculdu: el bolgesi 1509 nokta, 165 aday x 300 sorgu: izgara 14,8 s'nin 13,8'i);
        r=1 halkasinda bulunamayan (uzak) sorgular: kalan x nokta sayisi <= brute ise kaba kuvvet — halka buyutmekten ucuz."""
        Q = np.asarray(Q, dtype=np.float64)
        if len(self.P) <= brute_p:
            return self._nearest_brute(Q)
        D = np.full(len(Q), np.inf)
        I = np.zeros(len(Q), dtype=np.int64)
        todo = np.arange(len(Q))
        r = 1
        while len(todo) and r <= max_r:
            if r > 2 or (r > 1 and len(todo) * len(self.P) <= brute):
                break                     # uzak kalanlar kaba kuvvete (olculdu: 9000 nokta, 20 cm uzak 20k sorgu, halka r=64'e: 196 s)
            ch = max(16, int(chunk * 27 / (2 * r + 1) ** 3))
            starts = list(range(0, len(todo), ch))
            nxt = [None] * len(starts)

            def job(k, todo=todo, ch=ch, r=r, starts=starts, nxt=nxt):      # sorgu basina sonuc parcadan bagimsiz -> paralel
                idx = todo[starts[k]:starts[k] + ch]
                d, i, ok = self._nearest_r(Q[idx], r)
                D[idx[ok]] = d[ok]
                I[idx[ok]] = i[ok]
                nxt[k] = idx[~ok]
            _map(job, range(len(starts)))
            todo = np.concatenate(nxt) if nxt else todo[:0]
            r *= 2
        if len(todo):
            D[todo], I[todo] = self._nearest_brute(Q[todo])
        return D, I
