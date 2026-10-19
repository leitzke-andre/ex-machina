# 6. The setup page

The setup page (*Ex-Machina setup*) edits the mapping, keeps your presets, fills the device's slots and installs or removes the firmware. It runs
entirely in your browser and talks to the controller directly; nothing is uploaded anywhere.

## Opening it
```bash
python3 tools/ui/serve.py
```
This serves the page at `http://localhost:8765` and opens it. Use **Chrome or Edge** (they have Web MIDI and WebUSB). `serve.py --mock` opens it
with a stand-in device instead, to look around without the controller.

Close other programs that use the controller's USB connection (NI's Controller Editor, other browser tabs that were given access to it). A second
MIDI program is fine.

## The header
- **Connect**: asks once for MIDI access (with SysEx) and reads the device.
- **Read from device** / **Send to device** / **Save on device**: get the active mapping, make the editor's mapping active, keep it across power cycles
  (*Save* sends first if needed). **Send as I edit** sends every change a moment after you make it.
- The status shows whether the editor matches the device: *Edited, not sent*, *On the device, not saved*, *Saved on the device*, *Device defaults*.
- The **Preset** switcher, with *modified* when the editor has drifted from the preset it was loaded from.

## The tabs
| Tab | What you set |
|---|---|
| **Presets** | Every preset as a card: its description, the mapping in plain words, and what would change compared with the editor. **Use** loads it (and sends it when connected). Your own presets have Duplicate, Rename, Export and Delete; *Save as preset*, *Save changes to preset*, *Discard changes*; import and export of preset files |
| **Buttons** | For each of the 41 controls: a CC, a note, MIDI Start / Continue / Stop, an MMC command, nothing, or one of the device's functions (pad modes, scales, curves, transpose, panic, Shift, strip modes, encoder targets, Program Change, tap tempo, clock, arp, latch, mute / solo, snapshot, MIDI channel, preset slots, the sequencer). Functions with a choice show a second selector. Per CC button: *gate*, *toggle* or *trigger*. *Show what each button does while Shift is held* adds the Shift row. **Project** is greyed out: it always loads the next preset slot. Quick buttons set the transport to MIDI Start / Stop, NI's CCs, or MMC |
| **Pads** | The 4x4 grid as on the device, with a note per pad; *set pads 1-16 in a row* from a first note (General MIDI drums 36, NI's 12, C2, C3). **Playing**: velocity curve, Fixed Vel value, Keyboard root, pad pressure, start scale and chord type, arp pattern / rate / octaves, start tempo |
| **Encoder & strip** | The encoder's CC, mode (absolute, relative offset, relative) and start value; the three encoder target CCs, their pages and the acceleration; the strip's CC and whether it sends 0 on release; MIDI channel; how CC buttons behave; pad velocity gain and sensitivity |
| **LEDs** | The five local-lighting options (buttons at rest, buttons when pressed, pads at rest, pads when hit, strip), pad and strip colours, button levels, and the channel apps use to light the controller |
| **Device** | What the device reports (firmware name and version), the **four preset slots** (*Store current*, *Make active*), back to defaults, erase the saved mapping, and a log of what was sent |
| **Firmware** | Install Ex-Machina or restore NI's firmware (chapter 7) |

A button changed from what the device has shows a dot. Trying things is always safe: until you press *Save on device*, unplugging the controller
brings back the saved mapping.

## Preset files
*Export my presets* or a card's *Export* write a small JSON file (`"format": "mmk3-presets-1"`); *Import* reads it back, here or on another computer.
The command line reads the same files (`mmk3_config.py preset apply NAME FILE`).
