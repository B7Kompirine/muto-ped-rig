"""Click Key Points ekran rehberi (Blender'siz): on gorunus insan figuru, nokta durumu (yapildi / siradaki / bekliyor), metinler.
bl/keyguide_draw.py yalniz cizer. Neden: kullanici "hangi kemigi koydugumu goremiyorum, ezberlemeyen yapamaz" (2026-09-14) — eski surum
yalniz baslik satirinda ad yaziyordu, tiklanan noktanin adi gorunmuyordu, sol / sag hangi taraf belirsizdi.
Ekran kurali: karakter kameraya bakar (Blender on gorunus, Numpad 1; karakter -Y'ye bakar) -> karakterin SOLU ekranin SAGINDA.
"""
from .keypoints import KEY_ORDER

# Figur, birim kutu: x -1..1 (ekranin sagi +), y 0 (taban) .. 1 (tepe). Tiklanan noktalar marker tanimina gore: baş = SKEL_Head (omuz
# cizgisinin ~%31 yukarisi, cene / kulak hizasi; autodetect kural v7), boyun = omuz hizasinda boyun kok, kalca = uyluk eklemi.
FIGURE_POINTS = {
    "head": (0.0, 0.875), "neck": (0.0, 0.79),
    "L_shoulder": (0.21, 0.775), "R_shoulder": (-0.21, 0.775),
    "L_wrist": (0.43, 0.47), "R_wrist": (-0.43, 0.47),
    "L_hip": (0.12, 0.50), "R_hip": (-0.12, 0.50),
    "L_ankle": (0.14, 0.05), "R_ankle": (-0.14, 0.05),
    # yalniz cizim icin (tiklanmaz)
    "_L_elbow": (0.33, 0.62), "_R_elbow": (-0.33, 0.62), "_L_knee": (0.13, 0.27), "_R_knee": (-0.13, 0.27),
    "_pelvis": (0.0, 0.52), "_head_top": (0.0, 0.99),
}
FIGURE_LINES = (("neck", "L_shoulder"), ("neck", "R_shoulder"), ("L_shoulder", "_L_elbow"), ("_L_elbow", "L_wrist"),
                ("R_shoulder", "_R_elbow"), ("_R_elbow", "R_wrist"), ("neck", "_pelvis"), ("_pelvis", "L_hip"), ("_pelvis", "R_hip"),
                ("L_hip", "_L_knee"), ("_L_knee", "L_ankle"), ("R_hip", "_R_knee"), ("_R_knee", "R_ankle"))
HEAD_CENTER, HEAD_RADIUS = (0.0, 0.90), 0.085          # bas dairesi (figur); tiklanan bas noktasi dairenin alt yarisinda

HINTS = {
    "head": "center of the head, at jaw / ear height",
    "neck": "base of the neck, at shoulder height",
    "shoulder": "the shoulder joint, top of the arm",
    "wrist": "the wrist joint",
    "hip": "the hip joint, where the leg starts (crotch height)",
    "ankle": "the ankle bone",
}
NAMES = {"head": "Head", "neck": "Neck", "shoulder": "Shoulder", "wrist": "Wrist", "hip": "Hip", "ankle": "Ankle"}

COLORS = dict(done=(0.36, 0.85, 0.47, 1.0), current=(1.0, 0.80, 0.18, 1.0), pending=(0.62, 0.64, 0.66, 0.9),
              line=(0.85, 0.87, 0.88, 0.55), panel=(0.04, 0.05, 0.06, 0.78), text=(1.0, 1.0, 1.0, 1.0), dim=(0.78, 0.80, 0.82, 1.0),
              left=(0.93, 0.80, 0.25, 1.0), right=(0.90, 0.35, 0.40, 1.0))


def part(key):
    return key.split("_", 1)[1] if key[:2] in ("L_", "R_") else key


def side(key):
    return {"L_": "L", "R_": "R"}.get(key[:2])


def display_name(key):
    s = {"L": "Left ", "R": "Right "}.get(side(key), "")
    return s + NAMES[part(key)]


def side_note(key):
    """Sol / sag karisikligini onleyen not; orta noktalarda None."""
    if side(key) == "L":
        return "LEFT = the character's own left: the RIGHT side of the screen when it faces you (front view, Numpad 1)"
    if side(key) == "R":
        return "RIGHT = the character's own right: the LEFT side of the screen when it faces you (front view, Numpad 1)"
    return None


def status(order, index):
    """{anahtar: 'done' | 'current' | 'pending'}"""
    return {k: ("done" if i < index else "current" if i == index else "pending") for i, k in enumerate(order)}


def title(order, index):
    if index >= len(order):
        return "All key points clicked"
    k = order[index]
    return f"Click: {display_name(k).upper()}   ({index + 1} / {len(order)})"


def guide_items(order, index, x0, y0, w, h):
    """Rehber paneli ciziminin piksel ogeleri. Panel sol alt (x0, y0), boyut w x h; figur panelin sol kismina sigdirilir.
    -> dict(panel=(x0, y0, w, h), lines=[((x, y), (x, y))], head=((x, y), r), points=[dict(key, x, y, r, state)],
            rows=[dict(key, text, state, x, y)]) — rows: sag sutunda numarali liste."""
    fig_w = min(w * 0.42, h * 0.62)
    cx = x0 + fig_w * 0.55
    pad = h * 0.06
    fy0, fh = y0 + pad, h - 2 * pad

    def px(p):
        return (cx + p[0] * fig_w * 0.5, fy0 + p[1] * fh)

    st = status(order, index)
    lines = [(px(FIGURE_POINTS[a]), px(FIGURE_POINTS[b])) for a, b in FIGURE_LINES]
    head = (px(HEAD_CENTER), HEAD_RADIUS * fh)
    base_r = max(3.0, h * 0.018)
    points = [dict(key=k, x=px(FIGURE_POINTS[k])[0], y=px(FIGURE_POINTS[k])[1],
                   r=base_r * (2.0 if st[k] == "current" else 1.0), state=st[k]) for k in order]
    rows = []
    col_x = x0 + fig_w * 1.12
    row_h = (h - 2 * pad) / max(len(order), 1)
    for i, k in enumerate(order):
        rows.append(dict(key=k, text=f"{i + 1:>2}  {display_name(k)}", state=st[k], x=col_x, y=y0 + h - pad - (i + 0.75) * row_h))
    return dict(panel=(x0, y0, w, h), lines=lines, head=head, points=points, rows=rows)


def check_tables():
    """Tutarlilik: her ana nokta figurde, cizgiler var olan noktalara, sol ekranin saginda. -> sorun listesi."""
    probs = [f"{k} not in figure" for k in KEY_ORDER if k not in FIGURE_POINTS]
    probs += [f"line {a}-{b}" for a, b in FIGURE_LINES if a not in FIGURE_POINTS or b not in FIGURE_POINTS]
    probs += [f"{k} not on screen right" for k in FIGURE_POINTS if k.lstrip("_").startswith("L_") and FIGURE_POINTS[k][0] <= 0]
    probs += [f"{k} not on screen left" for k in FIGURE_POINTS if k.lstrip("_").startswith("R_") and FIGURE_POINTS[k][0] >= 0]
    probs += [f"{k} has no hint" for k in KEY_ORDER if part(k) not in HINTS]
    return probs
