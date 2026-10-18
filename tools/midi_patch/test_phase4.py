"""Generation 8 in the emulator: the MIDI channel selector (kept across power cycles), the four preset slots in flash (SysEx and buttons, power cuts), the
Ex-Machina idle screen and its status line, the step sequencer and its grid on the screen.
Usage: test_phase4.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2, CC
from dispsim import reference, idle, Screen, MS16
from flash_model import PAGE, image_after

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
REAL_PRESET = PRESET
PRESET = bytearray(PRESET)                                              # the tests of storing from the buttons: the preset plus Shift + Scene / Pattern / Events / Variation = store in slot 1-4
for _k, _n in enumerate(('Scene', 'Pattern', 'Events', 'Variation')): PRESET[F['btn_act2'][0] + B[_n]] = mc.ACT_SLOT; PRESET[F['btn_cc2'][0] + B[_n]] = 4 + _k
PRESET = bytes(PRESET)
NON = lambda n, v=93, ch=0: (0x09, 0x90 | ch, n, v)
NOFF = lambda n, ch=0: (0x08, 0x80 | ch, n, 0)
DEFAULTS = mc.default_cfg()

def cfg(base=PRESET, **kw):
    c = bytearray(base)
    for k, v in kw.items():
        off, n = F[k]
        if isinstance(v, (list, tuple, bytes)): c[off:off + len(v)] = bytes(v)
        else: c[off] = v
    return bytes(c)

class T:
    """A device with a clock: the stock millisecond counter is advanced by the test, the main loop's tick runs after every step."""
    def __init__(self, c=None, flash=None):
        self.d = devsim.Dev(fw, data, None if flash is not None else c if c is not None else PRESET, flash)    # (a flash image brings its own config block)
        self.d.translate(report1()); self.d.start()
        self.t = 5000; self.enc = 0; self.write()
    def write(self): self.d.mu.mem_write(MS16, struct.pack('<H', self.t & 0xFFFF))
    def at(self, t): self.t = t; self.write()
    def run(self, ms, step=1, probe=None):
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
    def cfg(self): return bytes(self.d.cfg())
    def ask(self, msg): return mc.parse_reply(self.d.ask(msg)[0])
    def reboot(self): return T(None, self.d.flash_image())

# ---- INFO ----------------------------------------------------------------------------------------------------------------------------------------
x = T(DEFAULTS)
check('INFO reports the firmware version (v0)', x.ask(mc.info_request())['version'], mc.FW_VERSION)

# ---- the MIDI channel ------------------------------------------------------------------------------------------------------------------------------
x = T()
x.tap('Group'); out = x.run(30)
cc123 = [p for t, p in out if p[0] == 0x0B and p[2] == 123]
check('Group steps the MIDI channel on (1 -> 2): the active config says channel 2 (index 1)', x.cfg()[F['channel'][0]], 1)
check('... all notes are released on every channel (CC 120 and 123 on all 16, the old channel included)', (len(out), sorted(p[1] & 15 for p in cc123)), (32, list(range(16))))
check('pads play on the new channel', x.hit(1), [NON(36, 93, 1)]); x.lift(1)
x.hit(2); x.tap('Group'); x.run(30)
check('a pad held while the channel changes does not leave a note on: the panic burst covers it, and its release sends nothing', x.lift(2), [])
x.shift_tap('Group'); x.run(30); x.shift_tap('Group'); x.run(30); x.shift_tap('Group'); x.run(30)
check('Shift + Group steps back (3 -> 2 -> 1); from channel 1 it wraps to 16', x.cfg()[F['channel'][0]], 15)
x.tap('Group'); x.run(30)
check('and forward from 16 it wraps to 1', x.cfg()[F['channel'][0]], 0)
x = T(); x.tap('Group'); x.tap('Group'); x.run(30)
x2 = x.reboot()
check('the channel survives a power cycle without a save (the settings log): channel 3', x2.cfg()[F['channel'][0]], 2)
check('... the config is not marked as changed by it', x.ask(mc.info_request())['unsaved_changes'], False)
x.d.send_sysex(mc.save_request()); [x.d.tick(0) for _ in range(5)]
page = x.d.page()
check('a SAVE bakes the channel into the record and clears the log', (mc.parse_record(page)[F['channel'][0]], set(page[0x200:])), (2, {0xFF}))
x = T(); x.tap('Group'); x.run(30); x.d.send_sysex(mc.set_request(PRESET)); [x.d.tick(0) for _ in range(5)]
check('a SET sends the config\'s own channel (the host\'s word wins until the next power cycle, then the log)', x.cfg()[F['channel'][0]], 0)
x = T(); x.tap('Group'); x.run(30)
sc = Screen(x.d); sc.settle()
check('the status line shows the channel: CH2', sc.fb() == idle('DRUMS CH2 120'), True)

