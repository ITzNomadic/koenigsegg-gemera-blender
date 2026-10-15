#!/usr/bin/env python3
"""
modelbin_to_glb.py
------------------
Converts .modelbin files (burG format) to binary glTF (.glb).

Usage:
    python modelbin_to_glb.py <file.modelbin> [output_dir]

Output: <assembly>.glb beside the source file (or in output_dir).
All geometry LODs become separate named meshes in one .glb.
Skeleton and skinning are included when Skel + MBuf chunks are present.

Coordinate transform
--------------------
burG: Y-up, Z-forward, left-handed.
glTF: Y-up, -Z-forward, right-handed.
Negate Z on positions, normals, and bone translations.
Reverse triangle winding (a,b,c) -> (a,c,b).

Decoded attributes
------------------
  POSITION     VEC3 float32  from VerB[0] SNORM16 decoded against per-LOD BBox
  NORMAL       VEC3 float32  from VerB[1/2] 2xSNORM16 + W-bit NZ sign
  TEXCOORD_0   VEC2 float32  UV0 from VerB[1/2]
  JOINTS_0     VEC4 uint8    bone indices (2 active, 2 zero-padded)
  WEIGHTS_0    VEC4 float32  blend weights (2 active, normalised, 2 zero)

Skinning notes
--------------
Primary bone:   root_bone from Mesh chunk +0x08 (constant per LOD).
                Falls back to bone 0 (<root>) for multi-bone assemblies
                (root_bone=0xFFFF) where the true primary is unresolved.
Secondary bone: MBuf b[5] raw byte as global bone index (>60 = none).
Weights:        b[2]/(b[2]+b[4]), b[4]/(b[2]+b[4]), normalised at export.

Tangent frame (VerB[1/2] bytes 24-35) is not decoded.
Recalculate tangents in Blender from UV0 after import.
"""

import json
import math
import struct
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# glTF constants
# ---------------------------------------------------------------------------
ARRAY_BUFFER         = 34962
ELEMENT_ARRAY_BUFFER = 34963
FLOAT                = 5126
UNSIGNED_BYTE        = 5121
UNSIGNED_INT         = 5125


# ---------------------------------------------------------------------------
# burG parsing
# ---------------------------------------------------------------------------

def _fourcc(data, off):
    return data[off:off+4][::-1].decode('ascii', errors='replace')

def _s16(v):
    return v / 32767.0

def _s16_bbox(v, lo, hi):
    return lo + (v + 32768) / 65535.0 * (hi - lo)

def parse_chunks(data):
    if data[:4] != b'burG':
        raise ValueError(f"bad magic {data[:4]!r}")
    version = struct.unpack_from('<HH', data, 4)
    n       = struct.unpack_from('<I',  data, 16)[0]
    by_id, pos = {}, 0x14
    for _ in range(n):
        c = dict(
            id  = _fourcc(data, pos),
            unk = struct.unpack_from('<I', data, pos +  8)[0],
            off = struct.unpack_from('<I', data, pos + 12)[0],
            sz  = struct.unpack_from('<I', data, pos + 16)[0],
        )
        by_id.setdefault(c['id'], []).append(c)
        pos += 24
    return by_id, version

def _valid_bbox(f):
    return (all(x == x for x in f) and all(abs(x) <= 500 for x in f)
            and f[3] >= f[0] and f[4] >= f[1] and f[5] >= f[2])

def read_name_bbox(data, offset):
    """
    Read a Name+BBox record from a known absolute offset (Mesh chunk unk field).
    Returns {'name', 'bbox_min', 'bbox_max'} or None if the record is invalid.

    Record layout:
      offset+0  : 'emaN' tag (4 B)
      offset+4  : uint32 (absolute-offset-related, ignored)
      offset+8  : 'xoBB' tag (4 B)
      offset+12 : uint16 = 0x0180 (constant); uint16 N
      offset+16 : ASCII name (N-8 bytes)
      offset+8+N: 6 × float32 bounding box (min XYZ, max XYZ)

    N = uint16_LE at offset+14; bbox starts at offset+8+N.
    """
    if offset + 40 > len(data):
        return None
    if data[offset:offset+4] != b'emaN' or data[offset+8:offset+12] != b'xoBB':
        return None

    n        = struct.unpack_from('<H', data, offset + 14)[0]
    bbox_off = offset + 8 + n
    if bbox_off + 24 > len(data):
        return None

    f = struct.unpack_from('<6f', data, bbox_off)
    if not _valid_bbox(f):
        return None

    name_len = n - 8
    name = data[offset+16:offset+16+name_len].decode('ascii', errors='replace').strip()
    return {'name': name, 'bbox_min': f[:3], 'bbox_max': f[3:]}

