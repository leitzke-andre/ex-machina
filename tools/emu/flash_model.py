"""Model of the STM32F1 flash interface (registers at 0x40022000) for Unicorn, strict enough to catch the mistakes that matter.

The firmware's own flash routines (ST's standard peripheral library, kept in the stock image) run against it unchanged. Modelled:
  - the lock: KEYR needs the two keys in order; CR writes are ignored while locked (and recorded as a violation if they try to
    start something); CR.LOCK locks again
  - page erase (CR.PER + AR + CR.STRT): the 1 KB page becomes 0xFF
  - programming (CR.PG): only halfword writes, only into erased cells; anything else is recorded
  - an address allow-list: erasing or programming outside it is recorded (the tests allow exactly one page)
  - a log of every erase and programmed halfword in order, so a test can rebuild the flash content at any point of a save and
    replay "the power failed here" (NOR flash can only clear bits, an interrupted halfword may be anything between old and new)
Not modelled: timing (an operation is complete at once, BSY always 0), option bytes, write protection.
"""
import struct
from unicorn import *

FLASH_IF = 0x40022000
KEY1, KEY2 = 0x45670123, 0xCDEF89AB
SR_PGERR, SR_EOP = 0x04, 0x20
CR_PG, CR_PER, CR_MER, CR_STRT, CR_LOCK = 0x01, 0x02, 0x04, 0x40, 0x80
PAGE = 0x400
FLASH_LO, FLASH_HI = 0x08000000, 0x08020000


class FlashModel:
    def __init__(self, mu, writable=()):
        """writable: [(start, end)) address ranges the firmware may erase or program; everything else is a violation."""
        self.mu = mu
        self.writable = list(writable)
        self.locked, self.key_state = True, 0
        self.cr, self.sr, self.ar = CR_LOCK, 0, 0
        self.log = []            # ('erase', page) / ('prog', address, halfword), in order
        self.violations = []
        mu.mem_unmap(FLASH_IF, 0x400)
        mu.mmio_map(FLASH_IF, 0x400, self._read, None, self._write, None)
        mu.hook_add(UC_HOOK_MEM_WRITE, self._flash_write, begin=FLASH_LO, end=FLASH_HI - 1)

    # ---- helpers for tests ----
    @property
    def erases(self): return [e[1] for e in self.log if e[0] == 'erase']
    @property
    def programs(self): return [(e[1], e[2]) for e in self.log if e[0] == 'prog']

    def _allowed(self, start, end): return any(a <= start and end <= b for a, b in self.writable)

    def _violation(self, what): self.violations.append(what)

    # ---- registers ----
    def _read(self, uc, off, size, ud):
        return {0x00: 0x30, 0x0C: self.sr, 0x10: self.cr, 0x14: self.ar, 0x1C: 0, 0x20: 0xFFFFFFFF}.get(off, 0)

    def _write(self, uc, off, size, value, ud):
        value &= 0xFFFFFFFF
        if off == 0x04:                                  # KEYR
            if self.key_state == 0 and value == KEY1: self.key_state = 1
            elif self.key_state == 1 and value == KEY2: self.key_state = 2; self.locked = False; self.cr &= ~CR_LOCK
            else: self.key_state = 0; self._violation(f'wrong flash key {value:#x}')
        elif off == 0x0C:                                # SR: write 1 to clear
            self.sr &= ~value
        elif off == 0x14:
            self.ar = value
        elif off == 0x10:                                # CR
            if value & CR_LOCK:
                self.locked, self.key_state = True, 0; self.cr = (value & ~(CR_PG | CR_PER | CR_MER | CR_STRT)) | CR_LOCK
                return
            if self.locked:
                if value & (CR_PG | CR_PER | CR_MER | CR_STRT): self._violation(f'flash CR {value:#x} written while locked')
                return
            self.cr = value & ~CR_STRT
            if value & CR_STRT:
                if value & CR_MER: self._violation('mass erase')
                elif value & CR_PER: self._erase(self.ar)
                self.sr |= SR_EOP

    def _erase(self, addr):
        page = addr & ~(PAGE - 1)
        if not self._allowed(page, page + PAGE): self._violation(f'erase of {page:#x} outside the allowed range'); return
        self.mu.mem_write(page, b'\xff' * PAGE)
        self.log.append(('erase', page))

    # ---- programming: every write into the flash range ----
    def _flash_write(self, uc, access, addr, size, value, ud):
        if not (self.cr & CR_PG) or self.locked:
            self._violation(f'write of {size} bytes to flash {addr:#x} without PG'); return
        if size != 2 or addr & 1:
            self._violation(f'programming with a {size}-byte write at {addr:#x} (only aligned halfwords)'); return
        if not self._allowed(addr, addr + 2): self._violation(f'programming {addr:#x} outside the allowed range'); return
        old = struct.unpack('<H', bytes(uc.mem_read(addr, 2)))[0]
        if old != 0xFFFF and (value & 0xFFFF) != 0: self._violation(f'programming {addr:#x} that is not erased ({old:#06x} -> {value & 0xFFFF:#06x})')
        self.log.append(('prog', addr, value & 0xFFFF))
        self.sr |= SR_EOP


def image_after(initial, log, upto, partial=None):
    """The flash content (a bytearray based at FLASH_LO) after the first `upto` events of `log`; `partial` = (halfword mask) to model the
    event number `upto` being cut short: its bits are cleared only where the mask has zeros (old & (new | ~mask))."""
    img = bytearray(initial)
    def apply(ev, mask=0xFFFF):
        if ev[0] == 'erase':
            base = ev[1] - FLASH_LO
            if mask == 0xFFFF: img[base:base + PAGE] = b'\xff' * PAGE
            else:                                    # an interrupted erase: some bytes erased, some not
                for k in range(PAGE):
                    if (k * 2654435761 >> 7) & 1: img[base + k] = 0xFF
        else:
            a = ev[1] - FLASH_LO
            old = struct.unpack_from('<H', img, a)[0]
            struct.pack_into('<H', img, a, old & (ev[2] | (~mask & 0xFFFF)))
    for ev in log[:upto]: apply(ev)
    if partial is not None and upto < len(log): apply(log[upto], partial)
    return img