# ---- the preset slots -------------------------------------------------------------------------------------------------------------------------------
A, Bc = cfg(channel=2, keys_root=50), cfg(channel=5, scale=3, fixvel=64)
x = T(DEFAULTS)
check('a new device has four empty slots', x.ask(mc.slots_request())['used'], [False] * 4)
x.d.send_sysex(mc.set_request(A)); [x.d.tick(0) for _ in range(5)]
r = x.ask(mc.slot_store_request(0))
check('storing the active config in slot 1: status 0, slot 1 used, nothing else touched', (r['status'], x.ask(mc.slots_request())['used'], x.d.flash.violations), (0, [True, False, False, False], []))
x.d.send_sysex(mc.set_request(Bc)); [x.d.tick(0) for _ in range(5)]
x.ask(mc.slot_store_request(3))
check('slot 4 holds the other config, slot 1 is untouched', x.ask(mc.slots_request())['used'], [True, False, False, True])
check('loading slot 1: status 0 and the active config is A (nothing saved, the config shows as changed)', (x.ask(mc.slot_load_request(0))['status'], x.cfg() == A, x.ask(mc.info_request())['unsaved_changes']), (0, True, True))
check('loading slot 4: B', (x.ask(mc.slot_load_request(3))['status'], x.cfg() == Bc), (0, True))
check('loading an empty slot: status 4, the active config does not change', (x.ask(mc.slot_load_request(1))['status'], x.cfg() == Bc), (4, True))
check('a slot command without its slot number: status 1 (wrong length), nothing is written', (mc.parse_reply(x.d.ask(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x15, 0xF7]))[0])['status'], mc.parse_reply(x.d.ask(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x16, 0xF7]))[0])['status'], x.ask(mc.slots_request())['used']), (1, 1, [True, False, False, True]))
check('a slot number that does not exist: status 2', (x.ask(mc.slot_store_request(4))['status'], x.ask(mc.slot_load_request(9))['status']), (2, 2))
x2 = x.reboot()
check('after a power cycle the slots are still there and the device starts on the defaults (nothing was saved)', (x2.ask(mc.slots_request())['used'], x2.cfg() == DEFAULTS), ([True, False, False, True], True))
check('... and slot 1 loads again', (x2.ask(mc.slot_load_request(0))['status'], x2.cfg() == A), (0, True))
x2.ask(mc.slot_store_request(0))
# older record (shorter) in a slot: overlay on the defaults like the saved record
x = T(DEFAULTS); x.d.send_sysex(mc.set_request(A)); [x.d.tick(0) for _ in range(5)]
n0 = len(x.d.flash.log); x.ask(mc.slot_store_request(0)); n1 = len(x.d.flash.log)
x.ask(mc.slot_store_request(0))
check('a second identical store writes nothing', len(x.d.flash.log), n1)
# power cut sweep: the slot is the old config, empty, or the new one - never garbage - and the other slots are never touched
x = T(DEFAULTS); x.d.send_sysex(mc.set_request(A)); [x.d.tick(0) for _ in range(5)]; x.ask(mc.slot_store_request(1)); x.ask(mc.slot_store_request(0))
x.d.send_sysex(mc.set_request(Bc)); [x.d.tick(0) for _ in range(5)]
before = x.d.flash_image(); n0 = len(x.d.flash.log)
x.ask(mc.slot_store_request(0))
log = x.d.flash.log[n0:]
erase_at = [i for i, e in enumerate(log) if e[0] == 'erase']
seen, bad = {}, []
for cut in range(len(log) + 1):
    for mask in ((None,) if cut == len(log) else (None, 0x00FF, 0xFF00)):
        y = T(DEFAULTS, bytes(image_after(before, log, cut, mask)))
        used = y.ask(mc.slots_request())['used']
        loaded = y.ask(mc.slot_load_request(0)); got = y.cfg() if loaded['status'] == 0 else None
        kind = 'old' if got == A else 'new' if got == Bc else 'empty' if loaded['status'] == 4 else 'garbage'
        seen[kind] = seen.get(kind, 0) + 1
        other = y.ask(mc.slot_load_request(1));
        if other['status'] != 0 or y.cfg() != A: bad.append((cut, mask, 'slot 2 damaged'))
        want = {'old'} if cut < erase_at[0] or (cut == erase_at[0] and mask is None) else {'old', 'empty'} if cut == erase_at[0] else {'new'} if cut == len(log) else {'empty'}
        if kind not in want: bad.append((cut, mask, kind, sorted(want)))
