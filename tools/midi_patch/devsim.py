"""A patched Mikro MK3 image in the Unicorn emulator, driven at the level of the patch's hooks: the boot hooks, the report translator,
the host->device hook, the main-loop tick. The stock routines these hooks call (board init, stage-2 init, the OUT parser, the ring
enqueue, the watchdog kick) are replaced by recording stubs; the ST flash routines run for real against tools/emu/flash_model.py,
which records every erase and program and flags anything outside the one page the patch may write.

Shared by test_features.py, test_config.py and the host-library tests."""
import os, struct, sys
from unicorn import *
from unicorn.arm_const import *

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import build_patch as bp
import mmk3_config as mc
from flash_model import FlashModel, PAGE

FL = 0x08003000
STRUCT = 0x20001028                                  # the stock firmware's own struct (not ours)
LED_BUF, LED_FLAG = 0x20001351, STRUCT + 0x2cf
RING_W, RING_R = 0x20000146, 0x20000148                # the stock TX ring (0x500 bytes): write and read index


def bl_target(fw, addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off


class Dev:
    def __init__(self, fw, data, cfg=None, flash=None, model=True):
        """cfg: replaces the build-time config block in flash before the boot hook runs; flash: the whole flash content (0x08000000.., 256 KB)
        to start from instead of the image, e.g. the flash of a device that was just switched off."""
        self.fw = fw
        self.T_TRANS, self.T_INIT, self.T_BOOT2, self.T_RX, self.T_TICK = (bl_target(fw, a) | 1 for a in
            (0x08004036, 0x08008CF8, 0x08008CFC, 0x08004ABA, 0x08008D06))
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        mu.mem_map(0x08000000, 0x40000); mu.mem_write(0x08000000, b'\xff' * 0x40000)      # erased flash reads 0xFF
        if flash is not None: mu.mem_write(0x08000000, bytes(flash))
        else: mu.mem_write(FL, fw)
        mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
        mu.mem_map(0x40000000, 0x100000); mu.mem_map(0xE0000000, 0x100000)
        mu.mem_map(0x1FFFF000, 0x1000); mu.mem_write(0x1FFFF7E0, struct.pack('<H', 128) + bytes(6) + bytes(range(0xA0, 0xAC)))   # system memory: flash size 128 KB, a unique ID
        if cfg is not None: mu.mem_write(bp.CFG_ADDR, bytes(cfg))
        self.flash = FlashModel(mu, writable=[(bp.SLOT_BASE, bp.SAVE_PAGE + PAGE)]) if model else None
        self.sent, self.all_sent, self.out_ptr, self.stock_rx, self.watchdog, self.threshold_calls = [], [], None, 0, 0, 0
        def enqueue(uc, a, s, u):
            r0, r1 = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
            self.out_ptr = r0; blob = bytes(uc.mem_read(r0, r1)); self.sent.append(blob); self.all_sent.append(blob)
            w = struct.unpack('<H', bytes(uc.mem_read(RING_W, 2)))[0]
            uc.mem_write(RING_W, struct.pack('<H', (w + r1) % 0x500))                                    # the stock enqueue advances the ring's write index
            uc.reg_write(UC_ARM_REG_R0, r1); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))     # and returns the byte count
        def stub(uc, a, s, u):
            if a == 0x08008799: self.stock_rx += 1
            if a == 0x080046B8: self.threshold_calls += 1
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        def kick(uc, a, s, u):
            self.watchdog += 1; uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
        mu.hook_add(UC_HOOK_CODE, enqueue, begin=0x08008a38, end=0x08008a39)
        mu.hook_add(UC_HOOK_CODE, kick, begin=0x08005414, end=0x08005415)           # the stock watchdog kick the tick hook calls
        for a in (0x08007EA3, 0x08008BAD, 0x080046B9, 0x08008799): mu.hook_add(UC_HOOK_CODE, stub, begin=a & ~1, end=(a & ~1) + 1)
        self.call(self.T_INIT)                                                       # mmk3_init: state reset, saved config loaded, descriptors repointed

    # ---- running code ----
    def call(self, pc, count=600000, sp=0x20004000):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        try: mu.emu_start(pc | 1, 0x08000000, count=count)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise

    def boot2(self):
        self.mu.mem_write(STRUCT + 0x5e1, bytes([80])); self.mu.mem_write(STRUCT + 2, struct.pack('<H', 6000))
        self.call(self.T_BOOT2)

    def tick(self, countdown=0):
        """One main-loop iteration's hook; `countdown` is the stock startup counter (6000 ms down to 0)."""
        self.mu.mem_write(STRUCT + 2, struct.pack('<H', countdown))
        self.call(self.T_TICK)

    def start(self):
        """Stage-2 init and the end of the stock startup: the state a user sees once the fade-in animation is over."""
        self.boot2(); self.tick(0)

    def translate(self, buf):
        self.sent.clear()
        mu = self.mu
        mu.mem_write(0x20003000, bytes(buf))
        mu.reg_write(UC_ARM_REG_R0, 0x20003000); mu.reg_write(UC_ARM_REG_R1, len(buf))
        mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        try: mu.emu_start(self.T_TRANS, 0x08000000, count=600000)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        return [tuple(b[k:k + 4]) for b in self.sent for k in range(0, len(b), 4)]

    def rx(self, pkt, sp=0x20004000):
        self.mu.mem_write(0x200001d8, bytes(pkt)); self.mu.mem_write(0x20000074, bytes([len(pkt)]))
        self.call(self.T_RX, sp=sp)

    def tick_interrupted(self, after, isr):
        """Runs the tick hook for `after` instructions, then (if it is still running) lets the USB interrupt run `isr(sp)` on the stack below the
        interrupted code, then lets the tick finish. Returns True if the tick was really interrupted."""
        mu = self.mu
        self.mu.mem_write(STRUCT + 2, struct.pack('<H', 0))
        mu.reg_write(UC_ARM_REG_SP, 0x20004000); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
        try: mu.emu_start(self.T_TICK | 1, 0x08000000, count=after)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        pc = mu.reg_read(UC_ARM_REG_PC)
        if pc == 0x08000000: return False
        ctx = mu.context_save(); sp = mu.reg_read(UC_ARM_REG_SP)
        isr((sp - 0x100) & ~7)
        mu.context_restore(ctx)
        try: mu.emu_start(pc | 1, 0x08000000, count=600000)
        except UcError:
            if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
        return True

    # ---- SysEx ----
    def send_sysex(self, msg, sp=0x20004000):
        raw = usb_packets(bytes(msg))
        for o in range(0, len(raw), 64): self.rx(raw[o:o + 64], sp=sp)  # 64-byte OUT transfers, like the bulk endpoint

    def ask(self, msg, ticks=10):
        """Sends a SysEx request, runs the main loop's tick a few times, returns the SysEx messages the device sent back."""
        self.all_sent.clear(); self.drain()
        self.send_sysex(msg)
        for _ in range(ticks): self.tick(0)
        return sysex_messages(self.all_sent)

    def cfg(self):                                                      # the active config, as the device reports it
        return mc.parse_reply(self.ask(mc.get_request())[0])['cfg']

    def drain(self):                                                    # the stock EP1 sender emptied the ring
        self.mu.mem_write(RING_R, bytes(self.mu.mem_read(RING_W, 2)))

    # ---- LED buffer of the stock firmware ----
    def led(self): return bytes(self.mu.mem_read(LED_BUF, 80))
    def flag(self): return self.mu.mem_read(LED_FLAG, 1)[0]
    def consume(self): self.mu.mem_write(LED_FLAG, b'\0')              # the stock main loop applied the frame and cleared the flag

    def flash_image(self): return bytes(self.mu.mem_read(0x08000000, 0x40000))
    def page(self): return bytes(self.mu.mem_read(bp.SAVE_PAGE, PAGE))


