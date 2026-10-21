# Ex-Machina in FL Studio

A MIDI controller script for FL Studio (desktop, macOS and Windows) that turns the Mikro running Ex-Machina into an FL Studio controller. It rebuilds the Maschine functions that need NI's software (groups and sounds, patterns, the step sequencer, mute and solo, plug-in control, the browser, undo) on FL's own objects. The playing functions that the firmware already has stay on the device: Keyboard / Chords with the scales, Fixed Vel, Note Repeat and the arp, and the strip modes. The script lives in `integrations/fl_studio/Ex-Machina/`. The user's instructions are in `manual/10-fl-studio.md`.

**Status 2026-10-21:**
- The script is tested against a stand-in for FL's modules (`integrations/fl_studio/flsim.py`) and against the emulated firmware (`test_fl_script.py`).
- It has **not run in FL Studio yet**: that check is the user's (FL Studio 2026, All Plugins Edition).
- The firmware's host mode (generation 11, `docs/midi-patch.md`) is built and emulator-tested, **not flashed**.
- On the generation 10 firmware now on the device, the script falls back to drawing pixels (below).

## What FL Studio's scripting offers (research, 2026-10-20)
- **Where scripts live.** FL Studio runs Python device scripts named `device_<name>.py` from `Documents/Image-Line/FL Studio/Settings/Hardware/<folder>/`.
- **Headers and modules.** A script carries `# name=` (the Controller type shown in MIDI Settings) and optionally `# supportedDevices=` (auto-linking by the USB name, here "Maschine Mikro MK3"). It can import modules from its own folder. Scripting needs the Fruity edition or higher; the All Plugins Edition has it.
- **Callbacks** (the script uses the starred ones):
  - lifecycle: `OnInit`★, `OnDeInit`★, `OnIdle`★ (about every 20 ms);
  - MIDI in: `OnMidiMsg`★, `OnSysEx`★;
  - FL state: `OnRefresh(flags)`★, `OnDoFullRefresh`★, `OnUpdateBeatIndicator`★, `OnProjectLoad`★, `OnDirtyChannel`, `OnDirtyMixerTrack`.
- **Modules.** `transport`, `channels` (the Channel Rack and its step grid), `mixer`, `patterns`, `playlist`, `arrangement`, `plugins` (parameters, presets, FPC pads), `ui` (windows, browser, hints), `general` (undo), `device` (MIDI and SysEx out) and `midi` (constants).
- **New in FL Studio 2026** (release notes):
  - `get_swing` / `set_swing`;
  - `setPatternLength` / `incrementPatternLength`;
  - clear-pattern and FPC "pad is empty" functions (2026.1.3 / .4; their names are not published);
  - `clonePattern` to a destination index (2026.1.1);
  - `duplicateMidiPatternData()`;
  - HW_Dirty flags for undo / redo;
  - a refresh flag for the Graph Editor;
  - `DisplayRect` limited to 2 s.

  Image-Line's API reference (IL-Group's FL-Studio-API-Stubs) does not document these yet: **which module the swing functions are in, and their units, are unknown**.
- **Existing scripts for the Mikro.** Third-party FL scripts for the *stock* Mikro in NI's MIDI mode exist (a GitHub project and paid ones). They are limited by NI's MIDI mode: Shift and the arrows send nothing, and the screen cannot be written. Nothing was taken from them.

