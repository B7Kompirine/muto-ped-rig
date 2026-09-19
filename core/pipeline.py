"""Uctan uca agirlik hatti (Blender'siz): referans govde aktarimi + kurallar + kemik birlestirme."""
import os
import re
import numpy as np
from .skeleton import Skeleton, complete_skeleton, map_to_canon
from .fit import fit_skeleton
from . import transfer as tr
from . import weights as wt
from . import voxel as vx

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def remap_rules(names, merge_face=True, merge_roll=False, merge_mh=False, merge_other=True, merge_fingers=False):
    """Kemik adi -> hedef ad (birlestirme). Yuz kapaliysa FB_/FACIAL_ -> SKEL_Head; parmaklar kapaliysa Finger* -> ayni tarafin SKEL_*_Hand."""
    rules = {}
    for n in names:
        m = re.match(r"SKEL_([LR])_Finger\d\d$", n)
        if merge_fingers and m:
            rules[n] = f"SKEL_{m.group(1)}_Hand"
            continue
        if merge_face and (n.startswith("FB_") or n.startswith("FACIAL_")):
            rules[n] = "SKEL_Head"
        elif merge_roll and n.startswith("RB_"):
            rules[n] = {"RB_Neck_1": "SKEL_Neck_1"}.get(n, n.replace("RB_", "SKEL_").replace("ForeArmRoll", "Forearm")
                                                        .replace("ArmRoll", "UpperArm").replace("ThighRoll", "Thigh"))
        elif merge_mh and n.startswith("MH_"):
            rules[n] = None  # ebeveyn SKEL
        elif merge_other and n.startswith(("SM_", "SPR_", "EO_")):
            rules[n] = None
    return rules


def apply_remap(W, skel, rules):
    W = W.copy()
    for n, dst in rules.items():
        j = skel.index[n]
        if not W[:, j].any():
            continue
        if dst is None:
            p = skel.parents[j]
            while p >= 0 and not skel.names[p].startswith("SKEL_"):
                p = skel.parents[p]
            dst = skel.names[p]
        W[:, skel.index[dst]] += W[:, j]
        W[:, j] = 0.0
    return W


def load_reference(key, tpl, data_dir=None):
    d = data_dir or DATA
    r = np.load(os.path.join(d, f"ref_{key}.npz"))
    rs = Skeleton.from_json(os.path.join(d, f"template_{key}.json"))
    remap = map_to_canon(rs, tpl)
    full, missing = complete_skeleton(rs, tpl)
    WV = r["WV"]
    s = WV.sum(1, keepdims=True)   # ambient iskelette FB_ yok -> atilan yuz agirligi kalanlara (SKEL_Head) dagilir
    WV = np.where(s > 0, WV / np.maximum(s, 1e-12), WV)
    return r["V"], r["F"], remap[r["WI"]], WV, full


def transfer_single(Vt, Ft, tpl, targets, ref_key, target_skel, adapt_iters=1, data_dir=None, log=print):
    """Tek referans aktarimi + kalinlik uyarlamasi. target_skel: hedefin P iskeleti (Skeleton).
    Donus: W (N,B) orijinal indekslerde, dist, uygulanan genislik carpanlari."""
    Vr, Fr, WIr, WVr, ref_skel = load_reference(ref_key, tpl, data_dir)
    fr = fit_skeleton(ref_skel, targets)
    Vw, Fw, inv = vx.weld(Vt, Ft)
    B = len(tpl.names)
    Wr_full = np.zeros((len(Vr), B))
    for k in range(WIr.shape[1]):
        np.add.at(Wr_full, (np.arange(len(Vr)), WIr[:, k]), WVr[:, k])
    r_ref = tr.measure_radii(Vr, Wr_full, ref_skel)
    sc = fr.scale.copy()
    widths = np.ones(B)
    W = dist = None
    for it in range(adapt_iters + 1):
        Vrd = tr.deform_reference(Vr, WIr, WVr, ref_skel.W, fr.P_W, sc)
        W, dist, _ = tr.transfer_weights(Vw, Fw, Vrd, Fr, WIr, WVr, B)
        if it == adapt_iters:
            break
        r_tgt = tr.measure_radii(Vw, W, target_skel)
        widths = tr.width_factors(r_tgt, r_ref, ref_skel)
        # referansin kendi olcegi (fit) uzerine kalinlik: yalniz y/z (uzunluk ekseni x korunur)
        sc = fr.scale.copy()
        sc[:, 1] *= widths
        sc[:, 2] *= widths
    return W[inv], dist[inv], widths


