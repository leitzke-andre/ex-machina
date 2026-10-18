"""The host library (mmk3_config.py): the pure functions, and the whole client and command line against the emulated firmware through a
fake `mido` that hands every SysEx to the emulated device and returns its replies.

Usage: test_mmk3_config.py <patched.bin> <data_init.bin>"""
import contextlib, io, json, os, random, struct, sys, types
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import devsim
import mmk3_config as mc

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

# ---- pure functions ----
rng = random.Random(7)
rt = all(mc.unpack7(mc.pack7(b)) == b for b in (bytes(rng.randrange(256) for _ in range(n)) for n in list(range(0, 40)) + [149, 152, 250, 252, 255]))
check('pack7 / unpack7 round-trip for lengths 0..39, 149, 152, 250, 252, 255 with all byte values', rt)
check('pack7: 7 data bytes behind one byte of their high bits; the config packs to 296 bytes, every byte below 0x80',
      (mc.pack7(bytes([0x80, 0, 0x81, 0, 0, 0, 0xFF])), len(mc.pack7(mc.default_cfg())), max(mc.pack7(bytes(range(256))))),
      (bytes([0b1000101, 0, 0, 1, 0, 0, 0, 0x7F]), 296, 0x7F))
check('crc16 is CRC-16/CCITT-FALSE (check value 0x29B1 for "123456789")', mc.crc16(b'123456789'), 0x29B1)
D = mc.default_cfg()
check('default_cfg is 259 bytes and valid', (len(D), mc.check(D)), (259, None))
variants = [mc.default_cfg(transport=t, local_leds=l, pad_base=b, enc_mode=e, btn_mode=m, vel_shift=v, pad_colour=c, sens=s)
            for t in ('realtime', 'cc', 'mmc') for l in (False, True) for b in (12, 36) for e in (0, 1, 2) for m in (0, 1, 2)
            for v in (1, 5, 8) for c in (0, 5, 17) for s in (0xFF, 80)]
check(f'all {len(variants)} variants build_patch can produce are valid configs', [i for i, c in enumerate(variants) if mc.check(c) is not None], [])
check('to_dict / from_dict round-trip, JSON-serialisable', mc.from_dict(json.loads(json.dumps(mc.to_dict(D)))), D)
d = mc.to_dict(D)
check('to_dict has raw values: channel 0, boot_ms 0xFFFF, 48 btn_cc, 16 pad_note', (d['channel'], d['boot_ms'], len(d['btn_cc']), len(d['pad_note'])), (0, 0xFFFF, 48, 16))
check('from_dict changes only what it is given', mc.from_dict({'channel': 4}, base=D)[4], 4)
try: mc.from_dict({'pad_note': [1, 2]}); raised = False
except ValueError: raised = True
check('from_dict refuses an array of the wrong length', raised)
rec = mc.build_record(D)
check('record: 272 bytes, magic "MKCF", version 1, length 259', (len(rec), rec[:4], struct.unpack_from('<HH', rec, 4)), (272, b'MKCF', (1, 259)))
check('parse_record(build_record(c)) == c, and a flipped bit anywhere in the data is refused', (mc.parse_record(rec), mc.parse_record(rec[:20] + bytes([rec[20] ^ 4]) + rec[21:])), (D, None))
check('parse_record refuses a blank page', mc.parse_record(b'\xff' * 272), None)
check('parse_reply: INFO, SET refused with offset, SAVE ok',
      (mc.parse_reply(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x50, 2, 122, 1, 5, 0xF7])), mc.parse_reply(bytes([0x7D, 0x4D, 0x4B, 0x52, 2, 100, 1])), mc.parse_reply(bytes([0x7D, 0x4D, 0x4B, 0x53, 3]))),
      ({'cmd': 16, 'protocol': 2, 'cfg_size': 250, 'saved': True, 'unsaved_changes': False, 'loaded_from_flash': True, 'version': None},
       {'cmd': 18, 'status': 2, 'status_text': 'value out of range', 'offset': 228}, {'cmd': 19, 'status': 3, 'status_text': 'flash error'}))
try: mc.parse_reply(bytes([0xF0, 0x41, 1, 2, 0xF7])); raised = False
except mc.ProtocolError: raised = True
check('parse_reply refuses other devices\' SysEx', raised)

# ---- presets ----
bp = mc.builtin_presets()
check('the built-in presets: "default" is the default configuration, valid', (bp[0]['id'], bp[0]['name'], bp[0]['cfg'] == D, mc.check(bp[0]['cfg'])), ('default', 'Default', True, None))
custom = {'name': 'Custom A', 'description': 'for the tests', 'cfg': bytes(D[:4]) + bytes([3]) + bytes(D[5:])}
text = mc.preset_file([custom])
back = mc.read_preset_file(text)
check('every built-in preset is valid, has a unique id and name, and survives a preset file round trip', all(mc.check(p['cfg']) is None for p in bp) and len({p['id'] for p in bp}) == len(bp) == len({p['name'] for p in bp})
      and [q['cfg'] for q in mc.read_preset_file(mc.preset_file(bp))] == [p['cfg'] for p in bp])
check('preset_file / read_preset_file round trip (name, description, bytes)', [(p['name'], p['description'], p['cfg']) for p in back] == [('Custom A', 'for the tests', custom['cfg'])])
j = json.loads(text); j['presets'][0]['cfg'] = j['presets'][0]['cfg'][:200]
old = mc.read_preset_file(json.dumps(j))[0]['cfg']
check('a shorter config (an older tool) is laid over the defaults', old[:100] == custom['cfg'][:100] and old[100:] == D[100:] and len(old) == 259)
bad_cases = {'a wrong format': {'format': 'x', 'presets': []}, 'a value out of range': {'format': mc.PRESET_FILE_FORMAT, 'presets': [{'name': 'x', 'cfg': (D[:4] + bytes([40]) + D[5:]).hex()}]},
             'a config that is too long': {'format': mc.PRESET_FILE_FORMAT, 'presets': [{'name': 'x', 'cfg': D.hex() + '00'}]}}