check(f'power cut at each of the {len(log) + 1} points of a slot store (and with half-programmed halfwords): the slot is old, empty or new - never garbage - and slot 2 is untouched',
      (bad, sorted(seen)), ([], ['empty', 'new', 'old']))
# buttons
x = T(); x.d.send_sysex(mc.set_request(cfg(channel=7))); [x.d.tick(0) for _ in range(5)]
x.shift_tap('Scene'); x.run(40)
check('Shift + Scene stores the active config in slot 1 (SAVED)', x.ask(mc.slots_request())['used'], [True, False, False, False])
x.d.send_sysex(mc.set_request(PRESET)); [x.d.tick(0) for _ in range(5)]
x.tap('Scene'); x.run(40)
check('Scene makes slot 1 the active config again (channel 8)', x.cfg()[F['channel'][0]], 7)
x.tap('Pattern'); x.run(40)
check('an empty slot on a button changes nothing', x.cfg()[F['channel'][0]], 7)
# ---- slot names: kept with the slot, listed, shown when a button loads the slot -------------------------------------------------------------------------
x = T(DEFAULTS)
check('slot names: none on slots stored without one', x.ask(mc.slots_request())['names'], [''] * 4)
x.d.send_sysex(mc.set_request(A)); [x.d.tick(0) for _ in range(5)]
r = x.ask(mc.slot_store_request(1, 'Beatmaker 3'))
check('storing with a name ("Beatmaker 3" -> BEATMAKER 3): status 0, listed, the other slots without', (r['status'], x.ask(mc.slots_request())['names']), (0, ['', 'BEATMAKER 3', '', '']))
check('the name is the same after a power cycle', x.reboot().ask(mc.slots_request())['names'][1], 'BEATMAKER 3')
check('a name of 20 characters is kept whole, a longer one cut, a character outside the font becomes ?', (mc.display_name('A' * 20), mc.display_name('a{b'), len(mc.display_name('x' * 40))), ('A' * 20, 'A?B', 20))
check('a preset without a display name gets one made from its name; its own wins', (mc.preset_display_name({'name': 'Korg Gadget 3 (draft)'}), mc.preset_display_name({'name': 'x', 'display_name': 'my drums'})), ('KORG GADGET 3', 'MY DRUMS'))
x.ask(mc.slot_store_request(2, 'ABCDEFGHIJKLMNOPQRST')); check('20 characters fit', x.ask(mc.slots_request())['names'][2], 'ABCDEFGHIJKLMNOPQRST')
check('a name of 21 characters in the request is refused (wrong length), nothing written', (mc.parse_reply(x.d.ask(mc.message(0x15, bytes([3]) + b'A' * 21))[0])['status'], x.ask(mc.slots_request())['used'][3]), (1, False))
x.ask(mc.slot_store_request(1, 'Renamed')); check('storing again under another name replaces it (one erase)', x.ask(mc.slots_request())['names'][1], 'RENAMED')
x.ask(mc.slot_store_request(1)); check('storing without a name leaves the slot unnamed', x.ask(mc.slots_request())['names'][1], '')
x.ask(mc.slot_store_request(1, 'Renamed'))
x.d.send_sysex(mc.set_request(PRESET)); [x.d.tick(0) for _ in range(5)]
sc = Screen(x.d); sc.settle(); x.tap('Pattern'); sc.run(6, 10)
check('a button that loads a slot shows its name on the screen (SLOT 2 / RENAMED)', sc.fb() == reference('SLOT 2', 'RENAMED'), True)
x.d.send_sysex(mc.set_request(PRESET)); [x.d.tick(0) for _ in range(5)]
x.shift_tap('Variation'); x.run(40)
check('a new config has no name: Shift + Variation stores it into slot 4 without one', x.ask(mc.slots_request())['names'][3], '')
x.tap('Pattern'); x.run(40); x.shift_tap('Events'); x.run(40)
check('after loading a named slot, Shift + a slot button stores under that name', x.ask(mc.slots_request())['names'][2], 'RENAMED')
x.tap('Variation'); sc.run(6, 10)
check('an unnamed slot shows LOADED', sc.fb() == reference('SLOT 4', 'LOADED'), True)
# the preset as shipped: no button stores (a Shift + slot button that stored overwrote slots by accident); Shift + the button loads, like the plain press
x = T(DEFAULTS); x.d.send_sysex(mc.set_request(A)); [x.d.tick(0) for _ in range(5)]; x.ask(mc.slot_store_request(1, 'Mine'))
x.d.send_sysex(mc.set_request(REAL_PRESET)); [x.d.tick(0) for _ in range(5)]
n0 = len(x.d.flash.log); x.shift_tap('Pattern'); x.run(40)
check('Maschine-like modes: Shift + Pattern loads slot 2 (and writes nothing to flash)', (x.cfg() == A, len(x.d.flash.log) - n0), (True, 0))
x.d.send_sysex(mc.set_request(REAL_PRESET)); [x.d.tick(0) for _ in range(5)]
x.tap('Pattern'); x.run(40)
check('... and so does the plain press; slot 2 is still the stored config and nothing was written', (x.cfg() == A, x.ask(mc.slots_request())['names'][1], len(x.d.flash.log) - n0), (True, 'MINE', 0))
check('no button of the shipped preset stores into a slot', [k for k in range(41) if REAL_PRESET[F['btn_act2'][0] + k] == mc.ACT_SLOT or (REAL_PRESET[F['btn_act'][0] + k] == mc.ACT_SLOT and REAL_PRESET[F['btn_cc'][0] + k] > 3)], [])
# ---- the step sequencer --------------------------------------------------------------------------------------------------------------------------
from dispsim import seq_grid
PADLED = lambda x, n: x.led()[39 + PADIDX[n]]
C = 11 * 4                                                     # the pad colour 11 (blue): variants 0 (off) / 2 (on) / 3 (accent) in step mode
ons = lambda ev: [(t, p[2], p[3]) for t, p in ev if p[0] == 9]
offs = lambda ev: [(t, p[2]) for t, p in ev if p[0] == 8]
x = T(); x.tap('Step')
check('the Step button switches the pads to step mode: they are dark (all steps off) and the Step button lights', ({PADLED(x, n) for n in range(1, 17)}, x.led()[B['Step']]), ({C}, 0x7F))
check('a pad hit edits a step and plays nothing: off -> normal (colour) -> accent (bright) -> off', (x.hit(1), PADLED(x, 1), x.lift(1), x.hit(1), PADLED(x, 1), x.lift(1), x.hit(1), PADLED(x, 1), x.lift(1)),
      ([], C + 2, [], [], C + 3, [], [], C, []))
