"""Toplu islem ISCI sureci (arka plan Blender): tek model -> eklenti zinciri -> Sollumz export + rig'li .blend + batch_report.json.

Panelin Batch dugmesi her model icin `blender -b --python batch_worker.py -- src=<model> out=<klasor> ped=<ad> [height=] [mode=] [tex=]`
calistirir: kullanicinin sahnesine dokunulmaz, her model ayri surecte. Normal acilista kullanicinin etkin eklentileri yuklenir (olculdu
2026-09-13, Blender 5.2.1 arka plan: bl_ext.user_default.muto_ped_rig + Sollumz etkin, bpy.ops.mpr ve Scene.mpr mevcut).
Adimlar panelle ayni operatorler (tools/t_full_chain.py ile ayni sira). Import'tan once sahne elle bosaltilir (factory ayari eklentileri
kaldirir). Blender 5.2 arka planda kapanista takildigi icin os._exit.
"""
import json
import os
import sys
import time
import traceback

import bpy

STEPS = (("strip", "strip_rig"), ("orient", "fix_orientation"), ("markers", "markers_auto"), ("fit", "fit"),
         ("weights", "weights"), ("gta_rest", "to_gta_rest"), ("validate", "validate"), ("export", "sollumz_export"))


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return dict(x.split("=", 1) for x in argv if "=" in x)


def _import(src):
    ext = os.path.splitext(src)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=src)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=src)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=src)
    else:
        raise RuntimeError(f"unsupported format {ext}")


def run(a):
    # mutlak yol sart: goreli out ile export dokuyu surecin calisma klasorune yazdi, Sollumz baska kokten okudu -> "Cannot read
    # ..._textures\ytd\head_diff_000_a_uni.dds" (olculdu 2026-09-13, zombi, out=out/batch_test/...)
    src, out, ped = os.path.abspath(a["src"]), os.path.abspath(a["out"]), a["ped"]
    os.makedirs(out, exist_ok=True)
    rep = dict(src=os.path.basename(src), ped=ped, steps={}, ok=False)
    t0 = time.time()
    try:
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        _import(src)
        arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        for ar in arms:
            ar.data.pose_position = "REST"                  # iskeletli model rest pozunda birlestirilir (t_prepare_model ile ayni)
        vl = bpy.context.view_layer
        vl.update()
        meshes = [o for o in bpy.data.objects if o.type == "MESH" and len(o.data.polygons) > 0]
        if not meshes:
            raise RuntimeError("no mesh with faces in the file")
        obj = max(meshes, key=lambda o: len(o.data.vertices))
        if len(meshes) > 1:
            with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=meshes, selected_editable_objects=meshes):
                bpy.ops.object.join()
        obj.name = ped
        rep["mesh"] = dict(parts=len(meshes), verts=len(obj.data.vertices), faces=len(obj.data.polygons), rigged=bool(arms),
                           shape_keys=obj.data.shape_keys is not None)
        s = bpy.context.scene.mpr
        rig = a.get("rig", "mp_m")
        s.rig_type = rig                                    # hayvan: Auto Markers ped'in oyun mesh'ini oturtur (core/animal_markers)
        s.target_height = float(a.get("height") or 0)       # hayvanda 0 = ped'in kendi oyun boyu (Scale to Height)
        if rig == "mp_m":
            s.ped_name, s.export_mode = ped, a.get("mode", "ADDON")
        else:
            # hayvan export'u yalniz vanilla hayvan ped'ini degistirir (MPR_OT_sollumz_export kurali): ad = iskeletin ped'i
            s.ped_name, s.export_mode = rig, "REPLACE"
        s.tex_mode, s.export_dir = a.get("tex", "YTD"), out
        rep["rig"] = rig
        ov = dict(selected_objects=[obj], selected_editable_objects=[obj], active_object=obj, object=obj)
        steps = STEPS
        if rig != "mp_m":
            # hayvan: Auto Markers olcekten bagimsiz, "Scale to Height" (Height 0) marker varsa eklem boylarindan olcekler (mesh boyu
            # durusla %22'ye kadar sapti; core/species.marker_scale) -> marker'lar olcekten ONCE
            order = ("strip", "markers", "orient", "fit", "weights", "gta_rest", "validate", "export")
            steps = tuple(sorted(STEPS, key=lambda st: order.index(st[0])))
        for key, opname in steps:
            if key == "strip" and not arms and obj.data.shape_keys is None and len(obj.vertex_groups) == 0 and \
                    not any(m.type == "ARMATURE" for m in obj.modifiers):
                rep["steps"][key] = "SKIPPED"
                continue
            for o in vl.objects:
                if o is not None:
                    o.select_set(o == obj)
            vl.objects.active = obj
            t = time.time()
            try:
                with bpy.context.temp_override(**ov):
                    res = next(iter(getattr(bpy.ops.mpr, opname)()), "?")
            except RuntimeError as e:
                res = "ERROR: " + str(e).strip().splitlines()[-1]
            rep["steps"][key] = res
            rep["t_" + key] = round(time.time() - t, 1)
            sc = bpy.context.scene
            if key == "markers" and "mpr_auto_gap" in sc:
                # hayvan Auto Markers oturma artigi (% boy); esigi asarsa panelde WARNING cikardi, raporda da gorunsun. Bu dosya
                # --python ile DOSYA olarak kosar -> `from .ops import` calismaz, esik operatorun sahneye yazdigindan okunur
                gap, limit = float(sc["mpr_auto_gap"]), float(sc.get("mpr_auto_gap_limit", 0.5))
                rep["auto_gap_pct"] = gap
                if gap > limit:
                    rep.setdefault("warnings", []).append(f"Auto Markers surface gap {gap:.2f}% of the height (close fit < {limit}%): "
                                                          f"check the markers in {ped}.blend")
            if res != "FINISHED":
                break
        rep["ok"] = all(v in ("FINISHED", "SKIPPED") for v in rep["steps"].values()) and len(rep["steps"]) == len(STEPS)
        res_dir = os.path.join(out, f"mpr_{ped}")
        if os.path.isdir(res_dir):
            rep["resource"] = {os.path.relpath(os.path.join(dp, f), res_dir): os.path.getsize(os.path.join(dp, f))
                               for dp, _, fs in os.walk(res_dir) for f in fs}
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{ped}.blend"), copy=True)
        rep["blend"] = f"{ped}.blend"
    except Exception:
        rep["error"] = traceback.format_exc()[-1500:]
    rep["sec"] = round(time.time() - t0, 1)
    with open(os.path.join(out, "batch_report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    print("MPR_BATCH " + json.dumps(rep, ensure_ascii=False))
    return rep


if __name__ == "__main__":
    run(_args())
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