def transfer_from_refs(Vt, Ft, tpl, targets, ref_keys, scale=1.0, sigma=0.015, data_dir=None, log=print):
    """Coklu referans govde: her referans kendi iskeletiyle hedefe esnetilir, vertex basina birlestirilir.
    targets: {SKEL_*: konum} (hedefin P eklemleri). Donus: dict(soft, nearest, dists (R,N), per_ref [W])."""
    Vw, Fw, inv = vx.weld(Vt, Ft)
    per, dists = [], []
    for key in ref_keys:
        Vr, Fr, WIr, WVr, ref_skel = load_reference(key, tpl, data_dir)
        fr = fit_skeleton(ref_skel, targets)
        Vrd = tr.deform_reference(Vr, WIr, WVr, ref_skel.W, fr.P_W, fr.scale)
        W, dist, _ = tr.transfer_weights(Vw, Fw, Vrd, Fr, WIr, WVr, len(tpl.names))
        per.append(W)
        dists.append(dist)
    D = np.stack(dists)                                   # (R, N)
    near = D.argmin(0)
    W_near = np.stack(per)[near, np.arange(len(Vw))]
    dmin = D.min(0, keepdims=True)
    s = sigma * scale
    wr = np.exp(-((D - dmin) / s) ** 2)                   # en yakina gore goreli: uzak govdeler soner
    W_soft = np.einsum("rn,rnb->nb", wr, np.stack(per)) / wr.sum(0)[:, None]
    return dict(soft=W_soft[inv], nearest=W_near[inv], dists=D[:, inv], per_ref=[p[inv] for p in per],
                weld=(Vw, Fw, inv))


FREEMODE_REFS = ("mp_m", "mp_f")


def available_refs(data_dir=None):
    d = data_dir or DATA
    keys = sorted(f[4:-4] for f in os.listdir(d) if f.startswith("ref_") and f.endswith(".npz"))
    return [k for k in keys if os.path.exists(os.path.join(d, f"template_{k}.json"))]


def head_subtree(tpl):
    ids = {tpl.index["SKEL_Head"]}
    for i in range(len(tpl.names)):              # parent index < cocuk index
        if tpl.parents[i] in ids:
            ids.add(i)
    return np.array(sorted(ids))


def _ray_hits(orig, d, V, F):
    """orig'den d yonunde isinin ucgenleri kac kez kestigi (Moller-Trumbore, vektorel)."""
    v0 = V[F[:, 0]]
    e1, e2 = V[F[:, 1]] - v0, V[F[:, 2]] - v0
    p = np.cross(d, e2)
    det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = orig - v0
    u = (s * p).sum(1) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = (e2 * q).sum(1) * inv
    return int((ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0)).sum())


# sac agirligi = Head/Spine3 yukseklik rampasi. 5 Rockstar sac cizimi GT ortalamasi (a_f_*: fitness/topless/fatwhite uzun,
# bodybuild/yoga kisa; t = (z - boyun) / (kafa - boyun)): t>=1 Head 1.00 · 0.5-1 0.92 · 0-0.5 0.58 · boyun alti 0.37,
# kalan Spine3 (Neck_1 hic yok). Sanatci farki buyuk: topless uzun sac boyun altinda Spine3 0.83.
HAIR_RAMP = (0.4, 1.2)          # Head = clip(a + b*t, a, 1)


# Sac/sapka parca kapisi (2026-09-12): parcali govdede (Xbot eklem/kol kabuklari, Soldier omuz zirhi) kafa ustune cikan govde parcalari
# sac sayilip Head'e gidiyordu (Xbot 15 bin vertex, kol bolge uyumu %0). Olcum (parca basina kafa eklemine yatay mesafe %95 / boy):
# 5 sacli vanilla kadin sac <= 0.105 (en uzun parca 0.118), Michelle sac 0.150, RPM sac/sapka <= 0.111; Soldier omuz zirhi 0.215,
# Xbot kol parcalari 0.24-0.41. Parca en alti: vanilla sac boyun - 0.093 H'ye kadar iner; Soldier gogus zirhi boyun - 0.185 H.
HAIR_MAX_HORIZ = 0.18
HAIR_BELOW_NECK = 0.12


