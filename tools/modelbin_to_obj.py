#!/usr/bin/env python3
"""
modelbin_to_obj.py
------------------
Converts .modelbin files (burG format, Forza Horizon 6) to Wavefront OBJ + MTL,
exporting every geometry LOD as a separately labelled file.

Usage:
    python modelbin_to_obj.py <file.modelbin> [output_dir]

Output (example for hood_a.modelbin):
    hood_a_LODS0.obj / .mtl   highest detail (2391 verts, 4328 tris)
    hood_a_LOD1.obj  / .mtl
    hood_a_LOD2.obj  / .mtl
    hood_a_LOD3.obj  / .mtl
    hood_a_LOD4.obj  / .mtl
    hood_a_LOD5.obj  / .mtl   lowest detail (23 verts, 19 tris)
    hood_a_info.txt            conversion summary

Shadow mesh duplicates (same index range, different render pass) are
suppressed automatically.

Decoded attributes
------------------
  Positions  VerB[0] stride=8
             3 × SNORM16 decoded against per-mesh BBox; W unused
  Normals    VerB[1/2] bytes  0-3
             2 × SNORM16 → NX, NY
             NZ = sqrt(1 - NX² - NY²)
             NZ sign from bits[30:31] of the same uint32: bit1 set → NZ = -NZ
  UV0        VerB[1/2] bytes  4-7   2 × SNORM16
  UV1        VerB[1/2] bytes  8-11  2 × SNORM16 (lightmap / detail)
  AO mask    VerB[1/2] byte  36     unsigned byte; written as MTL Kd hint

Vertex buffer routing
---------------------
  vi  0 .. 3259  →  VerB[1]  (normals, UVs, colour for LODs 0-4)
  vi 3260 .. end →  VerB[2]  (normals, UVs, colour for LOD5 / shadow proxy)
  All vi          →  VerB[0]  (positions, all LODs)

Skinning sidecar
----------------
When MBuf and Skel chunks are present, each LOD also produces:
    <label>_weights.txt   per-vertex bone assignment and blend weights

Format (tab-separated):
    # vi  bone0  weight0  bone1  weight1
    0     boneTrunk  1.0000  (null)             0.0000
    1     boneTrunk  0.9324  boneAimStrutUpperLR  0.0676
    ...

  bone0   = primary bone (from Mesh chunk root_bone field, constant per LOD)
  bone1   = secondary bone (b[5] raw byte as global index; "(null)" if >60)
  weight0 = b[2] / (b[2]+b[4]) , normalised
  weight1 = b[4] / (b[2]+b[4])

Multi-bone assemblies (root_bone=0xFFFF, e.g. door hinges) list bone0 as
"multi_bone"; secondary bone is still decoded from b[5].

Unknowns (not decoded , see burG_format_spec.txt)
--------------------------------------------------
  VerB[1/2] bytes 24-35  Tangent frame (12 bytes); recalculate in DCC tool
  VerB[1/2] bits[30]     W-bit 0; function unknown
  UV2-UV4                Bytes 12-23; UV4 always zero
  MBuf b[0],b[1],b[3]   Role not fully decoded (additional weight precision?)
"""

import struct
import sys
import math
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fourcc(data, offset):
    return data[offset:offset+4][::-1].decode('ascii', errors='replace')

def _snorm16_bbox(v, bmin, bmax):
    """Signed int16 decoded against a bounding box to a float position."""
    return bmin + (v + 32768) / 65535.0 * (bmax - bmin)

def _snorm16(v):
    """Signed int16 normalised to [-1, 1]."""
    return v / 32767.0


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------

