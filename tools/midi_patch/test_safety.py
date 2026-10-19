"""Stage 0 of docs/clean-firmware-plan.md in the emulator: the crash-loop guard (watchdog started at the patch's first instruction, three
watchdog resets in a row put the device into DFU mode), the Shift + Stop + Erase gesture, the DFU request written into the bootloader's
handshake page, the HANG test command, the raw pad capture and the PEEK whitelist for the peripheral registers.
Usage: test_safety.py <patched.bin> <data_init.bin>"""
import os, struct, sys
from unicorn.arm_const import UC_ARM_REG_PC

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import mmk3_config as mc
import devsim
from devsim import report1
from dispsim import reference, Screen, MS16

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

RCC_CSR, IWDG, AIRCR, GUARD, HANDSHAKE = 0x40021024, 0x40003000, 0xE000ED0C, 0x20004FF0, 0x0801FC00
POR, PIN, SFT, IWDGF, RMVF = 1 << 27, 1 << 26, 1 << 28, 1 << 29, 1 << 24
REQUEST, AFTER_FLASH = bytes.fromhex('555aa5aa59953aa3'), bytes.fromhex('59953aa3555aa5aa')
B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}
rd32 = lambda d, a: struct.unpack('<I', bytes(d.mu.mem_read(a, 4)))[0]
guard = lambda d: struct.unpack('<4I', bytes(d.mu.mem_read(GUARD, 16)))

def boot(csr, ram=None):
    """A boot with RCC_CSR = csr; ram: the guard words a previous boot left (they survive a reset), None = power-up garbage."""
    def pre(d):
        d.mu.mem_write(RCC_CSR, struct.pack('<I', csr))
        d.mu.mem_write(HANDSHAKE, AFTER_FLASH + b'\xff' * 8)                 # what the bootloader leaves after a flash
        d.mu.mem_write(GUARD, ram if ram is not None else bytes.fromhex('87004472a546b7f83793a9da1160f1d4'))
        d.flash.writable.append((HANDSHAKE, HANDSHAKE + 0x400))              # (the one page outside the patch's own that it may write)
        d.mu.mem_write(AIRCR, b'\0' * 4)
    return devsim.Dev(fw, data, pre=pre)

def dfu_requested(d): return bytes(d.mu.mem_read(HANDSHAKE, 16)) == REQUEST + b'\xff' * 8 and rd32(d, AIRCR) == 0x05FA0004

# ---- the guard -------------------------------------------------------------------------------------------------------------------------------------
d = boot(POR | PIN)
check('power-up: count 0, the boot cause kept for diagnostics, the reset flags cleared (RMVF), no DFU request',
      (guard(d)[1], guard(d)[3], rd32(d, RCC_CSR) & RMVF != 0, dfu_requested(d)), (0, POR | PIN, True, False))
check('the watchdog is started at the first instruction: about 26 s (prescaler /256, reload 4095), the last key written is 0xCCCC (start)',
      (rd32(d, IWDG + 4), rd32(d, IWDG + 8), rd32(d, IWDG) & 0xFFFF), (6, 0xFFF, 0xCCCC))
ram = bytes(d.mu.mem_read(GUARD, 16))
counts = []
for k in range(2):
    d = boot(IWDGF | PIN, ram); ram = bytes(d.mu.mem_read(GUARD, 16)); counts.append((guard(d)[1], dfu_requested(d)))
check('two watchdog resets in a row: count 1, 2, still starting normally', counts, [(1, False), (2, False)])
d = boot(IWDGF | PIN, ram)
check('the third: the DFU request is in the handshake page (rest of the page erased), the chip is reset (AIRCR = 05FA0004)', dfu_requested(d))
check('... and the count starts over (the next boot after the flash is a fresh one)', guard(d)[1], 0)
check('... only the handshake page was written', (d.flash.violations, sorted(set(d.flash.erases))), ([], [HANDSHAKE]))
d = boot(IWDGF | PIN, struct.pack('<4I', 0x47524431, 2, 0xFFFFFFFD, 0))
check('two watchdog resets, then a power-up: the count starts over', (boot(POR | PIN, bytes(d.mu.mem_read(GUARD, 16))).mu.mem_read(GUARD + 4, 4) == b'\0' * 4), True)
d = boot(SFT, struct.pack('<4I', 0x47524431, 2, 0xFFFFFFFD, 0))
check('a software reset (the bootloader after a flash) also starts it over', guard(d)[1], 0)
d = boot(IWDGF, struct.pack('<4I', 0x47524431, 2, 0x12345678, 0))
check('a count whose check word is wrong (power-up garbage) is not trusted: a watchdog reset counts as the first', (guard(d)[1], dfu_requested(d)), (1, False))