def head_attached_parts(W, Vw, Fw, tpl, fit):
    """Govdeden AYRI, tepesi kafa ekleminin ustunde ve kafa eklemini ICINE ALMAYAN parcalar (sac teli, sapka, gozluk):
    agirlik Head/Spine3 yukseklik rampasi. Ayri modellenmis kafa objesi eklemi icine alir (4 yatay isin tek sayida
    keser) -> dokunulmaz. Tuzak: sirta sarkan at kuyruguna en yakin referans yuzeyi sirt -> Spine3 %93, kafa donunce
    sac yerinde kaliyordu; aktarilan agirlik cogunlugu da bu yuzden parca secimine yaramaz."""
    lab = vx.mesh_components(len(Vw), Fw)
    sizes = np.bincount(lab)
    body = int(np.argmax(sizes))
    ih, i_n, i_s3 = tpl.index["SKEL_Head"], tpl.index["SKEL_Neck_1"], tpl.index["SKEL_Spine3"]
    p_head = fit.P_W[ih, :3, 3]
    z_neck = fit.P_W[i_n, 2, 3]
    top = np.full(len(sizes), -np.inf)
    np.maximum.at(top, lab, Vw[:, 2])
    dirs = np.array([[1.0, 0, 0], [-1.0, 0, 0], [0, 1.0, 0], [0, -1.0, 0]])
    fl = lab[Fw[:, 0]]
    H = float(np.ptp(Vw[:, 2]))
    low = np.full(len(sizes), np.inf)
    np.minimum.at(low, lab, Vw[:, 2])
    hd = np.linalg.norm(Vw[:, :2] - p_head[:2], axis=1)
    comps = []
    for c in np.nonzero((top > p_head[2]) & (np.arange(len(sizes)) != body))[0]:
        if low[c] < z_neck - HAIR_BELOW_NECK * H or np.percentile(hd[lab == c], 95) > HAIR_MAX_HORIZ * H:
            continue                            # govde parcasi (omuz/kol zirhi, gogus kabugu): sac/sapka degil
        Fc = Fw[fl == c]
        if len(Fc) and all(_ray_hits(p_head, d, Vw, Fc) % 2 == 1 for d in dirs):
            continue                            # kafa eklemini sariyor: ayri kafa objesi
        comps.append(c)
    if not comps:
        return W, 0
    vid = np.nonzero(np.isin(lab, comps))[0]
    t = (Vw[vid, 2] - z_neck) / max(p_head[2] - z_neck, 1e-6)
    a, b = HAIR_RAMP
    wh = np.clip(a + b * t, a, 1.0)
    W = W.copy()
    W[vid] = 0.0
    W[vid, ih] = wh
    W[vid, i_s3] = 1.0 - wh
    return W, len(vid)


