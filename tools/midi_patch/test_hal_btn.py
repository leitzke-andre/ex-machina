"""Our button matrix and encoder scan (hal.c) against the stock routines they replace, on the same emulated hardware: a key matrix model
(the 5 column lines on GPIOB, a pressed key pulls its row on PC8..PC15 low while its column is driven low) and an encoder on PC6 / PC7.
Random presses, releases, bounces and turns are fed to both; after every scan step the button bytes, the encoder event, the scan block and
the column lines must be the same.
Usage: test_hal_btn.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu')); sys.path.insert(0, HERE)
from periph import machine, call
from unicorn.arm_const import UC_ARM_REG_R0
import build_patch as bp
import mmk3_config as mc

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

ST, BTN = 0x20001028, 0x20000129
COLS = bp.BTN_COLUMNS
class Board:
    def __init__(self):
        self.pressed, self.enc = set(), 3                                  # matrix positions (column, row) held; encoder pins (PC7 << 1 | PC6)
    def port_c(self, p):
        odr = p.regs[0x40010C0C]
        rows = 0xFF
        for c, r in self.pressed:
            if not odr & COLS[c]: rows &= ~(1 << r)                        # its column is driven low: the key pulls the row low
        return (rows << 8) | ((self.enc & 3) << 6) | 0x3F

def machine_with(board):
    mu, p = machine(img, data)
    call(mu, 0x080076D4)                                                  # the stock pin set-up of the matrix
    p.inputs['C'] = board.port_c
    return mu, p

def step(mu, scan, ev):
    call(mu, scan); f = mu.reg_read(UC_ARM_REG_R0) & 0xFF
    if f: mu.reg_write(UC_ARM_REG_R0, f); mu.reg_write(13, 0x20001C18); call_with_r0(mu, ev, f)
    return f

def call_with_r0(mu, pc, r0):
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR
    from unicorn import UcError
    mu.reg_write(UC_ARM_REG_R0, r0); mu.reg_write(UC_ARM_REG_SP, 0x20001C18); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(pc | 1, 0x08000000, count=1_000_000)
    except UcError:
        if mu.reg_read(15) != 0x08000000: raise

def snapshot(mu, p):
    return (bytes(mu.mem_read(ST + 0x8A, 1 + 41)), mu.mem_read(ST + 0xBA, 1)[0], bytes(mu.mem_read(BTN, 0x1D)), p.regs[0x40010C0C] & 0xC1C)

def run(seed, n=3000):
    rng = random.Random(seed)
    events = []
    b = Board()
    for i in range(n):                                                     # the same input story for both
        if rng.random() < 0.02:
            k = (rng.randrange(5), rng.randrange(8))
            b.pressed.symmetric_difference_update({k})
        if rng.random() < 0.01: b.enc = [0, 1, 3, 2][([0, 1, 3, 2].index(b.enc) + rng.choice((1, -1))) % 4]
        if rng.random() < 0.003: b.enc ^= rng.choice((1, 2))               # a bounce on one pin
        events.append((frozenset(b.pressed), b.enc))
    traces = []
    for scan, ev in ((0x08007714, 0x080077E8), (SYM['own_btn_scan'], SYM['own_btn_eval'])):
        bd = Board(); mu, p = machine_with(bd)
        tr = []
        for pressed, enc in events:
            bd.pressed, bd.enc = set(pressed), enc
            mu.mem_write(ST + 0xBA, b'\0')
            f = step(mu, scan, ev)
            tr.append((f,) + snapshot(mu, p))
        traces.append(tr)
    return traces

bad, presses, turns = [], 0, 0
for seed in range(6):
    st, ow = run(seed)
    presses += sum(1 for a, b in zip(st, st[1:]) if a[1][1:] != b[1][1:]); turns += sum(1 for t in st if t[2])
    first = next((i for i, (a, b) in enumerate(zip(st, ow)) if a != b), None)
    if first is not None: bad.append((seed, first, st[first][:2], ow[first][:2]))
check('6 random stories of 3000 scan steps (presses, releases, encoder turns and bounces): after every step the same flags, button bytes, '
      'encoder event, scan block and column lines as the stock scan', bad, [])
check(f'... the stories exercise both: {presses} changes of the stock button bytes, {turns} stock encoder steps', presses > 100 and turns > 50, True)
# a sanity check of the wiring through ours: one key at a time ends up as its own button byte
names = []
for c in range(5):
    for r in range(8):
        bd = Board(); mu, p = machine_with(bd); bd.pressed = {(c, r)}
        for _ in range(60): mu.mem_write(ST + 0x8A, b'\0'); step(mu, SYM['own_btn_scan'], SYM['own_btn_eval'])
        held = [i for i in range(41) if mu.mem_read(ST + 0x8B + i, 1)[0]]
        names.append(held)
check('each of the 40 matrix positions held alone reports exactly its own button (ids 0..39, BTN_MATRIX)', names, [[i] for i in bp.BTN_MATRIX])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
