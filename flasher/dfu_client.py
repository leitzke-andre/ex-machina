#!/usr/bin/env python3
"""Minimal USB DFU 1.1 client for the Native Instruments Maschine Mikro MK3 bootloader, mirroring what NI's updater does
(`MM3Updater`: DFUDevice::sendDFUDetach / reconnectInDFUMode / writeImage / returnToAPPMode).

NI's own updater can only flash the image it carries, so another image needs another client. This one flashed the real device many times
(see README.md and PROTOCOL.md in this directory). Everything here is a DRY RUN unless --yes-flash is given. The protocol logic is tested
against a mock device in `test_dfu_client.py`. The device it knows is the profile MIKRO_MK3 below; other values can be given on the command
line (--vid --pid --dfu-pid --app-base --app-limit).

    dfu_client.py info                         # list the device and its DFU interface (read-only)
    dfu_client.py flash image.bin              # dry run: validate the image and print the plan
    dfu_client.py flash image.bin --yes-flash  # perform it (device reboots into the bootloader first)

Needs `pip install pyusb` and libusb only for the real transport; the logic works with any transport
object that has ctrl_in/ctrl_out.
"""
import argparse, collections, struct, sys, time

# What is specific to a device: its USB ids (normal mode / DFU mode) and the flash area an application image may occupy.
Profile = collections.namedtuple('Profile', 'name vid pid_runtime pid_dfu app_base app_limit')
MIKRO_MK3 = Profile('Maschine Mikro MK3', 0x17CC, 0x1700, 0x1702, 0x08003000, 0x0801F000)   # the NI settings pages start at 0x0801F000
VID, PID_RUNTIME, PID_DFU, APP_BASE, APP_LIMIT = MIKRO_MK3.vid, MIKRO_MK3.pid_runtime, MIKRO_MK3.pid_dfu, MIKRO_MK3.app_base, MIKRO_MK3.app_limit
DFU_DETACH, DFU_DNLOAD, DFU_GETSTATUS, DFU_CLRSTATUS, DFU_GETSTATE, DFU_ABORT = 0, 1, 3, 4, 5, 6
S_APP_IDLE, S_APP_DETACH, S_IDLE, S_DNLOAD_SYNC, S_DNBUSY, S_DNLOAD_IDLE, S_MANIFEST_SYNC, S_MANIFEST, S_MANIFEST_WAIT_RESET, S_UPLOAD_IDLE, S_ERROR = range(11)


class DfuError(Exception):
    pass


def validate_image(img, profile=MIKRO_MK3):
    """Sanity checks on a Cortex-M application image for this device. Returns a list of problems."""
    APP_BASE, APP_LIMIT = profile.app_base, profile.app_limit
    problems = []
    if len(img) < 0x200: problems.append('image is too small to contain a vector table')
    if len(img) > APP_LIMIT - APP_BASE: problems.append(f'image is larger than the application area ({APP_LIMIT - APP_BASE:#x} bytes)')
    if len(img) >= 8:
        sp, reset = struct.unpack_from('<II', img, 0)
        if not (0x20000000 <= sp <= 0x20005000 and sp % 4 == 0): problems.append(f'initial stack pointer {sp:#x} is not in RAM')
        if not (reset & 1 and APP_BASE <= reset < APP_BASE + len(img)): problems.append(f'reset vector {reset:#x} is not Thumb code inside the image')
    return problems


class UsbTransport:
    """pyusb transport for one interface of one device."""
    def __init__(self, dev, interface):
        self.dev, self.interface = dev, interface
    def ctrl_out(self, request, value, data=b''):
        return self.dev.ctrl_transfer(0x21, request, value, self.interface, data, timeout=5000)
    def ctrl_in(self, request, length):
        return bytes(self.dev.ctrl_transfer(0xA1, request, 0, self.interface, length, timeout=5000))


def get_status(t):
    r = t.ctrl_in(DFU_GETSTATUS, 6)
    if len(r) != 6: raise DfuError(f'short GETSTATUS reply ({len(r)} bytes)')
    return r[0], r[1] | (r[2] << 8) | (r[3] << 16), r[4]          # status, poll timeout ms, state