def transfer_pipeline(Vt, Ft, tpl, fit, ref_key="auto", merge_face=True, merge_roll=False,
                      merge_mh=False, use_votes=True, lam=0.8, data_dir=None, exclude=(), head_parts=True, fill=True, fill_near=0.02, fill_far=0.07, islands=True, fill_groups="arms",
                      merge_fingers=False, log=print):
    """Hedef mesh (P pozunda) icin yogun agirlik (N, B) + temel referans mesafesi.

    Olculmus hat (birini-disarida-birak, 12 vanilla govde, 2026-09-11):
      temel = uyumlu freemode govdesi (RB_/MH_ dagilimi tasir) ; 12 govde UZUV oylar ; oy yuzeyde yumusar (lam 0.8)
      -> azinlik uzvun kemikleri soner ; taraf kisiti ; L/R cozumu ; guvensiz vertex yuzeyden doldurulur.
    Bellek: referans basina yalniz baskin uzuv + mesafe + top-4 saklanir (200k vertex x 12 referans)."""
    import time
    t0 = time.time()
    B = len(tpl.names)
    main = [n for n in tpl.names if n.startswith("SKEL_")]
    targets = {n: fit.P_W[tpl.index[n], :3, 3] for n in main}
    Vw, Fw, inv = vx.weld(Vt, Ft)
    edges = wt.mesh_edges(Fw)
    refs = [k for k in available_refs(data_dir) if k not in exclude]     # exclude: testte hedef govdenin kendisi
    if not use_votes:
        refs = [ref_key] if ref_key != "auto" else [k for k in refs if k in FREEMODE_REFS]
    grp = tr.bone_groups(tpl.names)
    dists, doms, sparse, dense = [], [], [], {}
    for key in refs:
        Vr, Fr, WIr, WVr, ref_skel = load_reference(key, tpl, data_dir)
        fr = fit_skeleton(ref_skel, targets)
        Vrd = tr.deform_reference(Vr, WIr, WVr, ref_skel.W, fr.P_W, fr.scale)
        if key in FREEMODE_REFS or key == ref_key:
            # temel aday: yon filtreli tam aktarim (k=48)
            # ornek araligi govde olcegiyle: cm birimli girdide sabit 4 mm ucgen basina 64 ornek sinirina dayandi (3.7 -> 64 s)
            W, dist, _ = tr.transfer_weights(Vw, Fw, Vrd, Fr, WIr, WVr, B, spacing=0.004 * fit.g)
            G = np.stack([W[:, grp == g].sum(1) for g in range(len(tr.GROUP_NAMES))], axis=1)
            dom = G.argmax(1).astype(np.int8)
            idx = np.argpartition(-W, 3, axis=1)[:, :4]
            sp = (idx.astype(np.int32), np.take_along_axis(W, idx, 1).astype(np.float32))
            dense[key] = W.astype(np.float32)
        else:
            # oy veren: en yakin yuzey noktasi yeterli (BVH, sorgu basina tek C cagrisi)
            dom, dist, sp = tr.transfer_dominant(Vw, Vrd, Fr, WIr, WVr, B, grp)
        doms.append(dom)
        dists.append(np.asarray(dist, np.float32))
        sparse.append(sp)
    D = np.stack(dists)
    med = {k: float(np.median(D[i])) for i, k in enumerate(refs)}
    base = ref_key if ref_key != "auto" else min((k for k in dense if k in FREEMODE_REFS), key=lambda k: med[k])
    W = dense[base].astype(np.float64)
    dist = D[refs.index(base)]
    if use_votes and len(refs) > 1:
        P, agree, om = tr.votes_from_doms(doms, D, sigma=0.015 * fit.g)
        # REDDEDILDI (2026-09-13, Blender bone-heat / Auto-Rig Pro fikri, out/arp_study/BULGULAR.md #1): uzuv oyuna kemik GORUNURLUK
        # kapisi. 12 vanilla govde LOO: normal testi (en yakin kemik noktasi yuzeyin onunde, cos > tau) net vertexin GT grubunu %8-11
        # yanlis eler; ucgen isin testi %25-59 engelli; ikisi birlikte %4.6-12.5 ve 530 kotu vertexin en cok 63'unu kurtarir.
        # Sert kapi + yuzey doldurma: %95 0.71 -> 0.84 (kotu), max ort 132 -> 115 (genfat bel yani 261 -> 177).
        P = tr.smooth_probs(P, edges, lam=lam)
        Wg = W * P[:, grp]
        s = Wg.sum(1)
        bad = np.nonzero(s < 1e-3)[0]
        W = Wg / np.maximum(s, 1e-12)[:, None]
        if len(bad):
            W[bad] = tr.consensus_from_sparse(sparse, agree, om, B, bad)
        log(f"  uzuv oylamasi: {len(refs)} govde, kararsiz vertex %{(P.max(1) < 0.75).mean()*100:.1f}")
    if head_parts:
        W, n_hp = head_attached_parts(W, Vw, Fw, tpl, fit)
        if n_hp:
            log(f"  kafaya bagli ayri parca (sac/sapka): {n_hp} vertex kafa+boyun bolgesinden aktarildi")
    midx = fit.P_W[tpl.index["SKEL_Spine2"], 0, 3]
    W = tr.side_clamp(W, tpl.names, Vw, midx)
    W = tr.lr_resolve(W, tpl.names, Vw, fit.P)
    # doldurma (12 govde LOO, GT eklem, 2026-09-11; %95 ort / en kotu max mm):
    #   tum vertexlerde mesafe guveni (eski) 0.94 / 308 · doldurma yok 0.72 / 362 · uzuv adaciklari + YALNIZ kol etiketinde
    #   mesafe guveni 0.71 / 261 (secilen). Tuzak: sisman uylugun referanstan 7+ cm uzak bolgesi komsu ortalamasiyla
    #   Thigh 0.4 / Calf 0.3 / Pelvis 0.3 oluyordu (GT Thigh 1.0); kola degen bel yani ise mesafe dolgusuyla duzeliyordu.
    conf = tr.confidence(dist, fit.g, near=fill_near, far=fill_far) if fill else np.ones(len(W))
    if fill and fill_groups == "arms":
        # yalniz kol etiketli vertexlerde mesafe guveni: sisman uylugun uzak bolgesi (bacak) harmanlanmasin
        Gd = np.stack([W[:, grp == g].sum(1) for g in range(len(tr.GROUP_NAMES))], axis=1).argmax(1)
        conf = np.where((Gd == 1) | (Gd == 2), conf, 1.0)
    if islands:
        bad = tr.group_islands(W, edges, grp, vx.mesh_components(len(Vw), Fw))
        conf = np.where(bad, 0.0, conf)
        log(f"  uzuv adaciklari: {int(bad.sum())} vertex yuzey komsularindan dolduruldu")
    if fill or islands:
        W = wt.graph_fill(W, conf, edges)
    # REDDEDILDI (2026-09-12): ayni parcadaki kafa ustunu (tac/migfer) Head'e karistirma. Vanilla LOO %95 0.71 -> 0.71, sentetik sac
    # Head 0.863 ayni, sauron (dogru marker) boyun_kafa %95 70.3 -> 70.3 mm: fark kafa ustunde degil, boyun ALTINDAKI yakada
    # (orijinal modcu miğfer + yakayi Head'e baglamis) -> uslup farki, kural etkisiz.
    # REDDEDILDI (2026-09-11): ayri giysi parcasina alttaki govdenin agirligini tasima (k=8 normal uyumlu ters mesafe). Sentetik bol
    # pantolonda (t_synth_e2e shell=pants shell_off=0.05, kaynak vertex'le birebir eslesme) poz boslugu degisimi %95 4.0 -> 6.1 mm,
    # max 7.2 -> 29.7 mm kotulesti; 12 vanilla govde LOO %95 0.71 -> 0.74. Referans aktarimi ayri giysiyi zaten govdeyle tasiyor.
    W = apply_remap(W, tpl, remap_rules(tpl.names, merge_face, merge_roll, merge_mh, merge_fingers=merge_fingers))
    log(f"  aktarim: temel={base}, {len(Vw)} birlesik vertex, referansa mesafe %95 {np.percentile(dist, 95)*1000:.1f} mm, "
        f"guven<0.5 %{(conf < 0.5).mean()*100:.1f}, {time.time()-t0:.1f}s")
    return W[inv], dist[inv]


