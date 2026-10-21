#!/usr/bin/env python3
"""The FL Studio script without FL Studio: flsim.py stands in for FL's modules, and the script is checked against it (every button, mode and encoder
target of docs/fl-studio.md gives the FL calls it should; LEDs and screen messages are well formed). With an image, the second part connects the
script to the emulated firmware (tools/midi_patch/devsim.py): the device's own MIDI goes to the script, the script's LEDs, HOST and TEXT go to the
device, and the LEDs and the screen the device ends up with are compared with what the script meant (host mode, and the pixel fallback).

    test_fl_script.py                              the script against flsim
    test_fl_script.py patched.bin data_init.bin    ... and against the emulated device (needs the venv of run_tests.sh)"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, 'Ex-Machina'))
import flsim
from flsim import Event
P = flsim.install()
import exm_core, exm_out as out, exm_tables as tb
import midi, transport

ok = True
def check(name, got, want=True):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}'), flush=True)

clock = [1000.0]
exm_core.now = lambda: clock[0]
def advance(s): clock[0] += s

def fresh(reply=True):
    """A new project and controller, started like FL starts it; reply: the device answers HOST (a firmware with host mode)."""
    flsim.P = flsim.Project(); global P; P = flsim.P
    c = exm_core.Controller(); c.init()
    if reply: c.on_sysex(Event(0xF0, sysex=bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x60, 0, 1, 0xF7])))
    c.idle(); P.log.clear(); P.out.clear()
    return c
def cc(c, n, v): e = Event(0xB0 | tb.CHANNEL, n, v); c.midi(e); return e.handled
def press(c, name):
    n = tb.SHIFT_CC[name[6:]] if name.startswith('Shift+') else tb.BUTTON_CC[name]
    a = cc(c, n, 127); b = cc(c, n, 0); c.idle(); return a, b
def pad(c, n, vel=100):
    e = Event(0x90 | tb.CHANNEL, tb.PAD_NOTE[n], vel); c.midi(e); f = Event(0x80 | tb.CHANNEL, tb.PAD_NOTE[n], 0); c.midi(f); c.idle(); return e.handled
def enc(c, d): h = cc(c, tb.ENC_CC, d & 0x7F); c.idle(); return h
def calls(name): return [a[1:] for a in P.log if a[0] == name]
def sysexes(): return [b for k, b in P.out if k == 'sysex']
def hosts(): return [b[5] for b in sysexes() if b[4] == tb.CMD_HOST]
def screen(c): return [out.clean(x).rstrip() for x in c.lines]

# ---- the start --------------------------------------------------------------------------------------------------------------------------------------
flsim.P = P = flsim.Project()
c = exm_core.Controller(); c.init()
check('OnInit asks for host mode: HOST 1 (screen)', hosts(), [tb.HOST_SCREEN])
leds = [m for k, m in P.out if k == 'msg']
check('... and sets every LED the script uses (16 pads + the script\'s buttons), as Note On on channel 2', (len(leds) >= 16 + 15, all(m & 0xFF == 0x91 for m in leds)), (True, True))
check('... no screen yet (waiting for the answer)', [b for b in sysexes() if b[4] in (0x01, tb.CMD_TEXT)], [])
c.on_sysex(Event(0xF0, sysex=bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x60, 0, 1, 0xF7]))); P.out.clear(); c.idle()
texts = [b for b in sysexes() if b[4] == tb.CMD_TEXT]
check('the answer comes: four TEXT lines, one per line', [b[5] for b in texts], [0, 1, 2, 3])
check('... 21 characters each (F0 7D 4D 4B 21 line 0 <21> F7: 29 bytes)', {len(b) for b in texts}, {29})
check('... the screen: mode, channel, pattern, tempo and transport', screen(c), ['PLAY', 'KICK', 'PAT 1 PATTERN 1', '140.0 BPM        STOP'])
P.out.clear(); c.idle(); c.idle()
check('nothing changed: nothing is sent again', P.out, [])

c = fresh(reply=False); advance(1.1); c.idle()
check('no answer within a second (older firmware): the screen goes out as pixel regions', (c.host_ok, len(c.px_queue)), (False, 1))
sent = [b for b in sysexes() if b[4] == 0x01]
check('... one region per idle call, at least 10 ms apart (half 0, then half 1)', ([b[6] for b in sent], len(sent[0]) if sent else 0), ([0], 9 + 293 + 1))
c.idle(); check('... the second region waits', len([b for b in sysexes() if b[4] == 0x01]), 1)
advance(0.02); c.idle(); check('... and goes 20 ms later', [b[6] for b in sysexes() if b[4] == 0x01], [0, 2])
P.out.clear(); advance(2.1); c.idle(); advance(0.02); c.idle(); advance(0.02); c.idle()
check('... drawn again every 2 s (the firmware may have drawn its own screen in between)', [b[6] for b in sysexes() if b[4] == 0x01], [0, 2])
press(c, 'Step'); check('... and no HOST is sent to a firmware that does not know it', hosts(), [])

# ---- transport --------------------------------------------------------------------------------------------------------------------------------------
c = fresh()
check('Play: transport.start, the CC goes no further (press and release)', (press(c, 'Play'), calls('start')), ((True, True), [()]))
check('... the Play LED is bright while FL plays', c.leds[tb.BUTTON_LED['Play']], 0x7F)
press(c, 'Stop'); check('Stop: transport.stop, the Play LED dims', (calls('stop'), c.leds[tb.BUTTON_LED['Play']]), ([()], 0x7C))
press(c, 'Rec'); check('Rec: transport.record, its LED lit', (calls('record'), c.leds[tb.BUTTON_LED['Rec']]), ([()], 0x7F))
P.log.clear(); press(c, 'Restart'); check('Restart: to the start and play', (calls('setSongPos'), calls('start')), ([(0,)], [()]))
P.log.clear(); P.playing = False; press(c, 'Shift+Play'); check('Shift + Play: the same', (calls('setSongPos'), calls('start')), ([(0,)], [()]))
press(c, 'Tap'); check('Tap: tap tempo', calls('globalTransport')[-1], (midi.FPT_TapTempo, 1))
press(c, 'Shift+Tap'); check('Shift + Tap: metronome, shown on the screen', (calls('globalTransport')[-1], screen(c)[1:3]), ((midi.FPT_Metronome, 1), ['METRONOME', 'ON']))
press(c, 'Follow'); check('Follow: pattern / song mode, LED lit in song mode', (calls('setLoopMode'), c.leds[tb.BUTTON_LED['Follow']]), ([()], 0x7F))
press(c, 'Shift+Left'); press(c, 'Shift+Right'); check('Shift + Left / Right: undo / redo', (calls('undoUp'), calls('undoDown')), ([()], [()]))
check('a button the script does not use (Scene) goes on to FL (press and release)', press(c, 'Scene'), (False, False))
c.beat_indicator(1); c.idle(); a = c.leds[tb.BUTTON_LED['Tap']]; c.beat_indicator(0); c.idle()
check('the beat blinks on Tap (OnUpdateBeatIndicator)', (a, c.leds[tb.BUTTON_LED['Tap']]), (0x7F, 0x7C))
advance(2); c.idle(); check('messages go after 1.5 s', screen(c)[1], 'KICK')

# ---- pad modes --------------------------------------------------------------------------------------------------------------------------------------
c = fresh()
check('play mode: pads go to FL (FPC on the selected channel plays them)', pad(c, 1), False)
check('... the pad LEDs show the FPC pad colours (pad 1 green, pad 2 blue)', (c.leds[tb.PAD_LED[1]], c.leds[tb.PAD_LED[2]]), (out.code(7, 2), out.code(11, 2)))
press(c, 'Step')
check('Step: step mode, HOST 3 (the pads become a grid), its LED lit, title STEP 1/1', (hosts(), c.leds[tb.BUTTON_LED['Step']], screen(c)[0]), ([3], 0x7F, 'STEP 1/1'))
check('... pad 1 sets step 1 of the selected channel, the note does not play', (pad(c, 1), calls('setGridBit')), (True, [(0, 0, 1)]))
check('... lit in the channel\'s colour (red), steps 5, 9, 13 marked dim white, others dark', [c.leds[tb.PAD_LED[n]] for n in (1, 2, 5)], [out.code(1, 3), 0, out.code(17, 0)])
pad(c, 1); check('... pad 1 again clears it', calls('setGridBit')[-1], (0, 0, 0))
P.pat[0]['length'] = 8; press(c, 'Right'); pad(c, 3)
check('a pattern of 8 beats: Right = steps 17-32, pad 3 = step 19', (c.page['step'], calls('setGridBit')[-1], screen(c)[0]), (1, (0, 18, 1), 'STEP 2/2'))
press(c, 'Right'); check('... Right stops at the last page', c.page['step'], 1)
P.playing = True; P.step = 18; advance(0.1); c.idle()
check('while FL plays, the playhead is a white pad (step 19 = pad 3)', c.leds[tb.PAD_LED[3]], out.code(17, 3))
P.playing = False; press(c, 'Erase'); check('Erase in step mode: the channel\'s steps cleared', (P.ch[0]['grid'], screen(c)[1]), (set(), 'ERASE'))
P.ch[1]['grid'] = {1, 2}; press(c, 'Shift+Erase'); check('Shift + Erase: every channel\'s', all(not ch['grid'] for ch in P.ch))
P.log.clear(); press(c, 'Shift+Step'); enc(c, 1)
check('Shift + Step + encoder: pattern length +4 beats (FL 2026 setPatternLength)', calls('setPatternLength'), [(1, 12)])
press(c, 'Step'); check('Step again: back to play mode, HOST 1', (c.mode, hosts()[-1], pad(c, 2)), ('play', 1, False))

c = fresh(); press(c, 'Select')
check('Select: pad 3 selects channel 3', (pad(c, 3), calls('selectOneChannel'), screen(c)[1]), (True, [(2,)], 'CHANNEL'))
check('... its pad is bright, the others dim, pads without a channel dark', [c.leds[tb.PAD_LED[n]] for n in (3, 1, 5)], [out.code(11, 3), out.code(1, 1), 0])
pad(c, 9); check('... a pad without a channel does nothing', calls('selectOneChannel'), [(2,)])
c = fresh(); press(c, 'Mute'); pad(c, 2)
check('Mute: pad 2 mutes channel 2, its pad dims', (calls('muteChannel'), c.leds[tb.PAD_LED[2]]), ([(1,)], out.code(7, 0)))
press(c, 'Solo'); pad(c, 3)
check('Solo (from Mute: straight over): pad 3 solos channel 3, bright, the others off', (c.mode, calls('soloChannel'), c.leds[tb.PAD_LED[3]], c.leds[tb.PAD_LED[1]]), ('solo', [(2,)], out.code(11, 3), out.code(1, 0)))
c = fresh(); press(c, 'Pattern'); pad(c, 2)
check('Pattern: pad 2 = pattern 2', (calls('jumpToPattern'), P.cur), ([(2,)], 2))
check('... the current one bright, the others dim, the next free one dim white', [c.leds[tb.PAD_LED[n]] for n in (2, 1, 3, 4)], [out.code(out.nearest(0x8000FF), 3), out.code(out.nearest(0xFF8000), 1), out.code(17, 0), 0])
press(c, 'Duplicate'); check('Duplicate: clonePattern', (calls('clonePattern'), len(P.pat)), ([(None,)], 3))
c = fresh(); press(c, 'Group'); pad(c, 4)
check('Group: pad 4 selects mixer insert 4', (calls('setTrackNumber'), P.track), ([(4,)], 4))
press(c, 'Volume'); enc(c, 5)
check('... Volume + encoder in Group mode: that insert\'s volume (+5 %)', round(P.tracks[4]['vol'], 3), 0.85)

# ---- the encoder ---------------------------------------------------------------------------------------------------------------------------------------
c = fresh()
check('no target: the encoder jogs (ui.jog), relative: 3 and -2', (enc(c, 3), enc(c, -2), calls('jog')), (True, True, [(3,), (-2,)]))
cc(c, 8, 127); cc(c, 8, 0); check('... the push = enter', calls('enter'), [()])
press(c, 'Volume'); enc(c, 10)
check('Volume: the selected channel\'s volume +10 %, on the screen', (round(P.ch[0]['vol'], 3), screen(c)[1:3]), (0.88, ['VOL KICK', '88%']))
cc(c, 8, 127); enc(c, 5); cc(c, 8, 0); check('... with the push held: fine steps', round(P.ch[0]['vol'], 3), 0.89)
press(c, 'Shift+Encoder Push'); check('Shift + push: back to the default', P.ch[0]['vol'], 0.78)
press(c, 'Volume'); check('Volume again: no target', c.target, None)
press(c, 'Sampling'); enc(c, -10); check('Sampling: pan, 20 % left', (round(P.ch[0]['pan'], 2), screen(c)[2]), (-0.2, '20% LEFT'))
press(c, 'Tempo'); enc(c, 2); check('Tempo: tempo jog, shown', (calls('globalTransport')[-1], screen(c)[2]), ((midi.FPT_TempoJog, 20), '142.0 BPM'))
press(c, 'Swing'); enc(c, 3); check('Swing: FL 2026 set_swing', (calls('set_swing'), screen(c)[2]), ([(3,)], '3'))
del transport.set_swing; enc(c, 3); check('... without it (older FL): a message, no error', screen(c)[1:3], ['SWING', 'NEEDS FL STUDIO 2026'])
transport.set_swing = lambda v: None
c = fresh(); press(c, 'Right'); press(c, 'Right'); press(c, 'Right')
check('Right with no grid mode: the next channel (Bass)', (P.sel, screen(c)[1]), (3, 'CHANNEL'))
press(c, 'Plug-in'); check('Plug-in: the first parameter of its plug-in, name and value', screen(c)[1:3], ['OSC 1 COARSE', '0 ST'])
cc(c, 8, 127); cc(c, 8, 0); c.idle(); check('... push: the next parameter that has a name (skips the empty one)', (c.param, screen(c)[1]), (2, 'OSC 2 COARSE'))
enc(c, 32); check('... encoder: its value (+32/128)', P.ch[3]['params'][2][1], 0.5)
press(c, 'Left'); check('... Left: the previous parameter', c.param, 0)
press(c, 'Shift+Plug-in'); enc(c, 1); enc(c, -1)
check('Shift + Plug-in: presets next / previous', (calls('nextPreset'), calls('prevPreset')), ([(3,)], [(3,)]))
press(c, 'Browser'); enc(c, 2); cc(c, 8, 127); cc(c, 8, 0)
check('Browser: shown and focused; encoder = next, push = enter', (calls('showWindow'), calls('next'), calls('enter')), ([(midi.widBrowser,)], [(), ()], [()]))
press(c, 'Shift+Browser'); check('Shift + Browser: hidden, no target', (calls('hideWindow'), c.target), ([(midi.widBrowser,)], None))
press(c, 'Favorites'); check('Favorites: the selected channel\'s plug-in window', calls('showEditor'), [(3,)])
check('the encoder touch sends nothing in the preset (a learn would grab it)', 'Encoder Touch' in tb.BUTTON_CC, False)

# ---- colours ------------------------------------------------------------------------------------------------------------------------------------------
check('colours: red, green, blue, yellow, grey, black', [out.nearest(x) for x in (0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00, 0x808080, 0)], [1, 7, 11, 5, 17, 17])
check('the text is the device font\'s (capitals, ? for the rest), 21 columns', out.clean('aé{x'), 'A??X'.ljust(21))

# ---- with the emulated device --------------------------------------------------------------------------------------------------------------------------
if len(sys.argv) > 2:
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'midi_patch')); sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'emu'))
    import devsim, dispsim
    import mmk3_config as mc
    fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
    FLCFG = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'fl-studio')
    B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}; PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}

    class Link:
        """The script and the emulated device, connected both ways."""
        def __init__(self, answer=True):
            self.d = devsim.Dev(fw, data, FLCFG); self.d.translate(devsim.report1()); self.d.start()
            self.sc = dispsim.Screen(self.d); self.sc.settle(); self.answer = answer
            flsim.P = flsim.Project(); global P; P = flsim.P
            self.c = exm_core.Controller(); self.c.init(); self.pump()
        def pump(self, n=6):
            for _ in range(n):
                items, P.out[:] = list(P.out), []
                pk = b''
                for k, m in items:
                    if k == 'msg': pk += bytes([(m & 0xFF) >> 4, m & 0xFF, (m >> 8) & 0x7F, (m >> 16) & 0x7F])
                    else:
                        if pk: self.flush(pk); pk = b''
                        if not self.answer and m[4] == tb.CMD_HOST: continue          # (an older firmware: HOST means nothing to it)
                        self.d.all_sent.clear(); self.d.send_sysex(m)
                        for _ in range(8): self.d.tick(0)
                        for r in devsim.sysex_messages(self.d.all_sent):
                            if self.answer: self.c.on_sysex(Event(0xF0, sysex=r))
                if pk: self.flush(pk)
                advance(0.02); self.c.idle(); self.sc.run(4, 10)
        def flush(self, pk):
            for o in range(0, len(pk), 64): self.d.rx(pk[o:o + 64])
        def device(self, out_pkts):                 # what the device sent goes to the script, like FL's MIDI input
            for cin, st, d1, d2 in out_pkts:
                if cin in (8, 9, 0xB): self.c.midi(Event(st, d1, d2))
            self.pump()
        def press(self, name): self.device(self.d.translate(devsim.report1([B[name]]))); self.device(self.d.translate(devsim.report1()))
        def hit(self, n): self.device(self.d.translate(devsim.report2([(PADIDX[n], 1, 3000)]))); self.device(self.d.translate(devsim.report2([(PADIDX[n], 3, 0)])))
        def leds_match(self):
            got = self.d.led(); return [(l, got[l], v) for l, v in self.c.leds.items() if got[l] != v]

    x = Link()
    check('device: the firmware answers HOST, the script uses TEXT', x.c.host_ok, True)
    x.sc.settle()
    check('device: the screen is the script\'s four lines, pixel for pixel', x.sc.fb() == out.frame(x.c.lines))
    check('device: every LED the script set is lit as it meant', x.leds_match(), [])
    x.press('Play')
    check('device: Play on the device -> FL plays, the Play LED is bright on the device', (P.playing, x.d.led()[B['Play']]), (True, 0x7F))
    x.press('Stop'); x.press('Keyboard'); x.press('Step')
    check('device: Keyboard (the device\'s own mode), then Step: step mode, the device in raw mode', (x.c.mode, x.c.host_flags), ('step', 3))
    x.hit(1); x.hit(16)
    check('device: pads 1 and 16 in Keyboard mode still set steps 1 and 16 (the grid notes 36 / 51)', calls('setGridBit'), [(0, 0, 1), (0, 15, 1)])
    x.sc.settle()
    check('device: the screen shows STEP 1/1 (TEXT)', (x.sc.fb() == out.frame(x.c.lines), out.clean(x.c.lines[0]).rstrip()), (True, 'STEP 1/1'))
    check('device: the step LEDs are on the device', x.leds_match(), [])
    x.press('Step'); P.log.clear()
    out1 = x.d.translate(devsim.report2([(PADIDX[1], 1, 3000)])); x.d.translate(devsim.report2([(PADIDX[1], 3, 0)]))
    check('device: back in play mode the pads play the device\'s Keyboard mode again (pad 1 = 60)', [m[2] for m in out1 if m[0] == 9], [60])
    x.press('Volume'); x.device(x.d.translate(devsim.report1(enc=3))); x.sc.settle()
    check('device: Volume + 3 encoder steps -> +3 %, the screen says so', (round(P.ch[0]['vol'], 2), out.clean(x.c.lines[2]).rstrip(), x.sc.fb() == out.frame(x.c.lines)), (0.81, '81%', True))

    x = Link(answer=False); advance(1.1); x.pump(8); x.sc.settle(); x.pump(4)
    check('device, no answer to HOST: the pixel regions draw the same picture', (x.c.host_ok, x.sc.fb() == out.frame(x.c.lines)), (False, True))
    check('device, no answer: the LEDs as well', x.leds_match(), [])

print('ALL PASS' if ok else 'SOME TESTS FAILED')
sys.exit(0 if ok else 1)
