# 2. Playing

The button names below are those of the **Maschine-like modes** preset (chapter 3), which puts each function on the button NI prints it on.
Any function can be put on any button with the setup page (chapter 6).

## The pads
The pads are numbered as printed on the device: **pad 1 is bottom left**, pad 16 top right.

```
 13  14  15  16
  9  10  11  12
  5   6   7   8
  1   2   3   4
```

- A hit sends **Note On** with the velocity of the hit, letting go sends **Note Off**. A slow press that never counts as a hit still plays a quiet note.
- While a pad is held, pressing harder sends **pressure**. Options (setup page, *Pads > Playing*): polyphonic aftertouch on the pad's note (default),
  channel pressure, a Control Change, or off.
- The pads light while hit and rest in their colour (blue by default; 17 colours on the *LEDs* tab).

### Pad modes
| Button | Mode | What the pads play | Screen |
|---|---|---|---|
| **Pad Mode** | Drums | The pad notes of the mapping (default 36-51, the General MIDI kit) | `DRUMS` |
| **Keyboard** | Keyboard | The current scale from the root note (C3 = 60): pad 1 is the root, each pad the next note of the scale, rows continue upwards | `KEYBOARD` with the range, e.g. `C3-D#4` |
| **Chords** | Chords | Pad *k* plays the chord built on the *k*-th note of the scale | `CHORDS` |

The mode button stays lit while its mode is on. A note always ends with the note it started with, even if you change mode, scale or transposition while holding a pad.

### Scales and chords
- **Shift + Keyboard** / **Shift + Pad Mode**: next / previous scale (from Drums mode this switches to Keyboard). 24 scales: chromatic, major, minor,
  harmonic minor, melodic minor, dorian, phrygian, lydian, mixolydian, locrian, major and minor pentatonic, blues, whole tone, both diminished scales,
  hungarian minor, phrygian dominant, double harmonic, hirajoshi, in-sen, major blues, bebop dominant, neapolitan minor.
- **Shift + Chords** / **Shift + Select**: next / previous chord type. On the chromatic scale, chords are built on the major scale.

  | Type | Built | Pad 1 / pad 2 in C major |
  |---|---|---|
  | triad | from the scale: notes 1, 3, 5 of the scale from the pad's note | C E G / D F A |
  | seventh | from the scale: 1, 3, 5, 7 | C E G B / D F A C |
  | sus2 | from the scale: 1, 2, 5 | C D G / D E A |
  | sus4 | from the scale: 1, 4, 5 | C F G / D G A |
  | power | from the scale: 1, 5 | C G / D A |
  | minor | fixed shape: root, minor third, fifth | C Eb G / D F A |
  | maj 9 | fixed shape: 1 3 5 7 9 with the major seventh | C E G B D / D F# A C# E |
  | maj 11 | fixed shape: 1 3 5 7 9 11 | C E G B D F / D F# A C# E G |

  The first five follow the scale, so their quality changes from pad to pad (a major scale gives major and minor chords). The fixed shapes play
  the same chord quality on every pad, starting from the pad's scale note.

### Velocity
- **Fixed Vel**: every note at one velocity (127 unless set otherwise). Screen: `FIXED VEL / ON 127`.
- **Shift + Fixed Vel** = **16 Velocities**: all pads play the same note (pad 1's), pad *n* at velocity 8 × *n*, from soft (pad 1) to 127 (pad 16).
- **Shift + Volume** / **Shift + Swing**: next / previous **velocity curve**: soft 3, soft 2, soft 1, linear (default, NI's default), hard 1, hard 2,
  hard 3, fixed, and a custom slot. The choice is **kept when the controller is unplugged**.

### Transpose
- **Left / Right**: down / up a semitone. **Shift + Left / Right**: an octave. Applies to every pad mode; at most 63 semitones either way, notes stay within 0-127.

## The touch strip
| Button | Strip mode | What it sends |
|---|---|---|
| **Perform** | Configured CC (default) | CC 1 (or the CC of the mapping), 0-127 along the strip |
| **Pitch** | Pitch bend | The whole strip is the bend range; springs back to the centre when you let go |
| **Mod** | Mod wheel | CC 1, **keeps its value** when you let go; the value shows as a dim bar on the strip LEDs |
| **Notes** | Strum | The strip is divided among the notes of the pads you hold (or the 16 pad notes); sliding plays them one by one |

## The encoder
- Turning sends **CC 7**, absolute 0-127, starting at 0 (other CCs and the relative modes are on the setup page). Pushing sends CC 8, touching CC 9.
- **Volume / Swing / Tempo** point the encoder at one of three **targets**: CC 7, CC 10 and CC 11 by default. Each target keeps its own value,
  starting at 64, shown on the screen as `CC 7 / VALUE 65` with a bar. Pressing the same button again returns the encoder to normal.
- **Encoder pages** (setup page, *Encoder & strip*): the three targets can have up to 8 pages of CCs, stepped with a button set to *Encoder page*;
  **acceleration** makes a fast turn take bigger steps.

## Shift
Hold **Shift** and press a button to get its second function (the right-hand column in chapter 3). The choice is made when the button goes down,
so releasing Shift first never leaves a note or CC stuck.

## Program Change, MIDI channel, panic
- **Favorites** / **Browser**: next / previous **Program Change**; **Shift + Browser**: back to program 0. Screen: `PROGRAM / PC 1`.
- **Group** / **Shift + Group**: next / previous **MIDI channel** 1-16. Notes held on the old channel are released first. The channel is **kept when
  the controller is unplugged**.
- **Shift + Mute** = **panic**: All Sound Off and All Notes Off on all 16 channels.

## The screen
- **Idle**: `EX-MACHINA`, the version (`V0`) and a status line, `DRUMS CH1 120`: the pad mode, the MIDI channel and the tempo, plus `ARP`, `CLK`
  or `SEQ` while the arp, the clock output or the sequencer runs.
- **Notes**: while notes sound, the middle line shows their names, lowest first (middle C = C3): a pad, every note of a chord, several pads, and
  what the arp, the sequencer and the strum play. More than five show as the first four and `+n`. They stay half a second after the last note.
- **Messages**: every change shows a message for 1.5 seconds: a large title and a detail line, sometimes a bar (`KEYBOARD / C3-D#4`,
  `VELOCITY / HARD 1`, `CHANNEL / 3`, `SLOT 2 / GROOVE RIDER 2`...).
- **Step mode**: the screen shows the sequencer grid instead (chapter 4).

## What the device remembers
| Kept when unplugged | Starts fresh at every power-up |
|---|---|
| The saved mapping (*Save on device*), the four slots, the velocity curve choice, the MIDI channel, the sequencer patterns once kept (*Shift + Restart*) | Pad mode, scale and chord type of the moment, transpose, Fixed Vel, encoder targets, strip mode, arp, latch, mute / solo, tempo |
