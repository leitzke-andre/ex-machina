#!/bin/sh
# The flasher's own tests: no hardware, no firmware images.   flasher/run_tests.sh [python]
set -e; set -o pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; PY="${1:-${PYTHON:-python3}}"
echo "== test_dfu_client (the Python client against a mock DFU device)"; "$PY" "$HERE/test_dfu_client.py" | tail -3
echo "== test_usb_guard (finding the device and who has it open, on synthetic registry data)"; "$PY" "$HERE/test_usb_guard.py" | tail -2
if command -v node >/dev/null 2>&1; then echo "== test_dfu.mjs (the WebUSB port against a mock DFU device)"; node "$HERE/test_dfu.mjs" | tail -3
else echo "== node not found: test_dfu.mjs skipped"; fi