def parse_skel(data, skel_chunk):
    """
    Parse the Skel chunk and return one dict per bone.

    Skel layout:
        uint16   bone_count
        [bone_count × bone_record]

    Bone record (variable size = name_len + 74 bytes):
        uint32      name_len
        char[N]     name (ASCII, no null terminator)
        uint16      parent_index     (0xFFFF = no parent)
        uint16      first_child_index (0xFFFF = leaf)
        uint16      next_sibling_index (0xFFFF = last sibling)
        float32[16] bind_pose_matrix (4×4 row-major, DirectX convention)
                    Translation in row 3: mat[12]=Tx, mat[13]=Ty, mat[14]=Tz
                    Rows 0-2 are the rotation/scale axes.
                    Column 3 is always [0, 0, 0, 1].

    Returns list of dicts: name, parent, first_child, next_sibling, matrix.
    Indices use -1 for "none".
    """
    off  = skel_chunk['off']
    skel = data[off:off + skel_chunk['sz']]

    bone_count = struct.unpack_from('<H', skel, 0)[0]
    bones = []
    pos   = 2

    for _ in range(bone_count):
        nlen     = struct.unpack_from('<I', skel, pos)[0]
        name     = skel[pos+4:pos+4+nlen].decode('ascii')
        parent   = struct.unpack_from('<H', skel, pos+4+nlen)[0]
        fchild   = struct.unpack_from('<H', skel, pos+4+nlen+2)[0]
        nsibling = struct.unpack_from('<H', skel, pos+4+nlen+4)[0]
        matrix   = struct.unpack_from('<16f', skel, pos+4+nlen+6)

        bones.append({
            'name':         name,
            'parent':       -1 if parent   == 0xFFFF else parent,
            'first_child':  -1 if fchild   == 0xFFFF else fchild,
            'next_sibling': -1 if nsibling == 0xFFFF else nsibling,
            'matrix':       matrix,
        })
        pos += nlen + 74

    return bones


# ---------------------------------------------------------------------------
# Skinning (MBuf)
# ---------------------------------------------------------------------------

def parse_mbuf(data, mbuf_chunks, bones):
    """
    Parse MBuf skinning data. Returns a flat list, one entry per vertex
    (MBuf chunks concatenated in order: [0] covers VerB[1] verts, [1] covers
    VerB[2] verts for dual-MBuf assemblies like doors).

    Each entry is a 3-tuple:
        (secondary_bone_name_or_None, w_primary, w_secondary)

    Primary bone is NOT stored per-vertex , it comes from the Mesh chunk
    root_bone field and is constant per LOD. See write_weights_sidecar().

    Encoding (confirmed across BMW single- and multi-bone meshes):
        b[5] raw  = secondary bone global index (>60 = no second influence)
        b[2]      = proportional weight for influence 0 (un-normalised)
        b[4]      = proportional weight for influence 1 (un-normalised)
        Normalised: w0 = b2/(b2+b4),  w1 = b4/(b2+b4)
    """
    entries = []
    for mc in mbuf_chunks:
        off = mc['off']
        vc  = struct.unpack_from('<I', data, off)[0]
        for v in range(vc):
            base = off + 16 + v * 16
            b2   = data[base + 2]
            b4   = data[base + 4]
            b5   = data[base + 5]
            sec  = bones[b5]['name'] if (b5 <= 60 and b5 < len(bones)) else None
            total = b2 + b4
            if sec is None or total == 0:
                entries.append((None, 1.0, 0.0))
            else:
                entries.append((sec, b2 / total, b4 / total))
    return entries


# ---------------------------------------------------------------------------
# Chunk table
# ---------------------------------------------------------------------------

def parse_chunk_table(data):
    if data[0:4] != b'burG':
        raise ValueError(f"Not a .modelbin file (bad magic: {data[0:4]!r})")
    version = struct.unpack_from('<HH', data, 4)
    n       = struct.unpack_from('<I',  data, 16)[0]
    chunks  = []
    pos = 0x14
    for _ in range(n):
        chunks.append(dict(
            id    = _fourcc(data, pos),
            flags = struct.unpack_from('<I', data, pos + 4)[0],
            unk   = struct.unpack_from('<I', data, pos + 8)[0],
            off   = struct.unpack_from('<I', data, pos + 12)[0],
            sz    = struct.unpack_from('<I', data, pos + 16)[0],
        ))
        pos += 24
    return chunks, version


# ---------------------------------------------------------------------------
# Name / BBox metadata
# ---------------------------------------------------------------------------

