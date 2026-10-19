"""Our LED colour layer (hal.c) against the stock routine it replaces: every LED index 0..79 with every colour code 0..127, with random
per-cell trims and random previous matrix contents, must leave the same LED-control bytes and PWM values. The tables come from the image
(copied from the stock image by build_patch.py), so this also checks that the copy is complete.
Usage: test_hal_colour.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call
from unicorn.arm_const import *

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

TRIM, MATRIX = 0x20000E1C, 0x20000EE2
mu, p = machine(img, data)
def run(fn, idx, code, trim, prev):
    mu.mem_write(TRIM, trim); mu.mem_write(MATRIX, prev); mu.mem_write(0x20001C18, b'\0' * 4)
    mu.reg_write(UC_ARM_REG_R0, idx); mu.reg_write(UC_ARM_REG_R1, code); mu.reg_write(UC_ARM_REG_R2, 0); mu.reg_write(UC_ARM_REG_R3, 0)
    call(mu, fn)
    return bytes(mu.mem_read(MATRIX, 0x144))
rng = random.Random(5); bad = []; lit = 0
for trial in range(3):
    trim = bytes(rng.choice((0, rng.randrange(0, 40), rng.randrange(0x80, 0xA8))) for _ in range(0xC6))
    for idx in range(80):
        for code in range(128):
            prev = bytes(rng.randrange(256) for _ in range(0x144))
            a, b = run(0x08005490, idx, code, trim, prev), run(SYM['own_led_colour'], idx, code, trim, prev)
            if a != b and len(bad) < 3: bad.append((trial, idx, code))
            lit += a != prev
check(f'3 x 80 LEDs x 128 colour codes with random trims and previous contents: the same control bits and PWM values as the stock code '
      f'({lit} of them changed the matrix)', bad, [])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
