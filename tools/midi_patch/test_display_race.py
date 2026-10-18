"""The firmware writes the display from the main loop, the USB interrupt writes the same staging buffer when a host sends a display region
(SysEx 01). The firmware guards its own write with interrupts off; this test checks that it works: a host region is injected into the
real USB handler at every point of the tick that writes a half of a message or of the restore (an interrupt is only taken where the
emulated PRIMASK allows it, exactly like the hardware: pending until the section ends), and whatever the stock main loop is handed
must be one of the known regions, never a mixture.

Usage: test_display_race.py <patched.bin> <data_init.bin>"""
import os, struct, sys
from unicorn import *
from unicorn.arm_const import *

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import mmk3_config as mc
import devsim
from devsim import report1, STRUCT
from dispsim import reference, idle, Screen

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

CFG = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'maschine-modes')
KEYBOARD = mc.BUTTON_NAMES.index('Keyboard')
HOST = bytes((0xA5 ^ (i * 7)) & 0xFF for i in range(256))                      # a recognisable region: pages 0-1, the whole width
HOST_MSG = mc.message(1, bytes([0, 0, 127, 1]) + mc.pack7(HOST))
MSG = reference('KEYBOARD', 'C3-D#4')
IDLE0, IDLE1 = idle('DRUMS CH1 120'), idle('KEYS CH1 120')     # the idle screen before and after Keyboard mode was switched on

def interrupted_tick(d, after, isr):
    """Runs the tick for `after` instructions, then the interrupt `isr(sp)` at the first point where PRIMASK allows it, then the rest of the tick."""
    mu = d.mu
    mu.mem_write(STRUCT + 2, struct.pack('<H', 0))
    mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    def run(pc, count):
        try: mu.emu_start(pc | 1, 0x08000000, count=count)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    run(d.T_TICK, after)
    pc = mu.reg_read(UC_ARM_REG_PC)
    if pc == 0x08000000: return False, False
    masked = False
    while mu.reg_read(UC_ARM_REG_PRIMASK) & 1:                                   # the interrupt stays pending until the section ends
        masked = True; run(pc, 1); pc = mu.reg_read(UC_ARM_REG_PC)
        if pc == 0x08000000: return False, masked
    ctx = mu.context_save(); sp = mu.reg_read(UC_ARM_REG_SP)
    isr((sp - 0x100) & ~7)
    mu.context_restore(ctx)
    run(pc, 600000)
    return True, masked

def scenario(phase, after):
    d = devsim.Dev(fw, data, CFG); d.translate(report1()); d.start(); sc = Screen(d)
    sc.run(8)                                                                    # the idle screen is drawn (two regions)
    d.translate(report1([KEYBOARD])); d.translate(report1())                     # a message starts: the next tick writes its first half
    want = {'msg0': 2, 'msg1': 3, 'view0': 3, 'view1': 4}[phase]
    while sc.regions < want: sc.run(1, 3 if sc.regions < 3 else 1600)            # past the message time the ticks move on to the idle screen
    if phase == 'view0': sc.run(1, 1600)                                         # the tick that only notices the time is up; the next one writes
    sc.advance(3)
    taken, masked = interrupted_tick(d, after, lambda sp: d.send_sysex(HOST_MSG, sp=sp))
    sc.apply()
    for _ in range(30): sc.run(1, 150)                                           # more ticks, the time passes, the message is removed
    return sc, taken, masked

candidates = {(0, 2, HOST), (0, 2, MSG[:256]), (2, 2, MSG[256:]), (0, 2, IDLE0[:256]), (2, 2, IDLE0[256:]), (0, 2, IDLE1[:256]), (2, 2, IDLE1[256:])}
for phase in ('msg0', 'msg1', 'view0', 'view1'):
    bad, taken_n, masked_n, host_seen, final_bad = [], 0, 0, 0, []
    for after in range(1, 9000, 83):
        sc, taken, masked = scenario(phase, after)
        taken_n += taken; masked_n += masked
        host_seen += any(r == (0, 2, HOST) for r in sc.seen)
        for r in sc.seen:
            if r not in candidates: bad.append((after, r[0], r[1]))
        late_host = sc.seen and sc.seen[-1] == (0, 2, HOST) or (len(sc.seen) > 1 and sc.seen[-2] == (0, 2, HOST) and sc.seen[-1][0] == 2)   # the host drew after our last write to the top half: its picture stays
        if sc.fb() != IDLE1 and not (late_host and sc.fb() == HOST + IDLE1[256:]): final_bad.append(after)
        if not taken and after > 3000: break
    check(f'{phase}: a host display region injected at {taken_n} different points of the tick ({masked_n} of them inside the masked section, taken after it): '
          f'every region the stock loop was handed is a whole known region ({host_seen} runs applied the host\'s)', bad, [])
    check(f'{phase}: ... and the idle screen is there in every run (unless the host drew after our write of that half: then its picture stays)', final_bad, [])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
