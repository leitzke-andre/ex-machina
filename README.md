# Ex-Machina

Alternative firmware for the **Native Instruments Maschine Mikro MK3**: it turns the controller into a class-compliant USB-MIDI device
(so it works on iPadOS / iOS and with any MIDI software, without NI's drivers or software), and adds a standalone feature set: remappable
buttons with a Shift layer, drum / keyboard / chord pad modes with scales, velocity curves, an arpeggiator with tap tempo and MIDI clock, a 16-step
sequencer, mute / solo pads, strip modes, MIDI channel selection, four preset slots stored in the device, on-screen feedback (an idle screen with the
firmware name and a live status line, messages, a sequencer grid), and a browser tool to configure and flash it.

Status: version **v0**, running on a real unit (and an iPad). Hobby project, no affiliation with Native Instruments.

## How it works
The firmware is **NI's own firmware v1.20 plus a patch**: `tools/midi_patch/translate.c` (C, a few hooks into the stock code, new flash content appended
to the image) is built by `tools/midi_patch/build_patch.py` into a patched image. NI's firmware is proprietary and is **not in this repository**:
you supply your own copy (it is inside NI's updater, `tools/carve_fw.py` extracts it) and the build, or the browser page, applies our patch to it.
`tools/ui/patch_bundle.json` holds only our bytes and checksums.

The patch is tested without hardware in an emulator (Unicorn, running the real stock firmware and a model of the USB and flash peripherals).

## Layout
| Path | What |
|---|---|
| `tools/midi_patch/` | the patch (`translate.c`), the image builder, the host-side config library / CLI (`mmk3_config.py`), and the emulator tests (`run_tests.sh`) |
| `tools/ui/` | the browser tool: mapping editor, presets, flashing and restoring the firmware (Web MIDI + WebUSB; Chrome or Edge) |
| `tools/emu/` | the Unicorn machine, USB and flash models |
| `flasher/` | self-contained DFU client for the NI bootloader (Python + WebUSB port), the guarded flash script, its tests and the protocol notes; could be its own project |
| `tools/*.py`, `tools/*.sh` | the restore script (hash-gated NI image), USB / HID / chip probes, firmware carving |
| `tools/ghidra/` | helper scripts used for the reverse engineering |
| `docs/` | design notes and the research: reverse-engineering findings, what each source confirmed, the SysEx protocol, hardware plan and results, the chip probe |
| `proprietary/` | **not committed** (see `.gitignore`): NI's manual, updaters, installer image and the unmodified stock firmware, kept locally for the build and the restore path |
| `CLAUDE.md` | working notes for the AI assistant used on this project (commands, constraints) |

Start with `docs/midi-patch.md` (design and features), `docs/ui.md` (the browser tool) and `docs/remap-protocol.md` (SysEx protocol).

## Getting started
```
# the tests (needs clang with the ARM target, python with unicorn pyelftools usb-protocol; node for the page's tests)
tools/midi_patch/run_tests.sh <stock firmware image> <work dir>

# the browser tool
python3 tools/ui/serve.py        # then open http://localhost:8765 in Chrome or Edge
```
Flashing replaces the device's firmware. The bootloader is not touched and NI's original can be restored from the page or with
`tools/restore_stock.sh` (from your own copy of NI's image), but you do it at your own risk.

## License
The code and documentation in this repository are under the **MIT License** (`LICENSE`). Native Instruments, Maschine and Mikro are trademarks of
Native Instruments GmbH; NI's firmware, manuals and software are theirs and are not part of this repository or covered by this license.
