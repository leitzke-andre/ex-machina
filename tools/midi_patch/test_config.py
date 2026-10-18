"""The run-time configuration of the patch in the emulator: the SysEx protocol (INFO / GET / SET / SAVE / RESET), the range check
(differentially against the host library's), the reply path through the stock TX ring, the saved record in flash, loading it at boot,
corrupt and older records, and a save that is cut short at every point. The flash routines are the firmware's own (ST's library)
running against tools/emu/flash_model.py, which fails the test on any erase or program outside the one save page.

Usage: test_config.py <patched.bin> <data_init.bin>"""
import os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import devsim
from devsim import report1, report2, CC
import build_patch as bp
import mmk3_config as mc
sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
from flash_model import PAGE, image_after

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

def Dev(cfg=None, flash=None): return devsim.Dev(fw, data, cfg, flash)
DEFAULTS = bytes(mc.default_cfg())
def reply(d, msg, **kw):
    r = d.ask(msg, **kw)
    return mc.parse_reply(r[0]) if len(r) == 1 else r
def edit(cfg, **fields): return mc.from_dict(fields, base=cfg)
F = mc.FIELDS
SAVE_OFS = bp.SAVE_PAGE - 0x08000000

# ---- the image carries the defaults the host library knows ----
check('the config block in the image is the host library\'s default_cfg()', fw[bp.CFG_ADDR - 0x08003000:][:mc.CFG_SIZE], DEFAULTS)

# ---- INFO / GET ----
d = Dev()
check('INFO: protocol 2, 259-byte config, nothing saved, no changes', reply(d, mc.info_request()),
      {'cmd': 0x10, 'protocol': 2, 'cfg_size': 259, 'saved': False, 'unsaved_changes': False, 'loaded_from_flash': False, 'version': 0})
raw = d.ask(mc.get_request())
check('GET: one SysEx reply F0 7D 4D 4B 51 <296 packed bytes> F7, all data bytes below 0x80', (len(raw), len(raw[0]), raw[0][:5].hex(), all(b < 0x80 for b in raw[0][1:-1])),
      (1, 302, 'f07d4d4b51', True))
check('GET returns the active config, here the defaults', mc.parse_reply(raw[0])['cfg'], DEFAULTS)

# ---- SET: valid ----
new = edit(DEFAULTS, channel=2, pad_note=[40 + i for i in range(16)], enc_cc=70, strip_cc=71)
new = bytearray(new); new[F['btn_cc'][0] + 3] = 20; new[F['btn_act'][0] + 4] = mc.ACT_NOTE; new[F['btn_cc'][0] + 4] = 60; new = bytes(new)
r = reply(d, mc.set_request(new))
check('SET with a valid config: status 0', r, {'cmd': 0x12, 'status': 0, 'status_text': 'ok'})
check('... GET shows it', mc.parse_reply(d.ask(mc.get_request())[0])['cfg'], new)
d.translate(report1())
check('... Volume (button 3) now sends CC 20 on channel 3 (no restart needed)', d.translate(report1([3])), [CC(20, 127, 2)])
check('... button 4 sends a note (60)', (d.translate(report1()), d.translate(report1([4]))), ([CC(20, 0, 2)], [(0x09, 0x92, 60, 127)]))
d.translate(report1())
hit = d.translate(report2([(12, 1, 3000)]))
check('... pad 1 (report index 12) plays its new note (pad_note[12] = 52) on channel 3', hit[0][:3], (0x09, 0x92, 52))
r = reply(d, mc.info_request())
check('INFO afterwards: changes not saved', (r['saved'], r['unsaved_changes']), (False, True))

# ---- SET: every rule of the range check, differentially against the host library ----
base = DEFAULTS
bad_cases = []
def mutate(name, i, v):
    c = bytearray(base); c[F[name][0] + i] = v; return bytes(c)
