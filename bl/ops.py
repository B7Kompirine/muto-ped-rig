import time
import bpy
import numpy as np

from . import io
from ..core import markers as mk
from ..core.fit import fit_skeleton
from ..core import pipeline as pl
from ..core import weights as wt
from ..core.skeleton import lbs


def _meshes_or_fail(op, context):
    objs = io.selected_meshes(context)
    if not objs:
        op.report({"ERROR"}, "Select the character mesh first")
    return objs


def _poll_object_mode(cls, context, need_mesh):
    """Grey the button out instead of failing: Object Mode, plus a selected mesh for operators that work on meshes."""
    if context.mode != "OBJECT":
        cls.poll_message_set("Switch to Object Mode")
        return False
    if need_mesh and not any(o.type == "MESH" for o in (getattr(context, "selected_objects", None) or ())):
        cls.poll_message_set("Select the character mesh")
        return False
    return True


class _MeshOperator:
    @classmethod
    def poll(cls, context):
        return _poll_object_mode(cls, context, need_mesh=True)


class _ObjectModeOperator:
    @classmethod
    def poll(cls, context):
        return _poll_object_mode(cls, context, need_mesh=False)


def rig_root_offset(context, arm, tpl, objs, apply=False):
    """GTA rest (G) rig'inde taban -> SKEL_ROOT mesafesinin sablona gore sapmasi (m). apply=True: ROOT + IK_Root duzeltilir.
    Neden: bu duzeltmeden (2026-09-13) once G'ye cevrilip kaydedilen .blend eski koku tasir; dogrudan export oyunda comelme yapar
    (core/fit.ground_root, tools/t_ground_contact.py). None: olculemez (mesh yok / G degil)."""
    from ..core.fit import ground_root
    if arm is None or arm.get("mpr_stage") != "G" or not objs:
        return None
    V, _, _ = io.meshes_to_numpy(objs)
    W = io.rig_world_matrices(arm, tpl)
    W2, dz = ground_root(W, tpl, float(V[:, 2].min()), io.root_above_sole(context.scene.mpr.rig_type, tpl))
    if apply and abs(dz) > 1e-4:
        io.set_rest(arm, W2, tpl)
    return dz


# Iskelet mesh'e uymuyor (yalniz mesh ya da yalniz rig olceklenmis / tasinmis). Veri (2026-09-13, export geri okuma; SKEL_ROOT ve
# SKEL_Tail_* haric SKEL kemiginin mesh kutusu disina tasmasi / boy): saglam export'lar insan en cok %0,68 (zombi parmak), hayvan
# kuyruk disinda kutu icinde (kuyruk ucu geyik %13,5, yaban domuzu %5,4 -> haric); yalniz mesh x0,6 olceklenmis: SKEL_Head %48,6.
FIT_OUTSIDE_MAX = 0.10
# Iskelet mesh ICINDE kucuk kalirsa kutu disi olcutu yakalamaz (rig + mesh x1,5'te kayitli fit'le GTA rest: bas - taban 1,66 m, mesh 2,79 m,
# hicbir kemik disarida degil; tools/t_edit_after_fit.py) -> Weights aninda saklanan iskelet / mesh boy orani (io.skel_mesh_ratio) ile kiyas.
FIT_RATIO_MAX = 0.15
FIT_HINT = " — was only the mesh or only MPR_Rig scaled or moved? Scale / move both together, or run Fit Skeleton again"
# Tasma, iskelet ve mesh'i birlikte degistiren son adimdaki (Weights / GTA rest) tasmadan en cok bu kadar (boyun orani) buyuduyse sebep
# olcek degil yerlesimdir. Veri (2026-09-13, tools/t_animal_auto_chain.py pose=1 markers=manual): cakal ayak parmagi marker'i 14,5 cm
# yanlis -> SKEL_L_Toe1 8 cm disarida (%10), GTA rest'ten beri ayni; yalniz mesh x0,6: SKEL_Head %48,6.
FIT_OUTSIDE_GROW = 0.03


def skel_outside(arm, tpl, objs):
    """-> (kemik, mesh kutusu disina en cok tasma m, mesh boyu m) ya da None. Dunya uzayinda, kok ve kuyruk haric SKEL kemikleri."""
    V, _, _ = io.meshes_to_numpy(objs)
    lo, hi = V.min(0), V.max(0)
    H = float(hi[2] - lo[2])
    if H < 1e-6:
        return None
    W = io.rig_world_matrices(arm, tpl)
    worst = None
    for i, n in enumerate(tpl.names):
        if not n.startswith("SKEL_") or n == "SKEL_ROOT" or n.startswith("SKEL_Tail"):
            continue
        d = float(np.max(np.maximum(lo - W[i, :3, 3], W[i, :3, 3] - hi)))
        if worst is None or d > worst[1]:
            worst = (n, d)
    return None if worst is None else (worst[0], worst[1], H)


def store_fit_baseline(arm, tpl, objs):
    """Iskeleti ve mesh'i BIRLIKTE degistiren adimin sonunda (Weights, GTA rest): sonraki uyum kontrolu bu tabana gore yapilir."""
    arm["mpr_skel_ratio"] = io.skel_mesh_ratio(arm, tpl, objs)
    out = skel_outside(arm, tpl, objs)
    arm["mpr_outside"] = out[1] / out[2] if out else 0.0


def rig_mesh_ratio_problem(arm, tpl, objs):
    """-> sorun metni ya da None: iskelet / mesh boy orani kayitli tabandan FIT_RATIO_MAX'tan fazla farkli (ayri olcek / tasima)."""
    was = arm.get("mpr_skel_ratio")
    now = io.skel_mesh_ratio(arm, tpl, objs)
    if was and now and abs(now / was - 1) > FIT_RATIO_MAX:
        return (f"the skeleton and the mesh were scaled differently after Compute Weights (skeleton / mesh height {now:.2f}, it was "
                f"{was:.2f})" + FIT_HINT)
    return None


def rig_mesh_fit_problem(arm, tpl, objs):
    """-> sorun metni ya da None. Dunya uzayinda (rig ve mesh nesne donusumleri dahil): SKEL kemigi mesh kutusu disinda (kok ve kuyruk
    haric, boyun FIT_OUTSIDE_MAX'i) ya da iskelet / mesh boy orani kayitli tabandan FIT_RATIO_MAX'tan fazla farkli."""
    if arm is None or not objs:
        return None
    out = skel_outside(arm, tpl, objs)
    if out is not None and out[1] / out[2] > FIT_OUTSIDE_MAX:
        n, d, H = out
        msg = f"the skeleton does not fit the mesh: {n} is {d * 100:.0f} cm outside it ({d / H:.0%} of the height)"
        base = arm.get("mpr_outside")
        if base is not None and d / H - base <= FIT_OUTSIDE_GROW:
            return msg + (" — it was already outside after Compute Weights / GTA Rest Pose, so a marker near it is off: move that marker, "
                          "then run Fit Skeleton and Compute Weights again")
        return msg + FIT_HINT
    return rig_mesh_ratio_problem(arm, tpl, objs)