def clear_to_idle(t, sleep=time.sleep):
    status, _, state = get_status(t)
    if state == S_ERROR:
        t.ctrl_out(DFU_CLRSTATUS, 0); status, _, state = get_status(t)
    if state in (S_DNLOAD_IDLE, S_UPLOAD_IDLE, S_DNLOAD_SYNC):
        t.ctrl_out(DFU_ABORT, 0); status, _, state = get_status(t)
    if state != S_IDLE: raise DfuError(f'device is not in dfuIDLE (state {state}, status {status})')


def download(t, img, block=64, progress=None, sleep=time.sleep):
    """Standard DFU download: blocks of `block` bytes, GETSTATUS polling after each, then the zero-length
    block that starts the manifestation. Returns when the device reports manifest-wait-reset / idle."""
    clear_to_idle(t, sleep)
    n = 0
    for off in range(0, len(img), block):
        t.ctrl_out(DFU_DNLOAD, n, img[off:off + block]); n += 1
        while True:
            status, poll, state = get_status(t)
            if status != 0: raise DfuError(f'device reported status {status:#x} after block {n - 1} (state {state})')
            if state == S_DNBUSY: sleep(min(poll, 1000) / 1000.0); continue
            if state == S_DNLOAD_IDLE: break
            raise DfuError(f'unexpected state {state} after block {n - 1}')
        if progress: progress(min(off + block, len(img)), len(img))
    t.ctrl_out(DFU_DNLOAD, n, b'')                                   # zero-length: end of data
    for _ in range(100):
        try: status, poll, state = get_status(t)
        except OSError:
            # The Maschine's bootloader resets the chip as soon as the image is programmed, so the status poll after the last block
            # fails with an I/O error (seen on the real device, 2026-10-17). That is the normal ending: the caller must check that
            # the device comes back and what it reports.
            return 'reset'
        if status != 0: raise DfuError(f'device rejected the image: status {status:#x} (state {state})')
        if state in (S_APP_IDLE, S_IDLE, S_MANIFEST_WAIT_RESET): return state
        if state in (S_MANIFEST_SYNC, S_MANIFEST): sleep(min(max(poll, 10), 1000) / 1000.0); continue
        raise DfuError(f'unexpected state {state} during manifestation')
    raise DfuError('manifestation did not finish')


def wait_for_device(find, pids, timeout=20.0, sleep=time.sleep, step=0.5, vid=VID):
    """Poll find(idVendor=VID, idProduct=pid) for each pid until a device shows up or `timeout` seconds have passed; returns it or None."""
    waited = 0.0
    while True:
        for pid in pids:
            dev = find(idVendor=vid, idProduct=pid)
            if dev is not None: return dev
        if waited >= timeout: return None
        sleep(step); waited += step

def parse_dfu_functional(extra):
    """DFU 1.1 functional descriptor, 9 bytes: bLength, 0x21, bmAttributes, wDetachTimeOut, wTransferSize, bcdDFUVersion.
    Returns (attributes, detach timeout, transfer size, DFU version) or None. (An earlier version read bcdDFUVersion as the
    transfer size; the first run against the real device printed 272 = 0x0110 instead of 64.)"""
    if len(extra) < 9 or extra[1] != 0x21: return None
    return (extra[2],) + struct.unpack_from('<HHH', extra, 3)

