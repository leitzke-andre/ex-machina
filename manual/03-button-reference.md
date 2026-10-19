# 3. Button reference

Two mappings come with every install: **Default** (plain MIDI: every button sends a Control Change on NI's own numbers) and **Maschine-like modes**
(the controller's own functions on the buttons NI prints them on). The table lists both; *Shift +* is what the button does while **Shift** is held
(empty = the same as without Shift). The groups are those of the setup page's *Buttons* tab.

Buttons that send a CC send 127 when pressed and 0 when released (*gate*; *toggle* and *trigger* are options, per button or for all). **Project**
is the same in every mapping: it loads the next preset slot (chapter 5).

### Transport
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Play | MIDI Start | MIDI Start | |
| Rec | CC 58 | CC 58 | |
| Stop | MIDI Stop | MIDI Stop | |

### Pad modes
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Fixed Vel | CC 80 | Fixed Vel on / off | 16 Velocities on / off |
| Pad Mode | CC 81 | Drums (the pad notes) | previous scale |
| Keyboard | CC 82 | Keyboard mode | next scale |
| Chords | CC 84 | Chords mode | next chord type |
| Step | CC 83 | Step sequencer mode | sequencer start / stop |

### Scenes and patterns
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Group | CC 34 | next MIDI channel | previous MIDI channel |
| Scene | CC 85 | CC 85 | |
| Pattern | CC 86 | CC 86 | |
| Events | CC 87 | CC 87 | |
| Variation | CC 88 | CC 88 | |

### Edit
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Duplicate | CC 89 | CC 89 | |
| Select | CC 90 | sequencer: hold + a pad selects the track | previous chord type |
| Solo | CC 91 | solo pads (edit mode) | clear mutes and solos |
| Mute | CC 92 | mute pads (edit mode) | **panic** (all notes off) |
| Restart | CC 53 | sequencer back to step 1 | keep the sequencer patterns in the device |
| Erase | CC 54 | sequencer: clear the track | sequencer: clear the pattern |
| Tap | CC 55 | tap tempo | MIDI clock out on / off |
| Follow | CC 56 | next arp pattern | previous arp pattern |

### Pages
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Volume | CC 44 | encoder drives target 1 (CC 7) | next velocity curve |
| Swing | CC 46 | encoder drives target 2 (CC 10) | previous velocity curve |
| Tempo | CC 48 | encoder drives target 3 (CC 11) | |
| Plug-in | CC 45 | sequencer: next pattern | |
| Sampling | CC 47 | sequencer: previous pattern | |
| Pitch | CC 49 | strip: pitch bend | |
| Mod | CC 50 | strip: mod wheel | |
| Perform | CC 51 | strip: the configured CC | |
| Notes | CC 52 | strip: strum | |

### Navigation
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Left | CC 41 | transpose −1 | transpose −12 |
| Right | CC 42 | transpose +1 | transpose +12 |
| Shift | CC 43 | Shift | |
| **Project** | **next preset slot** | **next preset slot** | (the same) |
| Favorites | CC 39 | next program | |
| Browser | CC 40 | previous program | program 0 |

### Performance
| Button | Default | Maschine-like modes | Shift + |
|---|---|---|---|
| Auto | CC 35 | arp octaves (1-4) | previous arp rate |
| Lock | CC 36 | arp latch on / off | snapshot: store, then recall |
| Note Repeat | CC 37 | arp / Note Repeat on / off | next arp rate |

### Encoder
| Control | Default | Maschine-like modes |
|---|---|---|
| Turn | CC 7, absolute 0-127 | CC 7, or the target chosen with Volume / Swing / Tempo |
| Push | CC 8 | CC 8 |
| Touch | CC 9 | CC 9 |

### Special gesture
**Shift + Stop + Erase held for 2 seconds** shows `DFU MODE` and restarts the controller into its bootloader, ready to be flashed (chapter 7).
It works in every mapping.
