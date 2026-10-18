#!/bin/sh
# Guarded flash of a Maschine Mikro MK3 image with tools/dfu_client.py (macOS).
# Refuses to write while any program other than the OS has the device open (a browser with WebUSB access, NI's updater or
# agents, ...): such a program could grab the bootloader mid-flash. The client itself waits for the device to come back and
# exits 0 only if it is back in normal mode.
#
#   tools/flash_guarded.sh <image.bin> [python with pyusb]      # libusb from Homebrew is expected in /opt/homebrew/lib
#
# Restore path if anything goes wrong: NI's updater (proprietary/MM3_FWUpdater_120_Mac.zip, run by you, not by this script).
set -u
IMG="${1:-}"; PY="${2:-python3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$IMG" ] || { echo "usage: $0 <image.bin> [python]"; exit 2; }
# MIDIServer (macOS CoreMIDI) always holds a class-compliant MIDI device and copes with it resetting, so it is not counted.
CLIENTS=$(ioreg -r -c IOUSBHostDevice -n "Maschine Mikro MK3" -l -w0 2>/dev/null | grep -o '"IOUserClientCreator" = "[^"]*"' | grep -v ', MIDIServer"' | sort | uniq -c)
if [ -n "$CLIENTS" ]; then
  echo "something else has the device open, NOT flashing:"; echo "$CLIENTS"; exit 3
fi
echo "device is free; image $IMG ($(wc -c < "$IMG" | tr -d ' ') bytes, sha256 $(shasum -a 256 "$IMG" | cut -c1-16)...)"
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib "$PY" "$HERE/dfu_client.py" flash "$IMG" --yes-flash
status=$?
echo "client exit status: $status"
exit $status