def parse_indb(data, chunk):
    off   = chunk['off']
    count = struct.unpack_from('<I', data, off)[0]
    return list(struct.unpack_from(f'<{count}I', data, off + 16))

def parse_skel(data, chunk):
    raw  = data[chunk['off']:chunk['off'] + chunk['sz']]
    n    = struct.unpack_from('<H', raw, 0)[0]
    pos  = 2
    bones = []
    for _ in range(n):
        nlen     = struct.unpack_from('<I', raw, pos)[0]
        name     = raw[pos+4:pos+4+nlen].decode('ascii')
        parent   = struct.unpack_from('<H', raw, pos+4+nlen)[0]
        fchild   = struct.unpack_from('<H', raw, pos+4+nlen+2)[0]
        nsibling = struct.unpack_from('<H', raw, pos+4+nlen+4)[0]
        mat      = struct.unpack_from('<16f', raw, pos+4+nlen+6)
        bones.append({
            'name':     name,
            'parent':   -1 if parent   == 0xFFFF else parent,
            'fchild':   -1 if fchild   == 0xFFFF else fchild,
            'nsibling': -1 if nsibling == 0xFFFF else nsibling,
            'tx': mat[12], 'ty': mat[13], 'tz': mat[14],
        })
        pos += nlen + 74
    return bones

def parse_mbuf(data, mbuf_chunks, n_bones):
    """
    Returns list of (secondary_bone_idx, w_primary, w_secondary) per vertex.
    secondary_bone_idx == -1 means no secondary influence.
    Chunks concatenated: [0] covers VerB[1] verts, [1] covers VerB[2] verts.
    """
    out = []
    for mc in mbuf_chunks:
        off = mc['off']
        vc  = struct.unpack_from('<I', data, off)[0]
        for v in range(vc):
            base  = off + 16 + v * 16
            b2    = data[base + 2]
            b4    = data[base + 4]
            b5    = data[base + 5]
            sec   = b5 if (b5 <= 60 and b5 < n_bones) else -1
            total = b2 + b4
            if sec == -1 or total == 0:
                out.append((-1, 1.0, 0.0))
            else:
                out.append((sec, b2 / total, b4 / total))
    return out

def parse_lods(data, mesh_chunks, indices):
    seen, lods = set(), []
    for mc in mesh_chunks:
        rec = read_name_bbox(data, mc['unk'])
        if rec is None:
            continue
        h      = struct.unpack_from('<16H', data, mc['off'] + 0x20)
        i0, ic = h[1], h[5]
        if ic == 0 or i0 + ic > len(indices):
            continue
        key = (i0, ic)
        if key in seen:
            continue
        seen.add(key)
        slc  = indices[i0:i0+ic]
        rb   = struct.unpack_from('<H', data, mc['off'] + 0x08)[0]
        name = rec['name'] or f"LOD{len(lods)}"
        lods.append({
            'label':     name,
            'bbox_min':  rec['bbox_min'],
            'bbox_max':  rec['bbox_max'],
            'v_min':     min(slc),
            'v_count':   max(slc) - min(slc) + 1,
            'tri_count': ic // 3,
            'indices':   slc,
            'root_bone': -1 if rb == 0xFFFF else rb,
        })
    order = {'LODS0': 0, 'LOD1': 1, 'LOD2': 2, 'LOD3': 3, 'LOD4': 4, 'LOD5': 5}
    lods.sort(key=lambda l: next(
        (v for k, v in order.items() if k in l['label']), 99))
    return lods


# ---------------------------------------------------------------------------
# Vertex decode
# ---------------------------------------------------------------------------