for name, vals in (('channel', (16, 255)), ('pad_note', (128, 200)), ('btn_cc', (128, 254)), ('btn_act', (mc.ACT_LAST + 1, 255)), ('enc_cc', (128, 254)),
                   ('strip_cc', (128, 200)), ('vel_shift', (0, 9, 255)), ('led_channel', (16,)), ('pad_led', (80, 100, 254)), ('enc_mode', (3,)),
                   ('flags', (2,)), ('sens', (101, 200)), ('enc_init', (128,)), ('btn_mode', (3,)), ('led_flags', (32, 255)), ('btn_led_idle', (128,)),
                   ('btn_led_on', (200,)), ('pad_colour', (18, 255)), ('strip_colour', (18,)), ('vel_curve', (9, 255)), ('fixvel', (0, 128)),
                   ('keys_root', (128,)), ('press_mode', (4,)), ('press_cc', (128,)), ('scale', (24, 255)), ('chord_type', (5,)), ('enc_tgt_cc', (128, 254)), ('arp_type', (6, 255)), ('arp_rate', (7,)), ('arp_oct', (0, 5)), ('btn_act2', (mc.ACT_LAST + 1, 255)), ('btn_cc2', (128, 254))):
    for v in vals: bad_cases.append((f'{name}={v}', mutate(name, 5 if F[name][1] > 5 else 0, v)))
bad_cases.append(('magic', b'XMK3' + base[4:]))
d = Dev(); before = mc.parse_reply(d.ask(mc.get_request())[0])['cfg']
wrong = []
for label, cfg in bad_cases:
    r = reply(d, mc.set_request(cfg)); want = mc.check(cfg)
    if not (r.get('status') == 2 and r.get('offset') == want): wrong.append((label, r, want))
check(f'SET with a bad value is refused with status 2 and the right offset, for each of the {len(bad_cases)} rule cases', wrong, [])
check('... and the active config did not change', mc.parse_reply(d.ask(mc.get_request())[0])['cfg'], before)
for label, cfg in (('btn_cc 0xFF', mutate('btn_cc', 3, 0xFF)), ('pad_led 0xFF', mutate('pad_led', 3, 0xFF)), ('sens 0xFF', mutate('sens', 0, 0xFF)),
                   ('enc_cc 0xFF', mutate('enc_cc', 0, 0xFF)), ('btn_cc2 0xFF', mutate('btn_cc2', 3, 0xFF)), ('btn_act2 last action', mutate('btn_act2', 3, mc.ACT_LAST)), ('fixvel 1', mutate('fixvel', 0, 1)), ('vel_curve 8', mutate('vel_curve', 0, 8)), ('sens 100', mutate('sens', 0, 100)), ('pad_led 79', mutate('pad_led', 0, 79))):
    r = reply(d, mc.set_request(cfg))
    if r.get('status') != 0: wrong.append((label, r))
check('the allowed edge values (0xFF for "none", sens 100, pad_led 79) are accepted', wrong, [])

rng = random.Random(20261018)
disagree = []
for n in range(120):
    c = bytearray(DEFAULTS)
    for _ in range(rng.choice((1, 1, 2, 3))):
        off = rng.randrange(4, mc.CFG_SIZE)
        if off in (93, 94): continue
        c[off] = rng.choice((rng.randrange(256), 0xFF, 0, 127, 128, rng.randrange(20)))
    r = reply(d, mc.set_request(bytes(c))); want = mc.check(bytes(c))
    if (want is None) != (r.get('status') == 0) or (want is not None and r.get('offset') != want): disagree.append((c.hex(), r, want))
check('120 random single / multi byte mutations: the device and the host library agree on accept / refuse and on the offset', disagree, [])

# ---- SET: wrong length, busy, startup ----
d = Dev()
short = mc.message(mc.CMD_SET, mc.pack7(DEFAULTS[:100]))
longer = mc.message(mc.CMD_SET, mc.pack7(DEFAULTS + b'\0\0\0'))
check('SET with too few / too many bytes: status 1', (reply(d, short)['status'], reply(d, longer)['status'], reply(d, mc.message(mc.CMD_SET))['status']), (1, 1, 1))
d.send_sysex(mc.info_request()); d.send_sysex(mc.get_request())            # two requests before the main loop gets a turn
d.all_sent.clear()
for _ in range(8): d.tick(0)
got = devsim.sysex_messages(d.all_sent)
check('a second request while one is pending is ignored (the host asks again): only the INFO reply comes', [m[4] for m in got], [0x50])
d = Dev(); d.send_sysex(mc.info_request()); d.all_sent.clear(); d.tick(3000)
check('requests are served during the stock startup too (countdown still running)', [m[4] for m in devsim.sysex_messages(d.all_sent)], [0x50])
d = Dev()
check('foreign and malformed SysEx are ignored', (d.ask(bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x1F, 0xF7])), d.ask(bytes([0xF0, 0x41, 0x10, 0xF7])), d.ask(bytes([0xF0, 0x7D, 0x4D, 0xF7]))), ([], [], []))

