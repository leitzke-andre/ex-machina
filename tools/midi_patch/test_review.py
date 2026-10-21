"""Regression tests for the defects found by the adversarial review of 2026-10-20, each written to fail on the firmware before the fix:
notes released when another config takes over (held pads, a held note button, the sequencer), a bent pitch back to the centre, the external
clock's 16-bit timeout, an arp phrase restarting the sequencer's grid, slots that would not load, a full settings log, NOTE / MMC buttons without
a number, RESET's unsaved flag, the tap tempo's 16-bit pause, mute / solo and the arp, pressure for a pad held through the arp, clock out next
to an external clock, and a refused SLOT STORE changing the name. (The ring, USB and HANG fixes are in test_features / test_hal_usb / test_safety,
the note counting in test_phase2, the standalone image's stack in test_native.)
Usage: test_review.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2
from dispsim import MS16

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

def cfg(base=PRESET, **kw):
    c = bytearray(base)
    for k, v in kw.items():
        off, n = F[k]
        if isinstance(v, (list, tuple, bytes)): c[off:off + len(v)] = bytes(v)
        else: c[off] = v
    return bytes(c)
def button(c, name, act, par, shifted=False):
    c = bytearray(c); k = B[name]
    c[F['btn_act2' if shifted else 'btn_act'][0] + k] = act; c[F['btn_cc2' if shifted else 'btn_cc'][0] + k] = par
    return bytes(c)

class T:
    """A device with a clock (as in test_phase3): the test advances the stock millisecond counter, the main loop's tick runs after every step."""
    def __init__(self, c=None, flash=None):
        self.d = devsim.Dev(fw, data, None if flash is not None else (c if c is not None else PRESET), flash)
        self.d.translate(report1()); self.d.start(); self.t = 5000; self.write()
    def write(self): self.d.mu.mem_write(MS16, struct.pack('<H', self.t & 0xFFFF))
    def run(self, ms, step=1):
        out, t0 = [], self.t
        for _ in range(0, ms, step):
            self.t += step; self.write(); self.d.all_sent.clear(); self.d.tick(0)
            for b in self.d.all_sent:
                for k in range(0, len(b), 4): out.append((self.t - t0, tuple(b[k:k + 4])))
            self.d.drain()
        return out
    def press(self, *names, pos=0): return self.d.translate(report1([B[n] for n in names], pos=pos))
    def release(self, pos=0): return self.d.translate(report1(pos=pos))
    def tap(self, *names, pos=0): a = self.press(*names, pos=pos); return a + self.release(pos=pos)
    def shift_tap(self, name): return self.tap('Shift', name)
    def hit(self, pad, val=3000): return self.d.translate(report2([(PADIDX[pad], 1, val)]))
    def lift(self, pad): return self.d.translate(report2([(PADIDX[pad], 3, 0)]))
    def ask(self, msg, ticks=10):
        self.d.all_sent.clear(); r = self.d.ask(msg, ticks)
        return r, [tuple(b[k:k + 4]) for b in self.d.all_sent for k in range(0, len(b), 4)]
    def reboot(self): return T(None, self.d.flash_image())
    def cfg(self): return self.d.cfg()

# ---- another config takes over while notes sound: they are released with the old one -------------------------------------------------------------
x = T(); x.hit(1)
r, sent = x.ask(mc.set_request(cfg(channel=1)))
check('a pad held (channel 1, note 36) when a config on channel 2 arrives: its Note Off goes out on channel 1 at once', NOFF(36) in sent, True, sent)
check('... and letting go of the pad later sends nothing more (nothing is left hanging on either channel)', x.lift(1), [])
x = T(button(PRESET, 'Duplicate', mc.ACT_NOTE, 70))
check('a note button (Duplicate = note 70) held ...', x.press('Duplicate'), [NON(70, 127)])
r, sent = x.ask(mc.set_request(cfg()))
check('... when another config arrives: its Note Off goes out with the old config', NOFF(70) in sent, True, sent)
x = T(); x.tap('Step'); x.hit(1); x.tap('Step')                         # step mode: pad 1 = step 1 of track 1 (note 36) on; back to playing
x.shift_tap('Step'); ev = x.run(30)                                     # the sequencer starts: step 1 sounds at once
check('the sequencer sounds note 36 on step 1', [p for t, p in ev if p[0] == 9][:1], [NON(36, 100)])
newnotes = list(range(60, 76))
r, sent = x.ask(mc.set_request(cfg(pad_note=[newnotes[mc.PAD_LABEL[i] - 1] for i in range(16)])))
ev = x.run(300)
check('a config with other pad notes arrives while it sounds: note 36 is released (not the new note 60 of that track)', (NOFF(36) in sent, NOFF(60) in sent + [p for t, p in ev]), (True, False), sent)

