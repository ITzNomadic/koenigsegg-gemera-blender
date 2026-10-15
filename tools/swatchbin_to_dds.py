#!/usr/bin/env python3
"""
swatchbin_to_dds.py
-------------------
Converts .swatchbin files (burG container, TXCB chunk) to DDS + PGM.

Format detection via TXCH field at HCXT+72:
  0  -> BC4_UNORM  (ATI1)         impact / splatter masks
  3  -> BC4_UNORM  (ATI1)         livery masks, ground AO
  4  -> BC4_UNORM  (ATI1)         ground AO variant (possibly BC4_SNORM)
  5  -> BC5_UNORM  (ATI2)         normal maps
  9  -> BC7_UNORM  (DX10 fmt 98)  base colour / RGBA
  11 -> R16G16B16A16_UNORM        (DX10 fmt 11) proxy LOD
  13 -> R8G8B8A8_UNORM            (DX10 fmt 28) wiper masks
  19 -> R8_UNORM                  AO maps (also writes .pgm for direct view)

Usage:
    python swatchbin_to_dds.py <file.swatchbin> [output_dir]
"""

import struct, sys, math
from pathlib import Path

# --------------------------------------------------------------------------
# DDS constants
# --------------------------------------------------------------------------
DDPF_FOURCC    = 0x00000004
DDPF_LUMINANCE = 0x00020000
DDSD_CAPS        = 0x00000001
DDSD_HEIGHT      = 0x00000002
DDSD_WIDTH       = 0x00000004
DDSD_PITCH       = 0x00000008
DDSD_PIXELFORMAT = 0x00001000
DDSD_LINEARSIZE  = 0x00080000
DDSD_MIPMAPCOUNT = 0x00020000
DDSCAPS_TEXTURE  = 0x00001000
DDSCAPS_MIPMAP   = 0x00400000
DDSCAPS_COMPLEX  = 0x00000008

# --------------------------------------------------------------------------
# Format table  field74 -> descriptor
# --------------------------------------------------------------------------
FORMATS = {
    0:  dict(name='BC4_UNORM',           fourcc=b'ATI1', dxgi=None, bpb=8,  block=4),
    3:  dict(name='BC4_UNORM',           fourcc=b'ATI1', dxgi=None, bpb=8,  block=4),
    4:  dict(name='BC4_UNORM',           fourcc=b'ATI1', dxgi=None, bpb=8,  block=4),
    5:  dict(name='BC5_UNORM',           fourcc=b'ATI2', dxgi=None, bpb=16, block=4),
    9:  dict(name='BC7_UNORM',           fourcc=b'DX10', dxgi=98,   bpb=16, block=4),
    11: dict(name='R16G16B16A16_UNORM',  fourcc=b'DX10', dxgi=11,   bpb=8,  block=1),
    13: dict(name='R8G8B8A8_UNORM',      fourcc=b'DX10', dxgi=28,   bpb=4,  block=1),
    19: dict(name='R8_UNORM',            fourcc=None,    dxgi=None,  bpb=1,  block=1),
}

