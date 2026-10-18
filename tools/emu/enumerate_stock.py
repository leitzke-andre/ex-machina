"""Baseline for the USB model: enumerate the UNPATCHED stock firmware through its real USB handler and
compare with the descriptors found statically in the image. If the model reproduces the stock device
(which works on real hardware), its verdicts on the patched image mean something.
Usage: enumerate_stock.py <stock fw.bin> <data_init.bin>"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import *
from unicorn.arm_const import *
from usb_model import *

FL = 0x08003000
fw = open(sys.argv[1], 'rb').read()[:0x9dc8]; data = open(sys.argv[2], 'rb').read()
mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
mu.mem_map(0x08000000, 0x40000); mu.mem_write(FL, fw)
mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
mu.mem_map(0xE0000000, 0x100000)
usb = UsbModel(mu)
usb.run(USB_INIT); usb.reset()
ok = True
def check(n, c, d=''):
    global ok; ok &= bool(c); print(('PASS ' if c else 'FAIL ') + n + ('' if c else '  ' + str(d)))
dev = fw[0x5d54:0x5d54 + 18]; cfg = fw[0x5d66:0x5d66 + 0x3b]; rpt = fw[0x5e4d:0x5e4d + 0x1ef]
d, st = usb.control(setup_packet(0x80, 6, 0x0100, 0, 64)); check('stock device descriptor', d == dev and st == 'ok', d.hex())
d, st = usb.control(setup_packet(0x80, 6, 0x0200, 0, 255)); check('stock configuration descriptor (59 B)', d == cfg and st == 'ok', len(d))
d, st = usb.control(setup_packet(0x81, 6, 0x2200, 0, 0x1ef)); check('stock HID report descriptor (495 B, several packets)', d == rpt and st == 'ok', (len(d), st))
check('stock EP1 is an INTERRUPT endpoint (type 11)', (usb.ep[1] & EP_TYPE) == 0x0600, hex(usb.ep[1]))
d, st = usb.control(setup_packet(0x00, 9, 1, 0, 0)); check('stock SET_CONFIGURATION', st == 'ok' and mu.mem_read(0x200001c9, 1)[0] != 0)
usb.ep[0] = (usb.ep[0] & ~(STAT_TX | STAT_RX)) | VALID_RX
d, st = usb.control(setup_packet(0x01, 11, 0, 1, 0)); check('stock SET_INTERFACE on interface 1 (DFU) is refused (only interface 0 accepted)', st == 'stall', st)
print('ALL PASS' if ok else 'SOME FAILED')
