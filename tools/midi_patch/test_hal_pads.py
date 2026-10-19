"""Our pad averaging and evaluation (hal.c) against the stock routines they replace. Synthetic raw ADC streams (fast hits, slow presses,
holds with changing pressure, noise, many pads at once so that the event buffer fills) are fed scan by scan to both, with the per-pad
millisecond timers advancing like the stock SysTick does; after every scan the averages, the event buffer and its flags, and every pad's
state must be the same. The 16-segment curve is also checked on its own against the stock code for every 12-bit value.
Usage: test_hal_pads.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

ST = 0x20001028
RAW, ACC, AVG, NSCAN, TH, CNT, OFF, PEAK, ZERO = 0x20000718, 0x20000738, 0x20000758, 0x20000128, 0x2000014A, 0x20000CB8, 0x20000CC8, 0x20000C78, 0x20000C98
STOCK = (0x080033A4, 0x08003970); OWN = (SYM['own_adc_avg'], SYM['own_pad_eval'])

def state(mu, p):
    return (bytes(mu.mem_read(AVG, 32)), bytes(mu.mem_read(ACC, 32)), mu.mem_read(NSCAN, 1)[0], bytes(mu.mem_read(ST + 6, 1)),
            bytes(mu.mem_read(ST + 8, 128)), bytes(mu.mem_read(ST + 0x2CE, 1)), bytes(mu.mem_read(ST + 0x2EA, 63)),
            bytes(mu.mem_read(TH, 6)), bytes(mu.mem_read(CNT, 16)), bytes(mu.mem_read(PEAK, 32)), bytes(mu.mem_read(ZERO, 32)), p.regs[0x40012408], p.regs[0x40020004])

def story(seed, scans=3000):
    """Raw values per scan (a scan is about 0.2 ms apart in the stock loop; the timers advance 1 ms every 5 scans here)."""
    rng = random.Random(seed); pads = [None] * 16; out = []
    for t in range(scans):
        for i in range(16):
            if pads[i] is None and rng.random() < 0.002 * (4 if seed % 2 else 1):
                kind = rng.choice(('hit', 'hit', 'slow', 'hold'))
                peak = rng.randrange(1500, 4096)
                pads[i] = (kind, t, peak, {'hit': rng.randrange(10, 40), 'slow': rng.randrange(300, 900), 'hold': rng.randrange(800, 2500)}[kind])
        raw = []
        for i in range(16):
            v = rng.randrange(0, 200)                                          # the resting noise
            if pads[i]:
                kind, t0, peak, dur = pads[i]; age = t - t0
                if age >= dur: pads[i] = None
                elif kind == 'hit': v = int(peak * (age / (dur * 0.3) if age < dur * 0.3 else max(0.0, 1 - (age - dur * 0.3) / (dur * 0.7))))
                elif kind == 'slow': v = int(peak * min(1.0, age / (dur * 0.6)))
                else: v = int(peak * (0.6 + 0.4 * ((age // 97) % 5) / 4)) if age < dur - 20 else rng.randrange(0, 200)
                v = max(0, min(4095, v + rng.randrange(-30, 31)))
            raw.append(v)
        out.append(raw)
    return out

def run(fns, raws, offsets, threshold):
    mu, p = machine(img, data)
    mu.mem_write(OFF, bytes(offsets)); mu.mem_write(TH, struct.pack('<H', threshold))
    tr = []
    for k, raw in enumerate(raws):
        if k % 5 == 0:                                                         # SysTick: every pad's ms timer (capped at 255)
            for i in range(16):
                a = ST + 8 + 8 * i + 4; b = mu.mem_read(a, 1)[0]
                if b < 0xFF: mu.mem_write(a, bytes([b + 1]))
        mu.mem_write(RAW, struct.pack('<16H', *[v | (0xA000 if k % 7 == 0 else 0) for v in raw]))   # (bits above 12 must be ignored)
        call(mu, fns[0])
        if mu.mem_read(ST + 6, 1)[0]: mu.mem_write(ST + 0x2CE, b'\0'); call(mu, fns[1])
        tr.append(state(mu, p))
    return tr

bad, events = [], 0
for seed in range(6):
    rng = random.Random(100 + seed)
    offs = [rng.randrange(0, 200) for _ in range(16)]; th = rng.choice((0, 60, 120, 300))
    raws = story(seed)
    st, ow = run(STOCK, raws, offs, th), run(OWN, raws, offs, th)
    first = next((i for i, (a, b) in enumerate(zip(st, ow)) if a != b), None)
    if first is not None: bad.append((seed, first, [k for k in range(len(st[first])) if st[first][k] != ow[first][k]]))
    events += sum(1 for t in st if t[5] == b'\1')
check(f'6 stories of 3000 scans (hits, slow presses, holds, noise, offsets and thresholds): after every scan the same averages, events, '
      f'flags and pad states as the stock code ({events} scans with events)', bad, [])
# the curve on its own: one pad, every raw value, no offset / threshold, read the pressure report (type 4) after enough evaluations
diff = []
for fns in (STOCK, OWN):
    mu, p = machine(img, data); mu.mem_write(OFF, bytes(16)); mu.mem_write(TH, b'\0\0')
    vals = []
    for v in range(4096):
        mu.mem_write(AVG, struct.pack('<16H', *([v] + [0] * 15))); mu.mem_write(CNT, bytes([200]) + bytes(15)); mu.mem_write(ST + 8, b'\xff\xff')
        call(mu, fns[1]); vals.append(struct.unpack('<H', mu.mem_read(ST + 8, 2))[0])
    diff.append(vals)
check('the pressure curve: the same 12-bit value as the stock code for every raw value 0..4095', diff[1], diff[0])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
