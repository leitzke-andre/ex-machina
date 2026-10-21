#!/bin/sh
# Copies the Ex-Machina FL Studio script into FL Studio's user folder for hardware scripts. Writes nothing else.
# Usage: install.sh [TARGET]   TARGET defaults to the macOS location:
#   ~/Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina
# On Windows (Git Bash / WSL), pass the folder: "<Documents>/Image-Line/FL Studio/Settings/Hardware/Ex-Machina"
# (the user data folder can be moved in FL Studio: Options > File settings > User data folder).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Documents/Image-Line/FL Studio/Settings/Hardware/Ex-Machina}"
case "$(basename "$DEST")" in Ex-Machina) ;; *) echo "the target folder must be called Ex-Machina: $DEST"; exit 1;; esac
PARENT="$(dirname "$DEST")"
if [ ! -d "$PARENT" ]; then echo "no FL Studio hardware folder at $PARENT (is FL Studio installed? pass the folder as an argument)"; exit 1; fi
mkdir -p "$DEST"
for f in "$HERE"/Ex-Machina/*.py; do cp "$f" "$DEST/"; done
echo "installed into $DEST:"; ls "$DEST"
echo "In FL Studio: Options > MIDI Settings > the Mikro's input > Controller type \"Ex-Machina (Maschine Mikro MK3)\";"
echo "give the input and the Mikro's output the same Port number. On the device: Shift + Project switches to FL Studio mode (an older firmware: load the preset 'FL Studio')."
