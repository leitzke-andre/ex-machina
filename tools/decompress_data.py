#!/usr/bin/env python3
"""Decompress the Keil scatter-load RLE .data image of the Mikro MK3 firmware.
Usage: decompress_data.py <carved fw image> <out.bin>   (image base 0x08003000)
Compressed source at flash 0x0800cd20, expands to 0x1c0 bytes at RAM 0x20000000."""
import sys
d = open(sys.argv[1], 'rb').read()
src = d[0x0800cd20 - 0x08003000:]
out = bytearray(); i = 0
while len(out) < 0x1c0:
    b = src[i]; n = b & 7; p = i + 1
    if n == 0: n = src[i + 1]; p = i + 2
    m = b >> 4
    if m == 0: m = src[p]; p += 1
    for _ in range(n - 1): out.append(src[p]); p += 1
    if b & 8:
        off = src[p]; p += 1
        for _ in range(m + 2): out.append(out[-off])
    else:
        out.extend(b'\x00' * m)
    i = p
open(sys.argv[2], 'wb').write(out[:0x1c0])
