"""El sablon kaydi (autodetect.HAND_REG): vanilla referans ellerinin mesh'i (Hand + Finger agirligi > 0,5) hedefin el bolgesine
benzerlik donusumlu, kirpmali ICP ile oturtulur; referansin GTA parmak eklemleri ayni donusumle tasinir -> 15 parmak marker'i
{S}_f{f}{j} (fit_skeleton hedefli kemigi birebir yerlestirir). Neden: marker yolunda kalan parmak hatasinin cogu elin BUTUN olarak
yerlesimi; sablon kaydi GTA'nin kendi el geometrisi -> eklem iliskisini tasir (olcum: tests/an_hand_icp.py, tests/an_handreg.py; PLAN.md
'ICP v3..').
Adaylar: REFS x AUG_DEG (referans eli kendi GTA iskeletiyle bukulur: isaret..serce 3 eklem, yerel Z) x ROLL_DEG (fit el ekseni etrafinda
baslangic donusu). Tarama TOPLU (tum adaylar tek nearest cagrisi + toplu SVD; sure ICP iterasyon sayisiyla orantili, olculdu ~2,5 ms/cagri)
ve ardisik yarilamali (SCREEN_PLAN) -> en iyi REFINE_TOP aday tum noktalarla ICP -> en kucuk SKOR (_score: kalinti x bukulme cezasi x
olcek cezasi; kalinti tek basina bukulmus/olcekli yanlis adayi secer — tests/an_hand_select.py).
Kalinti / el boyu > RES_GATE ise o el icin marker yazilmaz (marker yolu kalir). Blender'da scipy yok -> knn.GridKNN.nearest.
"""
import numpy as np
from .knn import GridKNN
from .fit import axis_angle
from .skeleton import lbs

REFS = ("mp_m", "mp_f", "a_m_m_fatlatin_01", "a_f_m_fatwhite_01", "a_m_y_musclbeac_01", "a_f_y_fitness_01", "a_m_o_beach_01",
        "a_f_m_bodybuild_01", "a_m_y_beach_01", "a_f_y_topless_01", "a_m_m_genfat_01", "a_f_y_yoga_01")
AUG_DEG = (-30.0, -15.0, 0.0, 15.0, 30.0)
ROLL_DEG = (-25.0, 0.0, 25.0)
SHIFT_L = (-0.1, 0.0)        # baslangic kaydirmasi el ekseni boyunca (el boyu orani): seyrek (dusuk poly) hedefte ICP havzasi dar,
                             # bilek marker'inin ~1 cm kaymasi yerel minimuma kilitler (PLAN.md 'AYRISTIRMA'); olculdu 36 vanilla vaka
                             # (simetrik aile disi): (0,) 0,302 -> (-0,1, 0) 0,278 cm, (-0,1, 0, 0,1) 0,280
ITERS, TRIM = 30, 0.8
SCREEN_PTS = 300
SCREEN_DST = 2500            # tarama hedef nokta ust siniri (voksel alt ornekleme; inceltme tum noktalarla)
SCREEN_PLAN = ((6, 0.4), (6, 0.15), (8, 0.0))   # (iterasyon, sonra tutulacak aday orani — tum adaylara gore; 0 = REFINE_TOP)
REFINE_TOP = 4
RES_GATE = 1e9               # ortalama kalinti / el boyu (Hand -> Finger22) ust siniri (olcum: kapi hicbir senaryoda yardim etmedi)
KNN_CELL = 0.06              # GridKNN hucresi / el boyu (~11 mm; uzak sorgu kaba kuvvete duser)
SYM_GATE, SYM_MARGIN = 0.2, 0.1  # simetri kapisi: sablon L <-> aynalanmis R parmak farki / el boyu > SYM_GATE ve cekirdek yolun farkindan
                                 # SYM_MARGIN fazlaysa, cekirdek yoldan (mesh uclari) sapmasi buyuk olan el REDDEDILIR (yakinsa ikisi).
                                 # Olculdu: GTA vanilla fark 0,64-1,34 cm (~0,04-0,08 L), Winter Soldier sol eldiven 7,75 cm (sablon ters doner)
