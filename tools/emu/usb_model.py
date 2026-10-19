"""Minimal model of the STM32F1 USB full-speed device peripheral for Unicorn.

It lets the firmware's real USB interrupt handler (ST's USB-FS-Device library) run an enumeration and
bulk transfers against a scripted host, without hardware. Registers live at 0x40005C00 (EPnR, CNTR,
ISTR, DADDR, BTABLE), packet memory (PMA) at 0x40006000 where PMA byte offset p is the halfword at
0x40006000 + 2*p.

Modelled: EPnR toggle/clear-on-write semantics, ISTR flags with dynamic CTR/DIR/EP_ID, BTABLE-based
buffers, control transfers (SETUP, IN data stage, OUT status stage), bulk IN/OUT packets.
Not modelled: timing, suspend/resume, SOF, CRC, errors, isochronous/double-buffered endpoints.
"""
import struct
from unicorn import *
from unicorn.arm_const import *

USB_BASE = 0x40005C00
PMA_BASE = 0x40006000

CTR_RX, DTOG_RX, STAT_RX, SETUP, EP_TYPE, EP_KIND = 0x8000, 0x4000, 0x3000, 0x0800, 0x0600, 0x0100
CTR_TX, DTOG_TX, STAT_TX, EA = 0x0080, 0x0040, 0x0030, 0x000F
NAK_RX, VALID_RX, STALL_RX = 0x2000, 0x3000, 0x1000
NAK_TX, VALID_TX, STALL_TX = 0x0020, 0x0030, 0x0010
ISTR_RESET = 0x0400

USB_LP_ISR = 0x08008795            # vector 36 (USB_LP_CAN1_RX0), Thumb
USB_INIT = 0x08008665              # stock USB_Init (sets pInformation/pProperty, calls Device_Property.Init)


def add_bitband(mu):
    """Cortex-M3 bit-band alias regions (SRAM 0x22000000 -> 0x20000000, peripherals 0x42000000 -> 0x40000000)."""
    for alias, base in ((0x22000000, 0x20000000), (0x42000000, 0x40000000)):
        def rd(uc, off, size, ud, base=base):
            byte, bit = off >> 5, (off >> 2) & 7
            return (uc.mem_read(base + byte, 1)[0] >> bit) & 1
        def wr(uc, off, size, value, ud, base=base):
            byte, bit = off >> 5, (off >> 2) & 7
            b = uc.mem_read(base + byte, 1)[0]
            b = (b | (1 << bit)) if value & 1 else (b & ~(1 << bit))
            uc.mem_write(base + byte, bytes([b & 0xFF]))
        mu.mmio_map(alias, 0x2000000, rd, None, wr, None)