# ---- pitch bend back to the centre ------------------------------------------------------------------------------------------------------------------
x = T(); x.tap('Pitch')
check('Pitch mode, finger at the right end: full bend up', x.press(pos=200) if False else x.d.translate(report1(pos=200)), [(0x0E, 0xE0, 127, 127)])
x.d.translate(report1([B['Mod']], pos=200)); x.d.translate(report1(pos=200)); ev = x.run(5)
check('switching to Mod while bent: the bend goes back to the centre (E0 00 40), without waiting for the finger', [p for t, p in ev if p[1] == 0xE0], [(0x0E, 0xE0, 0, 64)])
check('... and lifting the finger in Mod mode sends no second centre', [p for p in x.d.translate(report1(pos=0)) if p[1] == 0xE0], [])
x = T(); x.tap('Pitch'); x.d.translate(report1(pos=1)); x.tap('Group', pos=1); ev = x.run(5)
check('bent down and the MIDI channel changes: the old channel (1) is centred', [p for t, p in ev if p[1] & 0xF0 == 0xE0], [(0x0E, 0xE0, 0, 64)])

# ---- the external clock's timeout across the 16-bit wrap of the millisecond counter -------------------------------------------------------------------------
x = T(); x.shift_tap('Tap'); x.run(50)
x.d.rx(bytes(CLK)); x.run(1000)                                          # one external pulse, long gone
x.t += 65536 - 1000 - 100; x.write(); x.run(1)                           # 65.5 s after that pulse: the 16-bit difference is small again
ev = x.run(600)
check('one MIDI clock from the host 65.5 s ago: the internal clock output keeps running through the wrap (about 29 pulses in 600 ms)', len([p for t, p in ev if p == CLK]) >= 27, True, len([p for t, p in ev if p == CLK]))

# ---- an arp phrase does not restart the running sequencer's grid ----------------------------------------------------------------------------------------
x = T(); x.tap('Step')
for n in range(1, 17): x.hit(n)                                          # track 1 (note 36) on every step
x.tap('Step'); x.shift_tap('Step'); ev0 = x.run(200)
x.tap('Note Repeat'); x.hit(5); ev1 = x.run(800)                        # arp on, a pad 70 ms into a step
seq = [t for t, p in ev0 if p == NON(36, 100)] + [200 + t for t, p in ev1 if p == NON(36, 100)]
gaps = sorted(set(b - a for a, b in zip(seq, seq[1:])))
check('the arp starting (a pad hit mid-step) leaves the sequencer on its 1/16 grid: every step 125 ms (+-1) apart', all(124 <= g <= 126 for g in gaps), True, (seq, gaps))

# ---- slots that this firmware would refuse are skipped and not listed ------------------------------------------------------------------------------------
x = T()
bad = bytearray(cfg(channel=3)); bad[F['chord_type'][0]] = 9                                # intact (CRC right) but out of range
for n, c in ((0, cfg(channel=2)), (1, bytes(bad)), (2, cfg(channel=4))):
    x.d.mu.mem_write(bp.SLOT_BASE + 0x400 * n, mc.build_record(c))
check('SLOTS lists a slot that would not load as empty', x.d.ask(mc.slots_request())[0] and mc.parse_reply(x.d.ask(mc.slots_request())[0])['used'], [True, False, True, False])
seen = []
for _ in range(4): x.tap('Project'); x.run(20); seen.append(x.cfg()[F['channel'][0]] + 1)
check('Project skips it like an empty slot: slots 1, 3, 1, 3 (channels 3, 5, 3, 5)', seen, [3, 5, 3, 5])

# ---- a full settings log bakes into the SAVED config, not into whatever is active --------------------------------------------------------------------
x = T(); x.ask(mc.set_request(cfg(channel=2))); x.ask(mc.save_request())     # saved: channel 3 (a config equal to the defaults would not be saved)
x.ask(mc.set_request(cfg(channel=5, keys_root=48)))                     # active, never saved
for k in range(130):                                                    # the log holds 128 words: this overflows it
    x.press('Shift', 'Volume'); x.release(); x.run(2)
