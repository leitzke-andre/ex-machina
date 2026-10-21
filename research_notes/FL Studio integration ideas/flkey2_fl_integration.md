# Novation FLkey 2 (Mini 25 / 37 / 49 / 61) in FL Studio, as a model for a 16-pad + small-screen FL script

Source notes: the two primary sources are Novation's official FLkey 2 user guides. I read them in full as text: **FLkey 2 Mini 25 User Guide v9** ([MINI](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)) and **FLkey 2 37 User Guide v5** ([K37](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)). The 49/61 guides ([K61](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_61_user_guide_v5_en.pdf), [K49](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_49_user_guide_v5_en.pdf)) are larger than the fetch limit, so I could not read them. Their fader and fader-button details below come from search snippets and the script's file names only. The guides say the FLkey 2 needs **FL Studio 25 or later** ([MINI p.12](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)). MusicTech's review is dated 24 July 2026 ([MusicTech](https://musictech.com/reviews/controllers/novation-flkey-2-review/)), and Magnetic Magazine dates the launch to May 2026 ([Magnetic](https://magneticmag.com/2026/05/novation-drops-flkey-2/)). The scripts are also installed on this Mac, which made them inspectable (see the last question). Novation's userguides.novationmusic.com help-centre pages returned HTTP 403 to the fetch tool.

## What pad modes does FLkey 2 offer in FL Studio, and how does each behave?

### Takeaway
FLkey 2 renamed and reshaped the MK1 set. The modes are now **Patterns, Channel Rack, Drum (formerly "Instrument"), Sequencer, User Chord, Chord Map (Mini) / Arp Pattern (37), and Custom**. They are selected by holding Shift (or double-pressing it to latch) and pressing a pad labelled with the mode. Every FL-facing mode draws from FL's own colours: pattern colours, channel colours, or FPC pad colours. Every mode marks the selected or playing item in **white**. Paging uses dedicated up/down button pairs, which light only when paging in that direction is possible.

