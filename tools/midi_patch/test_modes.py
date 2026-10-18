"""The controller's own functions in the emulator: pad modes (Group / Keyboard), Fixed Vel, 16 Velocities, the velocity-curve selector and
its settings log in flash, transpose, panic, the shift layer, pad pressure options, the LEDs that show the modes, and the display messages
(rendered by the firmware, compared with an independent pixel-by-pixel reference, and the idle screen drawn again afterwards).

The stock display routine (copy of the staging buffer into the framebuffer, clear of the "pending" flag) is modelled in Python here; the
disassembly of 0x08003f34 shows nothing else happens to the bytes.
Usage: test_modes.py <patched.bin> <data_init.bin>"""
import os, random, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2, CC, STRUCT
from flash_model import PAGE, image_after

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

F = mc.FIELDS
B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}
PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}              # printed pad number -> index in the report
NON = lambda n, v, ch=0: (0x09, 0x90 | ch, n, v)
NOFF = lambda n, ch=0: (0x08, 0x80 | ch, n, 0)
MS16 = 0x200010E8
FB, DISP_FLAG, DISP_HDR, DISP_DATA = 0x200010F2, 0x200012F8, 0x200013A1, 0x200013A9
LOG_BASE = bp.SAVE_PAGE + 0x200

def modes_cfg(**kw):
    """The 'Maschine-like' assignment: mode buttons, Shift, curve on Shift+Volume / Shift+Swing, panic on Shift+Mute, transpose on the arrows."""
    c = bytearray(mc.default_cfg())
    def act(name, a, par=0xFF, shifted=False):
        k = B[name]
        c[F['btn_act2' if shifted else 'btn_act'][0] + k] = a; c[F['btn_cc2' if shifted else 'btn_cc'][0] + k] = par
    act('Pad Mode', mc.ACT_PADMODE); act('Keyboard', mc.ACT_KEYS); act('Fixed Vel', mc.ACT_FIXVEL); act('Fixed Vel', mc.ACT_VEL16, shifted=True)
    act('Shift', mc.ACT_SHIFT)
    act('Volume', mc.ACT_CURVE, 0, shifted=True); act('Swing', mc.ACT_CURVE, 1, shifted=True)
    act('Mute', mc.ACT_PANIC, shifted=True)
    act('Left', mc.ACT_TRANSPOSE, 63); act('Right', mc.ACT_TRANSPOSE, 65)
    act('Left', mc.ACT_TRANSPOSE, 52, shifted=True); act('Right', mc.ACT_TRANSPOSE, 76, shifted=True)
    for k, v in kw.items(): c[F[k][0]] = v
    return bytes(c)

PRESET = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'maschine-modes')
P2 = {B[n] for n in ('Chords', 'Step', 'Keyboard', 'Pad Mode', 'Pitch', 'Mod', 'Perform', 'Volume', 'Swing', 'Tempo', 'Favorites', 'Browser', 'Project',
                     'Notes', 'Tap', 'Note Repeat', 'Follow', 'Auto', 'Lock', 'Mute', 'Solo', 'Select', 'Plug-in', 'Sampling', 'Erase', 'Restart', 'Group', 'Scene', 'Pattern',
                     'Events', 'Variation')}   # assigned by the later generations
check('the built-in preset "Maschine-like modes" has the phase 1 assignments these tests use for every button that phase 2 did not touch',
      [k for k in range(41) if k not in P2 and any(PRESET[F[f][0] + k] != modes_cfg()[F[f][0] + k] for f in ('btn_act', 'btn_cc', 'btn_act2', 'btn_cc2'))], [])

def Dev(cfg=None, flash=None):
    d = devsim.Dev(fw, data, cfg, flash); d.translate(report1()); return d

def press(d, *names):                                                  # press (and keep down) the named buttons, return what was sent
    return d.translate(report1([B[n] for n in names]))
def release(d): return d.translate(report1())
def tap(d, *names):
    out = press(d, *names); return out, release(d)
def hit(d, pad, val=3000): return d.translate(report2([(PADIDX[pad], 1, val)]))
def lift(d, pad): return d.translate(report2([(PADIDX[pad], 3, 0)]))

