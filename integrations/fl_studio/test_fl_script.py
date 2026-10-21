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

MODE_FL, MODE_SA = bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x62, 0, 1, 0xF7]), bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x62, 0, 0, 0xF7])
def fresh(reply=True):
    """A new project and controller, started like FL starts it, the device in FL Studio mode; reply: the device answers MODE and HOST (a firmware
    with modes and host mode), else neither (an older firmware: the script runs as before after a second)."""
    flsim.P = flsim.Project(); global P; P = flsim.P
    c = exm_core.Controller(); c.init()
    if reply: c.on_sysex(Event(0xF0, sysex=MODE_FL)); c.on_sysex(Event(0xF0, sysex=bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x60, 0, 1, 0xF7])))
    else: advance(1.1)
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
check('OnInit asks the device for its mode (SysEx 22), and nothing else yet', sysexes(), [bytes([0xF0, 0x7D, 0x4D, 0x4B, tb.CMD_MODE, 0xF7])])
check('... until it answers, the controller\'s MIDI does not reach FL (a button is swallowed, nothing called)', (cc(c, tb.BUTTON_CC['Play'], 127), calls('start')), (True, []))
P.out.clear(); c.on_sysex(Event(0xF0, sysex=MODE_FL))
check('the device is in FL Studio mode: the script asks for host mode, HOST 1 (screen)', hosts(), [tb.HOST_SCREEN])
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

flsim.P = P = flsim.Project(); c = exm_core.Controller(); c.init(); c.idle(); P.out.clear(); advance(1.1); c.idle()
check('no answer to MODE within a second (older firmware): the script takes over as before, HOST 1', hosts(), [tb.HOST_SCREEN])
c = fresh(reply=False)
advance(1.1); c.idle()
check('no answer within a second (older firmware): the screen goes out as pixel regions', (c.host_ok, len(c.px_queue)), (False, 1))
sent = [b for b in sysexes() if b[4] == 0x01]
check('... one region per idle call, at least 10 ms apart (half 0, then half 1)', ([b[6] for b in sent], len(sent[0]) if sent else 0), ([0], 9 + 293 + 1))
c.idle(); check('... the second region waits', len([b for b in sysexes() if b[4] == 0x01]), 1)
advance(0.02); c.idle(); check('... and goes 20 ms later', [b[6] for b in sysexes() if b[4] == 0x01], [0, 2])
P.out.clear(); advance(2.1); c.idle(); advance(0.02); c.idle(); advance(0.02); c.idle()
check('... drawn again every 2 s (the firmware may have drawn its own screen in between)', [b[6] for b in sysexes() if b[4] == 0x01], [0, 2])
press(c, 'Step'); check('... and no HOST is sent to a firmware that does not know it', hosts(), [])

# ---- the device's two modes ---------------------------------------------------------------------------------------------------------------------------
flsim.P = P = flsim.Project(); c = exm_core.Controller(); c.init(); P.out.clear()
c.on_sysex(Event(0xF0, sysex=MODE_SA)); c.idle(); advance(1.1); c.idle()
check('the device in Standalone mode: the script stays passive (no HOST, no LEDs, no screen, also after a second)', P.out, [])
check('... and FL sees nothing of the controller: buttons and pads are swallowed, no FL call', (press(c, 'Play'), pad(c, 1), calls('start')), ((True, True), True, []))
c.on_sysex(Event(0xF0, sysex=MODE_FL)); c.on_sysex(Event(0xF0, sysex=bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x60, 0, 1, 0xF7]))); c.idle()
check('Shift + Project on the device (it announces FL Studio mode): the script takes over, HOST 1, LEDs, the four lines', (hosts(), len([m for k, m in P.out if k == 'msg']) >= 31, len([b for b in sysexes() if b[4] == tb.CMD_TEXT])), ([tb.HOST_SCREEN], True, 4))
check('... and the controller works in FL (Play)', (press(c, 'Play'), calls('start')), ((True, True), [()]))
P.out.clear(); c.on_sysex(Event(0xF0, sysex=MODE_SA)); c.idle(); press(c, 'Stop'); advance(2.5); c.idle()
check('Shift + Project again (Standalone announced): the script stops at once: nothing sent, the controller swallowed (Stop not called)', (P.out, calls('stop')), ([], []))
c.deinit(); check('... and closing FL sends nothing either (the device already left host mode)', P.out, [])
c = fresh(); press(c, 'Project')
check('Project (a plain CC in FL Studio mode): the Playlist, shown and focused', (calls('showWindow'), calls('setFocused'), screen(c)[1]), ([(midi.widPlaylist,)], [(midi.widPlaylist,)], 'WINDOW'))
press(c, 'Project'); check('... again: the Channel Rack', calls('showWindow')[-1], (midi.widChannelRack,))