def animal_refs(data_dir, tpl):
    """data_dir'deki ayni iskelet ailesinden (species.family) referans anahtarlari."""
    from .species import family
    fam = family(tpl)
    keys = sorted(f[4:-4] for f in os.listdir(data_dir) if f.startswith("ref_") and f.endswith(".npz"))
    return [k for k in keys if os.path.exists(os.path.join(data_dir, f"template_{k}.json"))
            and family(Skeleton.from_json(os.path.join(data_dir, f"template_{k}.json"))) == fam]


ANIMAL_BEST_MM = 18.0     # auto: en yakin referansin medyan mesafesi bunun (x g) altindaysa tek referans, ustundeyse harman + son islem
# On bacak alt zinciri yeniden paylastirma — VARSAYILAN KAPALI (2026-09-13). LOO (paw_chain_ab / ab2, 11 ayri mesh, 11 tek eklem pozu):
# konum %95 11,68 -> 11,15, on bacak kotu kenar % 1,640 -> 1,448, kotulesen hedef 0. Tani: aktarilan kemik SINIRI yakin kemige kaymis
# (Hand vertexlerinin %22'si Forearm). AMA Sollumz emote (gercek klipler, 4 klip ort. en kotu kare kotu kenar %; zincirsiz / m 0,15 /
# m 0,35 / m 0,15 yari): cakal 12,79 / 13,11 / 13,03 / 13,26, geyik 11,32 / 10,66 / 11,86 / 11,26 -> cakal hicbir varyantta
# duzelmiyor (gerilme ayak ucundan on kola kayiyor) -> REDDEDILDI. Ayrica REDDEDILDI: arka bacak alt zinciri (LOO 3 hedef kotu), ust
# zincirler (diz pozu 7,1 -> 9,7), eski agirlikla yari karisim (LOO + emote kotu).
ANIMAL_FRONT_CHAINS = (("Forearm", "Hand", "Finger00", "Finger01"),)
ANIMAL_LIMB_CHAINS = None
ANIMAL_LIMB_MARGIN = 0.15


