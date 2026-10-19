"""Peripherals for running hardware-facing code in Unicorn: a register file for 0x40000000-0x4002FFFF with the GPIO set / reset registers,
the bit-band alias of the peripherals and of SRAM, a few status registers that must read "ready", and bit-banged I2C buses seen from the
slave side (start / stop / bytes / acknowledge, reads answered by a callback). Used by the tests that compare our drivers (hal.c) with the
stock routines they replace: both run on the same model and the bus traffic and pin waveforms are compared."""
import collections, struct
from unicorn import *
from unicorn.arm_const import *

GPIO = {'A': 0x40010800, 'B': 0x40010C00, 'C': 0x40011000}


class I2CSlaveBus:
    """The slave side of a bit-banged bus on one GPIO port: `acks` = the 7-bit addresses that answer; reads are served by reader(addr, index).
    Records every transaction as [addr, 'W' or 'R', [bytes]] in `tx`, and every change of the master's pin levels in `wave`."""
    def __init__(self, port, scl, sda, acks=(), reader=None):
        self.port, self.scl, self.sda = port, scl, sda
        self.acks, self.reader = set(acks), reader or (lambda a, i: 0xFF)
        self.S = self.D = 1; self.drive = None; self.state = 'idle'; self.bits = self.n = 0; self.cur = None
        self.tx, self.wave = [], []
        self.read_byte = self.rbit = 0; self.master_ack = 1

    def level(self): return self.D if self.drive is None else (self.D & self.drive)

    def flush(self):
        if self.cur: self.tx.append(self.cur)
        self.cur = None

    def update(self, S, D, mode):
        if (S, D, mode) != (self.S, self.D, getattr(self, 'mode', None)): self.wave.append((S, D, mode))
        self.mode = mode
        oS, oD = self.S, self.level()
        self.S, self.D = S, D
        nD = self.level()
        if oS and S and oD and not nD:                                   # START (or a repeated one)
            self.flush(); self.state = 'addr'; self.bits = self.n = 0; self.drive = None; return
        if oS and S and not oD and nD and self.drive is None:             # STOP
            self.flush(); self.state = 'idle'; return
        if not oS and S:                                                  # rising clock: the receiver samples
            if self.state in ('addr', 'w'): self.bits = (self.bits << 1) | (D & 1); self.n += 1
            elif self.state == 'rack': self.master_ack = D
        if oS and not S:                                                  # falling clock: the slave changes SDA
            if self.state in ('addr', 'w') and self.n == 8:
                b = self.bits & 0xFF; self.bits = self.n = 0
                if self.state == 'addr':
                    if (b >> 1) in self.acks:
                        self.cur = [b >> 1, 'R' if b & 1 else 'W', []]; self.drive = 0
                        self.state = 'ack_r' if b & 1 else 'ack_w'
                    else: self.state = 'nack'; self.drive = None
                else: self.cur[2].append(b); self.drive = 0; self.state = 'ack_w'
            elif self.state == 'ack_w': self.drive = None; self.state = 'w'
            elif self.state in ('ack_r', 'rack'):
                if self.state == 'rack' and self.master_ack: self.drive = None; self.state = 'done'; return
                v = self.reader(self.cur[0], len(self.cur[2])) & 0xFF; self.cur[2].append(v)
                self.read_byte, self.rbit = v, 7; self.drive = v >> 7; self.state = 'r'
            elif self.state == 'r':
                self.rbit -= 1
                if self.rbit >= 0: self.drive = (self.read_byte >> self.rbit) & 1
                else: self.drive = None; self.state = 'rack'


