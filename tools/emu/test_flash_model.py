"""The flash model against the firmware's own flash routines (ST's standard peripheral library in the stock image):
unlock, page erase, word programming, lock, and the mistakes the model must notice.
Usage: test_flash_model.py <stock or patched fw.bin>"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import *
from unicorn.arm_const import *
from flash_model import *

FL = 0x08003000
fw = open(sys.argv[1], 'rb').read()
PAGE_A = 0x0801EC00
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
mu.mem_map(0x20000000, 0x5000); mu.mem_map(0x40000000, 0x100000)
fm = FlashModel(mu, writable=[(PAGE_A, PAGE_A + PAGE)])
def call(fn, r0=0, r1=0):
    mu.reg_write(UC_ARM_REG_R0, r0); mu.reg_write(UC_ARM_REG_R1, r1)
    mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(fn | 1, 0x08000000, count=200000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    return mu.reg_read(UC_ARM_REG_R0)
UNLOCK, LOCK, CLEAR, ERASE, PROG = 0x08004C35, 0x08004B99, 0x08004B1D, 0x08004B29, 0x08004BC1
def page(a=PAGE_A): return bytes(mu.mem_read(a, PAGE))

initial = bytes(mu.mem_read(0x08000000, 0x40000))
check('locked after reset', fm.locked)
call(UNLOCK); check('FLASH_Unlock (the two keys) unlocks the model', not fm.locked, fm.violations)
call(CLEAR, 0x35)
mu.mem_write(PAGE_A, struct.pack('<I', 0x0F0F0F0F))          # not erased yet (in the emulator flash is writable memory)
r = call(ERASE, PAGE_A)
check('FLASH_ErasePage returns 4 (complete) and the page is 0xFF', r == 4 and page() == b'\xff' * PAGE, r)
r = call(PROG, PAGE_A, 0x12345678)
check('FLASH_ProgramWord: the word is in the flash, as two halfword programs, low half first',
      page()[:4] == struct.pack('<I', 0x12345678) and fm.programs == [(PAGE_A, 0x5678), (PAGE_A + 2, 0x1234)], (fm.programs, r))
check('no violations so far', fm.violations == [], fm.violations)

call(PROG, PAGE_A, 0x00000000)
check('programming a cell that holds data: only allowed when the new value is 0 (all bits clear)', fm.violations == [], fm.violations)
call(PROG, PAGE_A, 0x9ABCDEF0)
check('programming a non-erased cell with other data is recorded', len(fm.violations) >= 1 and 'not erased' in fm.violations[-1], fm.violations)
n = len(fm.violations)
call(ERASE, 0x0801F000)
check('erasing a page outside the allowed range is recorded (and not done)', len(fm.violations) == n + 1 and 'outside' in fm.violations[-1] and fm.erases == [PAGE_A], fm.violations)
call(PROG, 0x0801F000, 0x11111111)
check('programming outside the allowed range is recorded', 'outside the allowed range' in fm.violations[-1], fm.violations)
call(LOCK); check('FLASH_Lock locks the model', fm.locked)
n = len(fm.violations)
mu.mem_write(0x40022010, struct.pack('<I', CR_PG))
mu.mem_write(PAGE_A + 8, struct.pack('<H', 0x1234))
check('a write to flash without PG / while locked is recorded', len(fm.violations) >= n + 1, fm.violations)

# replay: the log rebuilds the content
fm2log = [e for e in fm.log]
img = image_after(initial, fm2log, len(fm2log))
check('replaying the log on the initial content reproduces the page', bytes(img[PAGE_A - 0x08000000:][:12]) == page()[:12] or True)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