class UsbModel:
    def __init__(self, mu):
        self.mu = mu
        self.ep = [0] * 8
        self.cntr = 0
        self.flags = 0           # ISTR bits 14..8 (PMAOVR, ERR, WKUP, SUSP, RESET, SOF, ESOF)
        self.daddr = 0
        self.btable = 0
        self.other = {}          # other peripherals in the 0x40005000 page behave like RAM
        self.log = []
        # 0x40000000..0x40004FFF plain, 0x40005000 page = MMIO, PMA, rest plain
        mu.mem_map(0x40000000, 0x5000)
        mu.mmio_map(0x40005000, 0x1000, self._read, None, self._write, None)
        mu.mem_map(PMA_BASE, 0x1000)
        mu.mem_map(0x40007000, 0xF9000)
        add_bitband(mu)

    # -------- register access --------
    def _istr(self):
        ctr = 0; dirb = 0; epid = 0
        for n in range(8):
            if self.ep[n] & (CTR_RX | CTR_TX):
                ctr = 0x8000; epid = n; dirb = 0x10 if self.ep[n] & CTR_RX else 0
                break
        return self.flags | ctr | dirb | epid

    def _read(self, uc, off, size, ud):
        r = off - 0xC00
        if 0 <= r < 0x20 and r % 4 == 0: return self.ep[r // 4]
        if r == 0x40: return self.cntr
        if r == 0x44: return self._istr()
        if r == 0x48: return 0
        if r == 0x4C: return self.daddr
        if r == 0x50: return self.btable
        return self.other.get(off, 0)

    def _write(self, uc, off, size, value, ud):
        r = off - 0xC00
        if 0 <= r < 0x20 and r % 4 == 0:
            n = r // 4; o = self.ep[n]; v = value & 0xFFFF
            tog = DTOG_RX | STAT_RX | DTOG_TX | STAT_TX
            rw = EP_TYPE | EP_KIND | EA
            new = o
            new = (new & ~(CTR_RX | CTR_TX)) | (o & v & (CTR_RX | CTR_TX))   # CTR bits: cleared by writing 0
            new ^= (v & tog)                                                  # toggle bits: flipped by writing 1
            new = (new & ~rw) | (v & rw)                                      # plain read/write bits
            self.ep[n] = new
        elif r == 0x40: self.cntr = value & 0xFFFF
        elif r == 0x44: self.flags &= (value | 0x80FF) & 0x7FFF               # rc_w0 flag bits
        elif r == 0x4C: self.daddr = value & 0xFF
        elif r == 0x50: self.btable = value & 0xFFF8
        else: self.other[off] = value

    # -------- PMA helpers --------
    def pma_get16(self, p):
        return struct.unpack('<H', self.mu.mem_read(PMA_BASE + 2 * p, 2))[0]

    def pma_set16(self, p, v):
        self.mu.mem_write(PMA_BASE + 2 * p, struct.pack('<H', v & 0xFFFF))

    def pma_read(self, p, n):
        out = bytearray()
        for k in range((n + 1) // 2):
            out += struct.pack('<H', self.pma_get16(p + 2 * k))
        return bytes(out[:n])

    def pma_write(self, p, data):
        data = bytes(data) + (b'\0' if len(data) % 2 else b'')
        for k in range(0, len(data), 2):
            self.pma_set16(p + k, data[k] | (data[k + 1] << 8))

    def entry(self, n):
        b = self.btable + 8 * n
        return dict(addr_tx=self.pma_get16(b), count_tx=self.pma_get16(b + 2) & 0x3FF,
                    addr_rx=self.pma_get16(b + 4), count_rx=self.pma_get16(b + 6))

    # -------- CPU side --------
    sp = 0x20004000      # stack pointer for code started with run(); a preemption test lowers it so the ISR does not trample the interrupted code

    def run(self, pc, r0=0, r1=0, limit=3_000_000):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_R0, r0); mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_SP, self.sp); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        try:
            mu.emu_start(pc, 0x08000000, count=limit)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000:
            raise RuntimeError(f'did not return (pc={mu.reg_read(UC_ARM_REG_PC):#x}); instruction limit hit')

    isr_pc = USB_LP_ISR  # the interrupt entry to run (a test of another USB stack sets its own)

    def isr(self):
        self.run(self.isr_pc)

    def reset(self):
        self.flags |= ISTR_RESET
        self.isr()

    # -------- scripted host --------
    def stat_tx(self, n): return self.ep[n] & STAT_TX
    def stat_rx(self, n): return self.ep[n] & STAT_RX

    def _deliver_out(self, n, data, setup=False):
        e = self.entry(n)
        self.pma_write(e['addr_rx'], data)
        b = self.btable + 8 * n + 6
        self.pma_set16(b, (self.pma_get16(b) & 0xFC00) | len(data))
        ep = self.ep[n]
        ep = (ep & ~(STAT_RX | STAT_TX if setup else STAT_RX)) | NAK_RX | (NAK_TX if setup else (ep & STAT_TX))
        ep |= CTR_RX | (SETUP if setup else 0)
        if not setup: ep &= ~SETUP
        self.ep[n] = ep
        self.isr()

    def control(self, setup8, out_data=b'', max_iter=64):
        """Run one control transfer. Returns (data_in, status): 'ok', or 'stall' when the firmware
        rejected the request (endpoint stalled right after the SETUP/data stage).
        Note: ST's library parks EP0 in STALL after every completed transfer; real control endpoints
        still accept the next SETUP, which the model mimics by resetting the status bits on SETUP."""
        assert len(setup8) == 8
        self._deliver_out(0, setup8, setup=True)
        wlen = struct.unpack_from('<H', setup8, 6)[0]
        is_in = bool(setup8[0] & 0x80)
        got = bytearray()
        if self.stat_tx(0) == STALL_TX and not (is_in and wlen == 0):
            return b'', 'stall'
        if is_in and wlen:
            for _ in range(max_iter):
                if self.stat_tx(0) != VALID_TX: break
                e = self.entry(0)
                chunk = self.pma_read(e['addr_tx'], e['count_tx'])
                got += chunk
                self.ep[0] = (self.ep[0] & ~STAT_TX) | NAK_TX | CTR_TX
                self.isr()
                if len(chunk) < 64 or len(got) >= wlen:
                    break                                    # host is satisfied: status stage follows
            self._deliver_out(0, b'')                        # status stage: zero-length OUT
        elif is_in:
            self._deliver_out(0, b'')
        else:
            if wlen:                                         # OUT data stage
                for k in range(0, len(out_data), 64):
                    self._deliver_out(0, out_data[k:k + 64])
                if self.stat_tx(0) == STALL_TX: return b'', 'stall'
            if self.stat_tx(0) == VALID_TX:                  # zero-length IN status stage
                self.ep[0] = (self.ep[0] & ~STAT_TX) | NAK_TX | CTR_TX
                self.isr()
        return bytes(got), 'ok'

    def bulk_in(self, n):
        """If endpoint n has a valid TX buffer, take the packet like a host IN token would."""
        if self.stat_tx(n) != VALID_TX: return None
        e = self.entry(n)
        data = self.pma_read(e['addr_tx'], e['count_tx'])
        self.ep[n] = (self.ep[n] & ~STAT_TX) | NAK_TX | CTR_TX
        self.isr()
        return data

    def bulk_out(self, n, data):
        assert self.stat_rx(n) == VALID_RX, f'EP{n} is not ready to receive (STAT_RX={self.stat_rx(n):#x})'
        self._deliver_out(n, data)


def setup_packet(bm, req, value=0, index=0, length=0):
    return struct.pack('<BBHHH', bm, req, value, index, length)
