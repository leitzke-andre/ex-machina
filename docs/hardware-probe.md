# Hardware probe: what the chip is and how much room the firmware has

Measured on the real device on 2026-10-18 with the read-only `PEEK` diagnostic (`docs/remap-protocol.md`, command `1E`) and `tools/probe_chip.py`. Everything under "Measured" is a reading from the running unit (firmware 1.20 patched, MIDI build with `PEEK`, 46,736 bytes); everything under "Derived" is arithmetic or reasoning on top of it; "Not known" lists what the probe could not answer.

## How it was done
- The firmware answers `PEEK <address> <length 1..64>` with the bytes, for **whitelisted ranges only** (a read of anything else could bus-fault the chip and hang it until the watchdog resets it, so the firmware refuses with status 1): flash `0x08000000-0x0801FFFF`, RAM `0x20000000-0x20004FFF`, flash size and unique ID `0x1FFFF7E0-0x1FFFF7FF`, option bytes `0x1FFFF800-0x1FFFF80F`, FLASH registers `0x40022000-0x4002202F`, DBGMCU_IDCODE `0xE0042000`, CPUID `0xE000ED00`. Peripheral registers must be read as aligned whole words (current source; the build that was probed read them byte by byte, see "Findings that changed the code").
- `python tools/probe_chip.py` prints a summary (add `--registers` only on firmware newer than 2026-10-18). It stores no memory content: only counts and maps are printed, because the flash holds NI's firmware.
- Nothing was written to the device by the probe; the only flash writes of that day were the firmware updates themselves.

## Measured
**The chip**
| Item | Reading | Meaning |
|---|---|---|
| CPUID | `0x411FC231` | ARM Cortex-M3, revision r1p1. Genuine STM32F103 parts report r1p1; GD32F103 clones report r2p1. So most likely a genuine ST part |
| Flash size register (`0x1FFFF7E0`) | 128 KB | STM32F103xB class, as the static analysis said |
| Option bytes (`0x1FFFF800`) | `A5 5A FF 00 FF 00 FF 00 FF 00 FF 00 FF 00 FF 00` | **No read protection** (RDP `0xA5`), USER `0xFF`, **no write protection** on any 4 KB sector (WRP0-3 `0xFF`) |
| Unique ID | read (96 bit), not recorded here | identifies the unit; not needed by anything |
| DBGMCU_IDCODE | read as `0x00000000` with byte access | not a valid reading; to be repeated with whole-word reads |

**Flash, in 1 KB pages from `0x08000000`** (`#` holds data, `.` is blank, as printed by the probe):
```
0x08000000  ##########..####################     pages   0-31
0x08008000  ##########################......     pages  32-63
0x08010000  ................................     pages  64-95
0x08018000  ...........................##.##     pages  96-127
```
| Pages | Addresses | What |
|---|---|---|
| 0-9 | `0x08000000-0x080027FF` | NI's bootloader (about 10 KB) |
| 10-11 | `0x08002800-0x08002FFF` | blank (bootloader area, not ours to use) |
| 12-57 | `0x08003000-0x0800E7FF` | the application: NI's 40,392 bytes, then ours (config, descriptors, velocity table, code), ending at `0x0800E6CC` |
| 58-122 | `0x0800E800-0x0801EBFF` | **blank: 65 pages = 65 KB** |
| 123 | `0x0801EC00` | our saved configuration (one record, when something is saved) |
| 124 | `0x0801F000` | NI's settings page A (LED brightness trim, pad offsets) |
| 125 | `0x0801F400` | blank (no code of the stock firmware refers to it) |
| 126 | `0x0801F800` | NI's settings page B (feature blocks, serial/ID bytes, version) |
| 127 | `0x0801FC00` | the bootloader handshake page |

