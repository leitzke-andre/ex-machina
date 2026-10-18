"""Build a booted, enumerated emulated Mikro MK3: patched (or stock) firmware in Unicorn, the STM32 USB
model from usb_model.py, real USB library enumeration finished (address 7, configuration 1)."""
import struct
from unicorn import *
from unicorn.arm_const import *
from usb_model import *

FL = 0x08003000

def bl_target(fw, addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off

def boot(fw, data, patched=True, configure=True, flash_patch=None):
    """flash_patch: {address: bytes} written into the (emulated) flash before anything runs, e.g. a different config block or a saved record."""
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
    for addr, blob in (flash_patch or {}).items(): mu.mem_write(addr, bytes(blob))
    mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
    mu.mem_map(0xE0000000, 0x100000)
    usb = UsbModel(mu)
    if patched:
        skip = mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1),
                           begin=0x08007EA2, end=0x08007EA3)      # skip the stock board init (touches clocks, I2C, ...)
        usb.run(bl_target(fw, 0x08008CF8) | 1)                    # our boot hook (descriptor table, translator state)
        mu.hook_del(skip)
    usb.run(USB_INIT); usb.reset()
    if configure:
        usb.control(setup_packet(0x00, 5, 7, 0, 0)); usb.control(setup_packet(0x00, 9, 1, 0, 0))
    return mu, usb