# ---- the reply goes through the stock ring only as far as it has room ----
RING_W, RING_R = devsim.RING_W, devsim.RING_R
d = Dev(); d.send_sysex(mc.get_request())
d.mu.mem_write(RING_W, struct.pack('<H', 100)); d.mu.mem_write(RING_R, struct.pack('<H', 120))     # 19 bytes free: room for 4 packets
d.all_sent.clear(); d.tick(0)
check('a nearly full ring takes whole packets only (here 4 = 16 bytes of the 60), never a split one', [len(b) for b in d.all_sent], [16])
d.tick(0)
check('... and nothing more while the ring stays full', [len(b) for b in d.all_sent], [16])
d.mu.mem_write(RING_R, struct.pack('<H', 100))                                  # the sender drained it
for _ in range(12): d.tick(0)
msgs = devsim.sysex_messages(d.all_sent)
check('... the rest follows once there is room, and the message is intact', (len(msgs), mc.parse_reply(msgs[0])['cfg'] if msgs else None), (1, DEFAULTS))
check('every chunk handed to the ring was a multiple of 4 bytes and at most 64', all(len(b) % 4 == 0 and len(b) <= 64 for b in d.all_sent), True, [len(b) for b in d.all_sent])

# ---- RESET ----
d = Dev(); reply(d, mc.set_request(new))
r = reply(d, mc.reset_request())
check('RESET: status 0, the defaults are active again', (r['status'], mc.parse_reply(d.ask(mc.get_request())[0])['cfg']), (0, DEFAULTS))
check('... nothing was saved, so no unsaved changes', {k: reply(d, mc.info_request())[k] for k in ('saved', 'unsaved_changes')}, {'saved': False, 'unsaved_changes': False})

# ---- SAVE ----
d = Dev(); initial = d.flash_image()
reply(d, mc.set_request(new))
r = reply(d, mc.save_request())
rec = mc.build_record(new)
check('SAVE: status 0', r['status'], 0)
check('the page holds exactly the record the host library builds (272 bytes, CRC-16, magic)', d.page()[:mc.REC_SIZE], rec)
check('the rest of the page is still erased', d.page()[mc.REC_SIZE:], b'\xff' * (PAGE - mc.REC_SIZE))
check('a blank page needs no erase; the record is 136 halfword programs inside the save page; no violations',
      (d.flash.erases, len(d.flash.programs), d.flash.violations, all(bp.SAVE_PAGE <= a < bp.SAVE_PAGE + PAGE for a, _ in d.flash.programs)), ([], 136, [], True))
check('the magic is programmed last (the two final halfwords are at the start of the page)', [a for a, _ in d.flash.programs[-2:]], [bp.SAVE_PAGE, bp.SAVE_PAGE + 2])
check('nothing but the save page changed in the flash', d.flash_image()[:SAVE_OFS] + d.flash_image()[SAVE_OFS + PAGE:] == initial[:SAVE_OFS] + initial[SAVE_OFS + PAGE:], True)
r = reply(d, mc.info_request())
check('INFO afterwards: saved, no unsaved changes', (r['saved'], r['unsaved_changes']), (True, False))
n = len(d.flash.log)
reply(d, mc.save_request())
check('saving the same config again touches nothing (no erase, no wear)', len(d.flash.log), n)
new2 = edit(new, channel=5, enc_cc=9)
reply(d, mc.set_request(new2)); r = reply(d, mc.save_request())
check('saving a different config erases the page once and writes the new record', (r['status'], d.flash.erases, d.page()[:mc.REC_SIZE] == mc.build_record(new2), d.flash.violations),
      (0, [bp.SAVE_PAGE], True, []))

