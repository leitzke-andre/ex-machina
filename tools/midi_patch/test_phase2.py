"""Phase 2 of the controller's own functions in the emulator: scales and chords (all 24 scales and 5 chord types against an independent model), the touch-strip
modes (pitch bend, mod wheel with the bar on the strip LEDs), the encoder targets, Program Change, and their screen messages.
Usage: test_phase2.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2, CC
from dispsim import reference, Screen

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

F = mc.FIELDS
B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}
PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}
PRESET = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'maschine-modes')
NON = lambda n, v=93, ch=0: (0x09, 0x90 | ch, n, v)
NOFF = lambda n, ch=0: (0x08, 0x80 | ch, n, 0)
BEND = lambda v, ch=0: (0x0E, 0xE0 | ch, v & 127, v >> 7)

def cfg(**kw):
    c = bytearray(PRESET)
    for k, v in kw.items():
        off, n = F[k]
        if isinstance(v, (list, tuple, bytes)): c[off:off + len(v)] = bytes(v)
        else: c[off] = v
    return bytes(c)

ENC = [0]                                                               # the encoder counter every report carries (a button report must not move it)
def Dev(c=None, flash=None):
    ENC[0] = 0
    d = devsim.Dev(fw, data, c if c is not None else PRESET, flash); d.translate(report1()); d.start(); return d
def turn(d, n): ENC[0] = (ENC[0] + n) % 16; return d.translate(report1(enc=ENC[0]))

def press(d, *names, **kw): return d.translate(report1([B[n] for n in names], enc=ENC[0], **kw))
def release(d, **kw): return d.translate(report1(enc=ENC[0], **kw))
def tap(d, *names): out = press(d, *names); return out, release(d)
def hit(d, pad, val=3000): return d.translate(report2([(PADIDX[pad], 1, val)]))
def lift(d, pad): return d.translate(report2([(PADIDX[pad], 3, 0)]))
def shift_tap(d, name): press(d, 'Shift', name); release(d)
def led(d): return d.led()

# ---- the model: scales and chords ----------------------------------------------------------------------------------------------------------
SEM = [sorted(s) for s in bp.SCALE_SEMITONES]
def degree(scale, deg):
    s = SEM[scale]; return 12 * (deg // len(s)) + s[deg % len(s)]
CHORDS = [(0, 2, 4), (0, 2, 4, 6), (0, 1, 4), (0, 3, 4), (0, 4)]
def keys_note(scale, pad, root=60, tr=0): return min(127, max(0, root + tr + degree(scale, pad - 1)))
def chord_notes(scale, ctype, pad, root=60, tr=0):
    sc = 1 if scale == 0 else scale                                     # chords on the chromatic scale are built on the major scale
    return [min(127, max(0, root + tr + degree(sc, pad - 1 + o))) for o in CHORDS[ctype]]

check('the scale masks in the image are the ones of the model: 24 scales, each starting on the root', all(m & 1 for m in bp.SCALES) and len(bp.SCALES) == 24
      and fw[bp.SCALES_ADDR - 0x08003000:][:48] == bp.scales_blob())

# ---- scales -------------------------------------------------------------------------------------------------------------------------------
d = Dev()
check('the Maschine-like preset starts in Group mode on the chromatic scale: pad 1 = 36', hit(d, 1), [NON(36)]); lift(d, 1)
shift_tap(d, 'Keyboard')
check('Shift + Keyboard from Group mode: Keyboard mode on the next scale (major): pads 1-8 = C D E F G A B C', [hit(d, n)[0][2] for n in range(1, 9)], [60, 62, 64, 65, 67, 69, 71, 72])
for n in range(1, 9): lift(d, n)
wrong = []
d = Dev(); shift_tap(d, 'Keyboard')
for sc in range(1, 24):
    got = [hit(d, n)[0][2] for n in range(1, 17)]
    for n in range(1, 17): lift(d, n)
    if got != [keys_note(sc, n) for n in range(1, 17)]: wrong.append((sc, got))
    shift_tap(d, 'Keyboard')
check('all 24 scales (stepped through with Shift + Keyboard, wrapping 23 -> 0): the 16 pads play root + scale degree, octaves continuing', wrong, [])
check('... and after the wrap round it is the chromatic scale again', [hit(d, n)[0][2] for n in (1, 2, 3, 16)], [60, 61, 62, 75]); [lift(d, n) for n in (1, 2, 3, 16)]
shift_tap(d, 'Pad Mode')
check('Shift + Pad Mode steps back (chromatic -> the last scale)', [hit(d, n)[0][2] for n in (1, 2, 3)], [keys_note(23, n) for n in (1, 2, 3)]); [lift(d, n) for n in (1, 2, 3)]
d = Dev(); shift_tap(d, 'Keyboard'); tap(d, 'Right')
check('transposing moves the whole scale (major, +1 semitone)', [hit(d, n)[0][2] for n in (1, 2, 3)], [61, 63, 65]); [lift(d, n) for n in (1, 2, 3)]
d = Dev(cfg(scale=5, keys_root=57)); tap(d, 'Keyboard')
check('a config can start on a scale and a root (dorian from 57): Keyboard mode plays it at once', [hit(d, n)[0][2] for n in range(1, 5)], [keys_note(5, n, 57) for n in range(1, 5)]); [lift(d, n) for n in range(1, 5)]
shift_tap(d, 'Keyboard'); d.send_sysex(mc.set_request(cfg(scale=5, keys_root=57))); [d.tick(0) for _ in range(5)]
tap(d, 'Keyboard')
check('a SET puts the scale back to the one of the config', hit(d, 2)[0][2], keys_note(5, 2, 57)); lift(d, 2)
d = Dev(); shift_tap(d, 'Keyboard'); hit(d, 5); shift_tap(d, 'Keyboard')
check('a pad held while the scale changes is released with the note it started', lift(d, 5), [NOFF(keys_note(1, 5))])

# ---- chords -------------------------------------------------------------------------------------------------------------------------------
d = Dev(); tap(d, 'Chords')
check('Chords mode on the chromatic scale (harmonised on major): pad 1 = C E G, pad 2 = D F A, pad 8 = C E G an octave up',
      [[p[2] for p in hit(d, n)] for n in (1, 2, 8)], [[60, 64, 67], [62, 65, 69], [72, 76, 79]])
check('releasing a chord pad releases every note of it', lift(d, 1), [NOFF(60), NOFF(64), NOFF(67)]); lift(d, 2); lift(d, 8)
d = Dev(); tap(d, 'Chords'); wrong = []
for sc in range(24):
    for ct in range(5):
        d3 = Dev(cfg(scale=sc, chord_type=ct)); tap(d3, 'Chords')
        for pad in (1, 7, 16):
            got = [p[2] for p in hit(d3, pad)]; lift(d3, pad)
            if got != chord_notes(sc, ct, pad): wrong.append((sc, ct, pad, got))
check('all 24 scales x 5 chord types x pads 1, 7, 16 (started from the config): the notes of the model', wrong, [])
d = Dev(); tap(d, 'Chords'); wrong = []
types = []
for k in range(6):
    shift_tap(d, 'Chords'); types.append([p[2] for p in hit(d, 1)]); lift(d, 1)
check('Shift + Chords steps the chord type: seventh, sus2, sus4, power, triad (wraps), seventh', types, [[60, 64, 67, 71], [60, 62, 67], [60, 65, 67], [60, 67], [60, 64, 67], [60, 64, 67, 71]])
shift_tap(d, 'Select'); shift_tap(d, 'Select')
check('Shift + Select steps back (seventh -> triad -> power)', [p[2] for p in hit(d, 1)], [60, 67]); lift(d, 1)
d = Dev(cfg(chord_type=1)); tap(d, 'Chords')
ev21 = [(p, 1, 3000) for p in range(16)] + [(p, 1, 3000) for p in range(5)]
out = d.translate(report2(ev21))
sent = [pk for b in d.sent for pk in [tuple(b[k:k + 4]) for k in range(0, len(b), 4)]]
check('a report of 21 chord hits (16 new pads + 5 retriggers, seventh chords): 16 x 4 Note On + 5 x (4 Note Off + 4 Note On) = 104 packets, all delivered in order',
      (len(sent), len(d.sent) >= 1, sum(1 for pk in sent if pk[0] == 8), sum(1 for pk in sent if pk[0] == 9)), (104, True, 20, 84))
check('... every held pad remembers its chord: lifting all of them sends 16 x 4 Note Offs', sum(len(lift(d, n)) for n in range(1, 17)), 64)
d = Dev(); tap(d, 'Chords'); hit(d, 1)
check('pressure on a chord pad goes to its root note (poly aftertouch)', d.translate(report2([(PADIDX[1], 4, 2000)])), [(0x0A, 0xA0, 60, 62)])
lift(d, 1)
d = Dev(); tap(d, 'Chords'); hit(d, 1); tap(d, 'Pad Mode'); shift_tap(d, 'Chords')
check('a chord held while the mode and the chord type change is released with the notes it started', lift(d, 1), [NOFF(60), NOFF(64), NOFF(67)])
d = Dev(); shift_tap(d, 'Keyboard'); tap(d, 'Chords'); tap(d, 'Right')
check('chords follow the scale and the transposition (major, +1): pad 3 = E G B -> F G B C', [p[2] for p in hit(d, 3)], chord_notes(1, 0, 3, tr=1)); lift(d, 3)
d = Dev(); led0 = led(d)
check('the Chords button lights in Chords mode only (Pad Mode at the start)', (led(d)[B['Chords']], led(d)[B['Pad Mode']]), (0x7C, 0x7F))
tap(d, 'Chords'); check('... Chords lit, Pad Mode dim', (led(d)[B['Chords']], led(d)[B['Pad Mode']], led(d)[B['Keyboard']]), (0x7F, 0x7C, 0x7C))

# ---- the touch strip -----------------------------------------------------------------------------------------------------------------------
d = Dev()
check('strip mode 0 (Perform, the configured CC): position 100 sends CC 1 = 63', d.translate(report1(pos=100)), [CC(1, 63)]); release(d)
tap(d, 'Pitch')
check('the Pitch button lights', (led(d)[B['Pitch']], led(d)[B['Mod']]), (0x7F, 0x7C))
touch = lambda pos: d.translate(report1(pos=pos, enc=ENC[0]))
check('Pitch: the whole strip is the bend range: 1 -> 0, 100 -> 8150, 200 -> 16383', (touch(1), touch(100), touch(200)), ([BEND(0)], [BEND(8150)], [BEND(16383)]))
check('Pitch: letting go springs back to the centre (8192)', release(d), [BEND(8192)])
check('Pitch: nothing else is sent while nothing happens', (release(d), touch(100) != []), ([], True)); release(d)
tap(d, 'Mod')
check('Mod: position 100 sends CC 1 = 63', touch(100), [CC(1, 63)])
check('Mod: letting go sends nothing (the value stays)', release(d), [])
check('Mod: the strip LEDs show the value as a bar: 13 dim LEDs from the left (63 of 127 on 25 LEDs)', set(led(d)[55:68]) == {17 * 4 + 1} and set(led(d)[68:80]) == {0}, True, bytes(led(d)[55:80]).hex())
touch(10)
check('Mod: while the finger is down its LED is lit on top of the bar (LED 56 bright, LED 55 the bar)', (led(d)[55], led(d)[56]), (17 * 4 + 1, 17 * 4 + 3))
release(d)
check('Mod: the bar follows the value after release (5 -> one LED)', (led(d)[55], set(led(d)[56:80])), (17 * 4 + 1, {0}))
check('Mod: the same value is not sent twice', touch(10), []); release(d)
tap(d, 'Perform')
check('Perform (the configured CC again) clears the bar', (set(led(d)[55:80]), led(d)[B['Perform']], led(d)[B['Mod']]), ({0}, 0x7F, 0x7C))
check('... and the strip sends CC 1 as configured', touch(150), [CC(1, 95)]); release(d)
tap(d, 'Mod'); touch(100); release(d)
d.send_sysex(mc.set_request(PRESET)); [d.tick(0) for _ in range(5)]
check('a SET puts the strip back to the configured CC and clears the bar', (touch(100), set(led(d)[55:80]) <= {0, 17 * 4 + 3}), ([CC(1, 63)], True))
d = Dev(cfg(strip_cc=74, channel=2)); tap(d, 'Pitch')
check('on another channel: pitch bend uses it too (channel 3)', touch(100), [BEND(8150, 2)])

# ---- the encoder targets -----------------------------------------------------------------------------------------------------------------------
d = Dev(cfg(enc_cc=20, enc_mode=2))
check('no target: the encoder sends its own CC 20 in its own mode (relative: +1)', turn(d, 1), [CC(20, 1)])
tap(d, 'Volume')
check('the Volume button selects target 1 (CC 7) and lights', (led(d)[B['Volume']], led(d)[B['Swing']]), (0x7F, 0x7C))
check('target 1: absolute from 64: +1 -> CC 7 = 65, then +2 -> 67 (whatever the encoder mode)', (turn(d, 1), turn(d, 2)), ([CC(7, 65)], [CC(7, 67)]))
check('turning back: -3 -> 64', turn(d, -3), [CC(7, 64)])
tap(d, 'Swing')
check('Swing selects target 2 (CC 10) and keeps its own value (64)', (led(d)[B['Volume']], led(d)[B['Swing']], turn(d, 1)), (0x7C, 0x7F, [CC(10, 65)]))
tap(d, 'Tempo'); check('Tempo = target 3 (CC 11), its own value 64', turn(d, 1), [CC(11, 65)])
tap(d, 'Volume')
check('Volume again selects target 1 and its value is still 64', turn(d, 1), [CC(7, 65)])
tap(d, 'Volume')
check('the same button again goes back to the configured encoder CC (relative: +1)', (turn(d, 1), led(d)[B['Volume']]), ([CC(20, 1)], 0x7C))
d = Dev(cfg(enc_tgt_cc=[0xFF, 10, 11])); tap(d, 'Volume')
check('a target without a CC (0xFF): the encoder sends nothing', turn(d, 1), [])
d = Dev(); tap(d, 'Volume'); got = []
for k in range(80): got += turn(d, 1)
check('64 -> 127 in single clicks sends 63 values and then nothing (the limit)', (len(got), got[-1], max(p[3] for p in got)), (63, CC(7, 127), 127))
d = Dev(); tap(d, 'Volume'); d.send_sysex(mc.set_request(PRESET)); [d.tick(0) for _ in range(5)]
check('a SET deselects the target: the encoder is the configured one again (absolute from enc_init: +1 -> 1)', turn(d, 1), [CC(7, 1)])

# ---- Program Change ---------------------------------------------------------------------------------------------------------------------------
d = Dev(cfg(channel=2))
PC = lambda n, ch=2: (0x0C, 0xC0 | ch, n, 0)
def shift_out(d, name): o = press(d, 'Shift', name); release(d); return o
check('Favorites = next program: 1, 2; Browser = previous: 1; Shift + Browser = back to 0 (sent)', [tap(d, 'Favorites')[0], tap(d, 'Favorites')[0], tap(d, 'Browser')[0], shift_out(d, 'Browser')], [[PC(1)], [PC(2)], [PC(1)], [PC(0)]])
check('previous from 0 wraps to 127, next from 127 wraps to 0', (tap(d, 'Browser')[0], tap(d, 'Favorites')[0]), ([PC(127)], [PC(0)]))
check('nothing on release', (press(d, 'Favorites') != [], release(d)), (True, []))

# ---- screen messages -----------------------------------------------------------------------------------------------------------------------------
d = Dev(); sc = Screen(d)
def show(title, detail, action, bar=None):
    sc.run(250, 10); action(); sc.run(4)
    check(f'message: {title} / {detail}' + (f' / bar {bar}' if bar is not None else ''), sc.fb() == reference(title, detail, bar))
show('SCALE', 'MAJOR  C3', lambda: shift_tap(d, 'Keyboard'))
show('SCALE', 'MINOR  C3', lambda: shift_tap(d, 'Keyboard'))
show('SCALE', 'HARMONIC MINOR  C3', lambda: shift_tap(d, 'Keyboard'))
show('SCALE', 'MINOR  C3', lambda: shift_tap(d, 'Pad Mode'))
show('CHORDS', 'TRIAD  C3', lambda: tap(d, 'Chords'))
show('CHORD TYPE', 'SEVENTH', lambda: shift_tap(d, 'Chords'))
show('STRIP', 'PITCH BEND', lambda: tap(d, 'Pitch'))
show('STRIP', 'MOD WHEEL', lambda: tap(d, 'Mod'))
show('STRIP', 'CONFIGURED CC', lambda: tap(d, 'Perform'))
show('CC 7', 'ENCODER', lambda: tap(d, 'Volume'))
show('CC 7', 'VALUE 65', lambda: turn(d, 1), 65 * 118 // 127)
show('PROGRAM', 'PC 1', lambda: tap(d, 'Favorites'))
show('KEYBOARD', 'C3-D5', lambda: tap(d, 'Keyboard'))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
