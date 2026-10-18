"""Tests the report parsing and summary of hid_capture.py with synthetic reports (no hardware, no hidapi needed)."""
import os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hid_capture as H

ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

def r1(buttons=0, touch=0, enc=0, pos=0):
    return bytes([1]) + bytes((buttons >> (8 * k)) & 255 for k in range(5)) + bytes([touch, enc, 0, 0, pos, 0, 0, 0])
def r2(*events):
    p = bytearray([2])
    for pad, typ, val in events: p += bytes([pad, (typ << 4) | (val >> 8), val & 255])
    return bytes(p + bytes(64 - len(p)))

check('report 1 is 14 bytes and report 2 is 64 bytes', len(r1()) == 14 and len(r2((0, 4, 5))) == 64)
check('parse: one report 1', H.parse(r1(buttons=1 << 22)) == [('r1', r1(buttons=1 << 22)[1:])])
check('parse: pad events, a zero triplet ends the list', H.parse(r2((12, 4, 60), (12, 1, 765))) == [('r2', [(12, 4, 60), (12, 1, 765)])])
check('parse: two reports concatenated in one read', [k for k, _ in H.parse(r1() + r2((3, 4, 7)))] == ['r1', 'r2'])
check('parse: values use all 12 bits', H.parse(r2((5, 1, 4095))) == [('r2', [(5, 1, 4095)])])
check('parse: an unknown report id is passed through', H.parse(bytes([9, 1, 2, 3]))[0][0] == 'other')

rows = [(0.0, r1()),
        (10.0, r1(buttons=1 << 22)), (30.0, r1()),                                   # Play pressed once
        (40.0, r1(enc=3)), (50.0, r1(enc=1)),                                        # encoder +3 then -2
        (60.0, r1(enc=1, pos=50)), (70.0, r1(enc=1, pos=150)), (80.0, r1(enc=1)),                  # strip touched once, 50..150
        (100.0, r2((12, 4, 60))), (107.0, r2((12, 1, 765))), (120.0, r2((12, 4, 120))),
        (150.0, r2((12, 4, 0), (12, 3, 0))),                                         # hit on index 12 = pad 1
        (200.0, r2((15, 4, 20))), (230.0, r2((15, 0, 140))), (240.0, r2((15, 4, 140))), (260.0, r2((15, 2, 0))),   # slow press, pad 4
        (300.0, r2((0, 4, 20))), (320.0, r2((0, 4, 0)))]                             # touch on pad 13, no hit
text = H.summarize(rows)
check('summary: button press edges', 'button presses: Play x1' in text, text)
check('summary: encoder steps and net movement', 'encoder: 5 steps, net +1' in text, text)
check('summary: strip touches and range', 'touch strip: 1 touches, position 50..150' in text, text)
check('summary: the hit is on printed pad 1 with value 765, velocity 23, 7 ms after the first event, pressure 60 before and 120 after',
      re.search(r'pad\s+1: note-on\s+765 -> velocity\s+23 \(7 ms after the first event\), pressure before 60, after 120', text), text)
check('summary: slow press recognised on printed pad 4', re.search(r'pad\s+4: slow press \(press-on 140\), max pressure 140', text), text)
check('summary: aftertouch without a hit on printed pad 13', re.search(r'pad 13: aftertouch only, max 20', text), text)
check('summary: note-on statistics', 'note-on values: n=1, min 765, median 765, max 765 (velocity 23..23 at >> 5)' in text, text)
check('summary: event type counts', 'aftertouch x' in text and 'note-on x1' in text and 'note-off x1' in text and 'press-on x1' in text and 'press-off x1' in text, text)
# guided-test timeline: pads in order, buttons in order, encoder runs, strip slides
seq_rows = [(0.0, r1(enc=5)),
            (100.0, r2((12, 1, 900))), (150.0, r2((12, 3, 0))), (1100.0, r2((13, 1, 900))), (1150.0, r2((13, 3, 0))),
            (2000.0, r1(enc=5, buttons=1 << 3)), (2100.0, r1(enc=5)), (3000.0, r1(enc=5, buttons=1 << 8)), (3100.0, r1(enc=5)),
            (4000.0, r1(enc=6)), (4100.0, r1(enc=7)), (4200.0, r1(enc=6)), (9000.0, r1(enc=6, pos=10)), (9100.0, r1(enc=6, pos=100)), (9200.0, r1(enc=6, pos=190)), (9300.0, r1(enc=6))]
text2 = H.sequence(seq_rows)
check('sequence: pads in trigger order with printed numbers and HID indices', 'printed numbers): 1 2   [HID indices: 12 13]' in text2, text2)
check('sequence: buttons in press order', 'buttons pressed, in order: Volume, Left' in text2, text2)
check('sequence: encoder runs with direction', 'encoder runs (counter + = increasing): +2 at 4.0s; -1 at 4.2s' in text2, text2)
check('sequence: strip slide from 10 to 190', 'strip touch 1 at 9.0s: 3 samples, from 10 to 190 (min 10, max 190)' in text2, text2)
first = [(0.0, r1(buttons=1 << 0)), (50.0, r1())]
check('a button pressed in the very first report counts as a press (report 1 is sent on change only)',
      'button presses: Project x1' in H.summarize(first) and 'buttons pressed, in order: Project' in H.sequence(first), H.sequence(first))
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, 'log.txt')
    open(p, 'w').write(''.join(f'{ms:.1f} {b.hex()}\n' for ms, b in rows))
    check('read_log round-trips the recording', H.read_log(p) == rows)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
