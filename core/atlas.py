"""Coklu doku -> tek doku atlasi (saf numpy; Blender Python'unda Pillow yok).

Neden: GTA ped'i cizim basina TEK diffuse adi arar (<bilesen>_diff_000_a_uni). Govde + kiyafet + sac + goz ayri dokuluysa
yalniz en buyugu kullanilabiliyordu, digerleri yanlis gorunuyordu.
Yontem: kaynak basina 2'nin kuvveti kare hucre (yuzey payiyla), dortlu agac paketleme (buyukten kucuge -> toplam alan S^2'yi
asmadikca her zaman sigar), hucreye yeniden ornekleme + kenar dolgusu (mip sizmasina karsi), UV'ler afin donusumle hucreye.
Piksel dizileri ALTTAN USTE (Blender image.pixels ve UV v=0 alt) — DDS yazarken dikey cevrilir.
"""
import numpy as np

TILE_MAX = 4        # UV 0-1 disina tasiyorsa hucrede en fazla bu kadar karo


def next_pow2(n):
    return 1 << max(0, int(np.ceil(np.log2(max(float(n), 1.0)))))


def nearest_pow2(n):
    return 1 << max(0, int(round(np.log2(max(float(n), 1.0)))))


def fit_sides(shares, caps, S, min_side=64):
    """shares: kaynak basina yuzey payi; caps: kaynak basina anlamli en buyuk kenar (cozunurluk x karo).
    -> 2'nin kuvveti kenarlar, toplam alan <= S^2 (en buyuk hucre yarilanarak)."""
    tot = float(sum(shares)) or 1.0
    sides = []
    for sh, cap in zip(shares, caps):
        s = nearest_pow2(S * np.sqrt(max(sh / tot, 1e-12)))
        sides.append(int(max(min_side, min(s, S, next_pow2(cap)))))
    while sum(s * s for s in sides) > S * S:
        i = int(np.argmax(sides))
        if sides[i] <= min_side:
            raise ValueError(f"atlas does not fit: {len(sides)} textures do not fit into {S}px even with {min_side}px cells")
        sides[i] //= 2
    return sides


def pack_pow2(sides, S):
    """2'nin kuvveti kareler -> sol-alt kose (x, y) listesi (ayni sirada). Dortlu agac; buyukten kucuge."""
    free = [(0, 0, S)]
    pos = [None] * len(sides)
    for i in sorted(range(len(sides)), key=lambda i: -sides[i]):
        s = sides[i]
        fits = [n for n in free if n[2] >= s]
        if not fits:
            raise ValueError("packing failed (total area exceeds S^2)")
        n = min(fits, key=lambda n: (n[2], n[1], n[0]))
        free.remove(n)
        x, y, ns = n
        while ns > s:
            ns //= 2
            free += [(x + ns, y, ns), (x, y + ns, ns), (x + ns, y + ns, ns)]
        pos[i] = (x, y)
    return pos


def resample(img, w, h):
    """(H, W, C) -> (h, w, C): once 2x kutu kucultme (h/w'nin iki katina inene kadar), sonra bilineer."""
    img = np.asarray(img, np.float32)
    H, W = img.shape[:2]
    while H >= 2 * h and W >= 2 * w and H >= 2 and W >= 2:
        img = img[: H // 2 * 2, : W // 2 * 2]
        img = 0.25 * (img[0::2, 0::2] + img[1::2, 0::2] + img[0::2, 1::2] + img[1::2, 1::2])
        H, W = img.shape[:2]
    if (H, W) == (h, w):
        return img
    ys = np.clip((np.arange(h) + 0.5) * H / h - 0.5, 0, H - 1)
    xs = np.clip((np.arange(w) + 0.5) * W / w - 0.5, 0, W - 1)
    y0 = np.floor(ys).astype(int)
    x0 = np.floor(xs).astype(int)
    y1, x1 = np.minimum(y0 + 1, H - 1), np.minimum(x0 + 1, W - 1)
    wy, wx = (ys - y0)[:, None, None], (xs - x0)[None, :, None]
    top = img[y0][:, x0] * (1 - wx) + img[y0][:, x1] * wx
    bot = img[y1][:, x0] * (1 - wx) + img[y1][:, x1] * wx
    return (top * (1 - wy) + bot * wy).astype(np.float32)


def uv_range(uv, eps=1e-3):
    """UV kumesinin karo araligi: (umin, vmin, nx, ny); nx/ny TILE_MAX ile sinirli (asan kisim uv_to_cell'de kirpilir)."""
    lo = np.floor(uv.min(0) + eps).astype(int)
    hi = np.ceil(uv.max(0) - eps).astype(int)
    n = np.clip(hi - lo, 1, TILE_MAX)
    return float(lo[0]), float(lo[1]), int(n[0]), int(n[1])


def build_atlas(items, S, pad_div=32, min_side=64):
    """items: [{"key", "pixels": (H, W, 4) alttan uste float | cagrilabilir (ayni diziyi dondurur) | None (duz renk),
    "size": (W, H) (pixels cagrilabilirse zorunlu), "color": (4,) | None, "share", "tiles": (nx, ny)}]
    -> (atlas (S, S, 4) alttan uste, layout {key: (x, y, side, pad)}).
    Cagrilabilir pixels: kaynaklar tek tek yuklenip hucreye kuculur (4096 doku ~270 MB float; hepsini ayni anda tutma)."""
    caps = []
    for it in items:
        if it.get("pixels") is None:
            caps.append(min_side)
        else:
            W, H = it["size"] if callable(it["pixels"]) else it["pixels"].shape[1::-1]
            nx, ny = it.get("tiles", (1, 1))
            caps.append(max(W * nx, H * ny))
    sides = fit_sides([it["share"] for it in items], caps, S, min_side)
    pos = pack_pow2(sides, S)
    atlas = np.zeros((S, S, 4), np.float32)
    atlas[..., 3] = 1.0
    layout = {}
    for it, s, (x, y) in zip(items, sides, pos):
        pad = max(2, s // pad_div)
        inner = s - 2 * pad
        if it.get("pixels") is None:
            atlas[y:y + s, x:x + s] = np.asarray(it.get("color") or (0.5, 0.5, 0.5, 1.0), np.float32)
        else:
            nx, ny = it.get("tiles", (1, 1))
            src = it["pixels"]() if callable(it["pixels"]) else it["pixels"]
            tile = resample(src, max(1, inner // nx), max(1, inner // ny))
            del src
            content = np.tile(tile, (ny, nx, 1)) if (nx, ny) != (1, 1) else tile
            if content.shape[:2] != (inner, inner):
                content = resample(content, inner, inner)
            atlas[y:y + s, x:x + s] = np.pad(content, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        layout[it["key"]] = (int(x), int(y), int(s), int(pad))
    return atlas, layout


def uv_to_cell(uv, cell, S, umin=0.0, vmin=0.0, nx=1, ny=1):
    """uv (N, 2) -> atlas UV. Hucre icerigi [umin, umin+nx] x [vmin, vmin+ny] araligini kaplar; disi kirpilir."""
    x, y, s, pad = cell
    inner = s - 2 * pad
    un = np.clip((uv[:, 0] - umin) / nx, 0.0, 1.0)
    vn = np.clip((uv[:, 1] - vmin) / ny, 0.0, 1.0)
    return np.stack([(x + pad + un * inner) / S, (y + pad + vn * inner) / S], 1)