class Periph:
    """Maps the peripheral space of `mu` and keeps the register values; `buses` see every change of their port's output register."""
    def __init__(self, mu):
        self.mu, self.regs, self.buses = mu, collections.defaultdict(int), []
        self.inputs = {}                 # port letter -> function(periph) giving that port's input register (e.g. a key matrix)
        self.watchers = []               # functions(periph, port) called after every change of a port's output or mode registers
        for b in GPIO.values(): self.regs[b] = self.regs[b + 4] = 0x44444444          # reset values: every pin an input
        self.regs[0x40021000] = 0x83                                                   # RCC_CR: the internal oscillator on
        mu.mmio_map(0x40000000, 0x30000, lambda uc, off, size, ud: self.read(0x40000000 + off, size), None,
                    lambda uc, off, size, v, ud: self.write(0x40000000 + off, size, v), None)
        mu.mmio_map(0x42000000, 0x600000, self._bb_read, None, self._bb_write, None)
        mu.mmio_map(0x22000000, 0xA0000, self._sbb_read, None, self._sbb_write, None)

    def read(self, a, size):
        v = self.regs[a & ~3] >> (8 * (a & 3))
        if a == 0x40021000: v |= (1 << 17) | (1 << 25) | 2                # clocks ready
        if a & ~3 == 0x40021004: v = (self.regs[0x40021004] & ~0xC) | ((self.regs[0x40021004] & 3) << 2)      # the clock switch status follows the switch
        if a & ~3 == 0x40012408: v = self.regs[0x40012408] & ~0xC          # ADC calibration: done at once
        if a == 0x40003808: v = 2                                          # SPI2: TX empty, not busy
        for port, base in GPIO.items():
            if a == base + 8:                                              # IDR: the output levels (or a model's), SDA pulled low by a driving slave
                v = self.inputs[port](self) if port in self.inputs else self.regs[base + 0xC] & 0xFFFF
                for b in self.buses:
                    if b.port == port and b.drive is not None: v = (v & ~(1 << b.sda)) | ((b.drive & 1) << b.sda)
        return v & ((1 << (8 * size)) - 1)

    def write(self, a, size, v):
        w = a & ~3
        if size < 4:
            sh = 8 * (a & 3); m = ((1 << (8 * size)) - 1) << sh
            v = (self.regs[w] & ~m) | ((v << sh) & m)
        for port, base in GPIO.items():
            if w == base + 0x10: self.regs[base + 0xC] = (self.regs[base + 0xC] | (v & 0xFFFF)) & ~(v >> 16); self._buses(port); return
            if w == base + 0x14: self.regs[base + 0xC] &= ~v; self._buses(port); return
        if w == 0x4002200C: self.regs[w] &= ~v; return                    # FLASH_SR: flags cleared by writing 1
        self.regs[w] = v & 0xFFFFFFFF
        for port, base in GPIO.items():
            if w in (base, base + 4, base + 0xC): self._buses(port)

    def _buses(self, port):
        for f in self.watchers: f(self, port)
        base = GPIO[port]; odr = self.regs[base + 0xC]
        for b in self.buses:
            if b.port == port:
                cr = self.regs[base + (0 if b.sda < 8 else 4)]
                b.update((odr >> b.scl) & 1, (odr >> b.sda) & 1, (cr >> (4 * (b.sda & 7))) & 15)

    def _bb_read(self, uc, off, size, ud):
        a = 0x40000000 + (off >> 5); bit = 8 * (a & 3) + ((off >> 2) & 7)
        return (self.read(a & ~3, 4) >> bit) & 1

    def _bb_write(self, uc, off, size, value, ud):
        a = 0x40000000 + (off >> 5); bit = 8 * (a & 3) + ((off >> 2) & 7); w = a & ~3
        v = self.regs[w]; v = (v | (1 << bit)) if value & 1 else (v & ~(1 << bit))
        self.regs[w] = v
        for port, base in GPIO.items():
            if w in (base, base + 4, base + 0xC): self._buses(port)

    def _sbb_read(self, uc, off, size, ud):
        return (self.mu.mem_read(0x20000000 + (off >> 5), 1)[0] >> ((off >> 2) & 7)) & 1

    def _sbb_write(self, uc, off, size, value, ud):
        a = 0x20000000 + (off >> 5); bit = (off >> 2) & 7
        b = self.mu.mem_read(a, 1)[0]; b = (b | (1 << bit)) if value & 1 else (b & ~(1 << bit))
        self.mu.mem_write(a, bytes([b]))


def machine(image, data):
    """Unicorn with the flash image at 0x08003000, the stock RAM image, the system space and the peripheral model."""
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(0x08000000, 0x40000); mu.mem_write(0x08000000, b'\xff' * 0x40000); mu.mem_write(0x08003000, image)
    mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
    mu.mem_map(0xE0000000, 0x100000)
    return mu, Periph(mu)


def call(mu, pc, limit=20_000_000, sp=0x20001C18):
    mu.reg_write(UC_ARM_REG_SP, sp); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(pc | 1, 0x08000000, count=limit)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise RuntimeError(f'did not return (pc={mu.reg_read(UC_ARM_REG_PC):#x})')
