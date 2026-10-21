# 10. FL Studio

With the **Ex-Machina script**, FL Studio on a Mac or a PC treats the Mikro as its own controller:
- the transport and tempo;
- the Channel Rack: select, mute, solo, and the step sequencer on the pads;
- patterns, mixer inserts, plug-in parameters and presets, the browser, undo.

The screen and the LEDs follow what FL is doing. The pad modes, scales, chords, Fixed Vel and the arpeggiator still run on the controller itself (chapters 2 and 4).

> The script has been tested against a model of FL Studio and of the controller, **not yet in FL Studio itself**. FL Studio Mobile has no scripting: use its preset (chapter 5) there.

## What you need
- FL Studio 20.8 or later, Fruity edition or higher. FL Studio 2026 is needed for swing and the pattern length on the encoder.
- The controller with Ex-Machina and the **FL Studio** preset. Load the preset from the setup page, or run `mmk3_config.py preset apply fl-studio --save`. You can also store it in a slot and reach it with Project.
- Best: the **generation 11 firmware (host mode)**. With it, FL writes text on the screen and the pads work as a grid in every pad mode. An older Ex-Machina works too, but:
  - the screen is drawn as pixels and may flicker back to the Ex-Machina screen now and then;
  - the grid modes (Step, Select, Mute, Solo, Pattern, Group) need the controller in **Pad Mode**.

## Installing
1. **Copy the script.** Run:

   ```bash
   integrations/fl_studio/install.sh
   ```

   It copies `integrations/fl_studio/Ex-Machina/` to `~/Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina/`. On Windows, copy the folder by hand to `Documents\Image-Line\FL Studio\Settings\Hardware\Ex-Machina\`, or pass that path to `install.sh`.
2. **Set up FL Studio.** Open *Options > MIDI Settings*:
   - Select the *Maschine Mikro MK3* input, enable it, and choose the Controller type **Ex-Machina (Maschine Mikro MK3)**.
   - Give the input and the *Maschine Mikro MK3* output **the same Port number**. The script answers through the output.
   - Optional: enable *Send master sync* on that output, so the arpeggiator and Note Repeat follow FL's tempo.
3. **Check it works.** *View > Script output* should show the script loaded. The screen shows `PLAY`, the selected channel, the pattern, and the tempo with STOP.

## The buttons
| Button | In FL Studio |
|---|---|
| **Play / Stop / Rec** | play-pause, stop, record. Play is lit while FL plays, Rec while it records |
| **Restart** (or Shift + Play) | back to the start and play |
| **Tap** / Shift + Tap | tap tempo (the beat blinks on Tap) / metronome |
| **Follow** | switches between pattern and song mode (lit in song mode) |
| Shift + **Left / Right** | undo / redo |
| **Left / Right** | the page in a pad mode below. In Plug-in: the parameter. In Browser: fold / unfold. Otherwise: the previous / next channel |
| **Select** | pads = channels 1-16 (Left / Right for 17-32 ...). Press a pad to select its channel |
| **Mute / Solo** | pads = channels: mute / solo them |
| **Pattern** | pads = patterns: jump to one. The dim white pad makes a new pattern |
| **Group** | pads = mixer inserts: select one. Volume / Sampling then turn its volume / pan |
| **Step** | pads = the 16 steps of the selected channel; the white pad is the playhead. Left / Right show steps 17-32 ... in longer patterns. Erase clears the channel, Shift + Erase every channel. Shift + Step: the encoder sets the pattern length |
| **Duplicate** (or Shift + Pattern) | clones the pattern |
| **Volume / Sampling** | the encoder turns the selected channel's volume / pan. Hold the encoder down for fine steps; Shift + push resets it |
| **Tempo / Swing** | the encoder turns the tempo / the swing |
| **Plug-in** | the encoder turns a parameter of the selected channel's plug-in; push or Left / Right for the next one. The screen shows the name and value |
| Shift + **Plug-in** | the encoder steps through the plug-in's presets |
| **Browser** | opens FL's browser: the encoder moves, push opens or loads. Shift + Browser closes it |
| **Favorites** | opens the selected channel's plug-in window |
| the encoder with nothing selected | moves the selection in the focused window; push = enter |

Press a mode button again to go back to **playing**. The pads then play the selected channel; on an FPC they light in FPC's pad colours.

The playing buttons work exactly as in *Maschine-like modes* (chapter 3), and the notes go to FL:
- **Pad Mode / Keyboard / Chords** (Shift: scales and chord types);
- **Fixed Vel** (Shift: 16 Velocities);
- **Note Repeat** (Shift: rate), **Auto** (arp octaves), **Lock** (latch);
- **Pitch / Mod / Perform / Notes** for the strip;
- Shift + Volume / Swing for the velocity curve;
- Shift + Mute for panic.

**Project** still cycles the preset slots. **Scene, Events and Variation** are free: FL's *Link to controller* can learn them.

## If something is not right
- **Nothing on the screen, the LEDs stay as they were.** The output port number is not the input's, or the controller is not on the FL Studio preset.
- **The grid modes play notes instead of setting steps.** Either the firmware is older than generation 11 and the controller is not in Pad Mode, or the script did not get the controller's answer: check the output port.
- **Swing or the pattern length says `NEEDS FL STUDIO 2026`.** Your FL Studio version does not have those functions.
- **Uninstall.** Delete the `Ex-Machina` folder in FL's Hardware folder. The controller keeps working as a plain MIDI controller.
