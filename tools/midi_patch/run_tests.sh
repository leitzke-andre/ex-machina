#!/bin/sh
# Build the patched image from the stock firmware and run every emulator test.
# Usage: run_tests.sh <stock fw.bin (0x9dc8 bytes)> [workdir]
# Needs: clang with the ARM target, python venv with `unicorn pyelftools usb-protocol` installed.
set -e
STOCK="$1"; WORK="${2:-$(mktemp -d)}"; mkdir -p "$WORK"; HERE="$(cd "$(dirname "$0")" && pwd)"; PY="${PYTHON:-python3}"
"$PY" "$HERE/../decompress_data.py" "$STOCK" "$WORK/data_init.bin"
"$PY" "$HERE/build_patch.py" "$STOCK" "$WORK/patched.bin"
"$PY" "$HERE/build_patch.py" "$STOCK" "$WORK/stage1.bin" --stage 1
"$PY" "$HERE/build_patch.py" "$STOCK" "$WORK/stage2.bin" --stage 2
for t in test_translate test_patch test_features test_modes test_phase2 test_display_race test_config test_mmk3_config test_enumeration test_pad_pipeline test_real_pads test_real_controls stack_depth; do
  echo "== $t"; "$PY" "$HERE/$t.py" "$WORK/patched.bin" "$WORK/data_init.bin" | tail -3
done
echo "== test_led_race (random interleavings of an LED burst with the stock main loop)"
"$PY" "$HERE/test_led_race.py" "$WORK/patched.bin" "$WORK/data_init.bin" 150 | tail -3
echo "== test_startup (the real stage-2 init and main loop through the stock startup animation, patched vs stock)"
"$PY" "$HERE/test_startup.py" "$WORK/patched.bin" "$STOCK" "$WORK/data_init.bin" | tail -3
echo "== test_vel_curve (build options: --vel-curve, --vel-table, --vel-shift, stages)"
"$PY" "$HERE/test_vel_curve.py" "$STOCK" "$WORK/data_init.bin" "$WORK/vc" | tail -3
echo "== test_flash_model (the flash model against the stock flash routines)"
"$PY" "$HERE/../emu/test_flash_model.py" "$WORK/patched.bin" | tail -2
echo "== test_restore_stock (tools/restore_stock.sh hands only NI's exact firmware to the flash script)"
"$PY" "$HERE/../test_restore_stock.py" "$STOCK" | tail -2
UI="$HERE/../ui"
if command -v node >/dev/null 2>&1; then
  echo "== browser UI: generated tables, vectors and patch bundle are up to date"
  "$PY" "$UI/gen_data.py" --check; "$PY" "$UI/make_vectors.py" --check; "$PY" "$UI/make_bundle.py" --check "$STOCK" "$WORK/patched.bin"
  echo "== browser UI: protocol layer (vectors, and the JS client against the firmware in the emulator)"
  node "$UI/test_mmk3.mjs" "$PY" "$WORK/patched.bin" "$WORK/data_init.bin" | tail -3
  echo "== browser UI: presets (words, differences, the store, files)"
  node "$UI/test_presets.mjs" | tail -3
  echo "== browser UI: every module parses as an ES module (a duplicate name would stop the page from loading)"
  for f in app mmk3 presets dfu patch mock mmk3_data; do node --input-type=module --check < "$UI/$f.js" || { echo "FAIL: $f.js does not parse as a module"; exit 1; }; done; echo "ALL PASS"
  echo "== browser UI: image building and the DFU port"
  node "$UI/test_flash.mjs" "$STOCK" "$WORK/patched.bin" | tail -3
else echo "== node not found: the browser UI tests are skipped"; fi
echo "== enumerate_stock (model baseline on the unpatched image, and on the stage-1/2 images)"
for f in "$STOCK" "$WORK/stage1.bin" "$WORK/stage2.bin"; do "$PY" "$HERE/../emu/enumerate_stock.py" "$f" "$WORK/data_init.bin" | tail -1; done
echo "work files in $WORK (contain NI code: keep local)"
