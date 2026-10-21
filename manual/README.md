# Ex-Machina user manual

Ex-Machina is an alternative firmware for the **Native Instruments Maschine Mikro MK3**. It turns the controller into a
**class-compliant USB-MIDI device**: plug it into a Mac, a PC, an iPad or an iPhone and it shows up as a MIDI controller with no
drivers and no NI software. On top of plain MIDI it adds a set of functions that run on the controller itself: drum, keyboard and
chord pad modes, 24 scales, velocity curves, an arpeggiator with tap tempo and MIDI clock, a 16-step sequencer, mute and solo pads,
touch-strip modes, four preset slots stored in the device, and messages on its screen.

This manual is for **using** the firmware and the flashing tools. The design notes and the research behind them are in [`../docs/`](../docs/).

> Ex-Machina is a hobby project with no affiliation with Native Instruments. Flashing replaces the controller's firmware. NI's
> bootloader is never touched, so NI's original firmware can always be put back (chapter 7), but you do it at your own risk.

## Chapters
| | Chapter | What is in it |
|---|---|---|
| 1 | [Getting started](01-getting-started.md) | What you need, the two firmware images, the first power-up, connecting to a computer or an iPad |
| 2 | [Playing](02-playing.md) | Pads, pad modes, scales and chords, velocity, transpose, the touch strip, the encoder, Shift, the screen |
| 3 | [Button reference](03-button-reference.md) | Every button of the *Maschine-like modes* preset, with and without Shift, laid out like the device |
| 4 | [Rhythm: tempo, arp, sequencer](04-rhythm.md) | Tap tempo, MIDI clock in and out, arpeggiator and Note Repeat, mute / solo, strum, snapshot, the step sequencer |
| 5 | [Presets and slots](05-presets-and-slots.md) | The built-in presets, the four slots in the device and the Project button that cycles through them |
| 6 | [The setup page](06-setup-page.md) | The browser tool: editing the mapping, presets, the device's slots |
| 7 | [Flashing and recovery](07-flashing.md) | Installing the firmware from the browser or the command line, restoring NI's firmware, getting out of trouble |
| 8 | [Command line](08-command-line.md) | `mmk3_config.py`: the same configuration from a terminal |
| 9 | [MIDI reference](09-midi-reference.md) | What the controller sends and what it listens to (notes, CCs, LEDs, the screen, SysEx) |
| 10 | [FL Studio](10-fl-studio.md) | The Ex-Machina script for FL Studio: transport, channels, step sequencer, patterns, mixer, plug-ins on the controller |

## At a glance
- **Plug and play**: one USB-MIDI port, the usual General MIDI drum notes on the pads (36-51), CCs on the buttons, CC 7 on the encoder, CC 1 on the strip.
- **Standalone functions**: pick the *Maschine-like modes* preset and the buttons do what is printed on them (Pad Mode, Keyboard, Chords, Fixed Vel, Note Repeat, Tap, Step...), with feedback on the screen.
- **Four presets in the device**: store four mappings (for example one per app) and press **Project**, the top-left button, to cycle through them without a computer.
- **An FL Studio mode**: **Shift + Project** switches the controller to a built-in mapping for the FL Studio script (transport, Channel Rack, step sequencer, mixer, plug-ins) and back.
- **Configured from a browser**: the setup page (Chrome or Edge) edits every button, pad and setting, keeps your own presets, and installs or removes the firmware.
- **Always reversible**: the bootloader is never touched; NI's original firmware goes back with one click or one command.
