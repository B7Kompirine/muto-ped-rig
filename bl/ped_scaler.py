# -*- coding: utf-8 -*-
"""Muto Ped Scaler — Muto Ped Rig icinde (eski ayri muto_ped_scaler.py 4.3.0 buraya tasindi; mairon 4.1 formulu varsayilan) — GTA ped olcekleyici (insan + hayvan).

KAPSAM
    SADECE model dosyalarina dokunur: .yft.xml ve .ydd.xml.
    Hicbir meta/ymt yazmaz, hicbir resource'a dokunmaz.

TUR TANIMA
    GTA'nin kendi pedlerinden cikarilmis iskelet tablosuyla (SKELETONS)
    dosyadaki kemik uzunluklari kiyaslanir. Hangi turde oranlar en tutarli
    cikiyorsa tur odur, oranlarin medyani da mevcut olcektir. Tek islemde
    hem "bu hangi hayvan" hem "kac kat buyutulmus" cevabi gelir.

    Olculen ayirt etme: a_c_rottweiler -> yayilim 0.00000, ikinci aday
    (a_c_chop) 0.02572. Insan pedi -> u_m_y_abner 0.00000, en yakin hayvan
    (a_c_chimp) 1.39. Ayrim rahat.

NEDEN TUM DOSYALAR BIRDEN OLCEKLENIR
    Skinning:  v = R*v_mesh + s*(p_anim - R*p_bind)
    Sadece iskelet olceklenirse eklemler acilir, uzuv kalinligi ayni kalir.
    Sadece mesh olceklenirse mesh kemikleri takip edemez. Iskelet ve TUM
    mesh bilesenleri ayni oranla olceklenmeli. Hayvanlarda mesh parcali
    (head/uppr/lowr/accs), o yuzden arac klasordeki tum .ydd.xml'leri
    birlikte isler.

ZEMIN
    Oyunda:  taban_yuksekligi = taban_model - z_root + z_root_anim
    z_root_anim animasyondan gelir ve SABITTIR -- modelin olcegiyle
    degismez. Duz olceklenmis pedde bacak zinciri uzadigi icin ayaklar
    yerin altina duser; ayak IK'si dizleri bukerek onlari yukari ceker
    ("merdiven cikar gibi" gorunum). Kuculmede tam tersi, ped havada kalir.

    COZUM (ZModeler tutorial'inin yaptigi, velxor'da olculen imza):
        SKEL_ROOT'un dogrudan cocuklari ve mesh, AYNI miktar kadar
        dikeyde kaydirilir:   d = H0 * (olcek - 1)

            B'(b) = T(d)*B(b),  W_anim'(b) = T(d)*W_anim(b),  v' = v + d
            =>  W_anim' * B'^-1 * v'  =  T(d) * (W_anim * B^-1 * v)

        yani ped RIJIT olarak d kadar yukselir: yirtilma yok (bind ile mesh
        birlikte gidiyor), kemikler gercekten hareket ettigi icin IK de
        dogru yeri gorur, dizler bukulmez.

        Dogrulama -- velxor (1.070, oyunda calisiyor):
            SKEL_Pelvis / SKEL_Spine_Root / IK_Root  hepsi z=0.0726731
            ayni ped 1.0'da ucu de z=0

    SKEL_ROOT'un KENDI translation'ina dokunmak ise ise yaramaz: canli
    degeri animasyondan gelir, dosyadaki deger sadece ters-bind'e girer ve
    her kemigin donusuyle carpilir -> mesh yirtilir.

H0 NEREDEN GELIYOR
    Sabit degil, dosyadan olculur:   H0 = (z_root - taban + kaldirma) / olcek
    Insan pedinde 0.98154, a_c_rottweiler'de 0.43945 cikiyor. Boylece tur
    ne olursa olsun dogru kaldirma bulunur.

HAYVANLARDA BILINEN RISK
    Kopekte SKEL_Spine_Root / SKEL_PelvisRoot flags'inde TransX/Y/Z var
    (insanin SKEL_Pelvis'inde yok). Hayvan animasyonlari bu kemiklerin
    translation'ini yaziyorsa dosyadaki deger calisma aninda ezilir ve
    kaldirma sadece bind tarafina girer -> mesh yirtilir. Oyunda
    denenmeden bilinemez; yirtilma gorursen Zemine oturt'u 0'a cek.

MUTLAK HESAP
    SKEL_ROOT hep duz carpilir, hic kaydirilmaz. Bu sayede pedin 1.0'daki
    dogal kok Z'si her zaman geri hesaplanabilir; kaldirma ve mesh konumu
    da mutlak yazilir. Dosyanin gecmisi onemsiz, ust uste uygulamak
    birikme yapmaz, bozuk dosya kendiliginden duzelir.

DOKUNULMAYANLAR
    Rotation, kemik Scale, TransformUnk, normal, tangent, UV, vertex
    renkleri, blend weight/index, IndexBuffer, shader parametreleri.

MUTO SURUMU 4.2.0 (2026-09-13) — muto-ped-rig olcumleriyle duzeltmeler
    1) .yft <BoneTransforms>: vanilla ped'lerde (mp_m_freemode_01, a_c_coyote) unk="0" ve SIFIR, player_zero'da hic yok;
       Sollumz ciktilarinda unk="1" ve her kemigin MODEL uzayi matrisi (3 satir: donus satiri + oteleme). 4.1 bunlari olceklemiyor /
       kaldirmiyordu -> olcekten sonra iskelet yeni boyda, bu matrisler eski boyda kaliyordu. Artik DOLUYSA son iskeletten yeniden
       hesaplanir (rebuild_bone_transforms); sifirsa dokunulmaz.
    2) Hayvan fizigi (.yft Physics/LOD1): kapsul CompositeTransform'u MODEL uzayinda, satir-vektor (oteleme son satirda). 4.1 yaricap ve
       kutuyu olcekliyor ama kapsul KONUMUNU tasimiyordu. Artik kapsulun kemigine gore yerel ofseti olcekle buyutulup yeni kemik yerine
       tasinir, eklem capalari (Joints Unknown50 / Unknown90) olceklenir (move_physics); BoxCenter / SphereCenter olceklenir. Kutle ve
       inertia degismez. OYUNDA DENENMEDI.
    3) Hayvan uyarisi: hayvan klipleri SKEL_ROOT, Spine_Root, Spine0, PelvisRoot, Pelvis, Thigh, UpperArm, Forearm, Hand, Finger00,
       Tail_01'e KONUM yazar (3 klip sozlugu, 2026-09-13): kok cocuklarinin kaldirmasi oyunda ezilir, bacaklar vanilla boya zorlanir.
       Tespit ve uygulama raporu bunu soyler.
    4) Insan ailesinde ozel oranli iskelet reddedilmez (muto-ped-rig ciktilari yayilim 0,16-0,55): insan RIGS kaydi turden bagimsiz
       ayni (kok 180 derece Z, cocuklar 0) -> kaldirma dogru; olcek = kemik orani medyani, rapor bunu yazar. Hayvanda sinir aynen.
    5) Adlar: Scene.muto_ped_scale, operatorler muto_pedscale.*, panel sekmesi "Muto Rig" (ayni anda 4.1 ile cakismaz).
    6) Zemin (ozel oranli iskelet): 4.1 kaldirma = H0*(hedef-1); H0 dosyadan legen-taban / kemik orani medyani oldugu icin iskelet vanilla
       oranli degilse sapar: muto-ped-rig hipster 1,4 m (yayilim 0,16 -> 4.1 de kabul) hedef 1,0'da kok - taban 0,983 yerine 1,101, oyun
       kliplerinde ~12 cm gomulu. Degismez: olcekten sonra kok - taban = turun vanilla H0'i -> kaldirma = H0*hedef - H0_ref (vanilla
       oranli dosyada H0_ref = H0, sonuc 4.1 ile birebir; ozel oranli insanda INSAN_H0 = 0,983).
    7) Onizleme: 4.1 Sollumz'u modul adiyla ariyordu; eski usul kurulumda modul 'Sollumz' (buyuk harf) -> "Sollumz gerekli", onizleme hic
       calismiyordu. Artik bpy.ops.sollumz.import_assets kayitli mi diye bakilir.
    8) Onizleme uyarisi: CodeWalker cizim adini cozemeyince sozlukteki cizimler ayni adli ('<ped>.#dd'); Sollumz import'u bunlari
       birlestirir, yalniz sonuncusu gorunur (a_m_y_hipster_01: 11 cizim -> 1 mesh). Onizleme bunu soyler; olcek dosyada hepsine uygulanir.

MUTO SURUMU 4.3.0 (2026-09-18) — VARSAYILAN MAIRON 4.1 ZEMINI
    Kullanici karari: mairon'un oyunda denenmis formulu varsayilan (arkadasi gelistirip kullandi). "Muto zemin duzeltmesi"
    (muto_ground) KAPALIYKEN: yayilim > 0,25 insan iskeleti 4.1 gibi reddedilir, kaldirma = H0*(hedef-1) (4.1 birebir). ACIKKEN 4.2
    davranisi (madde 4 ve 6: ozel oranli insan kabul, zemin vanilla H0 ile; Sollumz'da gomulme 12-13 -> 1-2 cm, OYUNDA DENENMEDI).
    Madde 1-3, 5, 7-8 (BoneTransforms, hayvan fizigi, uyarilar, adlar, onizleme) iki durumda da acik.
"""


import bpy
import os
import re
import sys
import json
import shutil
import tempfile
import statistics
import xml.etree.ElementTree as ET
from mathutils import Vector, Quaternion
from bpy.props import BoolProperty, StringProperty, FloatProperty
from bpy.types import Operator, Panel, PropertyGroup


