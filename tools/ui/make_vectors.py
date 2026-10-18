#!/usr/bin/env python3
"""Writes vectors.json: inputs and the outputs of the Python host library (tools/midi_patch/mmk3_config.py), which test_mmk3.mjs
checks the JavaScript implementation (mmk3.js) against.

    make_vectors.py [--check]"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'midi_patch'))
import mmk3_config as mc

def render():
    rng = random.Random(20261018)
    D = mc.default_cfg()
    v = {'defaults': {k: mc.default_cfg(**kw).hex() for k, kw in {
            'default': {}, 'transport_cc': {'transport': 'cc'}, 'transport_mmc': {'transport': 'mmc'}, 'pads_ni': {'pad_base': 12}, 'leds_off': {'local_leds': False}}.items()}}
    v['pack7'] = [{'data': b.hex(), 'packed': mc.pack7(b).hex()} for b in
                  [bytes(rng.randrange(256) for _ in range(n)) for n in list(range(0, 24)) + [149, 152, 250, 252, 255, 256, 259, 260, 273, 274, 275]] + [D]]
    v['crc'] = [{'data': b.hex(), 'crc': mc.crc16(b)} for b in (b'', b'123456789', D, bytes(range(256)))]
    v['requests'] = {'info': mc.info_request().hex(), 'get': mc.get_request().hex(), 'save': mc.save_request().hex(), 'reset': mc.reset_request().hex(),
                     'reset_erase': mc.reset_request(True).hex(), 'set_default': mc.set_request(D).hex(),
                     'slot_store': mc.slot_store_request(2).hex(), 'slot_store_named': mc.slot_store_request(1, 'BeatMaker 3 (draft)').hex(), 'display_names': [mc.display_name(n) for n in ('BeatMaker 3 (draft)', 'a{b', 'x' * 40, '  Spaced  ')], 'preset_display_names': [mc.preset_display_name(p) for p in ({'name': 'BeatMaker 3 (draft)'}, {'name': 'Maschine-like modes'}, {'name': 'Mine', 'display_name': 'my drums'}, {'name': 'x' * 56})], 'slot_load': mc.slot_load_request(3).hex(), 'slots': mc.slots_request().hex(),
                     'peek': mc.peek_request(0x1FFFF7E0, 16).hex(), 'peek_flash': mc.peek_request(0x0800CD20, 64).hex()}
    replies = [bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x50, 2, 122, 1, 5, 0xF7]), bytes([0x7D, 0x4D, 0x4B, 0x52, 2, 100, 1]), bytes([0x7D, 0x4D, 0x4B, 0x53, 3]),
               bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x52, 0, 0xF7]), bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x54, 0, 0xF7]), bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x51]) + mc.pack7(D) + bytes([0xF7])]
    replies.append(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x5E, 0]) + bytes((0x1FFFF7E0 >> (28 - 7 * i)) & 0x7F for i in range(5)) + mc.pack7(bytes(range(16))) + bytes([0xF7]))
    replies.append(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x5E, 1, 0, 0, 0, 0, 0, 0xF7]))
    replies += [bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x57, 0, 0b1010, 0xF7]), bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x56, 4, 0xF7]), bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x55, 0, 0xF7]),
                bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x50, 2, 3, 2, 5, 0, 0xF7])]
    out = []
    for r in replies:
        p = mc.parse_reply(r); out.append({'hex': r.hex(), 'parsed': {k: (x.hex() if isinstance(x, bytes) else x) for k, x in p.items()}})
    v['replies'] = out
    cases = []
    def mut(name, i, val):
        c = bytearray(D); c[mc.FIELDS[name][0] + i] = val; return bytes(c)
    for name, vals in (('channel', (15, 16)), ('pad_note', (127, 128)), ('btn_cc', (127, 128, 255)), ('btn_act', (mc.ACT_LAST, mc.ACT_LAST + 1)), ('enc_cc', (255, 128)), ('strip_cc', (200,)),
                       ('vel_shift', (0, 1, 8, 9)), ('led_channel', (16,)), ('pad_led', (79, 80, 255)), ('enc_mode', (2, 3)), ('flags', (1, 2)), ('sens', (100, 101, 255)),
                       ('enc_init', (127, 128)), ('btn_mode', (2, 3)), ('led_flags', (31, 32)), ('btn_led_idle', (127, 128)), ('btn_led_on', (200,)),
                       ('pad_colour', (17, 18)), ('strip_colour', (18,)), ('vel_curve', (8, 9)), ('fixvel', (0, 1, 127, 128)), ('keys_root', (127, 128)),
                       ('press_mode', (3, 4)), ('press_cc', (127, 128)), ('btn_act2', (mc.ACT_LAST, mc.ACT_LAST + 1)), ('btn_cc2', (127, 128, 255)), ('scale', (23, 24)), ('chord_type', (4, 5)), ('enc_tgt_cc', (127, 128, 255)), ('arp_type', (5, 6)), ('arp_rate', (6, 7)), ('arp_oct', (0, 1, 4, 5))):
        for val in vals: cases.append(mut(name, 3 if mc.FIELDS[name][1] > 3 else 0, val))
    cases.append(b'XMK3' + D[4:]); cases.append(D[:100]); cases.append(D + b'\0')
    for _ in range(150):
        c = bytearray(D)
        for _ in range(rng.choice((1, 1, 2, 3))):
            off = rng.randrange(4, mc.CFG_SIZE)
            c[off] = rng.choice((rng.randrange(256), 0xFF, 0, 127, 128, rng.randrange(20)))
        cases.append(bytes(c))
    v['check'] = [{'cfg': c.hex(), 'offset': mc.check(c)} for c in cases]
    v['records'] = [{'cfg': c.hex(), 'record': mc.build_record(c).hex()} for c in (D, mc.default_cfg(transport='cc'), mut('channel', 0, 5))]
    page = mc.build_record(D); bad = bytearray(page); bad[20] ^= 1
    v['parse_record'] = [{'page': page.hex(), 'cfg': D.hex()}, {'page': bytes(bad).hex(), 'cfg': None}, {'page': (b'\xff' * 288).hex(), 'cfg': None}]
    v['dict'] = {'cfg': mut('channel', 0, 3).hex(), 'dict': mc.to_dict(mut('channel', 0, 3))}
    custom = {'name': 'Custom A', 'description': 'for the tests', 'cfg': mut('channel', 0, 3)}
    v['preset_file'] = {'text': mc.preset_file(mc.builtin_presets() + [custom]), 'custom_cfg': custom['cfg'].hex(), 'builtin_ids': [p['id'] for p in mc.builtin_presets()]}
    return json.dumps(v, indent=0) + '\n'

if __name__ == '__main__':
    path = os.path.join(HERE, 'vectors.json'); text = render()
    if '--check' in sys.argv:
        ok = os.path.exists(path) and open(path).read() == text
        print('vectors.json is up to date' if ok else 'vectors.json is out of date: run tools/ui/make_vectors.py'); sys.exit(0 if ok else 1)
    open(path, 'w').write(text); print('written', path, len(text), 'bytes')
