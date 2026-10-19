# 5. Presets and slots

A **mapping** (or *configuration*) is everything the controller does: what each button and pad sends, the encoder and strip, the lighting, the
channel, the start values of the modes. The controller holds three kinds of mapping:

| | Where | Changed by | Survives unplugging |
|---|---|---|---|
| **Active** | in use right now | *Use* / *Send to device* on the setup page, an app, a slot | no, unless saved |
| **Saved** (power-up) | the device's flash | *Save on device* | yes |
| **Slots 1-4** | the device's flash | *Store current* on the setup page | yes |

## The Project button: cycling through the slots
**Project** (top left) loads the **next slot that holds a mapping**: 1 → 2 → 3 → 4 → 1, skipping empty slots. The screen shows `SLOT 2` and the
slot's name (for example `GROOVE RIDER 2`). This works in **every** mapping, with or without Shift, and cannot be reassigned: whatever a mapping
says, the firmware keeps Project on the slots, so you can never lose the way to your other mappings.

- The cycle continues from the slot last loaded or stored. After a power-up it starts from the slot that matches the saved mapping, otherwise from slot 1.
- A loaded slot is **active, not saved**: unplug and the saved mapping is back. To make a slot the power-up mapping, load it and *Save on device*.
- With no slot filled, Project shows `SLOT / EMPTY`.
- Loading a slot writes nothing to flash, so you can cycle as often as you like.

**A typical set-up** for an iPad: slot 1 *Maschine-like modes* for playing on its own, slots 2-4 one preset per app. Store them once from the
setup page, then switch with Project.

## Filling the slots
On the setup page, **Device** tab, *Preset slots on the device*:
- **Store current** writes the active mapping into the slot, under the **display name** of the preset in the editor (what the screen shows when the
  slot is loaded, up to 20 characters).
- **Make active** loads a slot (like pressing Project until it comes up).
- Each slot shows whether it is empty or which preset it holds.

From the command line: `mmk3_config.py slot store 2 "Groove Rider 2"`, `slot load 2`, `slot list` (chapter 8).

No button stores into a slot in the built-in presets: storing overwrites a slot, so it is left to the setup page.

## The built-in presets
| Preset | Screen name | For | In short |
|---|---|---|---|
| **Default** | `DEFAULT` | any MIDI software | What the firmware starts with: Play / Stop = MIDI Start / Stop, every other button NI's CC, pads 36-51, encoder CC 7, strip CC 1 |
| **Maschine-like modes** | `MASCHINE MODES` | playing on the controller | The controller's own functions on the printed buttons (chapter 3) |
| **Groove Rider 2** | `GROOVE RIDER 2` | the iPad app (tried) | Pads 36-51, strip = cutoff (CC 74), encoder = relative CC 20 for *Last Knob Control*, Solo / Mute = CC 91 / 92 for the send throws, Erase = CC 120. In the app: Midi In Device = the Mikro, single channel 1 |
| **Korg Gadget 3** *(draft)* | `KORG GADGET 3` | the iPad app | Pads into the track whose MIDI button is lit; Play / Stop / Rec / Restart / Tap = CC 3 / 119 / 2 / 118 / 117 for Gadget's *Transport CC* settings; encoder CC 7, strip CC 1 |
| **BeatMaker 3** *(draft)* | `BEATMAKER 3` | the iPad app | Made for MIDI learn: pads = notes 0-15 with Left / Right paging to 64 pads, transport and mode buttons on CC 102-113, 16 macros on the encoder through Volume / Swing / Tempo and encoder pages |
| **Cubasis 3** *(draft)* | `CUBASIS 3` | the iPad app | Buttons send CC 102-114 once per press, to learn in Cubasis; encoder CC 20, strip CC 21 |
| **FL Studio Mobile** *(draft)* | `FL STUDIO MOBILE` | the app | Pads 48-63, MMC transport, CC 20-31 toggles to learn, encoder CC 102 |
| **GarageBand** *(draft)* | `GARAGEBAND` | the app (no MIDI learn) | Pads 36-51, strip = mod wheel, encoder = volume, Note Repeat = sustain, MMC transport |

*Draft* presets were made from the apps' manuals and forum posts and have not been tried yet; each one's description on the setup page says what to
set up in the app.

## Your own presets
On the setup page you can save any mapping as your own preset, rename it, duplicate it, export it to a file and import it on another computer
(chapter 6). Your presets live in the browser; to have one on the controller itself, store it in a slot.