# ---- reboot: the saved config is loaded ----
d2 = Dev(flash=d.flash_image())
r = reply(d2, mc.info_request())
check('after a restart the saved config is loaded: INFO says saved and loaded from flash', (r['saved'], r['unsaved_changes'], r['loaded_from_flash']), (True, False, True))
check('... GET returns it', mc.parse_reply(d2.ask(mc.get_request())[0])['cfg'], new2)
d2.translate(report1())
check('... and it is in use at once (no tick needed): Volume still sends CC 20, on channel 6 now', d2.translate(report1([3])), [CC(20, 127, 5)])

# ---- SAVE of the defaults erases the page ----
d3 = Dev(flash=d.flash_image())
reply(d3, mc.reset_request()); r = reply(d3, mc.save_request())
check('SAVE while the defaults are active leaves a blank page and "nothing saved"', (r['status'], d3.page(), reply(d3, mc.info_request())['saved']), (0, b'\xff' * PAGE, False))
d4 = Dev(flash=d.flash_image()); reply(d4, mc.reset_request(erase=True))
check('RESET with the erase argument removes the saved record', (d4.page(), reply(d4, mc.info_request())['saved'], d4.flash.violations), (b'\xff' * PAGE, False, []))
d5 = Dev(flash=d.flash_image()); reply(d5, mc.reset_request())
r = reply(d5, mc.info_request())
check('RESET without it keeps the record (only the RAM copy changes): saved, with unsaved changes; the next boot loads the record again',
      (r['saved'], r['unsaved_changes'], Dev(flash=d5.flash_image()).cfg()), (True, True, new2))

# ---- records that must not be loaded ----
def booted(page):
    flash = bytearray(d.flash_image()); flash[SAVE_OFS:SAVE_OFS + PAGE] = b'\xff' * PAGE; flash[SAVE_OFS:SAVE_OFS + len(page)] = page
    dd = Dev(flash=bytes(flash)); return dd.cfg(), reply(dd, mc.info_request())
good = mc.build_record(new2)
def flip(rec, i): b = bytearray(rec); b[i] ^= 1; return bytes(b)
for label, page in (('bad magic', flip(good, 0)), ('wrong version', flip(good, 4)), ('length 3 (too short)', good[:6] + struct.pack('<H', 3) + good[8:]),
                    ('length 150 (too long)', good[:6] + struct.pack('<H', 150) + good[8:]), ('a flipped data bit (CRC)', flip(good, 20)),
                    ('a half-written record (data, no magic)', b'\xff\xff\xff\xff' + good[4:])):
    cfg, info = booted(page)
    check(f'a record with {label} is not loaded: defaults, "nothing saved"', (cfg, info['saved'], info['loaded_from_flash']), (DEFAULTS, False, False))
badval = bytearray(new2); badval[F['channel'][0]] = 16
cfg, info = booted(mc.build_record(bytes(badval)))
check('a record with a correct CRC but a value out of range is not loaded either', (cfg, info['saved']), (DEFAULTS, False))
d6 = Dev(flash=d.flash_image()); d6.flash_log_before = len(d6.flash.log)
junk = bytearray(d.flash_image()); junk[SAVE_OFS:SAVE_OFS + PAGE] = bytes(range(256)) * 4
d7 = Dev(flash=bytes(junk)); reply(d7, mc.set_request(new)); r = reply(d7, mc.save_request())
check('a page full of junk is erased and rewritten by SAVE', (r['status'], d7.page()[:mc.REC_SIZE] == mc.build_record(new), d7.flash.erases, d7.flash.violations), (0, True, [bp.SAVE_PAGE], []))