def mip_size(w, h, fmt):
    if fmt['block'] == 4:
        return max(1, (w+3)//4) * max(1, (h+3)//4) * fmt['bpb']
    return w * h * fmt['bpb']

# --------------------------------------------------------------------------
# burG / TXCH parser
# --------------------------------------------------------------------------
def parse_swatchbin(data):
    if data[:4] != b'burG':
        raise ValueError(f"Not a burG file (magic={data[:4]!r})")

    n_chunks = struct.unpack_from('<I', data, 0x10)[0]
    # Find TXCB chunk  (stored on disk as b'BCXT', reversed tag = TXCB)
    chunk = None
    pos = 0x14
    for _ in range(n_chunks):
        raw_id = data[pos:pos+4]
        if raw_id == b'BCXT':
            chunk = dict(
                off  = struct.unpack_from('<I', data, pos+12)[0],
                size = struct.unpack_from('<I', data, pos+16)[0],
                meta = struct.unpack_from('<I', data, pos+8)[0],
            )
        pos += 24
    if chunk is None:
        raise ValueError("No TXCB chunk found")

    # TXCH metadata  (stored on disk as b'HCXT')
    m = chunk['meta']
    if data[m:m+4] != b'HCXT':
        raise ValueError(f"Expected HCXT at 0x{m:X}, got {data[m:m+4]!r}")

    w         = struct.unpack_from('<I', data, m + 0x20)[0]
    h         = struct.unpack_from('<I', data, m + 0x24)[0]
    mip_count = data[m + 0x2E]
    fmt_id    = struct.unpack_from('<I', data, m + 0x48)[0]

    return w, h, mip_count, fmt_id, data[chunk['off'] : chunk['off'] + chunk['size']]


# --------------------------------------------------------------------------
# DDS builder
# --------------------------------------------------------------------------
def build_dds(w, h, mip_count, fmt, payload):
    hdr = bytearray(124)
    def u32(off, v): struct.pack_into('<I', hdr, off, v & 0xFFFFFFFF)
    def fcc(off, b): hdr[off:off+4] = b[:4]

    compressed = (fmt['block'] == 4)
    base       = mip_size(w, h, fmt)

    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    caps  = DDSCAPS_TEXTURE
    if mip_count > 1:
        flags |= DDSD_MIPMAPCOUNT
        caps  |= DDSCAPS_MIPMAP | DDSCAPS_COMPLEX

    if compressed:
        flags |= DDSD_LINEARSIZE
        pitch_or_linear = base
    else:
        flags |= DDSD_PITCH
        pitch_or_linear = w * fmt['bpb']

    u32(0, 124)              # dwSize
    u32(4, flags)
    u32(8, h)
    u32(12, w)
    u32(16, pitch_or_linear)
    u32(20, 0)               # dwDepth
    u32(24, mip_count)
    # dwReserved1[11]: zeros (bytes 28-71)

    # DDS_PIXELFORMAT at byte 72
    u32(72, 32)              # pfSize
    if fmt['name'] == 'R8_UNORM':
        u32(76, DDPF_LUMINANCE)
        u32(80, 0)           # dwFourCC = 0
        u32(84, 8)           # dwRGBBitCount
        u32(88, 0xFF)        # dwRBitMask
    else:
        u32(76, DDPF_FOURCC)
        fcc(80, fmt['fourcc'])

    u32(104, caps)           # dwCaps

    parts = [b'DDS ', bytes(hdr)]

    if fmt.get('dxgi'):
        dx10 = struct.pack('<5I', fmt['dxgi'], 3, 0, 1, 0)
        parts.append(dx10)

    parts.append(payload)
    return b''.join(parts)


# --------------------------------------------------------------------------
# PGM writer for R8 (lets you open without a DDS viewer)
# --------------------------------------------------------------------------
def write_pgm(path, w, h, data):
    with open(path, 'wb') as f:
        f.write(f"P5\n{w} {h}\n255\n".encode())
        f.write(data[:w*h])


# --------------------------------------------------------------------------
# BC4 decoder (for verification PGM of livery masks)
# --------------------------------------------------------------------------
def decode_bc4_block(blk):
    e0, e1 = blk[0], blk[1]
    if e0 > e1:
        lut = [e0, e1,
               (6*e0+1*e1)//7, (5*e0+2*e1)//7,
               (4*e0+3*e1)//7, (3*e0+4*e1)//7,
               (2*e0+5*e1)//7, (1*e0+6*e1)//7]
    else:
        lut = [e0, e1,
               (4*e0+1*e1)//5, (3*e0+2*e1)//5,
               (2*e0+3*e1)//5, (1*e0+4*e1)//5,
               0, 255]
    bits = int.from_bytes(blk[2:8], 'little')
    return [lut[(bits >> (3*i)) & 7] for i in range(16)]


def decode_bc4_image(w, h, data):
    out = bytearray(w * h)
    bw, bh = (w+3)//4, (h+3)//4
    for by in range(bh):
        for bx in range(bw):
            blk = data[(by*bw+bx)*8 : (by*bw+bx)*8+8]
            texels = decode_bc4_block(blk)
            for ty in range(4):
                for tx in range(4):
                    px, py = bx*4+tx, by*4+ty
                    if px < w and py < h:
                        out[py*w+px] = texels[ty*4+tx]
    return bytes(out)


# --------------------------------------------------------------------------
# Main converter
# --------------------------------------------------------------------------
def convert(src_path, out_dir=None):
    src  = Path(src_path)
    data = src.read_bytes()
    out  = Path(out_dir) if out_dir else src.parent
    out.mkdir(parents=True, exist_ok=True)

    w, h, mip_count, fmt_id, payload = parse_swatchbin(data)

    fmt = FORMATS.get(fmt_id)
    if fmt is None:
        print(f"  WARNING: unknown format id {fmt_id} , writing raw payload")
        (out / f"{src.stem}.bin").write_bytes(payload)
        return

    total = sum(mip_size(max(1,w>>(m)), max(1,h>>(m)), fmt) for m in range(mip_count))
    print(f"  {src.name}")
    print(f"  {w}x{h}  mips={mip_count}  fmt={fmt_id} ({fmt['name']})")
    print(f"  payload={len(payload)} B  expected={total} B  {'OK' if len(payload)==total else 'MISMATCH!'}")

    dds_path = out / f"{src.stem}.dds"
    dds_path.write_bytes(build_dds(w, h, mip_count, fmt, payload))
    print(f"  -> {dds_path.name}")

    if fmt['name'] == 'R8_UNORM':
        pgm_path = out / f"{src.stem}.pgm"
        write_pgm(pgm_path, w, h, payload)
        print(f"  -> {pgm_path.name}")

    if fmt['name'] == 'BC4_UNORM':
        pgm_path = out / f"{src.stem}.pgm"
        decoded = decode_bc4_image(w, h, payload)
        write_pgm(pgm_path, w, h, decoded)
        print(f"  -> {pgm_path.name}  (BC4 decoded)")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
