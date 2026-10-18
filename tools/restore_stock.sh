#!/bin/sh
# Puts NI's ORIGINAL firmware (1.20) back on the Mikro MK3 with our own DFU client, without NI's updater (which macOS is about to stop
# supporting). It flashes only the exact image whose SHA-256 is known, from the copy saved in proprietary/ unless you name another file.
#
#   tools/restore_stock.sh [image.bin] [python with pyusb]
#
# What happens is the same as for any flash (flasher/flash_guarded.sh: refuses while another program has the device open, waits for the device
# to come back). Afterwards the device is the stock HID device again (bcdDevice 0x0052); to get the MIDI firmware back run
# flasher/flash_guarded.sh with the patched image. Any device in the stock bootloader mode (17cc:1702) can be restored the same way.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="${1:-$HERE/../proprietary/MM3_firmware_1.20_stock.bin}"; PY="${2:-python3}"
FLASH="${FLASH_GUARDED:-$HERE/../flasher/flash_guarded.sh}"
WANT=76ebf72d33961639a0bd042ba32354dd8dc07569be69175546eb9fc06e5c5917
[ -f "$IMG" ] || { echo "no firmware image at $IMG (carve it with tools/carve_fw.py from NI's updater)"; exit 2; }
SUM=$(shasum -a 256 "$IMG" | cut -d' ' -f1)
if [ "$SUM" != "$WANT" ]; then
  echo "$IMG is not NI's firmware 1.20 for the Mikro MK3 (sha256 $SUM, expected $WANT): refusing to flash it"; exit 2
fi
echo "image: NI's original firmware 1.20, $(wc -c < "$IMG" | tr -d ' ') bytes, sha256 ${SUM%????????????????????????????????????????????????}..."
exec "$FLASH" "$IMG" "$PY"
