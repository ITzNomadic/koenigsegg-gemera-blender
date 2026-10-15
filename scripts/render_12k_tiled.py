import bpy
import mathutils
import os
import time
import site
import sys
user_site = site.getusersitepackages()
if user_site not in sys.path:
    sys.path.append(user_site)
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

out_dir = r"e:\Decalga\calembo\renders_12k"
os.makedirs(out_dir, exist_ok=True)
temp_dir = os.path.join(out_dir, "temp_tiles")
os.makedirs(temp_dir, exist_ok=True)

shots = [
    {
        "filename": "01_Gemera_Front_ThreeQuarter_12K.png",
        "pos": (3.6, -4.5, 1.1),
        "target": (0.1, -0.4, 0.45),
        "lens": 50.0,
        "title": "Hero 3/4 Delantera"
    },
    {
        "filename": "02_Gemera_Rear_ThreeQuarter_12K.png",
        "pos": (3.8, 3.8, 1.25),
        "target": (0.0, 0.3, 0.45),
        "lens": 50.0,
        "title": "3/4 Trasera"
    },
    {
        "filename": "03_Gemera_Side_Profile_12K.png",
        "pos": (6.2, 0.0, 0.6),
        "target": (0.0, 0.0, 0.45),
        "lens": 70.0,
        "title": "Perfil Lateral Puro"
    },
    {
        "filename": "04_Gemera_Front_Low_Aggressive_12K.png",
        "pos": (1.2, -5.2, 0.55),
        "target": (0.0, -0.8, 0.45),
        "lens": 42.0,
        "title": "Frontal Baja Agresiva"
    },
    {
        "filename": "05_Gemera_Wheel_Tire_Detail_12K.png",
        "pos": (1.85, -1.95, 0.32),
        "target": (0.976, -1.500, 0.240),
        "lens": 75.0,
        "title": "Detalle Rueda y Neumático"
    },
    {
        "filename": "06_Gemera_Aerial_Cockpit_12K.png",
        "pos": (3.2, -2.8, 3.2),
        "target": (0.0, -0.2, 0.5),
        "lens": 45.0,
        "title": "Aérea / Cabina Interior"
    },
    {
        "filename": "07_Gemera_Rear_Diffuser_Low_12K.png",
        "pos": (0.0, 4.8, 0.5),
        "target": (0.0, 0.8, 0.4),
        "lens": 50.0,
        "title": "Difusor Trasero y Escapes"
    }
]

scene = bpy.context.scene
scene.render.engine = 'BLENDER_EEVEE'

# Tile resolution: 5760 x 3240 (5760 <= 8192 GPU buffer limit)
tile_w = 5760
tile_h = 3240
scene.render.resolution_x = tile_w
scene.render.resolution_y = tile_h
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.image_settings.compression = 15

cam = scene.objects.get("Gemera_Preview_Camera")
if not cam:
    cam_data = bpy.data.cameras.new("Gemera_Preview_Camera")
    cam = bpy.data.objects.new("Gemera_Preview_Camera", cam_data)
    scene.collection.objects.link(cam)
scene.camera = cam

print(f"=== INICIANDO BATCH RENDER NATIVO 12K UHD (11520 x 6480) ===")
print(f"Total tomas a procesar: {len(shots)}")
t_master_start = time.time()

tiles = [
    ("tl", -0.5, 0.28125, 0, 0),
    ("tr", 0.5, 0.28125, tile_w, 0),
    ("bl", -0.5, -0.28125, 0, tile_h),
    ("br", 0.5, -0.28125, tile_w, tile_h),
]

summary = []

for idx, s in enumerate(shots, 1):
    t_shot_start = time.time()
    print(f"\n[{idx}/{len(shots)}] Procesando: {s['filename']} ({s['title']})...")
    
    c_pos = mathutils.Vector(s["pos"])
    c_tgt = mathutils.Vector(s["target"])
    cam.location = c_pos
    direction = c_tgt - c_pos
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    base_lens = s["lens"]
    
    # 2x focal length for quadrant framing
    cam.data.lens = base_lens * 2.0
    
    tile_paths = []
    for name, sx, sy, px, py in tiles:
        cam.data.shift_x = sx
        cam.data.shift_y = sy
        bpy.context.view_layer.update()
        
        t_path = os.path.join(temp_dir, f"temp_{idx}_{name}.png")
        scene.render.filepath = t_path
        bpy.ops.render.render(write_still=True)
        tile_paths.append((t_path, px, py))
    
    # Reset camera shift
    cam.data.shift_x = 0.0
    cam.data.shift_y = 0.0
    cam.data.lens = base_lens
    
    # Stitch tiles into 11520 x 6480
    print(f"  -> Ensamblando cuadrantes 12K (11520 x 6480)...")
    full_img = Image.new('RGB', (tile_w * 2, tile_h * 2))
    for t_path, px, py in tile_paths:
        with Image.open(t_path) as im:
            full_img.paste(im, (px, py))
        try:
            os.remove(t_path)
        except:
            pass
            
    final_out = os.path.join(out_dir, s["filename"])
    full_img.save(final_out, optimize=False)
    
    dt_shot = time.time() - t_shot_start
    sz_mb = os.path.getsize(final_out) / (1024 * 1024)
    print(f"  -> COMPLETADO: {s['filename']} ({full_img.size[0]}x{full_img.size[1]}) | {sz_mb:.2f} MB en {dt_shot:.1f}s")
    
    if idx == 1:
        # Create preview copy for blender_view.png
        import shutil
        shutil.copyfile(final_out, r"C:\Windows\Temp\blender_view.png")
        
    summary.append({
        "name": s["filename"],
        "title": s["title"],
        "size_mb": round(sz_mb, 2),
        "time": round(dt_shot, 1)
    })

# Cleanup temp dir
try:
    os.rmdir(temp_dir)
except:
    pass

t_master_total = time.time() - t_master_start
print(f"\n==========================================")
print(f"🎉 TODO EL SET 12K UHD HA SIDO GENERADO CON ÉXITO EN {t_master_total:.1f}s!")
for item in summary:
    print(f" - {item['name']}: {item['size_mb']} MB ({item['time']}s) -> {item['title']}")
