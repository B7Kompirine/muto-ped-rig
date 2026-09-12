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


TARGET_HEIGHT = 1.8          # birim oranina uymayan boy bu boya olceklenir (GTA ped ~1,8 m)
UPSIDE_DOWN_CHECK = True


def _upside_down(V, lo, hi, H):
    """Bas asagi (kural v3, 2026-09-12; 36 vanilla + 80 gercek dokum, dik + X'te 180 cevrilmis kopyalar, scratchpad/an_upside_cues2.py):
    vertex agirlik merkezi yuksekligi < 0,50 H (dik 0,46-0,75, ters 0,25-0,54) VE su uc ipucundan en az biri:
      genislik(0,1-0,4 H) > 1,1 x genislik(0,6-0,9 H)   (omuz/kol asagida)
      ust %1 dilim vertex sayisi > 2 x alt %1 dilim     (duz taban ustte)
      ust %4 dilimin xy kapladigi alan > 2 x alttakinin (ayak izi ustte)
    Sonuc: dik yanlis alarm 0/116, ters yakalanan vanilla 34/36 (beach/musclbeac gobek agirlikli govdeler, merkez 0,46-0,54) + gercek 80/80.
    Eski kurallar: v1 (ustte iki kume + altta degil) gercek 56/80 — Michelle sac topuzu kafa ustunde de iki kume; v2 (bosluk + genislik 1,3)
    65/80 — tek bacak uzun / kisa bacak varyantlari. Sketchfab Goblin gövde+balta bas asagi: merkez 0,333, genislik 2,95 -> yakalanir."""
    n = len(V)
    if n < 50 or H <= 1e-9:
        return False
    rel = (V[:, 2] - lo[2]) / H
    if float(rel.mean()) >= 0.50:
        return False

    def width(a, b):
        m = (rel > a) & (rel < b)
        return float(np.percentile(V[m, 0], 98) - np.percentile(V[m, 0], 2)) if m.sum() > 20 else 0.0

    def area(sel):
        return float(np.ptp(sel[:, 0]) * np.ptp(sel[:, 1])) if len(sel) >= 10 else 0.0
    w_lo, w_hi = width(0.1, 0.4), width(0.6, 0.9)
    wide = w_hi > 0 and w_lo > 1.1 * w_hi
    flat = (int((rel > 0.99).sum()) + 1) > 2 * (int((rel < 0.01).sum()) + 1)
    top, bot = V[rel > 0.96], V[rel < 0.04]
    foot = (area(top) + 1e-12) > 2 * (area(bot) + 1e-12)
    return bool(wide or flat or foot)


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
    out = dict(problems=[], height=H, heading_deg=None, rot_z_deg=0.0, rot_x_deg=0.0, scale=1.0)
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
        elif H > 1e-6:
            # birim oranina uymayan olcek (Sketchfab Dune Dweller 51,46 m, dugum olcegi 0,807; 2026-09-12) -> GTA ped boyuna. Dune Dweller
            # 0,035 olcekle: marker 3,57 cm, parmak 1,42, bolge %80 (olceksiz "Cannot be fixed automatically").
            out["scale"] = round(TARGET_HEIGHT / H, 6)
            out["problems"].append(f"height {H:.2f} m; must be between {h_min} and {h_max} m — it will be scaled to {TARGET_HEIGHT:.2f} m")
        else:
            out["problems"].append(f"height {H:.2f} m; must be between {h_min} and {h_max} m")
    if UPSIDE_DOWN_CHECK and _upside_down(V, lo, hi, H):
        # bas asagi karakter yon kontrolunu SESSIZCE geciyordu (Sketchfab Goblin rotx -90: marker 50,8 cm, bolge %23) -> X etrafinda 180
        out["rot_x_deg"] = 180.0
        out["problems"].append("character is upside down (feet at the top); it needs a 180° turn around X")
        return out
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
# Govde orta hatti x. "bbox" = sinir kutusu ortasi (eski). Tek kolu uzun karakterde kutu uzun kola kayar (rig_variants tek_kol_uzun_35:
# xbot boyun 55, kafa 36 cm). "trunk" = govde bandindaki (0.45-0.75 H) en derin (erozyon) voxellerin medyan x'i: kollar ince, govde
# en derin. Olculdu 2026-09-12 (80 gercek model dokumu, BIN_SNAP_XC ile): tek_kol_uzun_35 satir ort 8,56 -> 4,30 cm (xbot 10,71 ->
# 3,51, cesium 12,00 -> 4,96, RPM 9,08 -> 4,01), diger varyantlar +-0,1 (WS uzun_boyun_50 -0,34); 84 vanilla varyant notr.
CENTER_MODE = "trunk"
TRUNK_DT_FRAC = 0.7
# Uc adaylari esit geodezik degerde kararli siralanir (detect icindeki not). Olculdu 2026-09-12 (sistem Python = Blender Python):
# 36 vanilla kalibre ort 2,3 / %90 4,7 -> 4,4 cm (kalibrasyon yeniden uyduruldu, en buyuk ofset degisimi 0,006 H parmak ucu);
# 84 oran varyanti max 11,3 -> 9,2 cm; 80 gercek model dokumu esit/iyi (tek_bacak_uzun_15 zaten cokuk haric).
ENDS_STABLE_SORT = True
# Kesit kutulamasi (center_run, leg_centroid, column_stats, mid_col, ymid) xc'ye en yakin voxel SUTUNUNA gore: x - xb tam h kati.
# Neden: xc serbest sayi; iki sutun ortasina yakinsa 1 mm kayma sinir voxelini kutu degistirir -> omuz kesiti coker (WS uzun_boyun_50:
# xc 0,004 -> 0,005, L_shoulder 10,4 -> 28,2 cm). Cikti x (boyun/kafa/pelvis) ve L/R ayrimi gercek xc'yi kullanir. Olculdu 2026-09-12: 80 dokum tek basina notr (6,488 -> 6,478),
# trunk ile WS uzun_boyun_50 sicramasini kaldirir (6,54 -> 4,61); 84 vanilla varyant notr.
BIN_SNAP_XC = True


