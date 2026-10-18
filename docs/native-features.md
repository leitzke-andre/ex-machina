# Native Maschine Mikro MK3 features that the MIDI firmware could reproduce

Review of NI's *Maschine Mikro MK3 Manual* (`proprietary/Maschine_Mikro_MK3_Manual_English.pdf`, English, text extracted locally with PDFKit; "p." = PDF page) for functions of the controller itself that do **not** need the Maschine software: they act on the pads, buttons, encoder, strip and display, and the result is MIDI. Written 2026-10-18 after the user asked for modes with on-screen feedback (Pad Mode, Keyboard, Fixed Vel, a velocity-curve selector on Shift + Volume). Resource numbers are from `docs/hardware-probe.md` (about 65 KB of free flash, 9.7 KB of free RAM, about 400 bytes of stack headroom). **Status 2026-10-20: generation 8 adds on-device preset slots, the MIDI channel selector, a step sequencer and the Ex-Machina idle screen with a live status line and a sequencer grid (`docs/midi-patch.md`; built and emulator-tested, flashing is step 9 of `docs/hardware-plan.md`). Earlier: **Status 2026-10-19: phase 1 is flashed and works (the screen messages were checked by the user); phase 2 (scales, chords, strip modes with the LED bar, encoder targets, Program Change) is flashed (step 7); phase 3 (tap tempo, MIDI clock out / in, Note Repeat and the arpeggiator, mute / solo pads, strip strumming, the Lock snapshot) is built and emulator-tested, not flashed (step 8). (Phase 1 details: `docs/midi-patch.md` "The controller's own functions", `docs/hardware-plan.md` step 6); the rest is still a plan.**

## Decisions (the user, 2026-10-18)
- The velocity-curve selector is **Shift + Volume** (the button already carries "Velocity" as its second label); Shift + Swing steps back. The modes **reset at power-up, the curve choice is kept**. 16 Velocities is on Shift + Fixed Vel, as NI does it. Keyboard ascends left to right and bottom to top from pad 1 = C3.
- The display keeps "Maschine Mikro" and shows **contextual information temporarily** when a mode or setting changes.
- MOD on the strip should hold its last value (phase 2). Scales: yes. The step sequencer waits ("hold").
- **Tap tempo / clock: both** (answer to "can we safely run an internal MIDI clock?"): yes, an internal timebase is safe. Note Repeat and the arpeggiator run on a purely internal software timer and never have to emit a MIDI clock; sending 0xF8 clock plus Start / Stop would be a separate **opt-in, off by default**, so that there is only ever one clock master (the app's, or the device's if the user asks for it). An incoming MIDI clock (the firmware ignores real-time bytes today) overrides the tapped tempo when it is present. NI's own design leaves the tempo to its software, and most of the iOS apps tried here cannot send clock to a controller (Gadget and FL Studio Mobile cannot), so tap tempo matters. Costs: a timer jitter of about 1 ms (the main loop), and flash saves stall the loop for 20-40 ms (never save while repeating).

## Built in phase 3 (2026-10-19, not flashed)
The grid (internal tempo, tap tempo, MIDI clock out as an opt-in, an incoming clock that takes over), Note Repeat and the arp (six patterns, seven rates, 1-4 octaves, latch), mute / solo pads, strip strumming, the Lock snapshot (store and recall the encoder targets, mod value and encoder value as CCs), the beat blink on the Tap button, the page (actions, arp settings, start tempo), and `test_phase3.py`. Not built: the step sequencer, swing, the metronome click (only the blink), LOCK of every parameter, user chord sets, FX performance.

## Built in phase 2 (2026-10-19)
Scales (24, Keyboard mode), Chords mode with five chord types, strip modes (Pitch, Mod with a bar on the LEDs, Perform), the encoder targets (Volume / Swing / Tempo in the preset), Program Change (Favorites / Browser / Project), the page (a second selector for the actions with a choice, scale and chord type at start, target CCs), and `test_phase2.py`. Not built from the plan: Mute / Solo pads (11), the strip's NOTES strumming and PERFORM FX, LOCK, user chord sets.

## Built in phase 1
Mode actions in the mapping table (Pad Mode, Keyboard, Fixed Vel, 16 Velocities, velocity-curve step, transpose, panic, Shift), the shift layer (a second action and parameter per button), the nine velocity-curve tables with the choice kept in a settings log in flash, pad pressure options (aftertouch, channel pressure, CC, off), mode LEDs, the display engine (title, detail line, bar, temporary, original picture restored), the browser page (new actions, a Shift row per button, a *Playing* card), the preset *Maschine-like modes*, and `test_modes.py`.

