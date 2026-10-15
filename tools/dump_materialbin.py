#!/usr/bin/env python3
"""
dump_materialbin.py: Decode a .materialbin file (burG container).

Usage:
    python tools/dump_materialbin.py <file.materialbin> [--hex]

--hex   Print raw hex dump of every chunk payload alongside decoded output.

Decodes:
  MATL chunk: shaderbin path
  RPTM chunk: 5 colour-parameter groups (partial , group preambles contain
              parameter-identity hashes whose hash function is not yet known;
              see CLAUDE.md section "materialbin" for the open research item)

Exit code 0 on success, 1 on error.
"""

import struct, sys
from pathlib import Path


# ── burG container parser ─────────────────────────────────────────────────────

def parse_burg(data):
    if data[:4] != b'burG':
        raise ValueError(f"not a burG file (magic={data[:4]!r})")
    chunk_count = struct.unpack_from('<I', data, 16)[0]
    chunks = {}
    for i in range(chunk_count):
        base = 20 + i * 24
        raw_id, flags, meta_ptr, offset, csize, usize = struct.unpack_from('<4sIIIII', data, base)
        tag = raw_id[::-1].decode('ascii', errors='replace')
        chunks[tag] = {
            'payload':  data[offset:offset + csize],
            'meta_ptr': meta_ptr,
            'flags':    flags,
            'offset':   offset,
            'size':     csize,
        }
    return chunks


# ── MATL chunk decoder ────────────────────────────────────────────────────────

def decode_matl(payload):
    """Return the null-terminated shader path string."""
    null = payload.find(b'\x00')
    return payload[:null].decode('latin-1') if null != -1 else payload.decode('latin-1')


# ── RPTM chunk decoder ────────────────────────────────────────────────────────

# Empirically determined RPTM layout for carpaint_calibrated materials (197 bytes):
#   byte 0:     group_count  (always 5)
#   then 5 groups, each starting with a 2-byte header "03 04":
#     bytes 0-1:   03 04 (type / count marker, meaning not fully decoded)
#     bytes 2-27:  26-byte constant preamble (contains parameter-identity hashes)
#     bytes 28+:   varying float32 values (one or three RGB + optional constant alpha)
#
# Group positions (offsets of the "03 04" header within RPTM):
#   Group 0:  RPTM[1]    data [3..33)  1×f32 at data[26]
#   Group 1:  RPTM[33]   data [35..77) 3×f32 (RGB) at data[26], f32(1.0) at data[38]
#   Group 2:  RPTM[77]   data [79..109) 1×f32 at data[26]
#   Group 3:  RPTM[109]  data [111..153) 3×f32 (RGB) at data[26], f32(1.0) at data[38]
#   Group 4:  RPTM[153]  data [155..189) 2×f32 at data[26]
#   Trailing: 8 zero bytes [189..197)
#
# Parameter assignment for carpaint_calibrated (partial):
#   Group 1 RGB  , primary colour (dominant colour channel; correlates with
#                  PaintColorColorParam or FlakeColorColorParam for solid/metallic)
#   Group 3 RGB  , glancing-angle colour flop (GlancingFlopColorColorParam)
#   Groups 0/2   , scalar PBR parameters (exact assignment unknown)
#   Group 4[0]   , scalar PBR parameter
#   Group 4[1]   , purpose unknown; near-zero for most colours
#
# The 26-byte preamble encodes parameter identity via an unidentified hash function
# (same unknown hash as the LDFB release format in LightPresets.bin , see
# workplan item 1db).  Until the hash is cracked, preamble bytes are printed raw.

_GROUPS = [
    {'hdr': 1,   'data_end': 33,  'n_rgb': 1, 'label': 'scalar_A'},
    {'hdr': 33,  'data_end': 77,  'n_rgb': 3, 'label': 'primary_RGB'},
    {'hdr': 77,  'data_end': 109, 'n_rgb': 1, 'label': 'scalar_B'},
    {'hdr': 109, 'data_end': 153, 'n_rgb': 3, 'label': 'glancing_RGB'},
    {'hdr': 153, 'data_end': 189, 'n_rgb': 2, 'label': 'scalar_C_D'},
]


