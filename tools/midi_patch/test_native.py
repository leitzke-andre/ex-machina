"""The standalone image (build_patch.py --native) booted in the emulator from its own reset vector, the way NI's bootloader starts it: the
peripheral model (tools/emu/periph.py) with the LED chips and the strip controller on their buses, settings pages in flash, the USB
peripheral model (tools/emu/usb_model.py) attached to it. The main loop runs in slices; SysTick and the USB interrupt are delivered
between slices like interrupts. Checks: the start-up reaches the main loop, the LED chips are set up, the strip controller start-up passes,
USB enumerates with our descriptors and strings (manufacturer and product as before, the serial number from the settings page), a SysEx
INFO request makes the round trip, and nothing ever runs in the "return 0" stub that stands in for NI's code.
Usage: test_native.py <native.bin>   (symbols from <native.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu')); sys.path.insert(0, HERE)
from unicorn import *
from unicorn.arm_const import *
from periph import machine, I2CSlaveBus
import usb_model
from usb_model import setup_packet
import mmk3_config as mc
import devsim

img = open(sys.argv[1], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

mu, p = machine(img, bytes(0x5000))
vec = struct.unpack_from('<16I', img, 0)
# settings pages: trims, pad offsets; page B with brightness 7, sensitivity 80, contrast, the format mark, a device id 12 34 56 78, the version
a = bytearray(b'\xff' * 0x400); a[:0xC6] = bytes(10 for _ in range(0xC6)); a[0x200:0x210] = bytes(range(90, 106))
b = bytearray(b'\xff' * 0x400); b[:6] = bytes([1, 0, 0, 0x17, 7, 80]); b[0x100:0x200] = bytes(0x100); b[0x104:0x108] = bytes([0x12, 0x34, 0x56, 0x78])
b[0x3E6] = 0x60; b[0x3E8] = 4; b[0x3E9] = 4; b[0x3FE] = 0x52; b[0x3FF] = 0
mu.mem_write(0x0801F000, bytes(a)); mu.mem_write(0x0801F800, bytes(b))
led = I2CSlaveBus('B', 6, 7, acks=(0x74, 0x77)); p.buses.append(led)
status = [0, 0, 0xF5, 0xF6, 0, 0]
strip = I2CSlaveBus('A', 10, 9, acks=(0x01, 0x38, 0x40, 0x15), reader=lambda ad, i: (status[i] if i < 6 else 0) if ad == 0x40 else 0); p.buses.append(strip)
stub_runs = []
resets = []                                          # software resets (SCB AIRCR): only DFU entry or a requested reboot may write it
mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, ad, sz, v, u: v & 4 and resets.append(hex(v)), begin=0xE000ED0C, end=0xE000ED0F)
mu.hook_add(UC_HOOK_CODE, lambda uc, ad, s, u: stub_runs.append(uc.reg_read(UC_ARM_REG_LR)), begin=0x08003140, end=0x08003141)

# the USB peripheral model, wired into the peripheral model's register file
class Usb(usb_model.UsbModel):
    def __init__(self, mu):                          # (no mapping of its own: periph.py owns the address space)
        self.mu = mu; self.ep = [0] * 8; self.cntr = 0; self.flags = 0; self.daddr = 0; self.btable = 0; self.other = {}; self.log = []
    def pma_get16(self, q): return p.regs[0x40006000 + 2 * q] & 0xFFFF
    def pma_set16(self, q, v): p.regs[0x40006000 + 2 * q] = v & 0xFFFF
    def isr(self): interrupt(SYM['mmk3_usb_isr'])
usb = Usb(mu)
pr, pw = p.read, p.write
def rd(ad, size):
    if 0x40005C00 <= ad < 0x40005C54: return usb._read(None, ad - 0x40005000, size, None)
    if 0x40006000 <= ad < 0x40006400: return p.regs[ad & ~3] & 0xFFFF
    return pr(ad, size)
def wr(ad, size, v):
    if 0x40005C00 <= ad < 0x40005C54: return usb._write(None, ad - 0x40005000, size, v, None)
    return pw(ad, size, v)
p.read, p.write = rd, wr

# running: the main code in slices, interrupts between them
main_ctx = [None]
def interrupt(fn):
    ctx = mu.context_save()
    sp = (mu.reg_read(UC_ARM_REG_SP) - 0x80) & ~7
    mu.reg_write(UC_ARM_REG_SP, sp); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(fn | 1, 0x08000000, count=2_000_000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    mu.context_restore(ctx)
mu.reg_write(UC_ARM_REG_SP, vec[0]); pc = [vec[1]]
def run(n_slices, slice_len=20000, ms_per_slice=1):
    for _ in range(n_slices):
        try: mu.emu_start(pc[0] | 1, 0, count=slice_len)
        except UcError as e: raise RuntimeError(f'{e} at {mu.reg_read(UC_ARM_REG_PC):#x}')
        pc[0] = mu.reg_read(UC_ARM_REG_PC)
        for _ in range(2 * ms_per_slice): interrupt(SYM['mmk3_systick'])

check('the vector table: stack 0x20001C18, reset = native_reset, SysTick and USB entries ours',
      (vec[0], vec[1], vec[15], struct.unpack_from('<I', img, 0x40 + 20 * 4)[0]), (0x20001C18, SYM['native_reset'] | 1, SYM['mmk3_systick'] | 1, SYM['mmk3_usb_isr'] | 1))
run(1500)                                            # the start-up (0.3 s countdown) and the first main-loop passes
cntr = rd(0x40005C40, 4)
check('the start-up reached the end: USB started (interrupts on, D+ pull-up on PA8 high)', (cntr, (p.regs[0x4001080C] >> 8) & 1), (0xBF00, 1))
check('the LED chips were set up (both chips: function page, frame cleared, normal operation)', sorted({t[0] for t in led.tx}), [0x74, 0x77])
check('the strip controller start-up passed (status F5 F6): the read cycles run (delay unit 2)', (bytes(mu.mem_read(0x20001028 + 0xC7, 1))[0], any(t[0] == 0x15 for t in strip.tx)), (2, True))
check('the settings were read: trims, pad offsets, brightness 7, sensitivity 80', (bytes(mu.mem_read(0x20000E1C, 2)), bytes(mu.mem_read(0x20000CC8, 2)), bytes(mu.mem_read(0x20001028 + 0x5E0, 2))), (bytes([10, 10]), bytes([90, 91]), bytes([7, 80])))
run(5000)                                            # no host for 5 s: the device must stay up (no fallback to a stock path that is not there)
check('no host for over 5 s: no restart', resets, [])
usb.reset()
d, st = usb.control(setup_packet(0x80, 6, 0x0100, 0, 64))
check('USB: the device descriptor (VID:PID 17cc:1700)', (st, d[8:12]), ('ok', bytes.fromhex('cc170017')))
usb.control(setup_packet(0x00, 5, 9))
strs = []
for i in (1, 2, 3):
    d, st = usb.control(setup_packet(0x80, 6, 0x0300 | i, 0x0409, 255)); strs.append(d[2:].decode('utf-16-le'))
check('USB strings: manufacturer, product as always, the serial number from the device id in the settings page', strs, ['Native Instruments', 'Maschine Mikro MK3', '78563412'])
check('USB: SET_CONFIGURATION 1', usb.control(setup_packet(0x00, 9, 1))[1], 'ok')
run(15500)                                           # a host that never sends our SysEx (any MIDI app) for over 15 s: still no restart
check('a host that never sends our SysEx, for over 15 s: no restart', resets, [])
for pk in [devsim.usb_packets(mc.info_request())[k:k + 64] for k in range(0, len(devsim.usb_packets(mc.info_request())), 64)]: usb.bulk_out(1, pk)
got = []
for _ in range(40):
    run(1); g = usb.bulk_in(1)
    if g: got.append(g)
reply = devsim.sysex_messages(got)
check('a SysEx INFO request over USB is answered by the main loop (protocol 2)', [mc.parse_reply(m)['protocol'] for m in reply], [2])
check('nothing ever ran in the "return 0" stub (no call into the missing NI code was made)', stub_runs, [])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