IN_GATE = True               # ic kapisi: sablon parmak eklemlerinin hedef mesh DISINDA kalan orani cekirdek yolunkinden IN_MARGIN fazlaysa el
IN_MARGIN = 0.1              # reddedilir (15 eklemde ~2 eklem). Dis = genellestirilmis sarim sayisi |w| <= 0,5. Olculdu (2026-09-13): kaynak
                             # rig eklemleri 9 GTA disi karakterde + GTA GT eklemleri HEP ic; bozuk oturma (sablon kuculup avucun altina
                             # yapisir, ileri kalinti dusuk kalir) fark xbot L 0,33, readyplayerme L 0,13, dune 0,67 / 0,47; GTA ates 0
IN_MIRROR = 0.1              # tek el ic kapisindan donerse ve cekirdek yol simetrikse (asimetri / el boyu < IN_MIRROR) diger el de reddedilir
IN_RAD = 1.6                 # ic testi yuz secimi: (Hand + Finger22) / 2 merkezli, IN_RAD x el boyu (ucgen merkezi)
LAM_AUG, MU_SCALE = 0.2, 0.5 # aday skoru = kalinti * (1 + LAM_AUG*|aci|/30) * (1 + MU_SCALE*|ln(s/s0)|) (tests/an_hand_select.py, LOBO)
REGION = 1.3                 # hedef bolge: (Hand + Finger22) / 2 merkezli, REGION x el boyu yaricap
EXCLUDE = set()              # test (LOO / el ailesi): atlanacak referanslar
LAST = {}                    # tani: el basina secilen aday
JOINTS = [f"Finger{f}{j}" for f in range(5) for j in range(3)]
FINGERS = (1, 2, 3, 4)
_CACHE = {}


def _umeyama(A, B):
    ma, mb = A.mean(0), B.mean(0)
    A0, B0 = A - ma, B - mb
    U, D, Vt = np.linalg.svd(A0.T @ B0 / len(A))
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1
    R = Vt.T @ S @ U.T
    s = float((D * np.diag(S)).sum() / max((A0 ** 2).sum() / len(A), 1e-18))
    return s, R, mb - s * R @ ma


def _umeyama_batch(A, B, w):
    """Agirlikli benzerlik (C aday): A, B (C,n,3), w (C,n) -> s (C,), R (C,3,3), t (C,3)."""
    W = np.maximum(w.sum(1), 1e-12)
    ma = np.einsum("cn,cni->ci", w, A) / W[:, None]
    mb = np.einsum("cn,cni->ci", w, B) / W[:, None]
    A0, B0 = A - ma[:, None], B - mb[:, None]
    U, D, Vt = np.linalg.svd(np.einsum("cn,cni,cnj->cij", w, A0, B0))
    d = np.sign(np.linalg.det(U) * np.linalg.det(Vt))
    Sg = np.ones((len(A), 3))
    Sg[:, 2] = np.where(d == 0, 1.0, d)
    R = np.einsum("cji,cj,ckj->cik", Vt, Sg, U)
    s = (D * Sg).sum(1) / np.maximum(np.einsum("cn,cn->c", w, (A0 ** 2).sum(2)), 1e-18)
    return s, R, mb - s[:, None] * np.einsum("cij,cj->ci", R, ma)


def _asym(JL, JR, wL, wR):
    """L ile x'te aynalanmis R arasi ortalama eklem farki (bilege gore; simetri duzleminin konumundan bagimsiz)."""
    M = np.array([-1.0, 1.0, 1.0])
    return float(np.mean(np.linalg.norm((np.asarray(JL) - wL) - (np.asarray(JR) - wR) * M, axis=1)))