# ---- transport --------------------------------------------------------------------------------------------------------------------------------------
c = fresh()
check('Play: transport.start, the CC goes no further (press and release)', (press(c, 'Play'), calls('start')), ((True, True), [()]))
check('... the Play LED is bright while FL plays', c.leds[tb.BUTTON_LED['Play']], 0x7F)
press(c, 'Stop'); check('Stop: transport.stop, the Play LED dims', (calls('stop'), c.leds[tb.BUTTON_LED['Play']]), ([()], 0x7C))
press(c, 'Rec'); check('Rec: transport.record, its LED lit', (calls('record'), c.leds[tb.BUTTON_LED['Rec']]), ([()], 0x7F))
P.log.clear(); press(c, 'Restart'); check('Restart: to the start and play', (calls('setSongPos'), calls('start')), ([(0,)], [()]))
P.log.clear(); press(c, 'Shift+Play'); check('Shift + Play: the Score Log (the last 5 minutes played go into the pattern), shown', (calls('dumpScoreLog'), screen(c)[1]), ([(300, False)], 'SCORE LOG'))
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
check('... lit in the channel\'s colour (red), steps 5, 9, 13 marked dim white, other off steps dim in the channel colour', [c.leds[tb.PAD_LED[n]] for n in (1, 2, 5)], [out.code(1, 3), out.code(1, 0), out.code(17, 0)])
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
P.log.clear(); press(c, 'Favorites'); check('Favorites: the selected channel\'s plug-in window', calls('showEditor'), [(3,)])
check('the encoder touch sends nothing in the preset (a learn would grab it)', 'Encoder Touch' in tb.BUTTON_CC, False)

# ---- the step editor, Shift, the strip, focus and the hint bar (the 2026-10-21 research: FLkey / Fire / DrivenByMoss ideas) ----------------------------
import exm_settings
def note(c, n, vel, on=True):
    e = Event((0x90 if on else 0x80) | tb.CHANNEL, tb.PAD_NOTE[n], vel if on else 0); c.midi(e); c.idle(); return e.handled
def shift(c, down): e = Event(0xB0 | tb.CHANNEL, tb.SHIFT_REPORT_CC, 127 if down else 0); c.midi(e); c.idle(); return e.handled
c = fresh(); press(c, 'Step'); P.log.clear()
note(c, 1, 112); note(c, 1, 0, False)
check('Step mode: a pad hit sets the step with the hit\'s velocity (112, FL step parameter 1, global channel index), the screen says so',
      (calls('setGridBit'), calls('setStepParameterByIndex'), screen(c)[1:3]), ([(0, 0, 1)], [(0, 1, 0, 1, 112)], ['STEP 1', 'VELOCITY 112']))
