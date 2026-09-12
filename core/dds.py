"""Saf numpy DDS yazici: A8R8G8B8 ve DXT1/DXT5 (BC1/BC3), mip zinciri. Blender Python'unda Pillow ve texconv yok (olculdu 2026-09-11).

Sollumz gomulu dokuyu DISKTEKI DDS dosyasindan paketler; PNG gomulmez (atlas: arac-tuzaklari §1).
Atlas: 128 bayt baslik ("DDS " + 124), Blender pikselleri ALTTAN USTE, DDS USTTEN ALTA -> dikey cevir.
Mip zinciri zorunlu (uzakta yanlis ornekleme). Vanilla ped dokulari DXT (diffuse DXT1 512, spec DXT5 256), mip'leri 4x4'te biter.
DXT1 alfa tasimaz (atlas gta-temel: delikler kapanir) -> alfali doku DXT5.
"""
import struct
import numpy as np

DDSD_CAPS, DDSD_HEIGHT, DDSD_WIDTH, DDSD_PIXELFORMAT, DDSD_MIPMAPCOUNT, DDSD_LINEARSIZE = 0x1, 0x2, 0x4, 0x1000, 0x20000, 0x80000
DDPF_ALPHAPIXELS, DDPF_FOURCC, DDPF_RGB = 0x1, 0x4, 0x40
DDSCAPS_TEXTURE, DDSCAPS_MIPMAP, DDSCAPS_COMPLEX = 0x1000, 0x400000, 0x8
ALPHA_OPAQUE = 250 / 255        # AUTO: en dusuk alfa bunun altindaysa DXT5
CHUNK = 65536                   # blok parcasi (bellek: ~50 MB gecici)


def _next_pow2(n):
    return 1 << max(0, int(np.ceil(np.log2(max(n, 1)))))


def _resize_box(img, w, h):
    """Kutu filtre ile kucultme (2'nin kuvveti oranlarinda), buyutmede en yakin komsu."""
    H, W = img.shape[:2]
    if (W, H) == (w, h):
        return img
    if W % w == 0 and H % h == 0:
        fx, fy = W // w, H // h
        return img.reshape(h, fy, w, fx, img.shape[2]).mean(axis=(1, 3))
    ys = (np.arange(h) * H / h).astype(int)
    xs = (np.arange(w) * W / w).astype(int)
    return img[ys][:, xs]


def mip_chain(rgba, max_size=None):
    """rgba float [0,1] (H, W, 4) USTTEN ALTA -> seviye listesi (2'nin kuvveti, 1x1'e kadar).
    max_size: taban seviye bu kenar boyuna kadar kutu filtreyle yarilanir."""
    H, W = rgba.shape[:2]
    w, h = _next_pow2(W), _next_pow2(H)
    base = _resize_box(rgba, w, h)
    while max_size and max(w, h) > max_size and w > 1 and h > 1:
        w, h = w // 2, h // 2
        base = base[: 2 * h, : 2 * w].reshape(h, 2, w, 2, base.shape[2]).mean(axis=(1, 3))
    levels = [base]
    while w > 1 or h > 1:
        w, h = max(1, w // 2), max(1, h // 2)
        prev = levels[-1]
        ph, pw = prev.shape[:2]
        if ph >= 2 * h and pw >= 2 * w:
            levels.append(prev[: 2 * h, : 2 * w].reshape(h, 2, w, 2, 4).mean(axis=(1, 3)))
        else:
            levels.append(_resize_box(prev, w, h))
    return levels


def _header(w, h, nlev, fourcc=None, block_bytes=0):
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT | DDSD_MIPMAPCOUNT
    if fourcc:
        flags |= DDSD_LINEARSIZE
        size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block_bytes
        pixfmt = struct.pack("<II4sIIIII", 32, DDPF_FOURCC, fourcc, 0, 0, 0, 0, 0)
    else:
        size = w * h * 4
        pixfmt = struct.pack("<II4sIIIII", 32, DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 32,
                             0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header = struct.pack("<IIIIIII", 124, flags, h, w, size, 0, nlev) + b"\0" * 44 + pixfmt + \
        struct.pack("<IIIII", DDSCAPS_TEXTURE | DDSCAPS_MIPMAP | DDSCAPS_COMPLEX, 0, 0, 0, 0)
    assert len(header) == 124
    return b"DDS " + header


def dds_size(path):
    """DDS basligindan (genislik, yukseklik); DDS degilse None."""
    with open(path, "rb") as fh:
        head = fh.read(20)
    if len(head) < 20 or head[:4] != b"DDS ":
        return None
    h, w = struct.unpack("<II", head[12:20])
    return w, h


def write_a8r8g8b8(path, rgba_top_down, max_size=None):
    levels = mip_chain(np.clip(rgba_top_down, 0, 1), max_size)
    h, w = levels[0].shape[:2]
    with open(path, "wb") as fh:
        fh.write(_header(w, h, len(levels)))
        for lv in levels:
            px = np.rint(lv * 255).astype(np.uint8)
            fh.write(px[..., [2, 1, 0, 3]].tobytes())   # BGRA
    return w, h, len(levels)


# --- DXT1 / DXT5 ------------------------------------------------------------------------------------------------------
_W4 = np.array([1.0, 0.0, 2 / 3, 1 / 3], dtype=np.float32)                          # renk indeksi -> c0 agirligi
_W8 = np.array([1.0, 0.0, 6 / 7, 5 / 7, 4 / 7, 3 / 7, 2 / 7, 1 / 7], dtype=np.float32)  # alfa indeksi -> a0 agirligi


def _blocks(img):
    """(h, w, C) -> (N, 16, C) satir satir 4x4 bloklar (piksel k = y*4 + x); kenar tekrariyla 4'un katina doldurulur."""
    h, w, c = img.shape
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="edge")
    bh, bw = img.shape[0] // 4, img.shape[1] // 4
    return img.reshape(bh, 4, bw, 4, c).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, c)


