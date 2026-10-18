#!/usr/bin/env python3
"""The patched firmware in the emulator behind a line protocol, so that node can run the real JavaScript client against it.

    emu_bridge.py <patched.bin> <data_init.bin>

One JSON object per line on stdin, one JSON object per line on stdout:
    {"op": "sysex", "hex": "f07d4d4b10f7"}              -> {"replies": ["f07d4d4b50...f7", ...]}   (the SysEx the device answered)
    {"op": "report1", "pressed": [3], "pos": 0}          -> {"packets": [[9, 144, 36, 100], ...]}   (what a HID report 1 makes it send)
    {"op": "report2", "events": [[12, 1, 3000]]}         -> {"packets": [...]}
    {"op": "page"}                                       -> {"hex": "..."}                             (the 1 KB save page)
    {"op": "reboot"}                                     -> {"ok": true}                               (power cycle: the flash stays)
    {"op": "violations"}                                 -> {"violations": [...]}                      (flash accesses outside the save page)"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'midi_patch'))
import devsim

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
dev = devsim.Dev(fw, data)
violations = []
for line in sys.stdin:
    if not line.strip(): continue
    req = json.loads(line); op = req['op']
    if op == 'sysex': resp = {'replies': [m.hex() for m in dev.ask(bytes.fromhex(req['hex']))]}
    elif op == 'report1': resp = {'packets': [list(p) for p in dev.translate(devsim.report1(req.get('pressed', []), pos=req.get('pos', 0)))]}
    elif op == 'report2': resp = {'packets': [list(p) for p in dev.translate(devsim.report2([tuple(e) for e in req['events']]))]}
    elif op == 'page': resp = {'hex': dev.page().hex()}
    elif op == 'reboot':
        violations += dev.flash.violations
        dev = devsim.Dev(fw, data, flash=dev.flash_image()); resp = {'ok': True}
    elif op == 'violations': resp = {'violations': violations + dev.flash.violations}
    else: resp = {'error': 'unknown op'}
    sys.stdout.write(json.dumps(resp) + '\n'); sys.stdout.flush()