P.log.clear(); note(c, 1, 90); held_led = c.leds[tb.PAD_LED[1]]; note(c, 1, 0, False)
check('... a set step hit again goes off when let go (and is white while held)', (calls('setGridBit'), held_led), ([(0, 0, 0)], out.code(17, 3)))
note(c, 2, 100); note(c, 2, 0, False); P.log.clear()
note(c, 2, 100); enc(c, 5); note(c, 2, 0, False)
check('hold a step and turn the encoder: its velocity +5 (100 -> 105), the graph editor opens on it, the step stays on when let go',
      (calls('setStepParameterByIndex')[-1], calls('showGraphEditor'), calls('setGridBit'), P.ch[0]['grid'] >= {1}), ((0, 1, 1, 1, 105), [(1, 1, 0)], [], True))
press(c, 'Events'); note(c, 2, 100); enc(c, 2)
check('Events: the encoder edits the next step parameter (pitch: 60 -> 62, shown as D5)', (calls('setStepParameterByIndex')[-1], screen(c)[1:3]), ((0, 1, 1, 0, 62), ['STEP 2 PITCH', 'D5']))
note(c, 2, 0, False)
check('Events outside Step mode goes on to FL (Link to controller can learn it)', (press(fresh(), 'Events')), (False, False))
exm_settings.STEP_VELOCITY = False
c = fresh(); press(c, 'Step'); P.log.clear(); note(c, 3, 127); note(c, 3, 0, False)
check('setting STEP_VELOCITY off: the step is set with FL\'s default velocity (no step parameter written)', (calls('setGridBit'), calls('setStepParameterByIndex')), ([(0, 2, 1)], []))
exm_settings.STEP_VELOCITY = True

c = fresh(); P.log.clear()
check('the device reports Shift (CC 111): handled, a help line on the screen while it is held', (shift(c, True), screen(c)[1]), (True, 'SHIFT PADS'))
check('Shift + pad 1 = UNDO (printed on the pad): undo, the note goes nowhere, nor does its release', (note(c, 1, 100), calls('undoUp'), note(c, 1, 0, False)), (True, [()], True))
note(c, 2, 100); note(c, 5, 100); note(c, 6, 100); note(c, 11, 100)
check('... pad 2 REDO, pad 5 QUANTIZE, pad 6 QUANTIZE 50% (the note starts), pad 11 COPY', (calls('undoDown'), calls('quickQuantize'), calls('globalTransport')[-1]), ([()], [(0, 0), (0, 1)], (51, 1)))
for n in (2, 5, 6, 11): note(c, n, 0, False)
shift(c, False)
check('Shift up: the help line goes; a pad plays again (in play mode it goes to FL)', (screen(c)[1] != 'SHIFT PADS', note(c, 1, 100)), (True, False))
c = fresh(); press(c, 'Shift+Rec'); a = screen(c)[1:3]; press(c, 'Shift+Restart'); b = screen(c)[1:3]
check('Shift + Rec = count-in (printed "Count-in"), Shift + Restart = loop recording (printed "Loop"), both shown', (a, b), (['COUNT-IN', 'ON'], ['LOOP RECORD', 'ON']))
P.ch[1]['mute'] = True; P.ch[2]['solo'] = True; press(c, 'Shift+Solo')
check('Shift + Solo: every channel mute and solo off', ([x['mute'] for x in P.ch], [x['solo'] for x in P.ch]), ([False] * 4, [False] * 4))
press(c, 'Group'); press(c, 'Mute'); press(c, 'Solo')
check('in the Mixer (Group mode): Mute / Solo mute and solo the selected insert', (calls('muteTrack'), calls('soloTrack')), ([(1, -1)], [(1, -1)]))