for what, doc in bad_cases.items():
    try: mc.read_preset_file(json.dumps(doc)); raised = False
    except ValueError: raised = True
    check(f'read_preset_file refuses {what}', raised)
check('find_preset: by id and by name, case-insensitive; unknown names raise KeyError', mc.find_preset('DEFAULT')['name'] == 'Default' and mc.find_preset('default')['id'] == 'default')
try: mc.find_preset('nope'); raised = False
except KeyError: raised = True
check('... unknown preset raises KeyError', raised)

# ---- the client and the command line against the emulated firmware ----
dev = devsim.Dev(fw, data)
class Port:
    def __init__(self): self.queue = []
    def iter_pending(self):
        q, self.queue = self.queue, []
        return iter(q)
    def send(self, m):
        for r in dev.ask(bytes([0xF0]) + bytes(m.data) + bytes([0xF7])): self.queue.append(types.SimpleNamespace(type='sysex', data=r[1:-1]))
fake = types.ModuleType('mido')
fake.get_input_names = lambda: ['Maschine Mikro MK3']; fake.get_output_names = lambda: ['Maschine Mikro MK3']
fake.Message = lambda type, data=(): types.SimpleNamespace(type=type, data=tuple(data))
shared = Port()                        # one object for both directions: what the output sends, the device answers into the input queue
fake.open_input = lambda name: shared; fake.open_output = lambda name: shared
sys.modules['mido'] = fake

def cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): rc = mc.main(list(argv))
    return rc, buf.getvalue().strip()

rc, out = cli('info')
check('mmk3_config info: protocol 2, 259 bytes, nothing saved', (rc, json.loads(out)['protocol'], json.loads(out)['cfg_size'], json.loads(out)['saved']), (0, 2, 259, False))
rc, out = cli('get')
check('mmk3_config get prints the active config as JSON, equal to the defaults', mc.from_dict(json.loads(out)), D)
rc, out = cli('button', 'Play', 'cc', '57')
check('mmk3_config button Play cc 57: accepted', (json.loads(out)['status'], dev.cfg()[mc.FIELDS['btn_act'][0] + 22], dev.cfg()[mc.FIELDS['btn_cc'][0] + 22]), (0, mc.ACT_CC, 57))
rc, out = cli('button', 'stop', 'mmc', '1')
check('mmk3_config button stop mmc 1 (names are case-insensitive)', (dev.cfg()[mc.FIELDS['btn_act'][0] + 24], dev.cfg()[mc.FIELDS['btn_cc'][0] + 24]), (mc.ACT_MMC, 1))
rc, out = cli('button', '25', 'none')
check('mmk3_config button 25 none (a number works as well as a name)', dev.cfg()[mc.FIELDS['btn_act'][0] + 25], mc.ACT_NONE)
rc, out = cli('pad', '1', '40')
check('mmk3_config pad 1 40 changes the note of the pad printed 1 (report index 12)', dev.cfg()[mc.FIELDS['pad_note'][0] + 12], 40)
check('the change is live: pad 1 plays 40', dev.translate(devsim.report2([(12, 1, 3000)]))[0][:3], (0x09, 0x90, 40))
cfg_file = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'mmk3_test_cfg.json')
pf = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'mmk3_test_presets.json'); open(pf, 'w').write(mc.preset_file([custom]))
rc, out = cli('preset', 'list', pf)
check('mmk3_config preset list names the built-in and the file\'s presets', 'default' in out and 'Custom A' in out and 'for the tests' in out, True, out)
rc, out = cli('preset', 'apply', 'Custom A', pf)
check('mmk3_config preset apply "Custom A" FILE: sent, and live', (json.loads(out)['status'], dev.cfg()), (0, custom['cfg']))
rc, out = cli('preset', 'apply', 'default')
check('mmk3_config preset apply default: back to the defaults', (json.loads(out)['status'], dev.cfg()), (0, D))
rc, out = cli('preset', 'apply', 'custom a', pf, '--save')
check('mmk3_config preset apply ... --save keeps it (the saved record holds the preset)', mc.parse_record(dev.page()) == custom['cfg'], True, rc)
cli('reset', '--erase')
try: cli('preset', 'apply', 'nope'); raised = False
except SystemExit as e: raised = 'no preset' in str(e)
check('an unknown preset name is refused with a hint', raised)
os.remove(pf)
cli('get', cfg_file)
saved_json = json.load(open(cfg_file))
saved_json['channel'] = 9
json.dump(saved_json, open(cfg_file, 'w'))
rc, out = cli('set', cfg_file)
check('mmk3_config get FILE / set FILE round trip (channel 10)', (json.loads(out)['status'], dev.cfg()[mc.FIELDS['channel'][0]]), (0, 9))
rc, out = cli('save')
check('mmk3_config save writes the record', (json.loads(out)['status'], mc.parse_record(dev.page())[mc.FIELDS['channel'][0]]), (0, 9))
rc, out = cli('reset', '--erase')
check('mmk3_config reset --erase: defaults again, the page blank', (json.loads(out)['status'], dev.cfg(), dev.page()), (0, D, b'\xff' * 1024))
try: cli('button', 'Nope', 'cc', '1'); raised = False
except SystemExit as e: raised = 'unknown button' in str(e)
check('an unknown button name is refused with the list of names', raised)
check('no flash violations in all of this', dev.flash.violations, [])
os.remove(cfg_file)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
