#!/usr/bin/env python3
"""Read-only capture of the STOCK Maschine Mikro MK3's HID input reports, with a summary of what the pads, buttons, encoder and
touch strip sent. Nothing is ever written to the device (no output or feature reports). Needs `pip install hidapi`.

    hid_capture.py capture log.txt [--seconds 40] [--idle-stop 8] [--wait 60]   # record, then print the summary
    hid_capture.py summary log.txt                                              # summarise an earlier recording
    hid_capture.py sequence log.txt                                             # ordered timeline of a guided test

Report layouts (three community drivers and the firmware agree): id 1 = 13 bytes after the id: 40 button bits (bit = button id,
39 = encoder press), a byte whose bit 0 is encoder touch, the encoder counter (low nibble), a 16-bit strip timestamp, strip
position 1 (0 = untouched, 1..200), 0, strip position 2, 0. Id 2 = pad events of 3 bytes [pad, type << 4 | value >> 8, value & 0xff]
with types 0 press-on, 1 note-on (hit, peak value), 2 press-off, 3 note-off, 4 aftertouch; a zero triplet ends the list.
Pad index 0 is the pad printed 13 (top left), index 12 is pad 1. Log format: one line per read, "<ms since the first report> <hex>".
"""
import argparse, sys, time

VID, PID = 0x17CC, 0x1700
PAD_LABEL = [13, 14, 15, 16, 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4]
BUTTONS = ['Project', 'Favorites', 'Browser', 'Volume', 'Swing', 'Tempo', 'Plug-in', 'Sampling', 'Left', 'Right', 'Pitch', 'Mod',
           'Perform', 'Notes', 'Group', 'Auto', 'Lock', 'Note Repeat', 'Restart', 'Erase', 'Tap', 'Follow', 'Play', 'Rec', 'Stop',
           'Shift', 'Fixed Vel', 'Pad Mode', 'Keyboard', 'Chords', 'Step', 'Scene', 'Pattern', 'Events', 'Variation', 'Duplicate',
           'Select', 'Solo', 'Mute', 'Encoder press', 'Encoder touch']
TYPES = {0: 'press-on', 1: 'note-on', 2: 'press-off', 3: 'note-off', 4: 'aftertouch'}

def parse(buf):
    """One read may hold several reports. Returns [('r1', 13 bytes) | ('r2', [(pad, type, value)]) | ('other', bytes)]."""
    out, i = [], 0
    while i < len(buf):
        if buf[i] == 1 and i + 14 <= len(buf):
            out.append(('r1', buf[i + 1:i + 14])); i += 14
        elif buf[i] == 2 and i + 4 <= len(buf):
            body, ev = buf[i + 1:i + 64], []
            body = body + bytes(-len(body) % 3)          # a log may have trimmed the trailing zero bytes of the last triplet
            for k in range(0, len(body) - 2, 3):
                pad, b1, b2 = body[k:k + 3]
                if pad == 0 and b1 == 0 and b2 == 0: break
                ev.append((pad, b1 >> 4, ((b1 & 15) << 8) | b2))
            out.append(('r2', ev)); i += 64
        else:
            out.append(('other', bytes(buf[i:]))); break
    return out

def read_log(path):
    """Lines starting with '#' and blank lines are ignored."""
    rows = []
    for line in open(path):
        if line.strip() and not line.startswith('#'):
            t, h = line.split(); rows.append((float(t), bytes.fromhex(h)))
    return rows

