"""The first seconds after power-up, with the REAL stock code: the stage-2 init, the SysTick handler, and the main-loop pieces (watchdog
kick = our tick hook, service routine) run in the emulator for the stock startup period (an LED fade-in that ends by clearing every
LED). Found on the real device (2026-10-17): the resting LEDs written at boot were wiped by that animation and only came back with the
first interaction; mmk3_tick() now writes them again once the startup countdown reaches 0.

Checks, comparing the patched image with the unpatched stock image run the same way:
  - during the animation the LED matrix is identical to stock (no flash of the resting state at power-up, the animation is not disturbed)
  - when the countdown reaches 0 the stock matrix is dark, the patched one shows the resting frame (buttons dim, pads blue)
  - the same holds with a shortened startup (--boot-ms) and for a LED the host sets during the animation
Usage: test_startup.py <patched.bin> <stock.bin> <data_init.bin>"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'emu'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from machine import *
import build_patch as bp

patched = open(sys.argv[1], 'rb').read(); stock = open(sys.argv[2], 'rb').read()[:bp.STOCK_LEN]; data = open(sys.argv[3], 'rb').read()
ST = 0x20001028; MATRIX, MLEN = 0x20000F06, 0x120
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)), flush=True)

def power_up(fw, is_patched, boot_ms=None, configure=False):
    patch = {bp.CFG_ADDR + 93: struct.pack('<H', boot_ms)} if boot_ms is not None else None      # cfg.boot_ms, in flash before the boot hook copies the config
    mu, usb = boot(fw, data, patched=is_patched, configure=configure, flash_patch=patch)
    usb.run((bl_target(fw, 0x08008CFC) | 1) if is_patched else 0x08008BAD, limit=20_000_000)    # stage-2 init (+ our boot hook)
    tick = (bl_target(fw, 0x08008D06) | 1) if is_patched else 0x08005415                        # the main loop's first call per iteration
    return mu, usb, tick

def iteration(mu, usb, tick):
    mu.mem_write(ST + 0x88, struct.pack('<H', 1)); mu.mem_write(ST + 0xc2, bytes([5]))          # keep the button scan and the strip I2C out of the way
    usb.run(tick); usb.run(0x08004621)

def countdown(mu): return struct.unpack('<H', mu.mem_read(ST + 2, 2))[0]
def matrix(mu): return bytes(mu.mem_read(MATRIX, MLEN))

def run_startup(fw, is_patched, boot_ms=None, host_led=None, max_ms=7000):
    """Returns (matrix per millisecond until the countdown is 0, the matrix after a few more iterations, ms at which the startup ended)."""
    mu, usb, tick = power_up(fw, is_patched, boot_ms, configure=host_led is not None)
    hist = []
    for ms in range(max_ms):
        usb.run(0x08007ed5); usb.run(0x08007ed5)                                                  # SysTick: 1 ms
        for _ in range(3): iteration(mu, usb, tick)
        hist.append(matrix(mu))
        if host_led and ms == host_led[0]: usb.bulk_out(1, bytes([0x09, 0x91, host_led[1], host_led[2]]))
        if countdown(mu) == 0: break
    else:
        raise AssertionError('the startup countdown did not reach 0')
    for _ in range(6): iteration(mu, usb, tick)
    return hist, matrix(mu), len(hist)

# the frame a quiet device shows: stage-2 init, then the frame applied directly (no animation)
mu, usb, tick = power_up(patched, True)
mu.mem_write(ST + 2, b'\0\0')
for _ in range(6): iteration(mu, usb, tick)
RESTING = matrix(mu)
lit = sum(1 for b in RESTING if b)
check('reference: the resting frame lights LED matrix cells (39 buttons + 16 pads, some of them several cells each)', lit > 55, lit)

sh, sfinal, sms = run_startup(stock, False)
ph, pfinal, pms = run_startup(patched, True)
check(f'stock 6000 ms countdown: the startup ends at the same time as on stock ({sms} ms in the emulator)', pms == sms, (pms, sms))
check(f'the LED matrix is identical to stock in every millisecond of the animation ({sms - 1} snapshots until its last millisecond): no flash of the resting state at power-up',
      ph[:-1] == sh[:-1], next((i for i in range(min(len(ph), len(sh)) - 1) if ph[i] != sh[i]), None))
check('stock has every LED dark when the startup is over (the finding on the real device)', sum(1 for b in sfinal if b) == 0, sum(1 for b in sfinal if b))
check('the patched device shows the resting frame once the startup is over', pfinal == RESTING, sum(1 for i in range(MLEN) if pfinal[i] != RESTING[i]))

# a shortened startup (--boot-ms 300)
ph3, pfinal3, pms3 = run_startup(patched, True, boot_ms=300)
check(f'--boot-ms 300: the startup ends after {pms3} ms and the resting frame is shown', pms3 <= 300 and pfinal3 == RESTING, (pms3, sum(1 for i in range(MLEN) if pfinal3[i] != RESTING[i])))

# a LED the host sets during the animation (LED 5, code 0x7F) is lit afterwards, together with the resting frame
ph4, pfinal4, pms4 = run_startup(patched, True, host_led=(400, 5, 0x7F))
mu2, usb2, tick2 = power_up(patched, True, configure=True)
usb2.bulk_out(1, bytes([0x09, 0x91, 5, 0x7F]))
mu2.mem_write(ST + 2, b'\0\0')
for _ in range(6): iteration(mu2, usb2, tick2)
REF_HOST = matrix(mu2)
check('a LED the host sets during the animation is shown after it, together with the resting frame', pfinal4 == REF_HOST and REF_HOST != RESTING,
      (pfinal4 == REF_HOST, REF_HOST != RESTING))

print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