# ---- pad modes, notes, velocity ---------------------------------------------------------------------------------------------------
d = Dev(modes_cfg()); d.start()
check('Group mode (the start): pad 1 plays the configured note 36, pad 16 plays 51', (hit(d, 1), hit(d, 16)), ([NON(36, 93)], [NON(51, 93)]))
lift(d, 1); lift(d, 16)
check('the Keyboard button sends nothing to the host', tap(d, 'Keyboard'), ([], []))
r = [(n, hit(d, n), lift(d, n)) for n in (1, 2, 4, 5, 13, 16)]
check('Keyboard mode: pad 1 = C3 (60), ascending left to right and bottom to top: pads 1, 2, 4, 5, 13, 16 = 60, 61, 63, 64, 72, 75',
      [(n, on[0][2], off[0][2]) for n, on, off in r], [(1, 60, 60), (2, 61, 61), (4, 63, 63), (5, 64, 64), (13, 72, 72), (16, 75, 75)])
check('... Note Off follows each Note On', all(on[0][1] == 0x90 and off[0][1] == 0x80 for _, on, off in r))
tap(d, 'Pad Mode')
check('the Pad Mode button puts the drum layout back', (hit(d, 1), hit(d, 16)), ([NON(36, 93)], [NON(51, 93)]))
lift(d, 1); lift(d, 16)

# a pad held while the mode changes is released with the note it started
d = Dev(modes_cfg()); d.start()
hit(d, 1); tap(d, 'Keyboard')
check('a pad held while the mode changes: its Note Off is the note it started (36), the new hit is the new mode\'s (60)', (lift(d, 1), hit(d, 1)), ([NOFF(36)], [NON(60, 93)]))
lift(d, 1)
hit(d, 1); tap(d, 'Right')
check('... same for transposing while a pad is held', (lift(d, 1), hit(d, 1)), ([NOFF(60)], [NON(61, 93)]))
lift(d, 1)
check('pressure on a held pad goes to the note it is sounding (poly aftertouch)', (hit(d, 3), d.translate(report2([(PADIDX[3], 4, 2000)]))), ([NON(63, 93)], [(0x0A, 0xA0, 63, 62)]))
lift(d, 3)

# Fixed Vel / 16 Velocities
d = Dev(modes_cfg()); d.start()
tap(d, 'Fixed Vel')
check('Fixed Vel on: a soft hit and a hard hit both play velocity 127 (fixvel)', (hit(d, 1, 200), hit(d, 2, 4000)), ([NON(36, 127)], [NON(37, 127)]))
lift(d, 1); lift(d, 2)
tap(d, 'Fixed Vel')
check('Fixed Vel off again: the curve is back', hit(d, 1, 3000), [NON(36, 93)]); lift(d, 1)
d = Dev(modes_cfg(fixvel=100)); d.start(); tap(d, 'Fixed Vel')
check('the fixed value is configurable (100)', hit(d, 5, 10), [NON(40, 100)])
d = Dev(modes_cfg()); d.start()
press(d, 'Shift', 'Fixed Vel'); release(d)
r = [hit(d, n, 1000) for n in (1, 2, 8, 16)]
check('Shift + Fixed Vel = 16 Velocities: every pad plays pad 1\'s note (36), pad n at velocity 8 n (8, 16, 64, 127)',
      r, [[NON(36, 8)], [NON(36, 16)], [NON(36, 64)], [NON(36, 127)]])
for n in (1, 2, 8, 16): lift(d, n)
tap(d, 'Keyboard')
check('16 Velocities in Keyboard mode plays the root (60)', hit(d, 3, 100), [NON(60, 24)]); lift(d, 3)
tap(d, 'Fixed Vel')
check('Fixed Vel replaces 16 Velocities (they exclude each other)', hit(d, 3, 100), [NON(62, 127)]); lift(d, 3)

