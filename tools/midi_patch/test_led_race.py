"""Deterministic reproduction of the lost-LED-update race found on the real device (2026-10-17).

On hardware, a burst of 17 LED messages (16 pad colours + 1 strip LED) arrives as several USB packets while the stock main loop
applies the pending LED frame: the loop clears the "frame pending" flag, THEN reads the 80 entries one by one. A packet that
arrives in the middle of that read used to start a fresh all-0xFF frame, wiping entries the loop had not reached yet, so a
different handful of LEDs stayed dark each time.

This test runs the REAL stock service routine in the emulator, interrupts it after a random number of instructions, injects a
USB OUT packet (the real USB interrupt handler on its own stack), resumes, and finally compares the applied LED matrix with
a race-free reference run. Many random interleavings are tried with a fixed seed.

Usage: test_led_race.py <patched.bin> <data_init.bin> [scenarios=150]
"""
import os, random, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'emu'))
from unicorn import *
from unicorn.arm_const import *
from usb_model import *

FL = 0x08003000
fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SCENARIOS = int(sys.argv[3]) if len(sys.argv) > 3 else 150
ST = 0x20001028
MATRIX, MATRIX_LEN = 0x20000F06, 0x120               # the applied LED state (see tools/emu/emu_led.py)
SERVICE, MAIN_SP = 0x08004621, 0x20004000

def bl_target(addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off

class Machine:
    """A booted, configured device whose stock main loop (service passes) can be stopped at an address or after an exact number of
    instructions, so that a USB packet can arrive in the middle of a pass."""
    LED_ENTRY, LED_END = 0x08003e88, 0x08003f30          # the stock LED apply section (flag check ... end of the 80-entry loop)

    def __init__(self):
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
        mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
        mu.mem_map(0xE0000000, 0x100000)
        usb = self.usb = UsbModel(mu)
        skip = mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1), begin=0x08007EA2, end=0x08007EA3)
        usb.run(bl_target(0x08008CF8) | 1); mu.hook_del(skip)
        usb.run(USB_INIT); usb.reset()
        usb.control(setup_packet(0x00, 5, 7, 0, 0)); usb.control(setup_packet(0x00, 9, 1, 0, 0))
        self.pc = None                                   # None: no service pass in progress

    def start_pass(self):
        mu = self.mu
        mu.mem_write(ST + 0x88, struct.pack('<H', 1)); mu.mem_write(ST + 0xc2, bytes([5]))   # keep button scan and strip I2C out of the way
        mu.reg_write(UC_ARM_REG_SP, MAIN_SP); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        self.pc = SERVICE

    def go(self, until=0x08000000, count=0):
        """Continue the pass in progress (starting one if needed) until `until` is reached or `count` instructions have run."""
        if self.pc is None: self.start_pass()
        mu = self.mu
        try: mu.emu_start(self.pc, until, count=count or 3_000_000)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        pc = mu.reg_read(UC_ARM_REG_PC)
        self.pc = None if pc == 0x08000000 else pc | 1

    def finish_pass(self):
        if self.pc is not None: self.go()
        assert self.pc is None, 'a service pass did not finish'

    def passes(self, k):
        self.finish_pass()
        for _ in range(k): self.go(); self.finish_pass()

    def into_led_section(self):
        """Advance to the entry of the stock LED apply section (in this pass, or in the next one)."""
        for _ in range(3):
            self.go(until=self.LED_ENTRY)
            if self.pc is not None and (self.pc & ~1) == self.LED_ENTRY: return True
            self.finish_pass()
        return False

    def inject(self, packet):
        """A USB OUT packet arrives now: the real ISR runs on the stack below the interrupted code."""
        mu, usb = self.mu, self.usb
        ctx = mu.context_save()
        usb.sp = (mu.reg_read(UC_ARM_REG_SP) - 0x100) & ~7 if self.pc is not None else MAIN_SP
        usb.bulk_out(1, packet)
        usb.sp = 0x20004000
        mu.context_restore(ctx)

    def matrix(self): return bytes(self.mu.mem_read(MATRIX, MATRIX_LEN))

def packet(events): return b''.join(bytes([0x09, 0x91, led, code]) for led, code in events)
CMDS = [(39 + p, ((p + 1) << 2) | 2) for p in range(16)] + [(55, (17 << 2) | 2)]

# --- the race-free reference: every packet is followed by complete service passes
ref = Machine()
for led, code in CMDS:
    ref.inject(packet([(led, code)])); ref.passes(2)
REF = ref.matrix()
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)), flush=True)

lit = sum(1 for i in range(MATRIX_LEN) if REF[i])
check('reference run: all 17 commanded LEDs reach the applied LED matrix', lit > 17, lit)

# --- random interleavings: packets of random size arrive in the middle of the stock LED section, between passes, or elsewhere
rng = random.Random(20261017)
failures, inside = [], 0
for n in range(SCENARIOS):
    cuts = sorted(rng.sample(range(1, len(CMDS)), rng.randint(1, 8)))
    groups = [CMDS[i:j] for i, j in zip([0] + cuts, cuts + [len(CMDS)])]
    m = Machine()
    for g in groups:
        r = rng.random()
        if r < 0.7:
            if m.into_led_section():
                k = rng.randint(0, 2500)
                if k: m.go(count=k)
                inside += m.pc is not None and (m.pc & ~1) < Machine.LED_END
        elif r < 0.85: m.finish_pass()
        else: m.go(count=rng.randint(1, 20000))
        m.inject(packet(g))
    m.passes(3)
    if m.matrix() != REF: failures.append((n, [len(g) for g in groups], sum(1 for i in range(MATRIX_LEN) if m.matrix()[i] != REF[i])))
check(f'{SCENARIOS} random interleavings of a 17-message LED burst with the stock main loop ({inside} packets landed inside the LED section): the applied LEDs equal the race-free reference',
      not failures, f'{len(failures)} of {SCENARIOS} differ, e.g. (scenario, packet sizes, differing matrix bytes) = {failures[:3]}')
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