def _core_asym(markers):
    """Cekirdek yol parmak marker'lari L <-> aynalanmis R farki / el boyu -> (asimetri, wL, wR, L) ya da None."""
    if any(f"{S}_wrist" not in markers or f"{S}_f22" not in markers for S in "LR"):
        return None
    wL, wR = (np.asarray(markers[f"{S}_wrist"], float) for S in "LR")
    L = float(np.mean([np.linalg.norm(np.asarray(markers[f"{S}_f22"], float) - np.asarray(markers[f"{S}_wrist"], float)) for S in "LR"]))
    if L < 1e-6:
        return None
    keys = [f"f{f}{j}" for f in range(5) for j in range(3) if f"L_f{f}{j}" in markers and f"R_f{f}{j}" in markers]
    a_core = (_asym([markers["L_" + k] for k in keys], [markers["R_" + k] for k in keys], wL, wR) / L) if len(keys) >= 3 else 0.0
    return a_core, wL, wR, L


def _symmetry_reject(fits, markers):
    """fits {S: J (16,3)} -> reddedilecek taraflar. Karakter gercekten asimetrikse (cekirdek yol da asimetrik) kapi acilmaz."""
    ca = _core_asym(markers)
    if len(fits) < 2 or ca is None:
        return set()
    a_core, wL, wR, L = ca
    a_tpl = _asym(fits["L"][1:], fits["R"][1:], wL, wR) / L
    for S in "LR":
        LAST.get(S, {}).update(asym_L=a_tpl, asym_core_L=a_core)
    if a_tpl <= SYM_GATE or a_tpl <= a_core + SYM_MARGIN:
        return set()
    dL, dR = (LAST.get(S, {}).get("mid_dev_L") or 0.0 for S in "LR")
    if max(dL, dR) <= 1.15 * min(dL, dR):
        return {"L", "R"}
    return {"L"} if dL > dR else {"R"}


def _winding(P, V, F):
    """Genellestirilmis sarim sayisi (ucgen kati acilari toplami / 4 pi): P (n,3) -> w (n,); |w| ~ 1 ic, ~ 0 dis. Delige ve cok katmana
    (eldiven, kiyafet) dayanikli."""
    A, B, C = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    out = np.zeros(len(P))
    for i, p in enumerate(np.asarray(P, float)):
        a, b, c = A - p, B - p, C - p
        la, lb, lc = np.sqrt((a * a).sum(1)), np.sqrt((b * b).sum(1)), np.sqrt((c * c).sum(1))
        det = (a * np.cross(b, c)).sum(1)
        den = la * lb * lc + (a * b).sum(1) * lc + (b * c).sum(1) * la + (c * a).sum(1) * lb
        out[i] = float(np.arctan2(det, den).sum() / (2.0 * np.pi))
    return out


def _outside(P, V, Fh):
    """-> (mesh disinda kalan nokta, gecerli nokta) ya da None (nokta/yuz yok). NaN satirlar sayilmaz."""
    P = np.asarray(P, float)
    ok = np.all(np.isfinite(P), axis=1)
    if not ok.any() or len(Fh) == 0:
        return None
    w = np.abs(_winding(P[ok], V, Fh))
    return int((w <= 0.5).sum()), int(ok.sum())


def _inside_reject(o_t, o_c):
    """Sablon eklemlerinin disarida kalan orani cekirdek yolunkinden IN_MARGIN fazlaysa (ikisi de olculduyse) True."""
    if not o_t or not o_c or o_c[1] == 0:
        return False
    return o_t[0] / o_t[1] > o_c[0] / o_c[1] + IN_MARGIN


def _score(res, ang, sr):
    return res * (1.0 + LAM_AUG * np.abs(ang) / 30.0) * (1.0 + MU_SCALE * np.abs(np.log(np.maximum(sr, 1e-6))))