# ---- an older, shorter record only overlays the fields it has ----
old_cfg = bytearray(DEFAULTS); old_cfg[F['btn_cc'][0]] = 99; old_cfg[F['btn_cc'][0] + 40] = 98       # byte 61: beyond the first 100 bytes
page = struct.pack('<IHHHH', mc.REC_MAGIC, mc.REC_VERSION, 100, mc.crc16(bytes(old_cfg[:100])), 0xFFFF) + bytes(old_cfg[:100]) + bytes(52)
cfg, info = booted(page)
want = bytearray(DEFAULTS); want[:100] = old_cfg[:100]
check('a record of 100 bytes overlays the first 100 bytes of the defaults (fields added later keep their defaults)', (cfg, info['saved']), (bytes(want), True))
check('the host library agrees (parse_record)', mc.parse_record(page), bytes(want))

# ---- a save that is cut short at every point never leaves anything but the old config, the defaults, or the new config ----
d = Dev(); reply(d, mc.set_request(new)); reply(d, mc.save_request())
before = d.flash_image()
reply(d, mc.set_request(new2)); n0 = len(d.flash.log); reply(d, mc.save_request())
log = d.flash.log[n0:]
erase_at = [i for i, e in enumerate(log) if e[0] == 'erase']
check('a save over a saved record is one erase followed by 136 programs', (len(erase_at), len(log)), (1, 137))
seen = {}
bad = []
for cut in range(len(log) + 1):
    for mask in ((None,) if cut == len(log) else (None, 0x00FF, 0xFF00)):
        img = image_after(before, log, cut, mask)
        flash = bytearray(before); flash[:] = img
        got = Dev(flash=bytes(flash)).cfg()
        kind = 'old' if got == new else 'defaults' if got == DEFAULTS else 'new' if got == new2 else 'garbage'
        seen[kind] = seen.get(kind, 0) + 1
        if kind == 'garbage': bad.append((cut, mask))
        # before the erase the old record; an erase cut short may or may not have damaged it; after it nothing until the magic is in; then the new record
        want = {'old'} if cut < erase_at[0] or (cut == erase_at[0] and mask is None) else {'old', 'defaults'} if cut == erase_at[0] else {'new'} if cut == len(log) else {'defaults'}
        if kind not in want: bad.append((cut, mask, kind, sorted(want)))
check(f'power cut at each of the {len(log) + 1} points of a save (and with half-programmed halfwords): old config, then defaults, then the new config - never garbage',
      (bad, sorted(seen)), ([], ['defaults', 'new', 'old']))

# ---- activating a config rebuilds the LEDs and applies the sensitivity ----
d = Dev(); d.start(); d.consume()
cfg = bytearray(DEFAULTS); cfg[F['btn_cc'][0] + 3] = 0xFF; cfg[F['pad_colour'][0]] = 5
reply(d, mc.set_request(bytes(cfg)))
led = d.led()
check('SET rebuilds the LEDs: the button that lost its CC goes dark (an explicit 0, not "skip"), the others rest dim, the pads take the new colour, all flagged',
      (led[3], led[4], led[39], d.flag()), (0, 0x7C, 5 * 4 + 1, 1))
check('... and LEDs that were never part of the resting state are commanded off too (strip, unused)', (set(led[55:80]), set(led[0:3])), ({0}, {0x7C}))
n = d.threshold_calls
reply(d, mc.set_request(edit(DEFAULTS, sens=50)))
check('a changed sensitivity runs the stock threshold routine once and stores the value', (d.threshold_calls - n, d.mu.mem_read(devsim.STRUCT + 0x5e1, 1)[0]), (1, 50))
reply(d, mc.set_request(edit(DEFAULTS, sens=50)))
reply(d, mc.set_request(edit(DEFAULTS, sens=0xFF)))
check('... not again for the same value, nor for 0xFF (keep)', d.threshold_calls - n, 1)
d = Dev(); d.translate(report1(enc=0))
reply(d, mc.set_request(edit(DEFAULTS, enc_init=40)))
check('SET restarts the absolute encoder at its new start value (a click gives 41)', d.translate(report1(enc=1)), [CC(7, 41)])
d = Dev(cfg=edit(DEFAULTS, btn_mode=1)); d.translate(report1()); d.translate(report1([3])); d.translate(report1())
reply(d, mc.set_request(edit(DEFAULTS, btn_mode=1)))
check('SET clears the toggle state of the buttons (the next press is "on" again)', d.translate(report1([3])), [CC(44, 127)])

