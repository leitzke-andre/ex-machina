"""USB-level tests: enumerate the patched firmware through its REAL USB interrupt handler (ST's
USB-FS-Device library) against a scripted host, using tools/emu/usb_model.py.

Usage: test_enumeration.py <patched.bin> <data_init.bin>   (needs `pip install unicorn`)
"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'emu'))
from unicorn import *
from unicorn.arm_const import *
from usb_model import *

FL = 0x08003000
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp                       # the single source of truth for the flash layout
fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()

def bl_target(addr):
    h1, h2 = struct.unpack_from('<HH', fw, addr - FL)
    s = (h1 >> 10) & 1; j1 = (h2 >> 13) & 1; j2 = (h2 >> 11) & 1
    i1 = (~(j1 ^ s)) & 1; i2 = (~(j2 ^ s)) & 1
    off = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
    if s: off -= 1 << 25
    return addr + 4 + off
T_TRANS, T_INIT = bl_target(0x08004036) | 1, bl_target(0x08008CF8) | 1

ok = True
def check(name, cond, detail=''):
    global ok
    ok &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

def u16(mu, a): return struct.unpack('<H', mu.mem_read(a, 2))[0]
def lit(a): return struct.unpack_from('<I', fw, a - FL)[0]

mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
mu.mem_map(0xE0000000, 0x100000)
usb = UsbModel(mu)

# boot: our init hook with the original board init skipped, then the stock USB_Init
skip = mu.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1),
                   begin=0x08007EA2, end=0x08007EA3)
usb.run(T_INIT)
mu.hook_del(skip)
usb.run(USB_INIT)
check('USB_Init set pInformation (Device_Info) and pProperty', u16(mu, 0x20000060) == 0x01c0 and u16(mu, 0x20000064) == 0x00d4,
      (hex(u16(mu, 0x20000060)), hex(u16(mu, 0x20000064))))

usb.reset()
check('reset: EP0 is a control endpoint, RX valid', (usb.ep[0] & EP_TYPE) == 0x0200 and usb.stat_rx(0) == VALID_RX, hex(usb.ep[0]))
check('reset: EP1 is BULK (type bits 00), address 1, RX valid', (usb.ep[1] & EP_TYPE) == 0 and (usb.ep[1] & EA) == 1 and usb.stat_rx(1) == VALID_RX, hex(usb.ep[1]))
check('reset: device address enabled (DADDR bit 7)', usb.daddr & 0x80, hex(usb.daddr))

DEV = fw[bp.DESC_DEV_ADDR - FL:][:18]; CFG = fw[bp.DESC_CFG_ADDR - FL:][:119]
PAD1 = fw[bp.CFG_ADDR - FL + 5 + 12]               # cfg.pad_note[12]: report index 12 = printed pad 1
d, st = usb.control(setup_packet(0x80, 6, 0x0100, 0, 64))
check('GET_DESCRIPTOR device (wLength 64) returns the 18-byte descriptor', st == 'ok' and d == DEV, (st, d.hex()))
d, st = usb.control(setup_packet(0x80, 6, 0x0200, 0, 9))
check('GET_DESCRIPTOR configuration (9 bytes) reports wTotalLength 119', st == 'ok' and d[:2] == b'\x09\x02' and struct.unpack_from('<H', d, 2)[0] == 119, (st, d.hex()))
d, st = usb.control(setup_packet(0x80, 6, 0x0200, 0, 255))
check('GET_DESCRIPTOR configuration (full) returns all 119 bytes across two packets', st == 'ok' and d == CFG, (st, len(d)))

def string_desc(idx):
    return usb.control(setup_packet(0x80, 6, 0x0300 | idx, 0x0409, 255))
d, st = string_desc(0); check('string 0 = language ID 0x0409', st == 'ok' and d == bytes([4, 3, 9, 4]), d.hex())
for idx, want in ((1, 'Native Instruments'), (2, 'Maschine Mikro MK3')):
    d, st = string_desc(idx)
    check(f'string {idx} = "{want}"', st == 'ok' and d[2:].decode('utf-16le') == want, (st, d.hex()))
d, st = usb.control(setup_packet(0x80, 6, 0x0600, 0, 10))
check('GET_DESCRIPTOR device qualifier (high-speed only) is refused', st == 'stall', (st, d.hex()))
usb.ep[0] = (usb.ep[0] & ~(STAT_TX | STAT_RX)) | VALID_RX       # stall is cleared by the next SETUP on real hardware

d, st = usb.control(setup_packet(0x00, 5, 7, 0, 0))
check('SET_ADDRESS 7 applied after the status stage', st == 'ok' and usb.daddr == 0x87, (st, hex(usb.daddr)))
d, st = usb.control(setup_packet(0x00, 9, 1, 0, 0))
info = 0x200001c0
check('SET_CONFIGURATION 1 accepted, device state becomes configured', st == 'ok' and mu.mem_read(info + 9, 1)[0] != 0, (st, mu.mem_read(info + 9, 1)[0]))
d, st = usb.control(setup_packet(0x80, 8, 0, 0, 1))
check('GET_CONFIGURATION returns 1', st == 'ok' and d == b'\x01', (st, d.hex()))
for ifc, want in ((0, 'ok'), (1, 'ok'), (2, 'ok'), (3, 'stall')):
    usb.ep[0] = (usb.ep[0] & ~(STAT_TX | STAT_RX)) | VALID_RX
    d, st = usb.control(setup_packet(0x01, 11, 0, ifc, 0))
    check(f'SET_INTERFACE alt 0 on interface {ifc} -> {want}', st == want, st)
usb.ep[0] = (usb.ep[0] & ~(STAT_TX | STAT_RX)) | VALID_RX

# DFU_DETACH (class request to the DFU interface, index 2): must still arm the reboot-into-bootloader path
mode_addr = lit(0x080084CC)
d, st = usb.control(setup_packet(0x21, 0, 255, 2, 0))
check('DFU_DETACH to interface 2 accepted', st == 'ok', st)
check('DFU_DETACH sets mode 3 with the 2000-tick countdown (stock reboot-to-DFU path intact)',
      mu.mem_read(mode_addr, 1)[0] == 3 and u16(mu, mode_addr + 4) == 2000, (hex(mode_addr), mu.mem_read(mode_addr, 8).hex()))
mu.mem_write(mode_addr, b'\0')

# MIDI IN path: a pad hit becomes an EP1 bulk IN packet through the stock sender
def report2(events):
    p = bytearray([2])
    for pad, typ, val in events: p += bytes([pad, (typ << 4) | (val >> 8), val & 0xff])
    return bytes(p + bytes(64 - len(p)))
mu.mem_write(0x20003000, report2([(12, 1, 4000)]))
usb.run(T_TRANS, 0x20003000, 64)
usb.run(0x080089B5)                                   # stock EP1 sender (dequeues the ring, loads the PMA)
check('EP1 IN armed with one 4-byte USB-MIDI packet', usb.stat_tx(1) == VALID_TX and usb.entry(1)['count_tx'] == 4,
      (hex(usb.ep[1]), usb.entry(1)))
pkt = usb.bulk_in(1)
check(f'host reads 09 90 {PAD1:02x} 7d (Note On ch1, note {PAD1} = pad 1, velocity 125) from the bulk endpoint', pkt == bytes([0x09, 0x90, PAD1, 125]), pkt and pkt.hex())
check('EP1 returns to idle after the IN completes', usb.stat_tx(1) == NAK_TX)

# MIDI OUT path: host sends Note On on channel 2 (LED channel) -> LED buffer + pending flag
mu.mem_write(0x20001351, bytes([0x55] * 80)); mu.mem_write(0x20001028 + 0x2cf, b'\0')
usb.bulk_out(1, bytes([0x09, 0x91, 5, 127]))
led = mu.mem_read(0x20001351, 80)
check('bulk OUT Note On (ch2, note 5, vel 127) reaches the LED buffer via the stock OUT callback', led[5] == 127 and led[0] == 0xFF and mu.mem_read(0x20001028 + 0x2cf, 1)[0] == 1, (led[:8].hex()))
mu.mem_write(0x20001351, bytes([0x55] * 80)); mu.mem_write(0x20001028 + 0x2cf, b'\0')
usb.bulk_out(1, bytes([0x09, 0x91, 6, 64]))                # second packet uses the other RX buffer
led = mu.mem_read(0x20001351, 80)
check('second OUT packet (other ping-pong buffer) also works', led[6] == 64 and mu.mem_read(0x20001028 + 0x2cf, 1)[0] == 1, (led[:8].hex()))

# A burst arrives as several packets before the main loop applies the first one (the real-device finding of 2026-10-17: only the
# LEDs of the last packets survived). Packets must MERGE into the pending LED frame.
mu.mem_write(0x20001351, bytes([0x55] * 80)); mu.mem_write(0x20001028 + 0x2cf, b'\0')
for first in range(0, 16, 4):                      # 16 pad colours as 4 packets of 4 events, then the strip LED: no main loop in between
    usb.bulk_out(1, b''.join(bytes([0x09, 0x91, 39 + p, ((p + 1) << 2) | 2]) for p in range(first, first + 4)))
usb.bulk_out(1, bytes([0x09, 0x91, 55, (17 << 2) | 2]))
led = bytes(mu.mem_read(0x20001351, 80))
check('a 17-message LED burst over 5 packets keeps every LED (pads 39..54 = colours 1..16, strip LED 55) and leaves the rest alone',
      list(led[39:55]) == [((p + 1) << 2) | 2 for p in range(16)] and led[55] == (17 << 2) | 2 and led[0] == 0xFF and led[56] == 0xFF
      and mu.mem_read(0x20001028 + 0x2cf, 1)[0] == 1, led[36:58].hex())
mu.mem_write(0x20001351, bytes([0x55] * 80)); mu.mem_write(0x20001028 + 0x2cf, b'\0')
usb.bulk_out(1, bytes([0x0B, 0xB0, 44, 127]))      # CC feedback (Volume = button LED 3) followed by a note in the next packet
usb.bulk_out(1, bytes([0x09, 0x91, 5, 100]))
led = bytes(mu.mem_read(0x20001351, 80))
check('CC feedback and a note in separate packets merge too (LED 3 bright, LED 5 = 100, others untouched)', led[3] == 0x7F and led[5] == 100 and led[0] == 0xFF, led[:8].hex())

# END-TO-END: run the REAL main service routine 0x08004620 (the function that builds the HID reports and
# calls our hooked enqueue) with dirty flags set the way the scan code sets them, then let the stock
# sender move the result to the EP1 bulk endpoint.
ST = 0x20001028
def service(flags_data):
    mu.mem_write(ST + 0x88, struct.pack('<H', 1))     # keeps the button scan (hardware) out of the way
    mu.mem_write(ST + 0xc2, bytes([5]))               # keeps the touch-strip I2C read out of the way
    for off, val in flags_data.items(): mu.mem_write(ST + off, val)
    usb.run(0x08004621)
# fresh translator state (lazy init on first use), then report 1 baseline via the real report builder
mu.mem_write(bp.STATE_ADDR, bytes(0x260))
service({0x2cd: b'\x01', 0x2dd: bytes(13)})
service({})
check('baseline report 1 produces no MIDI', usb.stat_tx(1) != VALID_TX, hex(usb.ep[1]))
# Volume (button id 3) pressed + encoder one click clockwise (the counter counts up: 0 -> 1) + pad index 12 hit: report 1 and report 2 together
r1 = bytes([0b00001000, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0])
ev = bytes([12, 0x1F, 0xA0]) + bytes(60)             # pad 12, type 1, value 0xFA0 = 4000
service({0x2cd: b'\x01', 0x2dd: r1, 0x2ce: b'\x01', 0x2ea: ev})
service({})                                          # next main-loop pass: stock sender drains the ring into EP1
pkt = usb.bulk_in(1)
want = bytes([0x0B, 0xB0, 44, 127,  0x0B, 0xB0, 7, 1,  0x09, 0x90, PAD1, 125])
check('real report builder -> hook -> ring -> stock sender -> bulk IN delivers CC44, encoder CC7 and Note On for pad 1',
      pkt == want, pkt and pkt.hex())
# the stock main loop consumes the pending frame (it clears the flag, then reads the entries); afterwards every LED message
# rewrites the COMPLETE shadow state into the buffer, so stale contents are gone and earlier LEDs stay in the frame
usb.bulk_out(1, bytes([0x09, 0x91, 39, 6]))                    # LED 39 commanded
service({})
check('the real main loop applies the pending LED frame and clears the flag', mu.mem_read(ST + 0x2cf, 1)[0] == 0, mu.mem_read(ST + 0x2cf, 1).hex())
mu.mem_write(0x20001351, bytes([0x55] * 80))                   # stale contents from "the previous frame"
usb.bulk_out(1, bytes([0x09, 0x91, 7, 90]))
led = bytes(mu.mem_read(0x20001351, 80))
check('the next LED message rewrites the COMPLETE shadow state: stale contents are gone, the new LED is set, the earlier one is still in the frame, never-set LEDs stay 0xFF',
      led[7] == 90 and led[39] == 6 and led[8] == 0xFF and led[0] == 0xFF and 0x55 not in led and mu.mem_read(ST + 0x2cf, 1)[0] == 1, led[:10].hex() + ' ... ' + led[38:41].hex())
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