# GTA'dan cikarilmis iskelet tablosu: tur -> {kemik: lokal X uzunlugu}.
# Kaynak: common/x64e.rpf icindeki stok pedler (CodeWalker ile okundu).
SKELETONS = {
    "a_c_boar": {"FB_Brow_Centre_000":-0.005668, "FB_Jaw_000":0.156824, "FB_L_Brow_Out_000":-0.04922, "FB_L_CheekBone_000":0.519809, "FB_L_Ear_000":-0.075751, "FB_L_Eye_000":0.152303, "FB_L_Lid_Upper_000":0.147538, "FB_L_Lip_Bot_000":-0.183632, "FB_L_Lip_Corner_000":0.116858, "FB_L_Lip_Top_000":-0.004372, "FB_LowerLipRoot_000":0.093074, "FB_LowerLip_000":0.247626, "FB_R_Brow_Out_000":-0.049229, "FB_R_CheekBone_000":0.519815, "FB_R_Ear_000":-0.075708, "FB_R_Eye_000":0.152344, "FB_R_Lid_Upper_000":0.147575, "FB_R_Lip_Bot_000":-0.183633, "FB_R_Lip_Corner_000":0.116878, "FB_R_Lip_Top_000":-0.004372, "FB_TongueA_000":0.257221, "FB_TongueB_000":0.098306, "FB_TongueC_000":0.084491, "FB_UpperLipRoot_000":0.240688, "FB_UpperLip_000":0.262825, "IK_L_Foot":0.065097, "IK_L_Hand":0.058853, "IK_R_Foot":0.064991, "IK_R_Hand":0.058744, "PH_L_Foot":0.065097, "PH_L_Hand":0.058853, "PH_R_Foot":0.064991, "PH_R_Hand":0.058744, "SKEL_Head":0.069765, "SKEL_L_Calf":0.264571, "SKEL_L_Clavicle":0.096734, "SKEL_L_Finger00":0.156556, "SKEL_L_Finger01":0.077293, "SKEL_L_Foot":0.354351, "SKEL_L_Forearm":0.308842, "SKEL_L_Hand":0.204936, "SKEL_L_Thigh":0.162246, "SKEL_L_Toe0":0.182019, "SKEL_L_Toe1":0.094909, "SKEL_L_UpperArm":0.282052, "SKEL_Neck_1":0.088694, "SKEL_Neck_2":0.073548, "SKEL_Pelvis":0.345749, "SKEL_PelvisRoot":0.223008, "SKEL_R_Calf":0.264571, "SKEL_R_Clavicle":0.096734, "SKEL_R_Finger00":0.156374, "SKEL_R_Finger01":0.077254, "SKEL_R_Foot":0.354351, "SKEL_R_Forearm":0.308522, "SKEL_R_Hand":0.204737, "SKEL_R_Thigh":0.162246, "SKEL_R_Toe0":0.182018, "SKEL_R_Toe1":0.094909, "SKEL_R_UpperArm":0.283091, "SKEL_Spine0":0.223008, "SKEL_Spine1":0.409582, "SKEL_Spine2":0.19218, "SKEL_Spine3":0.100782, "SKEL_Tail_01":0.347456, "SKEL_Tail_02":0.106297, "SKEL_Tail_03":0.107576, "SKEL_Tail_04":0.102414, "SKEL_Tail_05":0.09613},
    "a_c_cat_01": {"FB_Jaw_000":0.018305, "FB_L_Ear_000":-0.018811, "FB_L_Eye_000":0.034099, "FB_L_Lid_Upper_000":0.034099, "FB_R_Ear_000":-0.01881, "FB_R_Eye_000":0.0341, "FB_R_Lid_Upper_000":0.0341, "FB_TongueA_000":-0.001704, "FB_TongueB_000":0.022245, "FB_TongueC_000":0.018991, "IK_L_Foot":0.012749, "IK_L_Hand":0.009212, "IK_R_Foot":0.012749, "IK_R_Hand":0.009213, "PH_L_Foot":0.012749, "PH_L_Hand":0.009212, "PH_R_Foot":0.012749, "PH_R_Hand":0.009213, "SKEL_Head":0.045472, "SKEL_L_Calf":0.107111, "SKEL_L_Clavicle":0.0064, "SKEL_L_Finger00":0.023323, "SKEL_L_Finger01":0.035842, "SKEL_L_Foot":0.098875, "SKEL_L_Forearm":0.078549, "SKEL_L_Hand":0.103312, "SKEL_L_Thigh":-0.00226, "SKEL_L_Toe0":0.065104, "SKEL_L_Toe1":0.026873, "SKEL_L_UpperArm":0.074084, "SKEL_Neck0":0.063134, "SKEL_Neck1":0.052673, "SKEL_Neck2":0.037622, "SKEL_R_Calf":0.107111, "SKEL_R_Clavicle":0.0064, "SKEL_R_Finger00":0.023323, "SKEL_R_Finger01":0.035842, "SKEL_R_Foot":0.098875, "SKEL_R_Forearm":0.078548, "SKEL_R_Hand":0.103313, "SKEL_R_Thigh":-0.00226, "SKEL_R_Toe0":0.065104, "SKEL_R_Toe1":0.026873, "SKEL_R_UpperArm":0.074085, "SKEL_Spine0":0.046852, "SKEL_Spine1":0.065933, "SKEL_Spine2":0.060629, "SKEL_Spine3":0.055632, "SKEL_Tail0":-0.017655, "SKEL_Tail1":0.056308, "SKEL_Tail2":0.058487, "SKEL_Tail3":0.04682, "SKEL_Tail4":0.044085, "SKEL_Tail5":0.040024},
    "a_c_chickenhawk": {"FB_Jaw_000":0.018878, "IK_L_Foot":0.005843, "IK_L_Hand":0.068577, "IK_R_Foot":0.005843, "IK_R_Hand":0.068577, "MH_L_WingPusher":0.06917, "MH_L_WingShoulder":0.205965, "MH_L_Wing_TrailingEdgeROOT":0.248428, "MH_R_WingPusher":0.06917, "MH_R_WingShoulder":0.205965, "MH_R_Wing_TrailingEdgeROOT":0.232645, "PH_L_Foot":0.005843, "PH_L_Hand":0.068577, "PH_R_Foot":0.005843, "PH_R_Hand":0.068577, "SKEL_Head":0.058487, "SKEL_L_Calf":0.052879, "SKEL_L_Clavicle":-0.060652, "SKEL_L_Finger00":0.218946, "SKEL_L_Foot":0.045116, "SKEL_L_Forearm":0.202111, "SKEL_L_Hand":0.205965, "SKEL_L_Thigh":-0.01941, "SKEL_L_Toe0":0.059222, "SKEL_L_UpperArm":0.120089, "SKEL_Neck_1":0.046024, "SKEL_R_Calf":0.052879, "SKEL_R_Clavicle":-0.060652, "SKEL_R_Finger00":0.218946, "SKEL_R_Foot":0.045117, "SKEL_R_Forearm":0.202111, "SKEL_R_Hand":0.205965, "SKEL_R_Thigh":-0.01941, "SKEL_R_Toe0":0.059222, "SKEL_R_UpperArm":0.120089, "SKEL_Spine0":0.024245, "SKEL_Spine1":0.024914, "SKEL_Spine2":0.030136, "SKEL_Spine3":0.059718, "SKEL_Tail_01":0.039922, "SKEL_Tail_02":0.057934},
    "a_c_chimp": {"FB_Brow_Centre_000":0.078168, "FB_Jaw_000":0.012558, "FB_L_Brow_Out_000":0.091615, "FB_L_CheekBone_000":0.078241, "FB_L_Eye_000":0.091601, "FB_L_Lid_Upper_000":0.091601, "FB_L_Lip_Bot_000":0.00432, "FB_L_Lip_Corner_000":0.023659, "FB_L_Lip_Top_000":0.011465, "FB_LowerLipRoot_000":0.056424, "FB_LowerLip_000":0.056151, "FB_R_Brow_Out_000":0.090299, "FB_R_CheekBone_000":0.078246, "FB_R_Eye_000":0.091676, "FB_R_Lid_Upper_000":0.091674, "FB_R_Lip_Bot_000":0.004318, "FB_R_Lip_Corner_000":0.023664, "FB_R_Lip_Top_000":0.011466, "FB_Tongue_000":-0.002027, "FB_UpperLipRoot_000":0.029432, "FB_UpperLip_000":0.061753, "IK_L_Foot":0.060976, "IK_L_Hand":0.048288, "IK_R_Foot":0.060903, "IK_R_Hand":0.048288, "PH_L_Foot":0.060976, "PH_L_Hand":0.068122, "PH_R_Foot":0.060903, "PH_R_Hand":0.068122, "RB_L_ArmRoll":0.130385, "RB_L_ForeArmRoll":0.16054, "RB_L_ThighRoll":0.106199, "RB_Neck_1":0.045655, "RB_R_ArmRoll":0.130385, "RB_R_ForeArmRoll":0.16054, "RB_R_ThighRoll":0.106199, "SKEL_Head":0.091311, "SKEL_L_Calf":0.313659, "SKEL_L_Clavicle":0.010672, "SKEL_L_Finger00":0.010273, "SKEL_L_Finger01":0.051529, "SKEL_L_Finger02":0.033065, "SKEL_L_Finger10":0.138144, "SKEL_L_Finger11":0.039233, "SKEL_L_Finger12":0.026965, "SKEL_L_Finger20":0.132963, "SKEL_L_Finger21":0.040093, "SKEL_L_Finger22":0.026668, "SKEL_L_Finger30":0.122234, "SKEL_L_Finger31":0.039803, "SKEL_L_Finger32":0.020758, "SKEL_L_Finger40":0.110422, "SKEL_L_Finger41":0.039465, "SKEL_L_Finger42":0.019441, "SKEL_L_Foot":0.263417, "SKEL_L_Forearm":0.33463, "SKEL_L_Hand":0.321081, "SKEL_L_Thigh":0.106199, "SKEL_L_Toe0":0.112234, "SKEL_L_UpperArm":0.130385, "SKEL_Neck_1":0.045189, "SKEL_R_Calf":0.313659, "SKEL_R_Clavicle":0.010672, "SKEL_R_Finger00":0.010273, "SKEL_R_Finger01":0.051529, "SKEL_R_Finger02":0.033065, "SKEL_R_Finger10":0.138144, "SKEL_R_Finger11":0.039233, "SKEL_R_Finger12":0.026965, "SKEL_R_Finger20":0.132963, "SKEL_R_Finger21":0.040093, "SKEL_R_Finger22":0.026668, "SKEL_R_Finger30":0.122234, "SKEL_R_Finger31":0.039803, "SKEL_R_Finger32":0.020758, "SKEL_R_Finger40":0.110421, "SKEL_R_Finger41":0.039466, "SKEL_R_Finger42":0.019441, "SKEL_R_Foot":0.263417, "SKEL_R_Forearm":0.33463, "SKEL_R_Hand":0.321081, "SKEL_R_Thigh":0.106199, "SKEL_R_Toe0":0.112234, "SKEL_R_UpperArm":0.130385, "SKEL_Spine0":0.03796, "SKEL_Spine1":0.130878, "SKEL_Spine2":0.136711, "SKEL_Spine3":0.118131},
    "a_c_chop": {"FB_Brow_Centre_000":0.106603, "FB_Jaw_000":0.122279, "FB_L_Brow_Out_000":0.116605, "FB_L_CheekBone_000":0.216117, "FB_L_Ear_000":0.058103, "FB_L_Eye_000":0.161926, "FB_L_Lid_Upper_000":0.161928, "FB_L_Lip_Bot_000":-0.063792, "FB_L_Lip_Corner_000":0.117533, "FB_L_Lip_Top_000":0.043003, "FB_LowerLipRoot_000":0.00764, "FB_LowerLip_000":0.104229, "FB_R_Brow_Out_000":0.116602, "FB_R_CheekBone_000":0.216117, "FB_R_Ear_000":0.095903, "FB_R_Eye_000":0.161926, "FB_R_Lid_Upper_000":0.161926, "FB_R_Lip_Bot_000":-0.06379, "FB_R_Lip_Corner_000":0.117529, "FB_R_Lip_Top_000":0.043003, "FB_TongueA_000":0.125683, "FB_TongueB_000":0.037119, "FB_TongueC_000":0.026509, "FB_UpperLipRoot_000":0.156192, "FB_UpperLip_000":0.114318, "IK_L_Foot":0.023017, "IK_L_Hand":0.022382, "IK_R_Foot":0.023017, "IK_R_Hand":0.022382, "PH_L_Foot":0.023017, "PH_L_Hand":0.022382, "PH_R_Foot":0.023017, "PH_R_Hand":0.022382, "SKEL_Head":0.0512, "SKEL_L_Calf":0.193324, "SKEL_L_Clavicle":0.003386, "SKEL_L_Finger00":0.090238, "SKEL_L_Finger01":0.034649, "SKEL_L_Foot":0.198544, "SKEL_L_Forearm":0.138202, "SKEL_L_Hand":0.206576, "SKEL_L_Thigh":0.139635, "SKEL_L_Toe0":0.184703, "SKEL_L_Toe1":0.036926, "SKEL_L_UpperArm":0.183114, "SKEL_Neck_1":0.055221, "SKEL_Neck_2":0.039543, "SKEL_Pelvis":0.090076, "SKEL_Pelvis1":0.113437, "SKEL_PelvisRoot":0.124949, "SKEL_R_Calf":0.193324, "SKEL_R_Clavicle":0.003386, "SKEL_R_Finger00":0.090238, "SKEL_R_Finger01":0.034649, "SKEL_R_Foot":0.198544, "SKEL_R_Forearm":0.138201, "SKEL_R_Hand":0.206576, "SKEL_R_Thigh":0.139635, "SKEL_R_Toe0":0.184703, "SKEL_R_Toe1":0.036926, "SKEL_R_UpperArm":0.183114, "SKEL_Spine0":0.124949, "SKEL_Spine1":0.165231, "SKEL_Spine2":0.047982, "SKEL_Spine3":0.047637, "SKEL_Tail_01":0.079127, "SKEL_Tail_02":0.149595, "SKEL_Tail_03":0.072884, "SKEL_Tail_04":0.046875, "SKEL_Tail_05":0.04696, "SPR_GonadsROOT":0.135971, "SPR_L_Ear":0.012663, "SPR_R_Ear":-0.010544},
    "a_c_cormorant": {"FB_Jaw_000":0.064444, "IK_L_Foot":0.019191, "IK_L_Hand":0.07219, "IK_R_Foot":0.019189, "IK_R_Hand":0.072363, "PH_L_Foot":0.019191, "PH_L_Hand":0.07219, "PH_R_Foot":0.019189, "PH_R_Hand":0.072363, "SKEL_Head":0.063891, "SKEL_L_Calf":0.114828, "SKEL_L_Clavicle":0.033444, "SKEL_L_Finger00":0.251905, "SKEL_L_Foot":0.08668, "SKEL_L_Forearm":0.267732, "SKEL_L_Hand":0.289559, "SKEL_L_Thigh":0.01002, "SKEL_L_Toe0":0.085865, "SKEL_L_UpperArm":0.156732, "SKEL_Neck_1":0.074648, "SKEL_R_Calf":0.11486, "SKEL_R_Clavicle":0.033444, "SKEL_R_Finger00":0.252402, "SKEL_R_Foot":0.086677, "SKEL_R_Forearm":0.267991, "SKEL_R_Hand":0.289384, "SKEL_R_Thigh":0.01002, "SKEL_R_Toe0":0.085864, "SKEL_R_UpperArm":0.156589, "SKEL_Spine0":0.017365, "SKEL_Spine1":0.086387, "SKEL_Spine2":0.116152, "SKEL_Spine3":0.064924, "SKEL_Tail_01":0.101534, "SKEL_Tail_02":0.151962},
    "a_c_cow": {"FB_Brow_Centre_000":0.007058, "FB_Jaw_000":0.196318, "FB_L_Brow_Out_000":-0.004636, "FB_L_CheekBone_000":0.36761, "FB_L_Ear_000":-0.052311, "FB_L_Eye_000":0.10568, "FB_L_Lid_Upper_000":0.10568, "FB_L_Lip_Bot_000":0.01357, "FB_L_Lip_Corner_000":0.303778, "FB_L_Lip_Top_000":0.019986, "FB_LowerLipRoot_000":-0.046202, "FB_LowerLipTwist_000":0.100427, "FB_LowerLip_000":0.134519, "FB_R_Brow_Out_000":-0.004626, "FB_R_CheekBone_000":0.367801, "FB_R_Ear_000":-0.051217, "FB_R_Eye_000":0.106588, "FB_R_Lid_Upper_000":0.106588, "FB_R_Lip_Bot_000":0.013572, "FB_R_Lip_Corner_000":0.303564, "FB_R_Lip_Top_000":0.019985, "FB_TongueA_000":-0.020111, "FB_TongueB_000":0.053712, "FB_TongueC_000":0.041121, "FB_UpperLipRoot_000":-0.019667, "FB_UpperLipTwist_000":0.262289, "FB_UpperLip_000":0.13985, "IK_L_Foot":0.077824, "IK_L_Hand":0.100015, "IK_R_Foot":0.077827, "IK_R_Hand":0.100011, "LookAtTarget":-0.690175, "LookAtUpnode":1.27946, "PH_L_Foot":0.077824, "PH_L_Hand":0.100015, "PH_R_Foot":0.077827, "PH_R_Hand":0.100011, "SKEL_Head":0.233317, "SKEL_L_Calf":0.32351, "SKEL_L_Clavicle":0.216985, "SKEL_L_Finger00":0.205963, "SKEL_L_Finger01":0.107544, "SKEL_L_Foot":0.306994, "SKEL_L_Forearm":0.360831, "SKEL_L_Hand":0.266513, "SKEL_L_Thigh":0.180586, "SKEL_L_Toe0":0.338634, "SKEL_L_Toe1":0.072274, "SKEL_L_UpperArm":0.155409, "SKEL_Neck_1":0.166131, "SKEL_Neck_2":0.169872, "SKEL_Pelvis":0.234785, "SKEL_Pelvis1":0.167879, "SKEL_PelvisRoot":0.181183, "SKEL_R_Calf":0.32351, "SKEL_R_Clavicle":0.216985, "SKEL_R_Finger00":0.205977, "SKEL_R_Finger01":0.107545, "SKEL_R_Foot":0.306991, "SKEL_R_Forearm":0.360842, "SKEL_R_Hand":0.266517, "SKEL_R_Thigh":0.180586, "SKEL_R_Toe0":0.338636, "SKEL_R_Toe1":0.072278, "SKEL_R_UpperArm":0.155409, "SKEL_Spine0":0.181183, "SKEL_Spine1":0.251497, "SKEL_Spine2":0.018711, "SKEL_Spine3":0.429588, "SKEL_Tail_01":0.308702, "SKEL_Tail_02":0.116554, "SKEL_Tail_03":0.10868, "SKEL_Tail_04":0.151471, "SKEL_Tail_05":0.159516, "SM_CowBell_ROOT":-0.022948, "SM_Udders":-0.053013},
    "a_c_coyote": {"FB_Brow_Centre_000":0.062047, "FB_Jaw_000":0.08314, "FB_L_Brow_Out_000":0.056221, "FB_L_CheekBone_000":0.200733, "FB_L_Ear_000":0.019379, "FB_L_Eye_000":0.082088, "FB_L_Lid_Upper_000":0.082088, "FB_L_Lip_Bot_000":-0.058678, "FB_L_Lip_Corner_000":0.108904, "FB_L_Lip_Top_000":0.008135, "FB_LowerLipRoot_000":0.034077, "FB_LowerLip_000":0.072859, "FB_R_Brow_Out_000":0.056221, "FB_R_CheekBone_000":0.200733, "FB_R_Ear_000":0.01938, "FB_R_Eye_000":0.082088, "FB_R_Lid_Upper_000":0.082088, "FB_R_Lip_Bot_000":-0.058677, "FB_R_Lip_Corner_000":0.108904, "FB_R_Lip_Top_000":0.008134, "FB_TongueA_000":0.120925, "FB_TongueB_000":0.015661, "FB_TongueC_000":0.023049, "FB_UpperLipRoot_000":0.118668, "FB_UpperLip_000":0.080812, "IK_L_Foot":0.046944, "IK_L_Hand":0.054566, "IK_R_Foot":0.04695, "IK_R_Hand":0.054567, "PH_L_Foot":0.046944, "PH_L_Hand":0.054566, "PH_R_Foot":0.04695, "PH_R_Hand":0.054567, "SKEL_Head":0.091256, "SKEL_L_Calf":0.215781, "SKEL_L_Clavicle":0.048002, "SKEL_L_Finger00":0.050152, "SKEL_L_Finger01":0.052785, "SKEL_L_Foot":0.167894, "SKEL_L_Forearm":0.158095, "SKEL_L_Hand":0.191651, "SKEL_L_Thigh":0.094708, "SKEL_L_Toe0":0.142224, "SKEL_L_Toe1":0.062485, "SKEL_L_UpperArm":0.12404, "SKEL_Neck_1":0.122817, "SKEL_Neck_2":0.092152, "SKEL_Pelvis":0.091693, "SKEL_PelvisRoot":0.070699, "SKEL_R_Calf":0.217322, "SKEL_R_Clavicle":0.048002, "SKEL_R_Finger00":0.050152, "SKEL_R_Finger01":0.052785, "SKEL_R_Foot":0.166696, "SKEL_R_Forearm":0.158095, "SKEL_R_Hand":0.191651, "SKEL_R_Thigh":0.094708, "SKEL_R_Toe0":0.142219, "SKEL_R_Toe1":0.06249, "SKEL_R_UpperArm":0.12404, "SKEL_Spine0":0.070699, "SKEL_Spine1":0.147722, "SKEL_Spine2":0.010255, "SKEL_Spine3":0.129346, "SKEL_Tail_01":0.095425, "SKEL_Tail_02":0.108939, "SKEL_Tail_03":0.093276, "SKEL_Tail_04":0.091538, "SKEL_Tail_05":0.093637},
    "a_c_crow": {"FB_Jaw_000":0.022633, "IK_L_Foot":0.007726, "IK_L_Hand":0.05509, "IK_R_Foot":0.007729, "IK_R_Hand":0.05514, "PH_L_Foot":0.007726, "PH_L_Hand":0.05509, "PH_R_Foot":0.007729, "PH_R_Hand":0.05514, "SKEL_Head":0.058732, "SKEL_L_Calf":0.068364, "SKEL_L_Clavicle":-0.034803, "SKEL_L_Finger00":0.172066, "SKEL_L_Foot":0.065081, "SKEL_L_Forearm":0.147999, "SKEL_L_Hand":0.160219, "SKEL_L_Thigh":0.036334, "SKEL_L_Toe0":0.044635, "SKEL_L_UpperArm":0.087816, "SKEL_Neck_1":0.028614, "SKEL_R_Calf":0.068364, "SKEL_R_Clavicle":-0.034803, "SKEL_R_Finger00":0.17252, "SKEL_R_Foot":0.065078, "SKEL_R_Forearm":0.14788, "SKEL_R_Hand":0.160279, "SKEL_R_Thigh":0.036237, "SKEL_R_Toe0":0.044631, "SKEL_R_UpperArm":0.087744, "SKEL_Spine0":0.024245, "SKEL_Spine1":0.024914, "SKEL_Spine2":0.030136, "SKEL_Spine3":0.038474, "SKEL_Tail_01":0.023774, "SKEL_Tail_02":0.049975},
    "a_c_deer": {"FB_Brow_Centre_000":0.042733, "FB_Jaw_000":0.158349, "FB_L_Brow_Out_000":0.059992, "FB_L_CheekBone_000":0.322311, "FB_L_Ear_000":-0.021093, "FB_L_Eye_000":0.111855, "FB_L_Lid_Upper_000":0.112561, "FB_L_Lip_Bot_000":-0.07495, "FB_L_Lip_Corner_000":0.251667, "FB_L_Lip_Top_000":0.010066, "FB_LowerLipRoot_000":0.037878, "FB_LowerLipTwist_000":0.047574, "FB_LowerLip_000":0.091609, "FB_R_Brow_Out_000":0.06009, "FB_R_CheekBone_000":0.322437, "FB_R_Ear_000":-0.020013, "FB_R_Eye_000":0.112641, "FB_R_Lid_Upper_000":0.11336, "FB_R_Lip_Bot_000":-0.074949, "FB_R_Lip_Corner_000":0.251398, "FB_R_Lip_Top_000":0.010068, "FB_TongueA_000":0.002182, "FB_TongueB_000":0.038976, "FB_TongueC_000":0.02382, "FB_UpperLipRoot_000":0.052179, "FB_UpperLipTwist_000":0.205408, "FB_UpperLip_000":0.087485, "IK_L_Foot":0.053907, "IK_L_Hand":0.054828, "IK_R_Foot":0.053907, "IK_R_Hand":0.054827, "PH_L_Foot":0.053907, "PH_L_Hand":0.054828, "PH_R_Foot":0.053907, "PH_R_Hand":0.054827, "SKEL_Head":0.177055, "SKEL_L_Calf":0.3058, "SKEL_L_Clavicle":0.091546, "SKEL_L_Finger00":0.212466, "SKEL_L_Finger01":0.070516, "SKEL_L_Foot":0.31909, "SKEL_L_Forearm":0.320315, "SKEL_L_Hand":0.327893, "SKEL_L_Thigh":0.145531, "SKEL_L_Toe0":0.33103, "SKEL_L_Toe1":0.089259, "SKEL_L_UpperArm":0.261048, "SKEL_Neck_1":0.199311, "SKEL_Neck_2":0.171726, "SKEL_Pelvis":0.269081, "SKEL_Pelvis1":0.074861, "SKEL_PelvisRoot":0.104809, "SKEL_R_Calf":0.3058, "SKEL_R_Clavicle":0.090612, "SKEL_R_Finger00":0.212466, "SKEL_R_Finger01":0.070516, "SKEL_R_Foot":0.319089, "SKEL_R_Forearm":0.320315, "SKEL_R_Hand":0.327893, "SKEL_R_Thigh":0.145531, "SKEL_R_Toe0":0.33103, "SKEL_R_Toe1":0.089259, "SKEL_R_UpperArm":0.261048, "SKEL_Spine0":0.104809, "SKEL_Spine1":0.255132, "SKEL_Spine2":0.011532, "SKEL_Spine3":0.242762, "SKEL_Tail_01":0.35519, "SKEL_Tail_02":0.099306, "SKEL_Tail_03":0.099547, "SKEL_Tail_04":0.10033, "SKEL_Tail_05":0.2709},
    "a_c_dolphin": {"SKEL_Dorsal_01":0.447902, "SKEL_Dorsal_02":0.282703, "SKEL_Jaw":0.298133, "SKEL_L_Fin":0.224775, "SKEL_L_TailFin_00":0.209082, "SKEL_L_TailFin_01":0.294171, "SKEL_Pelvis":-0.198802, "SKEL_R_Fin":0.239054, "SKEL_R_TailFin_00":0.20903, "SKEL_R_TailFin_01":0.296824, "SKEL_Tail0":0.575909, "SKEL_Tail1":0.499252, "SKEL_Tail2":0.514736, "SKEL_Tail3":0.500422, "SKEL_Tail4":0.547763},
    "a_c_fish": {"FB_Jaw_001":0.133624, "IK_L_Foot":0.10335, "IK_L_Hand":0.150767, "IK_R_Foot":0.10335, "IK_R_Hand":0.150738, "PH_L_Foot":0.10335, "PH_L_Hand":0.150767, "PH_R_Foot":0.10335, "PH_R_Hand":0.150738, "SKEL_Head":0.111642, "SKEL_L_Clavicle":0.061171, "SKEL_L_Thigh":0.121723, "SKEL_R_Clavicle":0.060976, "SKEL_R_Thigh":0.121723, "SKEL_Spine1":0.118901, "SKEL_Tail_01":0.124768, "SKEL_Tail_02":0.1566, "SKEL_Tail_03":0.150407},
    "a_c_hen": {"FB_Jaw_000":0.046025, "IK_L_Foot":0.014715, "IK_R_Foot":0.014372, "IK_R_Hand":0.139051, "PH_L_Foot":0.014715, "PH_R_Foot":0.014372, "PH_R_Hand":0.139051, "SKEL_Head":0.143308, "SKEL_L_Calf":0.093034, "SKEL_L_Clavicle":-0.018194, "SKEL_L_Foot":0.118681, "SKEL_L_Thigh":0.055571, "SKEL_L_Toe0":0.056145, "SKEL_Neck_1":-0.018342, "SKEL_PelvisRoot":0.007106, "SKEL_R_Calf":0.093034, "SKEL_R_Clavicle":0.012311, "SKEL_R_Foot":0.118681, "SKEL_R_Thigh":0.055571, "SKEL_R_Toe0":0.056145, "SKEL_Spine0":0.007106, "SKEL_Spine1":0.015567, "SKEL_Spine2":0.017813, "SKEL_Spine3":0.018379, "SKEL_Tail_01":0.05665, "SKEL_Tail_02":0.061118},
    "a_c_humpback": {"SKEL_Dorsal_01":0.402202, "SKEL_Dorsal_02":0.241904, "SKEL_Jaw":0.206872, "SKEL_L_Fin":0.10082, "SKEL_L_TailFin_00":0.737049, "SKEL_L_TailFin_01":1.092294, "SKEL_Pelvis":0.331352, "SKEL_R_Fin":0.102379, "SKEL_R_TailFin_00":0.737072, "SKEL_R_TailFin_01":1.092273, "SKEL_Tail0":1.736523, "SKEL_Tail1":1.819287, "SKEL_Tail2":2.026069, "SKEL_Tail3":2.05889, "SKEL_Tail4":1.871329},
    "a_c_husky": {"FB_Brow_Centre_000":0.024962, "FB_Jaw_000":0.020081, "FB_L_Brow_Out_000":0.029049, "FB_L_CheekBone_000":0.131146, "FB_L_Ear_000":0.002274, "FB_L_Eye_000":0.078351, "FB_L_Lid_Upper_000":0.080334, "FB_L_Lip_Bot_000":-0.011927, "FB_L_Lip_Corner_000":0.079945, "FB_L_Lip_Top_000":0.008421, "FB_LowerLipRoot_000":0.06029, "FB_LowerLip_000":0.076825, "FB_R_Brow_Out_000":0.029049, "FB_R_CheekBone_000":0.131146, "FB_R_Ear_000":0.002274, "FB_R_Eye_000":0.078351, "FB_R_Lid_Upper_000":0.080334, "FB_R_Lip_Bot_000":-0.011927, "FB_R_Lip_Corner_000":0.079945, "FB_R_Lip_Top_000":0.008421, "FB_TongueA_000":0.053231, "FB_TongueB_000":0.048554, "FB_TongueC_000":0.025202, "FB_UpperLipRoot_000":0.07617, "FB_UpperLip_000":0.099607, "IK_L_Foot":0.035897, "IK_L_Hand":0.033006, "IK_R_Foot":0.035897, "IK_R_Hand":0.032958, "PH_L_Foot":0.035897, "PH_L_Hand":0.033006, "PH_R_Foot":0.035897, "PH_R_Hand":0.032958, "SKEL_Head":0.067502, "SKEL_L_Calf":0.186092, "SKEL_L_Clavicle":0.002894, "SKEL_L_Finger00":0.078135, "SKEL_L_Finger01":0.036039, "SKEL_L_Foot":0.220489, "SKEL_L_Forearm":0.115893, "SKEL_L_Hand":0.232206, "SKEL_L_Thigh":0.120215, "SKEL_L_Toe0":0.142614, "SKEL_L_Toe1":0.038147, "SKEL_L_UpperArm":0.13127, "SKEL_Neck_1":0.048909, "SKEL_Neck_2":0.053178, "SKEL_Pelvis":0.089141, "SKEL_Pelvis1":0.112286, "SKEL_PelvisRoot":0.135271, "SKEL_R_Calf":0.186092, "SKEL_R_Clavicle":0.002894, "SKEL_R_Finger00":0.078104, "SKEL_R_Finger01":0.035978, "SKEL_R_Foot":0.220489, "SKEL_R_Forearm":0.115862, "SKEL_R_Hand":0.232207, "SKEL_R_Thigh":0.120215, "SKEL_R_Toe0":0.142614, "SKEL_R_Toe1":0.038147, "SKEL_R_UpperArm":0.131225, "SKEL_Spine0":0.135271, "SKEL_Spine1":0.163559, "SKEL_Spine2":0.047327, "SKEL_Spine3":0.042192, "SKEL_Tail_01":0.077982, "SKEL_Tail_02":0.138974, "SKEL_Tail_03":0.076796, "SKEL_Tail_04":0.065991, "SKEL_Tail_05":0.079405},
    "a_c_killerwhale": {"FB_Jaw_000":0.08106, "SKEL_Dorsal_01":0.50627, "SKEL_Dorsal_02":0.547138, "SKEL_Head":-0.510501, "SKEL_Jaw":0.08106, "SKEL_L_Fin":0.087914, "SKEL_L_TailFin_00":0.29003, "SKEL_L_TailFin_01":0.46583, "SKEL_Pelvis":-0.198909, "SKEL_R_Fin":0.088579, "SKEL_R_TailFin_00":0.290039, "SKEL_R_TailFin_01":0.465827, "SKEL_Tail0":0.701067, "SKEL_Tail1":0.775878, "SKEL_Tail2":0.864064, "SKEL_Tail3":0.875536, "SKEL_Tail4":0.791797},
    "a_c_mtlion": {"FB_Brow_Centre_000":0.023208, "FB_Jaw_000":0.034047, "FB_L_Brow_Out_000":0.062889, "FB_L_CheekBone_000":0.106758, "FB_L_Ear_000":-0.018625, "FB_L_Eye_000":0.077609, "FB_L_Lid_Upper_000":0.080503, "FB_L_Lip_Bot_000":-0.002233, "FB_L_Lip_Corner_000":0.090305, "FB_L_Lip_Top_000":0.003608, "FB_LowerLipRoot_000":0.124848, "FB_LowerLip_000":-0.02521, "FB_R_Brow_Out_000":0.063899, "FB_R_CheekBone_000":0.107268, "FB_R_Ear_000":-0.017493, "FB_R_Eye_000":0.078403, "FB_R_Lid_Upper_000":0.081297, "FB_R_Lip_Bot_000":-0.002233, "FB_R_Lip_Corner_000":0.089819, "FB_R_Lip_Top_000":0.003609, "FB_TongueA_000":-0.123731, "FB_TongueB_000":0.083299, "FB_TongueC_000":0.047913, "FB_UpperLipRoot_000":0.064558, "FB_UpperLip_000":0.102753, "IK_L_Foot":0.046663, "IK_L_Hand":0.062918, "IK_R_Foot":0.046667, "IK_R_Hand":0.062922, "PH_L_Foot":0.046663, "PH_L_Hand":0.062918, "PH_R_Foot":0.046667, "PH_R_Hand":0.062922, "SKEL_Head":0.157747, "SKEL_L_Calf":0.285268, "SKEL_L_Clavicle":0.130351, "SKEL_L_Finger00":0.07734, "SKEL_L_Finger01":0.084988, "SKEL_L_Foot":0.265282, "SKEL_L_Forearm":0.220857, "SKEL_L_Hand":0.227494, "SKEL_L_Thigh":0.118318, "SKEL_L_Toe0":0.164455, "SKEL_L_Toe1":0.06853, "SKEL_L_UpperArm":0.158209, "SKEL_Neck_1":0.050838, "SKEL_Neck_2":0.120425, "SKEL_Pelvis":0.204425, "SKEL_PelvisRoot":0.083277, "SKEL_R_Calf":0.285267, "SKEL_R_Clavicle":0.130351, "SKEL_R_Finger00":0.07734, "SKEL_R_Finger01":0.084988, "SKEL_R_Foot":0.265283, "SKEL_R_Forearm":0.220856, "SKEL_R_Hand":0.227495, "SKEL_R_Thigh":0.118318, "SKEL_R_Toe0":0.164455, "SKEL_R_Toe1":0.06853, "SKEL_R_UpperArm":0.158209, "SKEL_Spine0":0.083277, "SKEL_Spine1":0.187677, "SKEL_Spine2":0.007026, "SKEL_Spine3":0.083049, "SKEL_Tail_01":0.341973, "SKEL_Tail_02":0.08785, "SKEL_Tail_03":0.13221, "SKEL_Tail_04":0.20272, "SKEL_Tail_05":0.140804},
    "a_c_pig": {"FB_Brow_Centre_000":0.02642, "FB_Jaw_000":0.080704, "FB_L_Brow_Out_000":0.035309, "FB_L_CheekBone_000":0.259116, "FB_L_Ear_000":0.005725, "FB_L_Eye_000":0.070339, "FB_L_Lid_Upper_000":0.070339, "FB_L_Lip_Bot_000":-0.082322, "FB_L_Lip_Corner_000":0.108242, "FB_L_Lip_Top_000":-0.008913, "FB_LowerLipRoot_000":0.053425, "FB_LowerLip_000":0.112088, "FB_R_Brow_Out_000":0.035398, "FB_R_CheekBone_000":0.259231, "FB_R_Ear_000":0.007054, "FB_R_Eye_000":0.071026, "FB_R_Lid_Upper_000":0.071026, "FB_R_Lip_Bot_000":-0.082322, "FB_R_Lip_Corner_000":0.109058, "FB_R_Lip_Top_000":-0.008913, "FB_TongueA_000":0.094687, "FB_TongueB_000":0.15747, "FB_TongueC_000":0.19762, "FB_UpperLipRoot_000":0.100721, "FB_UpperLip_000":0.145984, "IK_L_Foot":0.187346, "IK_L_Hand":0.047077, "IK_R_Foot":0.187347, "IK_R_Hand":0.04708, "PH_L_Foot":0.187346, "PH_L_Hand":0.047077, "PH_R_Foot":0.187347, "PH_R_Hand":0.04708, "SKEL_Head":0.05093, "SKEL_L_Calf":0.218569, "SKEL_L_Clavicle":0.059738, "SKEL_L_Finger00":0.090348, "SKEL_L_Finger01":0.044209, "SKEL_L_Foot":0.218761, "SKEL_L_Forearm":0.179984, "SKEL_L_Hand":0.120662, "SKEL_L_Thigh":0.184404, "SKEL_L_Toe0":0.104092, "SKEL_L_Toe1":0.056508, "SKEL_L_UpperArm":0.165075, "SKEL_Neck_1":0.056903, "SKEL_Neck_2":0.046291, "SKEL_Pelvis":0.180517, "SKEL_PelvisRoot":0.079971, "SKEL_R_Calf":0.218569, "SKEL_R_Clavicle":0.059738, "SKEL_R_Finger00":0.090348, "SKEL_R_Finger01":0.04421, "SKEL_R_Foot":0.218761, "SKEL_R_Forearm":0.179984, "SKEL_R_Hand":0.120662, "SKEL_R_Thigh":0.184404, "SKEL_R_Toe0":0.104092, "SKEL_R_Toe1":0.056508, "SKEL_R_UpperArm":0.165076, "SKEL_Spine0":0.079971, "SKEL_Spine1":0.230008, "SKEL_Spine2":0.119908, "SKEL_Spine3":0.094141, "SKEL_Tail_01":0.259743, "SKEL_Tail_02":0.035245, "SKEL_Tail_03":0.0376, "SKEL_Tail_04":0.036664, "SKEL_Tail_05":0.02917},
    "a_c_pigeon": {"FB_Jaw_000":0.016402, "IK_L_Foot":0.009866, "IK_L_Hand":0.044253, "IK_R_Foot":0.009866, "IK_R_Hand":0.044095, "MH_L_Concertina_A":0.039255, "MH_L_Concertina_B":0.097191, "MH_R_Concertina_A":0.039255, "MH_R_Concertina_B":0.097191, "PH_L_Foot":0.009866, "PH_L_Hand":0.044253, "PH_R_Foot":0.009866, "PH_R_Hand":0.044095, "SKEL_Head":0.029325, "SKEL_L_Calf":0.03578, "SKEL_L_Clavicle":-0.004114, "SKEL_L_Finger00":0.043494, "SKEL_L_Foot":0.036011, "SKEL_L_Forearm":0.083185, "SKEL_L_Hand":0.097191, "SKEL_L_Thigh":0.032685, "SKEL_L_Toe0":0.031307, "SKEL_L_UpperArm":0.039255, "SKEL_Neck_1":0.01534, "SKEL_R_Calf":0.03578, "SKEL_R_Clavicle":-0.004114, "SKEL_R_Finger00":0.043494, "SKEL_R_Foot":0.036011, "SKEL_R_Forearm":0.083185, "SKEL_R_Hand":0.097191, "SKEL_R_Thigh":0.032685, "SKEL_R_Toe0":0.031307, "SKEL_R_UpperArm":0.039255, "SKEL_Spine0":0.01978, "SKEL_Spine1":0.014612, "SKEL_Spine2":0.012688, "SKEL_Spine3":0.011482, "SKEL_Tail_01":0.054155, "SKEL_Tail_02":0.040337},
    "a_c_poodle": {"FB_Jaw_000":0.064381, "FB_L_Ear_000":0.014655, "FB_L_Eye_000":0.088588, "FB_L_Lid_Upper_000":0.088588, "FB_R_Ear_000":0.014656, "FB_R_Eye_000":0.088588, "FB_R_Lid_Upper_000":0.088588, "FB_TongueA_000":0.025713, "FB_TongueB_000":0.018606, "FB_TongueC_000":0.032126, "IK_L_Foot":0.022235, "IK_L_Hand":0.014645, "IK_R_Foot":0.022235, "IK_R_Hand":0.014645, "PH_L_Foot":0.022235, "PH_L_Hand":0.014645, "PH_R_Foot":0.022235, "PH_R_Hand":0.014645, "SKEL_Head":0.03921, "SKEL_L_Calf":0.117641, "SKEL_L_Clavicle":0.005515, "SKEL_L_Finger00":0.03546, "SKEL_L_Finger01":0.020761, "SKEL_L_Foot":0.109341, "SKEL_L_Forearm":0.089773, "SKEL_L_Hand":0.148047, "SKEL_L_Thigh":-0.030041, "SKEL_L_Toe0":0.104228, "SKEL_L_Toe1":0.031266, "SKEL_L_UpperArm":0.102422, "SKEL_Neck0":0.066564, "SKEL_Neck1":0.055646, "SKEL_Neck2":0.051887, "SKEL_R_Calf":0.117641, "SKEL_R_Clavicle":0.005516, "SKEL_R_Finger00":0.03546, "SKEL_R_Finger01":0.020761, "SKEL_R_Foot":0.109341, "SKEL_R_Forearm":0.089773, "SKEL_R_Hand":0.148047, "SKEL_R_Thigh":-0.03004, "SKEL_R_Toe0":0.104228, "SKEL_R_Toe1":0.031266, "SKEL_R_UpperArm":0.102422, "SKEL_Spine0":0.056001, "SKEL_Spine1":0.058816, "SKEL_Spine2":0.061449, "SKEL_Spine3":0.062079, "SKEL_Tail0":-0.068485, "SKEL_Tail1":0.0663, "SKEL_Tail2":0.055733},
    "a_c_pug": {"FB_Jaw_000":0.066469, "FB_L_Ear_000":0.006244, "FB_L_Eye_000":0.064835, "FB_L_Lid_Upper_000":0.064835, "FB_R_Ear_000":0.006245, "FB_R_Eye_000":0.064836, "FB_R_Lid_Upper_000":0.064836, "FB_TongueA_000":-0.011482, "FB_TongueB_000":0.022882, "FB_TongueC_000":0.029692, "IK_L_Foot":0.018023, "IK_L_Hand":0.007588, "IK_R_Foot":0.018023, "IK_R_Hand":0.007588, "MH_Tail0":0.100699, "PH_L_Foot":0.018023, "PH_L_Hand":0.007588, "PH_R_Foot":0.018023, "PH_R_Hand":0.007588, "SKEL_Head":0.03921, "SKEL_L_Calf":0.117641, "SKEL_L_Clavicle":0.005515, "SKEL_L_Finger00":0.03546, "SKEL_L_Finger01":0.020761, "SKEL_L_Foot":0.109341, "SKEL_L_Forearm":0.089773, "SKEL_L_Hand":0.148047, "SKEL_L_Thigh":-0.030041, "SKEL_L_Toe0":0.104228, "SKEL_L_Toe1":0.031266, "SKEL_L_UpperArm":0.102422, "SKEL_Neck0":0.066564, "SKEL_Neck1":0.055646, "SKEL_Neck2":0.051887, "SKEL_R_Calf":0.117641, "SKEL_R_Clavicle":0.005516, "SKEL_R_Finger00":0.03546, "SKEL_R_Finger01":0.020761, "SKEL_R_Foot":0.109341, "SKEL_R_Forearm":0.089773, "SKEL_R_Hand":0.148047, "SKEL_R_Thigh":-0.03004, "SKEL_R_Toe0":0.104228, "SKEL_R_Toe1":0.031266, "SKEL_R_UpperArm":0.102422, "SKEL_Spine0":0.056001, "SKEL_Spine1":0.058816, "SKEL_Spine2":0.061449, "SKEL_Spine3":0.062079, "SKEL_Tail0":-0.068485, "SKEL_Tail1":0.0663, "SKEL_Tail2":0.055733},
    "a_c_rabbit_01": {"IK_L_Foot":-0.061055, "IK_L_Hand":0.002686, "IK_R_Foot":-0.061055, "IK_R_Hand":0.002686, "PH_L_Foot":-0.061055, "PH_L_Hand":0.002686, "PH_R_Foot":-0.061055, "PH_R_Hand":0.002686, "SKEL_Head":0.020029, "SKEL_L_Calf":0.110532, "SKEL_L_Clavicle":0.012717, "SKEL_L_Ear01":0.009772, "SKEL_L_Ear02":0.057848, "SKEL_L_Ear03":0.055625, "SKEL_L_Finger00":0.028891, "SKEL_L_Foot":0.149213, "SKEL_L_Forearm":0.095753, "SKEL_L_Hand":0.109916, "SKEL_L_Thigh":-0.032591, "SKEL_L_Toe0":0.066068, "SKEL_L_Toe1":0.046428, "SKEL_L_UpperArm":0.068026, "SKEL_Neck0":0.073514, "SKEL_Neck1":0.013346, "SKEL_Pelvis":0.015391, "SKEL_R_Calf":0.110532, "SKEL_R_Clavicle":0.012717, "SKEL_R_Ear01":0.009772, "SKEL_R_Ear02":0.057848, "SKEL_R_Ear03":0.055625, "SKEL_R_Finger00":0.028891, "SKEL_R_Foot":0.149212, "SKEL_R_Forearm":0.095753, "SKEL_R_Hand":0.109916, "SKEL_R_Thigh":-0.032591, "SKEL_R_Toe0":0.066068, "SKEL_R_Toe1":0.046428, "SKEL_R_UpperArm":0.068026, "SKEL_Spine0":0.065298, "SKEL_Spine1":0.075858, "SKEL_Spine2":0.087974, "SKEL_Tail0":-0.07857, "SKEL_Tail1":0.041305},
    "a_c_rat": {"IK_L_Foot":0.011088, "IK_L_Hand":0.008627, "IK_R_Foot":0.011088, "IK_R_Hand":0.008627, "PH_L_Foot":0.011088, "PH_L_Hand":0.008627, "PH_R_Foot":0.011088, "PH_R_Hand":0.008627, "SKEL_Head":0.029245, "SKEL_L_Calf":0.048621, "SKEL_L_Clavicle":0.021888, "SKEL_L_Foot":0.016851, "SKEL_L_Forearm":0.01622, "SKEL_L_Thigh":0.023676, "SKEL_L_UpperArm":0.045131, "SKEL_Neck_1":0.024252, "SKEL_Pelvis":0.019879, "SKEL_R_Calf":0.048727, "SKEL_R_Clavicle":0.021888, "SKEL_R_Foot":0.016851, "SKEL_R_Forearm":0.01622, "SKEL_R_Thigh":0.023676, "SKEL_R_UpperArm":0.045168, "SKEL_Spine0":0.02153, "SKEL_Spine1":0.032277, "SKEL_tail_01":0.025981, "SKEL_tail_02":0.078832, "SKEL_tail_m_01":0.065407, "SKEL_tail_m_02":0.088768},
    "a_c_retriever": {"FB_Brow_Centre_000":0.059947, "FB_Jaw_000":0.097257, "FB_L_Brow_Out_000":0.054725, "FB_L_CheekBone_000":0.157593, "FB_L_Ear_000":0.012992, "FB_L_Eye_000":0.106833, "FB_L_Lid_Upper_000":0.11178, "FB_L_Lip_Bot_000":-0.086122, "FB_L_Lip_Corner_000":0.117531, "FB_L_Lip_Top_000":0.021042, "FB_LowerLipRoot_000":0.057262, "FB_LowerLip_000":0.056989, "FB_R_Brow_Out_000":0.054725, "FB_R_CheekBone_000":0.157594, "FB_R_Ear_000":0.01299, "FB_R_Eye_000":0.106833, "FB_R_Lid_Upper_000":0.111779, "FB_R_Lip_Bot_000":-0.086121, "FB_R_Lip_Corner_000":0.117534, "FB_R_Lip_Top_000":0.02104, "FB_TongueB_000":0.038824, "FB_TongueC_000":0.038141, "FB_UpperLipRoot_000":0.155299, "FB_UpperLip_000":0.066854, "IK_L_Foot":0.035897, "IK_L_Hand":0.033006, "IK_R_Foot":0.035897, "IK_R_Hand":0.032958, "PH_L_Foot":0.035897, "PH_L_Hand":0.033006, "PH_R_Foot":0.035897, "PH_R_Hand":0.032958, "SKEL_Head":0.067502, "SKEL_L_Calf":0.186092, "SKEL_L_Clavicle":0.002894, "SKEL_L_Finger00":0.078135, "SKEL_L_Finger01":0.036039, "SKEL_L_Foot":0.220489, "SKEL_L_Forearm":0.115893, "SKEL_L_Hand":0.232206, "SKEL_L_Thigh":0.120215, "SKEL_L_Toe0":0.142614, "SKEL_L_Toe1":0.038147, "SKEL_L_UpperArm":0.13127, "SKEL_Neck_1":0.048909, "SKEL_Neck_2":0.053178, "SKEL_Pelvis":0.089141, "SKEL_Pelvis1":0.112286, "SKEL_PelvisRoot":0.135271, "SKEL_R_Calf":0.186092, "SKEL_R_Clavicle":0.002894, "SKEL_R_Finger00":0.078104, "SKEL_R_Finger01":0.035978, "SKEL_R_Foot":0.220489, "SKEL_R_Forearm":0.115862, "SKEL_R_Hand":0.232207, "SKEL_R_Thigh":0.120215, "SKEL_R_Toe0":0.142614, "SKEL_R_Toe1":0.038147, "SKEL_R_UpperArm":0.131225, "SKEL_Spine0":0.135271, "SKEL_Spine1":0.163559, "SKEL_Spine2":0.047327, "SKEL_Spine3":0.042192, "SKEL_Tail_01":0.077982, "SKEL_Tail_02":0.138974, "SKEL_Tail_03":0.076796, "SKEL_Tail_04":0.065991, "SKEL_Tail_05":0.079405},
    "a_c_rhesus": {"FB_Brow_Centre_000":0.048628, "FB_Jaw_000":0.014538, "FB_L_Brow_Out_000":0.070578, "FB_L_CheekBone_000":0.06631, "FB_L_Eye_000":0.066504, "FB_L_Lid_Upper_000":0.066167, "FB_L_Lip_Corner_000":0.006105, "FB_L_Lip_Top_000":0.006822, "FB_LowerLipRoot_000":0.037639, "FB_LowerLip_000":0.033821, "FB_R_Brow_Out_000":0.070578, "FB_R_CheekBone_000":0.06631, "FB_R_Eye_000":0.066504, "FB_R_Lid_Upper_000":0.066166, "FB_R_Lip_Corner_000":0.006105, "FB_R_Lip_Top_000":0.006822, "FB_Tongue_000":0.00187, "FB_UpperLipRoot_000":0.016785, "FB_UpperLip_000":0.043276, "IK_L_Foot":0.053754, "IK_L_Hand":0.048288, "IK_R_Foot":0.053754, "IK_R_Hand":0.048288, "PH_L_Foot":0.053754, "PH_L_Hand":0.048288, "PH_R_Foot":0.053754, "PH_R_Hand":0.048288, "RB_L_ForeArmRoll":0.114931, "RB_L_ThighRoll":0.066799, "RB_Neck_1":0.03759, "RB_R_ForeArmRoll":0.114931, "RB_R_ThighRoll":0.066799, "SKEL_Head":0.07518, "SKEL_L_Calf":0.24319, "SKEL_L_Clavicle":0.061696, "SKEL_L_Finger00":0.016255, "SKEL_L_Finger01":0.033021, "SKEL_L_Finger02":0.021189, "SKEL_L_Finger10":0.098532, "SKEL_L_Finger11":0.025142, "SKEL_L_Finger12":0.01728, "SKEL_L_Finger20":0.095271, "SKEL_L_Finger21":0.025692, "SKEL_L_Finger22":0.01709, "SKEL_L_Finger30":0.088448, "SKEL_L_Finger31":0.025506, "SKEL_L_Finger32":0.013301, "SKEL_L_Finger40":0.080971, "SKEL_L_Finger41":0.02529, "SKEL_L_Finger42":0.012458, "SKEL_L_Foot":0.196541, "SKEL_L_Forearm":0.222995, "SKEL_L_Hand":0.229862, "SKEL_L_Thigh":0.066799, "SKEL_L_Toe0":0.100959, "SKEL_L_UpperArm":0.088914, "SKEL_Neck_1":0.080047, "SKEL_R_Calf":0.24319, "SKEL_R_Clavicle":0.061696, "SKEL_R_Finger00":0.016255, "SKEL_R_Finger01":0.033021, "SKEL_R_Finger02":0.021189, "SKEL_R_Finger10":0.098532, "SKEL_R_Finger11":0.025141, "SKEL_R_Finger12":0.01728, "SKEL_R_Finger20":0.095271, "SKEL_R_Finger21":0.025692, "SKEL_R_Finger22":0.017089, "SKEL_R_Finger30":0.088447, "SKEL_R_Finger31":0.025506, "SKEL_R_Finger32":0.013303, "SKEL_R_Finger40":0.080969, "SKEL_R_Finger41":0.025291, "SKEL_R_Finger42":0.012458, "SKEL_R_Foot":0.196541, "SKEL_R_Forearm":0.222995, "SKEL_R_Hand":0.229862, "SKEL_R_Thigh":0.066799, "SKEL_R_Toe0":0.100959, "SKEL_R_UpperArm":0.088914, "SKEL_Spine1":0.072811, "SKEL_Spine2":0.064389, "SKEL_Spine3":0.072753},
    "a_c_rottweiler": {"FB_Brow_Centre_000":0.106603, "FB_Jaw_000":0.12228, "FB_L_Brow_Out_000":0.119372, "FB_L_CheekBone_000":0.275004, "FB_L_Ear_000":0.062354, "FB_L_Eye_000":0.161604, "FB_L_Lid_Upper_000":0.163105, "FB_L_Lip_Bot_000":-0.055357, "FB_L_Lip_Corner_000":0.136232, "FB_L_Lip_Top_000":0.02841, "FB_LowerLipRoot_000":0.00764, "FB_LowerLip_000":0.104229, "FB_R_Brow_Out_000":0.119371, "FB_R_CheekBone_000":0.275003, "FB_R_Ear_000":0.062354, "FB_R_Eye_000":0.161604, "FB_R_Lid_Upper_000":0.163103, "FB_R_Lip_Bot_000":-0.055356, "FB_R_Lip_Corner_000":0.136231, "FB_R_Lip_Top_000":0.02841, "FB_TongueA_000":0.125685, "FB_TongueB_000":0.037119, "FB_TongueC_000":0.026509, "FB_UpperLipRoot_000":0.156192, "FB_UpperLip_000":0.114318, "IK_L_Foot":0.023017, "IK_L_Hand":0.022382, "IK_R_Foot":0.023017, "IK_R_Hand":0.022382, "PH_L_Foot":0.023017, "PH_L_Hand":0.022382, "PH_R_Foot":0.023017, "PH_R_Hand":0.022382, "SKEL_Head":0.0512, "SKEL_L_Calf":0.193324, "SKEL_L_Clavicle":0.003386, "SKEL_L_Finger00":0.090238, "SKEL_L_Finger01":0.034649, "SKEL_L_Foot":0.198544, "SKEL_L_Forearm":0.138202, "SKEL_L_Hand":0.206576, "SKEL_L_Thigh":0.139635, "SKEL_L_Toe0":0.184703, "SKEL_L_Toe1":0.036926, "SKEL_L_UpperArm":0.183114, "SKEL_Neck_1":0.055221, "SKEL_Neck_2":0.039543, "SKEL_Pelvis":0.090076, "SKEL_Pelvis1":0.113437, "SKEL_PelvisRoot":0.124949, "SKEL_R_Calf":0.193324, "SKEL_R_Clavicle":0.003386, "SKEL_R_Finger00":0.090238, "SKEL_R_Finger01":0.034649, "SKEL_R_Foot":0.198544, "SKEL_R_Forearm":0.138201, "SKEL_R_Hand":0.206576, "SKEL_R_Thigh":0.139635, "SKEL_R_Toe0":0.184703, "SKEL_R_Toe1":0.036926, "SKEL_R_UpperArm":0.183114, "SKEL_Spine0":0.124949, "SKEL_Spine1":0.165231, "SKEL_Spine2":0.047982, "SKEL_Spine3":0.047637, "SKEL_Tail_01":0.079127, "SKEL_Tail_02":0.149595, "SKEL_Tail_03":0.072884, "SKEL_Tail_04":0.046875, "SKEL_Tail_05":0.04696, "SPR_Gonads_ROOT":0.135971, "SPR_L_Ear":0.013583, "SPR_R_Ear":0.013721},
    "a_c_seagull": {"FB_Jaw_000":0.036726, "IK_L_Foot":0.011243, "IK_L_Hand":0.08599, "IK_R_Foot":0.011243, "IK_R_Hand":0.085672, "MH_L_WingPusherInnerROOT":0.10419, "MH_L_WingRotator":0.195586, "MH_R_WingPusherInnerROOT":0.104226, "MH_R_WingRotator":0.195585, "PH_L_Foot":0.011243, "PH_L_Hand":0.08599, "PH_R_Foot":0.011243, "PH_R_Hand":0.085672, "SKEL_Head":0.058183, "SKEL_L_Calf":0.098389, "SKEL_L_Clavicle":-0.037268, "SKEL_L_Finger00":0.193778, "SKEL_L_Foot":0.075481, "SKEL_L_Forearm":0.171428, "SKEL_L_Hand":0.195586, "SKEL_L_Thigh":0.037482, "SKEL_L_Toe0":0.06462, "SKEL_L_UpperArm":0.07397, "SKEL_Neck_1":0.02678, "SKEL_R_Calf":0.098389, "SKEL_R_Clavicle":-0.037268, "SKEL_R_Finger00":0.193777, "SKEL_R_Foot":0.075481, "SKEL_R_Forearm":0.171428, "SKEL_R_Hand":0.195586, "SKEL_R_Thigh":0.037482, "SKEL_R_Toe0":0.06462, "SKEL_R_UpperArm":0.07397, "SKEL_Spine0":0.024245, "SKEL_Spine1":0.024914, "SKEL_Spine2":0.030136, "SKEL_Spine3":0.037216, "SKEL_Tail_01":0.021785, "SKEL_Tail_02":0.047494},
    "a_c_sharkhammer": {"FB_Jaw_000":0.025744, "SKEL_Head":0.409424, "SKEL_L_Clavicle":0.159563, "SKEL_L_Thigh":0.420931, "SKEL_R_Clavicle":0.161363, "SKEL_R_Thigh":0.420932, "SKEL_Spine1":0.399517, "SKEL_Tail_01":0.369776, "SKEL_Tail_02":0.525604, "SKEL_Tail_03":0.463203, "SKEL_Tail_04":0.334264, "SKEL_Tail_05":0.364117, "SKEL_Tail_07":0.368006},
    "a_c_sharktiger": {"FB_Jaw_000":-0.266985, "SKEL_Head":0.409424, "SKEL_L_Clavicle":0.159563, "SKEL_L_Thigh":0.420931, "SKEL_R_Clavicle":0.161363, "SKEL_R_Thigh":0.420932, "SKEL_Spine1":0.399517, "SKEL_Tail_01":0.369776, "SKEL_Tail_02":0.525604, "SKEL_Tail_03":0.463203, "SKEL_Tail_04":0.334264, "SKEL_Tail_05":0.364117, "SKEL_Tail_07":0.368006},
    "a_c_shepherd": {"FB_Brow_Centre_000":0.068245, "FB_Jaw_000":0.08153, "FB_L_Brow_Out_000":0.074349, "FB_L_CheekBone_000":0.164307, "FB_L_Ear_000":0.049701, "FB_L_Eye_000":0.117204, "FB_L_Lid_Upper_000":0.117102, "FB_L_Lip_Bot_000":-0.037087, "FB_L_Lip_Corner_000":0.130332, "FB_L_Lip_Top_000":0.018677, "FB_LowerLipRoot_000":0.072015, "FB_LowerLip_000":0.074971, "FB_R_Brow_Out_000":0.07435, "FB_R_CheekBone_000":0.164306, "FB_R_Ear_000":0.049697, "FB_R_Eye_000":0.117201, "FB_R_Lid_Upper_000":0.1171, "FB_R_Lip_Bot_000":-0.037087, "FB_R_Lip_Corner_000":0.130331, "FB_R_Lip_Top_000":0.018677, "FB_TongueA_000":0.113096, "FB_TongueB_000":0.028066, "FB_TongueC_000":0.036123, "FB_UpperLipRoot_000":0.137012, "FB_UpperLip_000":0.098689, "IK_L_Foot":0.023017, "IK_L_Hand":0.022382, "IK_R_Foot":0.023017, "IK_R_Hand":0.022382, "PH_L_Foot":0.023017, "PH_L_Hand":0.022382, "PH_R_Foot":0.023017, "PH_R_Hand":0.022382, "SKEL_Head":0.0512, "SKEL_L_Calf":0.193324, "SKEL_L_Clavicle":0.003386, "SKEL_L_Finger00":0.090238, "SKEL_L_Finger01":0.034649, "SKEL_L_Foot":0.198544, "SKEL_L_Forearm":0.138202, "SKEL_L_Hand":0.206576, "SKEL_L_Thigh":0.139635, "SKEL_L_Toe0":0.184703, "SKEL_L_Toe1":0.036926, "SKEL_L_UpperArm":0.183114, "SKEL_Neck_1":0.055221, "SKEL_Neck_2":0.039543, "SKEL_Pelvis":0.090076, "SKEL_Pelvis1":0.113437, "SKEL_PelvisRoot":0.124949, "SKEL_R_Calf":0.193324, "SKEL_R_Clavicle":0.003386, "SKEL_R_Finger00":0.090238, "SKEL_R_Finger01":0.034649, "SKEL_R_Foot":0.198544, "SKEL_R_Forearm":0.138201, "SKEL_R_Hand":0.206576, "SKEL_R_Thigh":0.139635, "SKEL_R_Toe0":0.184703, "SKEL_R_Toe1":0.036926, "SKEL_R_UpperArm":0.183114, "SKEL_Spine0":0.124949, "SKEL_Spine1":0.165231, "SKEL_Spine2":0.047982, "SKEL_Spine3":0.047637, "SKEL_Tail_01":0.079127, "SKEL_Tail_02":0.149595, "SKEL_Tail_03":0.072884, "SKEL_Tail_04":0.046875, "SKEL_Tail_05":0.04696},
    "a_c_stingray": {"SKEL_Head":0.17364, "SKEL_L_AFin_00":0.001991, "SKEL_L_AFin_01":0.160811, "SKEL_L_AFin_02":0.138982, "SKEL_L_BFin_00":0.131972, "SKEL_L_BFin_01":0.140584, "SKEL_L_BFin_02":0.112196, "SKEL_L_CFin_00":-0.01985, "SKEL_L_CFin_01":0.112165, "SKEL_L_FrontFin":-0.066972, "SKEL_L_RearFin":-0.153986, "SKEL_R_AFin_00":0.005933, "SKEL_R_AFin_01":0.160811, "SKEL_R_AFin_02":0.138982, "SKEL_R_BFin_00":0.12911, "SKEL_R_BFin_01":0.140584, "SKEL_R_BFin_02":0.112196, "SKEL_R_CFin_00":-0.022595, "SKEL_R_CFin_01":0.112165, "SKEL_R_FrontFin":-0.069494, "SKEL_R_RearFin":-0.155504, "SKEL_Spine0":0.27836, "SKEL_Spine1":0.206924, "SKEL_Tail0":-0.248387, "SKEL_Tail1":0.344366, "SKEL_Tail2":0.295933, "SKEL_Tail3":0.276466},
    "a_c_westy": {"FB_Jaw_000":0.060338, "FB_L_Ear_000":0.002074, "FB_L_Eye_000":0.077332, "FB_L_Lid_Upper_000":0.077332, "FB_R_Ear_000":0.002075, "FB_R_Eye_000":0.077333, "FB_R_Lid_Upper_000":0.077333, "FB_TongueA_000":0.015874, "FB_TongueB_000":0.025914, "FB_TongueC_000":0.01921, "IK_L_Foot":0.019646, "IK_L_Hand":0.007472, "IK_R_Foot":0.019646, "IK_R_Hand":0.007472, "PH_L_Foot":0.019646, "PH_L_Hand":0.007472, "PH_R_Foot":0.019646, "PH_R_Hand":0.007472, "SKEL_Head":0.03921, "SKEL_L_Calf":0.117641, "SKEL_L_Clavicle":0.005515, "SKEL_L_Finger00":0.03546, "SKEL_L_Finger01":0.02076, "SKEL_L_Foot":0.109341, "SKEL_L_Forearm":0.089773, "SKEL_L_Hand":0.148047, "SKEL_L_Thigh":-0.030042, "SKEL_L_Toe0":0.104227, "SKEL_L_Toe1":0.031266, "SKEL_L_UpperArm":0.102422, "SKEL_Neck0":0.066564, "SKEL_Neck1":0.055646, "SKEL_Neck2":0.051887, "SKEL_R_Calf":0.117641, "SKEL_R_Clavicle":0.005515, "SKEL_R_Finger00":0.03546, "SKEL_R_Finger01":0.02076, "SKEL_R_Foot":0.109341, "SKEL_R_Forearm":0.089773, "SKEL_R_Hand":0.148047, "SKEL_R_Thigh":-0.030041, "SKEL_R_Toe0":0.104227, "SKEL_R_Toe1":0.031266, "SKEL_R_UpperArm":0.102422, "SKEL_Spine0":0.056, "SKEL_Spine1":0.058816, "SKEL_Spine2":0.061449, "SKEL_Spine3":0.06208, "SKEL_Tail0":-0.068485, "SKEL_Tail1":0.066301, "SKEL_Tail2":0.055733, "SPR_BellyFur":0.083631, "SPR_R_ChinFur":0.108943},
    "a_c_whalegrey": {"FB_Jaw_000":0.547572, "SKEL_BackFin_00":0.164276, "SKEL_BackFin_01":0.994671, "SKEL_Head":-0.007552, "SKEL_L_Fin_00":-0.805849, "SKEL_L_TailFin_00":0.21523, "SKEL_L_TailFin_02":0.699943, "SKEL_Pelvis":-0.005335, "SKEL_R_Fin_00":0.808959, "SKEL_R_TailFin_00":0.21523, "SKEL_R_TailFin_02":0.699948, "SKEL_Tail_00":0.789571, "SKEL_Tail_01":0.843854, "SKEL_Tail_02":1.01123, "SKEL_Tail_03":0.852459, "SKEL_Tail_04":1.159896, "SKEL_Tail_05":1.034551, "SKEL_Tail_06":1.295694, "SKEL_Tail_07":1.34072},
    "a_m_m_skater_01": {"FB_Brow_Centre_001":0.060751, "FB_Jaw_001":0.012803, "FB_L_Brow_Out_001":0.087966, "FB_L_CheekBone_001":0.052376, "FB_L_Eye_001":0.066857, "FB_L_Lid_Upper_001":0.066857, "FB_L_Lip_Bot_001":0.008331, "FB_L_Lip_Corner_001":-0.016083, "FB_L_Lip_Top_001":0.01289, "FB_LowerLipRoot_001":0.075918, "FB_LowerLip_001":0.031887, "FB_R_Brow_Out_001":0.087968, "FB_R_CheekBone_001":0.052376, "FB_R_Eye_001":0.066602, "FB_R_Lid_Upper_001":0.066602, "FB_R_Lip_Bot_001":0.008331, "FB_R_Lip_Corner_001":-0.015381, "FB_R_Lip_Top_001":0.01289, "FB_Tongue_001":-0.015743, "FB_UpperLipRoot_001":0.005357, "FB_UpperLip_001":0.050238, "IK_L_Foot":0.102055, "IK_L_Hand":0.054434, "IK_R_Foot":0.102055, "IK_R_Hand":0.054435, "MH_Hair_Scale":0.093063, "MH_L_Elbow":0.275, "MH_L_Knee":0.4, "MH_R_Elbow":0.275, "MH_R_Knee":0.4, "PH_L_Foot":0.102055, "PH_L_Hand":0.054434, "PH_R_Foot":0.102055, "PH_R_Hand":0.054435, "RB_L_ForeArmRoll":0.129598, "RB_L_ThighRoll":0.073508, "RB_Neck_1":0.056537, "RB_R_ForeArmRoll":0.129598, "RB_R_ThighRoll":0.073508, "SKEL_Head":0.113076, "SKEL_L_Calf":0.406518, "SKEL_L_Clavicle":0.218041, "SKEL_L_Finger00":0.025858, "SKEL_L_Finger01":0.056322, "SKEL_L_Finger02":0.035984, "SKEL_L_Finger10":0.106708, "SKEL_L_Finger11":0.047289, "SKEL_L_Finger12":0.024109, "SKEL_L_Finger20":0.106343, "SKEL_L_Finger21":0.051797, "SKEL_L_Finger22":0.032839, "SKEL_L_Finger30":0.100143, "SKEL_L_Finger31":0.044589, "SKEL_L_Finger32":0.030654, "SKEL_L_Finger40":0.093704, "SKEL_L_Finger41":0.038221, "SKEL_L_Finger42":0.022898, "SKEL_L_Foot":0.41297, "SKEL_L_Forearm":0.274172, "SKEL_L_Hand":0.259194, "SKEL_L_Thigh":0.073508, "SKEL_L_Toe0":0.161524, "SKEL_L_UpperArm":0.181895, "SKEL_Neck_1":0.2485, "SKEL_R_Calf":0.406518, "SKEL_R_Clavicle":0.218041, "SKEL_R_Finger00":0.025859, "SKEL_R_Finger01":0.056322, "SKEL_R_Finger02":0.035984, "SKEL_R_Finger10":0.106709, "SKEL_R_Finger11":0.04729, "SKEL_R_Finger12":0.024109, "SKEL_R_Finger20":0.106344, "SKEL_R_Finger21":0.051797, "SKEL_R_Finger22":0.032839, "SKEL_R_Finger30":0.100144, "SKEL_R_Finger31":0.044589, "SKEL_R_Finger32":0.030654, "SKEL_R_Finger40":0.093704, "SKEL_R_Finger41":0.038221, "SKEL_R_Finger42":0.022898, "SKEL_R_Foot":0.41297, "SKEL_R_Forearm":0.274172, "SKEL_R_Hand":0.259194, "SKEL_R_Thigh":0.073508, "SKEL_R_Toe0":0.161524, "SKEL_R_UpperArm":0.181896, "SKEL_Spine0":0.018706, "SKEL_Spine1":0.084855, "SKEL_Spine2":0.085922, "SKEL_Spine3":0.112895},
    "u_m_y_abner": {"FB_Brow_Centre_000":0.052544, "FB_Jaw_000":0.010333, "FB_L_Brow_Out_000":0.074407, "FB_L_CheekBone_000":0.046303, "FB_L_Eye_000":0.063354, "FB_L_Lid_Upper_000":0.063354, "FB_L_Lip_Bot_000":0.005352, "FB_L_Lip_Corner_000":-0.015453, "FB_L_Lip_Top_000":0.009683, "FB_LowerLipRoot_000":0.060902, "FB_LowerLip_000":0.037918, "FB_R_Brow_Out_000":0.074408, "FB_R_CheekBone_000":0.046301, "FB_R_Eye_000":0.063156, "FB_R_Lid_Upper_000":0.063155, "FB_R_Lip_Bot_000":0.005356, "FB_R_Lip_Corner_000":-0.014544, "FB_R_Lip_Top_000":0.009684, "FB_Tongue_000":-0.006296, "FB_UpperLipRoot_000":0.003512, "FB_UpperLip_000":0.041977, "IK_L_Foot":0.101686, "IK_L_Hand":0.054434, "IK_R_Foot":0.101686, "IK_R_Hand":0.054435, "MH_L_Elbow":0.275, "MH_L_Knee":0.4, "MH_R_Elbow":0.275, "MH_R_Knee":0.4, "PH_L_Foot":0.101686, "PH_L_Hand":0.054434, "PH_R_Foot":0.101686, "PH_R_Hand":0.054435, "RB_L_ForeArmRoll":0.129598, "RB_L_ThighRoll":0.073508, "RB_Neck_1":0.056537, "RB_R_ForeArmRoll":0.129598, "RB_R_ThighRoll":0.073508, "SKEL_Head":0.113076, "SKEL_L_Calf":0.406518, "SKEL_L_Clavicle":0.21804, "SKEL_L_Finger00":0.025858, "SKEL_L_Finger01":0.056322, "SKEL_L_Finger02":0.035984, "SKEL_L_Finger10":0.106709, "SKEL_L_Finger11":0.047289, "SKEL_L_Finger12":0.024108, "SKEL_L_Finger20":0.106344, "SKEL_L_Finger21":0.051797, "SKEL_L_Finger22":0.032839, "SKEL_L_Finger30":0.100143, "SKEL_L_Finger31":0.044589, "SKEL_L_Finger32":0.030654, "SKEL_L_Finger40":0.093704, "SKEL_L_Finger41":0.038221, "SKEL_L_Finger42":0.022897, "SKEL_L_Foot":0.41297, "SKEL_L_Forearm":0.274172, "SKEL_L_Hand":0.259194, "SKEL_L_Thigh":0.073508, "SKEL_L_Toe0":0.161524, "SKEL_L_UpperArm":0.181895, "SKEL_Neck_1":0.248499, "SKEL_R_Calf":0.406518, "SKEL_R_Clavicle":0.21804, "SKEL_R_Finger00":0.025859, "SKEL_R_Finger01":0.056322, "SKEL_R_Finger02":0.035984, "SKEL_R_Finger10":0.106708, "SKEL_R_Finger11":0.04729, "SKEL_R_Finger12":0.024108, "SKEL_R_Finger20":0.106344, "SKEL_R_Finger21":0.051797, "SKEL_R_Finger22":0.032839, "SKEL_R_Finger30":0.100144, "SKEL_R_Finger31":0.044589, "SKEL_R_Finger32":0.030654, "SKEL_R_Finger40":0.093704, "SKEL_R_Finger41":0.038221, "SKEL_R_Finger42":0.022898, "SKEL_R_Foot":0.41297, "SKEL_R_Forearm":0.274172, "SKEL_R_Hand":0.259194, "SKEL_R_Thigh":0.073508, "SKEL_R_Toe0":0.161524, "SKEL_R_UpperArm":0.181896, "SKEL_Spine0":0.018706, "SKEL_Spine1":0.084855, "SKEL_Spine2":0.085922, "SKEL_Spine3":0.112895},
}

