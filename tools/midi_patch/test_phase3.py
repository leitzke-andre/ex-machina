"""Phase 3 in the emulator: the grid (internal tempo, tap tempo, MIDI clock out and in), Note Repeat and the arpeggiator (six patterns, seven rates, octaves, latch),
mute / solo pads, strip strumming, the snapshot, and their screen messages. Time is the stock millisecond counter, advanced by the test.
Usage: test_phase3.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2, CC
from dispsim import reference, Screen, MS16

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
CLK, START, STOP = (0x0F, 0xF8, 0, 0), (0x0F, 0xFA, 0, 0), (0x0F, 0xFC, 0, 0)

def cfg(**kw):
    c = bytearray(PRESET)
    for k, v in kw.items():
        off, n = F[k]
        if isinstance(v, (list, tuple, bytes)): c[off:off + len(v)] = bytes(v)
        else: c[off] = v
    return bytes(c)

class T:
    """A device with a clock: the stock millisecond counter is advanced by the test, the main loop's tick runs after every step."""
    def __init__(self, c=None):
        self.d = devsim.Dev(fw, data, c if c is not None else PRESET); self.d.translate(report1()); self.d.start()
        self.t = 5000; self.enc = 0; self.write()
    def write(self): self.d.mu.mem_write(MS16, struct.pack('<H', self.t & 0xFFFF))
    def at(self, t): self.t = t; self.write()
    def run(self, ms, step=1, probe=None):
        """Advances time in steps, ticks, and returns [(time since the start of the run, packet)] of everything the firmware sent;
        probe(self) is called after every step and its values are collected in self.probed."""
        out, t0 = [], self.t
        self.probed = []
        for _ in range(0, ms, step):
            self.t += step; self.write(); self.d.all_sent.clear(); self.d.tick(0)
            if probe: self.probed.append(probe(self))
            for b in self.d.all_sent:
                for k in range(0, len(b), 4): out.append((self.t - t0, tuple(b[k:k + 4])))
            self.d.drain()
        return out
    def press(self, *names): return self.d.translate(report1([B[n] for n in names], enc=self.enc))
    def release(self): return self.d.translate(report1(enc=self.enc))
    def tap(self, *names): a = self.press(*names); return a, self.release()
    def shift_tap(self, name): self.press('Shift', name); self.release()
    def hit(self, pad, val=3000): return self.d.translate(report2([(PADIDX[pad], 1, val)]))
    def lift(self, pad): return self.d.translate(report2([(PADIDX[pad], 3, 0)]))
    def led(self): return self.d.led()
    def sent(self): return [tuple(b[k:k + 4]) for b in self.d.all_sent for k in range(0, len(b), 4)]

only = lambda ev, pk: [(t, p) for t, p in ev if p == pk]
notes = lambda ev: [p[2] for t, p in ev if p[0] == 9]
offs = lambda ev: [p[2] for t, p in ev if p[0] == 8]
ons = lambda ev: [(t, p[2]) for t, p in ev if p[0] == 9]
PULSE_MS = lambda bpm: 2500.0 / bpm                                        # one of 24 pulses per beat, in ms

# ---- the grid: clock out ----------------------------------------------------------------------------------------------------------------------
x = T()
a = x.press('Shift', 'Tap'); x.release()
check('Shift + Tap switches the MIDI clock output on: MIDI Start (0F FA) at once, nothing else', a, [START])
ev = x.run(1000)
n = len(only(ev, CLK)); ts = [t for t, p in only(ev, CLK)]
check('at the default 120 BPM one second holds 48 clock pulses (24 per beat)', n, 48)
check('... evenly spaced (20.83 ms +- 1 ms)', all(abs((b - a) - PULSE_MS(120)) <= 1.01 for a, b in zip(ts, ts[1:])), True, [b - a for a, b in zip(ts, ts[1:])][:8])
x = T(); x.press('Shift', 'Tap'); x.release(); x.run(10)
ev = x.run(1200, probe=lambda x: x.led()[B['Tap']])
lit = [i for i, v in enumerate(x.probed) if v == 0x7F]
check('the Tap button blinks on the beat while the clock runs: lit for 6 pulses (125 ms) at the start of each beat (500 ms), at rest in between',
      (len(lit) > 200, set(x.probed) <= {0x7F, 0x7C}, any(abs(b - a) > 1 for a, b in zip(lit, lit[1:]))), (True, True, True))
