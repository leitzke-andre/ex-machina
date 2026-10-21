# 10. FL Studio

With the **Ex-Machina script**, FL Studio on a Mac or a PC treats the Mikro as its own controller:
- the transport and tempo;
- the Channel Rack: select, mute, solo, and the step sequencer on the pads;
- patterns, mixer inserts, plug-in parameters and presets, the browser, undo.

The screen and the LEDs follow what FL is doing. The pad modes, scales, chords, Fixed Vel and the arpeggiator still run on the controller itself (chapters 2 and 4).

> First run in FL Studio 2026 on macOS (2026-10-21): the script was found and assigned to the controller automatically, and it worked. Not every button and mode has been tried in FL yet. FL Studio Mobile has no scripting: use its preset (chapter 5) there.

## What you need
- FL Studio 20.8 or later, Fruity edition or higher. FL Studio 2026 is needed for swing and the pattern length on the encoder.
- The controller with Ex-Machina in **FL Studio mode**: press **Shift + Project** (see *The two modes* below).
- Best: the **generation 12 firmware** (FL Studio mode and host mode). With it, FL writes text on the screen and the pads work as a grid in every pad mode. An older Ex-Machina works too, with the **FL Studio** preset loaded by hand (setup page, or `mmk3_config.py preset apply fl-studio --save`), but:
  - the screen is drawn as pixels and may flicker back to the Ex-Machina screen now and then;
  - the grid modes (Step, Select, Mute, Solo, Pattern, Group) need the controller in **Pad Mode**.

## The two modes
The controller has two modes, and **Shift + Project** switches between them, whatever mapping is active (two buttons, so it does not happen by accident while playing):

| | Standalone | FL Studio |
|---|---|---|
| Mapping | your own: the saved one, the four slots, Maschine-like modes... | built in, made for the script (the button map below) |
| Project | the next preset slot | a button for FL: the Playlist and the Channel Rack in turn |
| Screen and LEDs | the controller's own | FL's (the script), or `FL STUDIO / WAITING FOR FL` while FL is not running |
| FL Studio | sees nothing of the controller | the controller is its controller |

- Switching shows `MODE / FL STUDIO` or `MODE / STANDALONE` and releases any note still sounding.
- Coming back to Standalone brings back exactly the mapping you had, even unsaved edits, and Project goes on from the same slot.
- The mode is **remembered when the controller is unplugged**.
- Sending a mapping from the setup page (or loading a slot from it) goes back to Standalone mode. *Save on device* in FL Studio mode saves your Standalone mapping.
- The setup page shows the mode on its *Device* tab and can switch it too; so can `mmk3_config.py mode standalone|fl`.

