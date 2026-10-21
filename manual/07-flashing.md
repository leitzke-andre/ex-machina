# 7. Flashing and recovery

The controller has two parts in its flash: **NI's bootloader**, at the bottom, which is never written by anything in this project, and the
**application** above it, which is what gets replaced. The bootloader is a standard USB DFU device, and the flashing tools speak that protocol
directly, so NI's updater is not needed for any of this.

> **First, keep a copy of NI's original firmware.** On the setup page's *Firmware* tab, step 1, **Save a copy of NI's original firmware** downloads
> `MM3_firmware_1.20_stock.bin` (40,392 bytes, SHA-256 `76ebf72d33961639a0bd042ba32354dd8dc07569be69175546eb9fc06e5c5917`). Keep it backed up:
> it is what puts the controller back to stock, and NI's updater may stop running on future versions of macOS.

## Three ways to flash
| | Setup page | `flash_guarded.sh` | `dfu_client.py` |
|---|---|---|---|
| Runs on | Chrome / Edge, any OS | macOS | any OS with Python, pyusb and libusb |
| Builds the patched image for you | yes, from your NI updater | no (give it an image) | no |
| Flashes the standalone image | not yet | yes | yes |
| Checks first | image checksum before and after patching; only a Mikro MK3 can be selected | the device is there (by its USB ids) and nothing else has it open | the image's vector table, size and USB identity; dry run unless `--yes-flash` |
| Checks after | the device came back in normal mode (back in its bootloader = failed) | as the client | the device came back in normal mode with the version the image names |

All three do the same thing on the wire: ask the running firmware to restart into the bootloader (`DFU_DETACH`), send the image in 64-byte blocks,
and wait for the controller to come back with the new firmware. The whole run takes about 6 seconds.

## From the setup page
*Firmware* tab:
1. **Choose your firmware file**: NI's updater (the `MM3Updater` file inside the app on a Mac, the `.exe` on Windows) or the 40,392-byte image.
   The page finds NI's image inside it by its checksum, applies Ex-Machina's patch (only Ex-Machina's own bytes; no NI code comes with this
   project) and checks the result against its expected checksum. It shows the image and its checksum.
2. **Select the Maschine…**: the browser's USB chooser.
3. Tick the confirmation and **Flash now**. The controller restarts into its bootloader, which is a new USB device, so the browser asks you to
   select it once more. Then the image is written and the controller restarts by itself; the page waits for it and shows its version.

The same tab has the **Restore NI's original firmware** mode (below).

## From the command line
Setup, once:
```bash
pip install pyusb
brew install libusb          # macOS; on Linux use the distribution's libusb package
```

The DFU client:
```bash
python3 flasher/dfu_client.py info                     # the device, its mode and its DFU interface (reads only)
python3 flasher/dfu_client.py flash image.bin          # dry run: checks the image and prints what it would do
python3 flasher/dfu_client.py flash image.bin --yes-flash
```

On macOS, the guarded wrapper first makes sure no other program has the controller open, which could grab the bootloader in the middle of a flash:
```bash
flasher/flash_guarded.sh image.bin [python with pyusb]
```
If it says *something else has the device open*, it names the program. Usually that is a browser that was given USB access to the controller on
the setup page; quit the browser completely (closing the tab may not be enough) and run it again. macOS's own MIDI service is not counted.
If it says *no device found*, the controller is not connected (or not recognised): it refuses rather than guess.

Output of a good run:
```text
device is free; image patched.bin (87726 bytes, sha256 ...)
found 17cc:1700 bcdDevice 0x0051, DFU interface 2 (runtime), attributes 0x09, transfer size 64
  1024/87726  2048/87726  ...  87726/87726
the device reset itself after the last block (the normal ending for this bootloader)
back as 17cc:1700, bcdDevice 0x0051
```

### Building the images yourself
```bash
python3 tools/carve_fw.py <MM3Updater binary> stock.bin                     # NI's image out of the Mac updater (keep it private)
python3 tools/midi_patch/build_patch.py stock.bin patched.bin               # the patched image
python3 tools/midi_patch/build_patch.py stock.bin standalone.bin --native   # the standalone image (no NI code)
tools/midi_patch/run_tests.sh stock.bin workdir                             # every test, in an emulator
```
Building needs clang with the ARM target and `pip install unicorn pyelftools usb-protocol` for the tests. `build_patch.py --help` lists the
build options (USB identity, default transport, pad base, colours, velocity curve...); almost everything is also changeable later from the setup page.

## Restoring NI's original firmware
- **Setup page**: *Firmware* tab, *Restore NI's original firmware*, then the same steps as a flash.
- **Command line**: `tools/restore_stock.sh [MM3_firmware_1.20_stock.bin] [python]`. It refuses any file but NI's exact 1.20 image (checked by its
  SHA-256), then flashes it with `flash_guarded.sh`.
- **NI's updater** still works too, as long as it runs on your system: the controller keeps NI's USB identity and reports an older version, so the
  updater offers to install 1.20.

Afterwards the controller is exactly the stock device again, and works with NI's software.

## Getting out of trouble
The firmware has three ways back to the bootloader, which always accepts a new image:

| Situation | What to do |
|---|---|
| The controller runs but you want the bootloader | Hold **Shift + Stop + Erase** for 2 seconds: the screen shows `DFU MODE` and the controller restarts into the bootloader |
| The firmware keeps crashing | Nothing: after **three watchdog resets in a row** the firmware puts itself into the bootloader |
| It shows `toucherror`, or the touch strip is dead | Unplug it and plug it back in |
| After a flash it stays in the bootloader | The image was not accepted or does not start: flash a known-good image (or NI's) |
| A flash stopped half-way (cable pulled, an error) | The controller stays in its bootloader, which never starts a half-written firmware: flash again |

In the bootloader the controller appears as USB device `17cc:1702` and **stays there until an image is flashed**,
even across unplugging. From there, flash any image with `dfu_client.py flash image.bin --yes-flash` (it finds the bootloader directly), with
`flash_guarded.sh` or `restore_stock.sh`, or from the setup page.

`python3 flasher/dfu_client.py info` tells you which mode the controller is in.

## Good to know
- The flash tools keep NI's USB identity (`17cc:1700`, *Maschine Mikro MK3*) on purpose: NI's updater only recognises that, so the way back to stock stays open.
- Flashing replaces the firmware only. Your saved mapping, the four slots, the sequencer patterns and NI's own calibration live in separate flash
  pages and survive a flash (NI's original firmware ignores Ex-Machina's pages).
- The flasher in `flasher/` is self-contained (DFU protocol notes in `flasher/PROTOCOL.md`) and could be used on its own.