# ---- a second request arriving (USB interrupt) while the first is being handled by the main loop ----
# While the first is being handled the second must be dropped (it would overwrite the staged config under the validation); once the first is
# complete the second is a normal request and is handled after it. Never a mix, never two replies for one config.
other = edit(DEFAULTS, channel=9, enc_cc=11)
dropped, queued, wrong = 0, 0, []
for after in range(1, 30000, 211):
    d = Dev(); d.send_sysex(mc.set_request(new))                        # request A is stored, the tick has not run yet
    d.all_sent.clear()
    if not d.tick_interrupted(after, lambda sp: d.send_sysex(mc.set_request(other), sp=sp)): break     # the tick finished before `after`: swept it all
    for _ in range(6): d.tick(0)
    replies = [mc.parse_reply(m)['status'] for m in devsim.sysex_messages(d.all_sent)]
    active = d.cfg()
    if active == new and replies == [0]: dropped += 1
    elif active == other and replies == [0, 0]: queued += 1
    else: wrong.append((after, active == new, active == other, replies))
check(f'a SET arriving in the interrupt at {dropped + queued} different points of the handling of another: dropped while it is busy ({dropped}), handled after it otherwise ({queued}); never a mix',
      (wrong, dropped > 20, queued > 0), ([], True, True))

# ---- PEEK: the read-only diagnostic ----
d = Dev(); d.start()
def peek(addr, n):
    r = d.ask(mc.peek_request(addr, n)); return mc.parse_reply(r[0]) if len(r) == 1 else r
r = peek(bp.CODE_ADDR, 64)
check('PEEK flash: 64 bytes of our own code, address echoed', (r['status'], r['addr'], r['data']), (0, bp.CODE_ADDR, bytes(d.mu.mem_read(bp.CODE_ADDR, 64))))
r = peek(0x20001C18, 40)
check('PEEK RAM', (r['status'], r['data']), (0, bytes(d.mu.mem_read(0x20001C18, 40))))
r = peek(0x1FFFF7E0, 16)
check('PEEK the system memory: flash size 128 KB and the unique ID', (r['status'], int.from_bytes(r['data'][:2], 'little'), r['data'][8:12]), (0, 128, bytes([0xA0, 0xA1, 0xA2, 0xA3])))
check('PEEK the FLASH registers as whole words (36 bytes) and the chip ID',
      (peek(0x40022000, 36)['status'], peek(0xE0042000, 4)['status'], peek(0xE000ED00, 4)['status']), (0, 0, 0))
check('PEEK 1 byte at the end of RAM, and the last 2 bytes of the flash', (peek(0x20004FFF, 1)['status'], peek(0x0801FFFE, 2)['status']), (0, 0))
for what, addr, n in (('address 0', 0, 4), ('the first byte after the flash', 0x08020000, 4), ('a range crossing the end of the flash', 0x0801FFFF, 2), ('a range crossing the end of RAM', 0x20004FFF, 2),
                      ('a peripheral that is not whitelisted (USB registers)', 0x40005C00, 4), ('a register read that is not word aligned', 0x40022001, 4), ('a register read of 3 bytes', 0x40022000, 3), ('an address that would wrap around', 0xFFFFFFF0, 64), ('the stack pointer register area', 0xE000ED08, 4)):
    check(f'PEEK refuses {what} (status 1)', peek(addr, n)['status'], 1)
check('PEEK refuses length 0 and 65 (status 2) and a malformed request (status 2)',
      (peek(0x20000000, 0)['status'], peek(0x20000000, 65)['status'], mc.parse_reply(d.ask(mc.message(mc.CMD_PEEK, bytes([0, 0, 0, 0, 0])))[0])['status']), (2, 2, 2))
check('PEEK changed nothing: the config is still the defaults and nothing was flashed', (d.cfg(), d.flash.log, d.flash.violations), (DEFAULTS, [], []))

# ---- the flash model saw nothing wrong anywhere in this test ----
# (violations are checked per save above; this covers the devices built on the way)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