x.d.all_sent.clear()
x.press('Shift', 'Tap'); a = x.release(); ev2 = x.run(100)
check('Shift + Tap again: MIDI Stop (0F FC) and the pulses stop', (only(ev2, CLK), ), ([],))
x = T(); x.press('Shift', 'Tap'); x.release(); x.run(200)
a = x.press('Shift', 'Tap'); x.release()
check('switching it off sends MIDI Stop', a, [STOP])

# ---- tap tempo -----------------------------------------------------------------------------------------------------------------------------------
def bpm_of(x, ms=2000):
    """The tempo the clock output runs at, measured over `ms` milliseconds (clock output must be on)."""
    ev = x.run(ms); return round(len(only(ev, CLK)) * 60000 / ms / 24)
for iv, want in ((500, 120), (400, 150), (600, 100), (300, 200)):
    x = T(); t = 10000
    for k in range(5): x.at(t + k * iv); x.tap('Tap')
    x.at(t + 5 * iv); x.press('Shift', 'Tap'); x.release()
    check(f'tap tempo: five taps {iv} ms apart -> {want} BPM (the clock output runs at it)', bpm_of(x), want)
x = T(); x.at(10000); x.tap('Tap'); x.at(10500); x.tap('Tap'); x.at(13000); x.tap('Tap')
x.at(13010); x.press('Shift', 'Tap'); x.release()
check('a pause over 2 s starts a new run: the third tap alone changes nothing (still 120 BPM from the first two)', bpm_of(x), 120)
x = T(cfg(tempo=160 - 20)); x.press('Shift', 'Tap'); x.release()
check('the config can start at another tempo (160 BPM)', bpm_of(x), 160)
x = T(); x.at(10000); x.tap('Tap'); x.at(10100); x.tap('Tap'); x.at(10110); x.press('Shift', 'Tap'); x.release()
check('the tempo is limited to 275 BPM (two taps 100 ms apart would be 600)', bpm_of(x), 275)

# ---- Note Repeat / arp -------------------------------------------------------------------------------------------------------------------------
def arp_t(**kw):
    x = T(cfg(**kw)); x.tap('Note Repeat'); return x
x = arp_t()
check('Note Repeat on: the Note Repeat button lights', x.led()[B['Note Repeat']], 0x7F)
a = x.hit(1)
check('a pad with the arp on sends nothing from the hit itself', a, [])
ev = x.run(1000)
check('the first step sounds at once (the grid starts with the first note), then every 1/16 (125 ms): 8 Note Ons in a second, each 1/32 later closed by a Note Off',
      (notes(ev)[:3], len(ons(ev)), len(offs(ev))), ([36, 36, 36], 8, 8))
t = [t for t, n in ons(ev)]
check('... the steps are 125 ms apart (+- 1.5 ms)', all(abs((b - a) - 125) <= 1.5 for a, b in zip(t, t[1:])), True, t)
to = [t for t, p in ev if p[0] == 8]
check('... and each note is closed half a step (62.5 ms) after it started', all(abs((o - n) - 62.5) <= 1.5 for n, o in zip(t, to)), True, (t[:3], to[:3]))
check('Note On velocity = the hit velocity (93)', {p[3] for t, p in ev if p[0] == 9}, {93})
b = x.lift(1); ev = x.run(300)
check('letting go stops the arp (a sounding note is closed at its gate, nothing new starts)', (notes(ev), b), ([], []))
check('no stuck note: every Note On has been matched by a Note Off', (len(notes(ev)), len(offs(ev))), (0, 0))
# rates
for r, name in enumerate(mc.ARP_RATES):
    x = arp_t(arp_rate=r); x.hit(1); ev = x.run(1500)
    per = PULSE_MS(120) * (24, 12, 8, 6, 4, 3, 2)[r]
    t = [t for t, n in ons(ev)]
    check(f'rate {name}: a step every {per:.1f} ms (the first sounds at once)', len(t) > 1 and all(abs((b - a) - per) <= 1.6 for a, b in zip(t, t[1:])), True, (t[:4], per))
