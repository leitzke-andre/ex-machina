"""Our settings-page load (hal.c own_settings_load) against the stock routine, on the emulated flash (tools/emu/flash_model.py): pages A
(LED trims, pad offsets) and B (two blocks, contrast, format mark, device id, version) with realistic random content. Both must leave the
same RAM (trims, pad offsets, brightness / sensitivity blocks, contrast, the USB serial number descriptor, the page buffer) and the same
flash: page B rewritten (erase + program, read back) only when its content changes (here: the version byte), otherwise untouched.
Usage: test_hal_settings.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import devsim

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

def pages(seed, version):
    r = random.Random(seed)
    a = bytearray(b'\xff' * 0x400)
    a[:0xC6] = bytes(r.choice((r.randrange(0, 30), r.randrange(0x80, 0x9E))) for _ in range(0xC6))
    a[0x200:0x210] = bytes(r.randrange(60, 140) for _ in range(16))
    b = bytearray(b'\xff' * 0x400)
    b[:0x100] = bytes([1, 0, 0, 0x17, r.randrange(11), r.randrange(30, 100)]) + bytes(r.randrange(256) for _ in range(0xFA))
    b[0x100:0x200] = bytes(r.randrange(256) for _ in range(0x100))
    b[0x3E6] = r.choice((0x40, 0xF0)); b[0x3E8] = 4; b[0x3E9] = 4; b[0x3FE] = version; b[0x3FF] = 0
    return bytes(a), bytes(b)

def run(fn, a, b):
    d = devsim.Dev(img, data)
    d.mu.mem_write(0x0801F000, a); d.mu.mem_write(0x0801F800, b)
    d.flash.writable.append((0x0801F000, 0x0801FC00)); d.flash.log.clear()
    d.call(fn | 1)
    ram = bytes(d.mu.mem_read(0x20000000, 0x4200))
    return ram, bytes(d.mu.mem_read(0x0801F000, 0x800)), [e[0] for e in d.flash.log], d.flash.violations

for seed, version, what in ((1, 0x52, 'page B already up to date: nothing written'), (2, 0x51, 'an older version byte in page B: page B rewritten'), (3, 0x52, 'other content, up to date')):
    a, b = pages(seed, version)
    st, ow = run(0x080047F4, a, b), run(SYM['own_settings_load'], a, b)
    rd = [hex(0x20000000 + i) for i in range(len(st[0])) if st[0][i] != ow[0][i] and not (0x1818 <= i < 0x1C18 or 0x3E00 <= i < 0x4000)]   # (the stacks)
    check(f'{what}: the same RAM (trims, pad offsets, blocks, contrast, serial number, buffer)', rd[:6], [])
    check(f'{what}: the same flash afterwards and the same operations ({st[2].count("erase")} erases, {st[2].count("prog")} programs)', (ow[1] == st[1], ow[2], ow[3]), (True, st[2], []))
serial = bytes(run(SYM['own_settings_load'], *pages(1, 0x52))[0][0x48:0x48 + 18])
check('the serial number descriptor holds 8 hex digits of the device id (UTF-16)', (serial[0], serial[1], all(48 <= c <= 70 for c in serial[2::2]), set(serial[3::2])), (0x12, 3, True, {0}))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
