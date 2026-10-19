"""Our display sender (hal.c) against the stock routine it replaces, on the same emulated hardware (tools/emu/periph.py): for every value of
the chunk counter (including the "changed again" values with bit 7), from different data pointers and with a random picture, both must put
the same bytes on SPI2 with the same data / command line, and leave the same counter, gap and data pointer.
Usage: test_hal_disp.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
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

ST = 0x20001028; FB, CNT, GAP, PTR = ST + 0xCA, ST + 0xC8, ST + 0xC9, 0x20000188
STOCK, OWN = 0x080068B0, SYM['own_disp_send']
rng = random.Random(3)
picture = bytes(rng.randrange(256) for _ in range(512))

def one(fn, counter, ptr):
    mu, p = machine(img, data)
    call(mu, 0x08007590)                                                  # the stock SPI2 / pin set-up
    mu.mem_write(FB, picture); mu.mem_write(CNT, bytes([counter])); mu.mem_write(GAP, b'\0'); mu.mem_write(PTR, struct.pack('<I', ptr))
    out = []; orig = p.write
    def w(a, size, v):
        if a == 0x4000380C: out.append((v & 0xFF, (p.regs[0x40010C0C] >> 14) & 1))
        orig(a, size, v)
    p.write = w
    call(mu, fn)
    return out, (mu.mem_read(CNT, 1)[0], mu.mem_read(GAP, 1)[0], struct.unpack('<I', mu.mem_read(PTR, 4))[0], (p.regs[0x40010C0C] >> 14) & 1)

bad, sent = [], 0
for counter in range(256):
    ptr = FB + 64 * rng.randrange(8)
    s, o = one(STOCK, counter, ptr), one(OWN, counter, ptr)
    if s != o: bad.append((counter, s[1], o[1], len(s[0]), len(o[0])))
    sent += len(s[0])
check(f'all 256 counter values: the same {sent} SPI bytes with the same data / command line, the same counter, gap, data pointer and D/C level after', bad[:5], [])
seq, frame = [], b''
mu_counter = 8
for c in range(8, 0, -1):
    s = one(OWN, c, FB + 64 * (8 - c - 1) if c < 8 else FB)
    seq.append(([b for b, dc in s[0] if dc == 0], s[1][0]))
    frame += bytes(b for b, dc in s[0][3:])
check('a picture is 8 calls: page 0 left / right, page 1 ... page 3 right (commands B0+page, 10|x>>4, x&15), the counter 8 -> 0',
      seq, [([0xB0 + (k >> 1), 0x10 | ((k & 1) * 4), 0], 7 - k) for k in range(8)])
check('... the data is the framebuffer, inverted, in order', frame, bytes(0xFF - b for b in picture))
s = one(OWN, 0x89, FB + 7 * 64)
check('a counter marked "changed again" whose chunk number (counter mod 17) is 1 (0x89): the last chunk, then it starts over at 8', s[1][0], 8)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
