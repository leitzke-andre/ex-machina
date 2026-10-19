"""Our second half of the start-up (hal.c own_stage2) against the stock one: given the stock logo as its picture and the stock countdown,
it must send the same I2C transactions to the LED chips, the same command and data bytes to the display (with the same data / command
line and reset pulses on PB12), and leave the same RAM. In the firmware it is called with no picture (a blank screen, no NI logo) and a
short countdown; that difference is the only one.
Usage: test_hal_stage2.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call, I2CSlaveBus
from unicorn.arm_const import *

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

def run(fn, r0=None, r1=None):
    mu, p = machine(img, data)
    led = I2CSlaveBus('B', 6, 7, acks=(0x74, 0x77)); p.buses.append(led)
    call(mu, 0x08004DA8); call(mu, 0x08007590)                            # the stock pin set-up of the LED bus and SPI2
    mu.mem_write(0x20001028 + 0x5E1, bytes([80])); mu.mem_write(0x20001028 + 0x5E0, bytes([7])); mu.mem_write(0x20001028 + 0x2CC, bytes([0x55]))
    led.tx.clear(); spi = []; pb12 = []; orig = p.write
    def w(a, size, v):
        if a == 0x4000380C: spi.append((v & 0xFF, (p.regs[0x40010C0C] >> 14) & 1))
        orig(a, size, v)
        if a == 0x40010C0C and (not pb12 or pb12[-1] != (v >> 12) & 1): pb12.append((v >> 12) & 1)
    p.write = w
    if r0 is not None: mu.reg_write(UC_ARM_REG_R0, r0); mu.reg_write(UC_ARM_REG_R1, r1)
    call(mu, fn, limit=100_000_000); led.flush()
    return led.tx, spi, pb12, bytes(mu.mem_read(0x20000000, 0x1818)) + bytes(mu.mem_read(0x20001C18, 0x25E8))

st = run(0x08008BAC)
ow = run(SYM['own_stage2'], 0x08009592, 6000)
check(f'the LED chips get the same {len(st[0])} I2C transactions', ow[0], st[0])
check(f'the display gets the same {len(st[1])} bytes with the same data / command line', ow[1] == st[1], True, f'{len(ow[1])} vs {len(st[1])}')
check('the display reset pulse on PB12 is the same (high, low, high)', ow[2], st[2])
diff = [hex(0x20000000 + i if i < 0x1818 else 0x20001C18 + i - 0x1818) for i in range(len(st[3])) if st[3][i] != ow[3][i]]
check('the same RAM afterwards (apart from the stack)', diff[:8], [])
bl = run(SYM['own_stage2'], 0, 300)
check('with no picture: the display gets 512 zero data bytes (blank) instead of the logo, the countdown is 0.3 s',
      ([b for b, dc in bl[1] if dc == 1][:512] == [0] * 512, struct.unpack('<H', bl[3][0x102A:0x102C])[0]), (True, 300))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