### Cited Findings
**Selecting modes**
- Pad modes are picked by holding Shift, or double-pressing it to latch. The pads then light, a printed label sits next to each pad, and pressing a pad selects that mode ([MINI p.15](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- On the 37, the Shift layer splits the pads: the **bottom row selects pad modes** and the **top row selects encoder modes** ([K37 p.16, p.20](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- Mode list on the Mini: Patterns, Channel Rack, Drum, Sequencer, User Chord, Chord Map, Custom ([MINI p.16](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Mode list on the 37: Patterns, Channel Rack, Drum, Sequencer, User Chord, Arp Pattern, Custom. Chord Map has its own button on the 37 ([K37 p.10, p.20](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- Selecting Arp Pattern shows "Pad Mode Arp Pattern" on the screen for a moment ([K37 p.31](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).

**Patterns mode** ([K37 p.21-22](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf); same text in [MINI p.17-18](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf))
- Each pad lights in its FL pattern's colour, and the selected pattern lights white. Pattern colours are set in FL with "Rename and color…" or "Random color".
- Pressing a pad selects that pattern. Pressing an **empty pad creates a new pattern**.
- Shift + Page-down **clones** the selected pattern. As in FL itself, an empty new pattern disappears if it is left unedited.
- The Channel Rack up/down buttons scroll the patterns shown on the pads in **banks of eight**.
- The pads **follow FL's pattern-group filter** and show only the filtered patterns.

**Channel Rack mode** ([K37 p.22-24](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf); [MINI p.18-20](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf))
- Up to 16 channels, one per pad. Each pad triggers its channel with a C5 note and lights in the **channel colour**.
- Pressing a pad selects that channel in FL and plays it. The **selected channel lights white**, and only one channel can be selected from the hardware.
- Layout runs left to right, bottom to top, in two rows of eight. The **lower row lines up with the Channel Volume/Pan encoder bank**.
- The Channel Rack up/down buttons bank to the previous or next channel. They **light white only when banking in that direction is possible**. Banking does not change the selected channel.
- The page buttons bank by groups of eight. Holding Channel Rack up/down auto-scrolls.
- The pad grid **follows the Channel Rack group** chosen in FL's group drop-down.
- **Holding an empty pad opens FL's plugin picker**, and encoder 1 then chooses a generator or effect. A generator adds a new channel, and an effect goes on the selected mixer track ([MINI p.18-19](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- **Preset navigation**: Shift + Channel Rack buttons (37) or Shift + Octave buttons (Mini) step through the selected plugin's presets, the same as FL's Presets arrows. Stock presets of third-party plugins cannot be browsed this way, but presets the user saved can ([K37 p.24](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf); [MINI p.20, p.42](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- The preset buttons' LEDs show whether preset navigation is available ([MINI p.42](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).

**Drum mode** (plays the selected channel) ([K37 p.25-26](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- The pad layout adapts to the selected channel's plugin: **FPC, Slicex, Fruity Slicer, Kepler**, or a default layout.
- **FPC**: the left 4×2 pads play FPC's lower half and the right 4×2 its upper half. The pads take **FPC's own pad colours** instead of the channel colour.
- **Slicex / Fruity Slicer**: the pads play slices, and the Page buttons bank by **16 slices**.
- **Default**: a chromatic layout with C5 (MIDI note 84) on the bottom-left pad. With Scale mode on, the pads play the scale's notes over two octaves.
- The Preset up/down buttons step through the instrument's presets.

**Sequencer mode** ([K37 p.26-28](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf); [MINI p.22-23](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf))
- Edits the selected channel's step grid in the selected pattern. The **upper row shows steps 1-8 and the lower row steps 9-16**.
- **Active steps light in bright channel colour and inactive steps in dim channel colour.** Pressing a pad toggles its step.
- Channel Rack up/down changes the channel being edited, and the pad colour follows the new channel.
- **Playhead**: while the transport plays, the current step is **bright white**. When paused, that pad stays white. When stopped, no playhead is shown.
- With the FLkey's own Play button, the sequencer always starts from step 1. A start point the user moves with the mouse is respected.
- **Graph editor via encoders.** The encoders stay in the last encoder mode until a step is held. While steps are held, encoders 1-8 edit the eight graph parameters: Note Pitch, Velocity, Fine Pitch, Panning, Mod X, Mod Y, Shift, Repeat. FL opens the graph editor and follows the note value ([K37 p.27-28](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- **Quick edit**: hold a step and move an encoder within one second. The graph editor shows while the step is held and closes when it is released.
- **Latch edit**: hold a step for more than one second. The pads light in the colour of a graph-editor parameter, and further presses add or remove steps from the selection. Every edit applies to all selected steps. Pressing the **pulsing** Channel Rack-down button exits.

**User Chord mode** ([K37 p.29-31](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- The pads are blank until chords are assigned. Assigned pads are **blue**, and the playing pad is **white**.
- To assign a chord, hold a blank pad and play up to six keys. The screen shows a keyboard picture, the notes and the **chord name**.
- The page buttons transpose the whole chord bank by ±12 semitones; with Shift they move it by octaves, up to ±3 octaves.
- Removing: hold Channel Rack-down. Pads that hold a chord turn **red** and the screen reads "Delete Chord!". Pressing a pad then deletes its chord.
- On the Mini, Channel Rack-up toggles **chord detection**, which shows the name of the chord being played on the keys ([MINI p.26](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).

**Chord Map** ([MINI p.26-33](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf))
- The left eight pads play eight chords that fit the current scale.
- The right six pads (6-8, 14-16) are **performance modifiers**, held while pressing a chord pad: Manual Arp Up, Inversion Up, Split Bass+Chord, Manual Arp Down, Inversion Down, Split Left/Right.
- Channel Rack-up latches a performance pad, and only one performance pad works at a time.
- Encoders: **Adventure and Explore** move through 40 chord banks per chord set; **Spread and Roll** change the voicing and strum.
- The chord set follows the scale chosen in Scale mode; the guide's table maps the 30 scales onto 12 chord sets.
- The screen shows the chord name and a keyboard picture of the chord.

**Arp Pattern** ([K37 p.31-32](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Top-row pads are the arp steps: active steps blue, inactive unlit, and a moving playhead.
- Bottom-row pads apply a per-step function, cycled with a Function button: **Tie** (red, gate 110%), **Accent** (orange, +30 velocity, capped at 127) or **Ratchet** (yellow, two triggers).

**Custom mode**
- The pads send notes, Program Change or CC messages set in Novation Components. In Custom mode the pads **light from incoming MIDI** (the External Feedback setting) ([MINI p.59, p.64](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).

**Other**
- On the Mini, Shift + Channel shows the MIDI channel on the pads: they light **red, with the current channel brightest**, and pads 1-16 choose the channel ([MINI p.42](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- **Holding Shift while FL's Channel Rack is visible shows the current selection** (channel bank, encoder bank and selected channel; the mixer bank in Mixer encoder modes). FL draws this as a highlight on screen ([K37 p.35](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).

**MK1 (for comparison)**
- The MK1 guides list **Scale Chord** and **Note Repeat** as features. Search snippets show them in the table of contents of the English v4 guide and the Chinese guide ([FLkey 37 guide v4 EN](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/FLkey%2037%20User%20Guide%20v4%20English%20-%20EN.pdf), [ZH](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_37_user_guide-pdf-zh-chs.pdf)). I could not open those PDFs (size limit).
- Product listings for the MK1 mention "Note Repeat" on the pads, plus Pad and Pot Custom modes ([zZounds](https://www.zzounds.com/a--3981094/item--NOVFLKEY37)).

### Inferences
- Patterns mode and Arp Pattern appear new in FLkey 2. Drum seems to replace MK1's "Instrument" mode, and Chord Map replaces "Scale Chord". This is based on the MK2 mode tables compared with the mode list in the brief; I did not read the MK1 guide body to confirm.
- Note Repeat is absent from both FLkey 2 tables of contents, which suggests it was dropped in MK2. The Mini guide still names a "Scale/Note Repeat" button label (p.42), which looks like leftover MK1 text.
- Patterns that apply directly to a 16-pad controller with a small screen:
  - Base colours come from FL objects, and the selected or playing item is white.
  - Step pads are bright or dim in the channel colour.
  - Navigation buttons light only when they can move.
  - Delete mode turns pads red while a modifier is held.
  - Modifier buttons that pulse while a latch is active.
  - Pads that adapt to FPC and Slicex.
  - Holding a step turns the encoders into graph-editor controls.

### Gaps
- Exact RGB and brightness values (how "dim" the inactive steps are) are not documented. Neither is how the script maps FL's 24-bit colours onto the pad palette; see the last question for the Fire's approach.
- I found no documentation of how the sequencer shows patterns longer than 16 steps. The Fire script uses a channel-rack start-position offset, but the FLkey guides only mention paging left and right in Sequencer mode, which focuses the Channel Rack.
- The MK1 body text (Scale Chord, Note Repeat behaviour) was not read, because the PDFs exceed the fetch limit.

## How are the knobs/faders mapped, and how is the focused window handled?

### Takeaway
There are eight endless encoders with modes **Plugin, Mixer (Volume/Pan), Mixer Inserts, Channel (Volume/Pan), Transport, Custom**, selected from the Shift layer. Sub-pages are reached with the encoder-bank buttons. Banking is coupled to the pad mode: in Channel Rack pad mode it moves in eights so that the encoders line up with the bottom pad row; in other modes it moves by one. **Pressing a mode or turning a control brings the matching FL window to the front.** Only the 49/61 have nine faders.

### Cited Findings
**Encoder modes** ([K37 p.16-19](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- **Plugin**: eight parameters of the focused plugin. The screen briefly shows the parameter name and the new value.
- **Mixer**: Volume and Pan pages, switched with the encoder-bank buttons; on the Mini, Pan is Shift + bank-down ([MINI p.34](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)). Both work in banks of eight tracks.
- **Mixer Inserts**: three pages: inserts 1-8, inserts 9-10, and Equalizer.
- **Channel**: Channel Volume and Channel Pan pages, banks of eight.
- **Transport**: encoder 1 scrubs the position ("Scrb"), 2 zooms ("Zoom"), 5 selects markers ("Mark"), 8 sets the tempo ("BPM"); 3, 4, 6 and 7 are unused. The screen shows these short names.
- **Custom**: messages set in Components. Any FL parameter can be mapped by right-clicking it and choosing "Link to controller" (a per-project link) or "Override global link" (follows the focused instance).

**Plugin mode coverage**
- Plugin mode works with most native FL plugins through **fixed, preset mappings**. Third-party plugins need Custom mode ([K37 p.17](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- The installed script contains a plugin-definition folder (`script/plugin`) and a `plugin_parameter_view` / `plugin_parameter_screen_view` / `plugin_parameter_preview_view` set. This is from file names only; local path `~/Documents/Image-Line/FL Studio/Settings/Hardware/Novation/script/`, no URL.

**Banking**
- In Channel Rack pad mode the encoders bank in eights, so they align with the bottom row of pads; in other modes they move one track or channel at a time.
- FL's **red selection rectangle** shows which bank the encoders control ([K37 p.16-17](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- On the 37, the Mixer Bank buttons move by eight tracks, or by one with Shift ([K37 p.10](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- On the Mini, Shift + the Scale/Arp buttons move left and right through mixer tracks ([MINI p.42](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).

**Preview without changing**
- Holding Shift and moving an encoder shows the parameter on the screen without changing it ([MINI p.40, p.44](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- The script has matching `*_preview_view` modules, for example `mixer_volume_preview_view`, `channel_rack_pan_preview_view` and `not_used_preview_view` (file names, local).

**Faders (49/61 only)**
- Only the 49 and 61 have faders and fader buttons ([MusicTech](https://musictech.com/reviews/controllers/novation-flkey-2-review/)).
- There are nine faders with fader modes. Mixer Volume is the default, and the modes include Plugin and Custom; they are picked with Shift + a Fader Mode button. This comes from a search snippet of [Novation user-guide article](https://userguides.novationmusic.com/hc/en-gb/articles/35710304305682), which I could not fetch (HTTP 403).
- MusicTech says the faders map to "channel strips, panning, mute, and solo" ([MusicTech](https://musictech.com/reviews/controllers/novation-flkey-2-review/)).
- An MK1 forum post reports that in Channel Volume fader mode the fader buttons become mute buttons ([IL forum](https://forum.image-line.com/viewtopic.php?p=2061570)). This is a user post, not the manual.
- The installed script has a `mixer_volume_fader_layout_manager`, a `mixer_master_volume_view` (the ninth fader as master, presumably) and solo/mute/arm toggle views for mixer tracks and channels (file names, local).

**Focus rules** ([K37 p.36](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf); [MINI p.37](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf))
- **Channel Rack** comes to the front on: choosing the Channel Rack or Sequencer pad mode; choosing the Channel Volume or Pan encoder mode; paging the sequencer; selecting a channel.
- **Mixer** comes to the front on: choosing the Mixer Volume or Pan encoder mode; moving a mixer encoder; banking in the mixer.
- **The selected channel's plugin window** comes to the front on moving a parameter in Plugin mode.

**Takeover**
- The setup steps enable FL's "Pickup (takeover mode)" and "Send master sync" on the DAW output ([MINI p.13](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)). Endless encoders do not strictly need pickup; it matters for the faders.

**Encoder speed**
- An "Encoders Curve" setting (Slow/Medium/Fast) applies only to Custom modes, not DAW modes ([MINI p.64](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- The script has a `control_change_rate_limiter` module (file name, local).

### Inferences
- With eight endless encoders and an FL script, the script owns relative-value handling. Pickup only matters for absolute controls such as faders.
- If a 16-pad controller has fewer encoders, the same "bank aligned to the bottom pad row" idea works with however many encoders it has.
- The focus rules are a deliberate UX choice: the window that matches the active control is always brought to the front.

### Gaps
- I did not see the per-plugin parameter lists for Plugin mode (which eight parameters for Sytrus, Harmor and so on). They live in the script's plugin definitions, which I did not read because of the script licence (see the last question).
- The 49/61 fader-button behaviour per fader mode (mute/solo/arm cycling) is not confirmed from an official text I could read.

## Transport and other buttons: Score Log, Quantise, Metronome, Undo/Redo, Pattern/Song, Note Repeat

### Takeaway
On the 37/49/61 every FL global action has a dedicated button: Score Log (Shift = Quantise), Undo (Shift = Redo), Metronome and Pattern/Song, plus Stop, Loop, Play and Record. The Mini keeps only Play and Record. Loop Record is turned on once, at the first connection, and is not a button. Without a DAW, Play and Stop send MIDI real-time messages.

### Cited Findings
**Transport** ([K37 p.11, p.14-15](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- **Stop** stops and resets the position.
- **Loop** toggles FL's loop-recording function.
- **Play** works like FL's Play button: it continues and pauses.
- **Record** toggles recording.
- Play and Stop send **MIDI real-time** messages when they are not controlling a DAW.
- The Mini has only Play and Record ([MINI p.14-15](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).

**Score Log** ([K37 p.33](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Inserts all notes FL received in the **last five minutes** into the selected pattern. If the pattern already has notes, FL asks for confirmation.
- Identical to FL's Tools > Dump Score Log to Selected Pattern. The script has a `dump_score_log_button_view` (file name, local).

**Quantise** ([K37 p.33](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Shift + Score Log runs FL's **"quick quantize start times"** on the selected channel's piano roll, using the current snap setting.

**Undo/Redo** ([K37 p.34](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Undo, and Shift + Undo for Redo. FL's "Alternate undo mode" setting does not change their behaviour.

**Metronome and Pattern/Song** ([K37 p.34-35](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Metronome toggles FL's metronome.
- Pattern/Song switches FL between Pattern mode and Song mode.

**Loop Record** ([K37 p.35](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf))
- Cannot be toggled from the FLkey. The script turns it ON at the **first connection** so a recording loops the pattern instead of extending it.
- If the user turns it off in FL, it stays off across reconnects.

**Other**
- Pattern cloning (Shift + Page-down) and the pattern-length and clear views in the script (`pattern_length_button_view`, `pattern_clear_view`, `clone_loop_button_view`; file names, local) suggest more pattern utilities. Some may belong to the Launchkey or FLpad models that share the codebase.
- **Note Repeat**: not found in the FLkey 2 guides (see the first question). Its job is partly taken by the arp's Rate and Chord types, an inference from [MINI p.45-46](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf).
- **Akai Fire (Image-Line's own)**:
  - The Fire's transport handling in its script uses `transport.globalTransport` with FPT_Loop, FPT_Metronome, FPT_Play, FPT_WaitForInput, FPT_Stop, FPT_CountDown, FPT_Record, FPT_LoopRecord, FPT_Snap, FPT_TapTempo, FPT_Undo, FPT_WindowJog and FPT_TrackJog. Source: the local file `~/Documents/Image-Line/FL Studio/Settings/Hardware/Akai FL Studio Fire/device_Fire.py` (version 2026.4); the script's own header points to [IL forum](https://forum.image-line.com/viewtopic.php?p=1496543#p1496543).
  - Fire Shift combinations listed by Image-Line: Shift+STEP = Accent, Shift+NOTE = Snap, Shift+DRUM = Tap tempo, Shift+PERFORM = Overview ([Image-Line Fire page via search](https://support.image-line.com/redirect/Akai%20FL%20Studio%20Fire), [IL forum Fire thread](https://forum.image-line.com/viewtopic.php?t=191060)).

### Inferences
- For a script on a controller with a few spare buttons, these one-press FL actions give the most value: Score Log dump, quick quantize, undo/redo, metronome, pattern/song, and loop-record forced on once. Each maps to a single `transport.globalTransport` or `general` call.

### Gaps
- The FLkey 2 49/61 guides were not readable, so any extra buttons on those models (for example dedicated mute/solo/arm per fader) are unconfirmed beyond MusicTech's summary.

## What does the screen show, and when?

### Takeaway
The OLED (MK2: brighter, three lines plus basic graphics, per [MusicTech](https://musictech.com/reviews/controllers/novation-flkey-2-review/)) mostly shows **temporary messages**: the parameter name and value after a control moves, the mode name after a mode change, the octave or transpose amount, and chord names with a keyboard picture. A **Display Timeout setting of 1-10 s** sets how long they stay. Holding Shift and touching an encoder previews its assignment without changing the value.

### Cited Findings
- Plugin mode: moving an encoder shows the parameter name and new value for a moment ([K37 p.16](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- Transport mode: the screen shows short labels: Scrb, Zoom, Mark, BPM ([K37 p.18](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- Mode change: for example, "Pad Mode Arp Pattern" shows briefly ([K37 p.31](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_37_user_guide_v5_en.pdf)).
- Octave and transpose: the screen briefly shows the shift ("+1") and the current key range ("C1 – C5"). The Octave buttons' brightness also scales with the amount of shift ([MINI p.38-39](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Scale mode: turning it on shows the selected scale. Encoders 1-3 set root, scale (30 scales) and mode (Snap / Filter / Easy) ([MINI p.40-41](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Chords: User Chord assignment, chord detection, Chord Map and Fixed Chord all show the **chord name plus a keyboard picture**. "Delete Chord!" shows while deleting ([MINI p.25-27, p.58](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Arp: moving an encoder shows the parameter and value. The Rhythm encoder draws the step pattern on the screen ([MINI p.44, p.47](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Settings: "Display Timeout 1-10" sets the length of temporary messages in one-second steps (default 5, per the table on [MINI p.64](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf); the extracted table columns are jumbled, so the exact default is uncertain).
- Shift preview: Shift + moving an encoder shows the parameter without changing it; this also works in HUI mode ([MINI p.40, p.62](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- Script screen views (file names, local), which indicate further screen contents:
  - `channel_selected_screen_view` and `channel_bank_selected_screen_view` (channel name or bank on select)
  - `mixer_track_selected_screen_view` and `mixer_bank_screen_view`
  - `pattern_select_screen_view`
  - `preset_button_screen_view` (preset name)
  - `mixer_volume_screen_view`, `mixer_pan_screen_view`, `channel_rack_volume_screen_view`, `channel_rack_pan_screen_view`
  - `button_function_screen_view` (names a button's function)
  - `fl_studio_text_view`
  - `discarded_surface_action_notification_view` (presumably a message when an action is not possible)
- **Akai Fire for comparison** (local `device_Fire.py`; FL's built-in `screen` module):
  - The script calls `screen.init/setup` with timeouts, `displayText`, `displayTimedText` (temporary messages), `displayBar` (a value bar, optionally bipolar), and `animateText`, and blanks the screen after inactivity.
  - It shows messages such as "Chan: <channel name>" on channel select, "<channel>: <param>: <value>" bars while editing held steps, the browser's focused node caption, and loop-length names.
  - It shows hint-bar messages in FL through `ui.setHintMsg`, for example pad brightness and saturation percentages.

### Inferences
- The pattern is a resting screen with mode, context and selected channel, plus short-lived overlays after every control action. The timeout is a user setting.
- Overlays should give the name and value, show a bar for continuous values, and show a keyboard picture or chord name for musical state.
- The idle or status screen should name the selected channel or pattern, the cue the user cannot see on the pads.

### Gaps
- No official description of the FLkey 2 **idle or resting** screen content in FL mode (for example whether it shows the selected channel name permanently). The guide screenshots were not machine-readable.

## Where are the official FL Studio scripts, and what can be learnt from their structure?

### Takeaway
On this Mac the Novation scripts are installed in the user data folder, `~/Documents/Image-Line/FL Studio/Settings/Hardware/Novation/` (version string `26.09.30`). There is one shared, modular Python codebase for FLkey, FLkey 2, FLkey Mini 1/2, FLpad, Launchkey and Launch Control. Each model and port has a thin `device_*.py` entry file. FL **auto-detects** them by the `supportedHardwareIds` header, which is matched against the USB MIDI device-inquiry response. **Each FLkey exposes two ports, "MIDI" and "DAW", each with its own script.** The Novation scripts carry a proprietary licence that forbids reverse engineering, so I read only file names and the header lines. The Image-Line Fire script (`device_Fire.py`, ~3,000 lines, no restrictive licence header) shows the concrete techniques.

### Cited Findings
**FL's script mechanism**
- Scripts are `device_*.py` files under the user data folder's Settings/Hardware/<folder> ([IL MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)).
- Header lines:
  - `# name=` sets the name in Controller type.
  - `# url=` must point to forum.image-line.com.
  - `# receiveFrom=` links scripts through `device.dispatch`.
  - `# supportedDevices=` matches device names.
  - `# supportedHardwareIds=` matches hardware IDs, with partial IDs ignoring the firmware version ([IL MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)).
- Callbacks: OnInit/OnDeInit, OnIdle ("from time to time"), OnRefresh(flags) / OnDoFullRefresh, OnMidiIn → OnMidiMsg → OnNoteOn, OnUpdateBeatIndicator(0 off / 1 bar / 2 beat), OnDirtyChannel(index, CE_New/Delete/Replace/Rename/Select), OnDirtyMixerTrack, OnProjectLoad, OnDisplayZone. The advice is to collect changes in the OnDirty* callbacks and redraw in OnRefresh ([IL MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)).
- OnRefresh flags: HW_Dirty_Mixer_Sel/Display/Controls, RemoteLinks, RemoteLinkValues, ControlValues, FocusedWindow, Performance, LEDs, Patterns, Tracks, Colors, Names, ChannelRackGroup, HW_ChannelEvent, Undo, ChannelRack, GraphEditor ([IL MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)).
- API calls relevant here: `channels.getChannelColor`, `channels.getGridBit/setGridBit`, `mixer.getSongStepPos`, `ui.getFocused/showWindow` (widMixer 0, widChannelRack 1, widPlaylist 2, widPianoRoll 3, widBrowser 4), `plugins.getParamCount/getParamName/getParamValue` (normalised), `ui.setHintMsg`, `device.midiOutSysex`, `device.dispatch` ([IL MIDI scripting](https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm)).

**Novation two-port setup**
- Each FLkey has "MIDI" and "DAW" ports, with scripts named "FLkey 2 MIDI" and "FLkey 2 DAW" (Mini: "FLkey 2 Mini MIDI/DAW").
- The ports get different port numbers, and the outputs share the input's port number so that the scripts link automatically.
- FL normally detects them on its own; a manual setup and "Update MIDI scripts" button are the fallback ([MINI p.12-14](https://fael-downloads-prod.focusrite.com/customer/prod/downloads/flkey_2_mini_25_user_guide_v9_en.pdf)).
- MusicTech: "no scripts to load", it just works ([MusicTech](https://musictech.com/reviews/controllers/novation-flkey-2-review/)).

**Device detection (local file headers)**
- `device_novation_flkey_2_daw.py` declares `supportedHardwareIds=00 20 29 53 01 00 01,00 20 29 54 01 00 01,00 20 29 55 01 00 01` (37/49/61). The `_midi` variant ends in `00` instead of `01`.
- FLkey 2 Mini uses `00 20 29 50 01 00 0x`.
- The MK1 scripts use family bytes 3B (Mini), 3D (37), 3E (49) and 3F (61).
- `00 20 29` is Novation's SysEx manufacturer ID, so the last byte tells the MIDI port from the DAW port. These IDs are what FL reads from the device-inquiry reply.
- Source: local files in the folder above, no URL.

**Structure (folder and file names only)**
- `script/device_adapters/{device_manager, device_setup, fl_setup, fl_to_application_adapter, led_writer, screen_writer}`
- `script/device_dependent/{FLkey2, FLkey2Range, FLkeyMini2, …}`, holding per-mode "layout managers": `channel_rack_pad_layout_manager`, `drum_pad_layout_manager`, `patterns_pad_layout_manager`, `sequencer_pad_layout_manager`, `sequencer_step_edit_encoder_layout_manager`, `plugin_encoder_layout_manager`, `mixer_encoder_layout_manager`, `mixer_inserts_encoder_layout_manager`, `transport_encoder_layout_manager`, `mixer_volume_fader_layout_manager`, `plugin_browser_view`
- `script/device_independent/view/`, with roughly 100 small single-purpose views. Each one is a feature, an LED feedback, a screen message or a preview, for example `channel_select_view`, `channel_rack_volume_feedback_view`, `channel_rack_volume_screen_view`, `channel_rack_volume_preview_view`, `fpc.py`, `metronome_button_view`, `quantise_button_view`, `redo_button_view`, `scale_model_controller`.
- `script/device_independent/layout_manager/{mode_cycling_layout_manager, paged_layout_manager}`
- `script/firmware_version_validator.py`, `script/fl_api_version_check_controller.py`

**Script licence**
- Novation's header reads "proprietary and confidential", and the terms forbid "reverse engineering, repurposing" (local file header, all `device_novation_*.py` and `version.py`). I therefore did not read the implementation code.

**Akai Fire script techniques** (local `device_Fire.py`, Image-Line, header `# version 2026.4`, forum URL [IL forum](https://forum.image-line.com/viewtopic.php?p=1496543#p1496543))
- **Colour mapping**:
  - The pad colour starts as `channels.getChannelColor(n)`.
  - The default sampler grey (`CT_ColorT[CT_Sampler]`) is replaced with near-white `0xC8C8C8`.
  - The colour is converted to HSV and scaled by a per-user brightness and saturation (`ScaleColor`, which keeps a minimum v of 0.1 for lit pads).
  - It is then halved into 7-bit R, G and B for SysEx (`AddPadDataCol`).
- **Differential LED updates**: a `BtnMap` cache of the last colour per pad, so only changed pads are added to one batched SysEx message.
- **Step sequencer**:
  - `RefreshStepSeq` reads `channels.getGridBit` over a 16-step window starting at a `ChanRackStartPos` offset, which allows paging through longer patterns.
  - The playing step (`self.CurStep = mixer.getSongStepPos()` in OnIdle) is drawn white.
  - Held steps blink. Pad presses call `setGridBit`.
  - With steps held, the knobs edit step parameters (pitch, velocity, pan, mod X/Y, shift) with on-screen bars.
- **OnUpdateBeatIndicator** flashes the Play button (bar vs beat colours) and pulses the pads that are playing.
- **"Receive notes from" awareness**: if a channel's MIDI input port equals this device's port (`channels.getChannelMidiInPort(n) == device.getPortNumber()`), the select LED blinks to show that the routing is locked.
- **Multi-device master/slave layouts**: several Fires are linked through `device.dispatch`.
- **Browser**: the script navigates with `FPT_WindowJog` and shows `ui.getFocusedNodeCaption()` on the screen.
- **Image-Line's Fire documentation**: knob modes Channel / Mixer / User 1 / User 2; a Browser button with the Select knob to browse and load samples, presets and plugins; Shift/Alt + Select picks the mixer track or channel ([IL forum Fire thread](https://forum.image-line.com/viewtopic.php?t=191060)).
- **Fire pad modes**: Step, Note (keyboard or harmonic layouts), Drum (FPC / Slicex / Omni) and Perform (playlist clip launching) ([Image-Line Fire page via search](https://support.image-line.com/redirect/Akai%20FL%20Studio%20Fire)).
- A MusicRadar review calls the step sequencer the Fire's strongest mode and its Drum mode less successful ([MusicRadar](https://www.musicradar.com/reviews/akai-professional-fire)).

### Inferences
- **Architecture to copy.** One script per port, a mode/layout manager that swaps which "views" are active, and small views that each own one feature: an LED feedback part, a screen message part and a Shift-preview part. Those views redraw from FL state on OnRefresh flags; Colors, Names, ChannelRack, Patterns, FocusedWindow and Mixer_Controls are the important ones.
- **Detection.** The Ex-Machina device would need its own `supportedHardwareIds` (or `supportedDevices` by port name) for FL to auto-assign the script. Its device-inquiry reply decides this.
- **Colours.** A small-palette or 7-bit RGB pad controller needs the Fire-style pipeline: FL colour → HSV → brightness and saturation scaling → quantise to the device palette. Two extra rules help: replace FL's default grey channel colour with white, and use white for "selected" and "playhead".
- **Performance.** Cache the last LED state and send only diffs. Compute the playhead in OnIdle from `mixer.getSongStepPos()`; the Fire does exactly this.

### Gaps
- I did not read the Novation implementation (licence). Their exact colour quantisation, OnIdle cadence, and the SysEx protocol between the FLkey 2's screen and LEDs are therefore not documented here. That reading is the user's call.
- I found no public Novation programmer's reference for the FLkey 2 DAW-port protocol (screen text, pad RGB) in this pass.
