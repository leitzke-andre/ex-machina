"""Build-option tests for the velocity curve. Usage: test_vel_curve.py <stock fw.bin> <data_init.bin> <workdir>
Runs build_patch.py with every --vel-curve, with --vel-table files (valid and invalid), --vel-shift and the stages, checks
the flash content, and runs one curved image through the emulated translator end to end. The curve formulas themselves
are checked against the disassembled editor code in test_translate.py."""
import os, struct, subprocess, sys
from unicorn import *
from unicorn.arm_const import *

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_patch as bp
STOCK, DATA, WORK = sys.argv[1], open(sys.argv[2], 'rb').read(), sys.argv[3]
FL = 0x08003000
os.makedirs(WORK, exist_ok=True)
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'))

def build(name, *args):
    out = os.path.join(WORK, name + '.bin')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'build_patch.py'), STOCK, out, *args], capture_output=True, text=True)
    return r, out
def table_of(path, slot=None):
    """The table the image's default curve selects (cfg.vel_curve at offset 149), or the given slot."""
    img = open(path, 'rb').read()
    if slot is None: slot = img[bp.CFG_ADDR - FL + 149]
    return img[bp.VEL_TABLE_ADDR - FL + slot * 256:][:256]
def count_of(path): return open(path, 'rb').read()[bp.CURVE_COUNT_ADDR - FL]
STANDARD = b''.join(bp.vel_table(n) for n in bp.VEL_CURVES) + bp.vel_table('linear')

# every build carries all eight curves and the ninth slot; --vel-curve only chooses the curve the config starts with (cfg.vel_curve, offset 149)
for i, name in enumerate(bp.VEL_CURVES):
    r, out = build('vc_' + name, '--vel-curve', name)
    img = open(out, 'rb').read()
    check(f'--vel-curve {name}: builds, selects slot {i}, all {len(STANDARD) // 256} slots at {bp.VEL_TABLE_ADDR:#x} are the generated curves, vel_shift stays 5, 8 curves to step through, image {len(img)} B',
          r.returncode == 0 and img[bp.CFG_ADDR - FL + 149] == i and table_of(out) == bp.vel_table(name) and img[bp.VEL_TABLE_ADDR - FL:][:len(STANDARD)] == STANDARD
          and img[bp.CFG_ADDR - FL + 71] == 5 and count_of(out) == 8 and len(img) > bp.CODE_ADDR - FL and len(img) <= bp.APP_LIMIT - FL, detail=(r.returncode, r.stderr[-200:]))
r, out = build('vc_default')
check('default build = --vel-curve linear (slot 3)', r.returncode == 0 and table_of(out) == bp.vel_table('linear') == bytes(i >> 1 for i in range(256)) and open(out, 'rb').read()[bp.CFG_ADDR - FL + 149] == 3)
check('the build summary names the curve', 'velocity linear' in r.stdout, detail=r.stdout[-120:])

# gain
r, out = build('vc_shift6', '--vel-shift', '6')
check('--vel-shift 6 is written to the config (offset 71)', r.returncode == 0 and open(out, 'rb').read()[bp.CFG_ADDR - FL + 71] == 6)
for bad in ('0', '9'):
    r, _ = build('vc_badshift', '--vel-shift', bad)
    check(f'--vel-shift {bad} is rejected', r.returncode != 0)

# custom tables: 128 entries are doubled (output velocity per input velocity), 256 are used as they are
tf = lambda name, text: (open(os.path.join(WORK, name), 'w').write(text), os.path.join(WORK, name))[1]
ident = tf('t128.txt', '# identity\n' + ', '.join(str(i) for i in range(128)) + '\n')
r, out = build('vc_t128', '--vel-table', ident)
check('--vel-table with 128 values (comments and commas allowed): each entry is doubled, identity = the linear table; it is slot 8, selected, and the curve button steps through 9',
      r.returncode == 0 and table_of(out) == bytes(i >> 1 for i in range(256)) and open(out, 'rb').read()[bp.CFG_ADDR - FL + 149] == 8 and count_of(out) == 9, detail=r.stderr[-200:])
ramp = [127 - i // 2 for i in range(256)]
r, out = build('vc_t256', '--vel-table', tf('t256.txt', '\n'.join(map(str, ramp))), '--vel-curve', 'hard3')
check('--vel-table with 256 values wins over --vel-curve, and the eight standard curves are still there', r.returncode == 0 and table_of(out) == bytes(ramp)
      and open(out, 'rb').read()[bp.VEL_TABLE_ADDR - FL:][:8 * 256] == STANDARD[:8 * 256], detail=r.stderr[-200:])
for label, text in (('127 values', ' '.join(['5'] * 127)), ('129 values', ' '.join(['5'] * 129)), ('a value of 128', ' '.join(['5'] * 127 + ['128'])),
                    ('a negative value', ' '.join(['5'] * 127 + ['-1'])), ('a non-number', ' '.join(['5'] * 127 + ['x']))):
    r, _ = build('vc_bad', '--vel-table', tf('bad.txt', text))
    check(f'--vel-table with {label} is rejected with a message', r.returncode != 0 and ('need 128 or 256 integers' in r.stderr or 'invalid literal' in r.stderr), detail=r.stderr[-160:])

# stages: 1 = stock size and no table, 2 = payload including the table, 3 = full patch
r1, o1 = build('vc_s1', '--stage', '1'); r2, o2 = build('vc_s2', '--stage', '2', '--vel-curve', 'hard2')
i1, i2 = open(o1, 'rb').read(), open(o2, 'rb').read()
check('stage 1 is the stock size and carries no table', r1.returncode == 0 and len(i1) == bp.STOCK_LEN)
check('stage 2 carries the tables (hard2 selected) but no hook: the stock bl at 0x08004036 is intact',
      r2.returncode == 0 and table_of(o2) == bp.vel_table('hard2') and i2[0x08004036 - FL:][:4] == bp.bl(0x08004036, 0x08008A38))

# end to end: a hard3 image through the emulated translator
r, out = build('vc_e2e', '--vel-curve', 'hard3')
fw = open(out, 'rb').read()
def bl_target(addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off
mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, DATA)
mu.mem_map(0x40000000, 0x100000); mu.mem_map(0xE0000000, 0x100000)
def hit(pad, val):
    buf = bytes([2, pad, (1 << 4) | (val >> 8), val & 0xff]) + bytes(60)
    mu.mem_write(0x20003000, buf)
    mu.reg_write(UC_ARM_REG_R0, 0x20003000); mu.reg_write(UC_ARM_REG_R1, len(buf))
    mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    w0 = struct.unpack('<H', mu.mem_read(0x20000146, 2))[0]
    try: mu.emu_start(bl_target(0x08004036) | 1, 0x08000000, count=300000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    w1 = struct.unpack('<H', mu.mem_read(0x20000146, 2))[0]
    ring = bytes(mu.mem_read(0x20000778, 0x500)); out = []; i = w0
    while i != w1: out.append(ring[i]); i = (i + 1) % 0x500
    return [tuple(out[k:k + 4]) for k in range(0, len(out), 4)]
t = bp.vel_table('hard3')
got = [hit(k, v) for k, v in enumerate((300, 1000, 2048, 3000, 4000))]
want = [[(9, 0x90, fw[bp.CFG_ADDR - FL + 5 + k], max(1, t[v >> 4]))] for k, v in enumerate((300, 1000, 2048, 3000, 4000))]
check('hard3 image in the emulator: hits 300, 1000, 2048, 3000, 4000 -> ' + str([w[0][3] for w in want]), got, want)

print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
