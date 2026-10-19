"""Our start-up of the touch-strip controller (hal.c own_strip_start) against the stock routine, with a controller model on the strip bus
whose application runs (its status read answers F5 F6): the same I2C transactions, the same pin waveform on SDA / SCL / PA15 (the reset
line), the same raw wake-up bytes, and the same fast bus timing afterwards.
Usage: test_hal_strip_start.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from periph import machine, call, I2CSlaveBus

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

def run(fn):
    mu, p = machine(img, data)
    status = [0, 0, 0xF5, 0xF6, 0, 0]
    bus = I2CSlaveBus('A', 10, 9, acks=(0x01, 0x38, 0x40), reader=lambda a, i: status[i] if i < 6 else 0xFF); p.buses.append(bus)
    call(mu, 0x0800508C)                                                  # the stock strip pin set-up (delay unit 0x12)
    wave = []
    def watch(per, port):
        if port != 'A': return
        odr = per.regs[0x4001080C]; st = ((odr >> 9) & 1, (odr >> 10) & 1, (odr >> 15) & 1)
        if not wave or wave[-1] != st: wave.append(st)
    p.watchers.append(watch)
    bus.tx.clear()
    call(mu, fn, limit=500_000_000); bus.flush()
    return bus.tx, wave, mu.mem_read(0x20001028 + 0xC7, 1)[0]

st, ow = run(0x08006E1C), run(SYM['own_strip_start'])
check(f'the same {len(st[0])} I2C transactions (configuration writes, the status read)', ow[0], st[0], st[0])
check(f'the same waveform of SDA / SCL / PA15 ({len(st[1])} changes: the reset pulses and the raw wake-up bytes included)', ow[1] == st[1], True)
check('the fast bus timing for the read cycles afterwards (delay unit 2)', (ow[2], st[2]), (2, 2))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
