#!/usr/bin/env python3
"""Read-only dump of the USB descriptors of a connected Maschine Mikro MK3 (stock or patched) and, with --image, a check that
each descriptor appears byte for byte in a firmware image (stock: the carved image; patched: build_patch.py's output).

Only standard GET_DESCRIPTOR requests are sent (the same ones every host sends at enumeration); nothing is written to the
device, no interface is claimed, and string descriptors (which include the serial number) are not requested.
Needs `pip install pyusb` and libusb (macOS: brew install libusb, then DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib).

    usb_dump.py                      # print the descriptors
    usb_dump.py --image stock.bin    # and say where in the image each one is (flash base 0x08003000)
"""
import argparse, struct, sys

VID, FLASH_BASE = 0x17CC, 0x08003000
NAMES = {1: 'device', 2: 'configuration', 4: 'interface', 5: 'endpoint', 0x24: 'class-specific interface', 0x25: 'class-specific endpoint'}

def get_descriptor(dev, dtype, index, length, recipient=0x80, windex=0):
    return bytes(dev.ctrl_transfer(recipient, 6, (dtype << 8) | index, windex, length, timeout=3000))

def descriptors(cfg):
    """Yield (offset, bytes) for every descriptor in a configuration descriptor blob."""
    i = 0
    while i + 2 <= len(cfg) and cfg[i]:
        yield i, cfg[i:i + cfg[i]]
        i += cfg[i]

def describe(body, iface_class):
    """A short description; type 0x21 means HID or DFU depending on the interface it follows."""
    n, t = body[0], body[1]
    if t == 2: return f'configuration: total {struct.unpack_from("<H", body, 2)[0]} B, {body[4]} interfaces, bMaxPower {body[8]} x 2 mA'
    if t == 4: return f'interface {body[2]} alt {body[3]}: class {body[5]:#04x} sub {body[6]:#04x} protocol {body[7]:#04x}, {body[4]} endpoints'
    if t == 5: return f'endpoint {body[2]:#04x}: attributes {body[3]:#04x}, max packet {struct.unpack_from("<H", body, 4)[0]}, interval {body[6]}'
    if t == 0x21 and n == 9 and iface_class == 3: return f'HID {struct.unpack_from("<H", body, 2)[0]:#06x}, report descriptor length {struct.unpack_from("<H", body, 7)[0]}'
    if t == 0x21 and n == 9 and iface_class == 0xFE:
        tmo, xfer, ver = struct.unpack_from('<HHH', body, 3)
        return f'DFU functional: attributes {body[2]:#04x}, detach timeout {tmo} ms, transfer size {xfer}, DFU version {ver:#06x}'
    return NAMES.get(t, f'type {t:#04x}')

def main():
    import usb.core            # imported here so the parsing helpers can be tested without pyusb
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='firmware image to search for the descriptors (flash base 0x08003000)')
    ap.add_argument('--pid', type=lambda x: int(x, 0), help='USB product id (default: any 17cc device)')
    a = ap.parse_args()
    dev = usb.core.find(idVendor=VID, idProduct=a.pid) if a.pid else usb.core.find(idVendor=VID)
    if dev is None: sys.exit('no Native Instruments (17cc) device found')
    found = {}

    dd = get_descriptor(dev, 1, 0, 18)
    cfg = get_descriptor(dev, 2, 0, struct.unpack_from('<H', get_descriptor(dev, 2, 0, 9), 2)[0])
    found['device descriptor'], found['configuration descriptor'] = dd, cfg
    print(f'device descriptor ({len(dd)} B): {dd.hex()}')
    print(f'  bcdUSB {dd[3]:x}.{dd[2]:02x}, class {dd[4]:#04x}/{dd[5]:#04x}/{dd[6]:#04x}, max packet {dd[7]}, '
          f'VID:PID {struct.unpack_from("<H", dd, 8)[0]:04x}:{struct.unpack_from("<H", dd, 10)[0]:04x}, bcdDevice {struct.unpack_from("<H", dd, 12)[0]:#06x}')
    print(f'configuration descriptor ({len(cfg)} B):')
    iface_class, hid_if = 0, None
    for off, body in descriptors(cfg):
        if body[1] == 4:
            iface_class = body[5]
            if iface_class == 3 and hid_if is None: hid_if = body[2]
        print(f'  {off:3d}: {body.hex()}   {describe(body, iface_class)}')

    if hid_if is not None:           # HID report descriptor: a standard request to the interface, no claim needed
        try:
            rd = get_descriptor(dev, 0x22, 0, 1024, recipient=0x81, windex=hid_if)
            found['HID report descriptor'] = rd
            print(f'HID report descriptor of interface {hid_if}: {len(rd)} B, starts {rd[:8].hex()}')
        except usb.core.USBError as e:
            print(f'HID report descriptor: not read ({e})')

    if a.image:
        img = open(a.image, 'rb').read()
        print(f'\nsearch in {a.image} ({len(img)} B):')
        for name, blob in found.items():
            off = img.find(blob)
            print(f'  {name} ({len(blob)} B): ' + (f'found at flash {FLASH_BASE + off:#010x} (image offset {off:#x})' if off >= 0 else 'NOT in the image'))

if __name__ == '__main__':
    main()
