"""Tests of usb_guard.py on synthetic I/O Registry data (no device, no ioreg needed):   python3 flasher/test_usb_guard.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usb_guard as G

ok = True
def check(name, got, want):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}'))

def dev(pid, name='Maschine Mikro MK3', clients=(), intf_clients=()):
    intf = [{'IOObjectClass': 'IOUSBHostInterface', 'idVendor': 0x17CC, 'idProduct': pid, 'bInterfaceNumber': 2, 'bInterfaceClass': 254,   # (interfaces carry the device's ids, as on the real registry)
             'IORegistryEntryChildren': [{'IOUserClientCreator': c} for c in intf_clients]}]
    return {'IORegistryEntryName': name, 'USB Product Name': name, 'idVendor': 0x17CC, 'idProduct': pid,
            'IORegistryEntryChildren': intf + [{'IOUserClientCreator': c} for c in clients]}
other = {'IORegistryEntryName': 'Keyboard', 'idVendor': 0x05AC, 'idProduct': 0x1234, 'IORegistryEntryChildren': [{'IOUserClientCreator': 'pid 1, Busy'}]}
P = (0x1700, 0x1702)
check('the device is found once, though its interfaces carry the same ids', len(G.scan([dev(0x1700)], 0x17CC, P)[0]), 1)
check('a free device: found, no clients', G.scan([dev(0x1700), other], 0x17CC, P), ([(0x17CC, 0x1700, 'Maschine Mikro MK3')], []))
check('MIDIServer does not count', G.scan([dev(0x1700, clients=['pid 300, MIDIServer'])], 0x17CC, P)[1], [])
check('a browser holding the device counts (on the device or on an interface)', G.scan([dev(0x1700, clients=['pid 9, Google Chrome'], intf_clients=['pid 9, Google Chrome'])], 0x17CC, P)[1], ['pid 9, Google Chrome'] * 2)
check('found by its ids, whatever its name, and in the bootloader too', G.scan([dev(0x1702, name='DFU device')], 0x17CC, P)[0], [(0x17CC, 0x1702, 'DFU device')])
check('another device\'s clients are not counted, and without the device nothing is found (the script then refuses: fail closed)', G.scan([other], 0x17CC, P), ([], []))
check('one entry instead of a list is read the same', G.scan(dev(0x1700), 0x17CC, P)[0], [(0x17CC, 0x1700, 'Maschine Mikro MK3')])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