def _to565(c):
    q = np.rint(np.clip(c, 0, 255) * np.array([31, 63, 31], np.float32) / 255).astype(np.uint16)
    return (q[..., 0] << 11) | (q[..., 1] << 5) | q[..., 2]


def _from565(v):
    v = v.astype(np.uint16)
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 3), (g << 2) | (g >> 4), (b << 3) | (b >> 3)], -1).astype(np.float32)


def _order(c0, c1):
    """4 renk kipi c0 > c1 ister; c0 <= c1 cozucuyu 3 renk kipine sokar (indeks 3 = seffaf SIYAH)."""
    return np.maximum(c0, c1), np.minimum(c0, c1)


def _color_fit(px, c0, c1):
    p0, p1 = _from565(c0), _from565(c1)
    pal = _W4[None, :, None] * p0[:, None, :] + (1 - _W4)[None, :, None] * p1[:, None, :]      # (N, 4, 3)
    d = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)                                # (N, 16, 4)
    idx = d.argmin(-1)
    return np.take_along_axis(d, idx[..., None], -1)[..., 0].sum(1), idx


def encode_color(px):
    """px (N, 16, 3) 0..255 -> (c0, c1, idx). Temel eksende aralik uydurma + bir en kucuk kareler turu (iyisi secilir)."""
    px = px.astype(np.float32)
    mean = px.mean(1)
    d = px - mean[:, None, :]
    cov = np.einsum("nki,nkj->nij", d, d)
    v = np.full((len(px), 3), 1 / np.sqrt(3), np.float32)
    for _ in range(6):
        v = np.einsum("nij,nj->ni", cov, v)
        v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-6)
    t = np.einsum("nki,ni->nk", d, v)
    c0, c1 = _order(_to565(mean + t.max(1)[:, None] * v), _to565(mean + t.min(1)[:, None] * v))
    err, idx = _color_fit(px, c0, c1)
    # en kucuk kareler: p_k ~ a_k*e0 + (1 - a_k)*e1, a = _W4[idx]
    a = _W4[idx]
    b = 1 - a
    aa, ab, bb = (a * a).sum(1), (a * b).sum(1), (b * b).sum(1)
    ap, bp = (a[..., None] * px).sum(1), (b[..., None] * px).sum(1)
    det = aa * bb - ab * ab
    ok = np.abs(det) > 1e-4
    s = np.where(ok, det, 1.0)[:, None]
    r0, r1 = _order(_to565((bb[:, None] * ap - ab[:, None] * bp) / s), _to565((aa[:, None] * bp - ab[:, None] * ap) / s))
    err2, idx2 = _color_fit(px, r0, r1)
    better = ok & (err2 < err)
    c0, c1 = np.where(better, r0, c0), np.where(better, r1, c1)
    idx = np.where(better[:, None], idx2, idx)
    idx[c0 == c1] = 0
    return c0, c1, idx