class MPR_OT_markers_add(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_add"
    bl_label = "Add Markers"
    bl_description = "Create vanilla joint markers scaled to the selected mesh's bounding box (drag them to adjust)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        from ..core import autodetect as ad
        from ..core import species as sp
        V, _, _ = io.meshes_to_numpy(objs)
        tpl = io.template()
        lo, hi = V.min(0), V.max(0)
        if sp.family(tpl) == "quad":
            # insan yon/boy kontrolu (ayak yonu, 0,8-3 m) dort ayakliya uymaz; hayvan -Y'ye bakar, sablon ped'in mesh kutusuna olceklenir
            rlo, rhi = io.animal_ref_bbox(context.scene.mpr.rig_type)
            pos = sp.initial_guess(tpl, lo, hi, rlo, rhi)
            io.set_markers(pos, context.scene.mpr.marker_size)
            context.scene.mpr.mirror_x = float((lo[0] + hi[0]) / 2)
            self.report({"INFO"}, f"{len(pos)} animal markers created (head toward -Y) — drag them onto the joints")
            return {"FINISHED"}
        chk = ad.orientation_check(V, target_height=context.scene.mpr.target_height or None)
        if chk["problems"]:
            self.report({"ERROR"}, "; ".join(chk["problems"]) + " — run 'Fix Orientation/Scale' first")
            return {"CANCELLED"}
        pos = mk.initial_guess(tpl, lo, hi, io.VANILLA_LO, io.VANILLA_HI)
        io.set_markers(pos, context.scene.mpr.marker_size)
        context.scene.mpr.mirror_x = float((lo[0] + hi[0]) / 2)
        self.report({"INFO"}, f"{len(pos)} markers created")
        return {"FINISHED"}


def bvh_cache(objs):
    """[(BVHTree nesne uzayinda, matrix_world kopyasi)] — Click Key Points imlec onizlemesi her fare hareketinde yeniden kurmasin."""
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    return [(BVHTree.FromObject(ob, dg), ob.matrix_world.copy()) for ob in objs]


def mesh_ray_hits(objs, origin, direction, max_hits=24, cache=None):
    """Dunya isininin secili mesh'lerle tum carpma mesafeleri (isin yonunde, sirali). BVH degerlendirilmis mesh'ten, nesne uzayinda."""
    from mathutils import Vector
    o0, d0 = Vector(origin), Vector(direction).normalized()
    ts = []
    for bvh, mw in (cache if cache is not None else bvh_cache(objs)):
        inv = mw.inverted()
        start, ld = inv @ o0, (inv.to_3x3() @ d0).normalized()
        for _ in range(max_hits):
            co, _n, _i, _d = bvh.ray_cast(start, ld)
            if co is None:
                break
            ts.append(float((mw @ co - o0).dot(d0)))
            start = co + ld * 1e-5
    return sorted(t for t in ts if t > 0.0)


def place_key_point(objs, origin, direction, key, placed, vanilla, size):
    """Tiklama isini -> ana nokta marker'i (core/keypoints.click_point). Donus konum ya da None (mesh'e carpmadi)."""
    from ..core import keypoints as kp
    p = kp.click_point(origin, direction, mesh_ray_hits(objs, origin, direction), key)
    if p is None:
        return None
    placed[key] = p
    io.set_markers({key: p}, size)
    return p


def finish_key_points(context, objs, placed, vanilla):
    """Ana noktalar tamam: otomatik algilama (Auto Markers ile ayni yol; parmak / yuz sablonlari dahil) -> ana noktalar ustune, dirsek / diz
    propagate_linked, leğen sablondan; algilama basarisizsa tum marker'lar sablondan. Donus (marker sayisi, kaynak metni)."""
    from ..core import keypoints as kp
    s = context.scene.mpr
    detected = None
    with context.temp_override(selected_objects=objs, selected_editable_objects=objs, active_object=objs[0], object=objs[0]):
        try:
            if "FINISHED" in bpy.ops.mpr.markers_auto():
                # yeni marker nesnesinin matrix_world'u guncellemeye kadar orijinde (olculdu 2026-09-14, t_click_keypoints: okunan leğen 104 cm)
                context.view_layer.update()
                detected = io.read_markers()
        except RuntimeError:
            detected = None
    out = kp.fill_markers(placed, vanilla, detected)
    if not s.detail_fingers:                            # sablon yolu parmak eklemi de doldurur; Fingers kapaliyken marker olmaz
        out = {k: v for k, v in out.items() if not mk.is_finger_key(k)}
    io.set_markers({k: v for k, v in out.items() if not mk.is_face_key(k)}, s.marker_size)
    if detected is None:
        V, _, _ = io.meshes_to_numpy(objs)
        s.mirror_x = float((V[:, 0].min() + V[:, 0].max()) / 2)
    return len(out), ("automatic detection" if detected is not None else "the GTA template (automatic detection failed)")


class MPR_OT_markers_click(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_click"
    bl_label = "Click Key Points"
    bl_description = ("Semi-automatic markers: click 10 key points on the mesh in order. An on-screen guide shows which point comes next, "
                      "where exactly to click and which side is the character's left; a ring under the cursor shows where the point will "
                      "go. The other markers are filled from these points and automatic detection. Right click or Backspace: undo · Esc: stop")
    bl_options = {"REGISTER", "UNDO"}
    PASS = {"MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM", "NDOF_MOTION"}

    def invoke(self, context, event):
        from ..core import keypoints as kp
        from . import keyguide_draw
        area = context.area
        if area is None or area.type != "VIEW_3D":
            self.report({"ERROR"}, "Run Click Key Points from the 3D View sidebar")
            return {"CANCELLED"}
        if context.scene.mpr.rig_type != "mp_m":
            self.report({"ERROR"}, "Click Key Points works with the human skeleton; use Add Markers for animals")
            return {"CANCELLED"}
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        self._objs = [o.name for o in objs]
        self._placed, self._i, self._hover = {}, 0, None
        self._vanilla = mk.vanilla_markers(io.template(), mk.BASIC + [f"{S}_f2{j}" for S in "LR" for j in range(3)])
        self._order = kp.KEY_ORDER
        self._bvh = bvh_cache(objs)                              # imlec onizlemesi her harekette BVH kurmasin
        self._area_ptr = area.as_pointer()
        # rehber: siradaki nokta, nereye, sol / sag; tiklanan noktalarin adlari; imlecin altinda gidecegi yer (bl/keyguide_draw.py).
        # Neden: kullanici "hangi kemigi koydugumu goremiyorum, ezberlemeyen yapamaz" (2026-09-14) — eski surum yalniz baslik satiri yaziyordu
        self._handle = bpy.types.SpaceView3D.draw_handler_add(keyguide_draw.draw, (self,), "WINDOW", "POST_PIXEL")
        context.window.cursor_modal_set("CROSSHAIR")
        self._prompt(context)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _prompt(self, context):
        from ..core import keyguide as kg
        k = self._order[self._i]
        context.area.header_text_set(f"{kg.title(self._order, self._i)} — {kg.HINTS[kg.part(k)]}")
        context.area.tag_redraw()

    def _finish(self, context):
        if getattr(self, "_handle", None) is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            self._handle = None
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, RuntimeError):
            pass
        if context.area is not None:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def cancel(self, context):
        self._finish(context)

    @staticmethod
    def _view_ray(context, event):
        """(origin, direction) 3D gorunumun WINDOW bolgesinden, ya da imlec panelde / basliktaysa None. Operator yan panel dugmesinden
        basildigi icin context.region yan panel olabilir; fare koordinati o bolgeye gore gelirse isin yanlis yere gider."""
        from bpy_extras import view3d_utils
        area = context.area
        if area is None:
            return None
        mx, my = event.mouse_x, event.mouse_y
        for r in area.regions:                                 # ust uste binen yan panel / arac cubugu / baslik: tiklama onlara
            if r.type != "WINDOW" and r.width > 1 and r.height > 1 and r.x <= mx < r.x + r.width and r.y <= my < r.y + r.height:
                return None
        win = next((r for r in area.regions if r.type == "WINDOW"), None)
        rv3d = area.spaces.active.region_3d if area.spaces.active else None
        if win is None or rv3d is None:
            return None
        co = (mx - win.x, my - win.y)
        if not (0 <= co[0] < win.width and 0 <= co[1] < win.height):
            return None
        return view3d_utils.region_2d_to_origin_3d(win, rv3d, co), view3d_utils.region_2d_to_vector_3d(win, rv3d, co)

    def modal(self, context, event):
        from ..core import keypoints as kp
        if context.area is None:
            self._finish(context)
            return {"CANCELLED"}
        if event.type in {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}:
            ray = self._view_ray(context, event)
            self._hover = None
            if ray is not None and self._i < len(self._order):
                hits = mesh_ray_hits(None, ray[0], ray[1], cache=self._bvh)
                self._hover = kp.click_point(ray[0], ray[1], hits, self._order[self._i])
            context.area.tag_redraw()
            return {"PASS_THROUGH"}
        if event.type in self.PASS or event.type.startswith("NUMPAD"):
            return {"PASS_THROUGH"}
        if event.value != "PRESS":
            return {"RUNNING_MODAL"}
        if event.type == "ESC":
            self._finish(context)
            self.report({"INFO"}, f"Click Key Points stopped after {self._i} points (placed markers kept)")
            return {"CANCELLED"}
        if event.type in {"RIGHTMOUSE", "BACK_SPACE"}:
            if self._i > 0:
                self._i -= 1
                k = self._order[self._i]
                self._placed.pop(k, None)
                io.remove_markers([k])
                self._prompt(context)
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE":
            ray = self._view_ray(context, event)
            if ray is None:
                return {"PASS_THROUGH"}                          # panel / baslik tiklamasi: arayuz calismaya devam etsin
            objs = [bpy.data.objects[n] for n in self._objs if n in bpy.data.objects]
            k = self._order[self._i]
            p = kp.click_point(ray[0], ray[1], mesh_ray_hits(objs, ray[0], ray[1], cache=self._bvh), k)
            if p is None:
                self.report({"WARNING"}, f"{mk.label(k)}: the click missed the character — click on the mesh")
                return {"RUNNING_MODAL"}
            self._placed[k] = p
            io.set_markers({k: p}, context.scene.mpr.marker_size)
            self._i += 1
            self._hover = None
            if self._i < len(self._order):
                self._prompt(context)
                return {"RUNNING_MODAL"}
            self._finish(context)
            n, src = finish_key_points(context, objs, self._placed, self._vanilla)
            self.report({"INFO"}, f"{len(self._order)} key points clicked, {n} markers filled from {src} — check them and drag to adjust")
            return {"FINISHED"}
        return {"RUNNING_MODAL"}


class MPR_OT_markers_from_rig(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_from_rig"
    bl_label = "Markers from Existing Rig"
    # OLCULDU (2026-09-14, tools/t_markers_from_rig.py + Sollumz 13 insan klibi, en kotu kare kotu kenar % toplam, otomatik -> iskeletten):
    # Xbot (Mixamo) 2,527 -> 2,810, Winter Soldier (Unreal) 3,052 -> 3,243; ikisinde de 9 / 13 klip kotu, kol / el / diz bolgesi kotu, govde
    # iyi. Kaynak iskelet GTA'ya kalibre degil (Auto Markers omuz 6,5 / 10 cm farkli) -> YEDEK yol: Auto Markers basarisizsa.
    bl_description = ("Fallback when Auto Markers fails: place the markers on the joints of the model's own skeleton (Mixamo / Ready Player "
                      "Me / Tripo, Unreal) — run it BEFORE 'Remove Existing Rig'. Auto Markers usually deforms arms and hands better in "
                      "GTA animations, because other skeletons place shoulders and knees differently")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        from ..core import autodetect as ad
        from ..core import rigmap as rm
        if context.scene.mpr.rig_type != "mp_m":
            self.report({"ERROR"}, "Markers from Existing Rig works with human skeletons (Mixamo / Unreal); use Add Markers for animals")
            return {"CANCELLED"}
        arms = io.foreign_armatures(objs)
        if not arms:
            self.report({"ERROR"}, "The selected meshes have no skeleton of their own (already removed?) — use Auto Markers")
            return {"CANCELLED"}
        arm = max(arms, key=lambda a: len(a.data.bones))
        name, mapping = rm.detect([b.name for b in arm.data.bones])
        if name is None:
            self.report({"ERROR"}, f"Skeleton '{arm.name}' not recognized (supported: Mixamo / Ready Player Me, Unreal) — use Auto Markers")
            return {"CANCELLED"}
        V, _, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V, target_height=context.scene.mpr.target_height or None)
        if chk["problems"]:
            self.report({"ERROR"}, "; ".join(chk["problems"]) + " — run 'Fix Orientation/Scale' first")
            return {"CANCELLED"}
        # REST eklemleri (head_local): iskelet silinince mesh rest'e doner, marker'lar onunla ayni yerde kalir
        heads = {b.name: np.array(arm.matrix_world @ b.head_local) for b in arm.data.bones}
        pos = rm.markers_from_heads(mapping, heads)
        io.set_markers(pos, context.scene.mpr.marker_size)
        context.scene.mpr.mirror_x = float((V[:, 0].min() + V[:, 0].max()) / 2)
        miss = [mk.label(k) for k in mk.REQUIRED if k not in pos]
        self.report({"WARNING" if miss else "INFO"},
                    f"{len(pos)} markers from the {name} skeleton '{arm.name}'" + (f" | missing: {', '.join(miss)}" if miss else "") +
                    " — now run 'Remove Existing Rig'")
        return {"FINISHED"}


# Auto Markers (hayvan) oturma artigi uyari esigi, mesh boyunun yuzdesi (veri execute icinde)
AUTO_GAP_WARN = 0.5


class MPR_OT_markers_auto(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_auto"
    bl_label = "Auto Markers"
    bl_description = ("Find the joints of the selected character automatically. Humanoid: upright, facing -Y, A-pose works best (about "
                      "3-4 cm average error). Animal: standing, head toward -Y; the chosen ped's own game mesh is fitted onto the model — "
                      "close on a model shaped like that animal, but on another species or a strongly posed model some markers can be "
                      "10+ cm off (the report shows the surface gap and warns). Drag the markers to adjust afterwards")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..core import autodetect as ad
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        if context.scene.mpr.rig_type != "mp_m":
            # hayvan: ped'in kendi oyun mesh'i iskelet guduumlu ICP ile modele oturtulur (core/animal_markers, olcum orada)
            import os
            from ..core import animal_markers as am
            key = context.scene.mpr.rig_type
            V, _, _ = io.meshes_to_numpy(objs)
            ref = np.load(os.path.join(io.ANIMAL_DATA, f"ref_{key}.npz"))
            t0 = time.time()
            pos, info = am.auto_markers(io.template(), ref["V"], ref["WI"], ref["WV"], V)
            io.set_markers(pos, context.scene.mpr.marker_size)
            context.scene.mpr.mirror_x = float((V[:, 0].min() + V[:, 0].max()) / 2)
            # oturma artigi (medyan yuzey mesafesi / mesh boyu), olcekten bagimsiz. Veri (2026-09-13, tools/t_animal_auto_residual.py;
            # cakal / geyik / yaban domuzu / retriever): kendi mesh'i duruş <= 1 -> %0,00-0,83, marker max <= 3,8 cm; guclu duruş ya da BASKA
            # TUR mesh'i (12 capraz cift) -> %0,87-3,37, marker max 13,7-91,7 cm (en yakin cakal <-> retriever bile ort 4-5 / max 14-17 cm)
            H = float(np.ptp(V[:, 2]))
            gap = float(info["surface_residual_median"]) / H * 100 if H > 1e-6 else 0.0
            # toplu islem raporu okur (bl/batch_worker.py dosya olarak kosar: paketten import edemez, esik de sahneye yazilir)
            context.scene["mpr_auto_gap"] = round(gap, 3)
            context.scene["mpr_auto_gap_limit"] = AUTO_GAP_WARN
            if gap > AUTO_GAP_WARN:
                # bolge adlari olculen en kotu marker'lardan (scratchpad bone_residual_eval, 24 vaka: kuyruk ucu, pati, boyun, gogus,
                # kurek, diz). Kemik basina artikla "su 3 marker'i kontrol et" DENENDI, EKLENMEDI: capraz turde en kotu marker ilk 3'te
                # yalniz 2 / 8 (sira korelasyonu ~0,1-0,4) -> yanlis marker'i gosterip asil kotuyu atlatabilir
                self.report({"WARNING"}, f"{len(pos)} animal markers placed from the {key} game mesh, but the surface gap is {gap:.2f}% of the "
                                         f"height (a close fit is under {AUTO_GAP_WARN}%): the model's shape or pose differs from the {key}, "
                                         "some markers can be 10+ cm off — check every marker (tail tip, paws, neck, chest, shoulder blades, "
                                         "knees) before Fit Skeleton")
            else:
                self.report({"INFO"}, f"{len(pos)} animal markers fitted from the {key} game mesh ({time.time() - t0:.1f}s; surface gap "
                                      f"{gap:.2f}% of the height; head must point to -Y) — check them and drag to adjust")
            return {"FINISHED"}
        V, F, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V, target_height=context.scene.mpr.target_height or None)
        if chk["problems"]:
            self.report({"ERROR"}, "; ".join(chk["problems"]) + " — run 'Fix Orientation/Scale' first")
            return {"CANCELLED"}
        t0 = time.time()
        try:
            det, _info = ad.detect(V, F, io.template(), log=lambda *a: None)
        except ValueError as e:
            self.report({"ERROR"}, f"Automatic detection failed: {e} — use 'Click Key Points' (or More Marker Tools > Add Markers)")
            return {"CANCELLED"}
        H = float(np.ptp(V[:, 2]))
        xc = float(_info["xc"])         # algilamanin kullandigi orta hat (autodetect.CENTER_MODE)
        det = ad.apply_calibration(det, ad.load_calibration(), H, xc)
        s = context.scene.mpr
        notes = []                      # rapor: kapidan donen sablonlar (kullanici neden mesh tabanli sonucu gordugunu bilsin)
        if s.detail_fingers:
            # parmak uclari / orta zincir / avuc yonu / bogum (autodetect) + istege bagli el sablon kaydi (core/handreg)
            from ..core import handreg
            handreg.LAST.clear()
            det.update(ad.palm_markers(V, det, io.template(), F, hand_reg=s.hand_template))
            skipped = sorted(S for S, d in handreg.LAST.items() if d.get("rejected")) if s.hand_template else []
            if skipped:
                side = {"L": "left", "R": "right"}
                notes.append(f"Hand Template skipped for the {' and '.join(side[S] for S in skipped)} hand (it did not fit; mesh-based fingers kept)")
        if s.detail_face and s.face_template:
            from ..core import headreg
            headreg.LAST.clear()
            fm = headreg.head_markers(V, det, io.template())              # 22 yuz kemigi (FB_/FACIAL_) kafa sablon kaydindan
            if headreg.LAST.get("rejected"):
                notes.append("Face Template skipped (the head does not match the GTA heads)")
            det.update(fm)
            if "FACIAL_facialRoot" in fm:
                # GTA'da facialRoot = SKEL_Head konumu (12 sablon); kayit Head'i 2,03 -> 1,29 cm iyilestiriyor (tests/an_headreg.py head=1)
                det["head"] = fm["FACIAL_facialRoot"]
        if not s.detail_fingers:
            # algilama orta parmak zincirini (L/R_f20-22) her zaman verir; Fingers kapaliyken marker olarak birakilmaz. Olcum (2026-09-14,
            # scratchpad f2_hand_eval, Xbot): el kemigi yonu Fingers acik Fit'e gore zincirle 25,5°, zincirsiz 26,5° -> fark ~1°
            det = {k: v for k, v in det.items() if not mk.is_finger_key(k)}
        is_face = mk.is_face_key
        # kapatilan secenekten kalan parmak/yuz marker'lari Fit'e eski hedef olmasin
        io.remove_markers([k for k in io.read_markers() if k not in det and (is_face(k) or mk.is_finger_key(k))])
        io.set_markers({k: v for k, v in det.items() if not is_face(k)}, s.marker_size)
        io.set_markers({k: v for k, v in det.items() if is_face(k)}, s.marker_size * 0.3)   # yuz kemikleri 1-2 cm arali
        context.scene.mpr.mirror_x = xc
        msg = f"{len(det)} markers found ({time.time()-t0:.1f}s) — check them and drag to adjust" + "".join(f" | {n}" for n in notes)
        rigged = [o.name for o in objs if o.data.shape_keys is not None or any(
            m.type == "ARMATURE" and (m.object is None or m.object.name != io.RIG_NAME) for m in o.modifiers)]
        if rigged:
            self.report({"WARNING"}, msg + f" | existing rig/shape keys: {', '.join(rigged[:3])} — run 'Remove Existing Rig' before weighting")
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MPR_OT_fix_orientation(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.fix_orientation"
    bl_label = "Fix Orientation/Scale"
    bl_description = ("Turn the selected character in 90° steps around Z so the feet point to -Y; rescale centimeters/millimeters "
                      "to meters; apply rotation and scale (undo with Ctrl+Z). Animal: scale to Height, or with Height 0 to the ped's "
                      "own size — from the markers' bone lengths when markers exist (pose does not matter), otherwise from the mesh height")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from mathutils import Matrix
        from ..core import autodetect as ad
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        if context.scene.mpr.rig_type != "mp_m":
            # ayak yonu / 0,8-3 m boy kurallari insan govdesinden olculdu, dort ayakliya uygulanirsa yanlis dondurur -> hayvanda yalniz hedef
            # boya olcek (tabandan; yon kullanicida). Zemin koku ped'in kendi oyun mesh'ine gore kuruldugu icin her boyda ayak yerde kalir.
            th = context.scene.mpr.target_height
            V, _, _ = io.meshes_to_numpy(objs)
            lo, hi = V.min(0), V.max(0)
            H = float(hi[2] - lo[2])
            if H < 1e-6:
                self.report({"ERROR"}, "The selected mesh has no height")
                return {"CANCELLED"}
            from ..core import species as sp
            if th:
                f, src = th / H, f"height {H:.2f} -> {th:.2f} m"
            else:
                # hayvan klipleri bacak eklemlerine KONUM yazar (vanilla ped kemik boyu) -> varsayilan hedef ped'in kendi boyu
                # (cakal 0,743 / 0,45 / 1,2 m: Sollumz en kotu kare kotu kenar %12,0 / 17,2 / 10,7; tools/t_animal_scale_check.py).
                # Marker varsa eklem boylarindan (durustan bagimsiz); yoksa mesh boyundan (kalkik kuyruk / egik bas boyu degistirir:
                # cakal guclu durusta %-16,9 kucultup Auto Markers'i 11,5 cm'ye bozdu; core/species.marker_scale)
                rlo, rhi = io.animal_ref_bbox(context.scene.mpr.rig_type)
                f_h = float(rhi[2] - rlo[2]) / H
                ratio, nseg = sp.marker_scale(io.template(), io.read_markers())
                if ratio:
                    f, src = 1.0 / ratio, f"from the markers' bone lengths ({nseg} segments; the mesh height alone would give x{f_h:.3f})"
                else:
                    f, src = f_h, (f"height {H:.2f} -> {rhi[2] - rlo[2]:.2f} m (run Auto Markers first to scale by bone lengths: a raised "
                                   "tail or lowered head changes the height)")
            c = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]], float)
            pivot = Matrix.Translation([float(x) for x in c])
            M = pivot @ Matrix.Scale(f, 4) @ pivot.inverted()
            for o in objs:
                o.matrix_world = M @ o.matrix_world
            applied = True
            try:
                with context.temp_override(selected_editable_objects=objs, selected_objects=objs, active_object=objs[0], object=objs[0]):
                    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            except RuntimeError:
                applied = False
            moved = io.scale_markers(c, f)                       # marker'lar mesh'le birlikte (yoksa eklemlerden kayar)
            s = context.scene.mpr
            s.mirror_x = float(c[0] + f * (s.mirror_x - c[0]))
            rig_note = " | MPR_Rig was not scaled: run Fit Skeleton again" if bpy.data.objects.get(io.RIG_NAME) is not None else ""
            self.report({"INFO"}, f"Scaled by {f:.4f}: {src}" + (f", {moved} markers moved with it" if moved else "")
                                  + " (head must point to -Y)" + ("" if applied else " (scale could not be applied)") + rig_note)
            return {"FINISHED"}
        V, _, _ = io.meshes_to_numpy(objs)
        chk = ad.orientation_check(V, target_height=context.scene.mpr.target_height or None)
        if not chk["problems"]:
            self.report({"INFO"}, f"Orientation and scale are already fine (height {chk['height']:.2f} m)")
            return {"FINISHED"}
        if chk["rot_z_deg"] == 0.0 and chk["scale"] == 1.0 and chk.get("rot_x_deg", 0.0) == 0.0:
            self.report({"ERROR"}, "Cannot be fixed automatically: " + "; ".join(chk["problems"]))
            return {"CANCELLED"}
        lo, hi = V.min(0), V.max(0)
        rx = chk.get("rot_x_deg", 0.0)
        # bas asagi cevirmede donus merkezi yukseklik ortasi (tabandan cevirmek karakteri zeminin altina atar)
        pz = float((lo[2] + hi[2]) / 2) if rx else float(lo[2])
        pivot = Matrix.Translation((float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), pz))
        M = (pivot @ Matrix.Rotation(np.radians(chk["rot_z_deg"]), 4, "Z") @ Matrix.Rotation(np.radians(rx), 4, "X")
             @ Matrix.Scale(chk["scale"], 4) @ pivot.inverted())
        for o in objs:
            o.matrix_world = M @ o.matrix_world
        applied = True
        try:
            with context.temp_override(selected_editable_objects=objs, selected_objects=objs, active_object=objs[0], object=objs[0]):
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        except RuntimeError:
            applied = False                     # multi-user mesh: world placement is still right, only not applied
        V2, _, _ = io.meshes_to_numpy(objs)
        after = ad.orientation_check(V2, target_height=context.scene.mpr.target_height or None)
        flip = " flipped upright," if rx else ""
        msg = f"Rotated{flip} {chk['rot_z_deg']:.0f}°, scale {chk['scale']}; height {after['height']:.2f} m" + ("" if applied else " (rotation/scale could not be applied)")
        if after["problems"]:
            self.report({"WARNING"}, msg + " — remaining: " + "; ".join(after["problems"]))
        else:
            self.report({"INFO"}, msg + " — ready")
        return {"FINISHED"}


