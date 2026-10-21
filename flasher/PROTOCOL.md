# The Maschine Mikro MK3 bootloader, as observed

Everything here was seen on one real unit (firmware 1.20, macOS host) or read from NI's updater and firmware; none of it comes from NI documentation.

## Two USB modes
| Mode | VID:PID | DFU interface |
|---|---|---|
| normal (the firmware runs) | `17cc:1700` | class `FE`/1/**1** (DFU runtime); attributes `0x09` (can download, **will detach**), detach timeout 255 ms, transfer size 64, DFU 1.10 |
| bootloader | `17cc:1702` | class `FE`/1/**2** (DFU mode) |

The interface number depends on the firmware (stock: HID is 0 and DFU is 1; the Ex-Machina firmware keeps DFU runtime and has it as 2), so the client finds it by
scanning the configuration descriptor, like NI's `queryDFUInfo`. **The transfer size is bytes 5-6 of the 9-byte DFU functional descriptor**; bytes 7-8 are the
DFU version (`0x0110`): the first version of the client mixed them up and tried 272-byte blocks.

## Flashing, step by step
1. `DFU_DETACH` (class request 0, `wValue` = the detach timeout, to the runtime interface). Because the descriptor says *will detach*, the device resets
   by itself; the firmware writes the 8-byte handshake `55 5a a5 aa 59 95 3a a3` to the page at `0x0801FC00` and resets, and the bootloader sees it.
2. The bootloader enumerates as `17cc:1702` (a **new USB device**: a browser has to be asked to select it again).
3. Standard `DFU_DNLOAD` blocks of 64 bytes, numbered from 0, with `DFU_GETSTATUS` after each one (honour the poll timeout while the state is `dfuDNBUSY`).
   A device left in `dfuERROR` is cleared with `CLRSTATUS`, one in a download state with `ABORT`.
4. A zero-length `DNLOAD` ends the data. **The bootloader then resets the chip by itself as soon as the image is programmed**, so the next `GETSTATUS`
   fails with an I/O error: that is the normal ending. The host waits for the device to enumerate again (about 6 s for the whole sequence).
5. Back as `17cc:1700` with the new firmware's descriptors. Still `17cc:1702` after 20 s = the image was not accepted or did not boot.

## What the bootloader accepts
- **No signature or content check was seen**: modified images of 40,392 up to about 67,000 bytes were accepted. Nothing in the bootloader, which occupies
  `0x08000000`-`0x08002FFF`, was ever written; the application starts at `0x08003000` (initial stack pointer at offset 0, reset vector at offset 4).
- The image length is not sent anywhere; the updater passes the stock image's length (`0x9dc8`). The client sends what the file has.
- Above the application the chip's flash holds NI's settings pages (`0x0801F000`, `0x0801F800`) and the handshake page (`0x0801FC00`); the
  Ex-Machina firmware keeps its own data (preset slots, patterns, the saved mapping) from `0x0801D800`, so the application area of the profile ends there.
- The bootloader erases only the pages an image covers: the pages above it (both firmwares' saved settings) survive a flash.
- The end of a download: the chip resets as soon as the image is programmed, so the zero-length DNLOAD or the GETSTATUS after it fails with the device
  gone (an I/O error, or "no such device"). Only that counts as the normal ending; a STALL there means the device is still present and refused.
- NI's updater offers an update only for a device that reports `bcdDevice` below `0x0052`; a device found in DFU mode is flashed without that check.

## Practical notes
- A program that has the device open (a browser tab with WebUSB access, NI's software) can grab the bootloader's USB device in the middle of a flash.
  `flash_guarded.sh` checks the I/O registry (macOS, `usb_guard.py`) and refuses; CoreMIDI's `MIDIServer` always holds a class-compliant MIDI device and is
  ignored. The device is found by its ids, in normal mode or in the bootloader, and a device that cannot be found is refused too (fail closed).
  Any user client counts, so a browser that merely has the device open (Chrome after a page was given access) blocks it; telling an open device from a
  claimed DFU interface would need checking on the hardware where each shows up in the registry.
- `pyusb` needs libusb: on macOS `brew install libusb` and `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`. macOS refuses control requests to the
  HID interface ("Access denied"); the DFU interface is free.
- In the browser, WebUSB hides class-specific descriptors, so the configuration descriptor is read with a standard `GET_DESCRIPTOR` control transfer.
- If the device does not come back: wait about three minutes, replug it, and flash the original firmware again (this client or NI's updater).