def decode_lod_verts(data, lod, vb0_off, attr_vbs):
    """
    Returns (pos_list, nrm_list, uv_list) , all post coordinate-transform.

    attr_vbs: list of (start_vi, data_off, stride) for each attribute VerB
              in order (VerB[1], VerB[2], ...). start_vi is the first global
              vertex index served by that buffer.
    """
    bmin, bmax = lod['bbox_min'], lod['bbox_max']
    v_min, n   = lod['v_min'], lod['v_count']
    pos, nrm, uv = [], [], []
    for vi in range(v_min, v_min + n):
        sx, sy, sz, _ = struct.unpack_from('<4h', data, vb0_off + vi*8)
        pos.append((
            _s16_bbox(sx, bmin[0], bmax[0]),
            _s16_bbox(sy, bmin[1], bmax[1]),
            -_s16_bbox(sz, bmin[2], bmax[2]),
        ))

        # Find which attribute buffer serves vi (last buffer whose start_vi <= vi)
        start_vi, base_off, stride = attr_vbs[0]
        for entry in attr_vbs[1:]:
            if vi >= entry[0]:
                start_vi, base_off, stride = entry
        ab = base_off + (vi - start_vi) * stride

        u32    = struct.unpack_from('<I', data, ab)[0]
        w_bits = (u32 >> 30) & 3
        nx_r, ny_r = struct.unpack_from('<2h', data, ab)
        nx = _s16(nx_r)
        ny = _s16(ny_r)
        nz = math.sqrt(max(0.0, 1.0 - nx*nx - ny*ny))
        if w_bits & 2:
            nz = -nz
        nrm.append((nx, ny, -nz))

        u0r, v0r = struct.unpack_from('<2h', data, ab + 4)
        uv.append((_s16(u0r), _s16(v0r)))

    return pos, nrm, uv


# ---------------------------------------------------------------------------
# Binary packing helpers
# ---------------------------------------------------------------------------

def pack_f32x3(arr):
    b = bytearray(len(arr) * 12)
    for i, (x, y, z) in enumerate(arr):
        struct.pack_into('<3f', b, i*12, x, y, z)
    return bytes(b)

def pack_f32x2(arr):
    b = bytearray(len(arr) * 8)
    for i, (u, v) in enumerate(arr):
        struct.pack_into('<2f', b, i*8, u, v)
    return bytes(b)

def minmax3(arr):
    xs, ys, zs = zip(*arr)
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


# ---------------------------------------------------------------------------
# Binary buffer manager
# ---------------------------------------------------------------------------

class BinBuf:
    """Collects all GLB buffer data; pads each view to 4-byte alignment."""

    def __init__(self):
        self.data  = bytearray()
        self.views = []

    def push(self, blob, target=None):
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data.extend(blob)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(blob)}
        if target is not None:
            bv["target"] = target
        self.views.append(bv)
        return len(self.views) - 1


# ---------------------------------------------------------------------------
# Main converter
# ---------------------------------------------------------------------------

