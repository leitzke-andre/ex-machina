"""Replays REAL pad reports of a stock Maschine Mikro MK3 (fixtures/stock_pad_capture.txt, recorded with tools/hid_capture.py)
through the patched translator in the emulator and checks what comes out.
Usage: test_real_pads.py <patched.bin> <data_init.bin> [capture log]   (the default log is the small fixture in the repo; a
longer recording of your own works too)"""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import hid_capture as H
import build_patch as bp
from replay import Replay
log = sys.argv[3] if len(sys.argv) > 3 else os.path.join(HERE, 'fixtures', 'stock_pad_capture.txt')
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'))

R = Replay(sys.argv[1], sys.argv[2])
translate = R.translate
NOTE = list(R.fw[bp.CFG_ADDR - 0x08003000 + 5:][:16])      # cfg.pad_note[HID pad index] of the image under test
BASE = NOTE[12]                                            # printed pad 1 = report index 12
assert NOTE == [BASE - 1 + n for n in H.PAD_LABEL], NOTE   # the default layout: pad n = base + n - 1

rows = H.read_log(log)
ev, msgs, per_read = [], [], []                  # pad events (pad, type, value) and MIDI messages (status, note, data2), in order
for ms, buf in rows:
    evs = [(p, t, v) for kind, body in H.parse(buf) if kind == 'r2' for p, t, v in body]
    out = [(q[1], q[2], q[3]) for q in translate(buf)]
    per_read.append((evs, out)); ev += evs; msgs += out
trig = [(p, t, v) for p, t, v in ev if t in (0, 1)]
rel = [(p, t, v) for p, t, v in ev if t in (2, 3)]
ons = [m for m in msgs if m[0] & 0xF0 == 0x90]; offs = [m for m in msgs if m[0] & 0xF0 == 0x80]; pres = [m for m in msgs if m[0] & 0xF0 == 0xA0]
print(f'{os.path.basename(log)}: {len(rows)} reads, {len(trig)} triggers ({sum(1 for _, t, _ in trig if t == 0)} press-on), {len(rel)} releases, '
      f'{sum(1 for _, t, _ in ev if t == 4)} aftertouch events -> {len(ons)} Note On, {len(offs)} Note Off, {len(pres)} poly pressure')

check('the recording is not trivially small: 10+ triggers, a slow press (press-on), a 4095 hit, the lowest value 416',
      len(trig) >= 10 and any(t == 0 for _, t, _ in trig) and any(v == 4095 for _, t, v in trig if t == 1) and any(v == 416 for _, t, v in trig if t == 1)
      or log != os.path.join(HERE, 'fixtures', 'stock_pad_capture.txt'))
check('one Note On per trigger event (note-on or press-on)', len(ons), len(trig))
check('one Note Off per release event (note-off or press-off)', len(offs), len(rel))
held, retrig, stray = set(), 0, 0
for st, note, d2 in msgs:
    if st & 0xF0 == 0x90:
        retrig += note in held; held.add(note)
    elif st & 0xF0 == 0x80:
        stray += note not in held; held.discard(note)
check('no note is still on at the end (no stuck notes)', sorted(held), [])
check('no Note On while the same note is still on (no double triggers)', retrig, 0)
check('no Note Off for a note that is not on', stray, 0)
check('velocity of every Note On = the event value >> 5 (at least 1)', [m[2] for m in ons], [max(1, min(127, v >> 5)) for _, _, v in trig])
check(f'every note is {BASE - 1} + the printed pad number (pad 1 = note {BASE})', [m[1] for m in ons], [NOTE[p] for p, _, _ in trig])
check('Note Offs come in the same order as the releases', [m[1] for m in offs], [NOTE[p] for p, _, _ in rel])
check('all MIDI data bytes are 7-bit', all(m[1] < 128 and m[2] < 128 for m in msgs))
# pressure rules, replayed on the message stream
state, last, bad_on, repeat = set(), {}, 0, 0
for st, note, d2 in msgs:
    t = st & 0xF0
    if t == 0x90: state.add(note); last[note] = None
    elif t == 0x80: state.discard(note); last.pop(note, None)
    elif t == 0xA0:
        bad_on += note not in state; repeat += last.get(note) == d2; last[note] = d2
check('no poly pressure for a note that is off', bad_on, 0)
check('no repeated identical pressure value', repeat, 0)
# a read with only aftertouch for pads whose note is off must produce nothing (light touches that never became a hit)
pad_of_note = {NOTE[p]: p for p in range(16)}
held_pads, quiet_reads, loud_reads = set(), 0, 0
for evs, out in per_read:
    if evs and all(t == 4 for _, t, _ in evs) and not any(p in held_pads for p, _, _ in evs):
        quiet_reads += 1; loud_reads += bool(out)
    for st, note, d2 in out:
        if st & 0xF0 == 0x90: held_pads.add(pad_of_note[note])
        elif st & 0xF0 == 0x80: held_pads.discard(pad_of_note[note])
check(f'aftertouch alone on a pad whose note is off sends nothing ({quiet_reads} such reads)', (quiet_reads > 0, loud_reads), (True, 0))
# slow presses: a quiet Note On at the press-on value, then pressure messages until the press-off
slow = [i for i, (p, t, v) in enumerate(trig) if t == 0]
follow = []
for i in slow:
    pos = [k for k, m in enumerate(msgs) if m[0] & 0xF0 == 0x90][i]
    note, n = msgs[pos][1], 0
    for st, nt, d2 in msgs[pos + 1:]:
        if nt == note and st & 0xF0 == 0x80: break
        n += nt == note and st & 0xF0 == 0xA0
    follow.append(n)
check(f'each of the {len(slow)} slow presses is followed by poly pressure messages before its Note Off', all(n >= 1 for n in follow), True, follow)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