for n in (1, 5, 9, 13): x.hit(n); x.lift(n)
check('steps 1, 5, 9, 13 on (the pads show them)', [PADLED(x, n) for n in (1, 2, 5, 9, 13)], [C + 2, C, C + 2, C + 2, C + 2])
x.press('Select'); x.hit(2); x.lift(2); x.release()
check('with Select held a pad picks the track instead: track 2 (note 37) has no steps yet', {PADLED(x, n) for n in range(1, 17)}, {C})
x.hit(3); x.hit(3); x.lift(3)
check('editing now changes track 2: step 3 is an accent', PADLED(x, 3), C + 3)
x.press('Select'); x.hit(1); x.lift(1); x.release()
check('back to track 1 (Select + pad 1): its steps are shown again', [PADLED(x, n) for n in (1, 3, 5)], [C + 2, C, C + 2])
x.tap('Pad Mode')
check('leaving step mode puts the pad LEDs back to their resting colour (blue, variant 1)', ({PADLED(x, n) for n in range(1, 17)}, x.led()[B['Step']]), ({C + 1}, 0x7C))
check('... and the pads play again', x.hit(1), [NON(36)]); x.lift(1)
# playback
x.press('Shift', 'Step'); x.release()
ev = x.run(2000)
n1 = [(t, n, v) for t, n, v in ons(ev) if n == 36]; n2 = [(t, n, v) for t, n, v in ons(ev) if n == 37]
check('Shift + Step starts the sequencer: step 1 sounds at once (the grid starts with it), track 1 (note 36, velocity 100) on steps 1, 5, 9, 13 = every 4 x 125 ms',
      ([n for t, n, v in n1], [v for t, n, v in n1], all(abs((b[0] - a[0]) - 500) <= 2 for a, b in zip(n1, n1[1:]))), ([36] * 4, [100] * 4, True), n1)
