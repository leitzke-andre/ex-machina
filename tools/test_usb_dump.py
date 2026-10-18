"""Tests the descriptor parsing helpers of usb_dump.py against the descriptors read from a real, stock Maschine Mikro MK3
(firmware 1.20, bcdDevice 0x0052) on 2026-10-17. No hardware or pyusb needed."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_dump as U

ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

# as read over USB from the stock device (they are byte for byte in NI's firmware image at 0x08008d54 and 0x08008d66)
DEVICE = bytes.fromhex('12010002ef020140cc170017520001020301')
CONFIG = bytes.fromhex('09023b0002010080f0' '090400000203000004' '09211101000122ef01' '07058103400001' '0705010340000a'
                       '0904010000fe010105' '092109ff0040001001')
check('the configuration descriptor is 59 bytes and its wTotalLength says so', len(CONFIG) == 59 and CONFIG[2] == 59)
lines, cls = [], 0
for off, body in U.descriptors(CONFIG):
    if body[1] == 4: cls = body[5]
    lines.append(U.describe(body, cls))
check('seven descriptors are walked', len(lines) == 7, lines)
check('configuration: 2 interfaces, 240 x 2 mA = 480 mA', 'total 59 B, 2 interfaces, bMaxPower 240 x 2 mA' in lines[0], lines[0])
check('interface 0 is HID with 2 endpoints, report descriptor length 495', 'class 0x03' in lines[1] and '2 endpoints' in lines[1] and 'report descriptor length 495' in lines[2], lines[1:3])
check('endpoints: 0x81 interrupt IN interval 1, 0x01 interrupt OUT interval 10, both 64 bytes',
      'endpoint 0x81: attributes 0x03, max packet 64, interval 1' in lines[3] and 'endpoint 0x01: attributes 0x03, max packet 64, interval 10' in lines[4], lines[3:5])
check('interface 1 is the DFU runtime interface (0xfe/1/1) with the functional descriptor: 0x09, 255 ms, transfer size 64, version 1.10',
      'class 0xfe sub 0x01 protocol 0x01' in lines[5] and 'attributes 0x09, detach timeout 255 ms, transfer size 64, DFU version 0x0110' in lines[6], lines[5:7])
check('the device descriptor is 18 bytes: USB 2.0, class EF/02/01, 17cc:1700, bcdDevice 0x0052',
      len(DEVICE) == 18 and DEVICE[2:4] == b'\x00\x02' and DEVICE[4:7] == b'\xef\x02\x01' and DEVICE[8:12] == bytes.fromhex('cc170017') and DEVICE[12:14] == b'\x52\x00')
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
