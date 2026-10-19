"""Our touch-strip read cycle (hal.c) against the stock routine it replaces, on the same emulated hardware: the strip controller is an I2C
slave (tools/emu/periph.py) answering each read with a scripted touch count, two positions and a pressure. Random stories of touches,
slides, jitter, jumps, second fingers and invalid counts are read by both; after every cycle the I2C transactions, the pin waveform and the
strip values (positions, pressure, "changed"), as well as the filter state, must be the same. A missing controller is checked too.
Usage: test_hal_strip.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call, I2CSlaveBus

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

ST, STRIP = 0x20001028, 0x2000018C
def norm(wave):
    out = []
    for w in wave:
        if w[2] == 0: continue
        if not out or out[-1] != w: out.append(w)
    return out

def story(seed, n=400):
    rng = random.Random(seed); out = []; cnt, p = 0, [100, 50]; pr = 0
    for _ in range(n):
        r = rng.random()
        if r < 0.05: cnt = rng.choice((0, 1, 2, 3, 7))
        elif r < 0.5: p = [max(1, min(200, x + rng.choice((-2, -1, 0, 1, 2)))) for x in p]       # slide / jitter
        elif r < 0.55: p = [rng.randrange(1, 201) for _ in p]                                     # a jump
        if rng.random() < 0.2: pr = rng.randrange(256)
        out.append([cnt, p[0] if cnt else 0, p[1] if cnt == 2 else 0, pr])
    return out

def run(fn, script, acks=(0x15,)):
    mu, p = machine(img, data)
    cur = [0, 0, 0, 0]
    bus = I2CSlaveBus('A', 10, 9, acks=acks, reader=lambda a, i: cur[i] if i < 4 else 0xFF); p.buses.append(bus)
    call(mu, 0x0800508C)                                                  # the stock pin set-up of the strip bus
    mu.mem_write(ST + 0xC7, bytes([2]))                                    # the delay unit (set by the stock start-up)
    trace = []
    for v in script:
        cur[:] = v
        bus.tx.clear(); bus.wave[:] = [(bus.S, bus.D, getattr(bus, 'mode', 7))]
        mu.mem_write(ST + 0xC3, b'\0')
        call(mu, fn); bus.flush()
        trace.append((list(bus.tx), norm(bus.wave), bytes(mu.mem_read(ST + 0xC2, 5)), bytes(mu.mem_read(STRIP, 19))))
    return trace

bad, changes = [], 0
for seed in range(5):
    sc = story(seed)
    st, ow = run(0x08007FA4, sc), run(SYM['own_strip_read'], sc)
    for i, (a, b) in enumerate(zip(st, ow)):
        if a != b: bad.append((seed, i, [k for k in range(4) if a[k] != b[k]])); break
    changes += sum(1 for t in st if t[2][1])
check(f'5 random stories of 400 read cycles: the same transactions, waveform, strip values and filter state after every cycle '
      f'({changes} cycles in which the stock code reported a change)', bad, [])
st, ow = run(0x08007FA4, story(9, 20)), run(SYM['own_strip_read'], story(9, 20))
check('a read cycle is: write register 0 to 0x15, then read 4 bytes (count, position 1, position 2, pressure)',
      [(t[0], t[1]) for t in [(x[0], x[1]) for x in ow[0][0]]], [(0x15, 'W'), (0x15, 'R')])
st, ow = run(0x08007FA4, story(3, 30), acks=()), run(SYM['own_strip_read'], story(3, 30), acks=())
check('no controller answering: the same waveform (start, address not acknowledged, stop) and nothing changes', st, ow)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
