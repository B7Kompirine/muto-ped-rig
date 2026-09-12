"""Otomatik marker algilama — dik duran, -Y'ye bakan humanoid (A-pose / T-pose).

1) Mesh kati voxel hacme cevrilir (voxel.solid_volume; kopuk parca / acik kenar dayanikli).
2) Govde merkezinden hacim ICI geodezik mesafe; uclar = geodezik YEREL maksimumlar -> kafa, 2 el, 2 ayak.
   (v1 tuzagi: "en uzak noktalar" acgozlu secimi bacak ortasini kafa tepesinden once aldi, kafa 90 cm kaydi.)
3) Her uctan govdeye en dik inis yolu; yol medial eksene (erozyon derinligi sirti) cekilir.
4) Kol: bilek/dirsek yol boyunca; omuz yatay kesitlerden (deltoid dis kenari ya da govde kenari, ust kol acisina gore).
   Bacak: kalca z = kasik kalinlik dususu / kalca arkasi / omuz cizgisi izlerinin ortalamasi; diz bacak-ici oranla;
   kalca x-y kalcanin altindaki uyluk kesit merkezlerinden. Boyun/omuz/kafa z: omuz cizgisinden (boyun en ince
   kesitinin altinda genisligin 1.6 kati astigi katman) — oran degisik karakterde boy oranindan kararli.
Cikti: markers anahtarlari (kullanici duzeltir).
"""
import numpy as np
from . import voxel as vx

N26 = vx.OFFSETS
VANILLA_GROUND_Z = -1.002     # ref_mp_m sinir kutusu (olculdu)
VANILLA_TOP_Z = 0.816


def _shift_extreme(A, fn):
    out = A.copy()
    nx, ny, nz = A.shape
    for dx, dy, dz in N26:
        tx = slice(max(dx, 0), nx + min(dx, 0)); sx = slice(max(-dx, 0), nx + min(-dx, 0))
        ty = slice(max(dy, 0), ny + min(dy, 0)); sy = slice(max(-dy, 0), ny + min(-dy, 0))
        tz = slice(max(dz, 0), nz + min(dz, 0)); sz = slice(max(-dz, 0), nz + min(-dz, 0))
        fn(out[tx, ty, tz], A[sx, sy, sz], out=out[tx, ty, tz])
    return out


def erosion_depth(solid, max_iter=64):
    """Her kati voxel icin yuzeye voxel cinsinden derinlik (6-komsu erozyon sayisi)."""
    dt = np.zeros(solid.shape, np.int16)
    cur = solid.copy()
    for it in range(1, max_iter + 1):
        er = cur.copy()
        er[1:] &= cur[:-1]; er[:-1] &= cur[1:]
        er[:, 1:] &= cur[:, :-1]; er[:, :-1] &= cur[:, 1:]
        er[:, :, 1:] &= cur[:, :, :-1]; er[:, :, :-1] &= cur[:, :, 1:]
        er[0] = er[-1] = False; er[:, 0] = er[:, -1] = False; er[:, :, 0] = er[:, :, -1] = False
        dt[cur & ~er] = it
        cur = er
        if not cur.any():
            break
    dt[cur] = max_iter
    return dt


def geodesic_bfs(solid, seed_ijk, max_steps=4000):
    """Kati hacimde 26-komsu BFS adim sayisi (erisilmeyen -1)."""
    G = np.full(solid.shape, -1, np.int32)
    front = np.zeros(solid.shape, bool)
    front[tuple(seed_ijk)] = True
    G[tuple(seed_ijk)] = 0
    step = 0
    while front.any() and step < max_steps:
        step += 1
        nb = _shift_extreme(front, np.logical_or)
        new = nb & solid & (G < 0)
        G[new] = step
        front = new
    return G


def _descend(G, start):
    path = [np.array(start)]
    cur = np.array(start)
    dims = np.array(G.shape)
    big = np.iinfo(np.int32).max
    for _ in range(4000):
        g0 = G[tuple(cur)]
        if g0 <= 0:
            break
        nb = cur + N26
        ok = np.all((nb >= 0) & (nb < dims), axis=1)
        nb = nb[ok]
        vals = G[nb[:, 0], nb[:, 1], nb[:, 2]]
        vals = np.where(vals < 0, big, vals)
        j = int(np.argmin(vals))
        if vals[j] >= g0:
            break
        cur = nb[j]
        path.append(cur)
    return np.array(path)


def _ridge(path_ijk, dt, radius=2):
    dims = np.array(dt.shape)
    rng = np.arange(-radius, radius + 1)
    off = np.stack(np.meshgrid(rng, rng, rng, indexing="ij"), -1).reshape(-1, 3)
    out = []
    for p in path_ijk:
        nb = p + off
        ok = np.all((nb >= 0) & (nb < dims), axis=1)
        nb = nb[ok]
        d = dt[nb[:, 0], nb[:, 1], nb[:, 2]].astype(float) - 0.01 * np.abs(nb - p).sum(1)
        out.append(nb[int(np.argmax(d))])
    return np.array(out)


def _smooth_polyline(P, iters=6):
    P = P.astype(float).copy()
    for _ in range(iters):
        P[1:-1] = 0.25 * P[:-2] + 0.5 * P[1:-1] + 0.25 * P[2:]
    return P


def _arc(P):
    return np.r_[0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]


def _at_arc(P, s, t):
    return np.array([np.interp(t, s, P[:, k]) for k in range(3)])


def _at_z(P, z, k_from=0):
    """Yol boyunca (k_from'dan sonra) z'ye ilk ulasilan noktanin interpolasyonu."""
    for k in range(max(k_from, 0), len(P) - 1):
        z0, z1 = P[k, 2], P[k + 1, 2]
        if (z0 - z) * (z1 - z) <= 0 and z0 != z1:
            t = (z - z0) / (z1 - z0)
            return P[k] + t * (P[k + 1] - P[k]), k
    k = int(np.argmin(np.abs(P[k_from:, 2] - z))) + k_from
    return P[k], k