def _trunk_center_x(P, depth, lo, H, fallback):
    band = (P[:, 2] > lo[2] + 0.45 * H) & (P[:, 2] < lo[2] + 0.75 * H)
    if not band.any():
        return fallback
    d = depth[band]
    return float(np.median(P[band][d >= TRUNK_DT_FRAC * d.max(), 0]))


# Avuc yonu (el ekseni etrafinda donus) mesh'ten. Olculdu 2026-09-12: gercek modellerde sablon donusu 20-50 derece hatali (Xbot 27,
# Michelle 31, RPM 20, WS 37-50; sol/sag ayna simetrik) -> basparmak/isaret 3-5,6 cm; vanilla govdelerde sablon 3,7 derece.
# El ekseni (bilek -> f22) boyunca 0,5-1,1 L dilimi, eksene < 0,3 L vertexlerinin eksene dik en buyuk yayilimi = avuc cizgisi:
# gercek modeller 2,4 / max 5,0, vanilla 9,1 / %90 19,8 derece (yonsuz; tests/an_palm.py). Isaret: sablon donusune en yakin yon
# (gercek hata < 90). Sablonla fark PALM_GATE_DEG'den kucukse sablon kalir. Cikti isaret (f10) ve serce (f40) koku marker'i:
# fit_skeleton el donusunu bu hedeflerden hesaplar. Ilk A/B (sablon kivrik parmaklarla) yuzuk/serceyi bozdu; uc zincirleri mesh'ten
# gelince (THUMB_TIP/FINGER_TIPS/MID_TIP_CHAIN) Blender 4 gercek model tum parmak 1,67 -> 1,59 (Xbot 1,35 -> 1,21, Michelle 1,05 -> 1,00,
# WS 2,44 -> 2,31, RPM donus 18,8 < kapi -> ayni); marker/eklem/bolge/p95 ayni; vanilla parmak BIREBIR ayni (kapi).
PALM_ROLL = True
PALM_GATE_DEG = 20.0
PALM_SV_MAX = 0.55                 # s1/s0 dilim yayilimi: gercek 0,23-0,52, vanilla yanlis PCA 0,73 (tests/an_palm_gate.py)
PALM_FRAC = 1.0                    # duzeltme acisinin uygulanan orani (1 = GT yanal cizgi; yuzuk/serce kotulesti, olculuyor)
PALM_SLICE = (0.5, 1.1, 0.3)


# Parmak bukulmesi: vanilla sablonda parmaklar avuca kivrik (uc eklem avuc normali yonunde +0,40..+0,49 x |Hand->Finger20|), Xbot/Michelle
# duz (+0,05); kok dizilimi benzer (fark <= 0,08; tests/an_palm_arch.py). Marker'i olan tek parmak orta (f20-f22): sablona gore bukulme
# farki (C1 = sablon f20->f21 yonunu algilanana, C2 = ardindan f21->f22) isaret/yuzuk/serce zincirlerine aktarilir -> tam zincir marker.
# Vanilla'da orta parmak da kivrik -> C ~ birim. Avuc donusu duzeltilince yuzuk/serce kotulesmesinin nedeni bu kivrikti. A/B bekliyor.
FINGER_CURL = False
CURL_FINGERS = (1, 3, 4)

