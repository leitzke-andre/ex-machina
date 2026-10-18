#!/usr/bin/env python3
"""Host-side helpers for the patched Mikro MK3: build the SysEx messages that drive the display
and LEDs. Pure Python; sending needs `pip install mido python-rtmidi` (optional).

    python3 mmk3_host.py probe   [--port NAME]   # light LED 0..79 one at a time, to learn the LED map
    python3 mmk3_host.py border  [--port NAME]   # draw a frame on the display (orientation check)
    python3 mmk3_host.py colors  [--port NAME]   # show the 17 colour codes on the 16 pad LEDs

LED colour code = colour * 4 + variant: colour 1..16 = red, orange, light orange, warm yellow,
yellow, lime, green, mint, cyan, turquoise, blue, plum, violet, purple, magenta, fuchsia (order
taken from the firmware palette and NI's public colour list; the names were checked against the
lit pads of a real unit on 2026-10-17);
colour 17+ = white; 0 = off. Variant 0/1 = dim, 2/3 = bright.
LED index: 0..38 buttons (mono), 39..54 pads (row-major 4x4, RGB+white), 55..79 touch strip (RGB).
Display: 128 x 32, 1 bit per pixel, 4 pages of 8 rows; a byte is one column of 8 vertical pixels
(bit 0 = top row of the page) and a LIT pixel is a CLEARED bit (0xFF = blank). Three community
drivers (r00tman, essaim-dev, flokapi/pymikro) agree on this; confirmed on a real unit: the `border`
demo draws an upright frame whose diagonal ticks run from the top left to the bottom right.
"""
import sys, time

MFR = [0x7D, 0x4D, 0x4B]      # educational-use manufacturer id + "MK"

def pack7(data):
    out = bytearray()
    for i in range(0, len(data), 7):
        g = data[i:i + 7]
        out.append(sum(((v >> 7) & 1) << k for k, v in enumerate(g)))
        out += bytes(v & 0x7F for v in g)
    return bytes(out)

def led_frame(codes):
    """SysEx body for all 80 LEDs (codes 0..127)."""
    assert len(codes) == 80 and all(0 <= c < 128 for c in codes)
    return bytes([0xF0] + MFR + [0x02] + list(codes) + [0xF7])

def display_region(x, page, pixels_bytes, w, h):
    """SysEx body writing a w x h(pages) region; pixels_bytes has w*h column bytes (page-major)."""
    assert 0 <= x and x + w <= 128 and 0 <= page and page + h <= 4 and w * h <= 256 and len(pixels_bytes) == w * h
    return bytes([0xF0] + MFR + [0x01, x, page, w - 1, h - 1]) + pack7(pixels_bytes) + bytes([0xF7])

def bitmap_to_messages(rows):
    """rows: 32 lists/strings of 128 pixels (truthy = lit). Returns two SysEx messages (pages 0-1, 2-3)."""
    assert len(rows) == 32 and all(len(r) == 128 for r in rows)
    msgs = []
    for first in (0, 2):
        data = bytearray()
        for page in range(first, first + 2):
            for x in range(128):
                data.append(sum((0 if rows[page * 8 + b][x] not in (0, '0', ' ', '.', False) else 1) << b for b in range(8)))
        msgs.append(display_region(0, first, bytes(data), 128, 2))
    return msgs

def border_bitmap():
    rows = [[0] * 128 for _ in range(32)]
    for x in range(128): rows[0][x] = rows[31][x] = 1
    for y in range(32): rows[y][0] = rows[y][127] = 1
    for i in range(32): rows[i][i * 4 % 128] = 1                 # diagonal ticks show orientation
    return rows

def _open(argv):
    import mido
    name = argv[argv.index('--port') + 1] if '--port' in argv else next(n for n in mido.get_output_names() if 'icro' in n or 'aschine' in n)
    return mido.open_output(name)

def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    out = _open(argv)
    if cmd == 'probe':
        for led in range(80):
            print('LED', led, '- note which physical LED lit; Ctrl-C to stop')
            out.send(__import__('mido').Message('note_on', channel=1, note=led, velocity=(2 << 2) | 3 if led < 39 else (9 << 2) | 3))
            time.sleep(1.0)
            out.send(__import__('mido').Message('note_off', channel=1, note=led))
    elif cmd == 'border':
        for m in bitmap_to_messages(border_bitmap()):
            out.send(__import__('mido').Message.from_bytes(list(m))); time.sleep(0.05)
    elif cmd == 'colors':
        M = __import__('mido').Message
        for p in range(16):
            out.send(M('note_on', channel=1, note=39 + p, velocity=((p + 1) << 2) | 2))
        out.send(M('note_on', channel=1, note=55, velocity=(17 << 2) | 2))
    else:
        print(__doc__)

if __name__ == '__main__':
    main(sys.argv)