def convert(src, out_dir=None, material=None, lod0_only=False):
    src  = Path(src)
    data = src.read_bytes()
    out  = Path(out_dir) if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)

    print(f"Converting : {src.name}  ({len(data):,} bytes)")

    chunks, ver = parse_chunks(data)
    for req in ('VerB', 'IndB', 'Mesh'):
        if req not in chunks:
            print(f"  Skipping: no {req} chunk (skeleton-only or non-mesh file)")
            return None
    if len(chunks['VerB']) < 2:
        raise ValueError("Expected at least 2 VerB chunks")

    vb0_off = chunks['VerB'][0]['off'] + 16

    # Build attr_vbs: list of (start_vi, data_off, stride) for VerB[1..N]
    attr_vbs = []
    cumulative = 0
    for vb in chunks['VerB'][1:]:
        cnt    = struct.unpack_from('<I', data, vb['off'])[0]
        stride = struct.unpack_from('<H', data, vb['off'] + 8)[0]
        attr_vbs.append((cumulative, vb['off'] + 16, stride))
        cumulative += cnt
    if not attr_vbs:
        raise ValueError("No attribute VerB chunks")

    all_indices = parse_indb(data, chunks['IndB'][0])
    lods        = parse_lods(data, chunks['Mesh'], all_indices)
    if not lods:
        raise ValueError("No named LODs found")

    if lod0_only:
        tier_order = ['LODS0', 'LOD1', 'LOD2', 'LOD3', 'LOD4', 'LOD5']
        non_shadow = [l for l in lods if 'Shadow' not in l['label']]
        best_tier  = next((t for t in tier_order
                           if any(t in l['label'] for l in non_shadow)), None)
        lods = [l for l in non_shadow if best_tier and best_tier in l['label']]
        if not lods:
            lods = non_shadow  # unusual label scheme , keep all non-shadow LODs

    bones   = parse_skel(data, chunks['Skel'][0]) if 'Skel' in chunks else []
    skinned = bool(bones and 'MBuf' in chunks)
    skin    = parse_mbuf(data, chunks['MBuf'], len(bones)) if skinned else None

    print(f"  burG v{ver[0]}.{ver[1]}  |  "
          f"LODs: {len(lods)}  |  bones: {len(bones)}  |  skinned: {skinned}")

    buf       = BinBuf()
    accessors = []
    nodes     = []
    meshes_j  = []
    skins_j   = []
    scene_top = []   # indices of top-level scene nodes

    # ----------------------------------------------------------------
    # Bone nodes  (node index == bone index)
    # ----------------------------------------------------------------
    for i, b in enumerate(bones):
        node = {
            "name":        b['name'],
            "translation": [b['tx'], b['ty'], -b['tz']],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
        }
        kids = []
        c = b['fchild']
        while c != -1:
            kids.append(c)
            c = bones[c]['nsibling']
        if kids:
            node["children"] = kids
        nodes.append(node)
        if b['parent'] == -1:
            scene_top.append(i)

    # ----------------------------------------------------------------
    # Skin + inverse bind matrices
    # Bind-pose positions are in world space.  IBM must invert the
    # *world* transform the bone has in the glTF node hierarchy , not
    # just the bone's local translation , so we accumulate ancestor
    # translations before negating.
    # ----------------------------------------------------------------
    if bones:
        # Compute world-space positions for every bone
        _world_cache = {}
        def _bone_world(idx):
            if idx in _world_cache:
                return _world_cache[idx]
            b = bones[idx]
            if b['parent'] == -1:
                _world_cache[idx] = (b['tx'], b['ty'], b['tz'])
            else:
                px, py, pz = _bone_world(b['parent'])
                _world_cache[idx] = (px + b['tx'], py + b['ty'], pz + b['tz'])
            return _world_cache[idx]

        for i in range(len(bones)):
            _bone_world(i)

        ibm_raw = bytearray()
        for i, b in enumerate(bones):
            wx, wy, wz = _world_cache[i]
            ibm_raw.extend(struct.pack('<16f',
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                -wx, -wy, wz, 1.0,
            ))
        ibm_bv  = buf.push(bytes(ibm_raw))
        ibm_acc = len(accessors)
        accessors.append({
            "bufferView":    ibm_bv,
            "componentType": FLOAT,
            "count":         len(bones),
            "type":          "MAT4",
        })
        root_node = next(i for i, b in enumerate(bones) if b['parent'] == -1)
        skins_j.append({
            "name":                src.stem,
            "joints":              list(range(len(bones))),
            "inverseBindMatrices": ibm_acc,
            "skeleton":            root_node,
        })

    # ----------------------------------------------------------------
    # LOD meshes
    # ----------------------------------------------------------------
    for lod in lods:
        label     = lod['label']
        v_min     = lod['v_min']
        v_count   = lod['v_count']
        tri_count = lod['tri_count']
        raw_idx   = lod['indices']
        root_bone = lod['root_bone']

        pos_arr, nrm_arr, uv_arr = decode_lod_verts(
            data, lod, vb0_off, attr_vbs)

        # Position (min/max required by spec)
        pmin, pmax = minmax3(pos_arr)
        p_bv  = buf.push(pack_f32x3(pos_arr), ARRAY_BUFFER)
        p_acc = len(accessors)
        accessors.append({"bufferView": p_bv, "componentType": FLOAT,
                          "count": v_count, "type": "VEC3",
                          "min": pmin, "max": pmax})

        # Normal
        n_bv  = buf.push(pack_f32x3(nrm_arr), ARRAY_BUFFER)
        n_acc = len(accessors)
        accessors.append({"bufferView": n_bv, "componentType": FLOAT,
                          "count": v_count, "type": "VEC3"})

        # TEXCOORD_0
        t_bv  = buf.push(pack_f32x2(uv_arr), ARRAY_BUFFER)
        t_acc = len(accessors)
        accessors.append({"bufferView": t_bv, "componentType": FLOAT,
                          "count": v_count, "type": "VEC2"})

        # Indices , winding reversed (a,b,c) -> (a,c,b) for handedness change
        idx_raw = bytearray(tri_count * 12)
        for t in range(tri_count):
            a = raw_idx[t*3+0] - v_min
            b = raw_idx[t*3+1] - v_min
            c = raw_idx[t*3+2] - v_min
            struct.pack_into('<3I', idx_raw, t*12, a, c, b)
        i_bv  = buf.push(bytes(idx_raw), ELEMENT_ARRAY_BUFFER)
        i_acc = len(accessors)
        accessors.append({"bufferView": i_bv, "componentType": UNSIGNED_INT,
                          "count": tri_count * 3, "type": "SCALAR"})

        attrs = {"POSITION": p_acc, "NORMAL": n_acc, "TEXCOORD_0": t_acc}

        # Skinning
        if skinned:
            # Primary joint: root_bone, or 0 (<root>) for multi-bone assemblies
            j0_def = root_bone if 0 <= root_bone < len(bones) else 0
            jdata  = bytearray(v_count * 4)
            wdata  = bytearray(v_count * 16)
            for li in range(v_count):
                vi       = v_min + li
                sec, w0, w1 = skin[vi] if vi < len(skin) else (-1, 1.0, 0.0)
                j0 = j0_def
                j1 = sec if sec != -1 else 0   # joint index 0 when weight is 0
                # normalise (parse_mbuf already does this, but clamp for safety)
                w0 = max(0.0, min(1.0, w0))
                w1 = max(0.0, min(1.0, w1))
                s  = w0 + w1
                if s > 1e-9:
                    w0, w1 = w0 / s, w1 / s
                else:
                    w0, w1 = 1.0, 0.0
                struct.pack_into('<4B', jdata, li*4,  j0, j1, 0, 0)
                struct.pack_into('<4f', wdata, li*16, w0, w1, 0.0, 0.0)

            j_bv  = buf.push(bytes(jdata), ARRAY_BUFFER)
            j_acc = len(accessors)
            accessors.append({"bufferView": j_bv, "componentType": UNSIGNED_BYTE,
                               "count": v_count, "type": "VEC4"})

            w_bv  = buf.push(bytes(wdata), ARRAY_BUFFER)
            w_acc = len(accessors)
            accessors.append({"bufferView": w_bv, "componentType": FLOAT,
                               "count": v_count, "type": "VEC4"})

            attrs["JOINTS_0"]  = j_acc
            attrs["WEIGHTS_0"] = w_acc

        prim = {"attributes": attrs, "indices": i_acc, "mode": 4}
        if material:
            prim["material"] = 0
        mesh_idx = len(meshes_j)
        meshes_j.append({"name": label, "primitives": [prim]})

        # Mesh node , no TRS (vertices are in skin space)
        mnode = {"name": label, "mesh": mesh_idx}
        if skinned:
            mnode["skin"] = 0
        scene_top.append(len(nodes))
        nodes.append(mnode)

        tag = "  [skinned]" if skinned else ""
        print(f"  {label:<40} {v_count:>5} verts  {tri_count:>5} tris{tag}")

    # ----------------------------------------------------------------
    # Assemble glTF JSON
    # ----------------------------------------------------------------
    gltf = {
        "asset":       {"version": "2.0", "generator": "modelbin_to_glb.py"},
        "scene":       0,
        "scenes":      [{"nodes": scene_top}],
        "nodes":       nodes,
        "meshes":      meshes_j,
        "accessors":   accessors,
        "bufferViews": buf.views,
        "buffers":     [{"byteLength": len(buf.data)}],
    }
    if skins_j:
        gltf["skins"] = skins_j

    if material:
        pbr = {
            "baseColorFactor": material.get('base_color', [1.0, 1.0, 1.0, 1.0]),
            "metallicFactor":  material.get('metallic', 0.0),
            "roughnessFactor": material.get('roughness', 0.5),
        }
        mat_j = {
            "name":                 material.get('name', 'default'),
            "pbrMetallicRoughness": pbr,
            "doubleSided":          True,
        }
        images_j   = []
        textures_j = []

        def _add_tex(uri):
            idx = len(images_j)
            images_j.append({"uri": uri})
            textures_j.append({"source": idx})
            return len(textures_j) - 1

        if material.get('normal_uri'):
            mat_j["normalTexture"] = {"index": _add_tex(material['normal_uri'])}
        if material.get('occlusion_uri'):
            mat_j["occlusionTexture"] = {
                "index": _add_tex(material['occlusion_uri']), "strength": 1.0}

        gltf["materials"] = [mat_j]
        if images_j:
            gltf["images"]   = images_j
            gltf["textures"] = textures_j

    # ----------------------------------------------------------------
    # Pack GLB
    # ----------------------------------------------------------------
    json_b = json.dumps(gltf, separators=(',', ':')).encode()
    while len(json_b) % 4:        # pad JSON chunk with spaces
        json_b += b' '

    bin_b = bytes(buf.data)
    while len(bin_b) % 4:         # pad BIN chunk with zeros
        bin_b += b'\x00'

    total    = 12 + 8 + len(json_b) + 8 + len(bin_b)
    out_path = out / f"{src.stem}.glb"
    with open(out_path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))     # GLB header
        f.write(struct.pack('<II',  len(json_b), 0x4E4F534A))  # JSON chunk
        f.write(json_b)
        f.write(struct.pack('<II',  len(bin_b),  0x004E4942))  # BIN\0 chunk
        f.write(bin_b)

    print(f"\n  -> {out_path.name}  ({total:,} bytes)")
    return out_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    try:
        convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        print("Done.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