## What the manual says the controller does by itself
- **Pad Input Modes** (p. 23-24, 148-158): PAD MODE = Group mode (one sound per pad; drums; the display shows a base key that the Encoder adjusts in semitones, Shift + Encoder in octaves); KEYBOARD = pads play 16 pitches from a root note on pad 1 (default C3), chromatic by default, or any of about 100 scales in 7 banks (the root is always on pad 1, the following pads continue into the next octave); CHORDS = each pad plays a chord (Harmonizer on the scale, 16 factory chord sets of 12, user chords); STEP = a step sequencer on the pads; FIXED VEL = every pad plays one velocity (value adjustable, shared by all modes); Shift + FIXED VEL = **16 Velocities** (all pads play the same note with 16 predefined velocities, the display shows them).
- **Smart Strip** (p. 166-168) with four modes: PITCH (centred pitch bend that springs back), MOD (CC 1; it keeps the last value after release, the LED bar shows it), PERFORM (a Perform FX parameter), NOTES (strumming the held pads, or all pads, in the direction of the swipe). With no mode active the strip LEDs show the playhead.
- **Note Repeat and Arp** (p. 158-161): hold NOTE REPEAT and a pad in Group mode to repeat the sound at a rate (the Encoder picks it); in Keyboard / Chords mode the same button is an arpeggiator (type up, down, up-down, played, chord; rate from 1 bar to 1/128; normal, triplet, dotted; pressure on a pad varies the velocity; LOCK pins it; swing applies). It runs on its own clock when the transport is stopped.
- **Mute and Solo modes, Choke All Notes** (p. 161-163): in Mute / Solo mode pads mute / solo sounds (muted pads dim); Shift + Mute chokes all playing notes (a panic).
- **Quick Edit** (p. 19, 39): VOLUME, SWING and TEMPO select what the Encoder adjusts; the display shows the value.
- **Transport and helpers** (p. 21-22): PLAY, REC, STOP, RESTART, TAP (tap tempo), Shift + TAP = metronome, FOLLOW, ERASE (hold + pad), LOCK (snapshot of all modulable parameters, press again to recall), AUTO (record modulation while turning the Encoder).
- **Group and pages**: GROUP + pads 9-16 select a Group (A-H); in NI's MIDI mode the same gesture selects a pad page, each page +12 notes (`docs/research-sources.md`).
- **Browser buttons** (p. 18): Project / Favorites / Browser + Encoder scroll and load; Shift + Project enters MIDI mode.
- **Hardware preferences** (p. 71): touch sensitivity and velocity scaling of the pads, display brightness (set in the software).
- **MIDI mode** (p. 74): the fixed CC map this project started from.
- Not reproducible without the software: Sounds and Groups, plug-in control, the Browser, Patterns / Scenes / Arranger, the sampler, Perform FX, undo / redo of the project, user chords created on other Maschine hardware.

## What can be reproduced, and what it costs
Effort: S = hours (a day of tests), M = a few days, L = a week or more. "Display" = a status or value message on the screen (needs the text engine below).

| # | Feature | Firmware behaviour | Needs | Effort | Value |
|---|---|---|---|---|---|
| 1 | **Fixed Vel** | toggle: every Note On at the fixed value (default 127, adjustable) | mode action, LED, display | S | high |
| 2 | **16 Velocities** | all pads play one note with velocities 8, 16 ... 127 (pad n) | mode action | S | medium |
| 3 | **Pad Mode** (Group / drums) | pad notes = the GM drum layout from a base key; Encoder = base key (semitone, octave with Shift) | mode state, encoder target | S | high |
| 4 | **Keyboard**, chromatic | pad 1 = root (C3 = 60), pads ascend; root by semitone / octave | mode state | S | high |
| 5 | **Scales** | the root on pad 1 and the following pads on the scale degrees (about 100 scales = 12-bit masks, about 1.5 KB with names) | table in flash, selector UI | M | high |
| 6 | **Velocity curve selector** (Shift + Volume) | steps through the curves; the choice is kept in the saved mapping | shift layer, curve tables (7 x 256 B), display | S | high |
| 7 | **Panic** (Shift + Mute: choke all) | All Sound Off / All Notes Off on all channels | shift layer | S | medium |
| 8 | **Pad pages** (Group + pad, +12 notes per page) | pad base shifts in steps of 12 | shift / hold layer | S | medium |
| 9 | **Strip modes**: PITCH, MOD, NOTES (and PERFORM = a CC) | pitch bend (centred, springs back), CC 1 that holds the last value with the LED bar showing it, strumming of the held pads | pitch bend message, strip LED bar, mode buttons | M | high |
| 10 | **Encoder targets** (Volume / Swing / Tempo buttons) | the Encoder sends the CC of the chosen target (3 user CCs), value on the display | config slots, display | S | high |
| 11 | **Mute / Solo modes** for pads | pads mute / solo themselves locally (notes suppressed, pads dim) | per-pad state, LEDs | S | medium |
| 12 | **Pressure options** | pad pressure as polyphonic, channel pressure, a CC, or off (several apps ignore or mishandle poly pressure) | config | S | high |
| 13 | **Program Change** from Browser / Favorites + Encoder | new action: Program Change and Bank Select, value on the display | new MIDI message type | S | medium |
| 14 | **Chords** (Harmonizer) | a pad plays the chord built on its scale degree (types such as 1-3-5, 1-3-5-7, 1-4-5); needs the note list per held pad for the Note Offs. The factory chord sets are NI's data and would have to be written from scratch | scales (5), RAM for held notes | M | high |
| 15 | **Tap tempo and a timebase** | tempo from TAP, a microsecond clock (the Cortex-M3 cycle counter, if the chip implements it, else the SysTick); MIDI clock / Start / Stop in and out | timebase, MIDI realtime input | M | high |
| 16 | **Note Repeat / Arp** | held pads re-triggered at a rate (normal, triplet, dotted), arp types up / down / up-down / played / chord, pressure varies the velocity, LOCK pins it; clock from tap tempo or incoming MIDI clock | (15), (4/5), RAM for the held-note list | L | high |
| 17 | **Metronome / playhead** | Shift + TAP blinks the beat on a button LED; with incoming clock the strip LEDs show the position in the bar | (15) | S-M | low |
| 18 | **LOCK snapshots** | store the current values of the encoder targets and the strip, press again to send them back | config / RAM | S | low |
| 19 | **Step sequencer** on the pads | 16 steps per sound, tempo from (15), plays notes and can send MIDI clock; a small pattern store; Pattern / Scene / Variation (humanise, random) on top | (15), (16), RAM and a save format | L | medium (it makes the Mikro a standalone groovebox) |
| 20 | **Shift layer** for every button | a second action per button reached with Shift held, so the user can define combinations (the Shift + Volume curve selector is one) | config grows by 96 bytes, page and presets learn it | M | high (it doubles the mapping space) |