# Tur basina rig bilgisi: SKEL_ROOT'un rotasyonu (quaternion x,y,z,w) ve
# dogrudan cocuklarinin 1.0 olcegindeki translation'lari.
#
# NEDEN GEREKLI: cocuk kemiklerin translation'i KOKUN BONE UZAYINDADIR.
# Insan pedinde kok 180 derece Z donmustur -> lokal Z = dunya Z, kaldirmayi
# z'ye yazmak ise yarar. a_c_boar'da kok 120 derece kosegen donmustur ->
# dunya Z, lokal X'e denk gelir; z'ye yazmak govdeyi YUKARI degil YANA iter.
# Ayrica cocuklarin dogal degeri her turde 0 degil (boar/SKEL_PelvisRoot
# 0.223008), o yuzden mutlak yazarken dogal deger bilinmek zorunda.
RIGS = {
    "a_c_boar": {"q": (-0.5001062, -0.4998937, -0.4999336, 0.5000663), "c": {"SKEL_PelvisRoot": (0.223008, -8.3e-05, -3.4e-05), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_cat_01": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_chickenhawk": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_chimp": {"q": (0.0, 0.0, -1.0, -2e-07), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_chop": {"q": (0.5016485, 0.5016575, 0.4983369, -0.4983459), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.124949, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_cormorant": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_cow": {"q": (-0.4181336, -0.4181337, -0.5702316, 0.5702318), "c": {"LookAtTarget": (-0.690175, 1e-06, -1.238149), "LookAtUpnode": (1.27946, 0.0, -0.617237), "SKEL_PelvisRoot": (0.181183, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_coyote": {"q": (0.5028338, 0.5028288, 0.497155, -0.4971501), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.070699, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_crow": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_deer": {"q": (-0.4531476, -0.4531473, -0.5428237, 0.5428233), "c": {"SKEL_PelvisRoot": (0.104809, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_dolphin": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"SKEL_Spine_Root": (0.0, 3e-05, 0.0)}},
    "a_c_fish": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_hen": {"q": (-0.4357028, -0.4357025, -0.5569232, 0.5569228), "c": {"SKEL_PelvisRoot": (0.007106, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_humpback": {"q": (0.0, 0.0, 1.0, -2e-07), "c": {"SKEL_Spine_Root": (0.0, -7e-05, 0.0)}},
    "a_c_husky": {"q": (-0.4951726, -0.4951707, -0.5047832, 0.5047812), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.135271, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_killerwhale": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"SKEL_Spine_Root": (0.0, 3e-05, 0.0)}},
    "a_c_mtlion": {"q": (-0.5003399, -0.4996599, -0.4996492, 0.5003505), "c": {"SKEL_PelvisRoot": (0.083277, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_pig": {"q": (-0.4995188, -0.499504, -0.5004955, 0.5004807), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.079971, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_pigeon": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_poodle": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_pug": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_rabbit_01": {"q": (0.0, 0.0, 1.0, -2e-07), "c": {"OH_FacingDir": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_rat": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_PelvisRoot": (0.0, 0.002461, 0.021389), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_retriever": {"q": (-0.4951726, -0.4951707, -0.5047832, 0.5047812), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.135271, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_rhesus": {"q": (0.0, 0.0, -1.0, -2e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_rottweiler": {"q": (0.5016485, 0.5016575, 0.4983369, -0.4983459), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.124949, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_seagull": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_sharkhammer": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_sharktiger": {"q": (0.0, 0.0, 0.0, 1.0), "c": {"SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_shepherd": {"q": (0.5016485, 0.5016575, 0.4983369, -0.4983459), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_PelvisRoot": (0.124949, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_stingray": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_westy": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "a_c_whalegrey": {"q": (0.0, 0.0, 1.0, 3e-07), "c": {"SKEL_Head": (-0.007552, 3.0516989, -0.005057), "SKEL_L_Fin_00": (-0.805849, 2.309804, -0.632477), "SKEL_Pelvis": (-0.005335, 3.0503089, -0.005194), "SKEL_R_Fin_00": (0.808959, 2.3098049, -0.632478), "SKEL_Spine_Root": (0.0, 0.373752, -0.477886)}},
    "a_m_m_skater_01": {"q": (0.0, 0.0, 1.0, -2e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
    "u_m_y_abner": {"q": (0.0, 0.0, 1.0, -2e-07), "c": {"IK_Root": (0.0, 0.0, 0.0), "SKEL_Pelvis": (0.0, 0.0, 0.0), "SKEL_Spine_Root": (0.0, 0.0, 0.0)}},
}

# Kemik oranlarinin kirpilmis yayilimi bunu asarsa eslesme guvenilmez.
# Olculen: dogru tur 0.000-0.020, en yakin yanlis aday 0.026+.
YAYILIM_SINIRI = 0.25
# muto (2026-09-13): muto-ped-rig ile rig'lenmis insan karakterlerinde yayilim 0,16 (1,4 m) / 0,25 (0,98 m) / 0,28 (2,4 m) / 0,35
# (Winter Soldier) / 0,55 (zombi 2,2 m) -> insan ailesinde sinir asilinca reddetmek yerine uyarilir (coz()).

PREVIEW_COLL = "__MUTO_PED_SCALE_ONIZLEME__"

# CodeWalker vertex verisini <Data> ya da <Data2> icinde yazabiliyor
# (VertexBuffer'in Data1/Data2 yuvalarindan hangisi doluysa). Ikisini de
# tanimazsak mesh hic olceklenmez -- iskelet buyur, mesh yerinde kalir.
DATA_AC = re.compile(r"^<Data\d*>")
DATA_KAPA = re.compile(r"^</Data\d*>")

VEC_TAGS = ("Translation", "BoundingBoxMin", "BoundingBoxMax",
            "BoundingSphereCenter", "CenterOfMass", "BoxMin", "BoxMax",
            "BoxCenter", "SphereCenter")     # muto: fizik bound merkezleri de (4.1'de yoktu)
VAL_TAGS = ("BoundingSphereRadius", "SphereRadius", "Margin")


def fmt(v):
    """CodeWalker 9 anlamli haneye kadar yaziyor; ayni bicimi koruyoruz."""
    s = "%.9g" % v
    return "0" if s in ("-0", "-0.0") else s


# ---------------------------------------------------------------------------
# Okuma / olcum
# ---------------------------------------------------------------------------
def read_skeleton(path):
    """{kemik adi: lokal X translation}. X uzunluk demek."""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    for sk in root.iter("Skeleton"):
        out = {}
        for it in sk.findall("./Bones/Item"):
            nm = it.findtext("Name")
            tr = it.find("Translation")
            if nm and tr is not None:
                out[nm] = float(tr.get("x", 0))
        if out:
            return out
    return None


def identify(bones):
    """Turu ve mevcut olcegi birlikte bulur.

    Her tur icin ortak kemiklerin oranlari cikarilir. Dogru turde bu
    oranlarin hepsi ayni sayiya yakinsar (yayilim ~0); yanlis turde
    dagilir. En dusuk yayilimli tur kazanir, oranlarin medyani olcektir."""
    if not bones:
        return None
    ad = {k: v for k, v in bones.items() if abs(v) > 0.001}
    en_iyi = None
    for tur, ref in SKELETONS.items():
        ortak = [n for n in ref if n in ad]
        if len(ortak) < 8:
            continue
        rat = sorted(ad[n] / ref[n] for n in ortak)
        # uc %10 kirpilir: tek tuhaf kemik sonucu bozmasin
        k = max(1, len(rat) // 10)
        ic = rat[k:-k] if len(rat) > 2 * k else rat
        aday = {"tur": tur, "scale": statistics.median(rat),
                "spread": max(ic) - min(ic), "n": len(ortak),
                "kapsama": len(ortak) / float(max(len(ref), len(ad)))}
        if en_iyi is None or aday["spread"] < en_iyi["spread"]:
            en_iyi = aday
    return en_iyi


def read_root_z(path):
    """SKEL_ROOT'un Translation z'si."""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    for sk in root.iter("Skeleton"):
        for it in sk.findall("./Bones/Item"):
            if it.findtext("Name") == "SKEL_ROOT":
                tr = it.find("Translation")
                if tr is not None:
                    return float(tr.get("z", 0))
    return None


def read_child_z(path):
    """SKEL_ROOT'un ilk cocugunun Translation z'si = mevcut kaldirma."""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    for sk in root.iter("Skeleton"):
        for it in sk.findall("./Bones/Item"):
            pi = it.find("ParentIndex")
            if pi is not None and pi.get("value") == "0":
                tr = it.find("Translation")
                if tr is not None:
                    return float(tr.get("z", 0))
    return None


def measure_sole(ydd_path):
    """Model uzayindaki en dusuk vertex Z'si. Sollumz importuyla
       dogrulandi: dosya Z'si ile Blender Z'si birebir."""
    zmin = None
    in_vb = in_data = False
    with open(ydd_path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.startswith("<VertexBuffer"):
                in_vb = True; continue
            if s.startswith("<IndexBuffer"):
                in_vb = False; continue
            if DATA_AC.match(s):
                in_data = in_vb; continue
            if DATA_KAPA.match(s):
                in_data = False; continue
            if in_data and s:
                parts = s.split(None, 3)
                if len(parts) >= 3:
                    try:
                        z = float(parts[2])
                    except ValueError:
                        continue
                    if zmin is None or z < zmin:
                        zmin = z
    return zmin


def measure_sole_all(ydds):
    """Tum bilesenlerin en dusuk noktasi = pedin gercek tabani."""
    vals = [z for z in (measure_sole(f) for f in ydds) if z is not None]
    return min(vals) if vals else None


# ---------------------------------------------------------------------------
# Yazma
# ---------------------------------------------------------------------------
def scale_file(path, k, do_vertices, backup):
    """Satir bazli olcekler; dokunulmayan her karakter byte-byte korunur.
       XML yeniden serilestirilmez -- CodeWalker'in bicimi aynen kalir."""
    if backup:
        bak = path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)

    in_vb = in_data = False
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            s = raw.strip()

            if do_vertices:
                if s.startswith("<VertexBuffer"):
                    in_vb = True
                elif s.startswith("<IndexBuffer"):
                    in_vb = False
                elif DATA_AC.match(s):
                    in_data = in_vb
                    out.append(raw); continue
                elif DATA_KAPA.match(s):
                    in_data = False
                    out.append(raw); continue

                if in_data and s:
                    # SADECE ilk 3 sayi (Position). Ayiricilar aynen kalir.
                    m = re.match(r'^(\s*)(\S+)(\s+)(\S+)(\s+)(\S+)(.*)$', raw)
                    if m:
                        g = m.groups()
                        try:
                            x, y, z = float(g[1]), float(g[3]), float(g[5])
                        except ValueError:
                            out.append(raw); continue
                        out.append("%s%s%s%s%s%s%s" % (
                            g[0], fmt(x * k), g[2], fmt(y * k),
                            g[4], fmt(z * k), g[6]))
                        continue
                    out.append(raw); continue

            tag = s[1:].split()[0].rstrip("/>") if (s.startswith("<") and len(s) > 1) else ""
            if tag in VEC_TAGS:
                new = raw
                for key in ("x", "y", "z"):
                    new = re.sub(r'\b(%s)="([-0-9.eE+]+)"' % key,
                                 lambda m: '%s="%s"' % (m.group(1), fmt(float(m.group(2)) * k)),
                                 new)
                out.append(new); continue
            if tag in VAL_TAGS:
                out.append(re.sub(r'\b(value)="([-0-9.eE+]+)"',
                                  lambda m: '%s="%s"' % (m.group(1), fmt(float(m.group(2)) * k)),
                                  raw))
                continue
            out.append(raw)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def shift_mesh_z(ydd_path, dz):
    """Mesh'i dikeyde kaydirir: vertex Z'leri + drawable bounding kutulari.
       Kemik <Translation>'larina DOKUNMAZ -- onlar yft ile eslesmeli."""
    in_vb = in_data = False
    out = []
    with open(ydd_path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            s = raw.strip()

            if s.startswith("<VertexBuffer"):
                in_vb = True
            elif s.startswith("<IndexBuffer"):
                in_vb = False
            elif DATA_AC.match(s):
                in_data = in_vb
                out.append(raw); continue
            elif DATA_KAPA.match(s):
                in_data = False
                out.append(raw); continue

            if in_data and s:
                m = re.match(r'^(\s*)(\S+)(\s+)(\S+)(\s+)(\S+)(.*)$', raw)
                if m:
                    g = m.groups()
                    try:
                        z = float(g[5])
                    except ValueError:
                        out.append(raw); continue
                    out.append("%s%s%s%s%s%s%s" % (
                        g[0], g[1], g[2], g[3], g[4], fmt(z + dz), g[6]))
                    continue
                out.append(raw); continue

            tag = s[1:].split()[0].rstrip("/>") if (s.startswith("<") and len(s) > 1) else ""
            if tag in ("BoundingBoxMin", "BoundingBoxMax", "BoundingSphereCenter"):
                out.append(re.sub(r'\bz="([-0-9.eE+]+)"',
                                  lambda m: 'z="%s"' % fmt(float(m.group(1)) + dz),
                                  raw))
                continue
            out.append(raw)

    with open(ydd_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")


def _bone_z(path, secici, value):
    """Iskeletteki secili kemiklerin Translation z'sini mutlak yazar."""
    out = []
    in_bones = False
    isaretli = False
    ad = None
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            s = raw.strip()
            if s.startswith("<Bones>"):
                in_bones = True
            elif s.startswith("</Bones>"):
                in_bones = False
            elif in_bones:
                if s.startswith("<Item"):
                    isaretli = False; ad = None
                elif s.startswith("<Name>"):
                    ad = s[6:-7]
                    if secici == "root" and ad == "SKEL_ROOT":
                        isaretli = True
                elif s.startswith("<ParentIndex") and 'value="0"' in s:
                    if secici == "children":
                        isaretli = True
                elif isaretli and s.startswith("<Translation"):
                    raw = re.sub(r'\bz="([-0-9.eE+]+)"', 'z="%s"' % fmt(value), raw)
                    isaretli = False
                    n += 1
            out.append(raw)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return n


def set_root_z(path, value):
    return _bone_z(path, "root", value)


def kaldirma_ekseni(q_xyzw):
    """Dunya +Z'nin SKEL_ROOT'un lokal uzayindaki karsiligi (birim vektor).

    Cocuklarin translation'i kokun bone uzayinda oldugu icin kaldirmayi
    dogru eksene yazmak sart. Insan: (0,0,1). a_c_boar: (1,0,0)."""
    x, y, z, w = q_xyzw
    v = Quaternion((w, x, y, z)).inverted() @ Vector((0.0, 0.0, 1.0))
    return v.normalized()


def read_root_children(path):
    """{kemik adi: (x,y,z)} -- SKEL_ROOT'un dogrudan cocuklari."""
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}
    for sk in root.iter("Skeleton"):
        its = sk.findall("./Bones/Item")
        if not its:
            continue
        out = {}
        for it in its:
            pi = it.find("ParentIndex")
            tr = it.find("Translation")
            if pi is not None and pi.get("value") == "0" and tr is not None:
                out[it.findtext("Name")] = (float(tr.get("x", 0)),
                                            float(tr.get("y", 0)),
                                            float(tr.get("z", 0)))
        return out
    return {}


def set_root_children_t(path, hedefler):
    """SKEL_ROOT cocuklarinin Translation'ini mutlak yazar.
       hedefler: {kemik adi: (x, y, z)}. Isin kalbi -- modul basligina bak."""
    out = []
    in_bones = False
    ad = None
    cocuk = False
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            s = raw.strip()
            if s.startswith("<Bones>"):
                in_bones = True
            elif s.startswith("</Bones>"):
                in_bones = False
            elif in_bones:
                if s.startswith("<Item"):
                    ad = None
                    cocuk = False
                elif s.startswith("<Name>") and s.endswith("</Name>"):
                    ad = s[6:-7]
                elif s.startswith("<ParentIndex") and 'value="0"' in s:
                    cocuk = True
                elif cocuk and s.startswith("<Translation"):
                    t = hedefler.get(ad)
                    if t is not None:
                        for eksen, deger in zip("xyz", t):
                            raw = re.sub(r'\b%s="[-0-9.eE+]+"' % eksen,
                                         '%s="%s"' % (eksen, fmt(deger)), raw)
                        n += 1
                    cocuk = False
            out.append(raw)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return n


# ---------------------------------------------------------------------------
# muto: uyarilar, BoneTransforms, hayvan fizigi (muto-ped-rig olcumleri 2026-09-13)
# ---------------------------------------------------------------------------
INSAN_TURLERI = tuple(t for t in RIGS if not t.startswith("a_c_"))
# vanilla insan taban -> SKEL_ROOT (muto-ped-rig freemode sablonu, atlas iskelet.md Kural 4; hipster dosyadan 0,9876)
INSAN_H0 = 0.983


def h0_referans(d):
    """Olcekten sonra korunacak taban - kok mesafesi (tur boyunda). Vanilla oranli dosyada (yayilim <= 0,02) dosyanin kendi H0'i;
    ozel oranli insan iskeletinde vanilla insan degeri (dosyadan H0 legen yuksekligini kemik oranina boldugu icin sapar)."""
    if d.get("muto") and d["tur"] in INSAN_TURLERI and d["spread"] > 0.02:
        return INSAN_H0
    return d["h0"]                                  # mairon 4.1: kaldirma = H0*hedef - H0 = H0*(hedef-1)
HAYVAN_KONUM_IZI = "SKEL_ROOT, Spine_Root, Spine0, PelvisRoot, Pelvis, Thigh, UpperArm, Forearm, Hand, Finger00, Tail_01"
_SAYI = re.compile(r"^(\s*)([-+0-9.].*)$")


def ydd_ayni_adlar(ydds):
    """Ayni adi tasiyan fazla cizim sayisi. CodeWalker adi cozemeyince sozlukteki cizimlerin hepsi '<ped>.#dd' yazilir; Sollumz import'u
    ayni adlilari birlestirir, yalniz sonuncusu gelir (olculdu 2026-09-13: a_m_y_hipster_01 11 cizim -> 1 mesh)."""
    fazla = 0
    for f in ydds:
        try:
            adlar = [it.findtext("Name") for it in ET.parse(f).getroot().findall("Item")]
        except Exception:
            continue
        fazla += len(adlar) - len(set(adlar))
    return fazla


def notlar(d):
    """Rapora eklenecek uyarilar (bos = yok)."""
    s = ""
    if d.get("ozel"):
        s += "  |  ozel oranli insan iskeleti (yayilim %.2f): olcek = kemik orani medyani" % d["spread"]
    elif d["tur"] in INSAN_TURLERI and d["spread"] > 0.02:
        if d.get("muto"):
            s += "  |  vanilla disi oran (yayilim %.2f): zemin vanilla insan H0 %.3f ile (muto duzeltmesi)" % (d["spread"], INSAN_H0)
        else:
            s += "  |  vanilla disi oran (yayilim %.2f): mairon zemini; gomulme gorursen 'Muto zemin duzeltmesi'ni ac" % d["spread"]
    if d["tur"].startswith("a_c_"):
        s += ("  |  UYARI hayvan: klipler %s konumunu yazar -> kaldirma oyunda ezilir, bacaklar vanilla boya zorlanir"
              % HAYVAN_KONUM_IZI)
    return s


def iskelet_dunya(path):
    """.yft.xml iskeleti -> {"ad": [...], "W": (B,4,4) model uzayi (sutun-vektor), "tag": {tag: indeks}} ya da None."""
    import numpy as np
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    for sk in root.iter("Skeleton"):
        its = sk.findall("./Bones/Item")
        if not its:
            continue
        W, ad, tag = [], [], {}
        for i, it in enumerate(its):
            p = int(it.find("ParentIndex").get("value"))
            r = it.find("Rotation")
            q = Quaternion((float(r.get("w", 1)), float(r.get("x", 0)), float(r.get("y", 0)), float(r.get("z", 0))))
            M = np.eye(4)
            M[:3, :3] = np.array(q.to_matrix())
            sc = it.find("Scale")
            if sc is not None:
                M[:3, :3] = M[:3, :3] @ np.diag([float(sc.get(k, 1)) for k in "xyz"])
            t = it.find("Translation")
            M[:3, 3] = [float(t.get(k, 0)) for k in "xyz"]
            W.append(M if p < 0 else W[p] @ M)
            ad.append(it.findtext("Name"))
            tg = it.find("Tag")
            if tg is not None:
                tag[int(tg.get("value"))] = i
        return {"ad": ad, "W": np.array(W), "tag": tag}
    return None


def rebuild_bone_transforms(path, isk):
    """<BoneTransforms> DOLUYSA her kalemi son iskeletin model uzayi matrisiyle yazar (3 satir: R satiri + oteleme); sifirsa (vanilla)
    dokunmaz. Satir bazli, bicim korunur. Donus: yazilan kalem sayisi."""
    lines = open(path, "r", encoding="utf-8").read().split("\n")
    a = next((i for i, l in enumerate(lines) if l.strip().startswith("<BoneTransforms")), None)
    if a is None or isk is None or lines[a].strip().endswith("/>"):
        return 0
    b = next((i for i in range(a + 1, len(lines)) if lines[i].strip().startswith("</BoneTransforms")), None)
    if b is None:
        return 0
    dolu = any(abs(float(x)) > 1e-9 for l in lines[a + 1:b] if _SAYI.match(l) for x in l.split())
    if not dolu:
        return 0
    item, row, n = -1, 0, 0
    W = isk["W"]
    for i in range(a + 1, b):
        st = lines[i].strip()
        if st.startswith("<Item"):
            item += 1
            row = 0
            continue
        m = _SAYI.match(lines[i])
        if m and 0 <= item < len(W) and row < 3:
            M = W[item]
            lines[i] = m.group(1) + " ".join(fmt(v) for v in (M[row, 0], M[row, 1], M[row, 2], M[row, 3]))
            row += 1
            if row == 3:
                n += 1
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return n


def fizik_oku(path):
    """Physics/LOD1 varsa [(BoneTag, 4x4 sutun-vektor CompositeTransform)] (bound cocuk sirasi); yoksa []."""
    import numpy as np
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return []
    lod = root.find("Physics/LOD1")
    if lod is None:
        return []
    kids = lod.findall("Children/Item")
    bnds = lod.findall("Archetype/Bounds/Children/Item")
    if len(kids) != len(bnds):
        return []
    out = []
    for c, bd in zip(kids, bnds):
        v = [float(x) for x in (bd.findtext("CompositeTransform") or "").replace(",", " ").split()]
        if len(v) != 16:
            return []
        out.append((int(c.find("BoneTag").get("value")), np.array(v).reshape(4, 4).T))
    return out


def move_physics(path, fizik0, once, sonra, k):
    """Kapsul CompositeTransform'u kemigiyle: yerel = inv(W_once) @ CT, yerel oteleme * k, CT' = W_sonra @ yerel (satir-vektor yazilir).
    ArticulatedBody eklem capalari (Unknown50 / Unknown90 x, y, z) * k. Satir bazli. Donus: tasinan kapsul sayisi."""
    import numpy as np
    if not fizik0 or once is None or sonra is None:
        return 0
    yeni = []
    for tag, CT in fizik0:
        i0, i1 = once["tag"].get(tag), sonra["tag"].get(tag)
        if i0 is None or i1 is None:
            yeni.append(None)
            continue
        L = np.linalg.inv(once["W"][i0]) @ CT
        L[:3, 3] *= k
        yeni.append((sonra["W"][i1] @ L).T)
    lines = open(path, "r", encoding="utf-8").read().split("\n")
    bloklar = sum(1 for l in lines if l.strip().startswith("<CompositeTransform") and not l.strip().endswith("/>"))
    if bloklar != len(yeni):
        return 0                           # beklenmeyen yapi: kapsuller siraya gore eslenemez -> hic yazma
    idx, row, in_ct, in_joints, n = -1, 0, False, False, 0
    for i, raw in enumerate(lines):
        st = raw.strip()
        if st.startswith("<CompositeTransform") and not st.endswith("/>"):
            in_ct, idx, row = True, idx + 1, 0
            continue
        if st.startswith("</CompositeTransform"):
            in_ct = False
            continue
        if in_ct:
            m = _SAYI.match(raw)
            if m and idx < len(yeni) and yeni[idx] is not None and row < 4:
                lines[i] = m.group(1) + " ".join(fmt(v) for v in yeni[idx][row])
                row += 1
                if row == 4:
                    n += 1
            continue
        if st.startswith("<Joints"):
            in_joints = True
        elif st.startswith("</Joints"):
            in_joints = False
        elif in_joints and (st.startswith("<Unknown50") or st.startswith("<Unknown90")):
            for key in ("x", "y", "z"):
                lines[i] = re.sub(r'\b(%s)="([-0-9.eE+]+)"' % key, lambda mm: '%s="%s"' % (mm.group(1), fmt(float(mm.group(2)) * k)), lines[i])
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return n

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------
class PedScaleProps(PropertyGroup):
    yft_path: StringProperty(name="YFT", subtype="FILE_PATH",
                             description=".yft.xml -- YDD kendiliginden bulunur")
    ydd_path: StringProperty(name="YDD", subtype="FILE_PATH",
                             description="Tek .ydd.xml ya da bilesenlerin oldugu klasor")
    target: FloatProperty(name="Hedef", default=1.0, min=0.10, max=10.0,
                          precision=3, description="1.0 = turun kendi normal boyu")
    ground_mix: FloatProperty(
        name="Zemine oturt", default=1.0, min=0.0, max=1.0, subtype="FACTOR",
        description="1.00 = ped yere tam oturur (tutorial yontemi). "
                    "0.00 = hic kaldirma, duz olcekleme. "
                    "Hayvanda yirtilma gorursen 0'a cek")
    muto_ground: BoolProperty(
        name="Muto zemin duzeltmesi", default=False,
        description="KAPALI (varsayilan): mairon 4.1'in oyunda denenmis zemin formulu; vanilla disi oranli insan iskeleti reddedilir. "
                    "ACIK: muto-ped-rig ciktilari gibi ozel oranli insan iskeletinde zemin vanilla H0 ile (Sollumz'da gomulme "
                    "12-13 -> 1-2 cm; oyunda denenmedi)")
    detected: FloatProperty(default=-1.0)
    species: StringProperty(default="")
    info: StringProperty(default="")
    preview_objects: StringProperty(default="")
    preview_data: StringProperty(default="")
    preview_tmp: StringProperty(default="")


def _auto_pair(p):
    """YDD yolunu kendiliginden bulur. Tek dosya yoksa klasore duser --
       hayvanlarda mesh bilesenlere bolunmus oluyor."""
    y = bpy.path.abspath(p.yft_path)
    if not y or p.ydd_path:
        return
    if y.lower().endswith(".yft.xml"):
        tek = y[:-len(".yft.xml")] + ".ydd.xml"
        if os.path.exists(tek):
            p.ydd_path = tek
            return
    klasor = os.path.dirname(y)
    if klasor and any(f.lower().endswith(".ydd.xml") for f in os.listdir(klasor)):
        p.ydd_path = klasor + os.sep


def ydd_listesi(p):
    """Tek dosya ya da klasor -> .ydd.xml listesi (yedekler haric)."""
    yol = bpy.path.abspath(p.ydd_path)
    if not yol:
        return []
    if os.path.isdir(yol):
        return sorted(os.path.join(yol, f) for f in os.listdir(yol)
                      if f.lower().endswith(".ydd.xml"))
    return [yol] if os.path.isfile(yol) else []


# ---------------------------------------------------------------------------
# Onizleme
# ---------------------------------------------------------------------------
def _sollumz_root():
    """Onizlemenin kullandigi Sollumz import operatoru kayitli mi -> 'bpy.ops.sollumz' ya da None.
    muto: 4.1 Sollumz'u modul ADIYLA ariyordu ('bl_ext.user_default.sollumz' / 'sollumz'); eski usul kurulumda modul 'Sollumz' (buyuk
    harf) oldugu icin import basarisiz -> onizleme "Sollumz gerekli" dedi (olculdu 2026-09-13). Kurulum bicimi onemsiz: operatore bakilir."""
    try:
        if bpy.ops.sollumz.import_assets.get_rna_type() is not None:
            return "bpy.ops.sollumz"
    except Exception:
        pass
    return None


def _import_pair(yft_src, ydd_srcs, workdir, from_scale, to_scale):
    """XML'leri gecici klasore kopyalar, istenen olcege getirir, import eder.
       ORIJINAL DOSYALARA DOKUNMAZ. Sollumz iskeleti ayni klasordeki ilk
       .yft.xml'den aldigi icin her varyant kendi klasorunde olmali."""
    os.makedirs(workdir, exist_ok=True)
    yft_dst = os.path.join(workdir, os.path.basename(yft_src))
    shutil.copy2(yft_src, yft_dst)
    ydd_dsts = []
    for s in ydd_srcs:
        d = os.path.join(workdir, os.path.basename(s))
        shutil.copy2(s, d)
        ydd_dsts.append(d)

    if from_scale and to_scale and abs(to_scale - from_scale) > 1e-9:
        k = to_scale / from_scale
        scale_file(yft_dst, k, do_vertices=False, backup=False)
        for d in ydd_dsts:
            scale_file(d, k, do_vertices=True, backup=False)

    if _sollumz_root() is None:
        raise RuntimeError("Sollumz bulunamadi")
    once = set(bpy.data.objects.keys())
    bpy.ops.sollumz.import_assets(
        directory=workdir + os.sep,
        files=[{"name": os.path.basename(d)} for d in ydd_dsts],
        use_custom_settings=True,
        dwd_import_external_skeleton="FROM_DIR",
    )
    return [n for n in bpy.data.objects.keys() if n not in once]


def _taban_dunya(names):
    zmin = None
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None or o.type != "MESH":
            continue
        for c in o.bound_box:
            z = (o.matrix_world @ Vector(c)).z
            if zmin is None or z < zmin:
                zmin = z
    return zmin if zmin is not None else 0.0


def _yerlestir(names, coll, dx):
    """Koleksiyona tasir, X'te kaydirir, tabani Z=0'a oturtur."""
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    dz = -_taban_dunya(names)
    for n in names:
        o = bpy.data.objects.get(n)
        if o is not None and o.parent is None:
            o.location.x += dx
            o.location.z += dz


def _wipe_preview(p):
    """SADECE onizlemenin olusturdugu objeleri siler. Isimler olusturulurken
       kaydedildi; bpy.context.active_object hic kullanilmaz."""
    try:
        names = json.loads(p.preview_objects) if p.preview_objects else []
    except Exception:
        names = []
    veri, silinen = [], 0
    for n in names:
        o = bpy.data.objects.get(n)
        if o is None:
            continue
        if o.data is not None:
            veri.append(o.data.name)
        bpy.data.objects.remove(o, do_unlink=True)
        silinen += 1
    for ad in veri:
        for kol in (bpy.data.meshes, bpy.data.armatures):
            d = kol.get(ad)
            if d is not None and d.users == 0:
                kol.remove(d)
                break
    try:
        ek = json.loads(p.preview_data) if p.preview_data else {}
    except Exception:
        ek = {}
    for ad in ek.get("materyal", []):
        d = bpy.data.materials.get(ad)
        if d is not None and d.users == 0:
            bpy.data.materials.remove(d)
    for ad in ek.get("resim", []):
        d = bpy.data.images.get(ad)
        if d is not None and d.users == 0:
            bpy.data.images.remove(d)
    coll = bpy.data.collections.get(PREVIEW_COLL)
    if coll is not None and len(coll.objects) == 0:
        bpy.data.collections.remove(coll)
    if p.preview_tmp and os.path.isdir(p.preview_tmp):
        shutil.rmtree(p.preview_tmp, ignore_errors=True)
    p.preview_objects = p.preview_data = p.preview_tmp = ""
    return silinen


# ---------------------------------------------------------------------------
# Ortak cozumleme
# ---------------------------------------------------------------------------
def coz(p):
    """Dosyalari okur; tur, olcek, kaldirma ekseni ve H0'i cikarir.
       (veri, hata) dondurur."""
    yft = bpy.path.abspath(p.yft_path)
    if not yft or not os.path.exists(yft):
        return None, "YFT XML bulunamadi"
    ydds = ydd_listesi(p)
    if not ydds:
        return None, "YDD XML yok — mesh olceklenmezse ped bozulur"

    kim = identify(read_skeleton(yft))
    if kim is None:
        return None, "Iskelet okunamadi"
    ozel = False
    if kim["spread"] > YAYILIM_SINIRI:
        if kim["tur"] in INSAN_TURLERI and p.muto_ground:
            # muto: ozel oranli insan iskeleti. Insan RIGS kaydi turden bagimsiz ayni -> kaldirma ekseni ve dogal cocuklar dogru.
            ozel = True
        elif kim["tur"] in INSAN_TURLERI:
            return None, ("Vanilla disi oranli insan iskeleti (yayilim %.2f > %.2f): mairon 4.1 bunu reddeder. muto-ped-rig "
                          "ciktisiysa 'Muto zemin duzeltmesi'ni acip tekrar dene" % (kim["spread"], YAYILIM_SINIRI))
        else:
            return None, ("Tur taninamadi (en yakin %s, yayilim %.2f). "
                          "Bilinmeyen iskelet — dosya bozulurdu."
                          % (kim["tur"], kim["spread"]))
    rig = RIGS.get(kim["tur"])
    if rig is None:
        return None, "%s icin rig bilgisi yok" % kim["tur"]

    z_root = read_root_z(yft)
    taban = measure_sole_all(ydds)
    if z_root is None or taban is None:
        return None, "SKEL_ROOT ya da taban okunamadi"

    k = kim["scale"]

    # Dunya +Z'nin kokun bone uzayindaki karsiligi. Insan (0,0,1),
    # a_c_boar (1,0,0) -- sabit eksen varsaymak govdeyi yana iter.
    eksen = kaldirma_ekseni(rig["q"])

    # Mevcut kaldirma: cocuklarin dogal degerinden sapmanin eksen bileseni.
    # Dogal degerler her turde 0 degil (boar/SKEL_PelvisRoot 0.223008),
    # o yuzden tablodan okunuyor.
    sapmalar = []
    for ad, t in read_root_children(yft).items():
        dogal = rig["c"].get(ad)
        if dogal is None:
            continue
        sapmalar.append((Vector(t) - Vector(dogal) * k).dot(eksen))
    kaldir = statistics.median(sapmalar) if sapmalar else 0.0

    h0 = (z_root - taban + kaldir) / k
    if not (0.05 < h0 < 5.0):
        return None, "H0 mantiksiz (%.3f) — dosya beklenen yapida degil" % h0

    return {"yft": yft, "ydds": ydds, "tur": kim["tur"], "scale": k,
            "spread": kim["spread"], "n": kim["n"], "h0": h0,
            "z1": z_root / k, "kaldir": kaldir, "eksen": eksen,
            "rig": rig, "ozel": ozel, "muto": bool(p.muto_ground)}, None

# ---------------------------------------------------------------------------
# Operatorler
# ---------------------------------------------------------------------------
class MUTO_PEDSCALE_OT_detect(Operator):
    bl_idname = "muto_pedscale.detect"
    bl_label = "Tespit et"
    bl_description = "Turu ve mevcut olcegi kemik uzunluklarindan bulur"

    def execute(self, context):
        p = context.scene.muto_ped_scale
        _auto_pair(p)
        d, err = coz(p)
        if d is None:
            p.detected = -1.0
            p.species = ""
            p.info = err
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        p.detected = d["scale"]
        p.target = d["scale"]
        p.species = d["tur"]
        p.info = "%d kemik  |  H0 %.4f  |  %d mesh" % (
            d["n"], d["h0"], len(d["ydds"])) + notlar(d)
        self.report({'WARNING'} if notlar(d) else {'INFO'}, "%s  olcek %.4f  (yayilim %.4f)"
                    % (d["tur"], d["scale"], d["spread"]) + notlar(d))
        return {'FINISHED'}


class MUTO_PEDSCALE_OT_apply(Operator):
    bl_idname = "muto_pedscale.apply"
    bl_label = "Olcegi uygula"
    bl_description = ("Iskeleti ve tum mesh bilesenlerini hedefe getirir. "
                      "Yedek (.bak) otomatik alinir")

    def execute(self, context):
        p = context.scene.muto_ped_scale
        _auto_pair(p)
        d, err = coz(p)
        if d is None:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        yft, ydds = d["yft"], d["ydds"]
        cur, h0, z1 = d["scale"], d["h0"], d["z1"]
        delta = p.target / cur
        once = iskelet_dunya(yft)          # muto: fizik kapsulleri eski kemik yerinden tasinir
        fizik0 = fizik_oku(yft)

        if abs(delta - 1.0) > 1e-6:
            scale_file(yft, delta, do_vertices=False, backup=True)
            for f in ydds:
                scale_file(f, delta, do_vertices=True, backup=True)
        else:
            for f in [yft] + ydds:
                if not os.path.exists(f + ".bak"):
                    shutil.copy2(f, f + ".bak")

        # --- hepsi MUTLAK yazilir: gecmis onemsiz, birikme olmaz ---
        # muto: taban - kok mesafesi olcekten sonra turun vanilla degeri (h0_referans). 4.1'in h0*(hedef-1) formulu ozel oranli insan
        # iskeletinde (muto-ped-rig 1,4 m -> 1,0) kok - taban 1,101 verdi (oyunda ~12 cm gomulu); vanilla dosyada iki formul ayni.
        h0_ref = h0_referans(d)
        kaldir = (h0 * p.target - h0_ref) * p.ground_mix
        # Cocuklarin hedef translation'i: dogal deger * olcek + kaldirma * eksen.
        # Eksen turden turne degisiyor (insan z, boar x) -- bkz. coz().
        hedefler = {}
        for ad, dogal in d["rig"]["c"].items():
            hedefler[ad] = tuple(Vector(dogal) * p.target + d["eksen"] * kaldir)
        for f in [yft] + ydds:
            set_root_z(f, z1 * p.target)
            set_root_children_t(f, hedefler)

        # mesh kemikle AYNI miktar kaymali, yoksa rijit hareket olmaz
        hedef = (z1 - h0) * p.target + kaldir
        simdi = measure_sole_all(ydds)
        dz = (hedef - simdi) if simdi is not None else 0.0
        if abs(dz) > 1e-6:
            for f in ydds:
                shift_mesh_z(f, dz)

        # muto: .yft BoneTransforms (doluysa) ve hayvan fizigi SON iskelete gore
        sonra = iskelet_dunya(yft)
        n_bt = rebuild_bone_transforms(yft, sonra)
        n_fz = move_physics(yft, fizik0, once, sonra, delta) if fizik0 else 0

        son, _ = coz(p)
        p.detected = son["scale"] if son else -1.0
        zemin = -(h0 * p.target - h0_ref) * (1.0 - p.ground_mix) * 100.0
        p.info = "%s  %.3f  |  kaldirma %+.4f  |  zemin %+.1f cm" % (
            d["tur"], p.target, kaldir, zemin)
        self.report({'WARNING'} if notlar(d) else {'INFO'}, "%.4f -> %.4f  |  %d dosya  |  kemik %+.5f  mesh %+.5f"
                    % (cur, p.target, 1 + len(ydds), kaldir, dz)
                    + "  |  BoneTransforms %d  fizik kapsul %d" % (n_bt, n_fz) + notlar(d))
        return {'FINISHED'}


class MUTO_PEDSCALE_OT_preview(Operator):
    bl_idname = "muto_pedscale.preview"
    bl_label = "Sahnede karsilastir"
    bl_description = ("Solda hedef olcekteki ped, sagda turun normal boyu. "
                      "Dosyaya dokunmaz, sahnendeki hicbir seye dokunmaz")

    def execute(self, context):
        p = context.scene.muto_ped_scale
        _auto_pair(p)
        d, err = coz(p)
        if d is None:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        if _sollumz_root() is None:
            self.report({'ERROR'}, "Sollumz gerekli")
            return {'CANCELLED'}

        _wipe_preview(p)
        cur = d["scale"]
        p.detected = cur
        p.species = d["tur"]
        ayni_ad = ydd_ayni_adlar(d["ydds"])        # muto: Sollumz ayni adli cizimleri birlestirir

        tmp = tempfile.mkdtemp(prefix="muto_pedscale_")
        p.preview_tmp = tmp
        coll = bpy.data.collections.get(PREVIEW_COLL)
        if coll is None:
            coll = bpy.data.collections.new(PREVIEW_COLL)
            bpy.context.scene.collection.children.link(coll)
        hepsi = []
        mat0 = set(bpy.data.materials.keys())
        img0 = set(bpy.data.images.keys())

        def kaydet():
            p.preview_objects = json.dumps(hepsi)
            p.preview_data = json.dumps({
                "materyal": [n for n in bpy.data.materials.keys() if n not in mat0],
                "resim": [n for n in bpy.data.images.keys() if n not in img0]})

        try:
            n1 = _import_pair(d["yft"], d["ydds"], os.path.join(tmp, "hedef"),
                              cur, p.target)
            _yerlestir(n1, coll, 0.0)
            hepsi += n1
            n2 = _import_pair(d["yft"], d["ydds"], os.path.join(tmp, "referans"),
                              cur, 1.0)
            _yerlestir(n2, coll, max(0.8, d["h0"] * 1.3))
            hepsi += n2
        except Exception as e:
            kaydet(); _wipe_preview(p)
            self.report({'ERROR'}, "Import hatasi: %s" % e)
            return {'CANCELLED'}

        kaydet()
        uyari = ("  |  UYARI %d cizim ayni adli (CodeWalker adi cozemedi): Sollumz yalniz sonuncusunu gosterir, olcek dosyada tum "
                 "cizimlere uygulanir" % ayni_ad) if ayni_ad else ""
        p.info = "sol %.3f  |  sag 1.000" % p.target + uyari
        self.report({'WARNING'} if ayni_ad else {'INFO'}, "Onizleme hazir (%d obje)" % len(hepsi) + uyari)
        return {'FINISHED'}


class MUTO_PEDSCALE_OT_clear_preview(Operator):
    bl_idname = "muto_pedscale.clear_preview"
    bl_label = "Onizlemeyi temizle"
    bl_description = "Sadece onizlemenin ekledigi objeleri siler"

    def execute(self, context):
        n = _wipe_preview(context.scene.muto_ped_scale)
        self.report({'INFO'}, "%d obje silindi" % n)
        return {'FINISHED'}


class MUTO_PEDSCALE_OT_restore(Operator):
    bl_idname = "muto_pedscale.restore"
    bl_label = "Yedekten geri al"
    bl_description = ".bak dosyalarini geri yukler"

    def execute(self, context):
        p = context.scene.muto_ped_scale
        _auto_pair(p)
        n = 0
        for f in [bpy.path.abspath(p.yft_path)] + ydd_listesi(p):
            if f and os.path.exists(f + ".bak"):
                shutil.copy2(f + ".bak", f)
                n += 1
        if not n:
            self.report({'WARNING'}, "Yedek bulunamadi")
            return {'CANCELLED'}
        bpy.ops.muto_pedscale.detect()
        self.report({'INFO'}, "%d dosya geri alindi" % n)
        return {'FINISHED'}


class MUTO_PEDSCALE_OT_preset(Operator):
    bl_idname = "muto_pedscale.preset"
    bl_label = "Oran"
    value: FloatProperty(default=1.0)

    def execute(self, context):
        context.scene.muto_ped_scale.target = self.value
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class MUTO_PEDSCALE_PT_panel(Panel):
    bl_label = "Muto Ped Scaler"
    bl_idname = "MUTO_PEDSCALE_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Muto Rig"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 10          # Muto Ped Rig panellerinin altinda

    def draw(self, context):
        lay = self.layout
        p = context.scene.muto_ped_scale

        col = lay.column(align=True)
        col.prop(p, "yft_path")
        col.prop(p, "ydd_path")

        row = lay.row(align=True)
        row.operator("muto_pedscale.detect", icon="VIEWZOOM")
        if p.detected > 0:
            row.label(text="%.3f" % p.detected,
                      icon="CHECKMARK" if abs(p.detected - 1.0) < 0.002 else "INFO")
        if p.species:
            lay.label(text=p.species, icon="OUTLINER_OB_ARMATURE")

        lay.separator()
        lay.prop(p, "target")
        row = lay.row(align=True)
        for v in (0.90, 0.95, 1.00, 1.05, 1.10):
            row.operator("muto_pedscale.preset", text="%.2f" % v).value = v
        lay.prop(p, "ground_mix", slider=True)
        lay.prop(p, "muto_ground")

        col = lay.column()
        col.scale_y = 1.4
        col.operator("muto_pedscale.apply", icon="CON_SIZELIKE")

        lay.separator()
        if p.preview_objects:
            r = lay.row()
            r.alert = True
            r.operator("muto_pedscale.clear_preview", icon="TRASH")
        else:
            lay.operator("muto_pedscale.preview", icon="OUTLINER_OB_ARMATURE")
        lay.operator("muto_pedscale.restore", icon="LOOP_BACK")

        if p.info:
            lay.separator()
            lay.label(text=p.info)


CLASSES = (PedScaleProps, MUTO_PEDSCALE_OT_detect, MUTO_PEDSCALE_OT_apply,
           MUTO_PEDSCALE_OT_preview, MUTO_PEDSCALE_OT_clear_preview,
           MUTO_PEDSCALE_OT_restore, MUTO_PEDSCALE_OT_preset, MUTO_PEDSCALE_PT_panel)


def register():
    # ayri kurulu eski muto_ped_scaler.py / mairon_ped_scaler.py ayni sinif adlarini tasir -> ikisi birden acilamaz
    if hasattr(bpy.types.Scene, "muto_ped_scale"):
        print("Muto Ped Rig: ayri kurulu Muto Ped Scaler acik; yerlesik olcekleyici atlandi (onu kapatin)")
        return
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.muto_ped_scale = bpy.props.PointerProperty(type=PedScaleProps)


def unregister():
    if not getattr(MUTO_PEDSCALE_PT_panel, "is_registered", False):
        return
    del bpy.types.Scene.muto_ped_scale
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)