class MPR_OT_markers_mirror(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_mirror"
    bl_label = "Mirror L > R"
    bl_description = "Copy the left (L_) markers to the right (R_) side across the mirror axis"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mx = context.scene.mpr.mirror_x
        m = io.read_markers()
        out = {}
        for k, p in m.items():
            mk_ = mk.mirror_key(k)
            if k.startswith("L_") and mk_:
                out[mk_] = np.array([2 * mx - p[0], p[1], p[2]])
        io.set_markers(out, context.scene.mpr.marker_size)
        self.report({"INFO"}, f"{len(out)} markers mirrored")
        return {"FINISHED"}


class MPR_OT_fit(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.fit"
    bl_label = "Fit Skeleton"
    bl_description = "Build the GTA skeleton from the markers in the character's own pose (bone names, tags and count stay fixed)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from ..core import species as sp
        tpl = io.template()
        from ..core.fit import NO_ROTATE
        no_rotate = None
        try:
            if sp.family(tpl) == "quad":
                T = sp.expand_generic(tpl, io.read_markers(), sp.QUAD_DIRECT, sp.QUAD_REQUIRED)
                no_rotate = NO_ROTATE | sp.QUAD_TARGET_NO_ROTATE    # leğen yardimci zinciri marker gurultusunu buyutmesin
            else:
                T = mk.expand_targets(tpl, io.read_markers())
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        fit = fit_skeleton(tpl, T, no_rotate=no_rotate)
        try:
            arm, replaced = io.get_or_append_rig()
        except RuntimeError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        io.set_rest(arm, fit.P_W, tpl)
        io.store_fit(arm, fit, "P")
        io.apply_detail_visibility(context.scene.mpr, arm)    # Fingers / Face kapali: o kemikler gorunumde gizli (iskelette kalir)
        extra = f" | the previous {replaced} skeleton was replaced: compute the weights again" if replaced else ""
        self.report({"WARNING" if replaced else "INFO"}, f"Skeleton fitted: {len(T)} targets, scale {fit.g:.3f}" + extra)
        return {"FINISHED"}


class MPR_OT_weights(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.weights"
    bl_label = "Compute Weights"
    bl_description = "Weight the selected meshes by GTA rules (at most 4 bones per vertex, sum 1, 1/255 steps)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        s = context.scene.mpr
        objs = _meshes_or_fail(self, context)
        arm = bpy.data.objects.get(io.RIG_NAME)
        if not objs:
            return {"CANCELLED"}
        if arm is None or "mpr_fit" not in arm:
            self.report({"ERROR"}, "Run 'Fit Skeleton' first")
            return {"CANCELLED"}
        if io.rig_template(arm) != s.rig_type:           # once tur: rest asamasi mesaji tur degisikligini gizliyordu (t_animal_chain)
            self.report({"ERROR"}, f"MPR_Rig was fitted for {io.rig_template(arm)} but Skeleton is set to {s.rig_type}: run 'Fit Skeleton' again")
            return {"CANCELLED"}
        if arm.get("mpr_stage") != "P":
            self.report({"ERROR"}, "Weights are computed in the character's own pose, but the skeleton is in GTA rest pose. Fit the skeleton again first")
            return {"CANCELLED"}
        from ..core import species as sp
        tpl = io.template()
        fit, dev = io.current_fit(arm, tpl)             # Fit'ten sonra elle tasinan / olceklenen kemikler (tools/t_edit_after_fit.py)
        V, F, ranges = io.meshes_to_numpy(objs)
        t0 = time.time()
        msgs = []
        if sp.family(tpl) == "quad":
            try:
                W, _ = pl.animal_transfer_pipeline(V, F, tpl, fit, io.ANIMAL_DATA, log=msgs.append)
            except ValueError as e:
                self.report({"ERROR"}, str(e))
                return {"CANCELLED"}
        elif s.engine == "TRANSFER":
            W, _ = pl.transfer_pipeline(V, F, tpl, fit, s.ref_body, not s.detail_face, s.merge_roll, s.merge_mh,
                                        use_votes=s.use_votes, head_parts=s.head_parts, merge_fingers=not s.detail_fingers, log=msgs.append)
        else:
            W, _ = pl.voxel_pipeline(V, F, tpl, fit, s.merge_roll, log=msgs.append)
            if not s.detail_fingers:
                W = pl.apply_remap(W, tpl, pl.remap_rules(tpl.names, merge_face=not s.detail_face, merge_fingers=True))
        idx, val = pl.finalize(W, tpl)
        raw = io.bone_raw_names(arm, tpl)
        io.write_weights(ranges, raw, idx, val)
        io.bind(ranges, arm)
        used = len(np.unique(idx[val > 0]))
        store_fit_baseline(arm, tpl, objs)       # sonra rig / mesh ayri olceklenirse Validate / GTA rest / Export yakalar
        from ..core.fit import REFIT_TOL
        changed = (f" | the skeleton changed after Fit Skeleton (up to {dev * 100:.1f} cm: moved bones or scale): the current bones were used"
                   if dev >= REFIT_TOL else "")
        self.report({"INFO"}, f"Weights: {len(V)} vertices, {used} bones, {time.time()-t0:.1f}s" + changed)
        for m in msgs:
            print("[muto_ped_rig]", m)
        return {"FINISHED"}


class MPR_OT_to_gta_rest(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.to_gta_rest"
    bl_label = "Convert to GTA Rest Pose"
    bl_description = ("Move the mesh and skeleton into the GTA rest pose with vanilla bone rotations (required for T-pose "
                      "characters: otherwise limbs drift in game by the rest pose difference)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        arm = bpy.data.objects.get(io.RIG_NAME)
        if not objs or arm is None or "mpr_fit" not in arm:
            self.report({"ERROR"}, "Skeleton and weights are required")
            return {"CANCELLED"}
        if arm.get("mpr_stage") != "P":
            self.report({"WARNING"}, "Already in GTA rest pose")
            return {"CANCELLED"}
        sk = [o.name for o in objs if o.data.shape_keys is not None]
        if sk:
            # with shape keys, writing vertices.co does not reach the evaluated mesh — the GTA rest pose would silently do nothing
            # (tools/t_strip_rig.py, Blender 5.2.1: written offset 1.0, evaluated 0.0)
            self.report({"ERROR"}, f"Shape keys found ({', '.join(sk[:3])}): the GTA rest pose cannot be applied — run 'Remove Existing Rig' first")
            return {"CANCELLED"}
        tpl = io.template()
        misfit = rig_mesh_ratio_problem(arm, tpl, objs)
        if misfit is not None:
            # Weights'ten sonra yalniz mesh / yalniz rig olceklenmis: bu adim sonunda taban yenilendigi icin export artik yakalayamazdi
            self.report({"ERROR"}, misfit[0].upper() + misfit[1:])
            return {"CANCELLED"}
        fit, dev = io.current_fit(arm, tpl)             # kayitli fit elle tasinan dirsegi eski boya donduruyordu (tools/t_edit_after_fit.py)
        V, F, ranges = io.meshes_to_numpy(objs)
        raw = io.bone_raw_names(arm, tpl)
        idx, val = io.read_weights(ranges, raw)
        empty = int((val.sum(1) == 0).sum())
        if empty:
            self.report({"ERROR"}, f"{empty} vertices have no weights; compute weights first")
            return {"CANCELLED"}
        Vg = lbs(V, idx, val, fit.repose_matrices())
        # zemin koku: klipler SKEL_ROOT'u ped boyundan bagimsiz ayni yukseklige koyar -> taban - kok mesafesi sablonunkiyle ayni olmali,
        # yoksa oyunda ayak havada / gomulu, bacak IK'si dizleri buker (core/fit.ground_root; tools/t_ground_contact.py)
        from ..core.fit import ground_root
        root_z = float(tpl.pos[tpl.index["SKEL_ROOT"]][2])
        if context.scene.mpr.rig_type == "mp_m":
            root_above = root_z - float(io.VANILLA_LO[2])
        else:
            root_above = root_z - float(io.animal_ref_bbox(context.scene.mpr.rig_type)[0][2])
        G_W, root_dz = ground_root(fit.G_W, tpl, float(Vg[:, 2].min()), root_above)
        for o, a, b in ranges:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.show_viewport = False
        io.set_world_verts(ranges, Vg)
        io.set_rest(arm, G_W, tpl)
        arm["mpr_stage"] = "G"
        for o, a, b in ranges:
            for m in o.modifiers:
                if m.type == "ARMATURE":
                    m.show_viewport = True
        # GTA rest iskeleti de mesh'i de degistirir: Weights anindaki taban burada kiyaslanamaz -> yenilenir (olculdu 2026-09-13, cakal bas
        # asagi / kuyruk yukari duruslu model, dogru marker'lar: oran 0,77 -> 0,88, export yanlis "ayri olceklendi" ile durdu;
        # tools/t_animal_auto_chain.py pose=1). Weights ile bu adim arasindaki ayri olcek basta yakalanir.
        store_fit_baseline(arm, tpl, objs)
        moved = np.linalg.norm(Vg - V, axis=1)
        from ..core.fit import REFIT_TOL
        changed = (f" | the skeleton changed after Fit Skeleton (up to {dev * 100:.1f} cm: moved bones or scale): the current bones were used"
                   if dev >= REFIT_TOL else "")
        self.report({"INFO"}, f"GTA rest pose: mesh moved at most {moved.max()*100:.1f} cm | root set {root_above:.3f} m above the feet "
                              f"(moved {root_dz*100:+.1f} cm so game animations keep the feet on the ground)" + changed)
        return {"FINISHED"}


class MPR_OT_validate(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.validate"
    bl_label = "Validate"
    bl_description = ("Check the skeleton signature (names, tags, parents, count), the GTA weight rules and the "
                      "wind/sweat vertex color layer")
    bl_options = {"REGISTER"}

    def execute(self, context):
        arm = bpy.data.objects.get(io.RIG_NAME)
        if arm is None:
            self.report({"ERROR"}, "MPR_Rig not found")
            return {"CANCELLED"}
        tpl = io.template()
        problems, notes = [], []
        bones = {b.name: b for b in arm.data.bones}
        if len(bones) != len(tpl.names):
            problems.append(f"bone count {len(bones)} != {len(tpl.names)}")
        from ..core.skeleton import canon
        by = {canon(n): b for n, b in bones.items()}
        for i, n in enumerate(tpl.names):
            b = by.get(n)
            if b is None:
                problems.append(f"missing bone {n}")
                continue
            if b.bone_properties.tag != tpl.tags[i]:
                problems.append(f"tag {n}: {b.bone_properties.tag} != {tpl.tags[i]}")
            p = tpl.parents[i]
            if (canon(b.parent.name) if b.parent else None) != (tpl.names[p] if p >= 0 else None):
                problems.append(f"parent {n}")
        objs = io.selected_meshes(context)
        if objs:
            raw = io.bone_raw_names(arm, tpl)
            _, _, ranges = io.meshes_to_numpy(objs)
            for o, a, b in ranges:
                over, empty = 0, 0
                gset = {g.index for g in o.vertex_groups if g.name in set(raw)}
                for v in o.data.vertices:
                    n = sum(1 for g in v.groups if g.group in gset and g.weight > 0)
                    over += n > 4
                    empty += n == 0
                if over:
                    problems.append(f"{o.name}: {over} vertices with more than 4 bones")
                if empty:
                    problems.append(f"{o.name}: {empty} vertices without weights")
                # Sollumz 2.9 (ydr/vertex_buffer_builder.try_get_bone_by_vgroup): iskelette adi olmayan grup ROOT kemigine yazilir, yalniz konsol
                # logu -> o vertexler animasyonda yerinde kalir; "CLOTH" (cloth_char.CLOTH_CHAR_VERTEX_GROUP_NAME) grubundaki vertexler deriden
                # cikip cloth'a baglanir (Sollumz #1206 kullanicisi 48 saat aradi). Kod okundu 2026-09-14.
                unknown = [g.name for g in o.vertex_groups if g.name not in set(raw) and g.name != "CLOTH"]
                if unknown:
                    problems.append(f"{o.name}: {len(unknown)} vertex groups are not GTA bones ({', '.join(unknown[:3])}"
                                    f"{'...' if len(unknown) > 3 else ''}) — Sollumz ties their weights to SKEL_ROOT and those parts will not "
                                    "follow animations (run 'Remove Existing Rig' or delete the groups)")
                if any(g.name == "CLOTH" for g in o.vertex_groups):
                    problems.append(f"{o.name}: has a 'CLOTH' vertex group — Sollumz binds those vertices to cloth simulation instead of "
                                    "the skeleton (delete the group unless this part is cloth)")
                if len(o.data.uv_layers) == 0:
                    notes.append(f"{o.name}: no UV map — textures will look flat and the .ydd grows (every triangle corner becomes a vertex)")
            from .sollumz_setup import wind_layer_report, wind_layer_uniform
            for o in objs:
                wind = wind_layer_report(o.data)
                if wind and wind_layer_uniform(o.data):
                    # one flat value = unpainted default (Sollumz 'Create Shader Material' adds it white); export resets it (2026-09-13)
                    notes.append(f"{o.name}: 'Color 2' is one flat value (e.g. added by Sollumz with a ped shader) — export resets it to 0")
                elif wind and context.scene.mpr.rig_type != "mp_m":
                    # vanilla dort ayaklilarda Color 2 koselerin %36-100'unde sifir degil (coyote / deer / boar, t_animal_chain 2026-09-13)
                    notes.append(f"{o.name}: 'Color 2' is non-zero on {wind * 100:.0f}% of corners (game animals use it too)")
                elif wind:
                    # painted "Color 2" is kept by the export; non-zero means wind/sweat in game -> jitter (measured 2026-09-12)
                    problems.append(f"{o.name}: 'Color 2' is non-zero on {wind * 100:.0f}% of corners (wind/sweat) -> jitter in game")
        if context.scene.mpr.rig_type != "mp_m" and "mpr_fit" in arm:
            # hayvan klipleri bacak zincirine KONUM yazar (vanilla ped kemik boyu): boy / bacak orani ped'den saparsa animasyonda mesh
            # gerilir (cakal 0,45 / 1,2 m, Sollumz en kotu kare kotu kenar %17,2 / 10,7, kendi boyunda %12,0)
            fit = io.load_fit(arm, tpl)
            tL = tpl.local_t()
            ratios = [float(np.linalg.norm(fit.t_local[tpl.index[f"SKEL_{s}_{c}"]]) / max(np.linalg.norm(tL[tpl.index[f"SKEL_{s}_{c}"]]), 1e-9))
                      for s in ("L", "R") for c in ("Calf", "Foot", "Forearm", "Hand", "Finger00") if f"SKEL_{s}_{c}" in tpl.index]
            if ratios and (abs(fit.g - 1) > 0.05 or max(abs(r - 1) for r in ratios) > 0.05):
                notes.append(f"size x{fit.g:.2f} of {context.scene.mpr.rig_type}, leg bones x{min(ratios):.2f}-x{max(ratios):.2f}: game "
                             "animal animations move leg joints to the ped's own bone lengths, so the mesh stretches — scale the model "
                             "to the ped's size ('Scale to Height' with Height 0)")
        misfit = rig_mesh_fit_problem(arm, tpl, objs)
        if misfit is not None:
            problems.append(misfit)
        root_dz = rig_root_offset(context, arm, tpl, objs)
        if root_dz is not None and abs(root_dz) > 0.01:
            # iki sebep olculdu: ground-root duzeltmesinden once cevrilmis .blend (-10,1 cm) ve GTA rest'ten sonra rig + mesh olcegi (x1,5: -49,2 cm)
            problems.append(f"SKEL_ROOT is {root_dz * 100:+.1f} cm off the feet distance (the character was scaled after 'Convert to GTA Rest "
                            "Pose', or converted before the ground-root fix): feet float or sink in game animations — Export to Sollumz "
                            "corrects it automatically")
        if arm.get("mpr_stage") == "G" and context.scene.mpr.rig_type == "mp_m":
            # Arac / koltuk klipleri (veh@std@ds@base 35 klip, veh@std@ps@base 11 klip; oyundan extract_asset + res_to_xml, 2026-09-14) konum
            # izi yalniz SKEL_ROOT + IK / PH el-ayak -> legen koke gore iskelet ofsetinde kalir. Vanilla'da legen = kok (ikisi z -0,019);
            # zemin koku duzeltmesinden sonra ozel boyda legen - kok (export .yft XML): 1,4 m -16,7 cm, 1,86 m +10,1, x0,6 -33,3, x1,5 +64,3 ->
            # oturunca kalca o kadar gomulur / havada kalir; ayakta klipler etkilenmez. OYUNDA DENENMEDI.
            Wr = io.rig_world_matrices(arm, tpl)
            ip, ir = tpl.index["SKEL_Pelvis"], tpl.index["SKEL_ROOT"]
            dp = float(Wr[ip, 2, 3] - Wr[ir, 2, 3]) - float(tpl.pos[ip][2] - tpl.pos[ir][2])
            if abs(dp) > 0.03:
                notes.append(f"hips are {abs(dp) * 100:.0f} cm {'above' if dp > 0 else 'below'} SKEL_ROOT (vanilla peds: level) — vehicle and "
                             f"seat animations place the root, so the hips {'float' if dp > 0 else 'sink'} by about that much when sitting; "
                             "standing animations are not affected")
        tail = "".join(f" | {n}" for n in notes)
        for n in notes:
            print("[muto_ped_rig] NOTE:", n)
        if problems:
            for p in problems[:20]:
                print("[muto_ped_rig] PROBLEM:", p)
            self.report({"WARNING"}, f"{len(problems)} problems (first: {problems[0]})" + tail)
        else:
            self.report({"INFO"}, "Clean: signature matches, weight rules OK" + tail)
        return {"FINISHED"}


class MPR_OT_sollumz_export(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.sollumz_export"
    bl_label = "Export to Sollumz + Test Resource"
    bl_description = ("Split the character into head/uppr/lowr drawables, assign ped materials, write a physics-free .yft + .ydd "
                      "and create a resource folder to test in game (/mprped). Disconnect from the server and reconnect")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        from . import sollumz_setup as sz
        import os
        s = context.scene.mpr
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        animal = s.rig_type != "mp_m"
        import re
        name = s.ped_name.strip().lower()
        if animal and (s.export_mode != "REPLACE" or name != s.rig_type):
            # hayvan: yalniz vanilla hayvan ped'ini degistirme (oyunun peds.meta / .ymt / klip seti kalir; iskelet o ped'in kendisi).
            # Addon hayvan ped'inin peds.meta girdisi dogrulanmadi (atlas yaratik-rig §11.8B). Tum geometri head_000_r; oyunda denenmedi.
            self.report({"ERROR"}, f"Animal export: set Output Type to 'Replace Vanilla Ped' and Ped Name to {s.rig_type} (the skeleton's own ped)")
            return {"CANCELLED"}
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", name):
            self.report({"ERROR"}, "Ped name must be 3-32 characters: lowercase letters, digits, underscore (starting with a letter)")
            return {"CANCELLED"}
        vanilla_like = re.match(r"(a_[mfc]_|s_[mf]_|u_[mf]_|g_[mf]_|mp_[mfg]_|csb_|cs_|ig_|hc_|player_)", name)
        if s.export_mode == "ADDON" and vanilla_like:
            self.report({"ERROR"}, f"Add-on ped name looks like a vanilla ped name ({name}); avoid a clash, e.g. muto_character_01")
            return {"CANCELLED"}
        if s.export_mode == "REPLACE" and not vanilla_like:
            # replace mode writes no peds.meta: a non-vanilla name is never registered -> in game "[mprped] <name> not found"
            # (measured 2026-09-12, mpr_robot)
            self.report({"ERROR"}, f"'{name}' is not a vanilla ped name, but Output Type is 'Replace Vanilla Ped' (e.g. a_m_y_beach_01). "
                                   "For a new model choose 'Add-on Ped (New Model)'")
            return {"CANCELLED"}
        arm = bpy.data.objects.get(io.RIG_NAME)
        misfit = rig_mesh_fit_problem(arm, io.template(), objs)
        if misfit is not None:
            # yalniz mesh x0,6 olceklenince dosyada bas kemigi mesh tepesinin 54 cm ustundeydi, export "FINISHED" dedi (2026-09-13)
            self.report({"ERROR"}, misfit[0].upper() + misfit[1:])
            return {"CANCELLED"}
        # zemin koku: duzeltmeden once G'ye cevrilmis .blend eski koku tasir -> export oncesi otomatik (tools/t_root_export_check.py)
        root_fix = rig_root_offset(context, arm, io.template(), objs, apply=True)
        out = bpy.path.abspath(s.export_dir)
        tex_dir = os.path.join(out, "_textures")
        use_ytd = s.tex_mode == "YTD"
        try:
            frag, dic, counts = sz.build_hierarchy(name, objs, tex_dir=None if use_ytd else tex_dir)
            tex_rep = sz.apply_ped_textures(dic, name, tex_dir) if use_ytd else {}
            # dokulardan SONRA: LOD mesh'leri son materyali tasir; hayvan tek cizim -> vanilla hayvan butcesi (sollumz_setup notu)
            lod_rep = (sz.add_lods(dic, sz.LOD_TARGET_TRIS_ANIMAL if animal else sz.LOD_TARGET_TRIS)
                       if s.export_lods else {})
        except (RuntimeError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        stream = os.path.join(out, "_sollumz")
        res = sz.export(frag, dic, stream, "NATIVE", ytd_name=name if use_ytd else None)
        files = [os.path.join(stream, f"{name}.{ext}") for ext in (("yft", "ydd", "ytd") if use_ytd else ("yft", "ydd"))]
        missing = [f for f in files if not os.path.exists(f) or os.path.getsize(f) == 0]
        if "FINISHED" not in res or missing:
            self.report({"ERROR"}, f"Sollumz export incomplete: {missing or res}")
            return {"CANCELLED"}
        rdir = sz.write_test_resource(out, f"mpr_{name}", name, files, s.export_mode, ymt=not animal)
        addon = s.export_mode == "ADDON"
        extra = " + peds.meta (add-on ped)" if addon else ""
        # boyut gorunur olsun: vanilla ambient .ydd 0,33-0,86 MB, a_m_y_hipster_01 .ytd 3,27 MB; FiveM "oversized asset" uyarisi 4096 DXT5'te
        # 64 MiB fiziksel bellek (atlas mlo-prop §2), TEX_MAX 2048 bunu ~16 MiB'e indirir (2026-09-14 olcumu)
        sizes = ", ".join(f".{os.path.splitext(f)[1][1:]} {os.path.getsize(f) / 1048576:.2f} MB" for f in files)
        msg = (f"Written: {rdir}{extra} (faces per drawable: {counts}; {sizes}). Copy it to the server, reconnect, "
               f"then run {'/' + name if addon else '/mprped'}")
        if root_fix is not None and abs(root_fix) > 1e-4:
            msg += f" | skeleton root corrected by {root_fix * 100:+.1f} cm (feet stay on the ground in game animations)"
        if lod_rep:
            n_med = sum(1 for v in lod_rep.values() if "medium" in v)
            n_low = sum(1 for v in lod_rep.values() if "low" in v)
            msg += f" | LODs: medium {n_med}, low {n_low} of {len(lod_rep)} models"
        notes = []
        atl = [f"{k.split('_')[0]} {len([t for t in v['atlas'] if not t.startswith('__')])} textures" for k, v in tex_rep.items() if v.get("atlas")]
        if atl:
            msg += " | texture atlas: " + ", ".join(atl)
        multi = [k for k, v in tex_rep.items() if v["multi"] and not v.get("atlas")]
        if multi:
            notes.append(f"several color textures: {', '.join(multi)} — only the largest was used")
        lost = sorted({n for v in tex_rep.values() for n in v["missing"]})
        if lost:
            notes.append(f"textures not found on disk: {', '.join(lost[:4])}{' ...' if len(lost) > 4 else ''}")
        reset = sorted({re.sub(r"\.(head|uppr|lowr)$", "", o.name) for o in dic.children_recursive
                        if o.type == "MESH" and o.data.get("mpr_wind_reset")})
        if reset:
            msg += (f" | 'Color 2' reset to 0 on {', '.join(reset[:4])}{' ...' if len(reset) > 4 else ''} "
                    "(it was one flat value, e.g. added by Sollumz; wind/sweat off, no jitter)")
        no_uv = sorted({re.sub(r"\.(head|uppr|lowr)$", "", o.name) for o in dic.children_recursive if o.get("mpr_no_uv")})
        if no_uv:
            notes.append(f"no UVs: {', '.join(no_uv[:4])}{' ...' if len(no_uv) > 4 else ''} — the texture shows as one color and the file grows ~4x; unwrap UVs first")
        if notes:
            self.report({"WARNING"}, msg + " | " + " | ".join(notes))
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


class MPR_OT_strip_rig(_MeshOperator, bpy.types.Operator):
    bl_idname = "mpr.strip_rig"
    bl_label = "Remove Existing Rig"
    bl_description = ("Remove the previous rig (Mixamo/Unreal/Sketchfab) from the selected meshes: parent (world transform kept), "
                      "armature modifier, vertex groups, shape keys; delete the old armature if nothing uses it anymore. "
                      "Facial shape keys are lost (undo with Ctrl+Z)")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objs = _meshes_or_fail(self, context)
        if not objs:
            return {"CANCELLED"}
        c = io.strip_foreign_rig(objs)
        self.report({"INFO"}, f"{len(objs)} meshes: parent {c['parent']}, armature modifier {c['modifier']}, vertex groups {c['grup']}, "
                              f"shape keys {c['shape_key']} | old armatures deleted {c['iskelet_silindi']}")
        return {"FINISHED"}


class MPR_OT_markers_update_linked(_ObjectModeOperator, bpy.types.Operator):
    bl_idname = "mpr.markers_update_linked"
    bl_label = "Update Linked"
    bl_description = ("After dragging a shoulder/wrist or hip/ankle marker, move the elbow/knee with it so it keeps its place along the limb. "
                      "Markers you moved yourself stay; fingers, head and toes are not moved")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        context.view_layer.update()             # suruklemeden hemen sonra (betikte) matrix_world guncel olmayabilir
        cur = io.read_markers()
        if not cur:
            self.report({"ERROR"}, "No markers: run 'Auto Markers' or 'Add Markers' first")
            return {"CANCELLED"}
        ref = io.read_marker_refs()
        new = mk.propagate_linked({k: ref.get(k, p) for k, p in cur.items()}, cur)
        io.commit_markers(new, cur)
        from ..core import species as sp
        label = sp.label if context.scene.mpr.rig_type != "mp_m" else mk.label      # panel ipucuyla ayni etiketler
        if new:
            self.report({"INFO"}, "Moved with the limb: " + ", ".join(label(k) for k in sorted(new)))
        else:
            self.report({"INFO"}, "Nothing to update (no shoulder, wrist, hip or ankle marker was dragged)")
        return {"FINISHED"}


def batch_plan(s, blend_path):
    """-> (isler [{src, ped, out}], cikti klasoru) ya da ValueError. Panel ayari s (Scene.mpr); bpy.path.abspath kaydedilmemis dosyada '//' birakir."""
    import os
    from ..core import batch as bt
    src = bpy.path.abspath(s.batch_src) if s.batch_src else ""
    models = bt.collect_models(src)
    if not models:
        raise ValueError(f"No .glb / .gltf / .fbx / .obj files in '{src or 'the models folder'}'")
    if s.batch_out.startswith("//") and not blend_path:
        raise ValueError("Save the .blend first or choose an absolute Batch Output folder")
    out = os.path.abspath(bpy.path.abspath(s.batch_out))
    taken = set()
    jobs = []
    for m in models:
        name = bt.ped_name(s.batch_prefix, m, taken)
        jobs.append(dict(src=m, ped=name, out=os.path.join(out, name)))
    return jobs, out


def batch_worker_cmd(job, height, tex, rig="mp_m"):
    import os
    worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "batch_worker.py")
    return [bpy.app.binary_path, "-b", "--python", worker, "--", f"src={job['src']}", f"out={job['out']}", f"ped={job['ped']}",
            f"height={height:.4f}", "mode=ADDON", f"tex={tex}", f"rig={rig}"]


class MPR_OT_batch_run(bpy.types.Operator):
    bl_idname = "mpr.batch_run"
    bl_label = "Rig Folder"
    bl_description = ("Rig every model in the folder in background Blender processes: import, remove old rig, orientation/scale, "
                      "Auto Markers, fit, weights, GTA rest pose, validate and export (humanoid: add-on ped; animal: replaces the chosen "
                      "game animal). Your scene is not touched; each model gets a report and a rigged .blend to fix by hand if a step "
                      "fails. Esc cancels")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        s = context.scene.mpr
        try:
            self._jobs, self._out = batch_plan(s, bpy.data.filepath)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        import os
        os.makedirs(self._out, exist_ok=True)
        self._queue, self._running = list(self._jobs), []
        self._height, self._tex, self._workers = s.target_height, s.tex_mode, s.batch_workers
        self._rig = s.rig_type                          # kuyruk basinda sabit: panelde tur degisse de ayni iskelet (hayvan: Replace export)
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        s.batch_status = f"0/{len(self._jobs)} done"
        self.report({"INFO"}, f"Batch started: {len(self._jobs)} models -> {self._out}")
        return {"RUNNING_MODAL"}

    def _launch(self, job):
        import os
        import subprocess
        os.makedirs(job["out"], exist_ok=True)
        job["log"] = open(os.path.join(job["out"], "worker_log.txt"), "w", encoding="utf-8", errors="replace")
        job["proc"] = subprocess.Popen(batch_worker_cmd(job, self._height, self._tex, self._rig), stdout=job["log"],
                                       stderr=subprocess.STDOUT)
        self._running.append(job)

    def modal(self, context, event):
        s = context.scene.mpr
        if event.type == "ESC":
            for j in self._running:
                j["proc"].terminate()
                j["log"].close()
            self._running = []
            self._finish(context, cancelled=True)
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        for j in list(self._running):
            if j["proc"].poll() is not None:
                j["log"].close()
                self._running.remove(j)
        while self._queue and len(self._running) < self._workers:
            self._launch(self._queue.pop(0))
        done = len(self._jobs) - len(self._queue) - len(self._running)
        s.batch_status = f"{done}/{len(self._jobs)} done, {len(self._running)} running"
        for area in (context.screen.areas if context.screen else ()):
            if area.type == "VIEW_3D":
                area.tag_redraw()
        if not self._queue and not self._running:
            self._finish(context)
            return {"FINISHED"}
        return {"PASS_THROUGH"}

    def _finish(self, context, cancelled=False):
        import json
        import os
        from ..core import batch as bt
        context.window_manager.event_timer_remove(self._timer)
        started = [j for j in self._jobs if "proc" in j]
        rows, cnt = bt.summarize([j["out"] for j in started])
        with open(os.path.join(self._out, "batch_summary.json"), "w", encoding="utf-8") as fh:
            json.dump(dict(counts=cnt, cancelled=cancelled, not_started=[j["ped"] for j in self._jobs if "proc" not in j], rows=rows),
                      fh, indent=1, ensure_ascii=False)
        failed = [r.get("ped", "?") for r in rows if not r.get("ok")]
        # tamamlanmis ama isci uyarisi olan (hayvan Auto Markers gevsek oturma: export sessizce bozuk marker'la biter; t_animal_auto_residual)
        warned = [r.get("ped", "?") for r in rows if r.get("ok") and r.get("warnings")]
        msg = f"Batch {'cancelled' if cancelled else 'finished'}: {cnt['ok']}/{len(self._jobs)} rigged and exported"
        if failed:
            msg += f" | failed (open <ped>.blend, fix markers): {', '.join(failed[:4])}{' ...' if len(failed) > 4 else ''}"
        if warned:
            msg += f" | check the markers (loose Auto Markers fit): {', '.join(warned[:4])}{' ...' if len(warned) > 4 else ''}"
        context.scene.mpr.batch_status = msg
        self.report({"WARNING" if failed or cancelled or warned else "INFO"}, msg + f" | {self._out}")


classes = (MPR_OT_markers_add, MPR_OT_markers_click, MPR_OT_markers_from_rig, MPR_OT_markers_auto, MPR_OT_fix_orientation, MPR_OT_markers_mirror, MPR_OT_markers_update_linked,
           MPR_OT_fit, MPR_OT_weights, MPR_OT_to_gta_rest, MPR_OT_validate, MPR_OT_sollumz_export, MPR_OT_strip_rig, MPR_OT_batch_run)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
