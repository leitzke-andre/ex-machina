#!/usr/bin/env python3
"""Which programs have a USB device open (macOS), found by VID:PID: the check flash_guarded.sh makes before it writes.

    usb_guard.py [--vid 0x17cc] [--pid 0x1700 --pid 0x1702]      exit 0: present and free, 3: another program has it open, 4: not found

The device is looked up by its ids in the I/O Registry (`ioreg -a -r -c IOUSBHostDevice -l`), in normal mode and in the bootloader, not by its
name, so a renamed device or one already in its bootloader is still found, and a device that cannot be found stops the flash (fail closed).
Every user client below the device (on the device itself or on one of its interfaces) counts, except macOS's MIDI service, which always
holds a class-compliant MIDI device and copes with it resetting. Standard library only."""
import argparse, plistlib, subprocess, sys

IGNORED = ('MIDIServer',)


def _walk(e):
    yield e
    for c in e.get('IORegistryEntryChildren', []) or []: yield from _walk(c)


def scan(registry, vid, pids):
    """registry: the parsed `ioreg -a` output (a list of entries, or one). Returns (devices found as (vid, pid, name), the user clients that
    count, as "pid N, Program" strings)."""
    roots = registry if isinstance(registry, list) else [registry]
    found, clients = [], []
    def visit(e):
        if e.get('idVendor') == vid and e.get('idProduct') in pids and 'bInterfaceNumber' not in e:     # the device (its interfaces carry its ids too)
            found.append((vid, e.get('idProduct'), e.get('USB Product Name') or e.get('IORegistryEntryName', '?')))
            for c in _walk(e):                                            # every user client below it, once
                who = c.get('IOUserClientCreator')
                if who and not any(who.endswith(', ' + i) for i in IGNORED): clients.append(who)
            return
        for c in e.get('IORegistryEntryChildren', []) or []: visit(c)
    for root in roots: visit(root)
    return found, clients


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--vid', type=lambda x: int(x, 0), default=0x17CC)
    ap.add_argument('--pid', type=lambda x: int(x, 0), action='append', help='product id (normal mode, bootloader); default 0x1700 and 0x1702')
    a = ap.parse_args(argv)
    pids = tuple(a.pid or (0x1700, 0x1702))
    out = subprocess.run(['ioreg', '-a', '-r', '-c', 'IOUSBHostDevice', '-l'], capture_output=True, check=False).stdout
    found, clients = scan(plistlib.loads(out) if out.strip() else [], a.vid, pids)
    if not found:
        print(f'no device {a.vid:04x}:{"/".join(f"{p:04x}" for p in pids)} found: NOT flashing'); return 4
    for v, p, name in found: print(f'found {name} ({v:04x}:{p:04x})')
    if clients:
        print('something else has the device open, NOT flashing:')
        for c in sorted(set(clients)): print(f'   {clients.count(c)} {c}')
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