def decode_rptm(payload):
    """
    Return a list of dicts, one per group:
      {'label': str, 'preamble': bytes, 'values': tuple[float, ...]}
    """
    if len(payload) < 1:
        raise ValueError("RPTM payload too short")
    group_count = payload[0]
    results = []
    for g in _GROUPS:
        hdr_off  = g['hdr']
        if hdr_off + 2 > len(payload):
            break
        header   = payload[hdr_off:hdr_off + 2]
        data_start = hdr_off + 2
        preamble = payload[data_start:data_start + 26]
        vary_off = data_start + 26
        n        = g['n_rgb']
        floats   = struct.unpack_from(f'<{n}f', payload, vary_off)
        results.append({
            'label':    g['label'],
            'header':   header,
            'preamble': preamble,
            'values':   floats,
        })
    return group_count, results


# ── sRGB conversion ────────────────────────────────────────────────────────────

def linear_to_srgb_u8(c):
    c = max(0.0, min(1.0, c))
    if c <= 0.0031308:
        return round(c * 12.92 * 255)
    return round((1.055 * c ** (1.0 / 2.4) - 0.055) * 255)


def rgb_hex(r, g, b):
    return '#{:02X}{:02X}{:02X}'.format(
        linear_to_srgb_u8(r), linear_to_srgb_u8(g), linear_to_srgb_u8(b))


# ── hex dump helper ────────────────────────────────────────────────────────────

def hexdump(data, indent='  '):
    for i in range(0, len(data), 16):
        row = data[i:i + 16]
        h = ' '.join(f'{b:02X}' for b in row)
        a = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
        print(f'{indent}{i:4d}  {h:<48}  {a}')


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__)
        return
    path = Path(args[0])
    show_hex = '--hex' in args

    data = path.read_bytes()
    print(f'File: {path}  ({len(data)} bytes)')

    try:
        chunks = parse_burg(data)
    except ValueError as e:
        print(f'ERROR: {e}')
        sys.exit(1)

    print(f'Chunks: {list(chunks.keys())}')
    print()

    # ── MATL: shaderbin path ──────────────────────────────────────────────────
    if 'MATL' in chunks:
        c = chunks['MATL']
        shader_path = decode_matl(c['payload'])
        print(f'MATL  ({c["size"]} bytes)')
        print(f'  Shader path: {shader_path}')
        if show_hex:
            hexdump(c['payload'])
        print()

    # ── DUTM: single-byte tag (purpose unknown; 0x00 for carpaint_calibrated) ──
    for try_tag in ('MTUD', 'DUTM'):
        if try_tag in chunks:
            c = chunks[try_tag]
            val = c['payload'][0] if c['payload'] else None
            print(f'DUTM  ({c["size"]} bytes)  value=0x{val:02X}={val}  (purpose not decoded)')
            print()
            break

    # ── RPTM: parameter groups ────────────────────────────────────────────────
    rptm_tag = 'MTPR' if 'MTPR' in chunks else ('RPTM' if 'RPTM' in chunks else None)
    if rptm_tag:
        c = chunks[rptm_tag]
        print(f'RPTM  ({c["size"]} bytes)')
        if show_hex:
            hexdump(c['payload'])

        try:
            group_count, groups = decode_rptm(c['payload'])
            print(f'  group_count = {group_count}')
            for i, g in enumerate(groups):
                vals = g['values']
                label = g['label']
                hdr = g['header'].hex()
                if len(vals) == 3:
                    hex_col = rgb_hex(*vals)
                    print(f'  Group {i} [{label}]  header={hdr}')
                    print(f'    RGB = ({vals[0]:.4f}, {vals[1]:.4f}, {vals[2]:.4f})  sRGB={hex_col}')
                elif len(vals) == 1:
                    print(f'  Group {i} [{label}]  header={hdr}')
                    print(f'    value = {vals[0]:.6f}')
                else:
                    print(f'  Group {i} [{label}]  header={hdr}')
                    print(f'    values = {tuple(f"{v:.6f}" for v in vals)}')
                print(f'    preamble (26 B, constant) = {g["preamble"].hex()}')
        except Exception as e:
            print(f'  RPTM decode error: {e}')
    print()
    print('Note: "primary_RGB" = paint primary colour (face-on, linear light)')
    print('      "glancing_RGB" = glancing-angle colour flop (GlancingFlopColorColorParam)')
    print('      scalar groups = PBR parameters (exact assignment unknown)')


if __name__ == '__main__':
    main()