x = arp_t(); x.hit(1); x.run(10); x.shift_tap('Note Repeat'); x.shift_tap('Note Repeat')
ev = x.run(1200); t = [t for t, n in ons(ev)]
check('Shift + Note Repeat steps the rate (1/16 -> 1/16T -> 1/32): steps now 62.5 ms apart', all(abs((b - a) - 62.5) <= 1.6 for a, b in zip(t, t[1:])), True, t[:5])
# patterns
def pattern(ty, oct_=1, held=(3, 1, 2), steps=12, pad_order=None):
    x = arp_t(arp_type=ty, arp_oct=oct_)
    for p in held: x.hit(p)
    ev = x.run(125 * steps + 40)
    return notes(ev)[:steps], ev
PADN = {1: 36, 2: 37, 3: 38}
seq, ev = pattern(0, steps=4)
check('repeat: all held notes together every step (3 pads: 3 Note Ons per step, 5 steps in 540 ms)', (len(notes(ev)), len({t for t, n in ons(ev)})), (15, 5))
seq, _ = pattern(1); check('up: 36 37 38 36 37 38 ... (sorted, whatever order the pads were pressed in)', seq, [36, 37, 38] * 4)
seq, _ = pattern(2); check('down: 38 37 36 ...', seq, [38, 37, 36] * 4)
seq, _ = pattern(3); check('up-down: 36 37 38 37 36 37 38 37 ... (the ends are not played twice)', seq, [36, 37, 38, 37] * 3)
seq, _ = pattern(4); check('played: in the order the pads were pressed (38 36 37)', seq, [38, 36, 37] * 4)
seq, _ = pattern(5, steps=30); check('random: only held notes, all of them show up, not always the same one', (set(seq) <= {36, 37, 38}, set(seq) == {36, 37, 38}, seq != [seq[0]] * 30), (True, True, True))
seq, _ = pattern(1, oct_=2, steps=12); check('up with 2 octaves: 36 37 38 48 49 50 36 ...', seq, [36, 37, 38, 48, 49, 50] * 2)
seq, _ = pattern(2, oct_=2, steps=6); check('down with 2 octaves: 50 49 48 38 37 36', seq, [50, 49, 48, 38, 37, 36])
seq, _ = pattern(3, oct_=2, steps=10); check('up-down with 2 octaves: 36 37 38 48 49 50 49 48 38 37 | 36 ...', seq[:10], [36, 37, 38, 48, 49, 50, 49, 48, 38, 37])
seq, _ = pattern(1, oct_=4, held=(1,), steps=5); check('4 octaves of one note: 36 48 60 72 36', seq, [36, 48, 60, 72, 36])
x = arp_t(arp_type=1, arp_oct=2, keys_root=120); x.tap('Keyboard'); x.hit(1)
ev = x.run(125 * 5 + 40); check('notes above 127 are skipped, not wrapped (root 120, 2 octaves: 120, then 132 = silent, 120, silent, 120)', ([t for t, n in ons(ev)], notes(ev)), ([1, 251, 501], [120, 120, 120]))
# chords through the arp
x = arp_t(arp_type=1); x.tap('Chords'); x.hit(1); ev = x.run(125 * 4 + 40)
check('a chord pad through the arp: the chord is arpeggiated (up: C E G C)', notes(ev)[:4], [60, 64, 67, 60])
# pads released and pressed
x = arp_t(arp_type=1); x.hit(1); x.hit(2); x.run(300); x.lift(1); ev = x.run(500)
check('letting go of one pad of two: the arp carries on with the other (37)', set(notes(ev)), {37})
# latch
x = arp_t(arp_type=1); x.tap('Lock'); x.hit(1); x.hit(2); x.run(200); x.lift(1); x.lift(2); ev = x.run(500)
nn = notes(ev)
check('latch: after both pads are released the arp keeps going, alternating 36 37 (and the Lock button is lit)', (len(nn) >= 4, set(nn), all(a != b for a, b in zip(nn, nn[1:])), x.led()[B['Lock']]), (True, {36, 37}, True, 0x7F))
x.hit(3); ev = x.run(500)
check('a new pad after everything was released replaces the latched notes (38 only)', set(notes(ev)), {38})
x.tap('Lock'); x.lift(3); ev = x.run(400)
check('Lock off with the pad up: the list is dropped, the arp stops (no more Note Ons)', notes(ev), [])
# arp off
x = arp_t(); x.hit(1); x.run(30); x.tap('Note Repeat'); ev = x.run(200)
check('Note Repeat off while a note sounds: the note is closed at once, nothing follows; the pad is a normal pad again', (offs(ev)[:1], notes(ev)), ([36], []))
x.lift(1)
check('... a hit now plays directly', x.hit(2), [NON(37)]); x.lift(2)
# modes
x = arp_t(arp_type=1); x.tap('Keyboard'); x.hit(1); x.hit(5); ev = x.run(125 * 4 + 40)
check('in Keyboard mode the arp plays the pads\' notes (pads 1 and 5 = 60 64)', notes(ev)[:4], [60, 64, 60, 64])
# pad held when the arp is switched on keeps sounding normally and is released normally
x = T(); a = x.hit(1); x.tap('Note Repeat'); b = x.lift(1)
check('a pad held when the arp is switched on keeps its note and is released with it', (a, b), ([NON(36)], [NOFF(36)]))
# SET and panic
x = arp_t(); x.hit(1); x.run(130); x.d.send_sysex(mc.set_request(PRESET)); ev = x.run(100)
check('a SET switches the arp off and the tick closes the note that was sounding', (offs(ev)[:1], notes(ev)), ([36], []))
x = arp_t(); x.hit(1); x.run(130); x.tap('Shift'); x.press('Shift', 'Mute'); x.release(); ev = x.run(200)
check('panic clears the arp (no more steps)', (notes(ev)), ([]))

