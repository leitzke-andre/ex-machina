# 4. Rhythm: tempo, arp, sequencer

Everything here runs on one clock inside the controller: 24 pulses per beat, from the internal tempo or from an incoming MIDI clock.
The buttons are those of the **Maschine-like modes** preset (chapter 3).

## Tempo
- **Tap**: tap three or more times; the tempo is the average of the last three taps (20-275 BPM). A pause of more than 2 seconds starts a new count.
  While the clock runs, Tap blinks on the beat. The status line shows the tempo (`DRUMS CH1 120`).
- The tempo at power-up is 120 BPM, or the start tempo set on the setup page (*Pads > Playing*).
- **External clock**: when an app sends MIDI clock to the controller, the arp and the sequencer follow it (the screen says `EXT CLOCK` on Tap). Start
  restarts them from the beginning, Stop ends the arp's note. Without clock for 0.4 s the internal tempo takes over again.

## MIDI clock out
**Shift + Tap** switches the clock output on and off: MIDI Start, then clock pulses at the current tempo, and MIDI Stop when switched off. It is off
by default so the controller never fights another clock master. While it runs the status line shows `CLK`.

## Arpeggiator and Note Repeat
- **Note Repeat** switches the arp on and off. While it is on, the pads you hold are played in turn instead of all at once, at the arp rate.
- **Follow** / **Shift + Follow**: next / previous **pattern**:

  | Pattern | Plays |
  |---|---|
  | repeat | all held notes together on every step (NI's Note Repeat) |
  | up / down | lowest to highest / highest to lowest |
  | up-down | up then down, the ends not repeated |
  | played | in the order the pads were pressed |
  | random | a random held note on each step |

- **Shift + Note Repeat** / **Shift + Auto**: next / previous **rate**: 1/4, 1/8, 1/8T, 1/16 (default), 1/16T, 1/32, 1/32T.
- **Auto**: **octaves**, 1 to 4: the pattern repeats that many octaves up.
- **Lock**: **latch**: the notes keep playing after you let go, until you press new pads with nothing held.
- The arp works in every pad mode: a chord pad arpeggiates its chord. Muted pads are skipped. The first note sounds at once; with a clock already
  running it waits for the next step.

## Mute and solo pads
- **Mute**: an edit mode; while it is on, hitting a pad mutes or unmutes it instead of playing. Muted pads are dark and silent.
- **Solo**: the same for solo; while any pad is soloed the others are silent. Soloed pads rest brighter.
- **Shift + Solo** clears all mutes and solos. Muting a pad also silences its track in the sequencer and in the arp.

## Strum
**Notes** puts the touch strip in strum mode: the strip is divided among the notes of the pads you hold (lowest on the left), or among the 16 pad
notes when none is held. Sliding plays each note as you cross it, at velocity 100; lifting the finger ends the note.

## Snapshot
**Shift + Lock** stores the current values of the three encoder targets, the mod wheel and the encoder. The next **Shift + Lock** sends them all
back as CCs, so the app's controls jump back to where they were.

## The step sequencer
A 16-step drum sequencer with 16 tracks (one per pad note of the drum layout) and 4 patterns.

| Action | Button |
|---|---|
| Enter / leave step mode | **Step** |
| Start / stop | **Shift + Step** |
| Back to step 1 | **Restart** |
| Choose the track | hold **Select** and hit a pad (track *n* = pad *n*'s note) |
| Edit steps | hit pad *n* to cycle step *n*: off → on → accent → off |
| Next / previous pattern | **Plug-in** / **Sampling** |
| Clear the track / the pattern | **Erase** / **Shift + Erase** |
| Keep the patterns in the device | **Shift + Restart** |

- In step mode the pad LEDs show the selected track: dim = off, colour = on, bright = accent, white = the playhead.
- The screen shows the **grid** of the track (a small bar for off, a tall bar for on, a taller one for accent), the playhead, the beat marks and a
  top line such as `TRK 1 C1 PAT 1 RUN`.
- Steps are 1/16 notes on the same clock as the arp (internal tempo, tap tempo or external clock). On notes play at velocity 100, accents at 127.
- Patterns are in memory until you keep them with **Shift + Restart**; kept patterns come back at the next power-up.
