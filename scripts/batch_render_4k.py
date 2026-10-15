import bpy
import mathutils
import os
import time

try:
    out_dir = r"e:\Decalga\calembo\renders_4k"
    os.makedirs(out_dir, exist_ok=True)

    cam = bpy.data.objects.get("Gemera_Preview_Camera")
    if not cam:
        cam_data = bpy.data.cameras.new("Gemera_Preview_Camera")
        cam = bpy.data.objects.new("Gemera_Preview_Camera", cam_data)
        bpy.context.scene.collection.objects.link(cam)

    bpy.context.scene.camera = cam

    # Setup 4K Resolution
    scene = bpy.context.scene
    scene.render.resolution_x = 3840
    scene.render.resolution_y = 2160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'

    shots = [
        {
            "name": "01_Gemera_Front_ThreeQuarter_4K.png",
            "pos": (3.6, -4.5, 1.1),
            "target": (0.1, -0.4, 0.45),
            "lens": 50.0
        },
        {
            "name": "02_Gemera_Rear_ThreeQuarter_4K.png",
            "pos": (3.8, 3.8, 1.25),
            "target": (0.0, 0.3, 0.45),
            "lens": 50.0
        },
        {
            "name": "03_Gemera_Side_Profile_4K.png",
            "pos": (6.2, 0.0, 0.6),
            "target": (0.0, 0.0, 0.45),
            "lens": 70.0
        },
        {
            "name": "04_Gemera_Front_Low_Aggressive_4K.png",
            "pos": (1.2, -5.2, 0.55),
            "target": (0.0, -0.8, 0.45),
            "lens": 42.0
        },
        {
            "name": "05_Gemera_Wheel_Tire_Detail_4K.png",
            "pos": (1.85, -1.95, 0.32),
            "target": (0.976, -1.500, 0.240),
            "lens": 75.0
        },
        {
            "name": "06_Gemera_Aerial_Cockpit_4K.png",
            "pos": (3.2, -2.8, 3.2),
            "target": (0.0, -0.2, 0.5),
            "lens": 45.0
        },
        {
            "name": "07_Gemera_Rear_Diffuser_Low_4K.png",
            "pos": (0.0, 4.8, 0.5),
            "target": (0.0, 0.8, 0.4),
            "lens": 50.0
        }
    ]

    rendered_files = []
    t_start = time.time()

    # Find 3D Viewport window/area/region
    v_win, v_screen, v_area, v_region = None, None, None, None
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.region_3d.view_perspective = 'CAMERA'
                        space.shading.type = 'MATERIAL'
                for region in area.regions:
                    if region.type == 'WINDOW':
                        v_win, v_screen, v_area, v_region = win, win.screen, area, region
                        break
                if v_region:
                    break
        if v_region:
            break

    for idx, s in enumerate(shots):
        c_pos = mathutils.Vector(s["pos"])
        c_tgt = mathutils.Vector(s["target"])
        cam.location = c_pos
        direction = c_tgt - c_pos
        cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
        cam.data.lens = s["lens"]

        bpy.context.view_layer.update()

        fpath = os.path.join(out_dir, s["name"])
        scene.render.filepath = fpath

        with bpy.context.temp_override(window=v_win, screen=v_screen, area=v_area, region=v_region):
            bpy.ops.render.opengl(write_still=True)

        sz_mb = round(os.path.getsize(fpath) / (1024 * 1024), 2)
        rendered_files.append({"name": s["name"], "size_mb": sz_mb})

        # Also copy the first hero shot to C:/Windows/Temp/blender_view.png for inspection rule
        if idx == 0:
            import shutil
            shutil.copyfile(fpath, "C:/Windows/Temp/blender_view.png")

    total_time = round(time.time() - t_start, 2)
    result = {
        "status": "Success",
        "total_time_seconds": total_time,
        "resolution": "3840x2160 (4K UHD)",
        "output_directory": out_dir,
        "files": rendered_files
    }
except Exception as e:
    result = f"Error: {e}"