# ---- healthy: 10 s of normal running clear the count ----------------------------------------------------------------------------------------------
d = boot(IWDGF, struct.pack('<4I', 0x47524431, 1, 0xFFFFFFFE, 0)); d.translate(report1()); d.mu.mem_write(MS16, struct.pack('<H', 5000)); d.start()
check('after a second watchdog reset the count is 2', guard(d)[1], 2)
sc = Screen(d); sc.run(300, 30)                                              # 9 s
check('still 2 after 9 s of running', guard(d)[1], 2)
sc.run(60, 30)
check('0 after 10 s: a later crash starts a new count', (guard(d)[1], guard(d)[2]), (0, 0xFFFFFFFF))

# ---- the gesture ---------------------------------------------------------------------------------------------------------------------------------------
GEST = [B['Shift'], B['Stop'], B['Erase']]
d = boot(POR); d.translate(report1()); d.start(); sc = Screen(d); sc.settle()
d.translate(report1(GEST)); sc.run(19, 100)
check('Shift + Stop + Erase held 1.9 s: nothing yet', dfu_requested(d), False)
d.translate(report1()); sc.run(30, 100)
check('released before 2 s: nothing', dfu_requested(d), False)
d.translate(report1(GEST)); shown = dfu = None
for k in range(1, 60):
    sc.run(1, 50)
    if shown is None and sc.fb() == reference('DFU MODE', 'FLASH TO LEAVE'): shown = k * 50
    if dfu is None and dfu_requested(d): dfu = k * 50
    if k == 45: d.translate(report1())
check('held 2 s: DFU MODE / FLASH TO LEAVE on the screen (2.0-2.2 s), then the DFU request and the reset 0.3 s after the gesture completed', (shown is not None and 2000 <= shown <= 2200, dfu is not None and 100 <= dfu - shown <= 400), (True, True), f'shown at {shown} ms, DFU at {dfu} ms')
d = boot(POR); d.translate(report1()); d.start(); sc = Screen(d)
d.translate(report1([B['Shift'], B['Stop']])); sc.run(40, 100)
check('Shift + Stop alone, 4 s: nothing', dfu_requested(d), False)

# ---- HANG -----------------------------------------------------------------------------------------------------------------------------------------------
d = boot(POR); d.translate(report1()); d.start()
check('HANG with a wrong confirmation: status 1, the device goes on', (mc.parse_reply(d.ask(mc.message(mc.CMD_HANG, b'HANX'))[0])['status'], mc.parse_reply(d.ask(mc.info_request())[0])['cmd']), (1, 0x10))
r = mc.parse_reply(d.ask(mc.hang_request(), ticks=1)[0])
d.call(d.T_TICK, count=20000)
check('HANG: status 0, then the next tick never returns (the watchdog ends it)', (r['status'], d.mu.reg_read(UC_ARM_REG_PC) != 0x08000000), (0, True))

# ---- raw pad capture ------------------------------------------------------------------------------------------------------------------------------
d = boot(POR); d.translate(report1()); d.start()
d.mu.mem_write(0x20000718, struct.pack('<16H', *range(100, 1700, 100)))
t0 = 5000; d.mu.mem_write(MS16, struct.pack('<H', t0))
r = mc.parse_reply(d.ask(mc.capture_request(0b1000000000000101, 2))[0])
for k in range(10):
    d.mu.mem_write(MS16, struct.pack('<H', t0 + k)); d.mu.mem_write(0x20000718, struct.pack('<H', 100 + k)); d.tick(0)
