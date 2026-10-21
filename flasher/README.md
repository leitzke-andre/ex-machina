# flasher

A small USB DFU 1.1 client for the **Native Instruments Maschine Mikro MK3** bootloader, in two forms that do the same thing:

| File | What |
|---|---|
| `dfu_client.py` | command-line client (Python, `pyusb`); dry run unless `--yes-flash` |
| `flash_guarded.sh` | macOS wrapper: finds the device by its ids (`usb_guard.py`), refuses to write while any program other than the OS has it open or when it cannot be found, then runs the client |
| `usb_guard.py` | the check itself: which programs hold a USB device, found by VID:PID in the I/O Registry (standard library only; `test_usb_guard.py`) |
| `dfu.js` | the same protocol as an ES module for the browser (WebUSB): `download`, `validateImage`, `findDfuInterface`, `webUsbTransport`, ... |
| `test_dfu_client.py`, `test_dfu.mjs` | tests against a mock DFU device (no hardware and no firmware image needed) |
| `PROTOCOL.md` | what the bootloader does, as observed on a real unit |

It exists because NI's own updater can only flash the image it carries (and macOS has announced it will stop running it). It was used to flash the
[Ex-Machina](../README.md) firmware many times, and to put NI's original firmware back.

**It writes to the device's flash. A wrong image can leave the device unusable** (the bootloader itself is not touched, so a device that does not boot
can still be flashed again, but there is no guarantee for your unit). The tools ask for an explicit `--yes-flash` / a confirmation, and `validate_image`
checks the vector table and the size, but they cannot know whether an image is a good firmware.

## Use
```
pip install pyusb            # and libusb (macOS: brew install libusb)

python3 flasher/dfu_client.py info                     # the device and its DFU interface (read-only)
python3 flasher/dfu_client.py flash image.bin          # dry run: validates the image and prints the plan
python3 flasher/dfu_client.py flash image.bin --yes-flash
flasher/flash_guarded.sh image.bin [python]            # the same, after checking that nothing else has the device open (macOS)
```
`dfu_client.py` takes `--vid --pid --dfu-pid --app-base --app-limit` for another device; the defaults are the profile `MIKRO_MK3`
(`17cc:1700` in normal mode, `17cc:1702` in the bootloader, application area `0x08003000`-`0x0801D800`: NI's settings pages start at
`0x0801F000`, and the Ex-Machina firmware keeps its presets and saved mapping from `0x0801D800`). An image must also hold a USB device descriptor
for the profile's VID:PID, and after a flash the device must come back in normal mode with the `bcdDevice` that descriptor names.
`flash_guarded.sh` reads `DFU_GUARD_ARGS` (`--vid` / `--pid` for the check) and `DFU_CLIENT_ARGS`. In the browser, `dfu.js` is used the way `tools/ui/app.js` uses it:
`findDfuInterface(await readConfigDescriptor(device))`, `webUsbTransport(device, interfaceNumber)`, `download(transport, image, { block, progress })`.
The protocol functions work with any transport that has `ctrl_out` / `ctrl_in` (Python) or `ctrlOut` / `ctrlIn` (JS), which is how the tests run them.

## Tests
```
python3 flasher/test_dfu_client.py [image.bin ...]     # optional: also checks that the given images pass validate_image
node flasher/test_dfu.mjs
```

## Keeping it separate
This directory is self-contained (it imports nothing from the rest of the repository, and the repository's own tests and the browser page use it from
here), so it can be moved to its own repository with its history: `git subtree split --prefix=flasher -b flasher-only`. What is specific to Ex-Machina
stays outside: applying the patch to NI's image (`tools/ui/patch.js`, `tools/ui/patch_bundle.json`) and the hash-gated restore script
(`tools/restore_stock.sh`).

MIT, see `LICENSE`. Native Instruments and Maschine are trademarks of Native Instruments GmbH; this project is not affiliated with them.
