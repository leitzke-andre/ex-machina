# 9. MIDI reference

The controller is a standard **USB-MIDI** device with one port in each direction, named *Maschine Mikro MK3*. Everything below is on **MIDI
channel 1** by default (the channel is set on the setup page or with Group in *Maschine-like modes*); LED messages use channel 2.

## What the controller sends (Default mapping)
| Control | Message |
|---|---|
| Pads 1-16 | Note On / Note Off, notes 36-51 (pad 1 = 36, bottom left), velocity from the curve |
| Pad pressure | Polyphonic aftertouch on the pad's note while it sounds (or channel pressure, a CC, or nothing) |
| Buttons | Control Change 127 on press, 0 on release, on NI's numbers (chapter 3); Play = MIDI Start (`FA`), Stop = MIDI Stop (`FC`); Project loads slots and sends nothing |
| Encoder | Turn: CC 7, absolute 0-127 from 0 (relative modes available); push: CC 8; touch: CC 9 |
| Touch strip | CC 1, 0-127 from left to right |

**Notes held by more than one source** (two chord pads sharing a note, a pad and the sequencer on the same drum, 16 Velocities): every Note On
goes out, and the Note Off only when the last of them lets go, so one release never cuts a note another pad still holds. When another mapping
takes over (a slot, the setup page, an app) everything still sounding is released first, on the channel it was played on, and a bent pitch goes
back to the centre.

With *Maschine-like modes* and the controller's own functions, the controller also sends Program Change, pitch bend (strip *Pitch*), MIDI clock,
Start and Stop (*Shift + Tap*), All Sound Off / All Notes Off (panic), and the notes of the arp, the chords, the strum and the sequencer.

## What it listens to
| Message | Effect |
|---|---|
| MIDI Clock, Start, Continue, Stop | The arp and the sequencer follow the incoming clock |
| Note On, channel 2, note *n* (0-79), velocity = colour | Lights LED *n* directly: 0-38 the buttons, 39-54 the pads, 55-79 the touch strip |
| Note On, channel 1, a pad's note | Lights that pad |
| Control Change, channel 1, a button's CC | Lights that button (0 off, below 43 dim, below 86 normal, above bright) |
| SysEx `F0 7D 4D 4B 02 <80 bytes> F7` | Sets all 80 LEDs at once |
| SysEx `F0 7D 4D 4B 01 ...` | Draws a region of the 128 x 32 screen |

**Colours**: the velocity is `colour × 4 + brightness`, colour 1 red, 2 orange, 3 light orange, 4 warm yellow, 5 yellow, 6 lime, 7 green, 8 mint,
9 cyan, 10 turquoise, 11 blue, 12 plum, 13 violet, 14 purple, 15 magenta, 16 fuchsia, 17 white; brightness 0-3. Velocity 0 or Note Off turns it off.
A LED set by an app becomes that LED's resting colour: a local press or hit lights it and returns to the app's colour.

## Configuration over SysEx
The setup page and `mmk3_config.py` use SysEx messages with the manufacturer bytes `7D 4D 4B` (`7D` is the ID for non-commercial use):

| Command | |
|---|---|
| `10` INFO | Protocol version, size of the mapping, saved / unsaved flags, firmware version |
| `11` GET / `12` SET | Read / replace the active mapping (274 bytes, 7-bit packed); a SET is range-checked and active at once |
| `13` SAVE / `14` RESET | Keep the mapping in flash / back to the defaults (optionally erasing the saved one) |
| `15` / `16` / `17` | Store a slot (with a name) / load a slot / list the slots |
| `20` HOST / `21` TEXT | Host mode for a DAW script (generation 11): the screen shows the host's four text lines, the pads send notes 36-51 whatever the pad mode, the firmware's own messages can be turned off; TEXT writes a line (chapter 10) |
| `1E` PEEK | Read-only diagnostics |

The full protocol and the layout of the mapping are in [`docs/remap-protocol.md`](../docs/remap-protocol.md).

## USB identity
VID:PID `17cc:1700`, product name *Maschine Mikro MK3*, manufacturer *Native Instruments*, as on the original, so that NI's updater can always put
the original firmware back. Interfaces: Audio Control, MIDI Streaming (bulk, 64 bytes) and DFU (for flashing). It asks the host for 480 mA.