# ---- external clock -------------------------------------------------------------------------------------------------------------------------------
def ext(x, n, gap_ms):
    """n incoming clock pulses, gap_ms apart; the events with times counted from the first pulse."""
    out, t0 = [], x.t
    for k in range(n):
        x.d.rx(bytes(CLK_PK))
        out += [(x.t - t0 + t, p) for t, p in x.run(gap_ms)]
    return out
CLK_PK = (0x0F, 0xF8, 0, 0)
x = arp_t(arp_type=1)
x.d.rx(bytes(START)); x.hit(1); x.hit(2)
ev = ext(x, 24 * 2, 10)
check('with a MIDI clock coming in (10 ms per pulse = 250 BPM) the arp follows it: 1/16 = 6 pulses = 60 ms; the first note waits for the grid',
      (len(ons(ev)) >= 7, all(abs((b - a) - 60) <= 2 for a, b in zip([t for t, n in ons(ev)], [t for t, n in ons(ev)][1:]))), (True, True))
check('... and no clock output was started by it', only(ev, CLK), [])
x.press('Shift', 'Tap'); x.release()
ev = ext(x, 24, 10)
check('with clock output on and an external clock the device does not echo the pulses', only(ev, CLK), [])
x = arp_t(arp_type=1); x.hit(1); x.d.rx(bytes(CLK_PK)); ev = x.run(100); ev = x.run(600)
check('when the external clock stops (400 ms without a pulse) the internal tempo takes over again (a note every 125 ms from then on)', (len(ons(ev)) >= 2, all(abs((b - a) - 125) <= 2 for (a, _), (b, _) in zip(ons(ev), ons(ev)[1:]))), (True, True), ons(ev))
x = arp_t(arp_type=1); x.d.rx(bytes(START)); x.hit(1); ev = ext(x, 3, 10); x.d.rx(bytes(STOP)); ev2 = x.run(30)
check('MIDI Stop from the host closes the note that is sounding', offs(ev2), [36])
x = T(); x.d.rx(bytes(CLK_PK)); ev = ext(x, 3, 5)
check('a MIDI clock byte is consumed by the firmware (not passed to NI\'s parser as a report)', x.d.stock_rx, 0)

