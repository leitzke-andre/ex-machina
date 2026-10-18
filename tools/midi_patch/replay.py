"""Replays recorded HID reads through the patched translator (mmk3_translate) in the Unicorn emulator.
Shared by test_real_pads.py and test_real_controls.py. The stock ring-buffer enqueue (0x08008a38) is replaced by a stub that
collects what the translator hands over, because the real endpoint sender is not running here."""
import struct
from unicorn import *
from unicorn.arm_const import *

FL = 0x08003000

class Replay:
    def __init__(self, fw_path, data_path):
        self.fw = open(fw_path, 'rb').read()
        h1, h2 = struct.unpack_from('<HH', self.fw, 0x08004036 - FL)          # the hooked bl: its target is mmk3_translate
        s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
        i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
        off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
        if s: off -= 1 << 25
        self.entry = 0x08004036 + 4 + off | 1
        self.mu = mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, self.fw)
        mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, open(data_path, 'rb').read())
        mu.mem_map(0x40000000, 0x100000); mu.mem_map(0xE0000000, 0x100000)
        self.sent = []
        def enqueue_stub(uc, addr, size, ud):
            self.sent.append(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1))))
            uc.reg_write(UC_ARM_REG_R0, 0); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        mu.hook_add(UC_HOOK_CODE, enqueue_stub, begin=0x08008a38, end=0x08008a39)

    def translate(self, buf):
        """One HID read in, the USB-MIDI packets (4-tuples) out. Trimmed pad reports are padded back to 64 bytes."""
        mu = self.mu
        self.sent.clear()
        buf = buf + bytes((64 if buf[0] == 2 else 14) - len(buf))
        mu.mem_write(0x20003000, buf)
        mu.reg_write(UC_ARM_REG_R0, 0x20003000); mu.reg_write(UC_ARM_REG_R1, len(buf))
        mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        try: mu.emu_start(self.entry, 0x08000000, count=300000)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        return [tuple(b[k:k + 4]) for b in self.sent for k in range(0, len(b), 4)]