def _upper_arm_angle(Pp, k_el, k_sh, frac=0.5):
    """Ust kol dogrusu (yol: dirsekten, dirsek-omuz arasinin frac'i kadar) yataydan kac derece yukari.
    Olculdu (12 govde): gercek 57/35/0 derece -> 52/33/-4.5 (std ~5.5). Yolun omuz ucu govdeye kivrilir -> frac 0.5."""
    e = min(k_el + max(int(frac * (k_sh - k_el)), 2), len(Pp) - 1)
    Q = Pp[k_el:e + 1]
    if len(Q) < 2:
        return 90.0
    d = np.linalg.svd(Q - Q.mean(0))[2][0]
    if d @ (Pp[k_sh] - Pp[k_el]) < 0:
        d = -d
    return float(np.degrees(np.arctan2(d[2], np.hypot(d[0], d[1]))))


def vanilla_ratios(tpl):
    p = lambda n: tpl.pos[tpl.index[n]]
    Hv = VANILLA_TOP_Z - VANILLA_GROUND_Z
    rz = lambda n: (p(n)[2] - VANILLA_GROUND_Z) / Hv
    tip = p("SKEL_L_Finger22") + (p("SKEL_L_Finger22") - p("SKEL_L_Finger21")) * 0.75
    wrist, elbow, shoulder = p("SKEL_L_Hand"), p("SKEL_L_Forearm"), p("SKEL_L_UpperArm")
    segs = [np.linalg.norm(tip - wrist), np.linalg.norm(wrist - elbow), np.linalg.norm(elbow - shoulder)]
    tot = sum(segs)
    f20, f21, f22 = p("SKEL_L_Finger20"), p("SKEL_L_Finger21"), p("SKEL_L_Finger22")
    chain = [np.linalg.norm(tip - f22), np.linalg.norm(f22 - f21), np.linalg.norm(f21 - f20), np.linalg.norm(f20 - wrist)]
    ctot = sum(chain)
    return dict(
        f_tip22=chain[0] / ctot, f_tip21=(chain[0] + chain[1]) / ctot, f_tip20=(chain[0] + chain[1] + chain[2]) / ctot,
        arm_wrist=segs[0] / tot, arm_elbow=(segs[0] + segs[1]) / tot,
        upper_frac=segs[2] / (segs[1] + segs[2]),
        z_toe=rz("SKEL_L_Toe0"), z_ankle=rz("SKEL_L_Foot"), z_knee=rz("SKEL_L_Calf"), z_hip=rz("SKEL_L_Thigh"),
        z_root=rz("SKEL_ROOT"), z_neck=rz("SKEL_Neck_1"), z_head=rz("SKEL_Head"),
        z_shoulder=0.5 * (rz("SKEL_L_UpperArm") + rz("SKEL_R_UpperArm")),
        toe_fwd=0.5,
    )


def orientation_check(V, h_min=0.8, h_max=3.0):
    """Algilamadan once: dik mi, boy metre mi, -Y'ye mi bakiyor. Sessiz basarisizligi onler — sentetik GTA disi govdede
    (2026-09-11) +Y'ye bakan karakterde butun operatorler FINISHED dondu ama L/R yer degistirdi (uzuv uyumu %0, marker 17-113 cm);
    cm biriminde agirlik 3.7 -> 64 s ve export 180 m'lik ped olurdu.
    Yon izi: ayak tabani (z < %3 boy) merkezi - ayak bilegi kesiti (%6-10 boy) merkezi = ayak parmagi yonu.
    Donus: dict(problems=[...], height, heading_deg (0 = -Y), rot_z_deg (90'a yuvarli duzeltme), scale (birim duzeltmesi))."""
    V = np.asarray(V, float)
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    H = float(ext[2])
    out = dict(problems=[], height=H, heading_deg=None, rot_z_deg=0.0, scale=1.0)
    # yatik karakterde boy (z) en uzun yatay kenarin cok altinda (~0.2-0.3). 0.8 esigi uzun kollu T-pose'u reddediyordu
    # (BrainStem robotu, 2026-09-12: x 2.41 / z 1.84 = dik ama "dik durmuyor").
    if ext[2] < 0.5 * max(ext[0], ext[1]):
        out["problems"].append(f"character is not upright (x {ext[0]:.2f}, y {ext[1]:.2f}, z {ext[2]:.2f}); Z must point up")
        return out
    if not h_min <= H <= h_max:
        if 80 <= H <= 300:
            out["scale"] = 0.01
            out["problems"].append(f"height {H:.1f} units — looks like centimeters (GTA peds need meters)")
        elif 800 <= H <= 3000:
            out["scale"] = 0.001
            out["problems"].append(f"height {H:.0f} units — looks like millimeters (GTA peds need meters)")
        else:
            out["problems"].append(f"height {H:.2f} m; must be between {h_min} and {h_max} m")
    sole = V[V[:, 2] < lo[2] + 0.03 * H]
    ank = V[(V[:, 2] > lo[2] + 0.06 * H) & (V[:, 2] < lo[2] + 0.10 * H)]
    if len(sole) >= 8 and len(ank) >= 8:
        d = sole[:, :2].mean(0) - ank[:, :2].mean(0)
        if np.linalg.norm(d) > 0.01 * H:
            head = float(np.degrees(np.arctan2(d[0], -d[1])))
            out["heading_deg"] = head
            if abs(head) > 45:
                out["rot_z_deg"] = float(-90.0 * round(head / 90.0))
                out["problems"].append(f"character does not face -Y (feet point {head:.0f}°); it needs a {out['rot_z_deg']:.0f}° turn around Z")
    return out