chosen = x.cfg()[F['vel_curve'][0]]; after = x.reboot().cfg()
check('130 curve steps with an unsaved config active: after a power cycle the saved config is back (channel 3, root 60), with the last curve chosen',
      (after[F['channel'][0]], after[F['keys_root'][0]], after[F['vel_curve'][0]]), (2, 60, chosen))

# ---- NOTE and MMC buttons need their number ---------------------------------------------------------------------------------------------------------------
c = button(PRESET, 'Duplicate', mc.ACT_NOTE, 0xFF)
x = T(); r = mc.parse_reply(x.d.ask(mc.set_request(c))[0])
check('SET with a note button without a number (0xFF, it would go out as a status byte): refused at that byte, as the host library says',
      (r['status'], r.get('offset'), mc.check(c)), (2, F['btn_cc'][0] + B['Duplicate'], F['btn_cc'][0] + B['Duplicate']))
c = button(PRESET, 'Duplicate', mc.ACT_MMC, 0xFF, shifted=True)
check('... the same for an MMC button on the Shift layer', mc.parse_reply(x.d.ask(mc.set_request(c))[0]).get('offset'), F['btn_cc2'][0] + B['Duplicate'])

# ---- RESET with a settings log: the next boot is not the defaults, so there are unsaved changes ------------------------------------------------------------
x = T(); x.tap('Group'); x.run(5)                                        # channel 2, kept in the log
x.ask(mc.reset_request())
check('RESET (nothing saved, the channel in the log): INFO says unsaved changes', mc.parse_reply(x.d.ask(mc.info_request())[0])['unsaved_changes'], True)

# ---- tap tempo: a long pause ends the run even across the 16-bit wrap ------------------------------------------------------------------------------------------
def bpm_after(pause):
    x = T()
    for k in range(3): x.tap('Tap'); x.run(1000)                         # 60 BPM
    x.run(3000); x.t += pause; x.write(); x.tap('Tap'); x.run(1)        # a pause, then one tap 300 ms "after" the last one modulo 65.5 s
    x.shift_tap('Tap'); ev = x.run(1000)
    return len([p for t, p in ev if p == CLK])
check('taps at 60 BPM, a pause of 65.5 s, one more tap: a new run (still 60 BPM: 24 pulses a second), not a 300 ms interval', bpm_after(65536 - 3000 - 1000 + 300), 24)

# ---- mute / solo and the arp ------------------------------------------------------------------------------------------------------------------------------------
x = T(); x.tap('Note Repeat'); x.tap('Lock'); x.hit(1); x.hit(2); x.run(50); x.lift(1); x.lift(2)     # arp, latched: notes 36 and 37
x.tap('Mute'); x.hit(2); x.lift(2); x.tap('Mute')                        # pad 2 muted
ev = x.run(1000)
check('a pad muted while the arp (latched) plays it: its note leaves the arp at once', sorted(set(p[2] for t, p in ev if p[0] == 9)), [36])
x = T(); x.tap('Note Repeat'); x.hit(1); x.run(30)
check('pressure on a pad held through the arp sends no aftertouch (the pad sounds nothing of its own)', x.d.translate(report2([(PADIDX[1], 4, 2000)])), [])

# ---- clock out next to an external clock ------------------------------------------------------------------------------------------------------------------------
x = T(); x.d.rx(bytes(CLK)); x.run(5); x.d.rx(bytes(CLK))
check('Shift + Tap while an external clock runs: no MIDI Start (nothing would follow it)', START in x.press('Shift', 'Tap'), False)

# ---- a refused SLOT STORE does not change the name a button store uses -------------------------------------------------------------------------------------------
c = button(PRESET, 'Scene', mc.ACT_SLOT, 4, shifted=True)                   # Shift + Scene = store in slot 1
x = T(c); x.ask(mc.slot_store_request(1, 'KEEP'))
r = mc.parse_reply(x.d.ask(mc.message(mc.CMD_SLOT_STORE, bytes([9]) + b'BAD'))[0])
x.shift_tap('Scene'); x.run(20)
check('SLOT STORE to slot 10 with a name: refused (2), and a button store afterwards keeps the name of the last real store (KEEP)',
      (r['status'], mc.parse_reply(x.d.ask(mc.slots_request())[0])['names'][0]), (2, 'KEEP'))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