## How the pieces fit
- **The device side.** The device runs the built-in preset **FL Studio** (`mmk3_config._fl_studio()`):
  - Every button the script uses sends its NI CC as a gate (press 127, release 0), Play and Stop too, not MIDI Start / Stop.
  - With Shift held, a few buttons send a second CC 102-110 (`FL_SHIFT_CC`). Shift itself is the device's modifier, so the device's own Shift functions still work.
  - The encoder sends relative CC 7 (two's complement); its push is CC 8. Its touch sends nothing, because FL's *Link to controller* would learn the touch instead of the turn.
  - The pads send notes 36-51, which is FPC's default layout.
  - Without the script, the preset is a plain CC controller.
- **The tables.** `gen_tables.py` copies what the script needs from the repository into `exm_tables.py`: the CC of every button with and without Shift, the pad and button LED indices, the font and the command numbers. FL cannot import the repository. `gen_tables.py --check` in `run_tests.sh` fails when the copy is stale.
- **Host mode and the fallback.** At `OnInit` the script sends HOST (SCREEN).
  - **A firmware with host mode** answers `60`. From then on the script writes its four screen lines with TEXT (29 bytes per changed line). While a pad grid mode is on, it sends HOST SCREEN | RAW, so the pads send notes 36-51 whatever the device's own pad mode. Outside the grid modes the pads play whatever the device's mode is, Keyboard and Chords included.
  - **No answer within a second** (an older firmware): the script draws the same four lines as two pixel regions (SysEx 01, at least 12 ms apart, one per `OnIdle`). It draws them again every 2 s, because that firmware draws its own idle screen when its status changes. The grid modes then need the device in Pad Mode, since in Keyboard mode a pad's note is not its number.
- **The LEDs.** One Note On on channel 2 per LED that changed (velocity = colour code). The firmware makes a host-set colour the LED's resting colour, so its local hit / press flash still works on top. FL colours are matched to the nearest of the device's 16 hues, and greys become white.
- **The screen.**
  - Line 1: the mode, with its page and the encoder target.
  - Line 2: the selected channel.
  - Line 3: the pattern.
  - Line 4: the tempo and PLAY / STOP / REC.
  - A changed value replaces lines 2-3 for 1.5 s, for example `VOL KICK / 88%` or `OSC 2 COARSE / -12 ST`.
- **Robustness.** Every FL function goes through `call()`, which returns a default when this FL version lacks the function or refuses the call. A missing 2026 function shows `NEEDS FL STUDIO 2026` instead of stopping the script. `OnDeInit` sends HOST 0, and a SET / RESET / slot load from another tool ends host mode too.

## The map
Shift + X means X pressed while Shift is held. "Device" means the firmware does it; the script never sees it.

| Button | FL Studio |
|---|---|
| Play / Stop / Rec | play-pause / stop / record; Play lit while playing, Rec while recording |
| Restart, Shift + Play | back to the start and play |
| Tap / Shift + Tap | tap tempo (the beat blinks on Tap) / metronome |
| Follow | pattern / song mode (lit in song mode) |
| Shift + Left / Right | undo / redo |
| Left / Right | the page in a grid mode; the parameter in Plug-in; folders in Browser; else the previous / next channel |
| Select | pads = channels 1-16 (pages of 16): select; colour = the channel's, the selected one bright |
| Mute / Solo | pads = channels: mute (dims) / solo (bright, the others dark) |
| Pattern | pads = patterns 1-16 (pages): jump; the next free one dim white |
| Group | pads = mixer inserts 1-16 (8 pages): select; Volume / Sampling then turn that insert's volume / pan |
| Step | pads = 16 steps of the selected channel (pages of 16 up to the pattern length); the playhead is a white pad; Erase = clear the channel, Shift + Erase = every channel; Shift + Step = the encoder sets the pattern length (FL 2026) |
| Duplicate, Shift + Pattern | clone the pattern |
| Volume / Sampling | the encoder turns the selected channel's volume / pan (push held: fine; Shift + push: back to the default) |
| Tempo | tempo jog (push held: 0.1 BPM) |
| Swing | the global swing (FL 2026 `set_swing`; older FL: a message) |
| Plug-in | the selected channel's plug-in: encoder = the value, push / arrows = the next / previous parameter that has a name; the screen shows its name and value text |
| Shift + Plug-in | its presets: encoder = next / previous |
| Browser / Shift + Browser | show and focus FL's browser: encoder = up / down, push = open / load, arrows = fold / unfold / hide it |
| Favorites | open the selected channel's plug-in window |
| Encoder with no target | `ui.jog` in the focused window, push = enter |
| Pad Mode / Keyboard / Chords / Fixed Vel / Note Repeat / Auto / Lock / Pitch / Mod / Perform / Notes, Shift + Volume / Swing, Shift + Mute | device (as in *Maschine-like modes*): the notes go to FL. Turn on *Send master sync* for the Mikro's output in FL's MIDI settings so the arp follows FL's tempo |
| Project | device: the next preset slot (in every preset) |
| Scene, Events, Variation | not used: their CCs go to FL (MIDI learn / Link to controller) |

**Play mode** (no grid mode): the pads go straight to FL, so the selected channel plays them. On an FPC channel, the pad LEDs take FPC's pad colours (`plugins.getPadInfo`). On any other channel they all take the channel's colour.

## What is not covered, and why
- **Groups and sounds as in Maschine.** FL's Channel Rack has no groups of 16. Select / Mute / Solo work on pages of 16 channels instead.
- **Scenes and the arranger.** Playlist performance mode and arrangement markers exist in the API but are left for later.
- **Automation recording (AUTO).** The device uses Auto for the arp octaves.
- **Per-step velocity / pitch** (`setStepParameterByIndex`) and **Note Repeat in FL's own sequencer.**
- **Clear pattern and the FPC empty-pad check.** The 2026 functions are not named in any document, so the script does not use them yet: Erase clears the steps itself, and an empty FPC pad still shows FPC's colour.
- **Unverified until it runs in FL.** The units of `get_swing` / `set_swing` (the script handles both an int and a 0-1 float) and which module they are in (it looks in transport, patterns, channels, mixer and general). The step size of `FPT_TempoJog` (10 = 1 BPM is assumed). Whether `getPatternLength` counts beats (assumed: 4 steps per beat). The colour order of `getChannelColor` (FL's own `utils.ColorToRGB` order, `0xRRGGBB`, is used).

## Testing
- `integrations/fl_studio/test_fl_script.py`:
  - **Part 1** runs the real script against `flsim.py`. That is a small project (4 channels, an FPC, a 3x Osc with parameters, 2 patterns, mixer inserts) behind the signatures of FL's API reference, with every call logged.
  - **Part 2** (with `patched.bin data_init.bin`) connects the script to the emulated firmware both ways. The device's MIDI goes to the script, and the script's LEDs, HOST and TEXT go to the device. It then compares the LEDs and the screen pixels the device ends up with against what the script meant, with host mode and with the pixel fallback. In particular, Step mode on the device while the device's Keyboard mode is on still sets steps 1 and 16 from pads 1 and 16.
- `tools/midi_patch/test_host.py` tests the firmware side.
- Both run in `run_tests.sh`.
