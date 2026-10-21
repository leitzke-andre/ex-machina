"""What the Ex-Machina script sends to the device: LED colour codes, the screen (four text lines, as TEXT commands or, on a firmware without them,
as pixel regions), host mode. Pure Python, no FL Studio module: the tests run it as it is.

Protocol: docs/remap-protocol.md (SysEx F0 7D 4D 4B <cmd> ... F7) and docs/midi-patch.md (LED n = Note On n on the LED channel, velocity = colour
code = colour * 4 + brightness 0..3; colour 1..16 = the hues of exm_tables.COLOURS, 17 = white)."""
import exm_tables as t

MFR = bytes([0xF0, 0x7D, 0x4D, 0x4B])
COLS, LINES = 21, 4
WHITE = 17
# the hue (degrees) of each of the device's colours 1..16 (red ... fuchsia), for the nearest match to an FL colour
HUES = (0, 20, 30, 42, 55, 80, 120, 150, 180, 200, 240, 258, 272, 288, 305, 330)

def code(colour, level):
    """LED colour code: colour 1..17, level 0 (dim) .. 3 (bright); colour 0 = off."""
    return 0 if not colour else (colour << 2) | (level & 3)

def rgb(c):
    """An FL colour int as (r, g, b) 0..255, the way FL's own utils.ColorToRGB splits it."""
    return (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF

def nearest(c):
    """The device colour (1..17) closest to an FL colour: by hue, white for greys."""
    r, g, b = (v / 255.0 for v in rgb(c & 0xFFFFFF))
    hi, lo = max(r, g, b), min(r, g, b)
    if hi < 0.08 or hi - lo < 0.25 * hi: return WHITE
    d = hi - lo
    if hi == r: h = (60 * ((g - b) / d)) % 360
    elif hi == g: h = 60 * ((b - r) / d) + 120
    else: h = 60 * ((r - g) / d) + 240
    return 1 + min(range(16), key=lambda i: min(abs(h - HUES[i]), 360 - abs(h - HUES[i])))

def led_msg(led, value):
    """The MIDI message (status, data1, data2) that sets one LED."""
    return 0x90 | t.LED_CHANNEL, led & 0x7F, value & 0x7F

def host(flags): return MFR + bytes([t.CMD_HOST, flags & 0x7F, 0xF7])

def mode_query(): return MFR + bytes([t.CMD_MODE, 0xF7])

NOTE_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
def note_name(n):
    """A MIDI note as FL names it (middle C = 60 = C5)."""
    return '%s%d' % (NOTE_NAMES[int(n) % 12], int(n) // 12)

def mode_msg(sx):
    """The device's mode (0 Standalone, 1 FL Studio) if `sx` is its answer to MODE or the announcement of a switch (62 00 <mode>), else None."""
    sx = bytes(sx)
    if len(sx) >= 8 and sx[:4] == MFR and sx[4] == t.CMD_MODE + 0x40 and sx[5] == 0: return sx[6]
    return None

def is_host_reply(sx):
    """(ok, flags) if `sx` is the device's answer to HOST, else None."""
    sx = bytes(sx)
    if len(sx) >= 7 and sx[:4] == MFR and sx[4] == t.CMD_HOST + 0x40: return sx[5] == 0, sx[6]
    return None

def clean(text):
    """A line as the device shows it: 21 characters of its font (capitals, ASCII 32..95)."""
    s = ''.join(ch if 32 <= ord(ch) <= 95 else '?' for ch in str(text).upper())
    return s[:COLS].ljust(COLS)

def text_line(n, text): return MFR + bytes([t.CMD_TEXT, n & 3, 0]) + clean(text).encode('ascii') + bytes([0xF7])

def pack7(data):
    out = bytearray()
    for i in range(0, len(data), 7):
        g = data[i:i + 7]
        out.append(sum(((v >> 7) & 1) << k for k, v in enumerate(g)))
        out += bytes(v & 0x7F for v in g)
    return bytes(out)

def frame(lines):
    """The 128 x 32 picture of four text lines like the firmware's TEXT draws them (line n on rows 8n..8n+6, 6-pixel cells from x = 1),
    page-major, one byte = 8 rows of a column, a lit pixel is a cleared bit."""
    fb = bytearray([0xFF]) * 512
    for n, line in enumerate(lines[:LINES]):
        for i, ch in enumerate(clean(line)):
            c = ord(ch) - 32
            for w in range(5):
                col = t.FONT[c * 5 + w]
                if col: fb[n * 128 + 1 + 6 * i + w] = (~col) & 0xFF
    return bytes(fb)

def regions(lines, half=None):
    """The picture as pixel regions (SysEx 01), one per half (pages 0-1, 2-3); half 0 or 1 for only that one."""
    fb = frame(lines); out = []
    for h in ((0, 1) if half is None else (half,)):
        out.append(MFR + bytes([0x01, 0, 2 * h, 127, 1]) + pack7(fb[256 * h:256 * h + 256]) + bytes([0xF7]))
    return out