def _icp(src, knn, dst, s, R, t, iters, trim):
    s0 = s
    for _ in range(iters):
        d, i = knn.nearest(src * s @ R.T + t)
        keep = d <= np.quantile(d, trim)
        if keep.sum() < 10:
            break
        s1, R1, t1 = _umeyama(src[keep], dst[i[keep]])
        if not (np.isfinite(s1) and 0.5 * s0 < s1 < 2.0 * s0):
            break
        s, R, t = s1, R1, t1
    d, _ = knn.nearest(src * s @ R.T + t)
    return s, R, t, float(d.mean())


def _icp_batch(A, knn, dst, s, R, t, iters, trim, s_ref):
    """C aday ayni anda: A (C,n,3). Olcek s_ref'in 0,5..2 kati disina cikan adimi o aday icin atlanir. -> s, R, t, ort kalinti (C,)"""
    C, n, _ = A.shape
    for _ in range(iters):
        X = s[:, None, None] * np.einsum("cij,cnj->cni", R, A) + t[:, None, :]
        d, i = knn.nearest(X.reshape(-1, 3))
        d, i = d.reshape(C, n), i.reshape(C, n)
        w = (d <= np.quantile(d, trim, axis=1)[:, None]).astype(float)
        s1, R1, t1 = _umeyama_batch(A, dst[i], w)
        ok = np.isfinite(s1) & (s1 > 0.5 * s_ref) & (s1 < 2.0 * s_ref) & (w.sum(1) >= 10)
        s = np.where(ok, s1, s)
        R = np.where(ok[:, None, None], R1, R)
        t = np.where(ok[:, None], t1, t)
    X = s[:, None, None] * np.einsum("cij,cnj->cni", R, A) + t[:, None, :]
    d, _ = knn.nearest(X.reshape(-1, 3))
    return s, R, t, d.reshape(C, n).mean(1)


def _voxel_sub(P, n_max, v0):
    """Voksel basina ilk nokta; voksel 1,3 kat buyutulerek <= n_max nokta."""
    v = v0
    while True:
        _, first = np.unique(np.floor(P / v).astype(np.int64), axis=0, return_index=True)
        if len(first) <= n_max:
            return P[np.sort(first)]
        v *= 1.3


def _curl_sign(sk, tL, RL, S):
    """Yerel Z etrafinda +10 derece Finger21 bukulmesi Finger22'yi avuc normaline yaklastiriyorsa +1 (tests/hand_variants.curl_sign)."""
    P0 = sk.fk(tL, RL)
    p = lambda n, P=P0: P[sk.index[f"SKEL_{S}_{n}"], :3, 3]
    h = p("Hand")
    x = p("Finger20") - h
    x = x / np.linalg.norm(x)
    y = p("Finger10") - p("Finger40")
    y = y - x * (y @ x)
    y = y / np.linalg.norm(y)
    z = np.cross(x, y) * (1.0 if S == "L" else -1.0)
    R2 = RL.copy()
    j = sk.index[f"SKEL_{S}_Finger21"]
    R2[j] = RL[j] @ axis_angle([0, 0, 1], np.radians(10.0))
    P1 = sk.fk(tL, R2)
    tip = sk.index[f"SKEL_{S}_Finger22"]
    return 1.0 if float((P1[tip, :3, 3] - P0[tip, :3, 3]) @ z) > 0 else -1.0