def parse_name_bboxes(data):
    """
    Locate every Name+BBox metadata record.

    Layout (at any 'emaN' offset where offset+8 holds 'xoBB'):
        +0   4B  'emaN'
        +4   4B  record flags
        +8   4B  'xoBB' sub-tag
        +12  4B  sub-chunk flags
        +16  NB  mesh name (ASCII, no null)
        +16+N 24B  6 × float32: bbox_min XYZ, bbox_max XYZ

    Returns dict: file_offset_of_emaN -> {name, bbox_min, bbox_max}
    """
    results = {}
    pos = 0
    while pos < len(data) - 52:
        if data[pos:pos+4] == b'emaN' and data[pos+8:pos+12] == b'xoBB':
            j = pos + 16
            while j < pos + 80 and 32 <= data[j] < 127:
                j += 1
            name = data[pos+16:j].decode('ascii', errors='replace').strip()
            if len(name) >= 3 and j + 24 <= len(data):
                f = struct.unpack_from('<6f', data, j)
                if (all(v == v for v in f) and
                        all(-500 < v < 500 for v in f) and
                        f[3] >= f[0] and f[4] >= f[1] and f[5] >= f[2]):
                    results[pos] = {
                        'name':     name,
                        'bbox_min': f[:3],
                        'bbox_max': f[3:],
                    }
        pos += 1
    return results


# ---------------------------------------------------------------------------
# Index buffer
# ---------------------------------------------------------------------------

def parse_indb(data, chunk):
    off   = chunk['off']
    count = struct.unpack_from('<I', data, off)[0]
    return list(struct.unpack_from(f'<{count}I', data, off + 16))


# ---------------------------------------------------------------------------
# Vertex decode
# ---------------------------------------------------------------------------

def make_vertex_decoder(data, vb0_off, vb1_off, vb2_off, vb1_count):
    """
    Returns a decode function: vi -> vertex dict.

    Vertex buffer routing:
        vi  < vb1_count  → VerB[1]  (LODs 0-4)
        vi >= vb1_count  → VerB[2]  (LOD5 / shadow proxy)
    All positions come from VerB[0] regardless.
    """
    def decode(vi, bbox_min, bbox_max):
        # --- Position (VerB[0], stride=8) ---
        sx, sy, sz, _ = struct.unpack_from('<4h', data, vb0_off + vi * 8)
        pos = (
            _snorm16_bbox(sx, bbox_min[0], bbox_max[0]),
            _snorm16_bbox(sy, bbox_min[1], bbox_max[1]),
            _snorm16_bbox(sz, bbox_min[2], bbox_max[2]),
        )

        # --- Attribute buffer routing ---
        if vi < vb1_count:
            attr_base = vb1_off + vi * 40
        else:
            attr_base = vb2_off + (vi - vb1_count) * 40

        # Normal (bytes 0-3)
        u32      = struct.unpack_from('<I', data, attr_base)[0]
        w_bits   = (u32 >> 30) & 3
        nx_r, ny_r = struct.unpack_from('<2h', data, attr_base)
        nx = _snorm16(nx_r)
        ny = _snorm16(ny_r)
        nz = math.sqrt(max(0.0, 1.0 - nx*nx - ny*ny))
        if w_bits & 2:
            nz = -nz

        # UV0 (bytes 4-7)
        u0_r, v0_r = struct.unpack_from('<2h', data, attr_base + 4)
        uv0 = (_snorm16(u0_r), _snorm16(v0_r))

        # UV1 (bytes 8-11)
        u1_r, v1_r = struct.unpack_from('<2h', data, attr_base + 8)
        uv1 = (_snorm16(u1_r), _snorm16(v1_r))

        # AO mask (byte 36, unsigned)
        ao = data[attr_base + 36] / 255.0

        return {
            'pos':    pos,
            'normal': (nx, ny, nz),
            'uv0':    uv0,
            'uv1':    uv1,
            'ao':     ao,
        }

    return decode


# ---------------------------------------------------------------------------
# LOD parsing
# ---------------------------------------------------------------------------