NECK_MIN_REL = 0.2      # boyun adayi: ust govde merkez genisliginin en az bu orani (tac dikeni 0.08-0.12, vanilla boyun 0.33-0.36)
# El ucu: yanalliga gore secilen uc, kalin kol + sarkik elde kolluk/on kol dis kenari olabilir (Winter Soldier UE ripi, 2026-09-12:
# secilen uc GT parmak ucunun 21.6 cm ustu, G 39; ayni kolda parmak ucu adayi G 53, GT'ye 1.2 cm -> bilek 14, parmak 16-20 cm kaydi).
# Duzeltme: secilen ucun HAND_TIP_R boy yakinindaki, geodezik olarak DAHA UZAK kati voxel. Salt "en uzak uc" secimi dize gider
# (ayni tarafta diz/baldir adayi G 66). Olculdu: WS el/kol ort 15.4 -> 2.8 cm (bilek 14/13 -> 4.4/1.5); 36 vanilla vaka + 84 oran
# varyanti BIREBIR ayni, kalibrasyon dosyasi degismedi (tests/run_flag.py ile A/B).
HAND_TIP_REFINE = True
HAND_TIP_R = 0.15
NECK_ABOVE_WIDEST = True    # boyun adayi omuz/kol bandinin altindaysa bandin ustundeki en ince katman (False = eski min())
HIP_BACK_DEP = 0.15         # z_crotch kasik ipucu tabanindan bu kadar (x H) ayrisirsa 'back' ipucu atilir (0 = kapali)