# Basparmak ucu mesh'ten (2026-09-12, tests/an_finger_tips.py): el vertexleri kNN grafi (k=TIP_K), bilek kesitinden (t < TIP_SEED_T)
# geodezik; uclar = yerel maksimum (TIP_MERGE L icinde birlesik). Basparmak = orta (en yuksek geodezik) haric t < 1,05 adaylardan
# eksene en uzak. Kapi rad >= THUMB_RAD_MIN: gercek 8/8 el secilir, uc hatasi 0,2-1,7 cm; vanilla 2/72 secilir (ikisi dogru; vanilla
# basparmak ucu rad 0,37, sablon zaten iyi). Zincir: kok sablondan (oturtulmus), kok -> uc dogrusunda sablon oranlari (uc = F02 + 0,75 seg).
# Mevcut basparmak hatasi gercek WS 5,6 / Xbot 4,2 / RPM 3,3 cm. A/B (Blender, 4 gercek model, yeni bilek varsayilani ustune):
# basparmak 3,93 -> 2,04, tum parmak 2,81 -> 2,43, ele gore 2,79 -> 2,47; marker/eklem/bolge/p95 ayni. Vanilla 1,37 -> 1,35 (notr).
THUMB_TIP = True
# Isaret/yuzuk/serce uclari (basparmak kapisi gecerse): adaylar orta ve basparmak haric t > TIP_T_MIN, g/gmax > TIP_G_MIN; basparmak
# yonune (eksene dik) izdusum p, orta ucun izdusumu pm. SIRA KURALI (v2): isaret = p > pm + TIP_ORDER_DELTA olanlardan en yuksek g;
# yuzuk = p < pm - delta olanlardan en yuksek g; serce = p < p(yuzuk) - delta olanlardan en kucuk p; aday yoksa o parmak sablonda.
# v1 (isaret max p / serce min p) Blender 4 gercek model: tum parmak 2,43 -> 2,11, ele gore 2,47 -> 2,15 (hepsi iyilesti) ama vanilla
# fitness apose'ta serce ucu aday degil -> yuzuk 5,7 cm yanlis. v2 analiz (delta 0,05): gercek isaret 0,9 / yuzuk 1,0 / serce 0,9 cm
# (serce 7/8 secilir), vanilla yuzuk 5,7 -> 0,6.
FINGER_TIPS = True
TIP_T_MIN = 0.8
TIP_G_MIN = 0.6
TIP_ORDER_DELTA = 0.05
# Orta parmak zinciri mesh ucundan (tests/an_mid_chain.py, 2026-09-12): f2j = mesh orta ucu (en yuksek geodezik) + vanilla oran (uc -> bilek).
# Duz dogru uzerindeki oranlar vanilla/gercek ayni (f20 0,515 / 0,526); vanilla parmak kivrik -> GT eklem dogrudan 0,215 L disarida
# (gercek 0,083) -> yalniz DUZ elde: kivrim ipucu = bilek->uc geodezik / duz mesafe <= MID_CURL_MAX (vanilla min 1,062, gercek ort 1,057).
# 1,04: gercek 65/120 kol secilir, f20 3,21 -> 1,74, f21 2,98 -> 1,81, f22 1,96 -> 1,41 cm; vanilla 0/72 (degismez).
# Blender 4 gercek model: tum parmak 2,05 -> 1,67 (Xbot 2,07 -> 1,35, Michelle 1,83 -> 1,05; RPM/WS kivrik -> degismez), marker 3,97 -> 3,71,
# eklem 4,27 -> 4,05, bolge 84,45 -> 84,4, p95 ayni; Xbot serce 1,16 -> 2,47 (kok olcegi). Vanilla parmak birebir ayni.
MID_TIP_CHAIN = True
# Kapi 1,04 -> 1,03 (2026-09-12, GTA el varyantlari; tests/hand_variants.py orta_kapi_*): kivrik vanilla parmak acik/buyuk_el varyantinda
# ipucu 1,024-1,039'a iner ve yanlis gecer. Fark (parmak dunya, 24 vaka/varyant) 1,03 / 1,02: yok 0 / 0, duz +0,06 / +0,10, kivrik 0 / 0,
# acik -0,06 / -0,14, buyuk_el -0,08 / -0,08. 1,03 = duz eldeki kaybi kucuk tutan denge.
MID_CURL_MAX = 1.03
# Kivrik elde (ipucu > MID_CURL_MAX) yalniz f22: uc->bilek dogrusunda sablon orani + MID_F22_ALPHA * (bilek->uc yuzey geodezik yolunun ayni
# orandaki dik sapmasi). scratchpad/an_curl_path.py (2026-09-12): kivrik gercek 55 kol f22 2,30 -> 1,56, vanilla 1,79 -> 1,48 (LOO alfa);
# f20/f21'e uygulamak kotulestirir (yol bogumu degil parmagin bir yuzunu izler). A/B bekliyor.
MID_F22_PATH = False
MID_F22_ALPHA = 0.64
# Parmak boyu orta parmaktan (2026-09-12, GTA el varyantlari tests/hand_variants.py): uclari bulunamayan parmaklarda segment boylari sablon x el
# olcegi kalir -> uzun parmak varyantinda parmak kemik boy orani 0,81, kisa 1,15, buyuk el 0,79 (adimlar acik/kapali ayni). Orta parmak
# marker zinciri (f20->f21->f22) gercek boyu tasir: s = |zincir| / (sablon orta zinciri x el olcegi); isaret/yuzuk/serce zincirleri kok +
# oturtulmus yon, segmentler x s (uc zinciri kurulmus parmaga dokunmaz). Tek basina etkisizdi (orta zincir sabit oranli); WEB_KNUCKLE f20'yi
# gercek boguma koyunca olcu anlam kazanir -> WEB_KNUCKLE ile birlikte acik (sonuc WEB_KNUCKLE notunda).
FINGER_LEN_FROM_MID = True
FINGER_LEN_CLAMP = (0.6, 1.6)
# Bogum (f20) parmak ayrilma cizgisinden (2026-09-12, tests/an_knuckle.py, GTA el varyantlari 12 govde x 2 poz x 7 = 336 el): bilek->f22
# ekseni dilimlerinde (0,35..1,15 L, kalinlik 0,015 L, eksene < 0,65 L) dilimin PCA yonune izdusumde WEB_GAP L'den buyuk bosluk sayisi + 1
# = parmak kumesi; ard arda iki dilimde >= 3 olan ilk t = web. GT f20 t ile corr +0,57 (algilanan f20 -0,15); f20 = web - WEB_OFFSET:
# |hata| 0,066 L vs algilanan 0,093 L (uzun parmak web 0,456 / GT 0,455 / algi 0,555; kivrik 0,685 / 0,734 / 0,548). f20 eksen boyunca
# tasinir (dik bileseni kalir), f21 f20-f22 arasindaki oranini korur. Sapma > WEB_MAX_SHIFT L ise dokunulmaz. A/B bekliyor.
# v2 (2026-09-12, tests/an_knuckle2.py): VERTEX dilimi dusuk poligon vanilla elinde gecersizdi (kume basina n1-n9, v1 A/B vanilla +0,63 cm).
# Yuzeyden alan agirlikli yogun ornekleme (WEB_DENS nokta/m2, sabit tohum) + kume >= WEB_MIN_PTS nokta ve >= WEB_MIN_W L genislik:
# 336 GTA elinde 258 bulundu, corr(web, GT f20) +0,82, f20 = web - 0,164 L -> |hata| ort 0,032 (medyan 0,021) L vs algilanan 0,088 L.
# Bulunamazsa (kivrik 14/48, acik 25/48) dokunulmaz. A/B (GTA el varyantlari, FINGER_LEN_FROM_MID ile birlikte, 24 vaka/varyant, parmak dunya):
# yok 1,40 -> 1,38, duz 2,42 -> 2,00, kivrik 3,53 -> 3,23, acik 1,65 -> 1,64, uzun 1,77 -> 1,53, kisa 1,67 -> 1,45, buyuk_el 2,31 -> 2,18; >0,3 cm
# kotulesen vaka 0; parmak kemik boy orani uzun 0,81 -> 0,90, kisa 1,13 -> 1,04, buyuk_el 0,80 -> 0,91. Bedel: ele gore (Hand konum hatasini
# iceren) metrik yok +0,07, kisa +0,52, buyuk_el +0,78 cm. Yalniz web (boy aktarimi yok) buyuk_el'de +0,32 -> ikisi birlikte acik.
WEB_KNUCKLE = True
WEB_GAP = 0.02
WEB_OFFSET = 0.164
WEB_MAX_SHIFT = 0.25
WEB_DENS = 400000.0
WEB_MIN_PTS = 15
WEB_MIN_W = 0.02
# f22 yalniz basina tasininca uc bogum boyu bozulur (vanilla parmak2_12 orani 0,98 -> 1,30, aralik 0,72..2,28). MID_F21_SHIFT: f21 de
# f22 kaymasinin sablon orani (|f20-f21| / (|f20-f21| + |f21-f22|) = 0,612) kadar kayar -> analiz (scratchpad/an_f22_f21.py): kivrik gercek
# f21 2,66 -> 1,99, f22 2,30 -> 1,56; vanilla f21 1,63 -> 1,10, f22 1,79 -> 1,43; uc bogum payi/GT vanilla 0,95..1,11 (yalniz f22: 0,82..1,52).
MID_F21_SHIFT = True
# Uc zincirlerinin (isaret/yuzuk/serce) koklerini de avuc donusuyle (PALM_ROLL) cevir; kapaliyken yalniz f10/f40 kokleri doner, zincir
# noktalari ve yuzuk koku donmemis sablondan kalir. Blender 4 gercek model tum parmak 1,59 -> 1,52 (Xbot 1,21 -> 1,16, Michelle 1,00 -> 0,93,
# WS 2,31 -> 2,14 (ele gore 2,66 -> 2,76), RPM ayni); marker/eklem/p95 ayni; vanilla BIREBIR ayni.
TIP_ROOTS_ROLL = True
# Parmak koku yanal yayilimi mesh avuc genisliginden (2026-09-12, scratchpad/an_palm_width.py): bilek->f22 ekseninde 0,9-1,05 L dilimi,
# eksene < 0,7 L vertexlerinin eksene dik PCA genisligi (p97-p3) w; GT isaret-serce koku yayilimi ~ SPREAD_K w (vanilla medyan 0,856;
# gercek corr +0,98). Yayilim gercek 0,28 (Xbot) .. 0,51 L (WS), sablon ~0,37 -> sabit sablon hatasi gercek 0,083 L; olcekli 0,018
# (vanilla 0,022 -> 0,028, olu bolge SPREAD_DEADZONE). WS canli: kok yanal hatasi isaret -2,9 / orta -1,7 / yuzuk -0,8 / serce +0,6 cm.
# Uygulama: isaret/yuzuk/serce kokleri orta kok hattina gore yanal (lambda-1) kaydirilir. A/B bekliyor.
ROOT_SPREAD = False
SPREAD_K = 0.856
SPREAD_SLICE = (0.9, 1.05, 0.7)
SPREAD_DEADZONE = 0.1
SPREAD_CLAMP = (0.6, 1.6)
THUMB_RAD_MIN = 0.44
TIP_K = 10
TIP_SEED_T = 0.08
TIP_MERGE = 0.12
TIP_MIN_FRAC = 0.35