# ---- mute and solo ------------------------------------------------------------------------------------------------------------------------------
LEDP = lambda x, pad: x.led()[39 + PADIDX[pad]]
PAD_REST, PAD_SOLO = 11 * 4 + 1, 11 * 4 + 2
x = T(); x.tap('Mute')
check('Mute on: its button lights', x.led()[B['Mute']], 0x7F)
a = x.hit(1); x.lift(1)
check('a hit in mute edit mode sends nothing and mutes the pad (its LED goes dark, the others rest)', (a, LEDP(x, 1), LEDP(x, 2)), ([], 0, PAD_REST))
x.tap('Mute')
check('Mute off: the muted pad is silent, the others play', (x.hit(1), x.hit(2)), ([], [NON(37)])); x.lift(1); x.lift(2)
x.tap('Mute'); x.hit(1); x.lift(1); x.tap('Mute')
a = x.hit(1); x.lift(1)
check('mute edit again on the muted pad unmutes it', (a, LEDP(x, 1)), ([NON(36)], PAD_REST))
x = T(); x.tap('Solo'); x.hit(2); x.lift(2); x.tap('Solo')
leds = (LEDP(x, 2), LEDP(x, 1), LEDP(x, 16)); a, b = x.hit(1), x.hit(2); x.lift(2)
check('Solo: the soloed pad is brighter, every other pad is silent and dark', (leds, a, b), ((PAD_SOLO, 0, 0), [], [NON(37)]))
x.tap('Solo'); x.hit(3); x.lift(3); x.tap('Solo')
check('two soloed pads both play', (x.hit(2)[0][2], x.hit(3)[0][2]), (37, 38)); x.lift(2); x.lift(3)
x.shift_tap('Solo')
leds = {LEDP(x, n) for n in range(1, 17)}
check('Shift + Solo clears every mute and solo: all pads play and rest in their colour', (x.hit(1), x.hit(16), leds), ([NON(36)], [NON(51)], {PAD_REST}))
x = T(); x.tap('Mute'); x.hit(1); x.lift(1); x.tap('Mute'); x.tap('Note Repeat'); x.hit(1); ev = x.run(300)
check('a muted pad does not reach the arp either', (notes(ev), x.hit(2)), ([], []))
x = T(); x.tap('Mute'); x.hit(1); x.lift(1); x.d.send_sysex(mc.set_request(PRESET)); [x.d.tick(0) for _ in range(5)]
a = x.hit(1); x.lift(1)
check('a SET clears the mutes', (a, LEDP(x, 1)), ([NON(36)], PAD_REST))