def rechain_limbs(W, V, tpl, P, chains=ANIMAL_FRONT_CHAINS, m=ANIMAL_LIMB_MARGIN):
    """Zincir vertexi (zincir kemik payi > 0,5) hedef iskeletin zincir segmentlerine izdusumle: segment ici -> o kemik, eklemin +-m
    cevresi -> iki kemik dogrusal karisim. Zincir disi agirlik ve zincir payi korunur. P: hedef eklem konumlari (B,3)."""
    W = W.copy()
    for S in ("L", "R"):
        for chain in chains:
            ids = [tpl.index[f"SKEL_{S}_{c}"] for c in chain]
            pts = [P[i] for i in ids]
            pts.append(pts[-1] + 0.75 * (pts[-1] - pts[-2]))            # son kemigin ucu (weights.bone_segments ile ayni)
            share = W[:, ids].sum(1)
            sel = np.nonzero(share > 0.5)[0]
            if not len(sel):
                continue
            X, C = V[sel], len(ids)
            D = np.full((len(sel), C), np.inf)
            T = np.zeros((len(sel), C))
            for k in range(C):
                ab = pts[k + 1] - pts[k]
                traw = ((X - pts[k]) @ ab) / max(float(ab @ ab), 1e-12)
                t = np.clip(traw, 0, 1)
                D[:, k] = np.linalg.norm(X - (pts[k] + t[:, None] * ab), axis=1)
                T[:, k] = traw
            rows = np.arange(len(sel))
            k = D.argmin(1)
            t = T[rows, k]
            up = (t < m) & (k > 0)
            dn = (t > 1 - m) & (k < C - 1) & ~up
            mid = ~(up | dn)
            new = np.zeros((len(sel), C))
            new[rows[mid], k[mid]] = 1.0
            wu = 0.5 + 0.5 * np.maximum(t[up], 0.0) / m
            new[rows[up], k[up]], new[rows[up], k[up] - 1] = wu, 1 - wu
            wd = 0.5 + 0.5 * np.maximum(1 - t[dn], 0.0) / m
            new[rows[dn], k[dn]], new[rows[dn], k[dn] + 1] = wd, 1 - wd
            W[np.ix_(sel, ids)] = new * share[sel, None]
    return W


# Bas bolgesi yerel afin aktarim (2026-09-13, scratchpad head_affine_ab / ab2, out/animals/head_affine_ab*_0913.txt; oracle iskelet,
# 11 hayvan, pozlar FB_Jaw 3 eksen + Head). Tani: global aktarim cogu hayvanda alt ceneyi SKEL_Head'e veriyor (GT FB_Jaw vertexlerinin
# FB_Jaw orani: boar / coyote / deer / mtlion %0, cow %3, pig %5, retriever %11, shepherd %22; iyi yalniz husky %49, rottweiler %89).
# Yontem: her referansin bas bolgesi (Head / FB_) yuz eklemleri uzerinden en kucuk kareler afiniyle hedef yuz eklemlerine tasinir, bas
# vertexleri en yakin yuzeyden alir, bas vertexi medyan mesafesi en kucuk tek referans. Cene uyumu %16,3 -> 57,9, poz %95 30,27 ->
# 21,72, AMA rottweiler 6,9 -> 12,0. Koruma: tabanda bas vertexlerinin FB_Jaw baskin orani >= ANIMAL_HEAD_JAW_Q ise (global aktarim
# ceneyi zaten bulmus) dokunulmaz; rottweiler %23 / husky %24 korunur -> hedef basina degerlerden %59,9 / 22,53, kotulesen 0.
# ESIK AYNI VERIDEN (coyote %14 ile rottweiler %23 arasi). REDDEDILDI: secimi bas vertexi referans mesafesiyle yapmak (afini yalniz
# rottweiler'da seciyor; ort 30,74).
# KORUMA KALDIRILDI (2026-09-14, scratchpad head_affine_q_rest.py): referans fit'i yardimci kemikte izotrop olunca (fit_skeleton aux_iso)
# genel aktarimin cene payi degisti ve artik ayirmiyor: geyik %22,4 / husky %24,0 / cakal %28,9'da afin IYI (yuz pozu %95 8,4 -> 5,4 /
# 29,1 -> 15,1 / 25,9 -> 6,3), rottweiler %23,2'de KOTU (6,9 -> 12,0). 11 hedef cene uyumu % / yuz %95 mm: q 0,2 %54,7 / 23,30 · hep afin
# %60,1 / 20,44 (duzeltme oncesi kod %59,9 / 22,52). 1,0 = her zaman (tamamen cene olan bas kumesi haric).
ANIMAL_HEAD_AFFINE = True
ANIMAL_HEAD_JAW_Q = 1.0
ANIMAL_FACE_JOINTS = ("SKEL_Head", "FB_Jaw", "FB_L_Eye", "FB_R_Eye", "FB_L_Ear", "FB_R_Ear", "FB_L_Lip_Corner", "FB_R_Lip_Corner",
                      "FB_Brow_Centre", "FB_L_CheekBone", "FB_R_CheekBone", "FB_L_Brow_Out", "FB_R_Brow_Out")


