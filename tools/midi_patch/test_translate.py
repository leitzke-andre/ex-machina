"""Translator tests with assertions. Usage: test_translate.py <patched.bin> <data_init.bin>
Checks the HID-report -> USB-MIDI translation against NI's documented MIDI-mode defaults."""
import os, re, struct, sys
from unicorn import *
from unicorn.arm_const import *
FL = 0x08003000
fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
PADNOTE = list(fw[0x0800CE00 - FL + 5:][:16])      # cfg.pad_note: note of each pad report index (default: pad 1 = index 12 = note 36)

def bl_target(addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off
ENTRY = bl_target(0x08004036) | 1

def session():
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
    mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
    mu.mem_map(0x40000000, 0x100000); mu.mem_map(0xE0000000, 0x100000)
    return mu

def call(mu, buf):
    mu.mem_write(0x20003000, buf)
    mu.reg_write(UC_ARM_REG_R0, 0x20003000); mu.reg_write(UC_ARM_REG_R1, len(buf))
    mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    w0 = struct.unpack('<H', mu.mem_read(0x20000146, 2))[0]
    try: mu.emu_start(ENTRY, 0x08000000, count=300000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    w1 = struct.unpack('<H', mu.mem_read(0x20000146, 2))[0]
    ring = bytes(mu.mem_read(0x20000778, 0x500)); out = []; i = w0
    while i != w1: out.append(ring[i]); i = (i + 1) % 0x500
    return [tuple(out[k:k + 4]) for k in range(0, len(out), 4)]

def r1(buttons=0, touch=0, enc=0, pos=0):
    return bytes([1] + [(buttons >> (8 * k)) & 0xff for k in range(5)] + [touch, enc, 0, 0, pos, 0, 0, 0])
def r2(events):
    p = bytearray([2])
    for pad, typ, val in events: p += bytes([pad, (typ << 4) | (val >> 8), val & 0xff])
    return bytes(p + bytes(64 - len(p)))
def cc(v, n=0, ch=0): return (0x0B, 0xB0 | ch, n, v)

ok = True
def check(name, got, want):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}'))

mu = session()
check('baseline report produces nothing', call(mu, r1()), [])
check('Volume (id 3) -> CC44 (NI map)', call(mu, r1(buttons=1 << 3)), [cc(127, 44)])
check('Volume released -> CC44 = 0', call(mu, r1()), [cc(0, 44)])
def rt(b): return (0x0F, b, 0, 0)
check('Play (id 22) -> MIDI Start, nothing on release', [call(mu, r1(buttons=1 << 22)), call(mu, r1())], [[rt(0xFA)], []])
check('Chords (id 29) -> CC84, Step (id 30) -> CC83 (NI quirk)', call(mu, r1(buttons=(1 << 29) | (1 << 30))), [cc(127, 84), cc(127, 83)])
check('Shift (id 25) -> spare CC43', call(mu, r1(buttons=1 << 25)), [cc(127, 43), cc(0, 84), cc(0, 83)])
check('encoder press (id 39) -> CC8', call(mu, r1(buttons=1 << 39)), [cc(0, 43), cc(127, 8)])
check('encoder touch (byte 5 bit 0) -> CC9', call(mu, r1(buttons=1 << 39, touch=1)), [cc(127, 9)])
check('encoder touch released -> CC9 = 0', call(mu, r1(buttons=1 << 39)), [cc(0, 9)])
mu = session(); call(mu, r1())
# The 4-bit counter counts UP when the knob is turned clockwise (measured on the real device); clockwise raises the value.
check('encoder: 1 click clockwise (counter 0 -> 1), absolute from 0 like NI\'s template -> CC7 = 1', call(mu, r1(enc=1)), [cc(1, 7)])
check('encoder: 2 clicks counter-clockwise (counter 1 -> 15) clamp at 0 (NI wrap mode 0) -> CC7 = 0', call(mu, r1(enc=15)), [cc(0, 7)])
# NI's engine (Assignment::incValueInt) sends nothing when an absolute encoder is already at its limit
m3 = session(); call(m3, r1())
check('encoder: 1 click counter-clockwise at the lower limit sends nothing', call(m3, r1(enc=15)), [])
check('encoder: 1 click clockwise afterwards -> CC7 = 1', call(m3, r1(enc=0)), [cc(1, 7)])
m4 = session(); m4.mem_write(0x0800CE00 + 92, bytes([126])); call(m4, r1())
check('encoder: 3 clicks clockwise from 126 clamp at 127 -> CC7 = 127', call(m4, r1(enc=3)), [cc(127, 7)])
check('encoder: 1 more click clockwise at the upper limit sends nothing', call(m4, r1(enc=4)), [])
# report 1 is sent only on change: the first report may already be a press; only the encoder counter needs a baseline
mb = session()
check('a button press in the very first report is not lost (Volume -> CC44 = 127)', call(mb, r1(buttons=1 << 3)), [cc(127, 44)])
check('and its release follows', call(mb, r1()), [cc(0, 44)])
mb = session(); call(mb, r1(enc=7))
check('the first report only sets the encoder baseline (counter 7 sends nothing), the next click clockwise (7 -> 8) -> CC7 = 1', call(mb, r1(enc=8)), [cc(1, 7)])
mb = session()
check('a strip touch in the very first report is reported (pos 100 -> CC1 = 63)', call(mb, r1(pos=100)), [cc(63, 1)])
mb = session()
check('encoder touch in the very first report is reported (CC9 = 127)', call(mb, r1(touch=1)), [cc(127, 9)])
check('strip untouched (pos 0) sends nothing', call(mu, r1(enc=15, pos=0)), [])
check('strip pos 1 -> CC1 = 0', call(mu, r1(enc=15, pos=1)), [cc(0, 1)])
check('strip pos 200 -> CC1 = 127', call(mu, r1(enc=15, pos=200)), [cc(127, 1)])
check('strip pos 100 -> CC1 = 63', call(mu, r1(enc=15, pos=100)), [cc(63, 1)])
check('strip release sends nothing by default', call(mu, r1(enc=15, pos=0)), [])
# every NI-assigned button against NI's built-in map (the Controller Editor's Map::Map; same numbers as the manual's diagram)
NI_CC = {1: 39, 2: 40, 3: 44, 4: 46, 5: 48, 6: 45, 7: 47, 10: 49, 11: 50, 12: 51, 13: 52, 14: 34, 15: 35, 16: 36, 17: 37,
         18: 53, 19: 54, 20: 55, 21: 56, 23: 58, 26: 80, 27: 81, 28: 82, 29: 84, 30: 83, 31: 85, 32: 86, 33: 87,
         34: 88, 35: 89, 36: 90, 37: 91, 38: 92}
m5 = session(); call(m5, r1())
wrong = [(bid, n) for bid, n in NI_CC.items() if call(m5, r1(buttons=1 << bid)) != [cc(127, n)] or call(m5, r1()) != [cc(0, n)]]
check(f'all {len(NI_CC)} CC buttons (everything NI assigns except Play and Stop, which are MIDI Start / Stop here, and Project (CC 38), which always loads the next preset slot) send their CC on press and 0 on release', wrong, [])
for mode, name, plus1, minus2 in ((0, 'relative-offset (65/63 around 64)', 65, 62), (2, 'relative two\'s complement (1/127)', 1, 126)):
    m2 = session(); m2.mem_write(0x0800CE00 + 89, bytes([mode])); call(m2, r1())
    check(f'encoder mode {name}: 1 click clockwise (counter 0 -> 1) -> {plus1}', call(m2, r1(enc=1)), [cc(plus1, 7)])
    check(f'encoder mode {name}: 2 clicks counter-clockwise (counter 1 -> 15) -> {minus2}', call(m2, r1(enc=15)), [cc(minus2, 7)])
# pad report index -> note: index 12 is pad 1 (note 12), index 0 is pad 13 (note 24), index 15 is pad 4 (note 15)
def note(on, n, v): return ((0x09 if on else 0x08), (0x90 if on else 0x80), n, v)
check('pad index 12 (pad 1) hit 4000 -> the note of pad 1, velocity 4000>>5 = 125', call(mu, r2([(12, 1, 4000)])), [note(1, PADNOTE[12], 125)])
check('pad index 0 (pad 13) hit 765 -> note PADNOTE[0], velocity 23', call(mu, r2([(0, 1, 765)])), [note(1, PADNOTE[0], 23)])
check('pad index 15 (pad 4) slow press type 0 value 40 -> its note, velocity floor 1', call(mu, r2([(15, 0, 40)])), [note(1, PADNOTE[15], 1)])
check('pressure 2000 on pad 12 while held -> poly pressure 62', call(mu, r2([(12, 4, 2000)])), [(0x0A, 0xA0, PADNOTE[12], 62)])
check('identical pressure is not repeated', call(mu, r2([(12, 4, 2000)])), [])
check('release (type 3) pad 12 -> note off', call(mu, r2([(12, 3, 0)])), [note(0, PADNOTE[12], 0)])
check('pressure after release ignored', call(mu, r2([(12, 4, 300)])), [])
check('release type 2 on pad 0 -> note off', call(mu, r2([(0, 2, 0)])), [note(0, PADNOTE[0], 0)])
check('two reports in one buffer', call(mu, r1(buttons=1 << 3, enc=15) + r2([(13, 1, 1000)])), [cc(127, 44), note(1, PADNOTE[13], 31)])
# button modes (cfg.btn_mode at +95): toggle = NI's default (127 / 0 on alternate presses), trigger = 127 on press only
for mode, name in ((1, 'toggle'), (2, 'trigger')):
    m3 = session(); m3.mem_write(0x0800CE00 + 95, bytes([mode])); call(m3, r1())
    seq = [call(m3, r1(buttons=1 << 3)), call(m3, r1()), call(m3, r1(buttons=1 << 3)), call(m3, r1())]
    want = ([[cc(127, 44)], [], [cc(0, 44)], []] if mode == 1 else [[cc(127, 44)], [], [cc(127, 44)], []])
    check(f'button mode {name}: press, release, press, release -> {want}', seq, want)

# --- velocity curves ---------------------------------------------------------------------------------------------
# build_patch.vel_table() writes the 256-byte table; here it is poked into the emulated flash so that every curve runs on
# the same image. The expectations come from the editor's calcPadVelocity_f as disassembled: per case, the coefficient of
# the cubic term and of the linear term (MULSS chains), written independently of build_patch's "a" parameterisation.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp
ASM = {'soft3': (0.9, 0.1), 'soft2': (0.6, 0.4), 'soft1': (0.3, 0.7), 'hard1': (0.3, 0.7), 'hard2': (0.6, 0.4), 'hard3': (0.9, 0.1)}
def asm_curve(name, x):
    if name == 'linear': return x
    if name == 'fixed': return 1.0                       # case 7 returns the constant 1.0 left in xmm0
    cube, lin = ASM[name]
    if name.startswith('hard'): return cube * x * x * x + x * lin
    t = 1.0 - x
    return 1.0 - (t * lin + cube * t * t * t)
def expect_vel(name, val, shift=5):
    i = min(255, val >> (shift - 1))
    return max(1, min(127, int(128 * asm_curve(name, (i + 0.5) / 256))))
VEL = bp.VEL_TABLE_ADDR + 3 * 256                        # the default curve (slot 3 = linear) is the one the translator uses in these tests
m = re.search(r'#define VEL_TABLES \(\(const u8 \*\)(0x[0-9A-Fa-f]+)\)', open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translate.c')).read())
check('the table address in translate.c and in build_patch.py agree', m is not None and int(m.group(1), 16) == bp.VEL_TABLE_ADDR, True)
check('the image carries the eight NI curves and the custom slot (a copy of linear) in the order of cfg.vel_curve',
      bytes(fw[bp.VEL_TABLE_ADDR - FL:][:9 * 256]) == b''.join(bp.vel_table(n) for n in bp.VEL_CURVES) + bp.vel_table('linear'), True)
check('image carries the default (linear) table at the table address: entry i = i >> 1',
      bytes(fw[VEL - FL:][:256]) == bytes(i >> 1 for i in range(256)), True)
VALS = [40, 300, 765, 1000, 2048, 3000, 4000, 4095]
tabs = {}
for name in bp.VEL_CURVES:
    t = tabs[name] = bp.vel_table(name)
    check(f'curve {name}: 256 entries, 0..127, non-decreasing, equal to the disassembly-derived formula',
          len(t) == 256 and max(t) <= 127 and all(t[i] <= t[i + 1] for i in range(255))
          and list(t) == [min(127, int(128 * asm_curve(name, (i + 0.5) / 256))) for i in range(256)], True)
    mp = session()
    mp.mem_write(VEL, t)
    got = [call(mp, r2([(k, 1, v)])) for k, v in enumerate(VALS)]
    want = [[note(1, PADNOTE[k], expect_vel(name, v))] for k, v in enumerate(VALS)]
    check(f'curve {name}: hits {VALS} -> velocities {[w[0][3] for w in want]}', got, want)
check('Linear is exactly value >> 5 (what the patch sent before curves existed)', all(tabs['linear'][min(255, v >> 4)] == v >> 5 for v in range(4096)), True)
check('NI default slot 3 = Linear: table equals i >> 1', tabs['linear'] == bytes(i >> 1 for i in range(256)), True)
check('Soft 3 >= Soft 2 >= Soft 1 >= Linear >= Hard 1 >= Hard 2 >= Hard 3 at every entry',
      all(tabs[a][i] >= tabs[b][i] for a, b in zip(bp.VEL_CURVES[:7], bp.VEL_CURVES[1:7]) for i in range(256)), True)
check('Soft n is the point mirror of Hard n (within one step): soft(i) + hard(255 - i) = 127 or 128',
      all(abs(tabs[f'soft{n}'][i] + tabs[f'hard{n}'][255 - i] - 127.5) <= 1 for n in (1, 2, 3) for i in range(256)), True)
check('Hard 1 at the half point matches NI: 0.7*0.5 + 0.3*0.5^3 = 0.3875 -> 49', tabs['hard1'][128], 49)
# gain in front of the curve (cfg.vel_shift at +71): 5 = full range, 6 halves, 4 doubles (saturating), 1 = index is the raw value
for shift, val, want_vel in ((6, 3000, 3000 >> 6), (4, 1000, 1000 >> 4), (4, 3000, 127), (5, 3000, 3000 >> 5)):
    ms = session(); ms.mem_write(0x0800CE00 + 71, bytes([shift]))
    check(f'vel_shift {shift} with the linear table: hit {val} -> {want_vel} (the old value >> {shift})', call(ms, r2([(12, 1, val)])), [note(1, PADNOTE[12], want_vel)])
mp = session(); mp.mem_write(VEL, tabs['fixed'])
check('type 0 (slow press) uses the curve too: fixed table -> 127', call(mp, r2([(15, 0, 40)])), [note(1, PADNOTE[15], 127)])
check('pressure ignores the curve: fixed table, 2000 -> still 62', call(mp, r2([(15, 4, 2000)])), [(0x0A, 0xA0, PADNOTE[15], 62)])
mp = session(); mp.mem_write(VEL, bytes(range(128)) * 2)
check('custom table (staircase 0..127 twice): hit 3000 -> table[187] = 59', call(mp, r2([(12, 1, 3000)])), [note(1, PADNOTE[12], 59)])
mp = session(); mp.mem_write(VEL, bytes([0]) * 256)
check('a table entry of 0 is raised to 1 (a Note On with velocity 0 would be a Note Off)', call(mp, r2([(12, 1, 3000)])), [note(1, PADNOTE[12], 1)])
mp = session(); mp.mem_write(VEL, bytes([0xFF]) * 256)
check('erased table (0xFF) is clamped to 127, never an invalid data byte', call(mp, r2([(12, 1, 3000)])), [note(1, PADNOTE[12], 127)])
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
