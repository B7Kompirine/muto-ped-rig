"""Click Key Points ekran rehberi cizimi (Blender gpu / blf). Veri ve yerlesim core/keyguide.py'de (tests/test_keyguide.py); burada yalniz
cizim. API adlari Sollumz 5.2 kodundaki kullanimla ayni (UNIFORM_COLOR, batch_for_shader, blf.size(font, float)).
Cizilenler: (1) ustte buyuk "Click: LEFT SHOULDER (3 / 10)" + nereye tiklanacagi + sol / sag notu + tuslar, (2) sol altta on gorunus
figuru (yapildi yesil, siradaki sari halka, bekleyen gri) ve numarali liste, (3) tiklanmis noktalarin yaninda adlari, (4) imlecin
altinda tiklaninca noktanin gidecegi yer (derinlik kurali dahil)."""
import math
import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..core import keyguide as kg

FONT = 0


def _tris(verts, color):
    if not verts:
        return
    sh = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(sh, "TRIS", {"pos": verts})
    sh.bind()
    sh.uniform_float("color", color)
    batch.draw(sh)


def rect(x, y, w, h, color):
    _tris([(x, y), (x + w, y), (x + w, y + h), (x, y), (x + w, y + h), (x, y + h)], color)


def disc(x, y, r, color, seg=20):
    v = []
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        v += [(x, y), (x + r * math.cos(a0), y + r * math.sin(a0)), (x + r * math.cos(a1), y + r * math.sin(a1))]
    _tris(v, color)


def ring(x, y, r, width, color, seg=36):
    v = []
    ri = max(r - width, 0.0)
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        p0o, p1o = (x + r * math.cos(a0), y + r * math.sin(a0)), (x + r * math.cos(a1), y + r * math.sin(a1))
        p0i, p1i = (x + ri * math.cos(a0), y + ri * math.sin(a0)), (x + ri * math.cos(a1), y + ri * math.sin(a1))
        v += [p0i, p0o, p1o, p0i, p1o, p1i]
    _tris(v, color)


def line(a, b, width, color):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return
    ox, oy = -dy / n * width / 2, dx / n * width / 2
    _tris([(a[0] + ox, a[1] + oy), (b[0] + ox, b[1] + oy), (b[0] - ox, b[1] - oy),
           (a[0] + ox, a[1] + oy), (b[0] - ox, b[1] - oy), (a[0] - ox, a[1] - oy)], color)


def text(x, y, s, size, color, shadow=True):
    blf.size(FONT, size)
    blf.color(FONT, *color)
    if shadow:
        blf.enable(FONT, blf.SHADOW)
        blf.shadow(FONT, 3, 0.0, 0.0, 0.0, 0.9)
        blf.shadow_offset(FONT, 1, -1)
    blf.position(FONT, x, y, 0)
    blf.draw(FONT, s)
    if shadow:
        blf.disable(FONT, blf.SHADOW)


def text_width(s, size):
    blf.size(FONT, size)
    return blf.dimensions(FONT, s)[0]


def _state_color(state):
    return kg.COLORS["done" if state == "done" else "current" if state == "current" else "pending"]


def draw(op):
    """SpaceView3D POST_PIXEL geri cagrisi. Yalniz operatorun calistigi 3D gorunumde cizer."""
    ctx = bpy.context
    area, region, rv3d = ctx.area, ctx.region, ctx.region_data
    if area is None or region is None or rv3d is None or area.as_pointer() != op._area_ptr:
        return
    try:
        _draw(op, ctx, region, rv3d)
    except Exception as e:                                   # cizim hatasi modal'i dusurmesin; bir kez yaz
        if not getattr(op, "_draw_error", False):
            op._draw_error = True
            print("[muto_ped_rig] Click Key Points guide draw failed:", repr(e))
    finally:
        gpu.state.blend_set("NONE")


def _draw(op, ctx, region, rv3d):
    from bpy_extras import view3d_utils
    sc = ctx.preferences.system.ui_scale
    order, i = op._order, op._i
    gpu.state.blend_set("ALPHA")
    c = kg.COLORS

    # (3) tiklanmis noktalar + adlari
    for k, p in op._placed.items():
        co = view3d_utils.location_3d_to_region_2d(region, rv3d, Vector([float(x) for x in p]))
        if co is None:
            continue
        disc(co.x, co.y, 4.5 * sc, c["done"])
        text(co.x + 9 * sc, co.y - 4 * sc, kg.display_name(k), 13 * sc, c["done"])

    # (4) imlec onizlemesi: tiklaninca noktanin gidecegi yer
    if i < len(order) and op._hover is not None:
        co = view3d_utils.location_3d_to_region_2d(region, rv3d, Vector([float(x) for x in op._hover]))
        if co is not None:
            ring(co.x, co.y, 11 * sc, 2.5 * sc, c["current"])
            disc(co.x, co.y, 3 * sc, c["current"])
            text(co.x + 15 * sc, co.y + 6 * sc, kg.display_name(order[i]), 15 * sc, c["current"])

    # (1) ust bilgi bandi
    title = kg.title(order, i)
    lines = []
    if i < len(order):
        k = order[i]
        lines.append((f"Where: {kg.HINTS[kg.part(k)]}", c["text"]))
        note = kg.side_note(k)
        if note:
            lines.append((note, c["left"] if kg.side(k) == "L" else c["right"]))
    lines.append(("Left click: place   ·   Right click / Backspace: undo   ·   Esc: stop   ·   Mouse wheel / middle mouse: view", c["dim"]))
    ts, ls = 24 * sc, 14 * sc
    band_w = max([text_width(title, ts)] + [text_width(s, ls) for s, _ in lines]) + 32 * sc
    band_h = ts + len(lines) * (ls + 8 * sc) + 26 * sc
    bx = max((region.width - band_w) / 2, 8 * sc)
    by = region.height - band_h - 48 * sc
    rect(bx, by, band_w, band_h, c["panel"])
    y = by + band_h - ts - 10 * sc
    text(bx + 16 * sc, y, title, ts, c["current"] if i < len(order) else c["done"])
    for s, col in lines:
        y -= ls + 8 * sc
        text(bx + 16 * sc, y, s, ls, col)

    # (2) sol alt rehber: figur + liste
    w, h = 360 * sc, 270 * sc
    x0, y0 = 58 * sc, 20 * sc                                # arac cubugunun sagi
    g = kg.guide_items(order, i, x0, y0, w, h)
    rect(*g["panel"], c["panel"])
    for a, b in g["lines"]:
        line(a, b, 2.2 * sc, c["line"])
    (hx, hy), hr = g["head"]
    ring(hx, hy, hr, 2.0 * sc, c["line"])
    for p in g["points"]:
        col = _state_color(p["state"])
        if p["state"] == "current":
            ring(p["x"], p["y"], p["r"] * 1.7, 2.5 * sc, col)
        disc(p["x"], p["y"], p["r"], col)
    for r in g["rows"]:
        col = _state_color(r["state"])
        prefix = "> " if r["state"] == "current" else "   "
        text(r["x"], r["y"], prefix + r["text"], (15 if r["state"] == "current" else 13) * sc, col, shadow=False)
    text(x0 + 10 * sc, y0 + h - 18 * sc, "FRONT VIEW (facing you)", 11 * sc, c["dim"], shadow=False)
