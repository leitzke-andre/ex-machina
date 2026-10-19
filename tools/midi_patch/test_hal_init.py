"""Our board init (hal.c own_board_init) against the stock one, on the emulated peripherals (reset values, ready flags): the settings load
and the strip controller start-up are recording stubs on both sides (the settings load is still the stock code; the strip
start-up has its own test, test_hal_strip_start.py). Every peripheral register written,
the output levels, SysTick and the vector table must end up the same, the two stubs must be called in the same place, and RAM must match.
Usage: test_hal_init.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

def run(fn):
    mu, p = machine(img, data); calls = []; order = []
    def stub(name):
        def h(uc, a, s, u): calls.append((name, len(order))); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        return h
    for a, n in ((0x080047F4, 'settings'), (0x08006E1C, 'strip_handshake'), (SYM['own_strip_start'], 'strip_handshake'), (SYM['own_settings_load'], 'settings')): mu.hook_add(UC_HOOK_CODE, stub(n), begin=a, end=a + 1)
    orig = p.write
    def w(a, size, v): order.append(a & ~3); orig(a, size, v)
    p.write = w
    scs = {}
    mu.hook_add(UC_HOOK_MEM_WRITE, lambda uc, acc, a, size, v, u: scs.__setitem__(a, v), begin=0xE000E000, end=0xE000EFFF)
    call(mu, fn, limit=50_000_000)
    regs = {hex(a): hex(v) for a, v in sorted(p.regs.items()) if v or a in (0x40010800,)}
    return regs, calls, {hex(a): hex(v) for a, v in sorted(scs.items())}, bytes(mu.mem_read(0x20000000, 0x4200)), sorted(set(order))

st, ow = run(0x08007EA2), run(SYM['own_board_init'])
diff = {k: (st[0].get(k), ow[0].get(k)) for k in set(st[0]) | set(ow[0]) if st[0].get(k) != ow[0].get(k)}
check(f'the same {len(st[0])} peripheral register values after the board init (clocks, flash, AFIO, GPIO A/B/C, ADC, DMA, SPI2)', diff, {})
check('SysTick and the vector table set the same way', ow[2], st[2])
check('the two stock pieces (settings pages, strip handshake) are called once each, in the same order', [c[0] for c in ow[1]], [c[0] for c in st[1]])
ramdiff = [hex(0x20000000 + i) for i in range(len(st[3])) if st[3][i] != ow[3][i] and not (0x1818 <= i < 0x1C18)]
check('RAM the same (apart from the stack)', ramdiff[:8], [])
check('the same set of registers written', ow[4], st[4])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
