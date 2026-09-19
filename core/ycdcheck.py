"""Klip sozlugu XML'inin geri okunmasi (Blender'siz): Sollumz export'u ve CodeWalker'in derlenmis .ycd dokumu (res_to_xml) ayni bicim.

Olculen yapi (2026-09-14, Sollumz 5.2 eklentisi, 2 retarget klibi; scratchpad ycd_xml_probe): Sollumz klip <Hash>'i (bossa bos), <Name>
pack:/<ad>.clip, <AnimationHash> bagini ve Start/EndTime'i YAZAR; klipleri ve animasyonlari alfabetik dizer; mover yazilan animasyonda
Unknown10 = 16 (RootMotion). CodeWalker bilinmeyen adi hash_XXXXXXXX (joaat) olarak dokebilir -> ad ya da hash kabul edilir.
"""
import xml.etree.ElementTree as ET

FPS = 30
ROOT_MOTION_FLAG = 16


def joaat(s):
    h = 0
    for c in s.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def same_hash(text, name):
    t = (text or "").strip()
    return t.lower() == name.lower() or t.upper() == f"HASH_{joaat(name):08X}"


def _val(el, tag, cast=float, default=None):
    n = el.find(tag)
    if n is None:
        return default
    v = n.get("value")
    return cast(v) if v is not None else default


def read_clip_dictionary(path):
    """-> (klipler [dict], animasyonlar {hash: dict})"""
    root = ET.parse(path).getroot()
    clips = []
    for it in root.findall("./Clips/Item"):
        typ = it.find("Type")
        clips.append(dict(hash=(it.findtext("Hash") or "").strip(), name=(it.findtext("Name") or "").strip(),
                          type=typ.get("value") if typ is not None else None, anim=(it.findtext("AnimationHash") or "").strip(),
                          start=_val(it, "StartTime"), end=_val(it, "EndTime"), rate=_val(it, "Rate")))
    anims = {}
    for it in root.findall("./Animations/Item"):
        bids = it.find("BoneIds")
        items = bids.findall("Item") if bids is not None else []
        anims[(it.findtext("Hash") or "").strip()] = dict(
            frames=_val(it, "FrameCount", int), duration=_val(it, "Duration"), flags=_val(it, "Unknown10", int, 0),
            channels=len(items), bones=sorted({_val(b, "BoneId", int) for b in items}))
    return clips, anims


def check_clip_dictionary(path, expected, min_bones=20):
    """expected {klip adi: dict(frames=n, root_motion=bool)} -> dict(problems=[...], clips={ad: ozet}). Bos problems = gecti."""
    clips, anims = read_clip_dictionary(path)
    problems, summary = [], {}
    if len(clips) != len(expected):
        problems.append(f"{len(clips)} clips in the file, expected {len(expected)}")
    seen = set()
    for c in clips:
        name = next((n for n in expected if same_hash(c["hash"], n)), None)
        if name is None:
            problems.append(f"unexpected or empty clip hash '{c['hash']}' (a clip without a name cannot be played)")
            continue
        if name in seen:
            problems.append(f"clip '{name}' appears twice (same hash: one overwrites the other)")
        seen.add(name)
        a = next((v for h, v in anims.items() if h and h == c["anim"]), None)
        if a is None:
            problems.append(f"clip '{name}' points to animation '{c['anim']}' that is not in the file (the ped would not move)")
            continue
        exp = expected[name]
        secs = (exp["frames"] - 1) / FPS
        if a["frames"] != exp["frames"]:
            problems.append(f"clip '{name}': {a['frames']} frames, expected {exp['frames']}")
        if c["start"] is None or abs(c["start"]) > 1e-4 or c["end"] is None or abs(c["end"] - secs) > 1e-3:
            problems.append(f"clip '{name}': time {c['start']}..{c['end']} s, expected 0..{secs:.4f}")
        if c["rate"] is not None and abs(c["rate"] - 1.0) > 1e-4:
            problems.append(f"clip '{name}': rate {c['rate']}")
        if bool(a["flags"] & ROOT_MOTION_FLAG) != bool(exp.get("root_motion")):
            problems.append(f"clip '{name}': root motion flag {bool(a['flags'] & ROOT_MOTION_FLAG)}, expected {bool(exp.get('root_motion'))}")
        if len(a["bones"]) < min_bones:
            problems.append(f"clip '{name}': only {len(a['bones'])} bones animated")
        summary[name] = dict(frames=a["frames"], seconds=round(a["duration"] or 0.0, 4), bones=len(a["bones"]), channels=a["channels"],
                             root_motion=bool(a["flags"] & ROOT_MOTION_FLAG))
    for n in expected:
        if n not in seen:
            problems.append(f"clip '{n}' is missing")
    return dict(problems=problems, clips=summary)