def summarize(rows):
    L = []
    ids, lens = {}, {}
    state, presses = [0] * 41, {}          # report 1 is sent on change only, so the first one can already be a press
    enc_net, enc_steps, enc_last = 0, 0, None
    strip_pos, strip_touches, strip_down = [], 0, False
    events = []                                  # (ms, pad, type, value)
    for ms, buf in rows:
        lens[len(buf)] = lens.get(len(buf), 0) + 1
        for kind, body in parse(buf):
            ids[kind] = ids.get(kind, 0) + 1
            if kind == 'r1':
                bits = [(body[k >> 3] >> (k & 7)) & 1 for k in range(40)] + [body[5] & 1]
                for k in range(41):
                    if bits[k] and not state[k]: presses[k] = presses.get(k, 0) + 1
                state = bits
                cnt = body[6] & 15
                if enc_last is not None and cnt != enc_last:
                    d = (cnt - enc_last) & 15; sd = d if d < 8 else d - 16
                    enc_net += sd; enc_steps += abs(sd)
                enc_last = cnt
                pos = body[9]
                if pos and not strip_down: strip_touches += 1
                strip_down = bool(pos)
                if pos: strip_pos.append(pos)
            elif kind == 'r2':
                events += [(ms, p, t, v) for p, t, v in body]
    L.append(f'{len(rows)} reads over {rows[-1][0] / 1000:.1f} s; read lengths {dict(sorted(lens.items()))}; reports {ids}' if rows else 'no reports')
    if presses: L.append('button presses: ' + ', '.join(f'{BUTTONS[k]} x{n}' for k, n in sorted(presses.items())))
    if enc_steps: L.append(f'encoder: {enc_steps} steps, net {enc_net:+d}')
    if strip_pos: L.append(f'touch strip: {strip_touches} touches, position {min(strip_pos)}..{max(strip_pos)} (of 1..200), {len(strip_pos)} samples')
    if events:
        by = {}
        for _, _, t, _ in events: by[t] = by.get(t, 0) + 1
        L.append('pad events: ' + ', '.join(f'{TYPES.get(t, t)} x{n}' for t, n in sorted(by.items())))
        strikes, cur = [], {}
        for ms, pad, t, v in events:
            c = cur.setdefault(pad, {'t0': ms, 'pre': [], 'post': [], 'on': None, 'presson': None})
            if t == 4:
                (c['pre'] if c['on'] is None else c['post']).append(v)
                if v == 0 and c['on'] is None and c['presson'] is None:      # a touch that ended without ever becoming a hit
                    strikes.append((pad, cur.pop(pad)))
            elif t == 1: c['on'] = (ms, v)
            elif t == 0: c['presson'] = (ms, v)
            elif t in (2, 3): c['off'] = (ms, t); strikes.append((pad, cur.pop(pad)))
        strikes += list(cur.items())
        L.append('strikes (pad as printed; value = the 12-bit note-on peak the firmware reports; velocity = value >> 5):')
        for pad, c in strikes:
            if c['on']:
                L.append(f'  t={c["t0"]:8.1f} ms pad {PAD_LABEL[pad]:2d}: note-on {c["on"][1]:4d} -> velocity {min(127, c["on"][1] >> 5):3d}'
                         f' ({c["on"][0] - c["t0"]:.0f} ms after the first event), pressure before {max(c["pre"], default=0)}, after {max(c["post"], default=0)}')
            elif c['presson']:
                L.append(f'  t={c["t0"]:8.1f} ms pad {PAD_LABEL[pad]:2d}: slow press (press-on {c["presson"][1]}), max pressure {max(c["pre"] + c["post"], default=0)}')
            else:
                L.append(f'  t={c["t0"]:8.1f} ms pad {PAD_LABEL[pad]:2d}: aftertouch only, max {max(c["pre"] + c["post"], default=0)} (no hit registered)')
        ons = sorted(c['on'][1] for _, c in strikes if c['on'])
        if ons: L.append(f'note-on values: n={len(ons)}, min {ons[0]}, median {ons[len(ons) // 2]}, max {ons[-1]} (velocity {ons[0] >> 5}..{min(127, ons[-1] >> 5)} at >> 5)')
        L.append(f'largest value of any pad event: {max(v for _, _, _, v in events)} (12-bit scale 0..4095)')
    return '\n'.join(L)