# transpose
d = Dev(modes_cfg()); d.start()
tap(d, 'Right'); tap(d, 'Right')
check('Right twice: +2 semitones (pad 1 = 38)', hit(d, 1), [NON(38, 93)]); lift(d, 1)
press(d, 'Shift', 'Right'); release(d)
check('Shift + Right: one octave up (pad 1 = 50)', hit(d, 1), [NON(50, 93)]); lift(d, 1)
for _ in range(6): press(d, 'Shift', 'Right'); release(d)
check('the transposition itself stops at +63 semitones (pad 16 = 51 + 63)', hit(d, 16), [NON(114, 93)]); lift(d, 16)
tap(d, 'Keyboard')
check('a note beyond 127 is clamped to 127 (Keyboard: 60 + 63 + 15 = 138)', hit(d, 16), [NON(127, 93)]); lift(d, 16)
tap(d, 'Pad Mode')
for _ in range(14): press(d, 'Shift', 'Left'); release(d)
check('... and at the bottom at 0', hit(d, 1), [NON(0, 93)]); lift(d, 1)

# modes start over with a new config, the curve choice does not
d = Dev(modes_cfg()); d.start(); tap(d, 'Keyboard'); tap(d, 'Right'); tap(d, 'Fixed Vel')
d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]
check('a new config (SET) resets the modes: Group, no transpose, no Fixed Vel', hit(d, 1, 3000), [NON(36, 93)])

# ---- the shift layer --------------------------------------------------------------------------------------------------------------
d = Dev(modes_cfg()); d.start()
check('Volume without Shift keeps its CC 44 (gate: 127 on press, 0 on release)', tap(d, 'Volume'), ([CC(44, 127)], [CC(44, 0)]))
check('Shift sends nothing', tap(d, 'Shift'), ([], []))
a = press(d, 'Shift', 'Volume'); b = release(d)
check('Shift + Volume is the curve action instead: no CC 44 on press or release', (a, b), ([], []))
check('... and the curve moved on (linear -> hard 1)', mc.parse_reply(d.ask(mc.get_request())[0])['cfg'][F['vel_curve'][0]], 4)
# release order: the layer of the press decides
press(d, 'Volume'); a = d.translate(report1([B['Volume'], B['Shift']])); b = release(d)
check('Volume pressed first, Shift pressed while it is down: the release is still Volume\'s CC (0), Shift sends nothing', (a, b), ([], [CC(44, 0)]))
a = press(d, 'Shift', 'Volume'); b = d.translate(report1([B['Volume']])); c = release(d)
check('Shift + Volume, Shift released first: nothing on any release (still the shifted action)', (a, b, c), ([], [], []))
check('a button without a shifted action keeps its action while Shift is held (Play still sends Start)', press(d, 'Shift', 'Play'), [(0x0F, 0xFA, 0, 0)])
release(d)
d = Dev(modes_cfg()); d.start()
curves = []
for name in ('Volume', 'Volume', 'Swing', 'Swing', 'Swing'):
    press(d, 'Shift', name); release(d); curves.append(d.cfg()[F['vel_curve'][0]])
check('Shift + Volume steps the curve forward, Shift + Swing back, through all eight and round: 3 -> 4 -> 5 -> 4 -> 3 -> 2', curves, [4, 5, 4, 3, 2])
d = Dev(modes_cfg()); d.start()
seq = []
for _ in range(9): press(d, 'Shift', 'Volume'); release(d); seq.append(d.cfg()[F['vel_curve'][0]])
check('forward from linear it wraps after the eighth (no custom table in this build): 4 5 6 7 0 1 2 3 4', seq, [4, 5, 6, 7, 0, 1, 2, 3, 4])

# the velocity of a hit follows the selected curve
d = Dev(modes_cfg()); d.start()
for _ in range(1): press(d, 'Shift', 'Volume'); release(d)
check('after one step (hard 1) a hit of 3000 gives the hard 1 table entry', hit(d, 1, 3000), [NON(36, bp.vel_table('hard1')[3000 >> 4])]); lift(d, 1)
for _ in range(4): press(d, 'Shift', 'Volume'); release(d)
check('... and with soft 3 (index 0, after wrapping round) its entry', hit(d, 1, 3000), [NON(36, bp.vel_table('soft3')[3000 >> 4])]); lift(d, 1)

