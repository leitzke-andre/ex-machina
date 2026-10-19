"""Our LED driver (hal.c) against the stock routines it replaces, on the same emulated hardware (tools/emu/periph.py: GPIO, bit-band, a
bit-banged I2C bus with the two LED chips as slaves): the chip start-up and the refresh steps must produce the same I2C transactions, the
same pin waveform (SCL, SDA and SDA's mode, change by change) and leave the same RAM behind, for random LED matrices, every brightness
level, unchanged blocks, and a chip that does not answer.
Usage: test_hal_led.py <patched.bin> <data_init.bin>   (the symbols come from <patched.bin>.syms.json, written by build_patch.py)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call, I2CSlaveBus

img = open(sys.argv[1], 'rb').read()
data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

STOCK_INIT, STOCK_REFRESH, STOCK_PINS = 0x08005EF4, 0x08006028, 0x08004DA8
OWN_INIT, OWN_REFRESH = SYM['own_led_init'], SYM['own_led_refresh']
MATRIX, SHADOW, BRI, SHOFF, LEVELS, STEP = 0x20000EE2, 0x20000CD8, 0x20000150, 0x20000152, 0x2000017C, 0x20001028 + 0xBC

def setup(acks=(0x74, 0x77)):
    mu, p = machine(img, data)
    bus = I2CSlaveBus('B', 6, 7, acks=acks); p.buses.append(bus)
    call(mu, STOCK_PINS)                                                  # the stock pin set-up (stays stock in this stage)
    bus.tx.clear(); bus.wave[:] = [(bus.S, bus.D, getattr(bus, 'mode', 3))]   # the state before: the first change counts from there
    return mu, bus

def norm(wave):
    """The waveform without the stock code's transient 'mode 0' between clearing and setting SDA's mode bits (two register writes where ours
    makes one; for a cycle the pin is an analog input, which drives nothing), with repeats collapsed."""
    out = []
    for w in wave:
        if w[2] == 0: continue
        if not out or out[-1] != w: out.append(w)
    return out

def run(fn, mu, bus):
    call(mu, fn); bus.flush()
    return list(bus.tx), norm(bus.wave)

def ram(mu): return bytes(mu.mem_read(SHADOW, 0x144)) + bytes(mu.mem_read(SHOFF, 2)) + bytes(mu.mem_read(STEP, 1))

# ---- the chip start-up ---------------------------------------------------------------------------------------------------------------------------------
mu, bus = setup(); st = run(STOCK_INIT, mu, bus)
mu2, bus2 = setup(); ow = run(OWN_INIT, mu2, bus2)
check(f'start-up: the same {len(st[0])} I2C transactions as the stock code (function page, frame 0 cleared, normal operation, both chips)', ow[0], st[0])
check(f'start-up: the same pin waveform ({len(st[1])} changes of SCL / SDA / SDA mode, apart from the stock code\'s one-cycle mode-0 transients)', ow[1] == st[1], True)
mu, bus = setup(acks=(0x74,)); st = run(STOCK_INIT, mu, bus)
mu2, bus2 = setup(acks=(0x74,)); ow = run(OWN_INIT, mu2, bus2)
check('start-up with chip 0x77 missing (no acknowledge): the same transactions and waveform (each write gives up after the address)', (ow[0], ow[1] == st[1]), (st[0], True))

# ---- the refresh ---------------------------------------------------------------------------------------------------------------------------------------
rng = random.Random(7)
def refresh_all(fn, mu, bus, start=10):
    mu.mem_write(STEP, bytes([start]))
    out = []
    while mu.mem_read(STEP, 1)[0]:
        bus.tx.clear(); bus.wave[:] = [(bus.S, bus.D, bus.mode)]; call(mu, fn); bus.flush(); out.append((list(bus.tx), norm(bus.wave)))
    return out

def scenario(matrix, bri, shadow=None, start=10, acks=(0x74, 0x77)):
    res = []
    for fn in (STOCK_REFRESH, OWN_REFRESH):
        mu, bus = setup(acks)
        mu.mem_write(MATRIX, matrix); mu.mem_write(BRI, bytes([bri]))
        if shadow is not None: mu.mem_write(SHADOW, shadow)
        steps = refresh_all(fn, mu, bus, start)
        res.append((steps, ram(mu)))
    return res

levels = list(open(sys.argv[2], 'rb').read()[0x17C:0x17C + 11])
bad = []
for trial in range(12):
    m = bytes(rng.randrange(256) for _ in range(0x144)); bri = trial % 11
    (st_steps, st_ram), (ow_steps, ow_ram) = scenario(m, bri)
    if [s[0] for s in ow_steps] != [s[0] for s in st_steps]: bad.append((trial, 'tx'))
    if [s[1] for s in ow_steps] != [s[1] for s in st_steps]: bad.append((trial, 'wave'))
    if ow_ram != st_ram: bad.append((trial, 'ram'))
check(f'refresh of 12 random matrices at brightness levels 0-10 (percent {levels}): every step sends the same transactions with the same waveform '
      f'and leaves the same shadow, offset and step counter', bad, [])
(st_steps, st_ram), (ow_steps, ow_ram) = scenario(bytes(range(1, 256)) + bytes(range(1, 0x46)), 10)
check('... a refresh walks 10 steps: control registers of 0x74, of 0x77, then PWM blocks of 36 alternating 0x74 / 0x77',
      [(t[0][0][0], t[0][0][2][0], len(t[0][0][2])) for t in st_steps if t[0]], [(0x74, 0, 19), (0x77, 0, 19)] + [(0x74 if k % 2 == 0 else 0x77, 0x24 + 0x24 * (k // 2), 37) for k in range(8)])
m = bytes(rng.randrange(256) for _ in range(0x144))
for bri in (3, 10):
    mu, bus = setup(); mu.mem_write(MATRIX, m); mu.mem_write(BRI, bytes([bri])); refresh_all(STOCK_REFRESH, mu, bus); shadow = bytes(mu.mem_read(SHADOW, 0x144))
    (st_steps, st_ram), (ow_steps, ow_ram) = scenario(m, bri, shadow)
    check(f'nothing changed (brightness {bri}): neither sends anything, both walk the steps', ([t[0] for t in ow_steps], ow_ram), ([t[0] for t in st_steps], st_ram))
shadow = bytearray(shadow); shadow[0x24 + 5] ^= 0x55; shadow[0x144 - 1] ^= 1
(st_steps, st_ram), (ow_steps, ow_ram) = scenario(m, 10, bytes(shadow))
check('one byte different in the first PWM block of 0x74 and in the last of 0x77: only those two blocks are sent, the same way',
      ([t[0] for t in ow_steps], ow_ram, sum(1 for t in st_steps if t[0])), ([t[0] for t in st_steps], st_ram, 2))
for start in (11, 12, 1):
    (st_steps, st_ram), (ow_steps, ow_ram) = scenario(m, 5, None, start)
    check(f'a step counter outside 2..10 ({start}): the last PWM block of 0x77, scaled only for {start} <= 8, the same as the stock code',
          ([t[0] for t in ow_steps], ow_ram), ([t[0] for t in st_steps], st_ram))
(st_steps, st_ram), (ow_steps, ow_ram) = scenario(m, 10, None, 10, acks=(0x74,))
check('chip 0x77 does not answer: the same transactions (0x74 only) and waveform, the shadow updated the same way',
      ([t[0] for t in ow_steps], [t[1] for t in ow_steps] == [t[1] for t in st_steps], ow_ram), ([t[0] for t in st_steps], True, st_ram))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
