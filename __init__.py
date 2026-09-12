"""Muto Ped Rig — kisisel FiveM humanoid ped rig eklentisi (sifirdan; ARP kodu icermez).

core/ Blender'siz calisir (testler sistem Python'uyla kosar); bl/ yalniz Blender icinde yuklenir.
"""
try:
    import bpy
except ImportError:          # Blender disi (testler): yalniz core kullanilir
    bpy = None

if bpy is not None:
    if "_modules" in locals():   # gelistirme sirasinda F3 > Reload Scripts
        import importlib
        from .core import skeleton, fit, markers, voxel, weights, transfer, pipeline, knn, autodetect, components
        for _m in (skeleton, fit, markers, voxel, weights, transfer, pipeline, knn, autodetect, components):
            importlib.reload(_m)
        from .bl import io, props, sollumz_setup, ops, ui
        for _m in (io, props, sollumz_setup, ops, ui):
            importlib.reload(_m)
    from .bl import props, ops, ui

    _modules = (props, ops, ui)

    def register():
        for m in _modules:
            m.register()

    def unregister():
        for m in reversed(_modules):
            m.unregister()
