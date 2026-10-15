#!/usr/bin/env python3
"""
dump_colors.py
--------------
Decodes ManufacturerColors.bin (burG container, MNCL chunk) and prints each
paint option with its sRGB hex, linear RGB, finish, and material name.

Usage:
    python dump_colors.py <ManufacturerColors.bin> [--csv]

Options:
    --csv   Write comma-separated output (car, index, hex, R, G, B, finish, path)
"""

import struct, sys
from pathlib import Path


def _linear_to_srgb_u8(c):
    c = max(0.0, min(1.0, c))
    if c <= 0.0031308:
        return round(c * 12.92 * 255)
    return round((1.055 * c ** (1.0 / 2.4) - 0.055) * 255)


def _read_pascal(data, off):
    length = data[off]
    return data[off+1 : off+1+length].decode('ascii'), off + 1 + length


def parse_mncl(data):
    if data[:4] != b'burG':
        raise ValueError(f"Not a burG file (magic={data[:4]!r})")

    n_chunks = struct.unpack_from('<I', data, 0x10)[0]
    chunk_off = None
    pos = 0x14
    for _ in range(n_chunks):
        if data[pos:pos+4] == b'LCNM':   # MNCL reversed on disk
            chunk_off = struct.unpack_from('<I', data, pos+12)[0]
        pos += 24
    if chunk_off is None:
        raise ValueError("No MNCL chunk found")

    off = chunk_off
    color_count = data[off]; off += 1

    colors = []
    for _ in range(color_count):
        unk1 = data[off]; off += 1
        part_count = data[off]; off += 1
        off += 3                             # padding zeros

        parts = []
        for _ in range(part_count):
            name, off = _read_pascal(data, off)
            parts.append(name)

        r, g, b = struct.unpack_from('<fff', data, off)
        primary_rgb_bytes = data[off:off+12]     # save for tail detection below
        off += 12
        mat_path, off = _read_pascal(data, off)

        if unk1 != 0x01:
            # Shipped-game format: one or more secondary-colour groups follow.
            # Each group: sec_count(1) + padding(3) + sec_count × pascal names
            #             + sec_rgb(12) + sec_materialbin(pascal).
            # Tail is always 27 B: 0x01 + primary_rgb_copy(12) + 0x00 0x01 + sec_rgb_copy(12).
            # Number of groups is not stored explicitly , loop until the tail is detected.
            # Tail detection uses the primary_rgb_bytes to avoid a false-positive when the
            # primary R component is exactly 0.0 (bytes 00 00 00 00), which would otherwise
            # look like a secondary group header (sc=1, pad=000000).
            while off + 4 <= len(data):
                # Tail signature: 0x01 + primary_rgb_copy + 0x00 0x01 ...
                if (data[off] == 0x01
                        and data[off+1:off+13] == primary_rgb_bytes
                        and data[off+13:off+15] == b'\x00\x01'):
                    break
                sc = data[off]
                if sc == 0 or data[off+1:off+4] != b'\x00\x00\x00':
                    break
                off += 4                         # count + padding
                for _ in range(sc):
                    _, off = _read_pascal(data, off)
                off += 12                        # secondary rgb
                _, off = _read_pascal(data, off) # secondary materialbin
            off += 27                            # fixed tail
        else:
            off += 1                             # separator 0x01
            off += 12                            # rgb_copy (identical duplicate)
            off += 2                             # terminal 0x0000

        colors.append({'r': r, 'g': g, 'b': b, 'path': mat_path, 'parts': parts})

    return colors


def _guess_finish(path):
    p = path.lower()
    if '_met_' in p or 'metallic' in p:
        return 'metallic'
    if '_solid_' in p:
        return 'solid'
    return 'unknown'


def dump(src_path, csv_mode=False):
    data = Path(src_path).read_bytes()
    colors = parse_mncl(data)
    car = Path(src_path).parent.name

    if csv_mode:
        print('car,index,hex_srgb,r_linear,g_linear,b_linear,finish,material_path')
        for i, c in enumerate(colors):
            hex_col = '#{:02X}{:02X}{:02X}'.format(
                _linear_to_srgb_u8(c['r']),
                _linear_to_srgb_u8(c['g']),
                _linear_to_srgb_u8(c['b']))
            print(f"{car},{i},{hex_col},{c['r']:.6f},{c['g']:.6f},{c['b']:.6f},"
                  f"{_guess_finish(c['path'])},{c['path']}")
        return

    print(f"  {car}  ({len(colors)} colour{'s' if len(colors) != 1 else ''})")
    for i, c in enumerate(colors):
        srgb = (
            _linear_to_srgb_u8(c['r']),
            _linear_to_srgb_u8(c['g']),
            _linear_to_srgb_u8(c['b']),
        )
        hex_col = '#{:02X}{:02X}{:02X}'.format(*srgb)
        finish = _guess_finish(c['path'])
        mat_name = Path(c['path'].replace('\\', '/')).stem
        print(f"  [{i}] {hex_col}  ({c['r']:.4f}, {c['g']:.4f}, {c['b']:.4f})"
              f"  {finish:8}  {mat_name}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    csv_mode = '--csv' in sys.argv
    paths = [a for a in sys.argv[1:] if not a.startswith('--')]
    dump(paths[0], csv_mode)