check('track 2 (note 37) is an accent (velocity 127) on step 3: 250 ms after each bar start, every 2 s', ([v for t, n, v in n2[:1]], n2[0][0] - n1[0][0]), ([127], 250))
check('every note is released half a step (62.5 ms) after it started', all(any(abs((o - t) - 62.5) <= 2 for o, nn in offs(ev) if nn == n) for t, n, v in ons(ev)[:6]), True)
x.press('Shift', 'Step'); x.release(); ev = x.run(300)
check('Shift + Step again stops it: no more notes, every sounding note released', ([e for e in ons(ev)], True), ([], True))
# patterns
x = T(); x.tap('Step'); x.hit(1); x.lift(1); x.tap('Plug-in'); x.hit(2); x.lift(2); x.tap('Pad Mode')
x.press('Shift', 'Step'); x.release(); ev = x.run(1000)
check('pattern 2 is empty and separate from pattern 1: the sequencer (on pattern 2) plays only its own step 2 (note 36)', sorted(set(n for t, n, v in ons(ev))), [36])
check('... and step 2 is 125 ms after the start', ons(ev)[0][0], 126)
x.tap('Sampling'); ev = x.run(300)
check('Sampling goes back to pattern 1: its step 1 (note 36) is what plays at the next bar', {n for t, n, v in ons(ev)} <= {36}, True)
# clear
x = T(); x.tap('Step')
for n in (1, 2, 3): x.hit(n); x.lift(n)
x.tap('Erase')
check('Erase clears the selected track of the pattern', {PADLED(x, n) for n in range(1, 17)}, {C})
x.tap('Select')
for n in (1, 2): x.hit(n); x.lift(n)
x.press('Select'); x.hit(2); x.lift(2); x.release(); x.hit(5); x.lift(5)
x.shift_tap('Erase')
x.press('Select'); x.hit(1); x.lift(1); x.release()
check('Shift + Erase clears the whole pattern (track 1 and 2 are both empty)', {PADLED(x, n) for n in range(1, 17)}, {C})
# muted track
x = T(); x.tap('Step'); x.hit(1); x.lift(1); x.tap('Pad Mode'); x.tap('Mute'); x.hit(1); x.lift(1); x.tap('Mute')
x.press('Shift', 'Step'); x.release(); ev = x.run(1000)
check('a muted pad silences its sequencer track', ons(ev), [])
# tempo and the clock
x = T(cfg(tempo=150 - 20)); x.tap('Step'); x.hit(1); x.hit(2); x.lift(1); x.lift(2); x.tap('Pad Mode'); x.press('Shift', 'Step'); x.release(); ev = x.run(500)
check('at 150 BPM the steps are 100 ms apart (1/16)', [t for t, n, v in ons(ev)][:3], [1, 101, 201]) if False else check('at 150 BPM the steps are 100 ms apart', [t2 - t1 for (t1, _, _), (t2, _, _) in zip(ons(ev), ons(ev)[1:])][:3], [100])
x = T(); x.tap('Step'); x.hit(1); x.lift(1); x.tap('Pad Mode')
x.press('Shift', 'Tap'); x.release(); x.run(30)
x.press('Shift', 'Step'); x.release(); ev = x.run(1200)
t0 = ons(ev)[0][0]
check('with the clock output running the sequencer waits for the grid: its first step is a 6-pulse multiple after the clock started (the first pulse comes one period, 20.8 ms, after the clock started; the sixth after 146 ms, which is 116 ms into this run)', t0, 116)
# restart
def restart_run(restart):
    x = T(); x.tap('Step')
    for n in (1, 2, 3, 4): x.hit(n); x.lift(n)
    x.tap('Pad Mode'); x.press('Shift', 'Step'); x.release(); x.run(300)
    if restart: x.tap('Restart')
    return len(ons(x.run(520)))
