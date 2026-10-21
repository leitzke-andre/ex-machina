"""The two modes in the emulator: Standalone (the mappings, slots and functions) and FL Studio (the built-in mapping for the FL Studio device script).
Shift + Project switches in every mapping (also where Shift is a plain CC), the switch is announced (62 00 <mode>), the standalone mapping comes back
exactly as it was (unsaved edits, slot, name), Project is a plain CC 38 in FL Studio mode, the mode is remembered across power cycles (also through a
SAVE and a full settings log), the MODE request, a mapping from a host ends FL Studio mode, notes and host mode end with it, and the screens.
Usage: test_mode.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
import devsim
from devsim import report1, report2
from dispsim import MS16, Screen, reference, idle

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

F = mc.FIELDS
B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}
PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}
P = {p['id']: p for p in mc.builtin_presets()}
PRESET = P['maschine-modes']['cfg']
NON = lambda n, v=93, ch=0: (0x09, 0x90 | ch, n, v)
NOFF = lambda n, ch=0: (0x08, 0x80 | ch, n, 0)
CC = lambda n, v, ch=0: (0x0B, 0xB0 | ch, n, v)
MODE_FL, MODE_SA = bytes.fromhex('f07d4d4b620001f7'), bytes.fromhex('f07d4d4b620000f7')

def cfg(base=PRESET, **kw):
    c = bytearray(base)
    for k, v in kw.items(): c[F[k][0]] = v
    return bytes(c)

class T:
    def __init__(self, c=None, flash=None):
        self.d = devsim.Dev(fw, data, None if flash is not None else (c if c is not None else PRESET), flash)
        self.d.translate(report1()); self.d.start(); self.t = 5000; self.write()
    def write(self): self.d.mu.mem_write(MS16, struct.pack('<H', self.t & 0xFFFF))
    def run(self, ms, step=1):
        out = []
        for _ in range(0, ms, step):
            self.t += step; self.write(); self.d.all_sent.clear(); self.d.tick(0)
            out += [bytes(b) for b in self.d.all_sent]; self.d.drain()
        return devsim.sysex_messages(out), [tuple(b[k:k + 4]) for b in out for k in range(0, len(b), 4)]
    def press(self, *names): return self.d.translate(report1([B[n] for n in names]))
    def release(self): return self.d.translate(report1())
    def shift_project(self):                          # Shift down, Project down, both up (as a player would)
        a = self.press('Shift'); a += self.press('Shift', 'Project'); a += self.press('Shift'); a += self.release()
        m, self.pk = self.run(10)
        return a, m
    def hit(self, pad): return self.d.translate(report2([(PADIDX[pad], 1, 3000)]))
    def lift(self, pad): return self.d.translate(report2([(PADIDX[pad], 3, 0)]))
    def ask(self, msg): return [mc.parse_reply(m) for m in self.d.ask(msg)]
    def info(self): return mc.parse_reply(self.d.ask(mc.info_request())[0])
    def cfg(self): return self.d.cfg()
    def reboot(self): return T(None, self.d.flash_image())

FLCFG = mc.fl_cfg()
check('the image carries the FL Studio mapping at CFG_FL_ADDR, as mmk3_config.fl_cfg() builds it (Project = CC 38)',
      (fw[bp.CFG_FL_ADDR - 0x08003000:][:mc.CFG_SIZE] == FLCFG, FLCFG[F['btn_act'][0]], FLCFG[F['btn_cc'][0]]), (True, mc.ACT_CC, 38))

# ---- the switch -----------------------------------------------------------------------------------------------------------------------------------
x = T(); x.ask(mc.slot_store_request(1, 'Two'))
check('a fresh device is in Standalone mode (INFO, MODE query)', (x.info()['mode'], x.ask(mc.mode_request())[0]['mode']), ('standalone', 'standalone'))
x.ask(mc.set_request(cfg(channel=3, keys_root=48)))                     # an unsaved edit
sent, msgs = x.shift_project()
check('Shift + Project: nothing goes out as MIDI for the gesture; the device announces FL Studio mode (62 00 01)', (sent, msgs), ([], [MODE_FL]))
got = x.cfg()
check('... the active mapping is the built-in FL one (Project = CC 38), INFO says fl', (got == FLCFG, x.info()['mode']), (True, 'fl'), [k for k in range(mc.CFG_SIZE) if got[k] != FLCFG[k]][:8])
check('in FL Studio mode Project alone is a plain CC 38 (gate), no slot is loaded', (x.press('Project'), x.release(), x.cfg() == FLCFG), ([CC(38, 127)], [CC(38, 0)], True))
x.shift_project()
check('Shift + Project again: Standalone, with the unsaved edit back exactly (channel 4, root 48) and still unsaved', (x.cfg() == cfg(channel=3, keys_root=48), x.info()['unsaved_changes']), (True, True))
x = T(); x.ask(mc.slot_store_request(1, 'Two')); x.ask(mc.slot_load_request(1)); x.shift_project(); x.shift_project()
x.press('Project'); x.release(); x.run(30)
check('a slot loaded before FL Studio mode is still the current one after it: Project goes on to the next slot (slot 2 -> 2, the only one)', x.ask(mc.slots_request())[0]['names'][1], 'TWO')

# ---- Shift for the FL Studio script ----------------------------------------------------------------------------------------------------------------
x = T(); x.shift_project()
check('FL Studio mode: Shift down / up is reported as CC 111 (the script shows its help and reads Shift + pads)', (x.press('Shift'), x.release()), ([CC(111, 127)], [CC(111, 0)]))
check('... Shift + Rec / Restart / Solo send their Shift CCs (113 count-in, 114 loop record, 115 clear mutes and solos)',
      (x.press('Shift'), [(x.press('Shift', b), x.press('Shift'))[0] for b in ('Rec', 'Restart', 'Solo')])[1], [[CC(113, 127)], [CC(114, 127)], [CC(115, 127)]])
x.release()
x = T(); check('Standalone mode: Shift stays the device\'s own (no CC 111)', (x.press('Shift'), x.release()), ([], []))

# ---- in every mapping, also where Shift is a plain CC ---------------------------------------------------------------------------------------------------
x = T(P['groove-rider-2']['cfg'])
sent, msgs = x.shift_project()
check('Groove Rider 2 (Shift = CC 43): Shift + Project still switches; Shift sends its CC, Project nothing', (sent, msgs), ([CC(43, 127), CC(43, 0)], [MODE_FL]))
x.shift_project(); check('... and back, to Groove Rider 2', x.cfg() == P['groove-rider-2']['cfg'], True)

# ---- notes, host mode and the screen --------------------------------------------------------------------------------------------------------------------
x = T(); x.hit(1); sent, msgs = x.shift_project()
check('a pad held while switching: its note is released with the switch, and letting go later sends nothing', (NOFF(36) in x.pk, x.lift(1)), (True, []))
sc = Screen(x.d); sc.settle()
check('FL Studio mode with no script: the idle screen says FL STUDIO / WAITING FOR FL', sc.fb() == idle('DRUMS CH1 120', 'WAITING FOR FL', 'FL STUDIO'), True)
x.ask(mc.host_request(mc.HOST_SCREEN | mc.HOST_RAW)); x.d.send_sysex(mc.text_request(0, 'FL LINE'))
x.shift_project(); sc.settle()
check('leaving FL Studio mode ends host mode: the Standalone idle screen is back (EX-MACHINA / V0)', sc.fb() == idle('DRUMS CH1 120'), True)
check('... and the pads are no longer a raw grid (Keyboard mode plays its scale again)', (x.press('Keyboard'), x.release(), x.hit(2))[2], [NON(61)])

# ---- the MODE request, and a mapping from a host ---------------------------------------------------------------------------------------------------------
x = T()
check('MODE fl: status 0, mode fl, and the mapping is the FL one', (x.ask(mc.mode_request('fl'))[0]['mode'], x.cfg() == FLCFG), ('fl', True))
check('MODE with a wrong value (2): status 1, nothing changes', (x.ask(mc.message(mc.CMD_MODE, bytes([2])))[0]['status'], x.info()['mode']), (1, 'fl'))
r = x.d.ask(mc.set_request(cfg(channel=5)))
check('a SET while in FL Studio mode: applied as the Standalone mapping, and the device says so (52 00, then 62 00 00)', (r, x.info()['mode'], x.cfg()[F['channel'][0]]),
      ([bytes.fromhex('f07d4d4b5200f7'), MODE_SA], 'standalone', 5))
x.ask(mc.mode_request('fl')); x.ask(mc.mode_request('standalone'))
check('MODE standalone: back, with the mapping the SET made', x.cfg() == cfg(channel=5), True)

# ---- remembered across power cycles, also through SAVE and a full log ------------------------------------------------------------------------------------------
x = T(); x.ask(mc.set_request(cfg(channel=2))); x.ask(mc.save_request()); x.shift_project()
y = x.reboot()
check('in FL Studio mode at power-off: FL Studio mode at power-up, with the FL mapping', (y.info()['mode'], y.cfg() == FLCFG), ('fl', True))
y.ask(mc.save_request())
z = y.reboot()
check('SAVE in FL Studio mode keeps the Standalone mapping (channel 3) and FL Studio mode stays remembered (the erase took the log)', (z.info()['mode'], z.info()['saved']), ('fl', True))
z.shift_project()
check('... back in Standalone: the saved mapping (channel 3)', z.cfg()[F['channel'][0]], 2)
w = z.reboot()
check('Standalone at power-off: Standalone at power-up', w.info()['mode'], 'standalone')
v = T(); v.shift_project()
for k in range(130): v.press('Shift', 'Volume'); v.release(); v.run(2)                   # FL mapping: Shift + Volume = curve; 130 log words overflow it
check('130 curve steps in FL Studio mode (the log overflows and is rewritten): still FL Studio mode after a power cycle', v.reboot().info()['mode'], 'fl')
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