def hand_tip_candidates(V, w0, t0):
    """Geodezik yerel maksimum parmak ucu adaylari: dict(P, g (L birimi), t, rad) ya da None. scipy'siz (Blender)."""
    import heapq
    from .knn import GridKNN
    w0, t0 = np.asarray(w0, float), np.asarray(t0, float)
    ax = t0 - w0
    L = float(np.linalg.norm(ax))
    if L < 1e-6:
        return None
    ax = ax / L
    V = np.asarray(V, float)
    rel = V - w0
    tt = rel @ ax / L
    rad = np.linalg.norm(rel - np.outer(rel @ ax, ax), axis=1) / L
    keep = (tt > -0.1) & (tt < 1.6) & (rad < 0.9)
    Vh, th = V[keep], tt[keep]
    n = len(Vh)
    if n < 50:
        return None
    k = min(TIP_K, n - 1)
    D, I = GridKNN(Vh).query(Vh, k + 1)
    adj = [dict() for _ in range(n)]
    for i in range(n):
        for d, j in zip(D[i, 1:], I[i, 1:]):
            j = int(j)
            if j != i and np.isfinite(d):
                adj[i][j] = min(adj[i].get(j, np.inf), float(d))
                adj[j][i] = min(adj[j].get(i, np.inf), float(d))
    g = np.full(n, np.inf)
    pred = np.full(n, -1, dtype=np.int64)
    heap = []
    for i in np.nonzero(th < TIP_SEED_T)[0]:
        g[i] = 0.0
        heap.append((0.0, int(i)))
    if not heap:
        return None
    heapq.heapify(heap)
    while heap:
        d, i = heapq.heappop(heap)
        if d > g[i]:
            continue
        for j, w in adj[i].items():
            nd = d + w
            if nd < g[j]:
                g[j] = nd
                pred[j] = i
                heapq.heappush(heap, (nd, j))
    g[~np.isfinite(g)] = -1.0
    gmax = float(g.max())
    if gmax <= 0:
        return None
    nbmax = g[I[:, 1:]].max(1)
    cand = np.nonzero((g >= nbmax) & (g > TIP_MIN_FRAC * gmax))[0]
    cand = cand[np.argsort(-g[cand], kind="stable")]
    picked = []
    for i in cand:
        if all(np.linalg.norm(Vh[i] - Vh[j]) > TIP_MERGE * L for j in picked):
            picked.append(int(i))
    P = Vh[picked]
    r = P - w0
    return dict(P=P, g=g[picked] / L, t=r @ ax / L, rad=np.linalg.norm(r - np.outer(r @ ax, ax), axis=1) / L, L=L,
                Vh=Vh, pred=pred, idx=np.asarray(picked, dtype=np.int64))


def _mid_tip_chain(markers, cands, tpl):
    rat = vanilla_ratios(tpl)
    out = {}
    for S, c in cands.items():
        if c is None or len(c["P"]) == 0:
            continue
        w = np.asarray(markers[f"{S}_wrist"], float)
        tip = c["P"][0]
        euc = float(np.linalg.norm(tip - w))
        if euc < 1e-6:
            continue
        if float(c["g"][0] * c["L"]) / euc > MID_CURL_MAX:
            if MID_F22_PATH:
                f22 = _f22_from_path(c, tip, w, rat)
                if f22 is not None:
                    out[f"{S}_f22"] = f22
                    if MID_F21_SHIFT and f"{S}_f21" in markers:
                        out[f"{S}_f21"] = np.asarray(markers[f"{S}_f21"], float) + _mid_seg_ratio(tpl) * (f22 - np.asarray(markers[f"{S}_f22"], float))
            continue
        for j in range(3):
            out[f"{S}_f2{j}"] = tip + rat[f"f_tip2{j}"] * (w - tip)
    return out