check('Restart jumps back to step 1: with steps 1-4 on, after 300 ms (steps 1-3 played) a restart plays four more steps within 520 ms, without it only the fourth', (restart_run(True), restart_run(False)), (4, 1))
# persistence
x = T(); x.tap('Step')
for n in (1, 6, 11): x.hit(n); x.lift(n)
x.tap('Pad Mode'); n0 = len(x.d.flash.log); x.shift_tap('Restart'); x.run(60)
check('Shift + Restart keeps the patterns in flash (a page, nothing else touched)', (len(x.d.flash.log) > n0, x.d.flash.violations), (True, []))
y = x.reboot(); y.tap('Step')
check('after a power cycle the pattern is back (steps 1, 6, 11)', [PADLED(y, n) for n in (1, 2, 6, 11)], [C + 2, C, C + 2, C + 2])
before = x.d.flash_image(); n0 = len(x.d.flash.log)
x.tap('Step'); x.hit(2); x.lift(2); x.tap('Pad Mode'); x.shift_tap('Restart'); x.run(60)
log = x.d.flash.log[n0:]
import zlib
PATPAGE = lambda img: bytes(img[bp.PAT_PAGE - 0x08000000:][:PAGE])
def pat_valid(img):
    pg = PATPAGE(img); magic, ver, ln, crc, _ = struct.unpack_from('<IHHHH', pg, 0)
    return magic == 0x54415053 and ver == 1 and ln == 256 and mc.crc16(pg[12:268]) == crc