c = fresh(); press(c, 'Volume')
lit = [c.leds[tb.STRIP_LED0 + k] for k in range(tb.STRIP_LEDS)]
check('the strip shows the encoder target as a bar (channel volume 78 %: 20 of 25 LEDs, green)', (sum(1 for v in lit if v), set(v for v in lit if v)), (20, {out.code(7, 2)}))
press(c, 'Volume'); press(c, 'Sampling'); P.ch[0]['pan'] = -0.5; c.dirty = True; c.idle()
lit = [c.leds[tb.STRIP_LED0 + k] for k in range(tb.STRIP_LEDS)]
check('... pan from the centre (50 % left: LEDs 6 to 12)', [k for k in range(25) if lit[k]], list(range(6, 13)))
c = fresh(); press(c, 'Step')
check('the arrows are dark where they cannot go (a one-page pattern: both)', (c.leds[tb.BUTTON_LED['Left']], c.leds[tb.BUTTON_LED['Right']]), (0, 0))
press(c, 'Step')
check('... selecting channels: Left dark on the first channel, Right lit', (c.leds[tb.BUTTON_LED['Left']], c.leds[tb.BUTTON_LED['Right']]), (0, 0x7C))
P.log.clear(); press(c, 'Step')
check('Step brings the Channel Rack to the front; the message also goes to FL\'s hint bar', (calls('showWindow'), calls('setFocused'), P.hint), ([(midi.widChannelRack,)], [(midi.widChannelRack,)], 'STEP: HOLD STEP + ENCODER'))
P.log.clear(); press(c, 'Group'); check('Group brings the Mixer', calls('showWindow'), [(midi.widMixer,)])
exm_settings.FOCUS_WINDOWS = False; P.log.clear(); press(c, 'Select'); check('... unless FOCUS_WINDOWS is off', calls('showWindow'), []); exm_settings.FOCUS_WINDOWS = True

import device_ExMachina as dev
flsim.P = P = flsim.Project(); dev.ctl = exm_core.Controller(); dev.ctl.init(); dev.ctl.on_sysex(Event(0xF0, sysex=MODE_FL)); dev.ctl.on_sysex(Event(0xF0, sysex=bytes([0xF0, 0x7D, 0x4D, 0x4B, 0x60, 0, 1, 0xF7]))); dev.ctl.idle()
dev.ctl.turn = lambda d: 1 / 0; P.out.clear()
import io, contextlib
with contextlib.redirect_stderr(io.StringIO()) as err: dev.OnMidiMsg(Event(0xB0 | tb.CHANNEL, tb.ENC_CC, 1))
texts = [b[7:-1].decode().rstrip() for b in sysexes() if b[4] == tb.CMD_TEXT]
check('an error in a callback: the script stands down, the device keeps only its screen (HOST 1: the pads are its own again) and says so; the traceback is printed',
      (dev.ctl.broken, hosts(), texts[:1], 'ZeroDivisionError' in err.getvalue()), (True, [tb.HOST_SCREEN], ['SCRIPT ERROR'], True))
e = Event(0x90 | tb.CHANNEL, tb.PAD_NOTE[1], 100); dev.OnMidiMsg(e)
P.out.clear(); dev.OnDeInit()
check('... from then on FL gets the controller\'s MIDI as plain MIDI; closing FL still ends host mode (HOST 0)', (e.handled, hosts()), (False, [0]))
exm_settings.LOOP_RECORD_ON_CONNECT = True; flsim.P = P = flsim.Project(); exm_core.Controller().init()
check('setting LOOP_RECORD_ON_CONNECT: loop recording switched on when the script starts (once, only if it is off)', calls('globalTransport'), [(113, 1)]); exm_settings.LOOP_RECORD_ON_CONNECT = False

# ---- colours ------------------------------------------------------------------------------------------------------------------------------------------
check('colours: red, green, blue, yellow, grey, black', [out.nearest(x) for x in (0xFF0000, 0x00FF00, 0x0000FF, 0xFFFF00, 0x808080, 0)], [1, 7, 11, 5, 17, 17])
check('the text is the device font\'s (capitals, ? for the rest), 21 columns', out.clean('aé{x'), 'A??X'.ljust(21))

