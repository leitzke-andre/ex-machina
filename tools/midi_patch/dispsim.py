"""A model of the display side for the emulator tests: the picture the firmware should draw for a message (computed pixel by pixel, independent of
the firmware's renderer), and the stock main loop's handling of the staging buffer (copy into the framebuffer, clear the pending flag; read from
the disassembly of 0x08003f34), recording every region it was handed. Used by test_modes.py and test_display_race.py."""
import random, struct
import build_patch as bp

MS16 = 0x200010E8
FB, DISP_FLAG, DISP_HDR, DISP_DATA = 0x200010F2, 0x200012F8, 0x200013A1, 0x200013A9

FONT = bp.FONT
def glyph(ch):
    c = ord(ch.upper()) if ch else 32
    if c < 32 or c > 95: c = ord('?')
    return FONT[(c - 32) * 5:(c - 32) * 5 + 5]
def _text(lit, text, x0, y0):
    for i, ch in enumerate(text[:21]):
        for gc, col in enumerate(glyph(ch)):
            for row in range(7):
                if col >> row & 1: lit.add((x0 + 6 * i + gc, y0 + row))
def _title(lit, text):
    for i, ch in enumerate(text[:10]):
        for gc, col in enumerate(glyph(ch)):
            for row in range(7):
                if col >> row & 1:
                    for dx in (0, 1):
                        for dy in (0, 1): lit.add((4 + 12 * i + 2 * gc + dx, 1 + 2 * row + dy))
def _pack(lit):
    """The pixels packed like the stock framebuffer: page-major, a lit pixel is a cleared bit."""
    fb = bytearray(512)
    for page in range(4):
        for x in range(128):
            v = 0
            for r in range(8):
                if (x, page * 8 + r) in lit: v |= 1 << r
            fb[page * 128 + x] = (~v) & 0xFF
    return bytes(fb)
def reference(title, detail, bar=None):
    """A message: title at twice the size, detail line, optional bar (pixels first, computed independently of the firmware's renderer)."""
    lit = set()
    _title(lit, title); _text(lit, detail, 4, 17)
    if bar is not None:
        for x in range(4, 124):
            rows = range(1, 7) if x in (4, 123) else [1, 6] + (list(range(2, 6)) if x - 5 < bar else [])
            for r in rows: lit.add((x, 24 + r))
    return _pack(lit)
def idle(status, name='EX-MACHINA', version='V0'):
    """The idle screen: the firmware's name at twice the size, the version, a status line."""
    lit = set()
    _title(lit, name); _text(lit, version, 4, 17); _text(lit, status, 4, 25)
    return _pack(lit)

def seq_grid(top, steps, cur=None):
    """The sequencer grid: a top line, 16 cells of 8 pixels (columns 1-6 drawn): off = a 2-row bar, on = 10 rows, accent = 14 rows; below, the playhead (3 rows,
    the whole cell) and beat marks every 4 steps (2 rows, 2 pixels)."""
    lit = set()
    _text(lit, top, 4, 1)
    for k, st in enumerate(steps):
        rows = {0: range(14, 16), 1: range(11, 21), 2: range(9, 23)}[st]
        for c in range(1, 7):
            for r in rows: lit.add((8 * k + c, r))
        if cur == k:
            for c in range(8):
                for r in range(25, 28): lit.add((8 * k + c, r))
        elif k % 4 == 0:
            for c in (3, 4):
                for r in (29, 30): lit.add((8 * k + c, r))
    return _pack(lit)

class Screen:
    """What the stock main loop does with the staging buffer, applied after every tick; counts the regions it was handed."""
    def __init__(self, d, seed=11):
        self.d = d; self.regions = 0; self.seen = []                                      # seen: (page, h, data) of every region applied
        self.original = bytes(random.Random(seed).randrange(256) for _ in range(512))       # stands in for what the stock firmware drew at start-up (NI's logo)
        d.mu.mem_write(FB, self.original); d.mu.mem_write(MS16, struct.pack('<H', 5000))
    def ms(self): return struct.unpack('<H', self.d.mu.mem_read(MS16, 2))[0]
    def advance(self, ms): self.d.mu.mem_write(MS16, struct.pack('<H', (self.ms() + ms) & 0xFFFF))
    def apply(self):
        mu = self.d.mu
        if mu.mem_read(DISP_FLAG, 1)[0]:
            h = bytes(mu.mem_read(DISP_HDR, 8)); x, page, w, hh = h[0], h[2], h[4], h[6]
            assert h[1] == h[3] == h[5] == h[7] == 0 and x + w <= 128 and page + hh <= 4 and w * hh <= 256, h.hex()
            data = bytes(mu.mem_read(DISP_DATA, w * hh))
            for pg in range(hh):
                for c in range(w): mu.mem_write(FB + (page + pg) * 128 + x + c, bytes([data[pg * w + c]]))
            self.seen.append((page, hh, data)); mu.mem_write(DISP_FLAG, b'\0'); self.regions += 1
    def run(self, ticks=8, ms=3):
        for _ in range(ticks): self.advance(ms); self.d.tick(0); self.apply()
    def fb(self): return bytes(self.d.mu.mem_read(FB, 512))
    def settle(self, ms=10): self.run(300, ms)                      # long enough for any message to end and the idle screen to be drawn