# ---- strumming ---------------------------------------------------------------------------------------------------------------------------------
x = T(); x.tap('Notes')
touch = lambda pos: x.d.translate(report1(pos=pos, enc=x.enc))
check('the Notes button selects strum and lights', x.led()[B['Notes']], 0x7F)
check('no pad held: the strip is divided among the 16 pad notes: position 1 -> 36 (velocity 100)', touch(1), [NON(36, 100)])
check('moving inside the zone changes nothing; the next zone closes 36 and starts 37 (position 13 -> zone 0, 14 -> zone 1)', (touch(12), touch(14)), ([], [NOFF(36), NON(37, 100)]))
check('position 200 -> the last note (51); letting go closes it', (touch(200)[-1], touch(0)), (NON(51, 100), [NOFF(51)]))
sweep = [p for pos in range(1, 201, 5) for p in touch(pos) if p[0] == 9]
check('a swipe over the whole strip plays all 16 notes upwards, once each', [p[2] for p in sweep], list(range(36, 52))); touch(0)
x.hit(1); x.hit(5); x.hit(9)
got = [p[2] for pos in (1, 70, 140, 200) for p in touch(pos) if p[0] == 9]
check('with pads 1, 5, 9 held (36, 40, 44) the strip is divided among their notes', got, [36, 40, 44])
touch(0); x.lift(1); x.lift(5); x.lift(9)
x.tap('Perform')
check('Perform leaves strum: the strip sends CC 1 again', touch(100), [CC(1, 63)])
x = T(); x.tap('Notes'); touch = lambda pos: x.d.translate(report1(pos=pos, enc=x.enc)); touch(100); x.tap('Mod'); ev = x.run(10)
check('changing the strip mode while a strum note sounds closes it', offs(ev), [36 + 99 * 16 // 200])

# ---- snapshot (Lock) ---------------------------------------------------------------------------------------------------------------------------
x = T(cfg(enc_cc=20)); x.tap('Volume')
def turn(n): x.enc = (x.enc + n) % 16; return x.d.translate(report1(enc=x.enc))
turn(5)
check('Shift + Lock stores the encoder target values (storing sends nothing)', (x.press('Shift', 'Lock'), x.release()), ([], []))
turn(10)
a = x.press('Shift', 'Lock'); x.release()
check('Shift + Lock again sends the stored values back: targets CC 7 / 10 / 11 = 69 / 64 / 64, mod wheel CC 1 = 0, the encoder\'s CC 20 = 0', a, [CC(7, 69), CC(10, 64), CC(11, 64), CC(1, 0), CC(20, 0)])
check('... and the encoder carries on from the recalled value (+1 -> 70)', turn(1), [CC(7, 70)])
c2 = bytearray(cfg(enc_cc=20)); c2[F['btn_act2'][0] + B['Erase']] = mc.ACT_SNAP; c2[F['btn_cc2'][0] + B['Erase']] = 1
x = T(bytes(c2)); x.tap('Volume'); turn(5); x.shift_tap('Lock'); turn(6)
x.shift_tap('Erase'); turn(3)
a = x.press('Shift', 'Lock'); x.release()
check('a button set to "store again" (parameter 1) replaces the snapshot: recalling now gives 75 (64 + 5 + 6), not the first 69', a[0], CC(7, 75))

# ---- the stack: the deepest the tick goes while the arp plays a 4-note chord with the clock out and the beat LED (the harness stack is 0x20004000 down) ----
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP
x = T(cfg(arp_type=3, arp_oct=4)); x.tap('Chords'); x.press('Shift', 'Tap'); x.release(); x.tap('Note Repeat')
for p in (1, 2, 3, 4): x.hit(p)
low = [0x20004000]
def track(uc, a, sz, u):
    sp = uc.reg_read(UC_ARM_REG_SP)
    if sp < low[0]: low[0] = sp
h = x.d.mu.hook_add(UC_HOOK_CODE, track); x.run(1500); x.d.mu.hook_del(h)
check(f'the grid in the tick (arp steps on 4 chords of 4 notes, clock out, beat LED) uses at most 420 bytes of stack ({0x20004000 - low[0]} measured; the stack_depth.py worst case adds the exception frame and the USB interrupt)', 0x20004000 - low[0] <= 420, True)

# ---- screen messages --------------------------------------------------------------------------------------------------------------------------
x = T(); sc = Screen(x.d)
def show(title, detail, action, bar=None):
    sc.run(250, 10); action(); sc.run(4)
    check(f'message: {title} / {detail}' + (f' / bar {bar}' if bar is not None else ''), sc.fb() == reference(title, detail, bar))
show('ARP', 'ON  REPEAT 1/16', lambda: x.tap('Note Repeat'))
show('ARP TYPE', 'UP', lambda: x.tap('Follow'))
show('RATE', '1/16T', lambda: x.shift_tap('Note Repeat'))
show('OCTAVES', '2', lambda: x.tap('Auto'))
show('LATCH', 'ON', lambda: x.tap('Lock'))
show('LATCH', 'OFF', lambda: x.tap('Lock'))
show('ARP', 'OFF', lambda: x.tap('Note Repeat'))
show('MUTE', 'ON', lambda: x.tap('Mute'))
show('MUTE', 'OFF', lambda: x.tap('Mute'))
show('SOLO', 'ON', lambda: x.tap('Solo'))
show('MUTE', 'CLEARED', lambda: x.shift_tap('Solo'))
show('TEMPO', '120 BPM', lambda: x.tap('Tap'), 100 * 118 // 255)
show('CLOCK OUT', 'ON  120 BPM', lambda: x.shift_tap('Tap'))
show('CLOCK OUT', 'OFF', lambda: x.shift_tap('Tap'))
show('STRIP', 'STRUM NOTES', lambda: x.tap('Notes'))
show('LOCK', 'STORED', lambda: x.shift_tap('Lock'))
show('LOCK', 'RECALLED', lambda: x.shift_tap('Lock'))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