hdr = struct.unpack('<4I', bytes(d.mu.mem_read(mc.CAP_BASE, 16)))
frames = [struct.unpack_from('<4H', bytes(d.mu.mem_read(mc.CAP_BASE + 16 + 8 * i, 8))) for i in range(hdr[1])]
check('capture of channels 0, 2, 15 every 2 ms: status 0, header (magic, frames, 8-byte frames, mask)', (r['status'], hdr[0], hdr[2], hdr[3]), (0, 0x50414352, 8, 0b1000000000000101))
check('... a frame every 2 ms with the time and the raw values', [(f[0] - t0, f[1], f[2], f[3]) for f in frames], [(t, 100 + t, 300, 1600) for t in range(0, 10, 2)])
for k in range(4000):                                                       # (on the stack the device uses: the emulator's usual one is inside the capture area)
    d.mu.mem_write(MS16, struct.pack('<H', (t0 + 10 + k * 2) & 0xFFFF)); d.mu.mem_write(devsim.STRUCT + 2, b'\0\0'); d.call(d.T_TICK, sp=0x20001C18)
hdr = struct.unpack('<4I', bytes(d.mu.mem_read(mc.CAP_BASE, 16)))
check('it stops when the RAM area is full and never writes past it', (hdr[1], mc.CAP_BASE + 16 + hdr[1] * 8 <= mc.CAP_END, mc.CAP_BASE + 16 + (hdr[1] + 1) * 8 > mc.CAP_END), ((mc.CAP_END - mc.CAP_BASE - 16) // 8, True, True))
check('a capture with period 0 is refused', mc.parse_reply(d.ask(mc.message(mc.CMD_CAPTURE, bytes([1, 0, 0, 0])))[0])['status'], 1)

# ---- the driver switch (SysEx 1C) ----------------------------------------------------------------------------------------------------------------
d = boot(POR); d.translate(report1()); d.start()
r1 = mc.parse_reply(d.ask(mc.hal_request(mc.HAL_LED))[0]); r0 = mc.parse_reply(d.ask(mc.hal_request(0))[0])
check('HAL 01 switches our LED refresh on, HAL 00 off again (the reply echoes the active set)', ((r1['status'], r1['hal']), (r0['status'], r0['hal'])), ((0, 1), (0, 0)))
check('HAL without its argument: status 1', mc.parse_reply(d.ask(mc.message(mc.CMD_HAL))[0])['status'], 1)
d2 = boot(POR); check('after a reboot the stock drivers are back (the switch lives in RAM)', mc.parse_reply(d2.ask(mc.hal_request(0))[0])['hal'], 0)

# ---- PEEK: the peripheral registers --------------------------------------------------------------------------------------------------------------
def peek_status(a, n): return mc.parse_reply(d.ask(mc.peek_request(a, n))[0])['status']
allowed = [(RCC_CSR, 4), (0x40021000, 0x28), (0x40010800, 0x1C), (0x40011800, 0x1C), (0x40012400, 0x40), (0x40012440, 12), (0x40020000, 0x40), (0x40003800, 12), (0x40005C00, 0x40), (0x40005C40, 0x14), (0x40006000, 64), (0xE000E100, 32), (0xE000ED00, 0x40), (0x40012C00, 0x40), (0x40012C40, 12)]
refused = [(0x4001244C, 4), (0x4000380C, 4), (0x40005414, 4), (0x40010800, 0x20), (0x40012C4C, 4), (0x40021028, 4), (0x40021024, 2), (0x40030000, 4), (0x40011C00, 4)]
check('PEEK reads the configuration registers (RCC, GPIO, ADC, DMA, SPI2, USB, NVIC, SCB, TIM1)', [peek_status(a, n) for a, n in allowed], [0] * len(allowed))
check('... but not the ones whose read has a side effect (ADC DR, SPI DR, I2C SR1, TIM DMAR), past a block, half words, unmapped space',
      [peek_status(a, n) for a, n in refused], [1] * len(refused))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
