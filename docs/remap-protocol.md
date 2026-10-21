# Run-time configuration: SysEx protocol and saved record

The patched device keeps its mapping in a **274-byte config block in RAM** (`struct cfg` in `tools/midi_patch/translate.c`). At power-up the block is the saved record in flash if there is a valid one, else the defaults the image was built with. A host edits the active block with SysEx and can keep it across power cycles. Everything the translator does (pad notes, button CCs and actions, the shifted layer, channel, encoder and strip, LED behaviour, velocity curve and pressure options) reads this block, so a change is live at once. The same protocol is implemented in `tools/midi_patch/mmk3_config.py` (Python, also the command line) and is what a browser UI speaks.

## Messages
All messages are `F0 7D 4D 4B <command> <data...> F7` (manufacturer ID 7D = non-commercial use, then `MK`), carried in USB-MIDI packets on cable 0 like any SysEx. All data bytes are below 0x80. The commands `01` (display region) and `02` (LED frame) predate this and are described in `docs/midi-patch.md`.

| Command | Request data | Reply |
|---|---|---|
| `10` INFO | none | `50 <protocol> <size lo7> <size hi7> <flags>`: protocol 2 (the block grew from 149 to 250, 255, 259 and 274 bytes within it: the size field tells), config size 274 as two 7-bit bytes, flags bit 0 = a valid saved config exists, bit 1 = the active config has changes that are not saved, bit 2 = the config in use at power-up came from flash; then the **firmware version** (0 = v0; the idle screen shows it) |
| `11` GET | none | `51 <the active config, 7-bit packed>` |
| `12` SET | `<config, 7-bit packed>` | `52 <status>` and, for status 2, `<offset lo7> <offset hi7>`. The config is checked and, if usable, **active at once** (not saved) |
| `13` SAVE | none | `53 <status>`. Writes the active config to flash (nothing is written if it is already saved; if it equals the defaults the saved record is erased instead) |
| `14` RESET | optional `01` | `54 <status>`. The defaults become active; with `01` the saved record is erased as well. INFO then reports unsaved changes unless the next boot loads exactly the defaults (nothing saved and an empty settings log) |
| `15` SLOT STORE | slot 0..3, then optionally a **name** (up to 20 ASCII characters, what the screen's detail line shows whole; lower case is made upper case, anything outside the font's 32-95 becomes `?`; a longer name is refused with status 1) | `55 <status>`: the active config is written to the slot's flash page, the name behind the record at page offset `0x120` (24 bytes, programmed after the record's magic; a power cut there leaves the slot valid with a shortened or no name). Status 1 without the slot number, 2 bad slot, 3 flash error. `mmk3_config.display_name()` / `displayName()` make it; a preset's display name is its own `display_name` or one made from its name (`preset_display_name()`, "(draft)" dropped) |
| `16` SLOT LOAD | slot 0..3 | `56 <status>`: the slot becomes the active config (not saved as the power-up one); status 4 = the slot is empty |
| `17` SLOTS | none | `57 00 <mask>` then 4 × 20 name characters (0 = none or padding; an older firmware sends no names): bit n set = slot n+1 holds a configuration this firmware would load (an intact record whose values it refuses, written by another version, counts as empty, as it does for the Project button) |
| `20` HOST | flags: bit 0 SCREEN, bit 1 RAW, bit 2 QUIET | `60 <status> <flags now>` (status 1: no flags byte or an unknown bit). **Host mode** for a DAW script (the FL Studio script, `docs/fl-studio.md`), RAM only. SCREEN: the picture behind the firmware's messages is the host's text (`21`), not the idle screen or the sequencer grid; it starts blank. RAW: every pad sends **note 36 + its number - 1** (pad 1 = 36 ... pad 16 = 51) on the MIDI channel whatever the pad mode, arp, mute / solo or step sequencer, without pressure, so a script can use the pads as a grid; what the pads hold is released when RAW changes. QUIET: no messages of the firmware's own. Host mode ends at power-up and with a SET, RESET or SLOT LOAD **from the host** that succeeds (not with the Project button's slot change) |
| `21` TEXT | line 0..3 (or `7F`: all four lines blank), column 0..20, then up to 21 − column characters | none (handled at once, like `01`). The characters replace those of the line from the column on (lower case shows as capitals, anything outside the font's 32-95 as `?`); line *n* is drawn on rows 8*n*..8*n*+6 in 6-pixel cells from x = 1, while HOST SCREEN is set (the text is kept otherwise). Every TEXT draws the picture again (two display regions, from the main loop) |
| `1E` PEEK | address (5 x 7 bits, MSB first), length 1..64 | `5E <status> <address, 5 bytes> <the bytes, 7-bit packed>`. **Read-only diagnostic**: flash `0x08000000-0x0801FFFF`, RAM `0x20000000-0x20004FFF`, the chip's flash-size / unique-ID / option-byte registers, FLASH interface registers, DBGMCU_IDCODE and CPUID; anything else (or a range crossing an end) is refused with status 1 so that it cannot bus-fault the device; bad length 2. `tools/probe_chip.py` uses it |

Status: 4 empty slot (SLOT LOAD). 0 ok, 1 wrong length (the unpacked config is not 274 bytes), 2 value out of range (followed by the offset of the first bad byte), 3 flash error. A reply carries the request's command plus 0x40. Requests are served one at a time: while one is being handled (a SAVE takes about 50 ms) a new one is dropped, so a host waits for the reply (it should time out after a second or so and ask again). Replies reach the host through the normal MIDI input endpoint, a few packets per main-loop pass and only as far as the transmit ring has room, so a host that is not reading delays them.

**7-bit packing**: the data in groups of up to 7 bytes; each group is preceded by one byte whose bit *k* is bit 7 of data byte *k*. 274 bytes become 314. (`pack7` / `unpack7` in `mmk3_config.py`.)

## The config block (offsets)
| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 4 | magic | `MMK3` |
| 4 | 1 | channel | MIDI channel 0..15 for pads, buttons, encoder, strip |
| 5 | 16 | pad_note | note of each pad, by report index (index 12 = the pad printed 1, index 0 = printed 13) |
| 21 | 48 | btn_cc | parameter of each button's action by button id (0..38 buttons, 39 encoder push, 40 encoder touch): CC number, note number or MMC command; 0xFF = none |
| 69 | 1 | enc_cc | encoder rotation CC; 0xFF = none |
| 70 | 1 | strip_cc | touch strip CC; 0xFF = none |
| 71 | 1 | vel_shift | 1..8, gain in front of the velocity curve and of pressure (smaller = more sensitive) |
| 72 | 1 | led_channel | channel on which note *n* lights LED *n* |
| 73 | 16 | pad_led | LED index of each pad (0xFF = none) |
| 89 | 1 | enc_mode | 0 relative offset (64 + step), 1 absolute, 2 relative (two's complement) |
| 90 | 1 | flags | bit 0: send strip_cc = 0 when the finger leaves the strip |
| 91 | 1 | sens | pad sensitivity 0..100 (applied at once when changed), 0xFF = keep the stored value |
| 92 | 1 | enc_init | start value of the absolute encoder |
| 93 | 2 | boot_ms | startup countdown in ms, 0xFFFF = stock (takes effect at the next power-up) |
| 95 | 1 | btn_mode | CC buttons: 0 gate, 1 toggle, 2 trigger |
| 96 | 48 | btn_act | what each button does: 0 CC, 1 note, 2 MIDI Start, 3 Continue, 4 Stop, 5 MMC, 6 none, and the controller's own functions (no MIDI of their own; they change how the pads play and show a message on the screen): 7 Pad Mode (Group: the configured pad notes), 8 Keyboard (chromatic from `keys_root`, pad 1 lowest, ascending left to right and bottom to top), 9 Fixed Vel (toggle), 10 16 Velocities (toggle: every pad plays pad 1's note, pad *n* at velocity 8 *n*), 11 velocity curve step (parameter 0 next, 1 previous), 12 transpose (parameter 64 + semitones), 13 panic (CC 120 and 123 on all 16 channels), 14 Shift (hold), and from phase 2: 15 scale step (parameter 0 next, 1 previous; from Group mode it switches to Keyboard), 16 Chords mode (a chord on each scale degree), 17 chord type step (0 next, 1 previous), 18 touch strip mode (parameter 0 the configured CC, 1 pitch bend that springs back to the centre, 2 mod wheel CC 1 that holds its value and shows it as a bar on the strip LEDs), 19 encoder target (parameter 0..2 = `enc_tgt_cc`; the encoder then sends absolute values from 64 and shows them; the same button again goes back), 20 Program Change (0 next, 1 previous, 2 back to program 0), and from phase 3: 21 tap tempo, 22 MIDI clock out (toggle; Start on switching on, Stop on switching off), 23 arp / Note Repeat (toggle), 24 arp pattern step (0 next, 1 previous), 25 arp rate step (0 next, 1 previous), 26 arp octaves (steps 1..4), 27 latch (toggle), 28 mute pads (toggle edit mode), 29 solo pads (toggle edit mode), 30 clear mutes and solos, 31 snapshot (0: store, then recall; 1: store again). Touch strip mode 3 (action 18, parameter 3) is **strum**; from generation 8: 32 MIDI channel step (0 next, 1 previous; kept across power cycles), 33 preset slot (0..3 load, 4..7 store, 8 load the next slot that holds a config: 1, 2, 3, 4, 1, empty ones skipped; **button 0, Project, is always 33 / 8, with its Shift action 6 / 0xFF (the same)**: the firmware overwrites whatever a SET, a slot or the saved record gives it, so GET returns that). A note (1) or MMC (5) button needs its number: `btn_cc` 0xFF (allowed for the other actions, "none") is refused for them, on both layers, at that byte, 34 step sequencer mode, 35 sequencer start / stop (parameter 0) or restart (1), 36 track select (hold), 37 pattern step (0 next, 1 previous), 38 clear (0 the track, 1 the pattern), 39 keep the patterns in flash; from generation 10: 40 pad page (0 next, 1 previous, 2 back to page 1: the drum pads move by 16 notes per page, 8 pages, the Keyboard layout does not move), 41 encoder page (0 next, 1 previous, 2 back to page 1, within `enc_pages`) |
| 144 | 1 | led_flags | bit 0 buttons rest dim, 1 buttons light while pressed, 2 pads rest in their colour, 3 pads flash when hit, 4 strip LED follows the finger |
| 145 | 1 | btn_led_idle | LED code of an assigned button at rest (0x7C) |
| 146 | 1 | btn_led_on | LED code while pressed / on (0x7F) |
| 147 | 1 | pad_colour | 1..17 (0 = white) |
| 148 | 1 | strip_colour | 1..17 (0 = white) |
| 149 | 1 | vel_curve | velocity curve 0..8: soft 3, soft 2, soft 1, linear, hard 1, hard 2, hard 3, fixed, custom (slot 8: the table given with `--vel-table`, else a copy of linear). A button set to *Velocity curve: step* changes it in RAM and keeps the choice (see "The settings log") |
| 150 | 1 | fixvel | 1..127, the velocity of every note while Fixed Vel is on |
| 151 | 1 | keys_root | note of pad 1 in Keyboard mode (60 = C3) |
| 152 | 1 | press_mode | pad pressure: 0 polyphonic aftertouch (on the sounding note), 1 channel pressure, 2 Control Change `press_cc`, 3 none. Modes 1 and 2 send 0 when the last pad lets go |
| 153 | 1 | press_cc | CC number for press_mode 2 |
| 154 | 48 | btn_act2 | the **shifted layer**: what each button does while a *Shift* button is held (6 = none: the button keeps its normal action) |
| 202 | 48 | btn_cc2 | parameter of the shifted action (0xFF = none) |
| 250 | 1 | scale | 0..23, the scale Keyboard and Chords mode start with (0 = chromatic, 1 major, 2 minor, ... `mmk3_config.SCALE_NAMES`; the masks are `build_patch.SCALES`) |
| 251 | 1 | chord_type | 0..7: triad, seventh, sus2, sus4, power (stacked from the scale on the pad's degree), minor, maj 9, maj 11 (fixed shapes in semitones on the pad's scale note: 0 3 7 / 0 4 7 11 14 / 0 4 7 11 14 17) |
| 252 | 3 | enc_tgt_cc | the CCs of the encoder targets 1..3 (default 7, 10, 11; 0xFF = none) |
| 255 | 1 | arp_type | 0..5: repeat (every held note at once, NI's Note Repeat), up, down, up-down, played, random |
| 256 | 1 | arp_rate | 0..6: 1/4, 1/8, 1/8T, 1/16, 1/16T, 1/32, 1/32T (24, 12, 8, 6, 4, 3, 2 clock pulses per step) |
| 257 | 1 | arp_oct | 1..4 octaves |
| 258 | 1 | tempo | the start tempo in BPM minus 20 (default 100 = 120 BPM); tap tempo changes it at run time only |
| 259 | 12 | btn_mode_ovr | a CC mode per button, 2 bits each (byte *k*>>2, bits (*k*&3)\*2): 0 = the global `btn_mode`, 1 gate, 2 toggle, 3 trigger. Only buttons whose action is *CC* use it (`mmk3_config.btn_mode_of` / `set_btn_mode`) |
| 271 | 1 | enc_pages | 1..8: pages of encoder targets (default 1) |
| 272 | 1 | enc_page_step | 1..32: on page *p* (from 0) target *t* sends `enc_tgt_cc[t] + enc_page_step × p`; a CC past 127 sends nothing (default 3) |
| 273 | 1 | enc_accel | 0 off, 1..3: a turn of *n* steps in one report moves *n* × (1 + accel × (*n* − 1)) steps, at most 40 (default 0) |

The firmware refuses a block that breaks any of the ranges in `mmk3_config.RANGES` (`cfg_check` in the C source applies the same rules; `test_config.py` compares the two on random blocks). The velocity curve tables (nine of 256 bytes), the display font and texts and the USB descriptors are not part of this block: they are fixed in the image. The run-time modes (Group / Keyboard / Chords, the scale and chord type in use, Fixed Vel, 16 Velocities, transpose, strip mode, encoder target, program number, the tempo, the arp and its list, mutes and solos, the snapshot, held Shift) are **not** part of it either: they start fresh at power-up and after every SET (a new config resets them).

## What a change does
- **Buttons, pads, encoder, strip, channel**: the next event uses the new values.
- **LEDs**: a new config rebuilds the LED state: every LED is commanded off, then the resting state of the new config is shown (host-set colours are dropped). Local LED behaviour follows `led_flags`.
- **Toggle state and the absolute encoder** restart (encoder at `enc_init`); so do the modes (Group, no transpose, Fixed Vel and 16 Velocities off, the scale and chord type of the config, strip and encoder on their configured CCs, program 0, the arp off with an empty list, the clock output off, mutes and solos cleared, the tempo of the config; whatever the arp or a strum has sounding is released by the main loop).
- **sens** is applied at once through the stock threshold routine when it changed. **boot_ms** is read at power-up.
- A note that is on (pad held) while the mapping changes is not released for the old note.

## The saved record
SAVE writes one record to the page at `0x0801EC00` (the last 1 KB page of the application area, below the stock settings pages, which are never touched): the page is erased only if it is not blank, then the data is programmed, then the header, **the magic last**.

| Offset | Size | |
|---|---|---|
| 0 | 4 | magic `MKCF` |
| 4 | 2 | version (1) |
| 6 | 2 | length of the config in bytes (274) |
| 8 | 2 | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) of the config bytes |
| 10 | 2 | 0xFFFF |
| 12 | 276 | the config, zero padded (the record is 288 bytes) |

At power-up the record is used only if magic, version, length (4..274) and CRC are right and the resulting block passes the range check; a shorter record (written by an older layout) only overlays the fields it has on the defaults. Anything else, including a half-written record, is ignored and the defaults are used (`test_config.py` cuts a save short at every flash write, also with half-programmed halfwords: the result is always the old config, the defaults or the new config, never anything else). **A save interrupted by a power loss loses the previous saved config** (the page is erased first), and the device then starts with the defaults.

## The settings log
The second half of the save page (offset `0x200`..`0x3FF`, 128 words) is an append-only log of changes made with the device's own buttons, so that they survive a power cycle **without a full save**. A word is `5A <kind> <value> <check>` (check = `5A ^ kind ^ value ^ FF`), programmed once into erased flash; there are two kinds, 1 = velocity curve and 2 = MIDI channel (changed with the buttons). At power-up the last valid word of that kind overrides `vel_curve` of the saved record (or of the defaults when nothing is saved); a word cut short by a power loss fails its check and is skipped, so a power cut during an append gives the old or the new curve and nothing else. An append is one word program (no erase). SAVE bakes the current curve into the record and clears the log (a SAVE does not take the shortcut "already saved" while the log holds anything), RESET with erase clears both, and a full log (128 changes) is cleared by saving the active config (or, when nothing is saved, by erasing the page). The log does not mark the config as unsaved. `test_modes.py` covers all of it, including the power-cut sweep.

The flash is written with the firmware's own ST library routines (unlock, page erase, word program, lock) from the main loop, never from an interrupt; the CPU stalls for the erase (about 20 to 40 ms). The watchdog timeout is about 1 s.

## Getting back to the defaults
`mmk3_config.py reset --erase` (SysEx `14 01`) erases the saved record. A saved config cannot keep the device from enumerating or from answering SysEx (descriptors and the protocol do not depend on it), so this always works while the device shows up as a MIDI port. Whether flashing the image again or running NI's updater erases that page is not known; the stock firmware ignores it.