def _ref_hands(tpl, key):
    """-> {S: dict(R, h, L, augs=[(aci, el vertexleri (n,3), eklemler (16,3): Hand + 15 parmak)])}, onbellekli."""
    ck = (key, len(tpl.names), tuple(AUG_DEG))
    if ck in _CACHE:
        return _CACHE[ck]
    from .pipeline import load_reference
    Vr, _, WI, WV, rs = load_reference(key, tpl)
    tL, RL = rs.local_t(), rs.local_R()
    inv = np.linalg.inv(rs.W)
    sign = {S: _curl_sign(rs, tL, RL, S) for S in ("L", "R")}
    poses = {}
    for ang in AUG_DEG:
        RLa = RL.copy()
        if ang:
            for S in ("L", "R"):
                for f in FINGERS:
                    for j in range(3):
                        k = rs.index[f"SKEL_{S}_Finger{f}{j}"]
                        RLa[k] = RL[k] @ axis_angle([0, 0, 1], np.radians(sign[S] * ang))
        poses[ang] = rs.fk(tL, RLa)
    out = {}
    for S in ("L", "R"):
        cols = np.array([rs.index[f"SKEL_{S}_Hand"]] + [rs.index[f"SKEL_{S}_{j}"] for j in JOINTS])
        sel = (WV * np.isin(WI, cols)).sum(1) > 0.5
        hb, tip = rs.index[f"SKEL_{S}_Hand"], rs.index[f"SKEL_{S}_Finger22"]
        augs = []
        for ang, Pt in poses.items():
            Pa = lbs(Vr[sel], WI[sel], WV[sel], Pt @ inv) if ang else Vr[sel]
            augs.append((ang, np.asarray(Pa, float), Pt[cols, :3, 3]))
        out[S] = dict(R=rs.W[hb, :3, :3], h=rs.W[hb, :3, 3], L=float(np.linalg.norm(rs.W[tip, :3, 3] - rs.W[hb, :3, 3])), augs=augs)
    _CACHE[ck] = out
    return out


