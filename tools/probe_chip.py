#!/usr/bin/env python3
"""Asks the running patched device about itself with the read-only PEEK diagnostic (needs firmware with protocol command 0x1E): which
chip it really is, how big its flash is, whether anything is write- or read-protected, which flash pages are blank, and how much RAM
nobody has ever touched since power-up (RAM is zero at boot, so a non-zero byte means something wrote there, the stack's deepest
non-zero byte is its high-water mark). Only a summary is printed; no memory content is stored.

    probe_chip.py [--registers]   (--registers also reads DBGMCU_IDCODE and the FLASH registers: only with firmware newer than 2026-10-18;
                                   older builds bus-fault on it and the watchdog resets the device)
                             (needs mido + python-rtmidi; the device on this computer, no other MIDI program using SysEx)"""
import os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'midi_patch'))
import mmk3_config as mc

DEVIDS = {0x410: 'STM32F1 medium density (16-128 KB flash)', 0x412: 'STM32F1 low density (16-32 KB)', 0x414: 'STM32F1 high density (256-512 KB)',
          0x418: 'STM32F1 connectivity line', 0x420: 'STM32F1 value line, medium density', 0x428: 'STM32F1 value line, high density', 0x430: 'STM32F1 XL density (768 KB-1 MB)'}

def main(registers=False):
    d = mc.Device(timeout=2.0)
    u16 = lambda b, o=0: struct.unpack_from('<H', b, o)[0]
    u32 = lambda b, o=0: struct.unpack_from('<I', b, o)[0]
    cpu = u32(d.peek(0xE000ED00, 4))
    if registers:       # needs firmware that reads registers as words; older builds bus-fault (the watchdog resets the device)
        idc = u32(d.peek(0xE0042000, 4))
        print(f'DBGMCU_IDCODE {idc:#010x}: device id {idc & 0xFFF:#05x} = {DEVIDS.get(idc & 0xFFF, "unknown")}, revision {idc >> 16:#06x}')
    print(f'CPUID {cpu:#010x}: implementer {cpu >> 24:#x}, part {(cpu >> 4) & 0xFFF:#x} ({"Cortex-M3" if (cpu >> 4) & 0xFFF == 0xC23 else "?"}), r{(cpu >> 20) & 15}p{cpu & 15}')
    sysmem = d.peek(0x1FFFF7E0, 32)
    print(f'flash size register: {u16(sysmem)} KB | unique ID: {sysmem[8:20].hex()}')
    ob = d.peek(0x1FFFF800, 16)
    print(f'option bytes: RDP {ob[0]:#04x} ({"no read protection" if ob[0] == 0xA5 else "READ-PROTECTED"}), USER {ob[2]:#04x}, WRP bytes {ob[8]:02x} {ob[10]:02x} {ob[12]:02x} {ob[14]:02x}')
    if registers:
        fl = d.peek(0x40022000, 0x24); obr, wrpr = u32(fl, 0x1C), u32(fl, 0x20)
        print(f'FLASH_OBR {obr:#010x} (RDPRT bit {(obr >> 1) & 1}), FLASH_WRPR {wrpr:#010x} ({"all 4 KB sectors writable" if wrpr == 0xFFFFFFFF else "some sectors WRITE-PROTECTED (bit = 0)"})')
    # the flash: which 1 KB pages are blank
    pages = []
    for p in range(128):
        base = 0x08000000 + p * 1024
        data = d.peek(base, 1024)
        pages.append('.' if data == b'\xff' * 1024 else '#')
    print('flash pages (1 KB each, from 0x08000000; # = holds data, . = blank):')
    for row in range(0, 128, 32): print(f'  {0x08000000 + row * 1024:#010x}  ' + ''.join(pages[row:row + 32]))
    used = [i for i, c in enumerate(pages) if c == '#']
    print(f'  data pages: {len(used)}; blank pages: {128 - len(used)}; the blank ones between the application and the save page: '
          f'{sum(1 for i in range(0x0E, 0x7B) if pages[i] == ".")} KB (pages 0x0800e000..0x0801e7ff)')
    # RAM: zero at power-up
    ram = bytearray()
    for a in range(0x20000000, 0x20005000, 64): ram += d.peek(a, 64)
    nz = [i for i, b in enumerate(ram) if b]
    stack = ram[0x1818:0x1C18]; deepest = next((i for i, b in enumerate(stack) if b), None)
    print(f'RAM 0x20000000-0x20004fff: stack 0x20001818-0x20001c18, deepest byte written so far: ' + ('none' if deepest is None else f'{0x20001818 + deepest:#x} = {0x1C18 - 0x1818 - deepest} bytes used of 1024'))
    runs, start = [], None
    for i in range(0x1C18, 0x5000):
        z = ram[i] == 0
        if z and start is None: start = i
        if (not z or i == 0x4FFF) and start is not None:
            end = i if not z else i + 1
            if end - start >= 128: runs.append((0x20000000 + start, end - start))
            start = None
    print('zero (never written since power-up) runs of 128 bytes or more above the stack:')
    for a, n in runs: print(f'  {a:#010x} .. {a + n - 1:#010x}  {n} bytes')
    print(f'  total above the stack: {sum(n for _, n in runs)} bytes; our state lives at 0x20004200 (about 1.7 KB)')

if __name__ == '__main__':
    main(registers='--registers' in sys.argv)