def detect(V, F, tpl, h_div=140, log=print):
    import time
    t0 = time.time()
    Vw, Fw, _ = vx.weld(V, F)
    lo, hi = Vw.min(0), Vw.max(0)
    H = float(hi[2] - lo[2])
    h = H / h_div
    grid = vx.Grid.around(Vw, h, pad=2)
    comp = vx.mesh_components(len(Vw), Fw)
    solid, surf = vx.solid_volume(grid, Vw, Fw, comp)
    dt = erosion_depth(solid)
    xc = 0.5 * (lo[0] + hi[0])
    ii, jj, kk = np.nonzero(solid)
    P = grid.center(np.stack([ii, jj, kk], 1))
    band = (P[:, 2] > lo[2] + 0.5 * H) & (P[:, 2] < lo[2] + 0.75 * H) & (np.abs(P[:, 0] - xc) < 0.12 * H)
    if not band.any():
        raise ValueError("body center not found (is the mesh upright and facing -Y?)")
    cand = np.nonzero(band)[0]
    c0 = cand[int(np.argmax(dt[ii[cand], jj[cand], kk[cand]]))]
    G = geodesic_bfs(solid, np.array([ii[c0], jj[c0], kk[c0]]))

    # uclar: geodezik YEREL maksimumlar + maksimum baskilama
    Gm = np.where(solid & (G >= 0), G, -1)
    mx = _shift_extreme(Gm, np.maximum)
    ismax = solid & (Gm >= mx) & (Gm > 0.12 * H / h)
    mi, mj, mk_ = np.nonzero(ismax)
    MP = grid.center(np.stack([mi, mj, mk_], 1))
    gv = Gm[mi, mj, mk_]
    ends = []
    for o in np.argsort(-gv):
        if all(np.linalg.norm(MP[o] - e) > 0.12 * H for e in ends):
            ends.append(MP[o])
        # 20 aday: uzun bacakli sisman govdede (kolu govdeye degen) on/arka diz tumsekleri ilk 10'u doldurdu, sag el
        # listeye girmedi (bilek 55 cm kaydi). El secimi yanalliga gore -> fazla aday secimi bozmaz.
        if len(ends) >= 20:
            break
    ends = np.array(ends)
    if len(ends) < 5:
        raise ValueError(f"not enough extremities found ({len(ends)}) — the arms may be attached to the body")
    center = np.abs(ends[:, 0] - xc) < 0.15 * H
    head_i = int(np.argmax(np.where(center, ends[:, 2], -1e9))) if center.any() else int(np.argmax(ends[:, 2]))
    rest = [i for i in range(len(ends)) if i != head_i]
    low = [i for i in rest if ends[i, 2] < lo[2] + 0.15 * H]
    fL = max((i for i in low if ends[i, 0] > xc), key=lambda i: -ends[i, 2], default=None)
    fR = max((i for i in low if ends[i, 0] <= xc), key=lambda i: -ends[i, 2], default=None)
    upper = [i for i in rest if ends[i, 2] >= lo[2] + 0.15 * H]
    hL = max((i for i in upper if ends[i, 0] > xc), key=lambda i: ends[i, 0] - xc, default=None)
    hR = max((i for i in upper if ends[i, 0] <= xc), key=lambda i: xc - ends[i, 0], default=None)
    if None in (fL, fR, hL, hR):
        raise ValueError("could not tell hand and foot tips apart")
    if HAND_TIP_REFINE:
        gP = G[ii, jj, kk]
        for hi_ in (hL, hR):
            e = ends[hi_]
            ge = G[tuple(np.clip(grid.index(e[None])[0], 0, grid.dims - 1))]
            near = np.nonzero(np.linalg.norm(P - e, axis=1) < HAND_TIP_R * H)[0]
            if len(near):
                k = near[int(np.argmax(gP[near]))]
                if gP[k] > ge:
                    ends[hi_] = P[k]
    rat = vanilla_ratios(tpl)
    zof = lambda r: lo[2] + r * H
    out = {}

    def limb_path(p):
        path = _descend(G, grid.index(p[None])[0])
        return _smooth_polyline(grid.center(_ridge(path, dt)))

    # --- yatay kesit yardimcilari (katman indeksli: cagri basina yalniz o katmanin voxelleri) ---
    kz = np.round((P[:, 2] - grid.lo[2]) / h).astype(int)
    order = np.argsort(kz, kind="stable")
    bounds = np.searchsorted(kz[order], np.arange(int(kz.max()) + 2))

    def center_run(sgn, z):
        """z katmaninda merkezden disari ILK kesintisiz kosu (govde + bitisik kol): (dis kenar mesafesi, voxel indeksleri)."""
        k = int(round((z - grid.lo[2]) / h))
        if k < 0 or k + 1 >= len(bounds):
            return None
        idx = order[bounds[k]:bounds[k + 1]]
        xs = sgn * (P[idx, 0] - xc)
        keep = (xs > -0.5 * h) & (xs < 0.6 * H)
        idx, xs = idx[keep], xs[keep]
        if len(idx) < 3:
            return None
        kx = np.round(xs / h).astype(int)
        occ = np.zeros(kx.max() + 2, bool)
        occ[kx] = True
        if not occ[:2].any():
            return None
        start = 0 if occ[0] else 1
        outer = (start + int(np.nonzero(~occ[start:])[0][0]) - 0.5) * h
        sel = idx[(xs >= 0) & (xs <= outer)]
        return (outer, sel) if len(sel) >= 3 else None

    def center_width(z):
        a, b = center_run(1.0, z), center_run(-1.0, z)
        return a[0] + b[0] if a and b else None

    # --- omuz cizgisi (v7): boynun en ince kesitinin altinda govde genisligi boyun genisliginin 1.6 katini ilk astigi katman.
    # 12 govde x (vanilla + 6 oran varyanti: uzun/kisa bacak, buyuk kafa, uzun kol, genis, cizgi film), 2026-09-11:
    # boyun z std 1.9, omuz 2.1, kafa (cizgi + 0.314 x (tepe - cizgi)) 1.5 cm; varyant kaymasi <= 2.4 cm.
    # v6 boy orani vanilla'da 1.8 cm ama oran degisik govdede 7-9 cm kaydi (cizgi film: boyun +9, omuz +7.6).
    top_z = lo[2] + H
    zl = lambda k: grid.lo[2] + k * h
    z_line = None
    k_top = int(round((top_z - 0.06 * H - grid.lo[2]) / h))
    k_bot = int(round((top_z - 0.45 * H - grid.lo[2]) / h))
    widths = {k: w for k in range(k_bot, k_top + 1) for w in [center_width(zl(k))] if w is not None}
    if widths:
        # ince cikinti (tac dikeni, boynuz, anten) boyun sayilmaz: ust govde bandi (lo + 0.55..0.70 H) merkez genisliginin %20'sinden
        # ince katman aday degil. Olculdu (tests/an_top_profile.py, 2026-09-12): kullanicinin sauron ped'inde tac dikenleri 0.08-0.12,
        # gercek boyun 0.50; vanilla boyunlar 0.33-0.36 (mp_m, fatlatin, fitness). Filtresiz: en ince katman dikende -> boyun +23 cm.
        kb0 = int(round((lo[2] + 0.55 * H - grid.lo[2]) / h))
        kb1 = int(round((lo[2] + 0.70 * H - grid.lo[2]) / h))
        band = [w for k in range(kb0, kb1 + 1) for w in [center_width(zl(k))] if w is not None]
        w_ref = float(np.median(band)) if band else 0.0
        cand = {k: w for k, w in widths.items() if w >= NECK_MIN_REL * w_ref} or widths
        k_neck = min(cand, key=cand.get)
        if NECK_ABOVE_WIDEST:
            # boyun omuz/kol bandinin (araliktaki en genis katman) USTUNDE olmali: Xbot'ta bel eklemi = boyun = 0.116 m, min() alttaki
            # beli secti -> boyun 39, kafa 25 cm asagi (2026-09-12). Aday bandin altindaysa bandin ustundeki, ustunde kafa sisligi
            # (>= 1.2x) olan en ince katman. Reddedilen: "yakin ince katmanlardan ustteki" (1.15x) — vanilla/varyant boynunu cene
            # altina kaydirdi (84 varyant ort 2.847 -> 2.859, fatlatin buyuk_kafa a35 3.31 -> 4.08).
            k_wide = max(widths, key=widths.get)
            if k_neck < k_wide:
                up = {k: w for k, w in cand.items() if k > k_wide and
                      max((widths[j] for j in range(k + 1, k_top + 1) if j in widths), default=0.0) >= 1.2 * w}
                if up:
                    k_neck = min(up, key=up.get)
        for k in range(k_neck - 1, k_neck - int(0.3 * H / h), -1):
            w = widths[k] if k in widths else center_width(zl(k))
            if w is not None and w > 1.6 * widths[k_neck]:
                z_line = zl(k)
                break

    # --- bacaklar: YATAY KESIT kutle merkezleri (yol degil) ---
    # v2 tuzagi: dizleri degen sisman ped'de sol ayak yolu diz hizasinda sag bacaga gecti (diz x +16 cm).
    # kasik: pelvis hizasindan ASAGI orta sutunun ilk bosaldigi yukseklik (alttaki degen dizler sayilmaz)
    mid_col = np.abs(P[:, 0] - xc) < 1.5 * h
    mid_levels = set(kz[mid_col].tolist())
    k_start = int(round((zof(0.55) - grid.lo[2]) / h))
    k_cr = k_start
    while k_cr in mid_levels and k_cr > 0:
        k_cr -= 1
    z_crotch = grid.lo[2] + (k_cr + 1) * h

    def leg_centroid(sgn, z):
        # taraf yarisinda merkezden disari ILK kesintisiz kosu (uyluk/diz); bacaga yakin sarkan el ayri kosu kalir
        m = (np.abs(kz - round((z - grid.lo[2]) / h)) <= 1) & (sgn * (P[:, 0] - xc) > 0.5 * h) & \
            (np.abs(P[:, 0] - xc) < 0.16 * H)
        if m.sum() < 3:
            return None
        kx = np.round(sgn * (P[m, 0] - xc) / h).astype(int)
        occ = np.zeros(kx.max() + 2, bool)
        occ[kx] = True
        first = int(np.argmax(occ))
        end = first + int(np.nonzero(~occ[first:])[0][0])
        sel = kx < end
        return P[m][sel].mean(0) if sel.sum() >= 3 else None

    # --- kalca yuksekligi (v7): govde oranindan bagimsiz uc izin ortalamasi.
    # 12 govde x (vanilla + 6 oran varyanti) olcumu (2026-09-11), z std / en buyuk varyant kaymasi (cm):
    #   boy orani (v6) 6.4 / 10.3 (vanilla 2.0) · kasik kalinlik dususu 5.5 / 1.4 · kalca arka max 5.7 / 1.8 ·
    #   omuz cizgisi orani 5.8 / 9.2 · UCUNUN ORTALAMASI 3.9 / 3.8 (vanilla 3.1; max 15.7 -> 11.9).
    #   kasik: lo+0.65H'den asagi, merkez sutunun (|x-xc| <= 1 voxel) dolu y kalinligi en kalin sutunun %80'inin altina
    #          indigi ilk katman (orta sutun bosalma taramasi degen ic uyluklarda std 10 cm). Esik (84 vaka, 2026-09-11):
    #          0.5/0.6/0.7/0.8/0.9 -> iz std 7.4/6.9/5.5/4.7/5.3 cm; uc izin ortalamasi 0.7 ile 3.9 (vanilla 3.1), 0.8 ile 3.7 (2.8).
    #          Reddedilen iz: on kasik kivrimi (std 10.8, kasikla korelasyon 0.83); medyan ve ters varyans agirligi fayda yok.
    #   arka: orta sutun kasigi -0.05H..+0.20H arasinda |x-xc| < 0.12H icindeki en arka y'nin yuksekligi.
    def column_stats(z):
        """z katmani, |x-xc| < 0.12H: (merkez 3 sutunun en kalini, en kalin sutun [dolu y hucresi], en arka y)."""
        k = int(round((z - grid.lo[2]) / h))
        if k < 0 or k + 1 >= len(bounds):
            return None
        Q = P[order[bounds[k]:bounds[k + 1]]]
        Q = Q[np.abs(Q[:, 0] - xc) < 0.12 * H]
        if len(Q) < 2:
            return None
        ix = np.round((Q[:, 0] - xc) / h).astype(int)
        iy = np.round((Q[:, 1] - grid.lo[1]) / h).astype(int)
        cols, cnt = np.unique(np.unique((ix + 1000) * 100000 + iy) // 100000 - 1000, return_counts=True)
        center = np.abs(cols) <= 1
        return (int(cnt[center].max()) if center.any() else 0), int(cnt.max()), float(Q[:, 1].max())

    z_cues = {}     # adli: testler ipuclarini tek tek olcer (info["z_cues"])
    for k in range(int(round((zof(0.65) - grid.lo[2]) / h)), int(round((zof(0.2) - grid.lo[2]) / h)), -1):
        st = column_stats(zl(k))
        if st and st[0] < 0.8 * st[1]:
            z_cues["crotch"] = zl(k) + h + 0.0539 * H
            break
    back = [(st[2], zl(k)) for k in range(int(np.ceil((z_crotch - 0.05 * H - grid.lo[2]) / h)),
                                         int(np.floor((z_crotch + 0.20 * H - grid.lo[2]) / h)) + 1)
            for st in [column_stats(zl(k))] if st]
    if back:
        z_cues["back"] = max(back, key=lambda t: t[0])[1] + 0.0126 * H
    if z_line is not None:
        z_cues["line"] = lo[2] + 0.5967 * (z_line - lo[2])
    # aykiri ipucu kapisi (2026-09-11): bol pantolon bacaklari birlestirince z_crotch ayak bilegine iner, 'back' -80 cm -> kalca -31 cm
    # (sentetik, tests/an_synth_dump.py). Medyandan > 0.10 H uzak ipucu atilir: 84 vanilla/oran vakasinda HIC tetiklenmez (sonuc ayni),
    # bol pantolonda -31 -> -6.3 cm (tests/an_hip_gate.py). 0.06 vanilla ortalamasini da iyilestirir ama ayni veriyle secilir + uzun bacakta kotu.
    vals, z_dropped = dict(z_cues), []
    # 'back' z_crotch'a baglidir: orta sutun kasik ipucunun tabanindan cok asagida bosaliyorsa (sisman/degen uyluk) 'back' bozuk sayilir,
    # oylamaya girmez. tests/an_hip_dep.py (2026-09-12), esik 0.15 H: 84 vanilla/varyant A-pose ort 2.66 -> 2.55, max 10.8 -> 9.1 cm
    # (4 vaka); test_autodetect kalibre 2.304 -> 2.261, test_variants 2.847 -> 2.785 (max 11.29 -> 9.30). 7 gercek model degismedi.
    # 0.06-0.10 esikleri 20-50 vanilla vakayi degistiriyordu (vanilla'da fark ort -13, |max| 36 cm). Soldier (uyluk dize kadar degen)
    # cozulmedi: dogru yonde crotch 0.40 / back 0.23 / line 0.53, kapi medyana dusuyor -> kalca -28 cm.
    if HIP_BACK_DEP and "back" in vals and "crotch" in vals and \
            abs(z_crotch - (vals["crotch"] - h - 0.0539 * H)) > HIP_BACK_DEP * H:
        vals.pop("back")
        z_dropped.append("back")
    if len(vals) >= 3:
        med = float(np.median(list(vals.values())))
        gate = [c for c, v in vals.items() if abs(v - med) > 0.10 * H]
        vals = {c: v for c, v in vals.items() if c not in gate} if len(gate) <= len(vals) - 2 else {"median": med}
        z_dropped += gate
    z_hip = float(np.mean(list(vals.values()))) if vals else max(zof(rat["z_hip"]), z_crotch + 0.01 * H)

    hips = {}
    for side, fi in (("L", fL), ("R", fR)):
        sgn = 1.0 if side == "L" else -1.0
        tip = ends[fi]
        ankle = leg_centroid(sgn, zof(rat["z_ankle"]))
        # diz (v7): ayak bilegi -> kalca arasinda bacak-ici oran 0.4942 (84 vaka, GT kalcayla std 1.05 cm);
        # boy orani uzun/kisa bacakta +-4.8 cm kaydi.
        knee = leg_centroid(sgn, ankle[2] + 0.4942 * (z_hip - ankle[2])) if ankle is not None else None
        if ankle is None or knee is None:
            raise ValueError(f"{side} leg cross-section not found")
        # kalca x/y: kalca yuksekliginin 0.06-0.14 boy altindaki uyluk kesit merkezlerinin ortalamasi.
        # 12 govde x 3 kol pozu LOO (2026-09-11): x std 1.9 -> 1.0, y 3.2 -> 1.2 cm; kalca ort 3.9 -> 2.4 cm, max 13 -> 4.3.
        # v5 tuzagi: diz-kasik dogrusu uzatmasi kasik algilamasina bagliydi (kasik z std 10 cm), y hatasini buyutuyordu.
        cen = [c for k in (0.06, 0.08, 0.10, 0.12, 0.14) for c in [leg_centroid(sgn, z_hip - k * H)] if c is not None]
        c = np.mean(cen, 0) if cen else knee
        hip = np.array([c[0], c[1], z_hip])
        # ayak TABANI (mesh vertexleri, z < %3 boy): on uc (-Y) -> topuk. 12 vanilla govde olcumu (2026-09-11):
        # Toe0 on uctan %25 geride (std 0.056), x taban medyaninda (+0.002H), z 0.0265H; ayak bilegi y %79 (std 0.029).
        # v3'te uc noktasina dayali tahmin sisman/fit govdelerde 12-13 cm kaydi.
        sole = (Vw[:, 2] < lo[2] + 0.03 * H) & (sgn * (Vw[:, 0] - xc) > 0)
        if sole.sum() >= 8:
            ymin, ymax = float(Vw[sole, 1].min()), float(Vw[sole, 1].max())
            xmed = float(np.median(Vw[sole, 0]))
            toe = np.array([xmed + sgn * 0.002 * H, ymin + 0.25 * (ymax - ymin), lo[2] + 0.0265 * H])
            ankle = np.array([ankle[0], ymin + 0.786 * (ymax - ymin), ankle[2]])
        else:
            toe = np.array([ankle[0], tip[1] + rat["toe_fwd"] * (ankle[1] - tip[1]), zof(rat["z_toe"])])
        out[f"{side}_ankle"], out[f"{side}_knee"], out[f"{side}_hip"], out[f"{side}_toe"] = ankle, knee, hip, toe
        hips[side] = hip

    # --- kollar: yol (el -> govde) bilek/dirsek/ust kol acisini verir; omuz yatay KESITLERDEN ---
    # v2 tuzagi: kose algilama koltuk altinda tuttu, omuz 10-22 cm asagida kaldi (tum govdelerde).
    z_sh = z_line - 0.0492 * H if z_line is not None else zof(rat["z_shoulder"])
    arms = {}
    for side, hi_ in (("L", hL), ("R", hR)):
        Pp = limb_path(ends[hi_])
        s = _arc(Pp)
        ka = int(np.searchsorted(s, 0.06 * H)); kb = int(np.searchsorted(s, 0.24 * H))
        kb = min(max(kb, ka + 2), len(Pp) - 1)
        axis = Pp[kb] - Pp[ka]
        axis /= max(np.linalg.norm(axis), 1e-9)
        k_end = len(Pp) - 1
        for k in range(kb, len(Pp) - 3):
            if s[k] < 0.26 * H:
                continue
            d = Pp[min(k + 3, len(Pp) - 1)] - Pp[max(k - 3, 0)]
            d /= max(np.linalg.norm(d), 1e-9)
            if np.degrees(np.arccos(np.clip(d @ axis, -1, 1))) > 40:
                k_end = k
                break
        seg = Pp[: min(k_end + 4, len(Pp))]
        if abs(axis[2]) < 0.5:
            # kol yataya yakin (T-pose): koseye kadar tum yol ayni yukseklikte, "z'ye en yakin" rastgele kol noktasi
            # secer (olculdu: T-pose omuz ort 23 / max 60 cm) -> x/y kose noktasindan
            k_sh = k_end
        else:
            k_sh = int(np.argmin(np.abs(seg[:, 2] - z_sh)))
        sh = Pp[k_sh].copy()
        sh[2] = z_sh
        L = s[k_sh]
        wrist = _at_arc(Pp, s, rat["arm_wrist"] * L)
        # orta parmak zinciri (v8b): geodezik el ucundan bilege DUZ dogru uzerinde vanilla zincir oranlariyla.
        # Parmak marker'i yokken el kemigi on kol yonunde vanilla kalir -> otomatik zincirde parmak kivirma %95 12-62 mm.
        # v8a tuzagi: yol boyunca yerlestirme voxel "eldiven" icinde kivrildi; sisman govdede zincir %95 3.60 -> 3.97 mm kotulesti.
        tip_end = ends[hi_]
        # dirsek: omuz-bilek dogrusunda vanilla oraninda (ust kol / (ust kol + on kol)), kolun medial yoluna oturtulur.
        # v3'te yol uzunlugu oraniyla omuz hatasini tasiyordu (A-pose ort 5.0 / max 12 cm).
        e_line = sh + rat["upper_frac"] * (wrist - sh)
        seg_arm = Pp[: k_sh + 1]
        k_el = int(np.argmin(np.linalg.norm(seg_arm - e_line, axis=1)))
        ang = _upper_arm_angle(Pp, k_el, k_sh)
        arms[side] = dict(path=Pp, k_sh=k_sh, k_el=k_el, axis=axis, angle=ang)
        # omuz (v6) — 12 govde x 3 kol pozu (57/35/0 derece) LOO, 2026-09-11; v5 (yol kosesi + boy orani) ort 4.1 cm:
        #  x: kol yatay degilse deltoid dis kenari (omuz hizasi kesiti) - (0.0072 + 0.0242/sin(ust kol acisi)) boy
        #     [silindir kolu yatay kesit eksenden ~r/sin(aci) disarida keser; std 3.4 -> 1.6 (57) / 2.2 (35)];
        #     kol yataysa (< 15 derece) omzun 0.10-0.14 boy altindaki govde kenari (std 2.8).
        #  y: omzun 0.14-0.16 boy altindaki govde kesitinin on-arka ortasi (kol pozundan bagimsiz; std 2.1 -> 1.7).
        #  z: omuz cizgisi - 0.0486 boy (v7) ile omuz ust yuzeyi - 0.035 boy ortalamasi (35/0 derecede std 2.1 -> 1.6).
        sgn = 1.0 if side == "L" else -1.0
        runs_ = {k: center_run(sgn, z_sh - k * H) for k in (0.0, 0.10, 0.12, 0.14, 0.16)}
        if ang < 15:
            edges = [runs_[k][0] for k in (0.10, 0.12, 0.14) if runs_[k]]
            xo = float(np.mean(edges)) if edges else None
        else:
            xo = runs_[0.0][0] - (0.0072 + 0.0242 / np.sin(np.radians(max(ang, 12.0)))) * H if runs_[0.0] else None
        mids = [0.5 * (P[runs_[k][1], 1].min() + P[runs_[k][1], 1].max()) for k in (0.14, 0.16) if runs_[k]]
        col = (np.abs(P[:, 0] - sh[0]) < 1.5 * h) & (np.abs(P[:, 1] - sh[1]) < 0.03 * H) & \
              (np.abs(P[:, 2] - z_sh) < 0.15 * H)
        if ang < 15:
            # kol yatay: omuz yuksekligi = ust kolun medial yolu (tup ekseni eklemden gecer). v8'de ust yuzey kolonu
            # boyun/kafaya denk geldi -> GTA disi sentetik T-pose omuz z +7 cm.
            upper = Pp[k_el:k_el + max((k_sh - k_el) // 2, 1) + 1]
            z_new = float(upper[:, 2].mean())
        else:
            z_new = 0.5 * z_sh + 0.5 * (P[col, 2].max() - 0.035 * H) if col.any() else z_sh
        sh = np.array([xc + sgn * xo if xo is not None else sh[0], float(np.mean(mids)) if mids else sh[1], z_new])
        # bilek / dirsek / parmak zinciri YENI omuza gore: kol boyu = el ucundan omuza en yakin yol noktasina kadar.
        # v8'e kadar yol kosesi (k_sh) kullaniliyordu; T-pose'da kose govde icinde kaldi -> sentetik bilek/dirsek x -7..-9 cm.
        k_new = int(np.argmin(np.linalg.norm(Pp - sh, axis=1)))
        wrist = _at_arc(Pp, s, rat["arm_wrist"] * (s[k_new] + float(np.linalg.norm(Pp[k_new] - sh))))
        for j in (0, 1, 2):
            out[f"{side}_f2{j}"] = tip_end + rat[f"f_tip2{j}"] * (wrist - tip_end)
        e_line = sh + rat["upper_frac"] * (wrist - sh)
        seg_arm = Pp[: max(k_new, 2) + 1]
        out[f"{side}_elbow"] = seg_arm[int(np.argmin(np.linalg.norm(seg_arm - e_line, axis=1)))]
        out[f"{side}_wrist"] = wrist
        out[f"{side}_shoulder"] = sh

    # --- govde / kafa: yukseklik boy oranindan (omuzdan turetmek hatayi tasiyordu) ---
    top = ends[head_i]

    def ymid(z):
        m = (np.abs(P[:, 2] - z) < 1.5 * h) & (np.abs(P[:, 0] - xc) < 0.05 * H)
        return float(np.median(P[m, 1])) if m.any() else float(top[1])
    if z_line is not None:
        zn, zh = z_line - 0.0082 * H, z_line + 0.314 * (top_z - z_line)
    else:
        zn, zh = zof(rat["z_neck"]), zof(rat["z_head"])
    out["neck"] = np.array([xc, ymid(zn), zn])
    out["head"] = np.array([xc, ymid(zh), zh])
    zroot = 0.5 * (hips["L"][2] + hips["R"][2]) + (rat["z_root"] - rat["z_hip"]) * H
    out["pelvis"] = np.array([xc, ymid(zroot), zroot])
    log(f"  otomatik marker: voxel {tuple(int(x) for x in grid.dims)} h={h*1000:.1f}mm, uc {len(ends)}, {time.time()-t0:.1f}s")
    return out, dict(ends=ends, head=head_i, hands=(hL, hR), feet=(fL, fR), z_crotch=z_crotch,
                     grid=grid, solid=solid, lo=lo, H=H, xc=xc, Vw=Vw, arms=arms, z_line=z_line, z_cues=z_cues,
                     z_dropped=z_dropped)


# --- veriyle kalibrasyon (sistematik kayma) -----------------------------------------------------
ARM_KEYS = ("elbow", "wrist", "f20", "f21", "f22")   # omuz v6'dan beri dunya cercevesinde (izleri dunya eksenli kesitler)


def _base(key):
    return key[2:] if key[:2] in ("L_", "R_") else key


def _frame(key, m, xc):
    """Kalibrasyon cercevesi (sutunlar). Kol: kol ekseni + ileri; digerleri dunya. R tarafi aynalanmis L olarak."""
    base = _base(key)
    if base in ARM_KEYS and key[:2] in ("L_", "R_"):
        s = key[:2]
        mir = np.array([-1.0, 1, 1]) if s == "R_" else np.ones(3)
        sh = (m[s + "shoulder"] - [xc, 0, 0]) * mir
        wr = (m[s + "wrist"] - [xc, 0, 0]) * mir
        a = wr - sh
        a /= max(np.linalg.norm(a), 1e-9)
        f = np.array([0.0, -1.0, 0.0])
        f = f - a * (f @ a)
        f /= max(np.linalg.norm(f), 1e-9)
        return np.stack([a, f, np.cross(a, f)], axis=1)
    return np.eye(3)


def residuals(det, gt, H, xc):
    """GT - algilanan, anahtar tabaninda (L/R havuzlanmis), boyla olcekli yerel koordinat."""
    out = {}
    for k in gt:
        if k not in det:
            continue
        r = (np.asarray(gt[k]) - np.asarray(det[k])) / H
        if k.startswith("R_"):
            r = r * np.array([-1.0, 1, 1])
        out.setdefault(_base(k), []).append(_frame(k, det, xc).T @ r)
    return out


def apply_calibration(det, calib, H, xc):
    """calib: {taban_anahtar: [ox, oy, oz]} (yerel, boy orani)."""
    out = {}
    for k, p in det.items():
        c = calib.get(_base(k))
        if c is None:
            out[k] = p
            continue
        off = _frame(k, det, xc) @ np.asarray(c) * H
        if k.startswith("R_"):
            off = off * np.array([-1.0, 1, 1])
        out[k] = np.asarray(p) + off
    return out


def load_calibration(path=None):
    import json, os
    path = path or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "autodetect_calib.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["offsets"]


# --- sablon kaydi ile ince ayar ---------------------------------------------------------------
# pelvis haric: Chamfer pelvisi iyi kisitlamiyor (olculdu: 1.8 -> 5.5 cm)
REFINE_ORDER = ("L_hip", "R_hip", "L_knee", "R_knee", "L_ankle", "R_ankle", "L_shoulder", "R_shoulder",
                "L_elbow", "R_elbow", "L_wrist", "R_wrist", "neck", "head", "L_toe", "R_toe")


def _nn_dist_builder(points):
    """Nokta bulutuna en yakin mesafe (k=1). scipy -> mathutils KDTree -> numpy izgara."""
    try:
        from scipy.spatial import cKDTree
        t = cKDTree(points)
        return lambda Q: t.query(Q, 1)[0]
    except ImportError:
        pass
    try:
        from mathutils.kdtree import KDTree
        kd = KDTree(len(points))
        for i, p in enumerate(points):
            kd.insert(p, i)
        kd.balance()
        return lambda Q: np.array([kd.find(q)[2] for q in Q])
    except ImportError:
        from .knn import GridKNN
        g = GridKNN(points)
        return lambda Q: g.query(Q, 1)[0][:, 0]


def refine(V, F, markers, tpl, ref, steps=(0.03, 0.015, 0.0075), rounds=2, symmetric=True,
           n_target=2500, log=print):
    """Marker'lari vanilla govde prior'uyla hedef yuzeye oturt (koordinat aramasi, cift yonlu Chamfer).
    ref: (Vr, Fr, WIr, WVr, ref_skel) — pipeline.load_reference ciktisi."""
    import time
    from . import markers as mk
    from .fit import fit_skeleton
    from . import transfer as tr
    t0 = time.time()
    Vw, Fw, _ = vx.weld(V, F)
    H = float(np.ptp(Vw[:, 2]))
    s = H / 1.82
    rng = np.random.default_rng(0)
    _, _, _, St = tr.sample_triangles(Vw, Fw, 0.01 * s)
    St = St[rng.choice(len(St), min(n_target, len(St)), replace=False)]
    d_to_target = _nn_dist_builder(tr.sample_triangles(Vw, Fw, 0.005 * s)[3])
    Vr, Fr, WIr, WVr, ref_skel = ref
    sub = rng.choice(len(Vr), min(3000, len(Vr)), replace=False)
    m = {k: np.asarray(v, float).copy() for k, v in markers.items()}

    def energy(mm):
        T = mk.expand_targets(tpl, mm)
        fr = fit_skeleton(ref_skel, T)
        Vd = tr.deform_reference(Vr[sub], WIr[sub], WVr[sub], ref_skel.W, fr.P_W, fr.scale)
        a = _nn_dist_builder(Vd)(St)
        b = d_to_target(Vd)
        return float(np.mean(np.minimum(a, 0.1 * s)) + np.mean(np.minimum(b, 0.1 * s)))

    e0 = best = energy(m)
    n_eval = 1
    moves = np.array([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)], float)
    keys = [k for k in REFINE_ORDER if k in m]
    for st in steps:
        for _ in range(rounds):
            for k in keys:
                if symmetric and k.startswith("R_") and "L_" + k[2:] in m:
                    continue
                mate = mk.mirror_key(k) if symmetric else None
                for mv in moves:
                    trial = dict(m)
                    trial[k] = m[k] + mv * st * s
                    if mate and mate in m:
                        mirror = mv * st * s * np.array([-1, 1, 1])
                        trial[mate] = m[mate] + mirror
                    e = energy(trial)
                    n_eval += 1
                    if e < best - 1e-6:
                        best, m = e, trial
    log(f"  sablon kaydi: enerji {e0*1000:.1f} -> {best*1000:.1f} mm, {n_eval} deneme, {time.time()-t0:.1f}s")
    return m
