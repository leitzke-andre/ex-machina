"""Measure worst-case stack use of the patched paths against the firmware's stack (initial SP 0x20001c18;
the stack is the last part of the zero-init region, Keil default size 0x400 -> down to 0x20001818).
Usage: stack_depth.py <patched.bin> <data_init.bin>"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'emu'))
from machine import *

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
TOP = 0x20001C18
mu, usb = boot(fw, data)
lo = [TOP]
def track(uc, a, s, u):
    sp = uc.reg_read(UC_ARM_REG_SP)
    if sp < lo[0]: lo[0] = sp
mu.hook_add(UC_HOOK_CODE, track)

def measure(label, fn):
    lo[0] = TOP
    fn()
    print(f'{label:62s} {TOP - lo[0]:4d} bytes')
    return TOP - lo[0]

# patch usb.run so every call starts at the real stack top
orig_run = usb.run
def run(pc, r0=0, r1=0, limit=3_000_000):
    mu.reg_write(UC_ARM_REG_R0, r0); mu.reg_write(UC_ARM_REG_R1, r1)
    mu.reg_write(UC_ARM_REG_SP, TOP); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(pc, 0x08000000, count=limit)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
usb.run = run

ST = 0x20001028
def service(flags):
    mu.mem_write(ST + 0x88, struct.pack('<H', 1)); mu.mem_write(ST + 0xc2, bytes([5]))
    for k, v in flags.items(): mu.mem_write(ST + k, v)
    usb.run(0x08004621)
r1 = bytes([0b00001000, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
ev = bytes([12, 0x1F, 0xA0]) + bytes(60)
a = measure('service routine, all reports, through our translator', lambda: service({0x2cd: b'\x01', 0x2dd: r1, 0x2ce: b'\x01', 0x2ea: ev}))
b = measure('service routine, nothing to report (idle pass)', lambda: service({}))
def tick_flush():                                        # the main-loop hook at the end of the stock startup: the LED shadow is written out
    mu.mem_write(ST + 2, b'\0\0')
    usb.run(bl_target(fw, 0x08008D06) | 1)
f = measure('main-loop tick hook (end of the stock startup: LED frame written out)', tick_flush)
def save_path():                                         # the deepest main-loop path: SAVE of a changed config (flash erase + program) in the tick
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mmk3_config as mc
    cfg = bytearray(mc.default_cfg()); cfg[mc.FIELDS['channel'][0]] = 3
    for msg in (mc.set_request(bytes(cfg)), mc.save_request()):
        pk = b''; i = 0
        while len(msg) - i > 3: pk += bytes([4]) + msg[i:i + 3]; i += 3
        rest = msg[i:]; pk += bytes([{1: 5, 2: 6, 3: 7}[len(rest)]]) + rest + bytes(3 - len(rest))
        for o in range(0, len(pk), 64): usb._deliver_out(1, pk[o:o + 64])
        lo[0] = TOP                                          # measure the tick, not the interrupt
        mu.mem_write(ST + 2, b'\0\0'); usb.run(bl_target(fw, 0x08008D06) | 1)
        for _ in range(5): mu.mem_write(ST + 2, b'\0\0'); usb.run(bl_target(fw, 0x08008D06) | 1)
g = measure('main-loop tick: SET and SAVE of a config (validate, flash erase, program, reply)', save_path)
def mode_path():                                         # a mode button through the service routine (message built), then the ticks that render it and the panic
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mmk3_config as mc
    cfg = bytearray(mc.default_cfg()); cfg[mc.FIELDS['btn_act'][0] + 28] = mc.ACT_KEYS; cfg[mc.FIELDS['btn_act'][0] + 38] = mc.ACT_PANIC
    msg = mc.set_request(bytes(cfg))
    pk = b''; i = 0
    while len(msg) - i > 3: pk += bytes([4]) + msg[i:i + 3]; i += 3
    rest = msg[i:]; pk += bytes([{1: 5, 2: 6, 3: 7}[len(rest)]]) + rest + bytes(3 - len(rest))
    for o in range(0, len(pk), 64): usb._deliver_out(1, pk[o:o + 64])
    for _ in range(6): mu.mem_write(ST + 2, b'\0\0'); usb.run(bl_target(fw, 0x08008D06) | 1)
    lo[0] = TOP
    for pressed in (bytes([0, 0, 0, 0x10, 0, 0, 1]), bytes([0, 0, 0, 0, 0x40, 0, 1]), bytes(7)):      # Keyboard, then Mute (panic), then nothing
        service({0x2cd: b'\x01', 0x2dd: pressed + bytes(6)})
        for _ in range(8):
            mu.mem_write(ST + 2, b'\0\0'); usb.run(bl_target(fw, 0x08008D06) | 1); mu.mem_write(ST + 0x2d0, b'\0')
h = measure('mode button through the service routine + the ticks that render and send (message, display, panic)', mode_path)
def pad_routine(): usb.run(0x08003971)
c = measure('pad processing routine (stock)', lambda: (mu.mem_write(ST + 6, bytes([1])), pad_routine()))
def isr_sysex():
    def pack7(d):
        out = bytearray()
        for i in range(0, len(d), 7):
            g = d[i:i + 7]; out.append(sum(((v >> 7) & 1) << k for k, v in enumerate(g))); out += bytes(v & 0x7f for v in g)
        return bytes(out)
    msg = bytes([0xF0, 0x7D, 0x4D, 0x4B, 1, 0, 0, 127, 1]) + pack7(bytes(range(256))) + bytes([0xF7])
    pk = b''; i = 0
    while len(msg) - i > 3: pk += bytes([4]) + msg[i:i + 3]; i += 3
    rest = msg[i:]; pk += bytes([{1: 5, 2: 6, 3: 7}[len(rest)]]) + rest + bytes(3 - len(rest))
    for o in range(0, len(pk), 64):
        usb._deliver_out(1, pk[o:o + 64])
d = measure('USB interrupt: bulk OUT carrying a display SysEx (final packet decodes)', isr_sysex)
e = measure('USB interrupt: control transfer (GET_DESCRIPTOR config)', lambda: usb.control(setup_packet(0x80, 6, 0x0200, 0, 255)))
worst = max(a, b, c, f, g, h) + 32 + max(d, e)       # task-level use + exception frame + deepest interrupt
print(f'worst case (deepest task path + 32 B exception frame + deepest USB interrupt): {worst} bytes of 1024 (assumed stack size)')
assert worst < 900, 'stack headroom too small'
print('ALL PASS')