## Installing
1. **Copy the script.** Run:

   ```bash
   integrations/fl_studio/install.sh
   ```

   It copies `integrations/fl_studio/Ex-Machina/` to `~/Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina/`. On Windows, copy the folder by hand to `Documents\Image-Line\FL Studio\Settings\Hardware\Ex-Machina\`, or pass that path to `install.sh`.
2. **Set up FL Studio.** Open *Options > MIDI Settings*:
   - If FL Studio was already open when you installed the script, click **Update MIDI scripts** there. FL then recognises the controller and sets its Controller type to **Ex-Machina (Maschine Mikro MK3)** by itself (the script names the device it supports).
   - Otherwise: select the *Maschine Mikro MK3* input, enable it, and choose the Controller type **Ex-Machina (Maschine Mikro MK3)**.
   - Give the input and the *Maschine Mikro MK3* output **the same Port number**. The script answers through the output.
   - Optional: enable *Send master sync* on that output, so the arpeggiator and Note Repeat follow FL's tempo.
3. **Check it works.** *View > Script output* should show the script loaded. The screen shows `PLAY`, the selected channel, the pattern, and the tempo with STOP.

## The buttons
| Button | In FL Studio |
|---|---|
| **Play / Stop / Rec** | play-pause, stop, record. Play is lit while FL plays, Rec while it records |
| **Restart** | back to the start and play |
| Shift + **Play** | **Score Log**: what you just played (the last 5 minutes) goes into the pattern, even if FL was not recording |
| Shift + **Rec** | count-in on / off (printed *Count-in*) |
| Shift + **Restart** | loop recording on / off (printed *Loop*) |
| **Tap** / Shift + Tap | tap tempo (the beat blinks on Tap) / metronome |
| **Follow** | switches between pattern and song mode (lit in song mode) |
| Shift + **Left / Right** | undo / redo |
| **Left / Right** | the page in a pad mode below. In Plug-in: the parameter. In Browser: fold / unfold. Otherwise: the previous / next channel |
| **Select** | pads = channels 1-16 (Left / Right for 17-32 ...). Press a pad to select its channel |
| **Mute / Solo** | pads = channels: mute / solo them. In the Mixer (Group): mute / solo the selected insert |
| Shift + **Solo** | every mute and solo off (the channels; in the Mixer the inserts) |
| **Pattern** | pads = patterns: jump to one. The dim white pad makes a new pattern |
| **Group** | pads = mixer inserts: select one. Volume / Sampling then turn its volume / pan |
| **Step** | pads = the 16 steps of the selected channel: set steps bright, the others dim in the channel's colour, every 4th dim white, the playhead white. **A hit sets a step with the hit's velocity** (hit harder for an accent). **Hold a step (or several) and turn the encoder** to edit it; **Events** chooses what: velocity, pitch, fine pitch, pan, release, Mod X, Mod Y, shift; FL's graph editor shows it. A set step hit again goes off when you let go, unless you edited it. Left / Right show steps 17-32 ... in longer patterns. Erase clears the channel, Shift + Erase every channel. Shift + Step: the encoder sets the pattern length |
| **Duplicate** (or Shift + Pattern) | clones the pattern |
| **Volume / Sampling** | the encoder turns the selected channel's volume / pan. Hold the encoder down for fine steps; Shift + push resets it |
| **Tempo / Swing** | the encoder turns the tempo / the swing |
| **Plug-in** | the encoder turns a parameter of the selected channel's plug-in; push or Left / Right for the next one. The screen shows the name and value |
| Shift + **Plug-in** | the encoder steps through the plug-in's presets |
| **Browser** | opens FL's browser: the encoder moves, push opens or loads. Shift + Browser closes it |
| **Favorites** | opens the selected channel's plug-in window |
| the encoder with nothing selected | moves the selection in the focused window; push = enter |

Press a mode button again to go back to **playing**. The pads then play the selected channel; on an FPC they light in FPC's pad colours.

**Shift + pads** do what is printed under the pads, in every mode: **1 Undo, 2 Redo, 3 Step undo, 4 Step redo** (FL has one undo history, so 3 and 4 do the same as 1 and 2), **5 Quantize** (FL's quick quantize of the selected channel: note starts and ends), **6 Quantize 50%**: FL's scripting offers no 50 % quantize (moving notes halfway to the grid), so pad 6 quantizes the note **starts only** and leaves the ends; the screen says `QUANTIZE STARTS`, **9 Clear** (the channel's steps), **11 Copy, 12 Paste** (in the focused window). While you hold Shift the screen shows a reminder.

**Feedback.** The touch strip shows the encoder's value as a bar (volume green, pan from the centre in cyan, tempo orange, plug-in parameter blue) and, while FL plays, the song position. Left / Right are dark where they cannot go. Every message also appears in FL's hint bar. A mode button brings the matching window to the front (the Channel Rack, or the Mixer for Group; Plug-in opens the plug-in's window).

**Settings.** `exm_settings.py` in the script's folder holds a few switches: step velocity from the hit, bringing windows to the front, the graph editor, loop recording on at start (off by default), the Score Log length, how long messages stay, the strip bar, the hint bar. Edit it and click *Update MIDI scripts*.

**If the script fails** (a new FL version, a case nobody tried), the controller does not go dark: the screen shows `SCRIPT ERROR`, the pads go back to playing, and FL gets the controller as a plain MIDI controller. *View > Script output* shows what happened; reload the script with *Update MIDI scripts*.

The playing buttons work exactly as in *Maschine-like modes* (chapter 3), and the notes go to FL:
- **Pad Mode / Keyboard / Chords** (Shift: scales and chord types);
- **Fixed Vel** (Shift: 16 Velocities);
- **Note Repeat** (Shift: rate), **Auto** (arp octaves), **Lock** (latch);
- **Pitch / Mod / Perform / Notes** for the strip;
- Shift + Volume / Swing for the velocity curve;
- Shift + Mute for panic.

**Project** shows the Playlist and the Channel Rack in turn; **Shift + Project** leaves FL Studio mode. **Scene and Variation** are free (Events too, outside Step mode): FL's *Link to controller* can learn them.

## If something is not right
- **The screen says `FL STUDIO / WAITING FOR FL`.** FL Studio is not running, the script is not selected for the controller, or the output port number is not the input's.
- **FL does not react to the controller at all.** The controller is in Standalone mode: press Shift + Project.
- **The grid modes play notes instead of setting steps.** Either the firmware is older than generation 11 and the controller is not in Pad Mode, or the script did not get the controller's answer: check the output port.
- **Swing or the pattern length says `NEEDS FL STUDIO 2026`.** Your FL Studio version does not have those functions.
- **Uninstall.** Delete the `Ex-Machina` folder in FL's Hardware folder. The controller keeps working as a plain MIDI controller.