def _len_from_mid(m, out, S, P, tpl, root):
    """Orta parmak marker zinciri boyu / (sablon orta zinciri x oturtulmus el olcegi) = s; uc zinciri olmayan isaret/yuzuk/serceye tam zincir."""
    if any(f"{S}_f2{j}" not in m for j in range(3)):
        return {}
    T = lambda n: np.asarray(tpl.pos[tpl.index[n]], float)
    f20, f21, f22 = (np.asarray(m[f"{S}_f2{j}"], float) for j in range(3))
    Ld = float(np.linalg.norm(f21 - f20) + np.linalg.norm(f22 - f21))
    Lt = float(np.linalg.norm(T(f"SKEL_{S}_Finger21") - T(f"SKEL_{S}_Finger20")) + np.linalg.norm(T(f"SKEL_{S}_Finger22") - T(f"SKEL_{S}_Finger21")))
    ht = float(np.linalg.norm(T(f"SKEL_{S}_Finger20") - T(f"SKEL_{S}_Hand")))
    hf = float(np.linalg.norm(P(f"SKEL_{S}_Finger20") - P(f"SKEL_{S}_Hand")))
    if min(Lt, ht, hf) < 1e-6:
        return {}
    s = min(max(Ld / (Lt * hf / ht), FINGER_LEN_CLAMP[0]), FINGER_LEN_CLAMP[1])
    res = {}
    for f in (1, 3, 4):
        if f"{S}_f{f}1" in out:
            continue
        F = [P(f"SKEL_{S}_Finger{f}{j}") for j in range(3)]
        p0 = root(f"SKEL_{S}_Finger{f}0")
        d1 = root(f"SKEL_{S}_Finger{f}1") - root(f"SKEL_{S}_Finger{f}0")
        d2 = root(f"SKEL_{S}_Finger{f}2") - root(f"SKEL_{S}_Finger{f}1")
        res.update({f"{S}_f{f}0": p0, f"{S}_f{f}1": p0 + s * d1, f"{S}_f{f}2": p0 + s * (d1 + d2)})
    return res


def _sample_surface(V, F, center, radius, dens, seed=0):
    """Merkezden radius icindeki ucgenlerden alan agirlikli rastgele nokta (sabit tohum -> ayni sonuc)."""
    rng = np.random.default_rng(seed)
    tri = V[F]
    keep = np.linalg.norm(tri.mean(1) - center, axis=1) < radius
    tri = tri[keep]
    if len(tri) == 0:
        return np.zeros((0, 3))
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    idx = np.repeat(np.arange(len(tri)), rng.poisson(area * dens))
    if len(idx) == 0:
        return np.zeros((0, 3))
    r1, r2 = rng.random(len(idx)), rng.random(len(idx))
    sq = np.sqrt(r1)
    t = tri[idx]
    return (1 - sq)[:, None] * t[:, 0] + (sq * (1 - r2))[:, None] * t[:, 1] + (sq * r2)[:, None] * t[:, 2]


def _web_t(Pts, w0, t0):
    """Parmaklarin >= 3 gercek kumeye ayrildigi ilk eksen konumu (L birimi, ard arda iki dilim) ya da None."""
    ax = t0 - w0
    L = float(np.linalg.norm(ax))
    if L < 1e-6 or len(Pts) == 0:
        return None
    ax = ax / L
    rel = Pts - w0
    tt = rel @ ax / L
    perp = rel - np.outer(rel @ ax, ax)
    near = np.linalg.norm(perp, axis=1) / L < 0.65
    prev = False
    for t in np.arange(0.30, 1.151, 0.01):
        m = near & (np.abs(tt - t) < 0.015)
        ok = False
        if m.sum() >= 3 * WEB_MIN_PTS:
            Q = perp[m] - perp[m].mean(0)
            u = np.linalg.svd(Q, full_matrices=False)[2][0]
            p = np.sort(perp[m] @ u)
            groups = np.split(p, np.nonzero(np.diff(p) > WEB_GAP * L)[0] + 1)
            ok = sum(1 for g in groups if len(g) >= WEB_MIN_PTS and g[-1] - g[0] >= WEB_MIN_W * L) >= 3
        if ok and prev:
            return float(t - 0.01)
        prev = ok
    return None


def _web_knuckle(V, F, m, S):
    if F is None or any(f"{S}_{k}" not in m for k in ("wrist", "f20", "f21", "f22")):
        return {}
    w0, f20, f21, f22 = (np.asarray(m[f"{S}_{k}"], float) for k in ("wrist", "f20", "f21", "f22"))
    ax = f22 - w0
    L = float(np.linalg.norm(ax))
    if L < 1e-6:
        return {}
    Pts = _sample_surface(V, np.asarray(F), (w0 + f22) / 2, 1.2 * L, WEB_DENS)
    wt = _web_t(Pts, w0, f22)
    if wt is None:
        return {}
    ax = ax / L
    t_old = float((f20 - w0) @ ax / L)
    shift = (wt - WEB_OFFSET) - t_old
    if abs(shift) > WEB_MAX_SHIFT:
        return {}
    n20 = f20 + shift * L * ax
    d_old = f22 - f20
    a = float((f21 - f20) @ d_old) / max(float(d_old @ d_old), 1e-12)
    perp21 = (f21 - f20) - a * d_old
    return {f"{S}_f20": n20, f"{S}_f21": n20 + a * (f22 - n20) + perp21}


def _mid_seg_ratio(tpl):
    p = lambda n: np.asarray(tpl.pos[tpl.index[n]], float)
    a = float(np.linalg.norm(p("SKEL_L_Finger21") - p("SKEL_L_Finger20")))
    b = float(np.linalg.norm(p("SKEL_L_Finger22") - p("SKEL_L_Finger21")))
    return a / (a + b) if a + b > 1e-9 else 0.5