def report1(pressed=(), touch=0, enc=0, pos=0):
    b = bytearray(5)
    for k in pressed:
        if k < 40: b[k >> 3] |= 1 << (k & 7)
    touch = touch or 40 in pressed                                   # button id 40 = encoder touch (bit 0 of byte 5)
    return bytes([1]) + bytes(b) + bytes([int(touch), enc & 15, 0, 0, pos, 0, 0, 0])

def report2(events):
    p = bytearray([2])
    for pad, typ, val in events: p += bytes([pad, (typ << 4) | (val >> 8), val & 0xff])
    return bytes(p + bytes(64 - len(p)))

CC = lambda n, v, ch=0: (0x0B, 0xB0 | ch, n, v)

def usb_packets(msg):
    """A SysEx message (F0 ... F7) as USB-MIDI event packets, cable 0."""
    pk = []; i = 0
    while len(msg) - i > 3: pk.append(bytes([4]) + msg[i:i + 3]); i += 3
    rest = msg[i:]; pk.append(bytes([{1: 5, 2: 6, 3: 7}[len(rest)]]) + rest + bytes(3 - len(rest)))
    return b''.join(pk)

def sysex_messages(blobs):
    """The SysEx messages in a list of enqueued USB-MIDI byte blobs (all other packets are ignored)."""
    out, cur = [], None
    for blob in blobs:
        for k in range(0, len(blob), 4):
            cin, data = blob[k] & 15, blob[k + 1:k + 4]
            if cin in (4, 5, 6, 7):
                for b in data[:3 if cin in (4, 7) else cin - 4]:
                    if b == 0xF0: cur = bytearray([b])
                    elif cur is not None:
                        cur.append(b)
                        if b == 0xF7: out.append(bytes(cur)); cur = None
    return out
