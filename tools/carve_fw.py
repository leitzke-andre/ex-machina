#!/usr/bin/env python3
"""Carve the embedded Mikro MK3 firmware out of the NI Mac updater (MM3Updater v1.20).
Usage: carve_fw.py <MM3Updater binary> <out.bin>
The image sits in __TEXT,__const: file offset 0x22d570 (Cortex-M vector table) (+0x9dc8 bytes).
Output is NI's proprietary firmware: keep it local, never commit or redistribute it."""
import sys
d = open(sys.argv[1], 'rb').read()
open(sys.argv[2], 'wb').write(d[0x22d570:0x22d570 + 0x9dc8])
