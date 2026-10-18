#!/usr/bin/env python3
"""Listens to the PATCHED Maschine Mikro MK3 as a MIDI input and prints what it sends, then a summary.
Needs `pip install mido python-rtmidi`. Read-only: it only receives.

    midi_monitor.py [--seconds 40] [--port NAME] [--log FILE] [--list]

Expected with the default build: pad n sends Note On/Off for note 35 + n (pad 1 = 36 ... pad 16 = 51; --pad-base 12 gives
12..27) plus Polyphonic Key Pressure while it is held; buttons send Control Change (NI's numbers, 127 on press and 0 on
release) except Play = MIDI Start and Stop = MIDI Stop (on press only; --transport cc / mmc change that); the encoder CC 7,
its press CC 8 and touch CC 9; the touch strip CC 1 (0..127).
"""
import argparse, sys, time

def describe(m):
    if m.type in ('note_on', 'note_off'): return f'{m.type:9s} ch{m.channel + 1} note {m.note:3d} velocity {m.velocity:3d}'
    if m.type == 'polytouch': return f'polytouch ch{m.channel + 1} note {m.note:3d} pressure {m.value:3d}'
    if m.type == 'control_change': return f'cc        ch{m.channel + 1} cc {m.control:3d} value {m.value:3d}'
    if m.type in ('start', 'stop', 'continue'): return f'{m.type.upper():9s} (MIDI realtime)'
    if m.type == 'sysex': return 'sysex     ' + ' '.join(f'{b:02X}' for b in m.data) + ('  (MIDI Machine Control)' if tuple(m.data[:3]) == (0x7F, 0x7F, 0x06) else '')
    return str(m)

def summarize(msgs):
    L = [f'{len(msgs)} messages']
    ons = [m for _, m in msgs if m.type == 'note_on' and m.velocity > 0]
    if ons: L.append(f'note on: {len(ons)}, notes {sorted({m.note for m in ons})}, velocity {min(m.velocity for m in ons)}..{max(m.velocity for m in ons)}')
    offs = [m for _, m in msgs if m.type == 'note_off' or (m.type == 'note_on' and m.velocity == 0)]
    if offs: L.append(f'note off: {len(offs)}')
    pt = [m for _, m in msgs if m.type == 'polytouch']
    if pt: L.append(f'poly pressure: {len(pt)}, max {max(m.value for m in pt)}')
    cc = {}
    for _, m in msgs:
        if m.type == 'control_change': cc.setdefault(m.control, []).append(m.value)
    if cc: L.append('control changes: ' + ', '.join(f'CC{c} x{len(v)}' for c, v in sorted(cc.items())))
    rt = [m.type for _, m in msgs if m.type in ('start', 'stop', 'continue')]
    if rt: L.append('realtime: ' + ', '.join(f'{t} x{rt.count(t)}' for t in sorted(set(rt))))
    sx = [m for _, m in msgs if m.type == 'sysex']
    if sx: L.append(f'sysex: {len(sx)}')
    return '\n'.join(L)

def main():
    import mido
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seconds', type=float, default=40); ap.add_argument('--port'); ap.add_argument('--log'); ap.add_argument('--list', action='store_true')
    a = ap.parse_args()
    names = mido.get_input_names()
    if a.list or not names:
        print('MIDI inputs:', names or 'none'); return 0 if names else 1
    name = a.port or next((n for n in names if 'icro' in n or 'aschine' in n), None)
    if name is None: print('no Maschine input among', names); return 1
    print(f'listening to "{name}" for {a.seconds:.0f} s', flush=True)
    msgs, t0 = [], time.monotonic()
    log = open(a.log, 'w') if a.log else None
    with mido.open_input(name) as port:
        while time.monotonic() - t0 < a.seconds:
            for m in port.iter_pending():
                t = time.monotonic() - t0; msgs.append((t, m))
                line = f'{t:7.3f}s  {describe(m)}'
                print(line, flush=True)
                if log: log.write(line + '\n')
            time.sleep(0.002)
    print(summarize(msgs)); return 0

if __name__ == '__main__':
    sys.exit(main())