def _f22_from_path(c, tip, w, rat):
    path, i = [], int(c["idx"][0])
    while i >= 0 and len(path) < len(c["Vh"]):
        path.append(i)
        i = int(c["pred"][i])
    if len(path) < 3:
        return None
    Pp = c["Vh"][path]
    line = w - tip
    Ll = float(np.linalg.norm(line))
    if Ll < 1e-6:
        return None
    u = line / Ll
    r22 = rat["f_tip22"]
    j = int(np.argmin(np.abs((Pp - tip) @ u / Ll - r22)))
    base = tip + r22 * line
    v = Pp[j] - base
    return base + MID_F22_ALPHA * (v - u * float(v @ u))


def _thumb_markers(c, markers, S, P, tpl, Pf=None):
    Pf = Pf or P
    if c is None or len(c["P"]) < 2:
        return {}
    rest = [i for i in range(1, len(c["P"])) if c["t"][i] < 1.05]      # 0 = orta (en yuksek geodezik)
    if not rest:
        return {}
    b = max(rest, key=lambda i: c["rad"][i])
    if c["rad"][b] < THUMB_RAD_MIN:
        return {}
    out = _tip_chain(S, 0, P(f"SKEL_{S}_Finger00"), c["P"][b], tpl)
    if not FINGER_TIPS:
        return out
    w0 = np.asarray(markers[f"{S}_wrist"], float)
    ax = np.asarray(markers[f"{S}_f22"], float) - w0
    ax = ax / np.linalg.norm(ax)
    u = c["P"][b] - w0
    u = u - ax * float(u @ ax)
    if np.linalg.norm(u) < 1e-9:
        return out
    u = u / np.linalg.norm(u)
    gmax = float(c["g"].max())
    cand = [i for i in range(1, len(c["P"])) if i != b and c["t"][i] > TIP_T_MIN and c["g"][i] > TIP_G_MIN * gmax]
    proj = lambda i: float((c["P"][i] - w0) @ u) / c["L"]
    pm, d = proj(0), TIP_ORDER_DELTA
    pick = {}
    side = [i for i in cand if proj(i) > pm + d]
    if side:
        pick[1] = max(side, key=lambda i: c["g"][i])
    other = [i for i in cand if proj(i) < pm - d]
    if other:
        pick[3] = max(other, key=lambda i: c["g"][i])
        beyond = [i for i in other if proj(i) < proj(pick[3]) - d]
        if beyond:
            pick[4] = min(beyond, key=proj)
    for f, i in pick.items():
        out.update(_tip_chain(S, f, Pf(f"SKEL_{S}_Finger{f}0"), c["P"][i], tpl))
    return out


def _tip_chain(S, f, root, tip, tpl):
    """Kok (oturtulmus sablon) -> mesh ucu dogrusunda sablon zincir oranlari; uc = F?2 + 0,75 seg (vanilla_ratios ile ayni)."""
    T = lambda j: tpl.pos[tpl.index[f"SKEL_{S}_Finger{f}{j}"]]
    a_, b_ = float(np.linalg.norm(T(1) - T(0))), float(np.linalg.norm(T(2) - T(1)))
    tot = a_ + 1.75 * b_
    return {f"{S}_f{f}0": root, f"{S}_f{f}1": root + (a_ / tot) * (tip - root), f"{S}_f{f}2": root + ((a_ + b_) / tot) * (tip - root)}


HAND_REG = False    # el sablon kaydi (core/handreg.py): 15 parmak marker'i vanilla el mesh'inin ICP kaydindan (PLAN.md 'ICP v3..')


def palm_markers(V, markers, tpl, F=None, hand_reg=None):
    """Parmak/avuc marker'lari: _palm_markers_core (uclar, orta zincir, bogum, avuc donusu); hand_reg (None = HAND_REG) ise el sablon
    kaydi ustune yazar (eklenti: Scene.mpr.hand_template)."""
    out = _palm_markers_core(V, markers, tpl, F)
    if HAND_REG if hand_reg is None else hand_reg:
        from . import handreg
        m = dict(markers)
        m.update(out)
        out.update(handreg.hand_markers(V, m, tpl, F=F))
    return out