def sequence(rows):
    """Ordered timeline for guided tests: pads in the order they first triggered, button edges in order, encoder runs, strip slides."""
    state, enc_last, strip_cur = [0] * 41, None, None
    pads_open, pad_order, edges, enc_runs, strips = set(), [], [], [], []
    for ms, buf in rows:
        for kind, body in parse(buf):
            if kind == 'r1':
                bits = [(body[k >> 3] >> (k & 7)) & 1 for k in range(40)] + [body[5] & 1]
                edges += [(ms, k, bits[k]) for k in range(41) if bits[k] != state[k]]
                state = bits
                cnt = body[6] & 15
                if enc_last is not None and cnt != enc_last:
                    d = (cnt - enc_last) & 15; sd = d if d < 8 else d - 16
                    if enc_runs and enc_runs[-1][0] == (sd > 0) and ms - enc_runs[-1][3] < 600:
                        enc_runs[-1][1] += abs(sd); enc_runs[-1][3] = ms
                    else: enc_runs.append([sd > 0, abs(sd), ms, ms])
                enc_last = cnt
                if body[9]:
                    if strip_cur is None: strip_cur = [ms, []]; strips.append(strip_cur)
                    strip_cur[1].append(body[9])
                else: strip_cur = None
            elif kind == 'r2':
                for pad, t, v in body:
                    if t in (0, 1) and pad not in pads_open: pads_open.add(pad); pad_order.append((ms, pad))
                    elif t in (2, 3): pads_open.discard(pad)
    L = []
    if pad_order: L.append('pads in the order they triggered (printed numbers): ' + ' '.join(str(PAD_LABEL[p]) for _, p in pad_order) + '   [HID indices: ' + ' '.join(str(p) for _, p in pad_order) + ']')
    pressed = [(ms, k) for ms, k, v in edges if v]
    if pressed: L.append('buttons pressed, in order: ' + ', '.join(BUTTONS[k] for _, k in pressed))
    if enc_runs: L.append('encoder runs (counter + = increasing): ' + '; '.join(f'{"+" if d else "-"}{n} at {a / 1000:.1f}s' for d, n, a, _ in enc_runs))
    for i, (t0, pos) in enumerate(strips):
        L.append(f'strip touch {i + 1} at {t0 / 1000:.1f}s: {len(pos)} samples, from {pos[0]} to {pos[-1]} (min {min(pos)}, max {max(pos)})')
    return '\n'.join(L)

def capture(path, seconds, idle_stop, wait):
    import hid
    h = hid.device(); h.open(VID, PID)
    print(f'opened {h.get_manufacturer_string()} / {h.get_product_string()}; waiting up to {wait:.0f} s for the first report', flush=True)
    t_open, t0, last = time.monotonic(), None, None
    with open(path, 'w') as f:
        while True:
            now = time.monotonic()
            if t0 is None and now - t_open > wait: break
            if t0 is not None and (now - t0 > seconds or now - last > idle_stop): break
            d = h.read(256, 100)
            if d:
                now = time.monotonic()
                if t0 is None:
                    t0 = now
                    print(f'first report after {now - t_open:.1f} s: {bytes(d).hex()}', flush=True)
                last = now
                f.write(f'{(now - t0) * 1000:.1f} {bytes(d).hex()}\n')
    h.close()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=('capture', 'summary', 'sequence')); ap.add_argument('log')
    ap.add_argument('--seconds', type=float, default=40, help='stop this long after the first report')
    ap.add_argument('--idle-stop', type=float, default=8, help='or when nothing arrived for this long')
    ap.add_argument('--wait', type=float, default=60, help='give up if no report arrives within this long')
    a = ap.parse_args()
    if a.cmd == 'capture': capture(a.log, a.seconds, a.idle_stop, a.wait)
    rows = read_log(a.log)
    print((sequence(rows) if a.cmd == 'sequence' else summarize(rows)) if rows else 'no reports were received')

if __name__ == '__main__':
    main()
