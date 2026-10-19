# 8. Command line

`tools/midi_patch/mmk3_config.py` does from a terminal what the setup page does in the browser. It talks to the controller over MIDI SysEx.

```bash
pip install mido python-rtmidi
python3 tools/midi_patch/mmk3_config.py info
```

## Commands
| Command | What it does |
|---|---|
| `info` | What the device reports: protocol version, whether a mapping is saved, unsaved changes, firmware version |
| `get [FILE.json]` | Print the active mapping as JSON, or save it to a file |
| `set FILE.json` | Make a mapping from a file active (not saved) |
| `button NAME ACTION [PARAM] [--shift]` | Change one button (with `--shift`: its Shift action). Actions: `cc N`, `note N`, `start`, `continue`, `stop`, `mmc N`, `none`, `padmode`, `keys`, `chords`, `fixvel`, `vel16`, `curve [next\|prev]`, `scale [next\|prev]`, `chordtype [next\|prev]`, `transpose ±N`, `panic`, `shift`, `strip 0..3`, `enctgt 0..2`, `program 0\|1\|2`, `tap`, `clockout`, `arp`, `arptype [next\|prev]`, `rate [next\|prev]`, `arpoct`, `latch`, `mute`, `solo`, `clear`, `snap 0\|1`, `channel [next\|prev]`, `slot 1..4\|store1..4\|next`, `step`, `seqrun`, `seqsel`, `seqpat`, `seqclear`, `seqsave`, `page [next\|prev\|first]`, `encpage [next\|prev\|first]` |
| `pad N NOTE` | Pad *N* (as printed, 1-16) plays note *NOTE* |
| `preset list [FILE]` | The built-in presets, and those in a preset file |
| `preset apply NAME [FILE] [--save]` | Make a preset active (by id or name), optionally save it as the power-up mapping |
| `slot list` | Which of the four slots hold a mapping, and their names |
| `slot store N [NAME]` | Store the active mapping in slot *N* under a name (shown on the screen when the slot is loaded) |
| `slot load N` | Make slot *N* active (not saved) |
| `save` | Keep the active mapping across power cycles |
| `reset [--erase]` | Back to the defaults; with `--erase` the saved mapping is erased as well |

Button names are those printed on the device (`Play`, `Fixed Vel`, `Note Repeat`, `Encoder Push`...). **Project** cannot be changed: it always
loads the next preset slot.

## Examples
```bash
mmk3_config.py preset apply maschine-modes --save          # the controller's own functions, kept at power-up
mmk3_config.py button Play cc 57                           # Play sends NI's CC 57 instead of MIDI Start
mmk3_config.py button Mute panic --shift                   # Shift + Mute = panic
mmk3_config.py pad 1 40                                    # pad 1 plays note 40
mmk3_config.py preset apply groove-rider-2                 # try a preset (unplug to go back)
mmk3_config.py slot store 2 "Groove Rider 2"               # ... and keep it in slot 2
mmk3_config.py get my-mapping.json                         # back up the active mapping
```

Changes are active at once and stay until the controller is unplugged; `save` keeps them.