def _palm_markers_core(V, markers, tpl, F=None):
    """Kalibre marker'lar -> gecici iskelet -> {S_f10, S_f40} (avuc donusu, PALM_ROLL) ve/veya tam isaret/yuzuk/serce zinciri
    (FINGER_CURL) ya da {}."""
    if not (PALM_ROLL or FINGER_CURL or THUMB_TIP or MID_TIP_CHAIN or FINGER_LEN_FROM_MID or WEB_KNUCKLE):
        return {}
    from . import markers as mk
    from .fit import fit_skeleton, axis_angle, rot_between
    V = np.asarray(V, float)
    cands, out = {}, {}
    if THUMB_TIP or MID_TIP_CHAIN:                   # uc adaylari el basina bir kez (algilanan bilek/f22 ekseni)
        for S in ("L", "R"):
            if f"{S}_wrist" in markers and f"{S}_f22" in markers:
                cands[S] = hand_tip_candidates(V, markers[f"{S}_wrist"], markers[f"{S}_f22"])
    m_fit = dict(markers)
    if MID_TIP_CHAIN:                                # oturtmadan ONCE: el olcegi -> parmak kokleri
        out.update(_mid_tip_chain(markers, cands, tpl))
        m_fit.update(out)
    if WEB_KNUCKLE:                                  # bogum parmak ayrilma cizgisinden (oturtmadan once)
        for S in ("L", "R"):
            upd = _web_knuckle(V, F, m_fit, S)
            out.update(upd)
            m_fit.update(upd)
    try:
        fit = fit_skeleton(tpl, mk.expand_targets(tpl, m_fit))
    except (ValueError, KeyError):
        return out
    P = lambda n: fit.P_W[tpl.index[n], :3, 3]
    for S in ("L", "R"):
        if any(f"{S}_{k}" not in markers for k in ("wrist", "f20", "f21", "f22")):
            continue
        h, m = P(f"SKEL_{S}_Hand"), P(f"SKEL_{S}_Finger20")
        hax = m - h
        if np.linalg.norm(hax) < 1e-9:
            continue
        hax = hax / np.linalg.norm(hax)
        ang = _palm_roll_angle(V, markers, S, P, hax) if PALM_ROLL else None
        R = axis_angle(hax, ang * PALM_FRAC) if ang is not None else np.eye(3)
        rot = lambda n, R=R, h=h: h + R @ (P(n) - h)
        root = rot if (TIP_ROOTS_ROLL and ang is not None) else P
        spread = _root_spread(V, markers, S, root) if ROOT_SPREAD else None
        if spread is not None:
            root = spread
        if THUMB_TIP:
            out.update(_thumb_markers(cands.get(S), markers, S, P, tpl, root))
        if FINGER_LEN_FROM_MID:
            out.update(_len_from_mid(m_fit, out, S, P, tpl, root))
        if not FINGER_CURL:
            if ang is not None or spread is not None:
                base = root if (TIP_ROOTS_ROLL or spread is not None) else rot
                for f in (1, 4):
                    out[f"{S}_f{f}0"] = base(f"SKEL_{S}_Finger{f}0")
            continue
        hb = tpl.index[f"SKEL_{S}_Hand"]
        Mr = R @ fit.P_W[hb, :3, :3] @ tpl.W[hb, :3, :3].T        # sablon dunya vektoru -> oturtulmus (ve donmus) el
        T = lambda j: tpl.W[tpl.index[f"SKEL_{S}_Finger2{j}"], :3, 3]
        d1 = np.asarray(markers[f"{S}_f21"], float) - np.asarray(markers[f"{S}_f20"], float)
        d2 = np.asarray(markers[f"{S}_f22"], float) - np.asarray(markers[f"{S}_f21"], float)
        s1, s2 = Mr @ (T(1) - T(0)), Mr @ (T(2) - T(1))
        if min(np.linalg.norm(v) for v in (d1, d2, s1, s2)) < 1e-6:
            continue
        C1 = rot_between(s1, d1)
        C2 = rot_between(C1 @ s2, d2) @ C1
        for f in CURL_FINGERS:
            F = [P(f"SKEL_{S}_Finger{f}{j}") for j in range(3)]
            p0 = h + R @ (F[0] - h)
            p1 = p0 + C1 @ (R @ (F[1] - F[0]))
            p2 = p1 + C2 @ (R @ (F[2] - F[1]))
            out.update({f"{S}_f{f}0": p0, f"{S}_f{f}1": p1, f"{S}_f{f}2": p2})
    return out


def _root_spread(V, markers, S, root):
    """Mesh avuc genisligi -> isaret/yuzuk/serce koklerini yanal olceklenmis kok fonksiyonu ya da None (olu bolge / veri yok)."""
    w0, t0 = np.asarray(markers[f"{S}_wrist"], float), np.asarray(markers[f"{S}_f22"], float)
    x = t0 - w0
    L = float(np.linalg.norm(x))
    if L < 1e-6:
        return None
    x = x / L
    a, b, rmax = SPREAD_SLICE
    rel = V - w0
    t = rel @ x / L
    perp = rel - np.outer(rel @ x, x)
    msk = (t > a) & (t < b) & (np.linalg.norm(perp, axis=1) / L < rmax)
    if msk.sum() < 15:
        return None
    Q = perp[msk] - perp[msk].mean(0)
    _, _, vt = np.linalg.svd(Q, full_matrices=False)
    q = Q @ vt[0]
    est = SPREAD_K * float(np.percentile(q, 97) - np.percentile(q, 3))
    names = [f"SKEL_{S}_Finger{f}0" for f in (1, 3, 4)]
    lat = root(names[0]) - root(names[2])
    lat = lat - x * float(lat @ x)
    cur = float(np.linalg.norm(lat))
    if cur < 1e-6:
        return None
    lat = lat / cur
    lam = est / cur
    if abs(lam - 1.0) < SPREAD_DEADZONE:
        return None
    lam = min(max(lam, SPREAD_CLAMP[0]), SPREAD_CLAMP[1])
    c = root(f"SKEL_{S}_Finger20")

    def fn(n):
        p = root(n)
        if n in names:
            p = p + (lam - 1.0) * float((p - c) @ lat) * lat
        return p
    return fn