def parse_lods(data, mesh_chunks, name_bboxes, all_indices):
    """
    Extract LOD descriptors from Mesh chunks.

    Mesh header (uint16 LE at chunk_data + 0x20):
        [1] = index_start
        [5] = index_count

    Deduplicates on (index_start, index_count) to suppress shadow pass copies.
    """
    seen   = set()
    lods   = []

    for mc in mesh_chunks:
        rec = name_bboxes.get(mc['unk'])
        if rec is None:
            continue
        h         = struct.unpack_from('<16H', data, mc['off'] + 0x20)
        idx_start = h[1]
        idx_count = h[5]
        if idx_count == 0 or idx_start + idx_count > len(all_indices):
            continue
        key = (idx_start, idx_count)
        if key in seen:
            continue
        seen.add(key)

        slc      = all_indices[idx_start : idx_start + idx_count]
        v_min    = min(slc)
        v_max    = max(slc)
        rb_raw   = struct.unpack_from('<H', data, mc['off'] + 0x08)[0]
        root_bone = -1 if rb_raw == 0xFFFF else rb_raw

        lods.append({
            'label':     rec['name'],
            'bbox_min':  rec['bbox_min'],
            'bbox_max':  rec['bbox_max'],
            'idx_start': idx_start,
            'idx_count': idx_count,
            'tri_count': idx_count // 3,
            'v_min':     v_min,
            'v_count':   v_max - v_min + 1,
            'indices':   slc,
            'root_bone': root_bone,
        })

    _order = {'LODS0': 0, 'LOD1': 1, 'LOD2': 2,
              'LOD3': 3, 'LOD4': 4, 'LOD5': 5}
    lods.sort(key=lambda l: next(
        (v for k, v in _order.items() if k in l['label']), 99))
    return lods


# ---------------------------------------------------------------------------
# Weights sidecar writer
# ---------------------------------------------------------------------------

def write_weights_sidecar(out_dir, lod, skin_entries, bones):
    """Write <label>_weights.txt with per-vertex bone assignments."""
    label     = lod['label']
    v_min     = lod['v_min']
    v_count   = lod['v_count']
    root_bone = lod.get('root_bone', -1)

    if 0 <= root_bone < len(bones):
        primary = bones[root_bone]['name']
    elif root_bone == -1:
        primary = 'multi_bone'
    else:
        primary = f'bone_{root_bone}'

    path = out_dir / f"{label}_weights.txt"
    with open(path, 'w') as f:
        f.write(f"# {label} skinning weights\n")
        f.write(f"# primary bone: {primary}\n")
        f.write(f"# vi\tbone0\tweight0\tbone1\tweight1\n")
        for i in range(v_count):
            vi = v_min + i
            if vi >= len(skin_entries):
                break
            sec, w0, w1 = skin_entries[vi]
            sec_str = sec if sec else '(null)'
            f.write(f"{i}\t{primary}\t{w0:.4f}\t{sec_str}\t{w1:.4f}\n")
    return path


# ---------------------------------------------------------------------------
# OBJ + MTL writer
# ---------------------------------------------------------------------------

def write_lod(out_dir, lod, decode_vertex):
    label     = lod['label']
    obj_path  = out_dir / f"{label}.obj"
    mtl_name  = f"{label}.mtl"
    mtl_path  = out_dir / mtl_name

    bbox_min  = lod['bbox_min']
    bbox_max  = lod['bbox_max']
    v_min     = lod['v_min']
    v_count   = lod['v_count']
    indices   = lod['indices']
    tri_count = lod['tri_count']

    verts = [decode_vertex(vi, bbox_min, bbox_max)
             for vi in range(v_min, v_min + v_count)]

    ao_avg = sum(v['ao'] for v in verts) / len(verts)

    # MTL
    with open(mtl_path, 'w') as f:
        f.write(f"# {label}\n\n")
        f.write(f"newmtl {label}_mat\n")
        f.write(f"# AO mask (vertex colour R): avg={ao_avg:.3f}  "
                f"range [69..109] / 255\n")
        f.write(f"Kd {ao_avg:.4f} {ao_avg:.4f} {ao_avg:.4f}\n")
        f.write(f"Ka 0.05 0.05 0.05\n")
        f.write(f"Ks 0.8 0.8 0.8\n")
        f.write(f"Ns 96.0\n")

    # OBJ
    with open(obj_path, 'w') as f:
        f.write(f"# {label}\n")
        f.write(f"# Vertices : {v_count}\n")
        f.write(f"# Triangles: {tri_count}\n")
        f.write(f"# Normals  : SNORM16x2 + W-bit NZ sign (bit1)\n")
        f.write(f"# UV0      : SNORM16x2\n")
        f.write(f"# Tangents : NOT decoded , recalculate from UV0 in DCC tool\n\n")

        f.write(f"mtllib {mtl_name}\n")
        f.write(f"o {label}\n\n")

        for v in verts:
            x, y, z = v['pos']
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        f.write("\n")

        for v in verts:
            u, vv = v['uv0']
            f.write(f"vt {u:.6f} {vv:.6f}\n")
        f.write("\n")

        for v in verts:
            nx, ny, nz = v['normal']
            f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
        f.write("\n")

        f.write(f"usemtl {label}_mat\n")
        for t in range(tri_count):
            a = indices[t*3+0] - v_min + 1
            b = indices[t*3+1] - v_min + 1
            c = indices[t*3+2] - v_min + 1
            f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")

    return obj_path


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