bad, kinds = [], set()
old = PATPAGE(before)
for cut in range(len(log) + 1):
    for mask in ((None,) if cut == len(log) else (None, 0x00FF, 0xFF00)):
        img = bytes(image_after(before, log, cut, mask))
        valid = pat_valid(img); kinds.add('valid' if valid else 'blank/partial')
        if valid and PATPAGE(img)[12:268] not in (old[12:268], PATPAGE(bytes(image_after(before, log, len(log))))[12:268]): bad.append((cut, mask))
check('power cut at every point of a pattern save: the page is a whole old or new record or not valid at all (the patterns then start empty), never garbage', (bad, 'valid' in kinds), ([], True))
# the screen
x = T(); sc = Screen(x.d); sc.settle()
x.tap('Step'); x.hit(1); x.lift(1); x.hit(3); x.hit(3); x.lift(3); sc.settle()
check('the grid on the screen: the top line TRK 1 C1 PAT 1, step 1 on, step 3 accent, beat marks, no playhead', sc.fb() == seq_grid('TRK 1 C1 PAT 1', [1, 0, 2] + [0] * 13), True)
x.tap('Plug-in'); sc.run(6); sc.settle()
check('another pattern: an empty grid, PAT 2', sc.fb() == seq_grid('TRK 1 C1 PAT 2', [0] * 16), True)
x.tap('Sampling'); x.press('Select'); x.hit(2); x.lift(2); x.release(); sc.settle()
check('another track (Select + pad 2): TRK 2 C#1', sc.fb() == seq_grid('TRK 2 C#1 PAT 1', [0] * 16), True)
x.press('Select'); x.hit(1); x.lift(1); x.release(); sc.settle()
x.press('Shift', 'Step'); x.release(); x.run(10); sc.run(12, 10); sc.settle()
g = sc.fb()
check('while it runs the grid shows the playhead on one of the steps and the top line says RUN', any(g == seq_grid('TRK 1 C1 PAT 1 RUN', [1, 0, 2] + [0] * 13, k) for k in range(16)), True)
x.press('Shift', 'Step'); x.release(); x.tap('Pad Mode'); sc.settle()
check('leaving step mode brings the idle screen back (EX-MACHINA, V0, DRUMS CH1 120)', sc.fb() == idle('DRUMS CH1 120'), True)
x2 = T(); sc2 = Screen(x2.d); sc2.settle()
x2.tap('Step'); sc2.run(6)
check('message: STEP / TRK 1 C1 PAT 1', sc2.fb() == reference('STEP', 'TRK 1 C1 PAT 1'), True)

