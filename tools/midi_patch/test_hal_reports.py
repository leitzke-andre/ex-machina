"""Our report builders and dispatcher (hal.c) against the stock routines they replace. Random states of the scan results (button bytes,
encoder events, strip positions and touch, the time) go through both report builders; random combinations of pending work (report 1,
report 2, LED frames with plain colour codes or the special commands, display regions inside and outside the screen, brightness and
sensitivity requests) through both dispatchers. The translator, the LED colour layer and the settings writer are replaced by recording
stubs: the calls they get (with the report bytes) and all of the stock RAM must be the same.
Usage: test_hal_reports.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
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
def setup():
    mu, p = machine(img, data); calls = []
    def stub(name, nargs):
        def h(uc, a, s, u):
            args = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)][:nargs]
            if name == 'translate': args = [bytes(uc.mem_read(args[0], args[1]))]
            if name == 'colour': args.append(struct.unpack('<I', uc.mem_read(uc.reg_read(UC_ARM_REG_SP), 4))[0] & 0xFF)
            calls.append((name, args)); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        return h
    for addr, name, n in ((SYM['translate_report'], 'translate', 2), (0x08005490, 'colour', 4), (0x08004704, 'settings', 1)):
        mu.hook_add(UC_HOOK_CODE, stub(name, n), begin=addr, end=addr + 1)
    return mu, p, calls

def ram(mu): return bytes(mu.mem_read(0x20000100, 0x100)) + bytes(mu.mem_read(0x20000C70, 0x80)) + bytes(mu.mem_read(ST, 0x490))

def compare(name, fn_stock, fn_own, prepare, n=300, seed=1):
    rng = random.Random(seed); bad = []; called = 0
    for t in range(n):
        st = random.Random(rng.random())
        res = []
        for fn in (fn_stock, fn_own):
            mu, p, calls = setup(); prepare(mu, random.Random(st.random() if False else t * 7919 + seed)); call(mu, fn)
            res.append((ram(mu), calls))
        if res[0] != res[1]:
            diff = [i for i in range(len(res[0][0])) if res[0][0][i] != res[1][0][i]][:6]
            bad.append((t, diff, res[0][1][:2], res[1][1][:2]))
        called += len(res[0][1])
    check(f'{name}: {n} random states, the same RAM and the same calls as the stock code ({called} calls)', bad[:3], [])

def prep_scan(mu, r):
    for i in range(41): mu.mem_write(ST + 0x8B + i, bytes([r.choice((0, 0, 0, 1, 2, 0x40, 0x80))]))
    mu.mem_write(ST + 0xBA, bytes([r.choice((1, 2, 3))])); mu.mem_write(ST + 0x2E3, bytes([r.randrange(16)]))
    mu.mem_write(ST + 0xC4, bytes([r.randrange(256) if r.random() < .3 else r.randrange(45)])); mu.mem_write(ST + 0xC5, bytes([r.randrange(256)]))
    mu.mem_write(ST + 0xC6, bytes([r.choice((0, 0, 1, 77))])); mu.mem_write(0x2000018D, bytes([r.randrange(2)]))
    mu.mem_write(0x20000198, bytes([r.randrange(50), r.randrange(50)])); mu.mem_write(ST + 0xC0, struct.pack('<H', r.randrange(65536)))
    mu.mem_write(ST + 0x2CD, bytes([r.randrange(2)]))
compare('button report', 0x080038D0, SYM['own_btn_report'], prep_scan)
compare('encoder report', 0x0800392C, SYM['own_enc_report'], prep_scan)
compare('strip report', 0x08003CE4, SYM['own_strip_report'], prep_scan)

def prep_dispatch(mu, r):
    prep_scan(mu, r)
    for f in range(0x2CD, 0x2D3): mu.mem_write(ST + f, bytes([r.random() < 0.45]))
    mu.mem_write(ST + 0x2DD, bytes(r.randrange(256) for _ in range(13))); mu.mem_write(ST + 0x2EA, bytes(r.randrange(256) for _ in range(63)))
    kind = r.randrange(5)
    led = [r.choice((r.randrange(128), 0xFF)) for _ in range(80)]
    if kind == 1: led[:3] = [0xAA, 0xAB, 0xAC]; led[3] = r.choice((0x10, 0x85, 0xC0)); led[8] = r.choice((0xAD, 0x00))
    if kind == 2: led[:3] = [0xAA, 0xAB, 0xAD]; led[3] = r.choice((0xF0, 0x33))
    if kind == 3: led[:2] = [0xAA, 0x12]
    mu.mem_write(ST + 0x329, bytes(led))
    x, pg, w, h = r.randrange(140), r.randrange(6), r.randrange(130), r.randrange(5)
    mu.mem_write(ST + 0x379, bytes([x, 0, pg, 0, w, 0, h, 0]) + bytes(r.randrange(256) for _ in range(256)))
    mu.mem_write(ST + 0xC8, bytes([r.choice((0, 3, 8))]))
    mu.mem_write(ST + 0x481, bytes([r.randrange(14)])); mu.mem_write(ST + 0x483, bytes([0x22, 0xFF, 5, 1, r.randrange(110)]) if r.random() < .7 else bytes(5))
compare('dispatcher', 0x08003E24, SYM['own_dispatch'], prep_dispatch, n=600)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