def hand_markers(V, markers, tpl, log=None, F=None):
    """markers (bilek + f22 + govde) -> gecici fit -> el basina sablon kaydi -> {S_f00..S_f42} ya da {}. F (ucgenler) verilirse ic testi
    (LAST out_tpl / out_core; IN_GATE acikken reddeder)."""
    from . import markers as mk
    from .fit import fit_skeleton
    try:
        fit = fit_skeleton(tpl, mk.expand_targets(tpl, markers))
    except (ValueError, KeyError):
        return {}
    V = np.asarray(V, float)
    refs = {k: _ref_hands(tpl, k) for k in REFS if k not in EXCLUDE}
    out, fits = {}, {}
    LAST.clear()
    Fa = np.asarray(F, np.int64) if F is not None and len(F) else None
    tri_c = V[Fa].mean(axis=1) if Fa is not None else None
    for S in ("L", "R"):
        if f"{S}_wrist" not in markers or f"{S}_f22" not in markers or not refs:
            continue
        hb = tpl.index[f"SKEL_{S}_Hand"]
        w0, t0 = fit.P_W[hb, :3, 3], fit.P_W[tpl.index[f"SKEL_{S}_Finger22"], :3, 3]
        L = float(np.linalg.norm(t0 - w0))
        if L < 1e-6:
            continue
        hax = (t0 - w0) / L
        near = np.sum((V - (w0 + t0) / 2) ** 2, axis=1) < (REGION * L) ** 2
        if near.sum() < 50:
            continue
        dst = V[near]
        knn = GridKNN(dst, cell=KNN_CELL * L)
        dst_s = dst if len(dst) <= SCREEN_DST else _voxel_sub(dst, SCREEN_DST, 0.01 * L)
        knn_s = knn if dst_s is dst else GridKNN(dst_s, cell=KNN_CELL * L)
        Rf = fit.P_W[hb, :3, :3]
        items, A, Rs, ts = [], [], [], []
        for key, rh in refs.items():
            r = rh[S]
            s0 = L / r["L"]
            for ai, (ang, Pa, _) in enumerate(r["augs"]):
                sub = Pa[np.linspace(0, len(Pa) - 1, SCREEN_PTS).astype(np.int64)]
                for roll in ROLL_DEG:
                    R0 = axis_angle(hax, np.radians(roll)) @ Rf @ r["R"].T
                    for sh in SHIFT_L:
                        items.append((key, ai, roll, ang, s0, sh))
                        A.append(sub)
                        Rs.append(R0)
                        ts.append(w0 + sh * L * hax - s0 * R0 @ r["h"])
        A, R, t = np.stack(A), np.stack(Rs), np.stack(ts)
        s_ref = np.array([it[4] for it in items])
        ang_a = np.array([it[3] for it in items])
        s = s_ref.copy()
        act = np.arange(len(items))
        for iters, frac in SCREEN_PLAN:
            s[act], R[act], t[act], res = _icp_batch(A[act], knn_s, dst_s, s[act], R[act], t[act], iters, TRIM, s_ref[act])
            act = act[np.argsort(_score(res, ang_a[act], s[act] / s_ref[act]))]
            act = act[:max(REFINE_TOP, int(np.ceil(frac * len(items))))] if frac > 0 else act[:REFINE_TOP]
        best = None
        for c in act:
            key, ai, roll, ang, s0, sh = items[c]
            _, Pa, Ja = refs[key][S]["augs"][ai]
            s1, R1, t1, r1 = _icp(Pa, knn, dst, float(s[c]), R[c], t[c], ITERS, TRIM)
            sc = float(_score(r1, ang, s1 / s0))
            if best is None or sc < best[0]:
                best = (sc, key, ang, roll, Ja * s1 @ R1.T + t1, r1, sh)
        if best is None:
            continue
        _, key, ang, roll, J, res, sh = best
        dev = [float(np.linalg.norm(J[7 + j] - np.asarray(markers[f"{S}_f2{j}"], float))) / L for j in range(3) if f"{S}_f2{j}" in markers]
        # mid_dev_L: sablon orta parmak zinciri <-> cekirdek yol (mesh ucundan) en buyuk sapma / el boyu (kapi tanisi)
        LAST[S] = dict(ref=key, aug=ang, roll=roll, shift=sh, res_mm=res * 1000, res_L=res / L, n_cand=len(items),
                       mid_dev_L=max(dev) if dev else None)
        if res / L > RES_GATE:
            if log:
                log(f"{S} hand template rejected (residual {res * 1000:.1f} mm)")
            continue
        if Fa is not None:
            # ic testi: dogru oturan elde eklemler parmagin icinde (kaynak rig'ler hep ic); bozuk oturmada sablon avucun altina kayar
            Fh = Fa[np.sum((tri_c - (w0 + t0) / 2) ** 2, axis=1) < (IN_RAD * L) ** 2]
            core = [markers.get(f"{S}_f{f}{j}", (np.nan,) * 3) for f in range(5) for j in range(3)]
            o_t, o_c = _outside(J[1:], V, Fh), _outside(core, V, Fh)
            LAST[S].update(out_tpl=o_t, out_core=o_c)
            if IN_GATE and _inside_reject(o_t, o_c):
                LAST[S]["rejected"] = "inside"
                if log:
                    log(f"{S} hand template rejected: its finger joints fall outside the hand mesh (kept the mesh-based fingers)")
                continue
        fits[S] = J
    ca = _core_asym(markers)
    for S in list(fits):
        o = "R" if S == "L" else "L"
        if IN_GATE and (LAST.get(o) or {}).get("rejected") == "inside" and ca is not None and ca[0] < IN_MIRROR:
            # simetrik karakterde el mesh'i aynali -> diger elin sablonu da ayni sekilde bozuk (olculdu: xbot R, readyplayerme R)
            LAST[S].update(rejected="inside_mirror", asym_core_L=ca[0])
            del fits[S]
            if log:
                log(f"{S} hand template rejected: the other hand failed the inside check (kept the mesh-based fingers)")
    rej = _symmetry_reject(fits, markers)
    for S, J in fits.items():
        if S in rej:
            LAST[S]["rejected"] = "symmetry"
            if log:
                log(f"{S} hand template rejected: it does not mirror the other hand (kept the mesh-based fingers)")
            continue
        for f in range(5):
            for j in range(3):
                out[f"{S}_f{f}{j}"] = J[1 + 3 * f + j]
    return out