def encode_alpha(al):
    """al (N, 16) 0..255 -> (a0, a1, idx), 8 deger kipi (a0 > a1; esitse tek deger)."""
    a0 = np.rint(np.clip(al.max(1), 0, 255)).astype(np.uint8)
    a1 = np.rint(np.clip(al.min(1), 0, 255)).astype(np.uint8)
    pal = _W8[None, :] * a0[:, None] + (1 - _W8)[None, :] * a1[:, None]
    idx = np.abs(al[:, :, None] - pal[:, None, :]).argmin(-1)
    idx[a0 == a1] = 0
    return a0, a1, idx


def _pack(idx, bits):
    sh = np.arange(16, dtype=np.uint64) * np.uint64(bits)
    return (idx.astype(np.uint64) << sh[None, :]).sum(1, dtype=np.uint64)


_DT1 = np.dtype([("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")])
_DT5 = np.dtype([("a0", "u1"), ("a1", "u1"), ("ai", "u1", (6,)), ("c0", "<u2"), ("c1", "<u2"), ("i", "<u4")])


def encode_dxt(level, fmt):
    """level (h, w, 4) 0..1 ustten alta -> blok baytlari (DXT1 8, DXT5 16 bayt/blok)."""
    blocks = _blocks(level.astype(np.float32) * 255.0)
    parts = []
    for s in range(0, len(blocks), CHUNK):
        b = blocks[s:s + CHUNK]
        c0, c1, ci = encode_color(b[..., :3])
        out = np.zeros(len(b), dtype=_DT1 if fmt == "DXT1" else _DT5)
        out["c0"], out["c1"], out["i"] = c0, c1, _pack(ci, 2).astype(np.uint32)
        if fmt == "DXT5":
            a0, a1, ai = encode_alpha(b[..., 3])
            out["a0"], out["a1"] = a0, a1
            ap = _pack(ai, 3)
            out["ai"] = ((ap[:, None] >> (np.arange(6, dtype=np.uint64) * np.uint64(8))[None, :]) & np.uint64(0xFF)).astype(np.uint8)
        parts.append(out.tobytes())
    return b"".join(parts)


def pick_format(rgba):
    return "DXT5" if float(rgba[..., 3].min()) < ALPHA_OPAQUE else "DXT1"


def write_dxt(path, rgba_top_down, fmt="DXT1", max_size=None):
    if fmt not in ("DXT1", "DXT5"):
        raise ValueError(f"unsupported DXT format: {fmt}")
    levels = mip_chain(np.clip(rgba_top_down, 0, 1), max_size)
    levels = levels[:1] + [lv for lv in levels[1:] if min(lv.shape[:2]) >= 4]     # vanilla DXT mip'leri 4x4'te biter
    h, w = levels[0].shape[:2]
    with open(path, "wb") as fh:
        fh.write(_header(w, h, len(levels), fmt.encode(), 8 if fmt == "DXT1" else 16))
        for lv in levels:
            fh.write(encode_dxt(lv, fmt))
    return w, h, len(levels)


def blender_image_to_dds(image, path, max_size=None, fmt="A8R8G8B8"):
    """bpy.types.Image -> DDS dosyasi (piksel dikey cevrilir). fmt: A8R8G8B8 | DXT1 | DXT5 | AUTO (alfaya gore DXT1/DXT5).
    Donus: (bicim, w, h, seviye)."""
    w, h = image.size
    if w == 0 or h == 0:
        raise ValueError(f"empty texture: {image.name}")
    px = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(px)
    rgba = px.reshape(h, w, 4)[::-1]
    if fmt == "AUTO":
        fmt = pick_format(rgba)
    if fmt == "A8R8G8B8":
        return (fmt,) + write_a8r8g8b8(path, rgba, max_size)
    return (fmt,) + write_dxt(path, rgba, fmt, max_size)