# ---- the settings log: the curve choice survives a power cycle without saving the config -------------------------------------------------
def reboot(d): return Dev(flash=d.flash_image())
d = Dev(modes_cfg()); d.start()
d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
n_prog = len(d.flash.log)
press(d, 'Shift', 'Volume'); release(d); d.tick(0)
words = struct.unpack('<2I', d.page()[0x200:0x208])
check('a curve change appends one word to the log (two halfword programs, no erase) at the second half of the save page',
      ([e[0] for e in d.flash.log[n_prog:]], words[0] == 0x5A | (1 << 8) | (4 << 16) | ((0x5A ^ 1 ^ 4 ^ 0xFF) << 24), words[1], d.flash.violations),
      (['prog', 'prog'], True, 0xFFFFFFFF, []))
info = mc.parse_reply(d.ask(mc.info_request())[0])
check('... and it does not make the config "unsaved"', info['unsaved_changes'], False)
d2 = reboot(d)
check('after a power cycle the curve is hard 1 (the saved config says linear, the log wins)', d2.cfg()[F['vel_curve'][0]], 4)
press(d, 'Shift', 'Volume'); release(d); d.tick(0)
d3 = reboot(d)
check('two changes: the last wins after a power cycle', d3.cfg()[F['vel_curve'][0]], 5)
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
page = d.page()
check('a full SAVE bakes the current curve into the record and clears the log', (mc.parse_record(page)[F['vel_curve'][0]], set(page[0x200:])), (5, {0xFF}))
check('... the power-cycled device has it too', reboot(d).cfg()[F['vel_curve'][0]], 5)
d = Dev(modes_cfg()); d.start(); press(d, 'Shift', 'Volume'); release(d); d.tick(0)
check('with nothing saved the log works as well (defaults + curve)', (reboot(d).cfg()[F['vel_curve'][0]], reboot(d).cfg()[F['channel'][0]]), (4, 0))
d.send_sysex(mc.reset_request(erase=True)); [d.tick(0) for _ in range(5)]
check('RESET with erase clears the log: after a power cycle the curve is the default again', reboot(d).cfg()[F['vel_curve'][0]], 3)

# the same curve saved again after the config was re-sent: the log must not override a deliberately saved curve
d = Dev(modes_cfg()); d.start(); d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
press(d, 'Shift', 'Volume'); release(d); d.tick(0)                                   # log: 4
d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]            # the page sends a config with curve 3 and saves
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
check('SAVE after a SET that changes the curve back clears an older log entry (the saved record wins)', reboot(d).cfg()[F['vel_curve'][0]], 3)

# a full log (128 changes) falls back to a full save, no violation, the right curve
d = Dev(modes_cfg()); d.start(); d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
for _ in range(131): press(d, 'Shift', 'Volume'); release(d); d.tick(0)
want = (3 + 131) % 8
check('131 curve changes with a saved config (the log fills up after 128): no flash violation, the curve is right, and survives a power cycle',
      (d.flash.violations, d.cfg()[F['vel_curve'][0]], reboot(d).cfg()[F['vel_curve'][0]]), ([], want, want))
d = Dev(modes_cfg()); d.start()
for _ in range(131): press(d, 'Shift', 'Volume'); release(d); d.tick(0)
check('... and with nothing saved (the log is erased and restarted)', (d.flash.violations, reboot(d).cfg()[F['vel_curve'][0]]), ([], want))

# power cut during the append: the old or the new curve, never anything else
d = Dev(modes_cfg()); d.start(); d.send_sysex(mc.set_request(modes_cfg())); [d.tick(0) for _ in range(5)]
d.send_sysex(mc.save_request()); [d.tick(0) for _ in range(5)]
before = d.flash_image(); n0 = len(d.flash.log)
press(d, 'Shift', 'Volume'); release(d); d.tick(0)
log = d.flash.log[n0:]
seen, bad = set(), []
for cut in range(len(log) + 1):
    for mask in ((None,) if cut == len(log) else (None, 0x00FF, 0xFF00)):
        flash = bytes(image_after(before, log, cut, mask))
        got = Dev(flash=flash).cfg()[F['vel_curve'][0]]
        seen.add(got)
        if got not in (3, 4): bad.append((cut, mask, got))
