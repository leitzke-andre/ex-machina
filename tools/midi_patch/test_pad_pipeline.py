"""Whole-chain test with synthetic analogue input: pad force -> the stock ADC-side processing (linearisation,
peak detection, event state machine) -> real HID report builder -> our translator -> stock EP1 sender ->
USB bulk IN, all running as firmware code in the emulator. Prints the raw-ADC-peak -> MIDI-velocity
response and the note timing.

Usage: test_pad_pipeline.py <patched.bin> <data_init.bin>"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'emu'))
from machine import *
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
PAD1 = fw[bp.CFG_ADDR - 0x08003000 + 5 + 12]       # cfg.pad_note[12]: report index 12 = printed pad 1
ST = 0x20001028
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

def fresh():
    mu, usb = boot(fw, data)
    # stock defaults when the settings page is blank: sensitivity 80 -> threshold (100-80)*6, pad offsets 100
    mu.mem_write(ST + 0x5e1, bytes([80])); usb.run(0x080046b9)
    mu.mem_write(0x20000cc8, bytes([100] * 16))
    return mu, usb

def drain(usb):
    out = []
    while True:
        p = usb.bulk_in(1)
        if p is None: break
        out += [tuple(p[i:i + 4]) for i in range(0, len(p), 4)]
    return out

def strike(mu, usb, profile, pad=12, settle_ms=60):
    """profile: list of raw ADC values, one per millisecond. Returns [(ms, packet)]."""
    events = []
    ms = 0
    for raw in profile + [0] * settle_ms:
        usb.run(0x08007ed5); usb.run(0x08007ed5)                       # two real SysTick handler runs = 1 ms
        if ms % 2 == 0:                                                # averaged ADC refresh (~every 1.7 ms)
            mu.mem_write(0x20000758 + 2 * pad, struct.pack('<H', raw))
            mu.mem_write(ST + 6, bytes([1]))                           # "ADC averages ready"
        for _ in range(5):                                             # main-loop passes per ms
            mu.mem_write(ST + 0x88, struct.pack('<H', 1)); mu.mem_write(ST + 0xc2, bytes([5]))
            usb.run(0x08004621)                                        # service routine (reports, sender)
            usb.run(0x080042a1)                                        # mode-0 scan handler (pad processing)
        for pkt in drain(usb): events.append((ms, pkt))
        ms += 1
    return events

def curve(peak, rise_ms, hold_ms, fall_ms):
    up = [int(peak * (k + 1) / rise_ms) for k in range(rise_ms)]
    return up + [peak] * hold_ms + [int(peak * (1 - (k + 1) / fall_ms)) for k in range(fall_ms)]

print('raw ADC peak -> first Note On (velocity, ms after strike start), Note Off at, pressure messages')
results = []
for peak in (1500, 2000, 2500, 3000, 3500, 3900):
    mu, usb = fresh()
    ev = strike(mu, usb, curve(peak, 4, 6, 40))
    ons = [(t, p) for t, p in ev if p[0] == 9]; offs = [(t, p) for t, p in ev if p[0] == 8]; press = [p for t, p in ev if p[0] == 0xA]
    v = ons[0][1][3] if ons else None
    print(f'  {peak:5d} -> ' + (f'vel {v:3d} at {ons[0][0]:2d} ms' if ons else 'no note-on') + (f', note off at {offs[0][0]} ms' if offs else ', NO note off') + f', {len(press)} pressure msgs')
    results.append((peak, ons, offs, press))
    if peak >= 3000:
        check(f'peak {peak}: exactly one Note On and one Note Off on note {PAD1} (pad 1)', len(ons) == 1 and len(offs) == 1 and ons[0][1][2] == PAD1 and offs[0][1][2] == PAD1, ev)
    else:   # below the stock hit threshold at the default sensitivity (80): silent, never a dangling note
        check(f'peak {peak}: below the default hit threshold -> silent or a balanced on/off pair', len(ons) == len(offs) and len(ons) <= 1, ev)
    check(f'peak {peak}: no stuck note afterwards (translator held mask empty)', struct.unpack('<H', mu.mem_read(bp.STATE_ADDR + 4, 2))[0] == 0)
vels = [r[1][0][1][3] for r in results if r[1]]
print('  (hit threshold at the default sensitivity 80 lies near raw ADC ~2700-3000; real pad ADC ranges are unknown until measured)')
check('velocity grows monotonically with force and spans a useful range', vels == sorted(vels) and vels[-1] - vels[0] >= 40, vels)
check('harder strikes are not slower than 15 ms', all(r[1][0][0] <= 15 for r in results if r[1]), [(r[0], r[1][0][0]) for r in results if r[1]])

# a light tap below the hit threshold must stay silent
mu, usb = fresh()
ev = strike(mu, usb, curve(1100, 4, 6, 30))
check('a very light touch (raw 1100) produces no Note On', not [1 for t, p in ev if p[0] == 9], ev)

# slow press: value keeps rising -> press-on style note, then pressure changes, then release
mu, usb = fresh()
slow = [int(1500 + 25 * k) for k in range(80)] + [3500] * 10 + [3500 + 14 * k for k in range(30)] + curve(3900, 1, 1, 30)[1:]
ev = strike(mu, usb, slow, settle_ms=80)
ons = [p for t, p in ev if p[0] == 9]; offs = [p for t, p in ev if p[0] == 8]
check('slow press: one Note On, pressure messages while held, one Note Off on release', len(ons) == 1 and len(offs) == 1 and any(p[0] == 0xA for t, p in ev), [(t, p) for t, p in ev][:12])
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