Not worth reproducing: AUTO (needs the host's parameters), Follow, Erase (needs a pattern), Grid, Navigate mode.

## What the features need from the architecture
1. **Mode actions.** New button action types (pad mode, keyboard, chords, fixed vel, 16 velocities, curve next, strip modes, mute / solo mode, panic, ...) in the same mapping table, so presets and the page can assign them like CC or note. A preset can then mix native-like behaviour with plain CC mappings, and a built-in preset "Maschine-like modes" would assign them to the buttons printed with those names.
2. **Run-time mode state** that is separate from the saved config: current pad mode, root note, scale, fixed-velocity flag, strip mode, held-note lists. Per the user's decision modes reset at power-up and the **velocity curve choice is saved** with the mapping.
3. **A shift layer**: one extra action and parameter per button, and Shift itself as a modifier action (hold).
4. **A text engine for the display** (below).
5. **A timebase** for 15-19 (the cycle counter or SysTick, plus an optional MIDI clock input; the firmware ignores incoming real-time messages today).
6. **Config growth**: root note, scale, fixed-velocity value, curve id, encoder target CCs, shift-layer actions, pad pressure mode, strip modes; the saved record is versioned (a shorter old record overlays the defaults), so existing saved mappings keep working.
7. **Resources**: flash is plentiful (the scales, curves and font add about 4 KB); RAM is the limit to watch for (held-note lists, the arp, a step pattern; each is a few hundred bytes); the stack must not take a 512-byte frame buffer.

### Display
The screen is 128 x 32 pixels, 1 bit per pixel, in 4 pages of 8 rows; the stock code draws "Maschine Mikro" and does not change it (user, 2026-10-18). The patch can write regions through the stock staging buffer (up to 256 bytes each). Plan:
- a small font (5 x 7 in 6-pixel cells, about 500 bytes, 21 characters per line, 4 lines) and a renderer in the main-loop hook;
- **write only when the stock "display pending" flag is clear and from the main loop**, so the race that cost LED frames cannot happen (the stock loop clears the flag first and then copies; from the tick, between service passes, the flag is a reliable interlock);
- **messages are temporary**: a message (for example `KEYBOARD  C3-D#4`, `FIXED VEL 127  ON`, `CURVE  HARD 2`, `CC 74  = 98` with a bar) for about 1.5 seconds, then the "Maschine Mikro" image is put back; the original image is captured from the stock framebuffer (RAM) once at start-up, so no NI bitmap has to be stored in the repository;
- the same text engine gives a host-text SysEx command ("write this on line n") for the page.

## Suggested order
1. **Core (approved scope):** mode actions, Fixed Vel, 16 Velocities, Pad Mode, Keyboard (root by semitone / octave), the velocity-curve selector on Shift + Volume (needs 20, at least for that one combination), button LEDs for the active modes, the display engine with temporary messages, pad pressure options (12), panic (7), pad pages (8). Then the page and presets learn the new actions, a built-in preset gives them NI's button layout, tests in the emulator (including the real stock display routine), and one flash with the usual checks.
2. **Playing:** scales (5), strip modes with the LED bar (9), encoder targets (10), mute / solo pads (11), Program Change (13), chords (14).
3. **Time:** tap tempo and clock (15), Note Repeat and Arp (16), metronome and playhead (17), LOCK (18).
4. **Sequencer** (19) only if wanted: it turns the controller into a standalone instrument and deserves its own design.

## Open questions
- Which button should select the **16 Velocities** mode: Shift + Fixed Vel, as NI does?
- The Keyboard layout: NI ascends left to right and bottom to top from pad 1; the same here unless you prefer otherwise.
- For the strip modes: should MOD hold its last value after release, as NI's does (a CC that stays), or return to 0?
- Whether the timing-based features (Note Repeat, Arp, step sequencer) should follow an incoming MIDI clock from the app, run on tap tempo, or both (both is the NI behaviour).
