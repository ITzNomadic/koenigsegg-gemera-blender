import bpy
import math

try:
    # 1. Texture file paths
    tread_nrml_path = r"e:\Decalga\calembo\tire_textures\tread_sport_nrml_bb47198c-0b80-4e3a-a683-8e6ff877a1a7.dds"
    tread_extra_path = r"e:\Decalga\calembo\tire_textures\tread_sport_extra_b4257cc7-045f-4cb3-860f-a665c5b268a4.dds"
    sidewall_nrml_path = r"e:\Decalga\calembo\tire_textures\sidewall_horizon_nrml_aad799fe-8795-43a0-8b7c-df9dda711bba.dds"
    sidewall_extra_path = r"e:\Decalga\calembo\tire_textures\sidewall_horizon_extra_5318a70d-ed5c-4b95-afc8-e8f4098e7acf.dds"

    def get_or_load_img(path, name):
        img = bpy.data.images.get(name)
        if not img:
            img = bpy.data.images.load(path)
            img.name = name
        img.colorspace_settings.name = 'Non-Color'
        return img

    img_tread_nrml = get_or_load_img(tread_nrml_path, "Tire_Tread_NRML")
    img_tread_extra = get_or_load_img(tread_extra_path, "Tire_Tread_EXTRA")
    img_side_nrml = get_or_load_img(sidewall_nrml_path, "Tire_Sidewall_NRML")
    img_side_extra = get_or_load_img(sidewall_extra_path, "Tire_Sidewall_EXTRA")

    # 2. Build detailed sports radial profile with physical circumferential drainage grooves
    def get_tire_profile(r_bead, r_tread):
        g_depth = 0.007  # 7mm groove depth
        prof = [
            # Inner sidewall & bead
            (0.000, r_bead, 0.0),
            (0.020, r_bead + 0.012, 0.0),
            (0.050, r_bead + 0.038, 0.0),
            (0.080, r_tread - 0.025, 0.0),
            (0.120, r_tread - 0.006, 0.5),
            (0.160, r_tread - 0.001, 1.0),
            # Tread Block 1
            (0.200, r_tread, 1.0),
            (0.230, r_tread, 1.0),
            # Groove 1
            (0.240, r_tread - g_depth, 1.0),
            (0.270, r_tread - g_depth, 1.0),
            # Tread Block 2
            (0.280, r_tread, 1.0),
            (0.360, r_tread, 1.0),
            # Groove 2
            (0.370, r_tread - g_depth, 1.0),
            (0.400, r_tread - g_depth, 1.0),
            # Tread Block 3 (Center Rib)
            (0.410, r_tread, 1.0),
            (0.500, r_tread, 1.0),
            (0.530, r_tread, 1.0),
            # Groove 3
            (0.540, r_tread - g_depth, 1.0),
            (0.570, r_tread - g_depth, 1.0),
            # Tread Block 4
            (0.580, r_tread, 1.0),
            (0.670, r_tread, 1.0),
            # Groove 4
            (0.680, r_tread - g_depth, 1.0),
            (0.710, r_tread - g_depth, 1.0),
            # Outer Shoulder Block
            (0.720, r_tread, 1.0),
            (0.820, r_tread, 1.0),
            (0.870, r_tread - 0.004, 0.5),
            # Outer Sidewall & Rim Protector Flange
            (0.920, r_tread - 0.022, 0.0),
            (0.965, r_bead + 0.045, 0.0),
            (1.010, r_bead + 0.022, 0.0),  # Flange extends slightly past rim lip
            (0.990, r_bead + 0.008, 0.0),  # Flange recess
            (0.960, r_bead, 0.0)           # Outer bead seat
        ]
        return prof

    # 3. Rebuild each tire mesh in place (EXACT OBJECT POSITION PRESERVED)
    configs = [
        {"name": "Gemera_Tire_LF", "y0": -1.500, "z0": 0.105, "xi": 0.700, "xo": 0.996, "rb": 0.2668, "rt": 0.3552, "right": False},
        {"name": "Gemera_Tire_RF", "y0": -1.500, "z0": 0.105, "xi": 0.700, "xo": 0.996, "rb": 0.2668, "rt": 0.3552, "right": True},
        {"name": "Gemera_Tire_LR", "y0": 1.500,  "z0": 0.115, "xi": 0.680, "xo": 0.996, "rb": 0.2794, "rt": 0.3739, "right": False},
        {"name": "Gemera_Tire_RR", "y0": 1.500,  "z0": 0.115, "xi": 0.680, "xo": 0.996, "rb": 0.2794, "rt": 0.3739, "right": True},
    ]

    N = 96  # 96 circumferential steps for ultra-smooth circular profile

    for cfg in configs:
        obj = bpy.data.objects.get(cfg["name"])
        if not obj:
            continue
        
        prof = get_tire_profile(cfg["rb"], cfg["rt"])
        M = len(prof)

        verts = []
        for i in range(N):
            theta = 2.0 * math.pi * i / float(N)
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)
            for j in range(M):
                u, r, mask_val = prof[j]
                if not cfg["right"]:
                    x = cfg["xi"] + u * (cfg["xo"] - cfg["xi"])
                else:
                    x = -(cfg["xi"] + u * (cfg["xo"] - cfg["xi"]))
                y = cfg["y0"] + r * sin_t
                z = cfg["z0"] + r * cos_t
                verts.append((x, y, z))

        faces = []
        for i in range(N):
            i_next = (i + 1) % N
            for j in range(M - 1):
                v00 = i * M + j
                v01 = i * M + j + 1
                v10 = i_next * M + j
                v11 = i_next * M + j + 1
                if not cfg["right"]:
                    faces.append((v00, v01, v11, v10))
                else:
                    faces.append((v00, v10, v11, v01))

        # Update mesh data without changing object transform
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        # Add Tread_Mask vertex color
        mask_attr = mesh.color_attributes.get("Tread_Mask")
        if not mask_attr:
            mask_attr = mesh.color_attributes.new(name="Tread_Mask", type='FLOAT_COLOR', domain='POINT')

        for vert in mesh.vertices:
            j = vert.index % M
            mval = prof[j][2]
            mask_attr.data[vert.index].color = (mval, mval, mval, 1.0)

        # UVMap_Tread
        uv_tread = mesh.uv_layers.get("UVMap_Tread")
        if not uv_tread:
            uv_tread = mesh.uv_layers.new(name="UVMap_Tread")

        # UVMap_Sidewall
        uv_side = mesh.uv_layers.get("UVMap_Sidewall")
        if not uv_side:
            uv_side = mesh.uv_layers.new(name="UVMap_Sidewall")

        for poly in mesh.polygons:
            poly.use_smooth = True
            for loop_idx in poly.loop_indices:
                v_idx = mesh.loops[loop_idx].vertex_index
                i_step = v_idx // M
                j_step = v_idx % M
                u_val = prof[j_step][0]
                circ_v = i_step / float(N)

                # Tread UV
                # Tread is between u=0.12 and u=0.87
                if u_val <= 0.12:
                    u_tr = 0.0
                elif u_val >= 0.87:
                    u_tr = 1.0
                else:
                    u_tr = (u_val - 0.12) / (0.87 - 0.12)
                v_tr = circ_v * 16.0
                uv_tread.data[loop_idx].uv = (u_tr, v_tr)

                # Sidewall UV
                # Outer sidewall is j_step >= 25 to 30
                u_sw = circ_v
                if j_step >= 25:
                    v_sw = (30 - j_step) / 5.0
                elif j_step <= 4:
                    v_sw = j_step / 4.0
                else:
                    v_sw = 1.0
                uv_side.data[loop_idx].uv = (u_sw, v_sw)

    # 4. Hyper-realistic Shader Network
    mat = bpy.data.materials.get("Rubber")
    if not mat:
        mat = bpy.data.materials.new("Rubber")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    node_out = nodes.new('ShaderNodeOutputMaterial')
    node_out.location = (1400, 0)

    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.location = (1100, 0)
    links.new(bsdf.outputs['BSDF'], node_out.inputs['Surface'])

    # Tread Mask
    attr_mask = nodes.new('ShaderNodeAttribute')
    attr_mask.attribute_name = "Tread_Mask"
    attr_mask.location = (-600, 100)

    # Tread UV & Normal Map
    uv_tread_node = nodes.new('ShaderNodeUVMap')
    uv_tread_node.uv_map = "UVMap_Tread"
    uv_tread_node.location = (-700, 500)

    tex_tread_nrml = nodes.new('ShaderNodeTexImage')
    tex_tread_nrml.image = img_tread_nrml
    tex_tread_nrml.location = (-450, 500)
    links.new(uv_tread_node.outputs['UV'], tex_tread_nrml.inputs['Vector'])

    nmap_tread = nodes.new('ShaderNodeNormalMap')
    nmap_tread.space = 'TANGENT'
    nmap_tread.uv_map = "UVMap_Tread"
    nmap_tread.inputs['Strength'].default_value = 1.2
    nmap_tread.location = (-150, 500)
    links.new(tex_tread_nrml.outputs['Color'], nmap_tread.inputs['Color'])

    # Sidewall UV & Normal Map
    uv_side_node = nodes.new('ShaderNodeUVMap')
    uv_side_node.uv_map = "UVMap_Sidewall"
    uv_side_node.location = (-700, -300)

    tex_side_nrml = nodes.new('ShaderNodeTexImage')
    tex_side_nrml.image = img_side_nrml
    tex_side_nrml.location = (-450, -300)
    links.new(uv_side_node.outputs['UV'], tex_side_nrml.inputs['Vector'])

    nmap_side = nodes.new('ShaderNodeNormalMap')
    nmap_side.space = 'TANGENT'
    nmap_side.uv_map = "UVMap_Sidewall"
    nmap_side.inputs['Strength'].default_value = 1.4
    nmap_side.location = (-150, -300)
    links.new(tex_side_nrml.outputs['Color'], nmap_side.inputs['Color'])

    # Mix Normal Vectors between Sidewall Normal and Tread Normal
    mix_nrml = nodes.new('ShaderNodeMix')
    mix_nrml.data_type = 'VECTOR'
    mix_nrml.location = (200, 100)
    links.new(attr_mask.outputs['Fac'], mix_nrml.inputs['Factor'])
    links.new(nmap_side.outputs['Normal'], mix_nrml.inputs[4])   # Input A (Sidewall)
    links.new(nmap_tread.outputs['Normal'], mix_nrml.inputs[5])  # Input B (Tread)

    # Micro Rubber Noise Bump (pore texture)
    tex_noise = nodes.new('ShaderNodeTexNoise')
    tex_noise.inputs['Scale'].default_value = 250.0
    tex_noise.inputs['Detail'].default_value = 4.0
    tex_noise.inputs['Roughness'].default_value = 0.7
    tex_noise.location = (450, -200)

    node_bump = nodes.new('ShaderNodeBump')
    node_bump.inputs['Strength'].default_value = 0.03
    node_bump.inputs['Distance'].default_value = 0.003
    node_bump.location = (750, -100)
    links.new(tex_noise.outputs['Fac'], node_bump.inputs['Height'])
    links.new(mix_nrml.outputs[1], node_bump.inputs['Normal'])  # Output Result
    links.new(node_bump.outputs['Normal'], bsdf.inputs['Normal'])

    # Base Color: Sidewall deep satin charcoal (0.016) vs Tread dry road charcoal (0.026)
    mix_color = nodes.new('ShaderNodeMix')
    mix_color.data_type = 'RGBA'
    mix_color.location = (650, 300)
    links.new(attr_mask.outputs['Fac'], mix_color.inputs['Factor'])
    mix_color.inputs[6].default_value = (0.016, 0.016, 0.018, 1.0) # Sidewall
    mix_color.inputs[7].default_value = (0.027, 0.027, 0.030, 1.0) # Tread
    links.new(mix_color.outputs[2], bsdf.inputs['Base Color'])

    # Roughness: Sidewall satin (0.54) vs Tread high-friction matte (0.84)
    mix_rough = nodes.new('ShaderNodeMix')
    mix_rough.data_type = 'FLOAT'
    mix_rough.location = (650, 100)
    links.new(attr_mask.outputs['Fac'], mix_rough.inputs['Factor'])
    mix_rough.inputs[2].default_value = 0.54  # Sidewall satin
    mix_rough.inputs[3].default_value = 0.84  # Tread matte
    links.new(mix_rough.outputs[0], bsdf.inputs['Roughness'])

    bsdf.inputs['Metallic'].default_value = 0.0
    if 'Specular IOR Level' in bsdf.inputs:
        bsdf.inputs['Specular IOR Level'].default_value = 0.48
    elif 'Specular' in bsdf.inputs:
        bsdf.inputs['Specular'].default_value = 0.48

    # Ensure all tires have Rubber material assigned
    for cfg in configs:
        t_obj = bpy.data.objects.get(cfg["name"])
        if t_obj:
            t_obj.data.materials.clear()
            t_obj.data.materials.append(mat)

    # 5. Capture close-up inspection
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for space in area.spaces:
                    if space.type == 'VIEW_3D':
                        space.shading.type = 'MATERIAL'
                for region in area.regions:
                    if region.type == 'WINDOW':
                        bpy.context.scene.render.filepath = 'C:/Windows/Temp/blender_view.png'
                        bpy.context.scene.render.image_settings.file_format = 'PNG'
                        with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
                            bpy.ops.render.opengl(write_still=True)
                        break
                break
        break

    result = "Hyperrealistic tire geometry and multi-tangent normal maps applied successfully!"
except Exception as e:
    result = f"Error: {e}"