# ---- with the emulated device --------------------------------------------------------------------------------------------------------------------------
if len(sys.argv) > 2:
    sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'midi_patch')); sys.path.insert(0, os.path.join(HERE, '..', '..', 'tools', 'emu'))
    import devsim, dispsim
    import mmk3_config as mc
    fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
    B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}; PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}

    class Link:
        """The script and the emulated device, connected both ways."""
        def __init__(self, answer=True, fl=True):
            self.d = devsim.Dev(fw, data); self.d.translate(devsim.report1()); self.d.start()      # (the device starts in Standalone mode)
            self.sc = dispsim.Screen(self.d); self.sc.settle(); self.answer = answer
            flsim.P = flsim.Project(); global P; P = flsim.P
            self.c = exm_core.Controller(); self.c.init(); self.pump()
            if fl: self.shift_project()
        def shift_project(self):                    # the mode switch on the device: Shift down, + Project, both up
            for pressed in (['Shift'], ['Shift', 'Project'], ['Shift'], []): self.device(self.d.translate(devsim.report1([B[n] for n in pressed])))
        def pump(self, n=6):
            for _ in range(n):
                items, P.out[:] = list(P.out), []
                pk = b''
                for k, m in items:
                    if k == 'msg': pk += bytes([(m & 0xFF) >> 4, m & 0xFF, (m >> 8) & 0x7F, (m >> 16) & 0x7F])
                    else:
                        if pk: self.flush(pk); pk = b''
                        if not self.answer and m[4] in (tb.CMD_HOST, tb.CMD_MODE): continue      # (an older firmware: HOST and MODE mean nothing to it)
                        self.d.all_sent.clear(); self.d.send_sysex(m)
                        for _ in range(8): self.d.tick(0)
                        for r in devsim.sysex_messages(self.d.all_sent):
                            if self.answer: self.c.on_sysex(Event(0xF0, sysex=r))
                if pk: self.flush(pk)
                self.d.all_sent.clear()
                for _ in range(4): self.d.tick(0)
                for r in devsim.sysex_messages(self.d.all_sent):           # what the device says unasked (the announcement of a mode switch)
                    if self.answer: self.c.on_sysex(Event(0xF0, sysex=r))
                self.d.drain()
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

    x = Link(fl=False); x.pump(4)
    check('device in Standalone mode: the script asked, stays passive (no host mode), the device keeps its own idle screen', (x.c.active, x.c.host_ok), (False, None))
    x.sc.settle(); check('... the screen is the device\'s (EX-MACHINA)', x.sc.fb() == dispsim.idle('DRUMS CH1 120'), True)
    x.shift_project(); x.pump(4)
    check('device: Shift + Project -> FL Studio mode; the device announces it and the script takes over (host mode, TEXT)', (x.d.cfg() == mc.fl_cfg(), x.c.active, x.c.host_ok), (True, True, True))
    x.shift_project(); x.pump(4); x.sc.settle()
    check('device: Shift + Project again -> Standalone; the script lets go, the device\'s own screen is back', (x.c.active, x.sc.fb() == dispsim.idle('DRUMS CH1 120')), (False, True))
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

    x = Link(); x.device(x.d.translate(devsim.report1([B['Shift']])))
    check('device: holding Shift on the device shows the script\'s help line (the firmware reports Shift)', out.clean(x.c.lines[1]).rstrip(), 'SHIFT PADS')
    pk = x.d.translate(devsim.report2([(PADIDX[5], 1, 3000)])); x.device(pk); x.device(x.d.translate(devsim.report2([(PADIDX[5], 3, 0)]))); x.device(x.d.translate(devsim.report1()))
    check('device: Shift + pad 5 on the device -> FL quick-quantizes the selected channel', calls('quickQuantize')[-1:], [(0, 0)])
    x = Link(answer=False, fl=False); advance(1.1); x.pump(2); advance(1.1); x.pump(8); x.sc.settle(); x.pump(4)   # (no answer to MODE, then none to HOST)
    check('device, no answer to HOST: the pixel regions draw the same picture', (x.c.host_ok, x.sc.fb() == out.frame(x.c.lines)), (False, True))
    check('device, no answer: the LEDs as well', x.leds_match(), [])

print('ALL PASS' if ok else 'SOME TESTS FAILED')
sys.exit(0 if ok else 1)