def convert(modelbin_path, output_dir=None):
    modelbin_path = Path(modelbin_path)
    if not modelbin_path.exists():
        raise FileNotFoundError(f"File not found: {modelbin_path}")

    data      = modelbin_path.read_bytes()
    base_name = modelbin_path.stem
    out_dir   = Path(output_dir) if output_dir else modelbin_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Converting : {modelbin_path.name}  ({len(data):,} bytes)")

    chunks, version = parse_chunk_table(data)
    print(f"Format     : burG v{version[0]}.{version[1]},  {len(chunks)} chunks")

    by_id = {}
    for c in chunks:
        by_id.setdefault(c['id'], []).append(c)

    for req in ('VerB', 'IndB', 'Mesh'):
        if req not in by_id:
            raise ValueError(f"Missing required chunk: {req}")

    if len(by_id['VerB']) < 2:
        raise ValueError("Expected at least 2 VerB chunks (positions + attributes)")

    # VerB[0] = positions (stride=8)
    # VerB[1] = attributes for vi < vb1_count (stride=40)
    # VerB[2] = attributes for vi >= vb1_count, if present (stride=40)
    vb0      = by_id['VerB'][0]
    vb1      = by_id['VerB'][1]
    vb2      = by_id['VerB'][2] if len(by_id['VerB']) > 2 else None

    vb0_off    = vb0['off'] + 16
    vb1_off    = vb1['off'] + 16
    vb1_count  = struct.unpack_from('<I', data, vb1['off'])[0]
    vb2_off    = (vb2['off'] + 16) if vb2 else vb1_off  # fallback

    decode_vertex = make_vertex_decoder(
        data, vb0_off, vb1_off, vb2_off, vb1_count)

    name_bboxes = parse_name_bboxes(data)
    all_indices = parse_indb(data, by_id['IndB'][0])
    lods        = parse_lods(data, by_id['Mesh'], name_bboxes, all_indices)

    if not lods:
        raise ValueError("No named LODs found")

    # Skinning , optional; silently skipped if Skel or MBuf absent
    bones        = parse_skel(data, by_id['Skel'][0]) if 'Skel' in by_id else []
    skin_entries = (parse_mbuf(data, by_id['MBuf'], bones)
                    if ('MBuf' in by_id and bones) else None)

    print(f"LODs       : {[l['label'] for l in lods]}\n")

    info = [
        f"Source  : {modelbin_path.name}",
        f"Format  : burG v{version[0]}.{version[1]}",
        f"LODs    : {len(lods)}",
        "",
        f"  {'Label':<20} {'Verts':>6} {'Tris':>6}  BBox",
        f"  {'-'*20} {'-'*6} {'-'*6}  {'-'*52}",
    ]

    exported = []
    for lod in lods:
        obj_path = write_lod(out_dir, lod, decode_vertex)
        if skin_entries is not None:
            write_weights_sidecar(out_dir, lod, skin_entries, bones)
        bmin, bmax = lod['bbox_min'], lod['bbox_max']
        skin_tag = '' if skin_entries is None else '  [skinned]'
        line = (f"  {lod['label']:<38} "
                f"{lod['v_count']:>5} verts  {lod['tri_count']:>5} tris{skin_tag}")
        print(line)
        exported.append(obj_path.name)
        info.append(
            f"  {lod['label']:<20} {lod['v_count']:>6} {lod['tri_count']:>6}"
            f"  X[{bmin[0]:.3f}..{bmax[0]:.3f}]"
            f" Y[{bmin[1]:.3f}..{bmax[1]:.3f}]"
            f" Z[{bmin[2]:.3f}..{bmax[2]:.3f}]"
        )

    info_path = out_dir / f"{base_name}_info.txt"
    info_path.write_text("\n".join(info) + "\n")
    print(f"\n  {info_path.name}")
    return exported


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    try:
        files = convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"\nDone. {len(files)} OBJ files written.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