**RAM** (20 KB, `0x20000000-0x20004FFF`)
- **RAM is not zeroed at power-up.** Only the firmware's zero-initialised region (the stock variables and the stack, up to `0x20001C18`) starts as zero; everything above holds random power-on data (every block above the stack read as almost entirely non-zero). A "never written" test therefore works for the stack only.
- **Stack** `0x20001818-0x20001C18` (1 KB): the deepest byte written since power-up was `0x20001A58`, i.e. **448 of 1,024 bytes in use** (read while the probe itself was running requests).
- **`0x20001C18-0x200041FF` (9,704 bytes)**: 0 bytes changed in 10 s, while the stock's own region `0x20000000-0x20001C17` changed 975 bytes in 2 s. Nothing writes there in normal use. (Not a proof against code that writes rarely, but the static analysis found no reference to it and the patch's own state has lived next to it for the whole project.)
- Our state occupies `0x20004200` for about 1.7 KB (to about `0x200048AC`); about 1.9 KB above it, to `0x20005000`, is unused.

## Derived: the budget for "how smart can the firmware be"
| Resource | Total | Used today | Free to use | Remark |
|---|---|---|---|---|
| Flash for code and data | 65 KB between our image and the save page | 5.8 KB of code, 0.3 KB config, 0.3 KB descriptors, 0.25 KB velocity table | **about 65 KB** (the image would have to end before `0x0801EC00`) | a bigger image also takes longer to flash (about 9 s per 46 KB over DFU) |
| Flash for saved data | pages 123 and 125 are usable; 124/126/127 belong to NI | page 123 (one config record) | page 125 (1 KB) is blank and unreferenced, but it is in the same 4 KB sector as NI's pages; page 123 has 1 KB for presets (a record was 164 bytes then, 264 now: three or four fit; the second half of the page now holds the curve log) | on-device presets would need a record format with several slots |
| RAM | 20 KB | stock about 7 KB (to `0x20001C18`), ours 1.7 KB | **about 9.7 KB** below our state plus **about 1.9 KB** above | RAM content is undefined at power-up: our code must initialise what it uses |
| Stack | 1 KB | worst case 584 B (emulator), 448 B seen on the device | about 400 B | deep recursion or big local buffers (a 512-byte frame buffer) must live in RAM, not on the stack |
| CPU | 72 MHz Cortex-M3, stock main loop | one report costs about 0.7-2.2k instructions (emulator), an idle tick 27 | the loop has no hard deadline except the pad hit detector (waits about 6 ms), the SysTick-driven timers and the **1 s watchdog** | flash erase/program stalls the CPU 20-40 ms per page; keep long work out of interrupts |

In short: code size is not a constraint for any feature discussed so far (display text and graphics with a font, preset slots, a USB keyboard interface, a small scripting layer would each take a few KB); **RAM and stack are the tighter limits**, and anything that needs a framebuffer, a large table or deep call chains has to be planned against the 9.7 KB of free RAM and the 400 bytes of stack headroom. USB endpoints and packet memory are a separate limit (the USB peripheral's 512 bytes of packet memory is shared by all endpoints; the stock library uses part of it for EP0 and EP1).

## Findings that changed the code
- **A byte-wide read of the FLASH registers bus-faults the chip.** The first `PEEK` build read the flash-controller registers with byte loads; the chip faulted, the watchdog reset the device within a second, and it came back with its saved mapping intact (a useful accident: the watchdog recovery works). The source now reads every peripheral register as one aligned 32-bit word and refuses unaligned reads; the corrected build exists (`PEEK` tests in `test_config.py`) but has not been flashed.
- **"RAM is zero at power-up" is false** (see above). The stack high-water mark was the only place where the zero assumption held.
- The static estimate "free RAM above `0x20001C18`" is now backed by a measurement.

## Not known
- DBGMCU_IDCODE and the FLASH registers (OBR, WRPR): need the corrected build.
- Whether the part is really ST (probably) or a compatible: the option bytes and CPUID fit ST; the IDCODE would confirm.
- The current draw (no power meter).
- Whether anything writes to the 9.7 KB region rarely (an event not seen in 10 s of idling). A stronger test would fill it with a pattern at boot and compare after heavy use.
- The USB packet-memory layout the stock library uses (matters if more endpoints are added).

## Repeating it
```
python tools/probe_chip.py              # needs the device running a PEEK build, mido + python-rtmidi, no other program using SysEx
python tools/probe_chip.py --registers  # only with the corrected build: also DBGMCU_IDCODE and the FLASH registers
```
The flash map changes whenever the image grows (the "application" pages) or something is saved (page 123 turns `#`); the other rows should stay as above.