check('power cut at every point of a log append (and half-programmed halfwords): the curve is the old or the new one', (bad, sorted(seen)), ([], [3, 4]))

# ---- panic ------------------------------------------------------------------------------------------------------------------------
d = Dev(modes_cfg()); d.start(); hit(d, 1); hit(d, 2)
check('Mute without Shift keeps its CC 92', tap(d, 'Mute'), ([CC(92, 127)], [CC(92, 0)]))
d.all_sent.clear(); d.drain()
check('Shift + Mute sends nothing from the report itself', (press(d, 'Shift', 'Mute'), release(d)), ([], []))
for _ in range(4): d.tick(0)
pk = [tuple(b[k:k + 4]) for b in d.all_sent for k in range(0, len(b), 4)]
check('... the tick then sends All Sound Off (120) and All Notes Off (123) on all 16 channels, 32 messages', pk, [(0x0B, 0xB0 | ch, cc, 0) for ch in range(16) for cc in (120, 123)])
check('the held pads were forgotten: letting go sends no Note Off', lift(d, 1), [])
# a nearly full ring: the rest follows when there is room
d = Dev(modes_cfg()); d.start(); press(d, 'Shift', 'Mute'); release(d)
d.mu.mem_write(devsim.RING_R, struct.pack('<H', 0)); d.mu.mem_write(devsim.RING_W, struct.pack('<H', 0x500 - 40))   # 39 bytes free
d.all_sent.clear(); d.tick(0)
first = sum(len(b) for b in d.all_sent) // 4
d.drain(); d.tick(0); d.tick(0)
total = sum(len(b) for b in d.all_sent) // 4
check('with only 39 bytes of room the panic is sent in pieces, nothing lost', (first, total), (9, 32))

# ---- pad pressure options -----------------------------------------------------------------------------------------------------------
for pm, name, want_msgs in ((0, 'poly aftertouch', [(0x0A, 0xA0, 36, 62)]), (1, 'channel pressure', [(0x0D, 0xD0, 62, 0)]), (2, 'control change 11', [CC(11, 62)]), (3, 'off', [])):
    d = Dev(modes_cfg(press_mode=pm)); d.start(); hit(d, 1, 3000)
    got = d.translate(report2([(PADIDX[1], 4, 2000)]))
    rel = lift(d, 1)
    check(f'pressure mode {pm} ({name}): pressure 2000 -> {want_msgs}', got, want_msgs)
    check(f'... release: {"Note Off, then pressure back to 0" if pm in (1, 2) else "Note Off only"}', rel, [NOFF(36)] + ([(0x0D, 0xD0, 0, 0)] if pm == 1 else [CC(11, 0)] if pm == 2 else []))

# ---- LEDs that show the modes -----------------------------------------------------------------------------------------------------
d = Dev(modes_cfg()); d.start(); d.consume()
led = d.led()
check('at the start the Pad Mode button is lit, Keyboard and Fixed Vel rest dim', (led[B['Pad Mode']], led[B['Keyboard']], led[B['Fixed Vel']]), (0x7F, 0x7C, 0x7C))
tap(d, 'Keyboard'); led = d.led()
check('Keyboard mode: Keyboard lit, Pad Mode dim', (led[B['Pad Mode']], led[B['Keyboard']]), (0x7C, 0x7F))
tap(d, 'Fixed Vel'); led = d.led()
check('Fixed Vel on: its button lit', led[B['Fixed Vel']], 0x7F)
press(d, 'Shift', 'Fixed Vel'); release(d); led = d.led()
check('Shift + Fixed Vel switches to 16 Velocities (Fixed Vel off, the button stays lit for the other mode)', led[B['Fixed Vel']], 0x7F)
tap(d, 'Fixed Vel'); tap(d, 'Fixed Vel'); led = d.led()
check('Fixed Vel on and off again: the button is dim', led[B['Fixed Vel']], 0x7C)
d2 = Dev(modes_cfg(led_flags=0)); d2.start(); d2.consume(); tap(d2, 'Keyboard'); led = d2.led()
check('with local lighting off the mode buttons still show their state (lit / dark)', (led[B['Pad Mode']], led[B['Keyboard']]), (0, 0x7F))

