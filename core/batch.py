"""Toplu islem yardimcilari (bpy'siz): klasordeki modelleri topla, gecerli ve benzersiz addon ped adi uret, isci ciktisini ozetle."""
import json
import os
import re

MODEL_EXT = (".glb", ".gltf", ".fbx", ".obj")
PED_RE = re.compile(r"[a-z][a-z0-9_]{2,31}")
# ops.MPR_OT_sollumz_export ile ayni: addon ped adi vanilla ped adina benzememeli (ADDON kipi reddeder)
VANILLA_RE = re.compile(r"(a_[mfc]_|s_[mf]_|u_[mf]_|g_[mf]_|mp_[mfg]_|csb_|cs_|ig_|hc_|player_)")


def collect_models(folder):
    """Klasordeki (alt klasor YOK) model dosyalari, ada gore sirali."""
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if os.path.splitext(f)[1].lower() in MODEL_EXT and os.path.isfile(os.path.join(folder, f)))


def ped_name(prefix, path, taken):
    """prefix + dosya adindan [a-z0-9_] ad (<= 32), vanilla'ya benzemez, taken icinde benzersiz. taken guncellenir."""
    stem = re.sub(r"[^a-z0-9]+", "_", os.path.splitext(os.path.basename(path))[0].lower()).strip("_")
    pre = re.sub(r"[^a-z0-9_]+", "_", (prefix or "").lower())
    name = (pre + stem) or "ped"
    if not name[0].isalpha() or VANILLA_RE.match(name):
        name = "muto_" + name
    name = name[:32].rstrip("_")
    base, i = name, 2
    while name in taken or not PED_RE.fullmatch(name):
        tail = f"_{i}"
        name = (base[:32 - len(tail)].rstrip("_") or "ped") + tail
        i += 1
        if i > 999:
            raise ValueError(f"no valid ped name for {path}")
    taken.add(name)
    return name


def summarize(out_dirs):
    """Isci raporlari (batch_report.json) -> satirlar + sayac. Rapor yoksa isci cokmus sayilir."""
    rows = []
    for d in out_dirs:
        p = os.path.join(d, "batch_report.json")
        try:
            with open(p, encoding="utf-8") as fh:
                rep = json.load(fh)
        except (OSError, ValueError):
            rep = dict(ped=os.path.basename(d), ok=False, error="no report (worker crashed)")
        log = os.path.join(d, "worker_log.txt")
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as fh:
                rep["problems"] = sum(1 for line in fh if "[muto_ped_rig] PROBLEM:" in line)
        rows.append(rep)
    return rows, dict(total=len(rows), ok=sum(1 for r in rows if r.get("ok")), failed=sum(1 for r in rows if not r.get("ok")))
