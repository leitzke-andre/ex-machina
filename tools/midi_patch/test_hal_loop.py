"""Our SysTick handler, service routine and normal-mode scan (hal.c) against the stock routines they replace. The SysTick handler runs
on random timer states; the two main-loop routines run on random combinations of due jobs with every routine they call replaced by a
recording stub (the drivers are left on the stock side of their switches, so both paths end in the same stock routines). The calls, in
order, and all of the RAM and output pins must be the same; the suspend path is checked with its display commands on SPI2.
Usage: test_hal_loop.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

ST = 0x20001028
STUBS = {0x08008C34: 'startup', 0x080033A4: 'adc_avg', 0x08007714: 'btn_scan', 0x080077E8: 'btn_eval', 0x08007FA4: 'strip_read', 0x08006028: 'led_refresh',
         0x080068B0: 'disp_send', 0x080089B4: 'usb_tx', 0x08003E24: 'dispatch', 0x08003970: 'pad_eval', 0x0800392C: 'enc_report', 0x080038D0: 'btn_report',
         0x08003CE4: 'strip_report', 0x08006624: 'disp_fade', 0x080047D4: 'settings_save'}

def setup(scan_result=0):
    mu, p = machine(img, data); calls = []
    def stub(name):
        def h(uc, a, s, u):
            calls.append((name, uc.reg_read(UC_ARM_REG_R0) if name == 'btn_eval' else None))
            if name == 'btn_scan': uc.reg_write(UC_ARM_REG_R0, scan_result)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        return h
    for addr, name in STUBS.items(): mu.hook_add(UC_HOOK_CODE, stub(name), begin=addr, end=addr + 1)
    spi = []; orig = p.write
    def w(a, size, v):
        if a == 0x4000380C: spi.append((v & 0xFF, (p.regs[0x40010C0C] >> 14) & 1))
        orig(a, size, v)
    p.write = w
    mu.mem_write(0x20004200, bytes(1))                                    # (our state: every driver on the stock side)
    return mu, p, calls, spi

def snap(mu, p): return bytes(mu.mem_read(0x20000140, 0x80)) + bytes(mu.mem_read(ST, 0x800)), p.regs[0x40010C0C] & 0x300

def random_state(mu, p, r):
    for o in (2, 0x88, 0xC0, 0x2CA, 0x7EA, 0xBE): mu.mem_write(ST + o, struct.pack('<H', r.choice((0, 1, 2, 300, 0xFFFF, r.randrange(65536)))))
    for o in (6, 0xBA, 0x8A, 0xC3, 0xBC, 0xC2, 0xC9, 0xC8) + tuple(range(0x2CD, 0x2D3)): mu.mem_write(ST + o, bytes([r.choice((0, 0, 1, 3, 255))]))
    for i in range(16): mu.mem_write(ST + 0xC + 8 * i, bytes([r.choice((0, 7, 254, 255))]))
    mu.mem_write(0x200001A4, bytes([r.randrange(2)])); mu.mem_write(0x200001A5, bytes([r.choice((0, 0, 1))]))
    mu.mem_write(0x200001AE, struct.pack('<H', r.choice((0, 5, 0xFFF0, 0xFFFF))))
    w = r.randrange(0x500); mu.mem_write(0x20000146, struct.pack('<HH', w, w if r.random() < .5 else (w + 4) % 0x500))
    p.regs[0x40020000] = r.choice((0, 2, 0x0F, 0xF0)); p.regs[0x40010C0C] = r.randrange(0x10000)

for name, stock, own, n in (('SysTick handler', 0x08007ED4, SYM['own_systick'], 600), ('service routine', 0x08004620, SYM['own_service'], 600),
                            ('normal-mode scan', 0x080042A0, SYM['own_normal'], 600)):
    bad, called = [], 0
    for t in range(n):
        res = []
        for fn in (stock, own):
            r = random.Random(t * 31 + 7); mu, p, calls, spi = setup(scan_result=r.choice((0, 1, 2, 3)))
            random_state(mu, p, r); call(mu, fn)
            res.append((snap(mu, p), calls, spi))
        if res[0] != res[1] and len(bad) < 3:
            d = [i for i in range(len(res[0][0][0])) if res[0][0][0][i] != res[1][0][0][i]][:5]
            bad.append((t, d, res[0][1], res[1][1], res[0][0][1], res[1][0][1], len(res[0][2]), len(res[1][2])))
        called += len(res[0][1])
    check(f'{name}: {n} random states, the same calls in the same order, RAM, LED-driver pins and display commands as the stock code ({called} calls)', bad, [])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
