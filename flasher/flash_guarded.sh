#!/bin/sh
# Guarded flash of an image with dfu_client.py (macOS), for the device named in DFU_DEVICE_NAME (default: Maschine Mikro MK3).
# Refuses to write while any program other than the OS has the device open (a browser with WebUSB access, NI's updater or
# agents, ...): such a program could grab the bootloader mid-flash. The client itself waits for the device to come back and
# exits 0 only if it is back in normal mode.
#
#   flasher/flash_guarded.sh <image.bin> [python with pyusb]      # libusb from Homebrew is expected in /opt/homebrew/lib
#   other dfu_client.py options (ids, flash area) can be passed in DFU_CLIENT_ARGS, other ids for the check in DFU_GUARD_ARGS (--vid / --pid)
#
# Restore path if anything goes wrong: the vendor's own updater, run by you, not by this script (for the Mikro MK3: see README.md).
set -u
IMG="${1:-}"; PY="${2:-python3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
[ -f "$IMG" ] || { echo "usage: $0 <image.bin> [python]"; exit 2; }
# The device is found by its ids (normal mode or bootloader), not its name, and one that cannot be found stops the flash (usb_guard.py).
# MIDIServer (macOS CoreMIDI) always holds a class-compliant MIDI device and copes with it resetting, so it is not counted.
"$PY" "$HERE/usb_guard.py" ${DFU_GUARD_ARGS:-} || exit $?
echo "device is free; image $IMG ($(wc -c < "$IMG" | tr -d ' ') bytes, sha256 $(shasum -a 256 "$IMG" | cut -c1-16)...)"
DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:/usr/local/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}" "$PY" "$HERE/dfu_client.py" flash "$IMG" --yes-flash ${DFU_CLIENT_ARGS:-}
status=$?
echo "client exit status: $status"
exit $status