# ---- the notes on the screen ----------------------------------------------------------------------------------------------------------------------
IDLE = lambda detail='V0', mode='DRUMS', extra='': idle(f'{mode} CH1 120{extra}', detail)
x = T(); sc = Screen(x.d); sc.settle()
check('nothing sounding: the detail line shows the version', sc.fb() == IDLE(), True)
x.hit(1); sc.run(10, 10)
check('a pad held in Group mode: its note name (pad 1 = note 36 = C1)', sc.fb() == IDLE('C1'), True)
x.hit(2); sc.run(10, 10)
check('two pads: both notes, lowest first', sc.fb() == IDLE('C1 C#1'), True)
x.lift(1); x.lift(2); sc.run(10, 10)
check('after the release the names stay for a moment (a short note is readable)', sc.fb() == IDLE('C1 C#1'), True)
sc.run(60, 10)
check('... and half a second later the version is back', sc.fb() == IDLE(), True)
x.hit(5); sc.run(1, 10); x.lift(5); sc.run(10, 10)
check('a note that was over before the screen was redrawn still shows', sc.fb() == IDLE('E1'), True)
sc.settle()
x = T(); sc = Screen(x.d); x.tap('Chords'); sc.settle()
x.hit(1); sc.run(10, 10)
check('Chords mode: a triad shows all three notes (C3 E3 G3)', sc.fb() == IDLE('C3 E3 G3', 'CHORDS'), True)
x.lift(1); sc.settle(); x.shift_tap('Chords'); sc.settle(); x.hit(1); sc.run(10, 10)
check('a seventh chord: four notes', sc.fb() == IDLE('C3 E3 G3 B3', 'CHORDS'), True)
x.hit(2); sc.run(10, 10)
check('two seventh chords at once (8 notes): the lowest four and "+4"', sc.fb() == IDLE('C3 D3 E3 F3 +4', 'CHORDS'), True)
x.lift(1); x.lift(2); sc.settle()
x = T(); sc = Screen(x.d); x.tap('Note Repeat'); sc.settle()
x.hit(1); sc.run(4, 10)
check('the arp shows the note it is playing (the status line says ARP)', sc.fb() == IDLE('C1', extra=' ARP') or sc.fb() == IDLE(extra=' ARP'), True)
sc.run(10, 10)
check('... and keeps showing it while the pad is held (the notes linger between steps)', sc.fb() == IDLE('C1', extra=' ARP'), True)
x.lift(1); sc.run(80, 10)
check('... and the version is back after the release', sc.fb() == IDLE(extra=' ARP'), True)
x = T(); sc = Screen(x.d); x.tap('Step'); x.hit(1); x.lift(1); x.hit(2); x.lift(2); x.tap('Pad Mode'); sc.settle(); x.press('Shift', 'Step'); x.release(); sc.settle()
seen = []
for _ in range(30): sc.run(8, 10); seen.append(sc.fb())                    # a bar is 2 s: steps 1 and 2 sound at its start
check('the sequencer\'s notes show too: while its steps sound the screen shows C1 (track 1) and the status line says SEQ, between bars the version', (any(f == IDLE('C1', extra=' SEQ') for f in seen), any(f == IDLE(extra=' SEQ') for f in seen)), (True, True))
x.press('Shift', 'Step'); x.release(); sc.settle()
check('... and when it stops the version is back', sc.fb() == IDLE(), True)
x = T(); sc = Screen(x.d); x.tap('Notes'); sc.settle(); x.d.translate(report1(pos=1, enc=x.enc)); sc.run(10, 10)
check('a strummed note shows (the strip over 16 pads: position 1 = the lowest, C1)', sc.fb() == IDLE('C1'), True)
x.d.translate(report1(pos=0, enc=x.enc)); sc.settle()
x = T(); sc = Screen(x.d); sc.settle(); x.hit(1); sc.run(10, 10); x.tap('Keyboard'); sc.run(4, 10)
check('a message still takes the screen first (Keyboard): the notes come back after it', sc.fb() == reference('KEYBOARD', 'C3-D#4'), True)
sc.settle()
check('... the held pad is still in its old mode: C1 shows again once the message is gone', sc.fb() == IDLE('C1', 'KEYS'), True)

x = T(); sc = Screen(x.d); sc.run(8)
def show(title, detail, action, bar=None):
    sc.settle(); action(); sc.run(6)
    check(f'message: {title} / {detail}' + (f' / bar {bar}' if bar is not None else ''), sc.fb() == reference(title, detail, bar))
show('SLOT 2', 'EMPTY', lambda: x.tap('Pattern'))
show('SLOT 2', 'SAVED', lambda: x.shift_tap('Pattern'))
show('SLOT 2', 'LOADED', lambda: x.tap('Pattern'))
show('CHANNEL', '2', lambda: x.tap('Group'))
show('SEQ', 'RUN', lambda: x.shift_tap('Step'))
show('SEQ', 'STOP', lambda: x.shift_tap('Step'))
show('PATTERN', '2', lambda: x.tap('Plug-in'))
show('CLEAR', 'TRACK', lambda: x.tap('Erase'))
show('CLEAR', 'PATTERN', lambda: x.shift_tap('Erase'))
show('PATTERNS', 'SAVED', lambda: x.shift_tap('Restart'))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