def head_affine_weights(W, Vw, Fw, tpl, fit, refs_data, jaw_q=ANIMAL_HEAD_JAW_Q):
    """W (birlesik uzay) bas vertexlerini referans bas afin aktarimiyla degistir. refs_data: [(Vr, Fr, WIr, WVr, ref_skel)].
    Donus: (W, uygulandi mi, taban cene payi)."""
    ij = tpl.index.get("FB_Jaw")
    headset = np.array([n == "SKEL_Head" or n.startswith("FB_") for n in tpl.names])
    hv = headset[W.argmax(1)]
    if ij is None or not hv.any():
        return W, False, 0.0
    share = float((W[hv].argmax(1) == ij).mean())
    if share >= jaw_q:
        return W, False, share
    tj = [n for n in ANIMAL_FACE_JOINTS if n in tpl.index]
    best, best_med = None, np.inf
    for Vr, Fr, WIr, WVr, rs in refs_data:
        common = [n for n in tj if n in rs.index]
        if len(common) < 6:
            continue
        src = np.hstack([rs.pos[[rs.index[n] for n in common]], np.ones((len(common), 1))])
        A, *_ = np.linalg.lstsq(src, fit.P_W[[tpl.index[n] for n in common], :3, 3], rcond=None)
        top = WIr[np.arange(len(Vr)), WVr.argmax(1)]
        Vd = np.hstack([Vr, np.ones((len(Vr), 1))]) @ A
        Vd[~headset[top]] += 1000.0                                   # bas disi referans yuzeyi sorguya karismasin
        Wr, dist, _ = tr.transfer_weights(Vw, Fw, Vd, Fr, WIr, WVr, len(tpl.names), spacing=0.004 * fit.g)
        m = float(np.median(dist[hv]))
        if m < best_med:
            best, best_med = Wr, m
    if best is None:
        return W, False, share
    W = W.copy()
    W[hv] = best[hv]
    return W, True, share


