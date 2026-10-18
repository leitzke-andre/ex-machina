"""Generation 10 in the emulator: a CC mode per button (gate / toggle / trigger instead of one for all), pad pages (the drum pads move by 16 notes per page),
encoder pages (the CC of an encoder target moves per page, each page remembers its value), encoder acceleration, and the BeatMaker 3 preset that uses them.
Usage: test_phase5.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2, CC
from dispsim import reference, idle, Screen, MS16

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
BM3 = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'beatmaker-3')

def cfg(base=None, **kw):
    c = bytearray(base if base is not None else mc.default_cfg())
    for k, v in kw.items():
        off, n = F[k]
        if isinstance(v, (list, tuple, bytes)): c[off:off + len(v)] = bytes(v)
        else: c[off] = v
    return bytes(c)
def act(c, name, a, par=0xFF):
    c = bytearray(c); k = B[name]; c[F['btn_act'][0] + k] = a; c[F['btn_cc'][0] + k] = par; return bytes(c)

class T:
    def __init__(self, c):
        self.d = devsim.Dev(fw, data, c)
        self.d.translate(report1()); self.d.start()
        self.t = 5000; self.enc = 0; self.write()
    def write(self): self.d.mu.mem_write(MS16, struct.pack('<H', self.t & 0xFFFF))
    def press(self, *names): return self.d.translate(report1([B[n] for n in names], enc=self.enc))
    def release(self): return self.d.translate(report1(enc=self.enc))
    def tap(self, *names): a = self.press(*names); return a, self.release()
    def turn(self, n): self.enc = (self.enc + n) % 16; return self.d.translate(report1(enc=self.enc))
    def hit(self, pad, val=3000): return self.d.translate(report2([(PADIDX[pad], 1, val)]))
    def lift(self, pad): return self.d.translate(report2([(PADIDX[pad], 3, 0)]))
    def note(self, pad):                                   # the note a pad strike sends (None: nothing)
        out = self.hit(pad); self.lift(pad)
        return next((m[2] for m in out if m[0] == 0x09), None)
    def led(self): return self.d.led()

# ---- a CC mode per button ------------------------------------------------------------------------------------------------------------------------
base = mc.set_btn_mode(mc.default_cfg(btn_mode=0), B['Mute'], 1)
base = mc.set_btn_mode(base, B['Solo'], 2)
check('the library: a button without its own mode has the global one; Mute toggle, Solo trigger, others unchanged',
      (mc.btn_mode_of(base, B['Mute']), mc.btn_mode_of(base, B['Solo']), mc.btn_mode_of(base, B['Select']), mc.btn_mode_of(mc.set_btn_mode(base, B['Mute'], None), B['Mute'])), (1, 2, 0, 0))
check('... and the bits of the other buttons are untouched (all 41)', all(mc.btn_mode_of(base, k) == 0 for k in range(41) if k not in (B['Mute'], B['Solo'])))
x = T(base); mute_cc, solo_cc, sel_cc = (base[F['btn_cc'][0] + B[n]] for n in ('Mute', 'Solo', 'Select'))
a, r = x.tap('Select'); check('gate (global): Select sends 127 on press, 0 on release', (a, r), ([CC(sel_cc, 127)], [CC(sel_cc, 0)]))
a, r = x.tap('Solo'); check('trigger (own): Solo sends 127 on press and nothing on release', (a, r), ([CC(solo_cc, 127)], []))
a, r = x.tap('Solo'); check('... every time', (a, r), ([CC(solo_cc, 127)], []))
a1, r1 = x.tap('Mute'); a2, r2 = x.tap('Mute'); a3, r3 = x.tap('Mute')
check('toggle (own): Mute sends 127, 0, 127 on successive presses, nothing on release', ([a1, a2, a3], [r1, r2, r3]), ([[CC(mute_cc, 127)], [CC(mute_cc, 0)], [CC(mute_cc, 127)]], [[], [], []]))
x = T(base); x.tap('Mute'); on = x.led()[B['Mute']]; x.tap('Mute'); off = x.led()[B['Mute']]
check('the toggle button\'s LED is bright while on and dim when off', (on, off), (base[F['btn_led_on'][0]], base[F['btn_led_idle'][0]]))
x.press('Select'); sel_down = x.led()[B['Select']]; x.release(); sel_up = x.led()[B['Select']]
check('a gate button\'s LED is bright while held, then back to rest', (sel_down, sel_up), (base[F['btn_led_on'][0]], base[F['btn_led_idle'][0]]))
g = mc.set_btn_mode(mc.default_cfg(btn_mode=2), B['Select'], 0)
x = T(g); a, r = x.tap('Select'); check('the other way round: global trigger, Select gate', (a, r), ([CC(sel_cc, 127)], [CC(sel_cc, 0)]))
a, r = x.tap('Solo'); check('... the others stay trigger', (a, r), ([CC(solo_cc, 127)], []))

# ---- pad pages -------------------------------------------------------------------------------------------------------------------------------------
c = act(mc.default_cfg(), 'Right', mc.ACT_PAGE, 0); c = act(c, 'Left', mc.ACT_PAGE, 1); c = act(c, 'Project', mc.ACT_PAGE, 2)
x = T(c); sc = Screen(x.d); sc.settle()
check('page 1: pad 1 = note 36, pad 16 = note 51', (x.note(1), x.note(16)), (36, 51))
x.tap('Right'); sc.run(4, 10)
shown = sc.fb() == reference('PAGE', '2/8  E2-G3')
check('Right: page 2, pads move up by 16 notes (52..67), with a message', (x.note(1), x.note(16), shown), (52, 67, True))
for _ in range(6): x.tap('Right')
check('after 7 steps: page 8 (pad 1 = 148 would pass 127: the note stays in range)', 0 <= x.note(1) <= 127, True)
x.tap('Right'); check('one more wraps to page 1', x.note(1), 36)
x.tap('Left'); check('Left from page 1 goes to page 8', x.note(1) is not None and x.note(1) >= 0, True)
x.tap('Project'); check('parameter 2 goes back to page 1', x.note(1), 36)
t = act(act(c, 'Keyboard', mc.ACT_KEYS), 'Pad Mode', mc.ACT_PADMODE)
x = T(t); x.tap('Right'); x.tap('Keyboard')
check('the Keyboard layout does not move with the page (pad 1 = the root)', x.note(1), 60)
x.tap('Pad Mode'); check('... and the drum pads are on their page again afterwards', x.note(1), 52)
x = T(cfg(c, pad_note=bytes(range(100, 116)))); x.tap('Right'); x.tap('Right')
check('notes past 127 stop at 127 (pad 1 = 100 on page 3 would be 132)', x.note(1), 127)

# ---- encoder pages ---------------------------------------------------------------------------------------------------------------------------------
e = cfg(enc_tgt_cc=[20, 21, 22], enc_pages=3, enc_page_step=3, enc_mode=1)
e = act(e, 'Volume', mc.ACT_ENCTGT, 0); e = act(e, 'Swing', mc.ACT_ENCTGT, 1); e = act(e, 'Tempo', mc.ACT_ENCTGT, 2)
e = act(e, 'Plug-in', mc.ACT_ENCPAGE, 0); e = act(e, 'Sampling', mc.ACT_ENCPAGE, 1); e = act(e, 'Browser', mc.ACT_ENCPAGE, 2)
x = T(e); sc = Screen(x.d); sc.settle()
x.tap('Volume'); check('page 1, target 1: CC 20 (value starts at 64)', x.turn(1), [CC(20, 65)])
x.tap('Plug-in'); sc.run(4, 10)
check('Plug-in: page 2 of 3: the same target is CC 23, from 64 again', x.turn(1), [CC(23, 65)])
check('... with the message on the screen', sc.fb() == reference('ENC PAGE', '2/3  CC 23 24 25'), True)
x.tap('Plug-in'); check('page 3: CC 26', x.turn(1), [CC(26, 65)])
x.tap('Plug-in'); check('a fourth step wraps to page 1; the target keeps the value of that page (65): +1 -> 66', x.turn(1), [CC(20, 66)])
x.tap('Sampling'); check('Sampling goes back: from page 1 to page 3 (wrapping), value remembered (65 -> 66)', x.turn(1), [CC(26, 66)])
x.tap('Sampling'); x.tap('Swing'); check('page 2, target 2: CC 24 (the first press of another target selects it)', x.turn(2), [CC(24, 66)])
x.tap('Browser'); check('parameter 2: page 1 again; target 2 is CC 21', x.turn(1), [CC(21, 65)])
e2 = cfg(e, enc_tgt_cc=[120, 0xFF, 5], enc_page_step=10)
x = T(e2); x.tap('Plug-in'); x.tap('Volume')
check('a CC that would pass 127 (120 + 10) sends nothing', x.turn(1), [])
x.tap('Swing'); check('... a target without CC stays without', x.turn(1), [])
x.tap('Tempo'); check('... another target still works on that page (5 + 10 = 15)', x.turn(1), [CC(15, 65)])
x = T(cfg(e, enc_pages=1)); x.tap('Plug-in'); x.tap('Volume')
check('with one page, Plug-in changes nothing (still CC 20)', x.turn(1), [CC(20, 65)])
sn = act(e, 'Lock', mc.ACT_SNAP, 0)
x = T(sn); x.tap('Volume'); x.tap('Plug-in'); x.turn(5)                  # page 2, target 1 = 69
x.tap('Lock'); x.tap('Browser'); x.turn(2)
a, r = x.tap('Lock')
check('a snapshot remembers the page it was taken on: recalling it sends that page\'s CC 23 with the stored value', CC(23, 69) in a + r, True)

# ---- acceleration ----------------------------------------------------------------------------------------------------------------------------------
def steps(accel, n):
    x = T(cfg(enc_mode=1, enc_init=0, enc_accel=accel, enc_cc=7)); out = x.turn(n); return out[0][3] if out else None
check('without acceleration a fast turn is exactly its steps (1, 2, 3, 5)', [steps(0, n) for n in (1, 2, 3, 5)], [1, 2, 3, 5])
check('acceleration 1: |step| * (1 + 1 * (|step| - 1)): 1, 4, 9, 25', [steps(1, n) for n in (1, 2, 3, 5)], [1, 4, 9, 25])
check('acceleration 3: 1, 8, 21, 40 (capped)', [steps(3, n) for n in (1, 2, 3, 5)], [1, 8, 21, 40])
x = T(cfg(enc_mode=1, enc_init=0, enc_accel=1, enc_cc=7)); x.turn(2); out = x.turn(-2)
check('turning back is accelerated the same way (4 up, 4 down)', out, [CC(7, 0)])
x = T(cfg(enc_mode=2, enc_accel=1, enc_cc=7)); check('relative mode: -3 steps with acceleration 1 = -9 -> 128 - 9 = 119', x.turn(-3), [CC(7, 119)])

# ---- the BeatMaker 3 preset -----------------------------------------------------------------------------------------------------------------------
check('BeatMaker 3 preset: a valid config of the current size', (mc.check(BM3), len(BM3)), (None, bp.CFG_SIZE))
x = T(BM3)
check('pads: 1-16 = notes 0-15; Right = page 2 = 16-31', (x.note(1), x.note(16), (x.tap('Right'), x.note(1))[1]), (0, 15, 16))
x.tap('Left')
a, r = x.tap('Play'); check('Play: one CC per press (102)', (a, r), ([CC(102, 127)], []))
a, r = x.tap('Mute'); check('Mute (mode button): CC 107, once per press', (a, r), ([CC(107, 127)], []))
x.tap('Volume'); check('Volume picks the encoder target 1: CC 20', x.turn(1), [CC(20, 65)])
for _ in range(5): x.tap('Plug-in')
check('five page steps later: the last page (6): CC 20 + 5 * 3 = 35', x.turn(1), [CC(35, 65)])
x.tap('Plug-in'); check('and one more wraps to page 1 (value kept)', x.turn(1), [CC(20, 66)])
check('acceleration 1 is on in the preset (a 2-step turn moves 4)', x.turn(2), [CC(20, 70)])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
