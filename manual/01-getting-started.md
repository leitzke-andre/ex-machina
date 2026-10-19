# 1. Getting started

## What you need
- A **Maschine Mikro MK3** and a USB cable.
- **Your own copy of NI's firmware 1.20.** NI's firmware is not part of this project and is never distributed with it. It is inside NI's
  firmware updater (the `MM3Updater` app on a Mac, the `.exe` on Windows); the setup page and the build tools take it from there.
- To flash from the browser: **Chrome or Edge** on a computer (Web MIDI and WebUSB; Safari and Firefox lack one or both).
- To flash from the command line, or to build the images yourself: Python 3 with `pyusb` and libusb, and for building, clang with the ARM target
  (see chapter 7 and the repository's `README.md`).

## Two firmware images
Ex-Machina comes in two forms that behave the same for playing:

| | **Patched image** (the default) | **Standalone image** |
|---|---|---|
| What it is | NI's firmware 1.20 with our code added and hooked in | Only our code: start-up, drivers, USB, flash writing, everything |
| How it is made | In the browser from your NI updater (chapter 7), or `build_patch.py` | `build_patch.py ... --native` on the command line |
| How it is installed | The setup page, or the command line | The command line (`flasher/flash_guarded.sh`) |
| NI code in it | Yes (yours, never in this repository) | **None**. Only NI's LED colour tables are copied from your copy at build time |
| Start-up | NI's logo and LED animation (about 2 s) | A blank screen, then the Ex-Machina screen after 0.3 s |

Both keep the USB identity of the original (`17cc:1700`, named *Maschine Mikro MK3*), so NI's own updater still recognises the device, and both
leave NI's bootloader alone, so either can be replaced by the other or by NI's original at any time.

## Installing
Chapter 7 has the details. In short, with the setup page:
1. `python3 tools/ui/serve.py` and open `http://localhost:8765` in Chrome or Edge.
2. **Firmware** tab: first **save a copy of NI's original firmware** and keep it safe.
3. Choose your NI updater file, select the Maschine, tick the confirmation, **Flash now**. The page asks once more for the device when it
   switches to its bootloader, then writes the firmware; the controller restarts by itself after about 6 seconds.

## The first power-up
After a moment the screen shows the idle screen:

```
 EX-MACHINA            <- the firmware's name, large
 V0                    <- the version, or the notes you are playing
 DRUMS CH1 120         <- pad mode, MIDI channel, tempo (and ARP / CLK / SEQ while they run)
```

The pads rest in blue, the buttons that do something are dimly lit, and the touch strip lights under your finger.

Out of the box the controller uses the **Default** mapping: plain MIDI, nothing on the device changes mode. To get the controller's own functions
(pad modes, arp, sequencer...), load the **Maschine-like modes** preset: on the setup page, **Presets** tab, **Use**, then **Save on device**.
Chapter 3 shows what every button does in it.

## Connecting
- **Mac**: it appears in *Audio MIDI Setup* and in every MIDI app as *Maschine Mikro MK3*, input and output.
- **Windows / Linux**: a standard USB-MIDI device, no driver needed.
- **iPad / iPhone**: connect directly with USB-C, or with a camera adapter on Lightning. The controller asks the host for 480 mA, like the
  original: a USB-C iPad is fine (tested on an iPad Air 4), a Lightning device without a powered adapter may refuse it ("requires too much power").
  In the app, choose the Mikro as MIDI input (and as output if the app should light its pads and buttons).

## Is it working?
- The pads play notes 36-51 (C1-D#2, the General MIDI drum kit), pad 1 bottom left.
- The screen shows the notes you play in the middle line, then `V0` again after half a second.
- **Play** and **Stop** send MIDI Start and Stop, so a drum machine app starts and stops with them.

If the controller does not appear at all, see *Getting out of trouble* in chapter 7.