# ---- the display ------------------------------------------------------------------------------------------------------------------
from dispsim import reference, idle, Screen, glyph

d = Dev(modes_cfg()); d.start(); sc = Screen(d)
check('before the first tick the screen still has what the stock firmware drew', sc.fb() == sc.original)
sc.run(8)
check('at start-up the idle screen is drawn (two regions): EX-MACHINA, V0 and the status line "DRUMS CH1 120", pixel for pixel the reference',
      (sc.fb() == idle('DRUMS CH1 120'), sc.regions), (True, 2))
sc.run(100, 10)
check('... and nothing more is written while nothing changes', sc.regions, 2)
tap(d, 'Keyboard'); sc.run(4)
check('Keyboard button: the screen shows KEYBOARD / C3-D#4 (two more regions: pages 0-1 and 2-3), pixel for pixel the reference', (sc.fb() == reference('KEYBOARD', 'C3-D#4'), sc.regions), (True, 4))
sc.run(100, 10)                                                    # 1.0 s later: still there
check('... still up after 1 s', sc.fb() == reference('KEYBOARD', 'C3-D#4'))
sc.run(60, 10)
check('... after about 1.5 s the idle screen is back with the new status "KEYS CH1 120" (two more regions)', (sc.fb() == idle('KEYS CH1 120'), sc.regions), (True, 6))
tap(d, 'Pad Mode'); sc.run(4)
check('Pad Mode: PAD MODE / GROUP  C1-D#2', sc.fb() == reference('PAD MODE', 'GROUP  C1-D#2'))
sc.settle()
check('... and the idle screen again', sc.fb() == idle('DRUMS CH1 120'))

# a second message while the first is up: the last one shows, and the idle screen returns once
tap(d, 'Keyboard'); sc.run(30, 10); tap(d, 'Pad Mode'); sc.run(4)
check('a second message replaces the first at once', sc.fb() == reference('PAD MODE', 'GROUP  C1-D#2'))
sc.settle()
check('... and the idle screen returns (not the first message)', sc.fb() == idle('DRUMS CH1 120'))
# a message while the idle screen is being drawn again
tap(d, 'Keyboard'); sc.run(160, 10)
tap(d, 'Pad Mode'); sc.run(1)                                      # just after the redraw began
sc.settle()
check('a message started during the redraw still ends with the idle screen', sc.fb() == idle('DRUMS CH1 120'))
# the status line follows the tempo and what runs
d = Dev(modes_cfg(tempo=160 - 20)); d.start(); sc = Screen(d); sc.run(8)
check('the start tempo of the config is in the status line (160)', sc.fb() == idle('DRUMS CH1 160'))
d = Dev(modes_cfg(channel=11)); d.start(); sc = Screen(d); sc.run(8)
check('... and the MIDI channel (12)', sc.fb() == idle('DRUMS CH12 120'))

# every message
d = Dev(modes_cfg()); d.start(); sc = Screen(d)
def show(name_or_names, title, detail, bar=None, shift=False):
    names = (name_or_names,) if isinstance(name_or_names, str) else tuple(name_or_names)
    sc.run(250, 10); press(d, *(('Shift',) if shift else ()), *names); release(d); sc.run(4)
    check(f'message: {title} / {detail}' + (f' / bar {bar}' if bar is not None else ''), sc.fb() == reference(title, detail, bar))
show('Fixed Vel', 'FIXED VEL', 'ON  127', 118 * 127 // 127)
show('Fixed Vel', 'FIXED VEL', 'OFF')
show('Fixed Vel', '16 VELS', 'ON  8-127', shift=True)
show('Fixed Vel', '16 VELS', 'OFF', shift=True)
show('Volume', 'VELOCITY', 'HARD 1', shift=True)
show('Swing', 'VELOCITY', 'LINEAR', shift=True)
show('Right', 'TRANSPOSE', 'BASE C#1  +1')
show('Right', 'TRANSPOSE', 'BASE D1  +2')
show('Right', 'TRANSPOSE', 'BASE D2  +14', shift=True)
show('Keyboard', 'KEYBOARD', 'D4-F5')                            # root 60 + 14 = 74 = D4 ... 89 = F5
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