def animal_transfer_pipeline(Vt, Ft, tpl, fit, data_dir, exclude=(), mode="auto", post=True, merge_face=False, tail_blend=True,
                             limb_chains=ANIMAL_LIMB_CHAINS, head_affine=ANIMAL_HEAD_AFFINE, log=print):
    """Hayvan hedefi: ayni ailedeki oyun hayvanlarinin agirliklari hedef iskelete esnetilip aktarilir. Donus: W (N,B), mesafe (N,).

    Olcek: referans IZOTROP global olcekle (fit.g) esnetilir. fit.scale eksen olcekleri hayvan referansinda patliyor: domuz -> yaban domuzu
    omurga z 8,25, deforme referans 2 m yukari tasti (poz %95 123 mm; izotrop 26; puma <- rottweiler 139 -> 12; 2026-09-13).
    mode: 'soft' referans mesafesine gore harman (+ post), 'best' medyan mesafesi en kucuk tek referans, 'auto' ikisinden biri.
    Olculdu (LOO, 11 ayri oyun hayvani mesh'i, oracle iskelet, 11 poz, %95 / max ort mm): tek en iyi 13,44 / 254, harman+son 13,97 / 212,
    auto 11,62 / 235 (harman: yaban domuzu x2, inek; en yakin medyan 20-31 mm, digerleri 7-15). ESIK AYNI VERIDEN secildi (15,4 ile 20,1
    arasi bosluk).
    tail_blend (LOO v2, out/animals/loo_weights_v2_0913): tek referansta kuyruk %95 46,5; tek referans + harman+son'un KUYRUK kemik
    payiyla yumusak karisimi 12,9 (genel 13,44 -> 13,20, max 254 -> 227). Auto ile birlikte hedef basina degerlerden 11,68 / 208 (auto
    11,62 / 235). REDDEDILDI: ayni karisimi on bacaga da uygulamak (auto_hibrit 11,89; ayni rest'li kopeklerde bozuyor, husky 0,7 -> 3,6)."""
    import time
    t0 = time.time()
    B = len(tpl.names)
    targets = {n: fit.P_W[tpl.index[n], :3, 3] for n in tpl.names if n.startswith("SKEL_")}
    Vw, Fw, inv = vx.weld(Vt, Ft)
    refs = [k for k in animal_refs(data_dir, tpl) if k not in exclude]
    if not refs:
        raise ValueError("no animal weight references found")
    per, dists = [], []
    for key in refs:
        Vr, Fr, WIr, WVr, ref_skel = load_reference(key, tpl, data_dir)
        fr = fit_skeleton(ref_skel, targets, aux_iso=True)      # yardimci (FB_) kemik de izotrop: fit_skeleton aux_iso notu
        Vrd = tr.deform_reference(Vr, WIr, WVr, ref_skel.W, fr.P_W, np.full_like(fr.scale, fr.g))
        W, dist, _ = tr.transfer_weights(Vw, Fw, Vrd, Fr, WIr, WVr, B, spacing=0.004 * fit.g)
        per.append(W)
        dists.append(dist)
    D = np.stack(dists)
    med = np.median(D, axis=1)
    dist = D.min(0)
    if mode == "auto":
        mode = "best" if med.min() < ANIMAL_BEST_MM / 1000 * fit.g else "soft"
    W_soft = None
    if mode == "soft" or tail_blend:
        wr = np.exp(-((D - dist[None]) / (0.015 * fit.g)) ** 2)
        W_soft = np.einsum("rn,rnb->nb", wr, np.stack(per)) / wr.sum(0)[:, None]
        if post:
            edges = wt.mesh_edges(Fw)
            W_soft = tr.side_clamp(W_soft, tpl.names, Vw, fit.P_W[tpl.index["SKEL_Spine2"], 0, 3])
            W_soft = tr.lr_resolve(W_soft, tpl.names, Vw, fit.P)
            bad = tr.group_islands(W_soft, edges, tr.bone_groups(tpl.names), vx.mesh_components(len(Vw), Fw))
            W_soft = wt.graph_fill(W_soft, np.where(bad, 0.0, tr.confidence(dist, fit.g)), edges)
    if mode == "best":
        W = per[int(med.argmin())]                      # olculen varyant: tek referans son islemsiz
        if tail_blend:
            tail = np.array(["Tail" in n for n in tpl.names])
            a = W_soft[:, tail].sum(1, keepdims=True)   # harmanin kuyruk kemik payi kadar harmana gecilir
            W = a * W_soft + (1 - a) * W
    else:
        W = W_soft
    # merge_face=True REDDEDILDI (2026-09-13, emote toplam kotu kenar: yaban domuzu 12,876 -> 12,901, cakal / geyik ayni): domuz cene
    # yirtilmasi yuzden boyun_kafa'ya kaydi; kok neden FB_Jaw'in oynamasi degil, cene vertexlerinin Head + kismi FB_Jaw karisimi
    W = apply_remap(W, tpl, remap_rules(tpl.names, merge_face=merge_face))
    if limb_chains:
        W = rechain_limbs(W, Vw, tpl, fit.P_W[:, :3, 3], limb_chains)   # birlesik vertex = ayni konum -> orijinalle esdeger
    head_note = ""
    if head_affine and not merge_face:
        W, applied, share = head_affine_weights(W, Vw, Fw, tpl, fit, [load_reference(k, tpl, data_dir) for k in refs])
        head_note = f", bas afin {'uygulandi' if applied else 'atlandi'} (taban cene payi %{share * 100:.0f})"
    log(f"  hayvan aktarimi: {len(refs)} referans ({mode}), en yakin {refs[int(med.argmin())]} med {med.min()*1000:.1f} mm, "
        f"{len(Vw)} birlesik vertex{head_note}, {time.time()-t0:.1f}s")
    return W[inv], dist[inv]


def voxel_pipeline(Vt, Ft, tpl, fit, merge_roll=False, log=print):
    names, W = wt.compute_weights(Vt, Ft, fit.P, alpha=0.5, ratio_k=1.3, power=4.0, smooth_iters=0,
                                  roll_split=not merge_roll, log=log)
    full = np.zeros((len(Vt), len(tpl.names)))
    for j, n in enumerate(names):
        full[:, tpl.index[n]] = W[:, j]
    return full, None


def finalize(W, tpl):
    """GTA kurallari: <=4 etki, 1/255, toplam 1, bos yok. Donus: idx (N,4) sablon indeksi, val (N,4)."""
    return wt.gta_rules(W, 4)
