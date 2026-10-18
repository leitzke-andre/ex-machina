"""Replays a REAL guided recording of a stock Maschine Mikro MK3 (fixtures/stock_controls_capture.txt) through the patched
translator in the emulator: pads 1..16 in order, every button once in id order, encoder, touch strip. Two kinds of checks:
(1) the whole MIDI stream equals an independent model of the intended behaviour, read by read; (2) fixed facts of the guided
sequence (note order, CC order from NI's map, encoder values, strip range).
Usage: test_real_controls.py <patched.bin> <data_init.bin> [capture log]"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..')); sys.path.insert(0, HERE)
import hid_capture as H
import build_patch as bp
from replay import Replay
log = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, 'fixtures', 'stock_controls_capture.txt')
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'))

# NI's built-in map (the editor's Map::Map, the manual's diagram) by button id; the arrows, Shift and encoder touch get spare CCs here
NI_CC = {0: 38, 1: 39, 2: 40, 3: 44, 4: 46, 5: 48, 6: 45, 7: 47, 8: 41, 9: 42, 10: 49, 11: 50, 12: 51, 13: 52, 14: 34, 15: 35, 16: 36, 17: 37,
         18: 53, 19: 54, 20: 55, 21: 56, 22: 57, 23: 58, 24: 59, 25: 43, 26: 80, 27: 81, 28: 82, 29: 84, 30: 83, 31: 85, 32: 86, 33: 87,
         34: 88, 35: 89, 36: 90, 37: 91, 38: 92, 39: 8, 40: 9}
R = Replay(sys.argv[1], sys.argv[2])
rows = H.read_log(log)
NOTE = list(R.fw[bp.CFG_ADDR - 0x08003000 + 5:][:16])      # cfg.pad_note[HID pad index] of the image under test
BASE = NOTE[12]                                            # printed pad 1 = report index 12
assert NOTE == [BASE - 1 + n for n in H.PAD_LABEL], NOTE   # the default layout: pad n = base + n - 1
# default build: Play (22) and Stop (24) are the MIDI realtime messages Start / Stop, sent on press only; everything else is a CC
REALTIME = {bp.BTN_PLAY: 0xFA, bp.BTN_STOP: 0xFC}

# --- an independent model of the intended behaviour (default config: channel 1, gate buttons, MIDI Start/Stop for Play/Stop, absolute
# encoder from 0, strip CC1)
bits_prev, enc_prev, enc_abs, strip_prev, held = [0] * 41, None, 0, 0, set()
got, want = [], []
for ms, buf in rows:
    got.append([(q[1], q[2], q[3]) for q in R.translate(buf)])
    exp = []
    for kind, body in H.parse(buf):
        if kind == 'r1':
            bits = [(body[k >> 3] >> (k & 7)) & 1 for k in range(40)] + [body[5] & 1]
            for k in range(41):
                if bits[k] == bits_prev[k]: continue
                if k in REALTIME:
                    if bits[k]: exp.append((REALTIME[k], 0, 0))        # on press only
                else: exp.append((0xB0, NI_CC[k], 127 if bits[k] else 0))
            bits_prev = bits
            c = body[6] & 15
            if enc_prev is not None and c != enc_prev:
                d = (c - enc_prev) & 15                            # the counter counts UP for clockwise (measured)
                sd = d if d < 8 else d - 16
                nv = max(0, min(127, enc_abs + sd))
                if nv != enc_abs: enc_abs = nv; exp.append((0xB0, 7, nv))
            enc_prev = c
            pos = body[9]
            if pos and pos != strip_prev: exp.append((0xB0, 1, (pos - 1) * 127 // 199))
            strip_prev = pos
        elif kind == 'r2':
            for pad, t, v in body:
                note = NOTE[pad]
                if t in (0, 1):
                    if pad in held: exp.append((0x80, note, 0))
                    exp.append((0x90, note, max(1, min(127, v >> 5)))); held.add(pad)
                elif t in (2, 3):
                    if pad in held: exp.append((0x80, note, 0))
                    held.discard(pad)
                elif t == 4 and pad in held:
                    exp.append(('AT', note, max(0, min(127, v >> 5))))
    want.append(exp)
# pressure messages are only sent when the 7-bit value changes: filter the model the same way
last = {}
for exp in want:
    keep = []
    for m in exp:
        if m[0] == 'AT':
            if last.get(m[1]) == m[2]: continue
            last[m[1]] = m[2]; m = (0xA0, m[1], m[2])
        elif m[0] == 0x90: last[m[1]] = None
        elif m[0] == 0x80: last.pop(m[1], None)
        keep.append(m)
    exp[:] = keep
flat_got = [m for r in got for m in r]
check(f'the MIDI stream of all {len(rows)} real reads equals the independent model, read by read ({len(flat_got)} messages)', got == want, True,
      next(((i, got[i], want[i]) for i in range(len(rows)) if got[i] != want[i]), None) if got != want else '')

# --- fixed facts of the guided sequence
note_ons = [m[1] for m in flat_got if m[0] == 0x90]
check(f'pads 1..16 played in numbered order give notes {BASE}..{BASE + 15} in that order (then one stray hit on pad 8 = note {BASE + 7})', note_ons, list(range(BASE, BASE + 16)) + [BASE + 7])
ccs = [(m[1], m[2]) for m in flat_got if m[0] == 0xB0]
presses = [n for n, v in ccs if v == 127 and n not in (1, 7)]
order = [38, 39, 40, 44, 46, 48, 45, 47, 41, 42, 49, 50, 51, 52, 34, 35, 36, 37, 53, 54, 55, 56, 56, 58, 43, 80, 81, 82, 84, 83, 85, 86, 87, 88, 89, 90, 91, 92]   # no 57 / 59: Play and Stop are realtime messages
check('buttons pressed in id order, Follow twice: NI\'s CCs come out in the expected order (Chords 84 before Step 83, the NI quirk)',
      [n for n in presses if n not in (8, 9)], order)
check('Play gives one MIDI Start and Stop one MIDI Stop, in that order, only on the press (the releases send nothing); no CC 57 / 59',
      ([m for m in flat_got if m[0] >= 0xF0], 57 in [n for n, _ in ccs], 59 in [n for n, _ in ccs]), ([(0xFA, 0, 0), (0xFC, 0, 0)], False, False))
check('every button press is followed by its release (CC value 0): same count of 127 and 0 for every CC', all(sum(1 for n2, v in ccs if n2 == n and v == 127) == sum(1 for n2, v in ccs if n2 == n and v == 0) for n in {n for n, _ in ccs if n not in (1, 7)}))
# (in this recording the user turned counter-clockwise first, which is why the first 5 clicks at the lower limit send nothing)
check('encoder: 5 clicks counter-clockwise at the lower limit send nothing, then 5 clicks clockwise (absolute from 0) -> CC7 = 1 2 3 4 5',
      [v for n, v in ccs if n == 7], [1, 2, 3, 4, 5])
check('encoder press -> CC8 127 then 0; encoder touch -> CC9: 4 touches, each with its release', ([v for n, v in ccs if n == 8], sum(1 for n, v in ccs if n == 9 and v == 127), sum(1 for n, v in ccs if n == 9 and v == 0)), ([127, 0], 4, 4))
strip = [v for n, v in ccs if n == 1]
check('strip: the slide covers the whole range (CC1 from 0 at the left end to 127 at the right end), both taps at the ends and one in the middle',
      min(strip) == 0 and max(strip) == 127 and strip[0] == 0 and 127 in strip and any(50 <= v <= 70 for v in strip[-4:]), True, (strip[:3], strip[-6:]))
check('all CC values are 7-bit and no CC outside NI\'s map is used', all(0 <= v < 128 for _, v in ccs) and {n for n, _ in ccs} <= set(NI_CC.values()) | {1, 7})
# --- a clean clockwise-only recording (6 clicks, finger on the knob) pins the direction: the counter counts up, CC7 rises
R2 = Replay(sys.argv[1], sys.argv[2])
cw = []
for ms, buf in H.read_log(os.path.join(HERE, 'fixtures', 'stock_encoder_clockwise.txt')):
    cw += [(q[1], q[2], q[3]) for q in R2.translate(buf)]
check('encoder turned only clockwise (counter 0 -> 6): CC7 rises 1 2 3 4 5 6; touching the knob gives CC9 127 first and 0 at the end',
      ([v for st, n, v in cw if n == 7], cw[0], cw[-1]), ([1, 2, 3, 4, 5, 6], (0xB0, 9, 127), (0xB0, 9, 0)))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