def find_dfu_interface(dev):
    """(interface number, runtime?, bmAttributes, wDetachTimeout, wTransferSize) from the configuration, like NI's queryDFUInfo."""
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass == 0xFE and intf.bInterfaceSubClass == 1 and intf.bInterfaceProtocol in (1, 2):
                f = parse_dfu_functional(bytes(intf.extra_descriptors))
                if f:
                    attrs, tmo, xfer, _version = f
                    return intf.bInterfaceNumber, intf.bInterfaceProtocol == 1, attrs, tmo, xfer
    raise DfuError('no DFU interface found')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('info', 'flash')); ap.add_argument('image', nargs='?')
    ap.add_argument('--yes-flash', action='store_true', help='actually write to the device (exit status 0 only if the device is back in normal mode)')
    ap.add_argument('--vid', type=lambda x: int(x, 0), default=MIKRO_MK3.vid); ap.add_argument('--pid', type=lambda x: int(x, 0), default=MIKRO_MK3.pid_runtime, help='product id in normal mode')
    ap.add_argument('--dfu-pid', type=lambda x: int(x, 0), default=MIKRO_MK3.pid_dfu, help='product id in the bootloader')
    ap.add_argument('--app-base', type=lambda x: int(x, 0), default=MIKRO_MK3.app_base); ap.add_argument('--app-limit', type=lambda x: int(x, 0), default=MIKRO_MK3.app_limit)
    a = ap.parse_args(argv)
    prof = MIKRO_MK3._replace(vid=a.vid, pid_runtime=a.pid, pid_dfu=a.dfu_pid, app_base=a.app_base, app_limit=a.app_limit)
    VID, PID_RUNTIME, PID_DFU, APP_BASE = prof.vid, prof.pid_runtime, prof.pid_dfu, prof.app_base
    if a.cmd == 'flash':
        if not a.image: ap.error('flash needs an image')
        img = open(a.image, 'rb').read()
        problems = validate_image(img, prof)
        print(f'image {a.image}: {len(img)} bytes, flash {APP_BASE:#x}-{APP_BASE + len(img) - 1:#x}')
        for p in problems: print('  PROBLEM:', p)
        if problems: return 2
        if not a.yes_flash:
            print(f'dry run: would send DFU_DETACH to the runtime device ({VID:04x}:{PID_RUNTIME:04x}), wait for the bootloader ({VID:04x}:{PID_DFU:04x}),\n'
                  'download the image in 64-byte blocks, finish with a zero-length block and a DFU_DETACH to leave DFU.\n'
                  'Re-run with --yes-flash to do it.')
            return 0
    import usb.core
    dev = usb.core.find(idVendor=VID, idProduct=PID_RUNTIME) or usb.core.find(idVendor=VID, idProduct=PID_DFU)
    if dev is None: print(f'no {prof.name} found'); return 1
    intf, runtime, attrs, tmo, xfer = find_dfu_interface(dev)
    print(f'found {dev.idVendor:04x}:{dev.idProduct:04x} bcdDevice {dev.bcdDevice:#06x}, DFU interface {intf} ({"runtime" if runtime else "DFU mode"}), '
          f'attributes {attrs:#04x}, transfer size {xfer}')
    if a.cmd == 'info': return 0
    t = UsbTransport(dev, intf)
    if runtime:
        if not attrs & 8: raise DfuError('device does not advertise bitWillDetach; refusing (NI uses a vendor request in that case)')
        t.ctrl_out(DFU_DETACH, tmo)                                  # firmware writes the boot flag and resets
        dev = None
        for _ in range(50):
            time.sleep(0.2); dev = usb.core.find(idVendor=VID, idProduct=PID_DFU)
            if dev: break
        if dev is None: raise DfuError(f'bootloader ({VID:04x}:{PID_DFU:04x}) did not appear')
        intf, _, attrs, tmo, xfer = find_dfu_interface(dev); t = UsbTransport(dev, intf)
    result = download(t, img, block=xfer or 64, progress=lambda d, n: print(f'\r  {d}/{n}', end=''))
    if result == 'reset':
        print('\nthe device reset itself after the last block (the normal ending for this bootloader)')
    else:
        print('\ndownload finished; leaving DFU mode')
        try: t.ctrl_out(DFU_DETACH, tmo)
        except Exception: pass
    back = wait_for_device(usb.core.find, (PID_RUNTIME, PID_DFU), timeout=20, vid=VID)
    if back is None:
        print('the device did not come back within 20 s: wait three minutes, replug it, then restore the original firmware with the vendor\'s updater or this tool'); return 5
    print(f'back as {back.idVendor:04x}:{back.idProduct:04x}, bcdDevice {back.bcdDevice:#06x}')
    if back.idProduct == PID_DFU:
        print(f'it is still in the bootloader ({VID:04x}:{PID_DFU:04x}): the image was not accepted or did not boot; flash the original firmware again'); return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