def _palm_roll_angle(V, markers, S, P, hax):
    """Mesh avuc cizgisinin oturtulmus sablon yanal cizgisine (Finger40 -> Finger10) isaretli acisi (radyan) ya da None (kapi)."""
    t_lo, t_hi, r_max = PALM_SLICE
    w0, t0 = np.asarray(markers[f"{S}_wrist"], float), np.asarray(markers[f"{S}_f22"], float)
    ax = t0 - w0
    L0 = float(np.linalg.norm(ax))
    if L0 < 1e-6:
        return None
    ax = ax / L0
    rel = V - w0
    tt = rel @ ax
    rad = np.linalg.norm(rel - np.outer(tt, ax), axis=1)
    sel = (tt > t_lo * L0) & (tt < t_hi * L0) & (rad < r_max * L0)
    if sel.sum() < 20:
        return None
    Q = V[sel] - V[sel].mean(0)
    Q = Q - np.outer(Q @ ax, ax)
    _, sv, vt = np.linalg.svd(Q, full_matrices=False)
    if sv[1] > PALM_SV_MAX * sv[0]:
        return None
    ref = P(f"SKEL_{S}_Finger10") - P(f"SKEL_{S}_Finger40")
    ref = ref - hax * np.dot(ref, hax)
    lat = vt[0] - hax * np.dot(vt[0], hax)
    if np.linalg.norm(ref) < 1e-9 or np.linalg.norm(lat) < 1e-9:
        return None
    ref, lat = ref / np.linalg.norm(ref), lat / np.linalg.norm(lat)
    if np.dot(lat, ref) < 0:
        lat = -lat
    ang = float(np.arctan2(np.dot(hax, np.cross(ref, lat)), np.dot(ref, lat)))
    return ang if abs(np.degrees(ang)) >= PALM_GATE_DEG else None


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
    ii, jj, kk = np.nonzero(solid)
    P = grid.center(np.stack([ii, jj, kk], 1))
    xc = 0.5 * (lo[0] + hi[0])
    if CENTER_MODE == "trunk":
        xc = _trunk_center_x(P, dt[ii, jj, kk], lo, H, xc)
    xb = grid.lo[0] + round((xc - grid.lo[0]) / h) * h if BIN_SNAP_XC else xc
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
    # gv tam sayi geodezik mesafe: esitlik cok. Varsayilan (quicksort) esitlerin sirasini numpy surumune gore degistirir -> Blender
    # (numpy 2.3.4) ile sistem Python (2.5.1) ayni girdide farkli uc secti (xbot 3,37 / 3,26 cm; tek kol uzun: basari / "hand and foot
    # tips" hatasi). stable iki ortamda birebir ayni (olculdu 2026-09-12, isaret toplami 6 hane).
    for o in np.argsort(-gv, kind="stable" if ENDS_STABLE_SORT else None):
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
        xs = sgn * (P[idx, 0] - xb)
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
    mid_col = np.abs(P[:, 0] - xb) < 1.5 * h
    mid_levels = set(kz[mid_col].tolist())
    k_start = int(round((zof(0.55) - grid.lo[2]) / h))
    k_cr = k_start
    while k_cr in mid_levels and k_cr > 0:
        k_cr -= 1
    z_crotch = grid.lo[2] + (k_cr + 1) * h

    def leg_centroid(sgn, z):
        # taraf yarisinda merkezden disari ILK kesintisiz kosu (uyluk/diz); bacaga yakin sarkan el ayri kosu kalir
        m = (np.abs(kz - round((z - grid.lo[2]) / h)) <= 1) & (sgn * (P[:, 0] - xb) > 0.5 * h) & \
            (np.abs(P[:, 0] - xb) < 0.16 * H)
        if m.sum() < 3:
            return None
        kx = np.round(sgn * (P[m, 0] - xb) / h).astype(int)
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
        Q = Q[np.abs(Q[:, 0] - xb) < 0.12 * H]
        if len(Q) < 2:
            return None
        ix = np.round((Q[:, 0] - xb) / h).astype(int)
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
        sh = np.array([xb + sgn * xo if xo is not None else sh[0], float(np.mean(mids)) if mids else sh[1], z_new])
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
        m = (np.abs(P[:, 2] - z) < 1.5 * h) & (np.abs(P[:, 0] - xb) < 0.05 * H)
        return float(np.median(P[m, 1])) if m.any() else float(top[1])
    if z_line is not None:
        zn, zh = z_line - 0.0082 * H, z_line + 0.314 * (top_z - z_line)
    else:
        zn, zh = zof(rat["z_neck"]), zof(rat["z_head"])
    out["neck"] = np.array([xc, ymid(zn), zn])
    out["head"] = np.array([xc, ymid(zh), zh])
    zroot = 0.5 * (hips["L"][2] + hips["R"][2]) + (rat["z_root"] - rat["z_hip"]) * H
    out["pelvis"] = np.array([xc, ymid(zroot), zroot])
    if WRIST_H_BLEND > 0:
        _hand_length_from_height(out, H)     # kalibrasyondan ONCE: ofsetler karismis bilege gore uydurulur
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


# El boyu boydan (2026-09-12, tests/an_wrist.py): bilek kol yolunun vanilla oraninda -> el kola gore kucuk/buyukse kayar (Xbot algilanan
# |bilek-f22| 0,119 H, GT 0,089; uzun_kol_30 bilek 5,1 cm). GT |bilek-f22|/H vanilla 0,0947 (std 0,0049). bilek' = (1-a) simdiki +
# a (f22 + HAND_LEN_H H birim(dirsek - f22)); f20/f21 f22 etrafinda ayni oranla. detect() sonunda (ham), kalibrasyon bununla uydurulmali. a 0,5 bilek ort: vanilla 1,38 -> 1,40 (max 5,3 -> 3,2),
# gercek base 2,80 -> 2,06, gercek 120 kol 3,03 -> 2,23. Kalibrasyon bununla yeniden uyduruldu. 4 gercek model (Blender) parmak ele
# gore 3,54 -> 2,79, dunya 2,81 -> 2,81, marker 4,02 -> 3,97; vanilla parmak dunya 1,42 -> 1,53, ele gore 1,59 -> 1,30 (0 = kapali).
# KAPATILDI (2026-09-12, kullanici karari): dogruluk olcutu GTA iskeleti (vanilla ped GT). Dis rig GT'leri kendi kurallarini tasir
# (Soldier Hand kemigi gorunur bilegin 4 cm gerisinde, WS omuz UE'de 10 cm farkli). Vanilla parmak dunya 1,42 -> 1,52 kotulestigi icin
# kapali; kalibrasyon eski dosyaya (out/fingers/calib_before_wrist.json) donduruldu.
WRIST_H_BLEND = 0.0
HAND_LEN_H = 0.0947


def _hand_length_from_height(m, H):
    for S in ("L", "R"):
        if any(f"{S}_{k}" not in m for k in ("wrist", "elbow", "f22")):
            continue
        w, e, t = (np.asarray(m[f"{S}_{k}"], float) for k in ("wrist", "elbow", "f22"))
        u = e - t
        if np.linalg.norm(u) < 1e-6:
            continue
        w_new = (1 - WRIST_H_BLEND) * w + WRIST_H_BLEND * (t + HAND_LEN_H * H * u / np.linalg.norm(u))
        d_old, d_new = w - t, w_new - t
        n2 = float(d_old @ d_old)
        if n2 < 1e-12:
            continue
        for j in (0, 1):
            k = f"{S}_f2{j}"
            if k in m:
                rel = np.asarray(m[k], float) - t
                a = float(rel @ d_old) / n2
                m[k] = t + a * d_new + (rel - a * d_old)
        m[f"{S}_wrist"] = w_new


CALIB_PATH = None      # A/B: baska kalibrasyon dosyasi (None = eklenti verisi)


def load_calibration(path=None):
    import json, os
    path = path or CALIB_PATH or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "autodetect_calib.json")
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
