"""The Ex-Machina controller in FL Studio: Maschine's own functions rebuilt on FL's objects (docs/fl-studio.md has the map).

The device has two modes, switched with Shift + Project on the device: Standalone (its own mappings; the script stays out of the way and FL sees
nothing of the controller) and FL Studio, where it runs its built-in FL mapping and tells the script (SysEx 62 00 <mode>, also the answer to MODE).
In FL Studio mode every button the script uses sends its CC as a gate, a few send a second CC with Shift held, the playing
modes (Keyboard, Chords, Fixed Vel, Note Repeat, the strip) stay on the device. The script answers with the LEDs (one Note On per LED that
changed) and the screen: four lines of text, as TEXT commands when the firmware has host mode (SysEx 20 answered), else as pixel regions.

Everything FL Studio offers is reached through call(), which turns a function this FL version lacks or refuses into a default: several
functions used here are new in FL Studio 2026 (swing, pattern length) and their exact form is not documented yet."""
import time
import channels, patterns, mixer, transport, plugins, ui, general, device, midi
import exm_tables as t
import exm_out as out
import exm_settings as cfg

def now(): return time.time()

def call(mod, name, *args, default=None):
    f = getattr(mod, name, None)
    if f is None: return default
    try: return f(*args)
    except Exception: return default

def has(mod, name): return callable(getattr(mod, name, None))

CC_NAME = {cc: n for n, cc in t.BUTTON_CC.items()}
CC_NAME.update({cc: 'Shift+' + n for n, cc in t.SHIFT_CC.items()})
NOTE_PAD = {note: pad for pad, note in t.PAD_NOTE.items()}
PUSH, TOUCH = t.BUTTON_CC.get('Encoder Push'), t.BUTTON_CC.get('Encoder Touch')
GRID = ('select', 'mute', 'solo', 'pattern', 'group', 'step')
MODE_BUTTON = {'Select': 'select', 'Mute': 'mute', 'Solo': 'solo', 'Pattern': 'pattern', 'Group': 'group', 'Step': 'step'}
TARGET_BUTTON = {'Volume': 'volume', 'Swing': 'swing', 'Tempo': 'tempo', 'Sampling': 'pan', 'Plug-in': 'plugin', 'Browser': 'browser',
                 'Shift+Plug-in': 'preset', 'Shift+Step': 'length'}
MODE_TITLE = {'play': 'PLAY', 'select': 'SELECT', 'mute': 'MUTE', 'solo': 'SOLO', 'pattern': 'PATTERN', 'group': 'MIXER', 'step': 'STEP'}
MSG_S = cfg.MESSAGE_SECONDS                         # how long a value stays on the screen
# The step parameters a held step's encoder edits (Events cycles them): name, FL's parameter number, default, maximum, step per click.
# Numbers, defaults and maxima as FL's API reference and Image-Line's Akai Fire script use them.
STEP_PARAMS = (('VELOCITY', 1, 100, 127, 1), ('PITCH', 0, 60, 127, 1), ('FINE PITCH', 3, 120, 240, 2), ('PAN', 4, 64, 127, 2),
               ('RELEASE', 2, 64, 127, 2), ('MOD X', 5, 128, 255, 2), ('MOD Y', 6, 128, 255, 2), ('SHIFT', 7, 0, 255, 1))
# Shift + pad (in every mode), after the labels printed on the pads: 1 UNDO, 2 REDO, 3 STEP UNDO, 4 STEP REDO, 5 QUANTIZE, 6 QUANTIZE 50%, 9 CLEAR,
# 11 COPY, 12 PASTE. FL has one undo history, so 3 / 4 do what 1 / 2 do. A 50 % quantize (notes halfway to the grid) is not in FL's MIDI-script API
# (quickQuantize has only a start-only flag), so 6 quantizes the note starts only, and the screen says so.
SHIFT_PAD = {1: 'undo', 2: 'redo', 3: 'undo', 4: 'redo', 5: 'quantize', 6: 'quantize_starts', 9: 'clear', 11: 'copy', 12: 'paste'}
STRIP_COLOUR = {'volume': 7, 'pan': 9, 'tempo': 2, 'swing': 13, 'plugin': 11, 'preset': 11, 'length': 5}   # the strip bar's hue per encoder target
PROBE_S = 1.0                                       # how long the script waits for the answer to HOST before drawing pixels
REGION_S = 0.012                                    # pixel regions at least 10 ms apart (the firmware drops one that comes too soon)
PLAY_REFRESH_S = 0.05                               # while FL plays: the playhead, the transport LEDs, the tempo
PIXEL_REFRESH_S = 2.0                               # without host mode the firmware may draw its own screen: draw ours again this often

class Controller:
    def __init__(self):
        self.mode = 'play'; self.target = None
        self.page = {m: 0 for m in GRID}
        self.param = 0; self.push = False
        self.used = set()                                            # buttons whose press the script took
        self.host_ok = None; self.probe_t = 0.0                     # None: not known yet, True: the firmware has host mode, False: pixels
        self.leds = {}; self.lines = [''] * 4; self.sent_lines = [None] * 4
        self.msg = None; self.msg_t = 0.0                            # temporary lines 2-3 (a value), until msg_t
        self.beat = 0; self.dirty = True; self.refresh_t = 0.0
        self.px_queue = []; self.px_t = 0.0; self.px_drawn = 0.0
        self.host_flags = None
        self.active = None; self.mode_t = 0.0                       # None: the device's mode not known yet, True: FL Studio mode, False: Standalone
        self.broken = False                                         # an error stopped the script (fail())
        self.win = None                                             # the window Project showed last (Playlist / Channel Rack)
        self.shift = False                                          # Shift is held (the device reports it as SHIFT_REPORT_CC)
        self.shift_pads = set()                                     # pads pressed with Shift held: their release is ours too
        self.held = {}                                              # Step mode: held steps -> 'new' (set by this press) / 'on' (was on: off on release, unless edited) / 'edited'
        self.step_param = 0                                         # which STEP_PARAMS entry the encoder edits on held steps

    # ---- FL Studio callbacks --------------------------------------------------------------------------------------------------------------------
    def init(self):
        """Asks the device for its mode; the script takes over only in FL Studio mode (or, with no answer, a firmware without modes)."""
        self.active = None; self.mode_t = now(); self.sysex(out.mode_query())
        if cfg.LOOP_RECORD_ON_CONNECT and not call(ui, 'isLoopRecEnabled', default=True): call(transport, 'globalTransport', midi.FPT_LoopRecord, 1)

    def activate(self):
        self.active = True
        self.leds = {}; self.sent_lines = [None] * 4; self.host_ok = None; self.host_flags = None; self.px_queue = []
        self.probe_t = now(); self.send_host()
        self.refresh(full=True)

    def deactivate(self):
        """Standalone mode: the device has ended host mode and gone back to its own mapping, LEDs and screen; the script forgets them."""
        self.active = False
        self.leds = {}; self.sent_lines = [None] * 4; self.host_ok = None; self.host_flags = None; self.px_queue = []
        self.mode = 'play'; self.target = None; self.msg = None; self.used = set(); self.shift = False; self.shift_pads = set(); self.held = {}

    def fail(self):
        """An error in a callback (device_ExMachina.guarded): stand down for good. The device keeps its screen for the message (host mode SCREEN only, so
        the pads are its own again) and the script lets every MIDI message through to FL from now on."""
        self.broken = True
        try:
            if self.active and self.host_ok:
                self.sysex(out.host(t.HOST_SCREEN))
                for n, line in enumerate(('SCRIPT ERROR', 'SEE FL STUDIO:', 'VIEW > SCRIPT OUTPUT', 'PLAIN MIDI NOW')): self.sysex(out.text_line(n, line))
        except Exception: pass

    def deinit(self):
        if not self.active: return
        if self.host_ok: self.sysex(out.host(0))
        for led in list(self.leds): self.led(led, 0)

    def midi(self, ev):
        """OnMidiMsg: controls of the script are handled (FL does not see them), pads in a grid mode too; everything else goes on to FL.
        In Standalone mode (and until the device has said which mode it is in) nothing goes to FL: the controller is not FL's then."""
        if not self.active: ev.handled = True; return
        st = ev.status & 0xF0; ch = ev.status & 15
        if ch != t.CHANNEL: return
        if st == 0xB0:
            n = ev.data1; v = ev.data2
            if n == t.SHIFT_REPORT_CC: ev.handled = True; self.shift_btn(v > 0); return
            if n == t.ENC_CC: ev.handled = True; self.turn(v if v < 64 else v - 128); return
            if n == PUSH: ev.handled = True; self.push_btn(v > 0); return
            if n == TOUCH: ev.handled = True; (self.show_value() if v else None); return
            name = CC_NAME.get(n)
            if name and self.button(name, v > 0): ev.handled = True
        elif st in (0x80, 0x90):
            pad = NOTE_PAD.get(ev.data1); down = st == 0x90 and ev.data2 > 0
            if pad and (pad in self.shift_pads or (down and self.shift)):     # Shift + pad: the printed function; its release goes nowhere
                ev.handled = True
                if down: self.shift_pads.add(pad); self.shift_pad(pad)
                else: self.shift_pads.discard(pad)
                return
            if self.mode not in GRID: return
            ev.handled = True
            if not pad: return
            if down: self.pad(pad, ev.data2)
            else: self.pad_up(pad)

    def sysex(self, msg): call(device, 'midiOutSysex', bytes(msg))

    def on_sysex(self, ev):
        m = out.mode_msg(getattr(ev, 'sysex', b'') or b'')
        if m is not None:                                            # the answer to MODE, or the device switched (Shift + Project)
            ev.handled = True
            if m == 1 and not self.active: self.activate()
            elif m == 0 and self.active is not False: self.deactivate()
            return
        if not self.active: return
        r = out.is_host_reply(getattr(ev, 'sysex', b'') or b'')
        if r is None: return
        ev.handled = True
        if self.host_ok is None or not self.host_ok:
            self.host_ok = r[0]; self.sent_lines = [None] * 4; self.dirty = True
        self.host_flags = r[1]

    def idle(self):
        tm = now()
        if self.active is None and tm - self.mode_t > PROBE_S: self.activate()      # no answer to MODE: a firmware without modes, run as before
        if not self.active: return
        if self.host_ok is None and tm - self.probe_t > PROBE_S: self.host_ok = False; self.sent_lines = [None] * 4
        if self.msg and tm > self.msg_t: self.msg = None; self.dirty = True
        if self.dirty or (tm - self.refresh_t > PLAY_REFRESH_S and call(transport, 'isPlaying', default=False)): self.refresh()
        if self.host_ok is False and tm - self.px_drawn > PIXEL_REFRESH_S: self.sent_lines = [None] * 4; self.draw()
        if self.px_queue and tm - self.px_t >= REGION_S:
            self.sysex(self.px_queue.pop(0)); self.px_t = tm

    def beat_indicator(self, value): self.beat = value; self.dirty = True

    # ---- buttons --------------------------------------------------------------------------------------------------------------------------------
    def button(self, name, down):
        """True if the script uses this button (then FL does not see its CC)."""
        if not down: return name in self.used                      # (a release goes where its press went)
        if name == 'Play': transport.start()
        elif name == 'Stop': transport.stop()
        elif name == 'Rec': transport.record()
        elif name == 'Restart':
            call(transport, 'setSongPos', 0)
            if not call(transport, 'isPlaying', default=False): transport.start()
        elif name == 'Shift+Play':                                 # the Score Log: what was just played goes into the pattern
            call(general, 'dumpScoreLog', cfg.SCORE_LOG_SECONDS, False); self.message('SCORE LOG', 'TO ' + self.pattern_name())
        elif name == 'Shift+Rec':                                  # printed "Count-in"
            call(transport, 'globalTransport', midi.FPT_CountDown, 1); self.message('COUNT-IN', 'ON' if call(ui, 'isPrecountEnabled', default=False) else 'OFF')
        elif name == 'Shift+Restart':                              # printed "Loop": loop recording
            call(transport, 'globalTransport', midi.FPT_LoopRecord, 1); self.message('LOOP RECORD', 'ON' if call(ui, 'isLoopRecEnabled', default=False) else 'OFF')
        elif name == 'Shift+Solo': self.clear_mute_solo()
        elif name in ('Mute', 'Solo') and self.mode == 'group':  # the Mixer: mute / solo the selected insert
            tr = self.track()
            if name == 'Mute': call(mixer, 'muteTrack', tr); self.message('MUTE ' + str(call(mixer, 'getTrackName', tr, default='')), 'ON' if call(mixer, 'isTrackMuted', tr, default=False) else 'OFF')
            else: call(mixer, 'soloTrack', tr); self.message('SOLO ' + str(call(mixer, 'getTrackName', tr, default='')), 'ON' if call(mixer, 'isTrackSolo', tr, default=False) else 'OFF')
        elif name == 'Events' and self.mode == 'step':           # what the encoder edits on held steps
            self.step_param = (self.step_param + 1) % len(STEP_PARAMS); self.message('STEP EDIT', STEP_PARAMS[self.step_param][0])
        elif name == 'Tap': call(transport, 'globalTransport', midi.FPT_TapTempo, 1); self.message('TAP TEMPO', self.tempo_text())
        elif name == 'Shift+Tap':
            call(transport, 'globalTransport', midi.FPT_Metronome, 1)
            self.message('METRONOME', 'ON' if call(ui, 'isMetronomeEnabled', default=False) else 'OFF')
        elif name == 'Follow':
            call(transport, 'setLoopMode'); self.message('MODE', 'SONG' if call(transport, 'getLoopMode', default=0) else 'PATTERN')
        elif name == 'Shift+Left': call(general, 'undoUp'); self.message('UNDO', call(ui, 'getHintMsg', default='') or '')
        elif name == 'Shift+Right': call(general, 'undoDown'); self.message('REDO', call(ui, 'getHintMsg', default='') or '')
        elif name in ('Left', 'Right'): self.arrow(-1 if name == 'Left' else 1)
        elif name in MODE_BUTTON:
            m = MODE_BUTTON[name]; self.mode = 'play' if self.mode == m else m; self.held = {}; self.send_host()
            if self.mode != 'play': self.focus(midi.widMixer if self.mode == 'group' else midi.widChannelRack)
            self.message(MODE_TITLE[self.mode], self.mode_hint())
        elif name in TARGET_BUTTON:
            tg = TARGET_BUTTON[name]; self.target = None if self.target == tg else tg
            if self.target == 'browser': call(ui, 'showWindow', midi.widBrowser); call(ui, 'setFocused', midi.widBrowser)
            if self.target == 'plugin': self.param = self.next_param(self.param, 0)
            if self.target in ('plugin', 'preset') and cfg.FOCUS_WINDOWS: call(channels, 'showEditor', self.chan(), 1); call(channels, 'focusEditor', self.chan())
            elif self.target in ('volume', 'pan') and self.mode == 'group': self.focus(midi.widMixer)
            self.show_value()
        elif name == 'Shift+Browser': call(ui, 'hideWindow', midi.widBrowser); self.target = None if self.target == 'browser' else self.target
        elif name == 'Favorites': call(channels, 'showEditor', self.chan())
        elif name == 'Project':                                    # the Playlist and the Channel Rack in turn, shown and focused
            self.win = midi.widChannelRack if self.win == midi.widPlaylist else midi.widPlaylist
            call(ui, 'showWindow', self.win); call(ui, 'setFocused', self.win)
            self.message('WINDOW', 'CHANNEL RACK' if self.win == midi.widChannelRack else 'PLAYLIST')
        elif name in ('Duplicate', 'Shift+Pattern'):
            call(patterns, 'clonePattern'); self.message('DUPLICATE', self.pattern_name())
        elif name == 'Erase':
            if self.mode == 'step': self.clear_steps([self.chan()]); self.message('ERASE', self.chan_name())
        elif name == 'Shift+Erase':
            self.clear_steps(range(call(channels, 'channelCount', default=0))); self.message('ERASE', 'ALL CHANNELS')
        elif name == 'Shift+Encoder Push': self.reset_value()
        else: self.used.discard(name); return False
        self.used.add(name); self.dirty = True
        return True

    def arrow(self, d):
        if self.mode in GRID:
            n = self.pages(); self.page[self.mode] = max(0, min(n - 1, self.page[self.mode] + d))
            self.message(MODE_TITLE[self.mode], 'PAGE %d/%d' % (self.page[self.mode] + 1, n))
        elif self.target == 'plugin': self.param = self.next_param(self.param, d); self.show_value()
        elif self.target == 'browser': call(ui, 'left' if d < 0 else 'right')
        else:
            c = max(0, min(call(channels, 'channelCount', default=1) - 1, self.chan() + d))
            call(channels, 'selectOneChannel', c); self.message('CHANNEL', self.chan_name())

    def push_btn(self, down):
        self.push = down
        if not down: return
        if self.target == 'plugin': self.param = self.next_param(self.param, 1); self.show_value()
        elif self.target in (None, 'browser'): call(ui, 'enter')

    # ---- pads in a grid mode --------------------------------------------------------------------------------------------------------------------
    def pad(self, n, vel=100):
        i = self.page[self.mode] * 16 + n - 1
        if self.mode == 'step':                                    # a step: on at once (with the hit's velocity); an on step goes off when let go,
            c = self.chan()                                        # unless the encoder edited it while held
            if call(channels, 'getGridBit', c, i, default=False): self.held[i] = 'on'
            else:
                call(channels, 'setGridBit', c, i, 1); self.held[i] = 'new'
                if cfg.STEP_VELOCITY: self.set_step(c, i, 1, vel)
                self.message('STEP %d' % (i + 1), 'VELOCITY %d' % (vel if cfg.STEP_VELOCITY else 100))
        elif self.mode == 'pattern': call(patterns, 'jumpToPattern', i + 1); self.message('PATTERN', self.pattern_name())
        elif self.mode == 'group': call(mixer, 'setTrackNumber', i + 1); self.message('MIXER', call(mixer, 'getTrackName', i + 1, default=''))
        elif i < call(channels, 'channelCount', default=0):
            if self.mode == 'select': call(channels, 'selectOneChannel', i); self.message('CHANNEL', call(channels, 'getChannelName', i, default=''))
            elif self.mode == 'mute': call(channels, 'muteChannel', i)
            elif self.mode == 'solo': call(channels, 'soloChannel', i)
        self.dirty = True

    def pad_up(self, n):
        if self.mode != 'step': return
        i = self.page[self.mode] * 16 + n - 1; h = self.held.pop(i, None)
        if h == 'on': call(channels, 'setGridBit', self.chan(), i, 0); self.dirty = True

    def set_step(self, c, i, param, value):
        call(channels, 'setStepParameterByIndex', call(channels, 'getChannelIndex', c, default=c), call(patterns, 'patternNumber', default=1), i, param, value, True)

    def step_value(self, c, i, k):
        name, param, dflt, hi, inc = STEP_PARAMS[k]
        v = call(channels, 'getCurrentStepParam', c, i, param, default=-1)
        return dflt if v is None or v < 0 else v

    def edit_steps(self, d):
        """The encoder on held steps: the chosen step parameter of every held step, the graph editor on it."""
        c = self.chan(); k = self.step_param; name, param, dflt, hi, inc = STEP_PARAMS[k]
        if param == 7: hi = max(1, (call(mixer, 'getRecPPS', default=hi) or hi) - 1)     # (a shift stays within its step)
        for i in list(self.held):
            v = clamp(self.step_value(c, i, k) + d * inc, 0, hi); self.set_step(c, i, param, v); self.held[i] = 'edited'
        i0 = min(self.held)
        if cfg.GRAPH_EDITOR: call(channels, 'showGraphEditor', False, param, i0, call(channels, 'getChannelIndex', c, default=c), True)
        self.message('STEP %d %s' % (i0 + 1, name), self.step_text(k, self.step_value(c, i0, k)))

    def step_text(self, k, v):
        name = STEP_PARAMS[k][0]
        if name == 'PITCH': return out.note_name(v)
        if name == 'FINE PITCH': return '%+d CENTS' % ((v - 120) * 10)
        if name == 'PAN': return pan_text((v - 64) / 64.0)
        return str(v)

    def shift_btn(self, down):
        self.shift = down
        if down: self.msg = ('SHIFT PADS', '1 UNDO 2 REDO 5 QUANT'); self.msg_t = now() + 3600; self.dirty = True   # a help line while Shift is held
        elif self.msg and self.msg[0] == 'SHIFT PADS': self.msg = None; self.dirty = True

    def shift_pad(self, n):
        f = SHIFT_PAD.get(n); c = self.chan()
        if f == 'undo': call(general, 'undoUp'); self.message('UNDO', call(ui, 'getHintMsg', default='') or '')
        elif f == 'redo': call(general, 'undoDown'); self.message('REDO', call(ui, 'getHintMsg', default='') or '')
        elif f in ('quantize', 'quantize_starts'):
            call(channels, 'quickQuantize', c, 1 if f == 'quantize_starts' else 0); self.message('QUANTIZE' if f == 'quantize' else 'QUANTIZE STARTS', self.chan_name())
        elif f == 'clear': self.clear_steps([c]); self.message('CLEAR', self.chan_name())
        elif f in ('copy', 'paste'): call(transport, 'globalTransport', midi.FPT_Copy if f == 'copy' else midi.FPT_Paste, 1); self.message(f.upper(), '')
        self.dirty = True

    def clear_mute_solo(self):
        """Shift + Solo: every mute and solo off (the channels; in the Mixer the inserts)."""
        if self.mode == 'group':
            for tr in range(1, 126):
                if call(mixer, 'isTrackSolo', tr, default=False): call(mixer, 'soloTrack', tr, 0)
                if call(mixer, 'isTrackMuted', tr, default=False): call(mixer, 'muteTrack', tr, 0)
        else:
            for i in range(call(channels, 'channelCount', default=0) or 0):
                if call(channels, 'isChannelSolo', i, default=False): call(channels, 'soloChannel', i)
            for i in range(call(channels, 'channelCount', default=0) or 0):
                if call(channels, 'isChannelMuted', i, default=False): call(channels, 'muteChannel', i, 0)
        self.message('MUTE / SOLO', 'ALL CLEARED')

    def focus(self, wid):
        if cfg.FOCUS_WINDOWS: call(ui, 'showWindow', wid); call(ui, 'setFocused', wid)

    def mode_hint(self):
        return {'step': 'HOLD STEP + ENCODER', 'select': 'PAD = CHANNEL', 'mute': 'PAD = MUTE', 'solo': 'PAD = SOLO', 'pattern': 'PAD = PATTERN',
                'group': 'PAD = MIXER INSERT', 'play': self.chan_name()}.get(self.mode, '')

    def pages(self):
        if self.mode == 'step': return max(1, (self.steps() + 15) // 16)
        if self.mode == 'pattern': return max(1, min(64, (call(patterns, 'patternCount', default=1) + 16) // 16))
        if self.mode == 'group': return 8
        return max(1, (call(channels, 'channelCount', default=1) + 15) // 16)

    def steps(self):
        beats = call(patterns, 'getPatternLength', call(patterns, 'patternNumber', default=1), default=0) or 0
        return max(16, int(beats) * 4)

    def clear_steps(self, chans):
        for c in chans:
            for i in range(self.steps()): call(channels, 'setGridBit', c, i, 0)

    # ---- the encoder ----------------------------------------------------------------------------------------------------------------------------
    def turn(self, d):
        if self.mode == 'step' and self.held: self.edit_steps(d); return
        tg, fine = self.target, self.push
        c = self.chan()
        if tg is None: call(ui, 'jog', d)
        elif tg == 'volume':
            if self.mode == 'group': tr = self.track(); call(mixer, 'setTrackVolume', tr, clamp(call(mixer, 'getTrackVolume', tr, default=0.8) + d * (0.002 if fine else 0.01), 0, 1))
            else: call(channels, 'setChannelVolume', c, clamp(call(channels, 'getChannelVolume', c, default=0.78) + d * (0.002 if fine else 0.01), 0, 1))
        elif tg == 'pan':
            if self.mode == 'group': tr = self.track(); call(mixer, 'setTrackPan', tr, clamp(call(mixer, 'getTrackPan', tr, default=0) + d * (0.005 if fine else 0.02), -1, 1))
            else: call(channels, 'setChannelPan', c, clamp(call(channels, 'getChannelPan', c, default=0) + d * (0.005 if fine else 0.02), -1, 1))
        elif tg == 'tempo': call(transport, 'globalTransport', midi.FPT_TempoJog, d * (1 if fine else 10))
        elif tg == 'swing':
            mod = swing_module()
            if mod:
                v = call(mod, 'get_swing', default=0)
                if isinstance(v, float) and v <= 1.0: call(mod, 'set_swing', clamp(v + d * (0.002 if fine else 0.01), 0.0, 1.0))
                else: call(mod, 'set_swing', int(clamp((v or 0) + d, 0, 128)))
        elif tg == 'plugin':
            if call(plugins, 'isValid', c, default=False):
                p = self.param; v = call(plugins, 'getParamValue', p, c, default=0.0)
                call(plugins, 'setParamValue', clamp(v + d / (1024.0 if fine else 128.0), 0.0, 1.0), p, c)
        elif tg == 'preset':
            if call(plugins, 'isValid', c, default=False): call(plugins, 'nextPreset' if d > 0 else 'prevPreset', c)
        elif tg == 'browser':
            for _ in range(min(abs(d), 8)): call(ui, 'next' if d > 0 else 'previous')
        elif tg == 'length':
            if not has(patterns, 'setPatternLength'): self.message('LENGTH', 'NEEDS FL STUDIO 2026'); return
            pat = call(patterns, 'patternNumber', default=1)
            call(patterns, 'setPatternLength', pat, max(1, int(call(patterns, 'getPatternLength', pat, default=4) or 4) + d * (1 if fine else 4)))
        self.show_value()

    def reset_value(self):
        c = self.chan(); tg = self.target
        if tg == 'volume': (call(mixer, 'setTrackVolume', self.track(), 0.8) if self.mode == 'group' else call(channels, 'setChannelVolume', c, 0.78))
        elif tg == 'pan': (call(mixer, 'setTrackPan', self.track(), 0.0) if self.mode == 'group' else call(channels, 'setChannelPan', c, 0.0))
        self.show_value()

    def next_param(self, p, d):
        """The next parameter with a name (VST plug-ins list thousands, most of them empty), d = 0: p itself if it has one."""
        c = self.chan(); n = call(plugins, 'getParamCount', c, default=0) or 0
        if not n: return 0
        for k in range(n if d else n + 1):
            q = (p + (k + 1) * d if d else p + k) % n
            if call(plugins, 'getParamName', q, c, default=''): return q
        return p

    # ---- what the screen and the LEDs show ------------------------------------------------------------------------------------------------------
    def chan(self): return call(channels, 'selectedChannel', default=0) or 0
    def chan_name(self): return call(channels, 'getChannelName', self.chan(), default='') or ''
    def track(self): return call(mixer, 'trackNumber', default=0) or 0
    def pattern_name(self): return call(patterns, 'getPatternName', call(patterns, 'patternNumber', default=1), default='') or ''
    def tempo_text(self):
        v = call(mixer, 'getCurrentTempo', default=None)
        return '%.1f BPM' % v if isinstance(v, (int, float)) and v < 1000 else ('%.1f BPM' % (v / 1000.0) if v else '')

    def value_lines(self):
        c = self.chan(); tg = self.target
        if tg == 'volume':
            if self.mode == 'group': tr = self.track(); return 'VOL ' + str(call(mixer, 'getTrackName', tr, default='')), '%d%%' % round(100 * call(mixer, 'getTrackVolume', tr, default=0))
            return 'VOL ' + self.chan_name(), '%d%%' % round(100 * call(channels, 'getChannelVolume', c, default=0))
        if tg == 'pan':
            v = call(mixer, 'getTrackPan', self.track(), default=0) if self.mode == 'group' else call(channels, 'getChannelPan', c, default=0)
            return 'PAN ' + (call(mixer, 'getTrackName', self.track(), default='') if self.mode == 'group' else self.chan_name()), pan_text(v)
        if tg == 'tempo': return 'TEMPO', self.tempo_text()
        if tg == 'swing':
            mod = swing_module()
            return ('SWING', str(call(mod, 'get_swing', default=''))) if mod else ('SWING', 'NEEDS FL STUDIO 2026')
        if tg in ('plugin', 'preset'):
            if not call(plugins, 'isValid', c, default=False): return 'PLUG-IN', 'NONE ON THIS CHANNEL'
            if tg == 'preset': return call(plugins, 'getPluginName', c, default=''), 'PRESET ' + str(call(plugins, 'getName', c, -1, 6, 0, default='') or '')
            return call(plugins, 'getParamName', self.param, c, default=''), call(plugins, 'getParamValueString', self.param, c, default='') or '%d%%' % round(100 * call(plugins, 'getParamValue', self.param, c, default=0))
        if tg == 'browser': return 'BROWSER', call(ui, 'getHintMsg', default='') or ''
        if tg == 'length': return 'LENGTH', '%s BEATS' % call(patterns, 'getPatternLength', call(patterns, 'patternNumber', default=1), default='?')
        return 'JOG', call(ui, 'getHintMsg', default='') or ''

    def show_value(self):
        a, b = self.value_lines(); self.message(a, b)

    def message(self, a, b=''):
        self.msg = (str(a), str(b)); self.msg_t = now() + MSG_S; self.dirty = True
        if cfg.HINT_BAR: call(ui, 'setHintMsg', ('%s: %s' % (a, b)) if b else str(a))

    def screen(self):
        pn = call(patterns, 'patternNumber', default=1)
        play = 'PLAY' if call(transport, 'isPlaying', default=False) else 'STOP'
        if call(transport, 'isRecording', default=False): play = 'REC'
        title = MODE_TITLE[self.mode]
        if self.mode in GRID: title += ' %d/%d' % (self.page[self.mode] + 1, self.pages())
        if self.target: title = (title + ' ' * 21)[:13] + self.target.upper()[:8]
        l1, l2 = self.msg if self.msg else (self.chan_name(), 'PAT %d %s' % (pn, self.pattern_name()))
        return [title, l1, l2, (self.tempo_text() + ' ' * 21)[:16] + play.rjust(5)]

    def pad_leds(self):
        """The 16 pad LEDs of the current mode (pad 1..16 -> code)."""
        m = self.mode; base = self.page.get(m, 0) * 16; cols = {}
        n_ch = call(channels, 'channelCount', default=0) or 0
        sel = self.chan()
        for p in range(1, 17):
            i = base + p - 1; v = 0
            if m == 'play':
                c = self.chan()
                if call(plugins, 'getPluginName', c, default='') == 'FPC':
                    v = out.code(out.nearest(call(plugins, 'getPadInfo', c, -1, 2, p - 1, default=0) or 0), 2)
                else: v = out.code(out.nearest(call(channels, 'getChannelColor', c, default=0) or 0), 1)
            elif m in ('select', 'mute', 'solo'):
                if i < n_ch:
                    col = out.nearest(call(channels, 'getChannelColor', i, default=0) or 0)
                    if m == 'select': v = out.code(col, 3 if i == sel else 1)
                    elif m == 'mute': v = out.code(col, 0 if call(channels, 'isChannelMuted', i, default=False) else 2)
                    else: v = out.code(col, 3 if call(channels, 'isChannelSolo', i, default=False) else 0)
            elif m == 'pattern':
                cnt = call(patterns, 'patternCount', default=0) or 0; cur = call(patterns, 'patternNumber', default=1)
                if i + 1 <= cnt: v = out.code(out.nearest(call(patterns, 'getPatternColor', i + 1, default=0) or 0), 3 if i + 1 == cur else 1)
                elif i + 1 == cnt + 1: v = out.code(out.WHITE, 0)
            elif m == 'group':
                v = out.code(out.nearest(call(mixer, 'getTrackColor', i + 1, default=0) or 0), 3 if i + 1 == self.track() else 1)
            elif m == 'step':
                on = call(channels, 'getGridBit', sel, i, default=False); col = out.nearest(call(channels, 'getChannelColor', sel, default=0) or 0)
                v = out.code(col, 3) if on else (out.code(out.WHITE, 0) if i % 4 == 0 else out.code(col, 0))   # on bright, off dim, every 4th step dim white
                if i == self.playhead() or i in self.held: v = out.code(out.WHITE, 3)
            cols[p] = v
        return cols

    def playhead(self):
        if not call(transport, 'isPlaying', default=False): return -1
        v = call(mixer, 'getSongStepPos', default=-1)
        return int(v) % max(16, self.steps()) if isinstance(v, (int, float)) and v >= 0 else -1

    def button_leds(self):
        on, dim = 0x7F, 0x7C
        L = {}
        lit = lambda name, cond: L.__setitem__(name, on if cond else dim)
        lit('Play', call(transport, 'isPlaying', default=False)); lit('Rec', call(transport, 'isRecording', default=False)); lit('Stop', False)
        lit('Restart', False); lit('Tap', self.beat in (1, 2)); lit('Follow', call(transport, 'getLoopMode', default=0) == 1)
        for b, m in MODE_BUTTON.items(): lit(b, self.mode == m)
        for b, tg in TARGET_BUTTON.items():
            if not b.startswith('Shift+'): lit(b, self.target == tg)
        for b in ('Favorites', 'Duplicate', 'Erase'): lit(b, False)
        lo, hi = self.can_move()
        L['Left'] = dim if lo else 0; L['Right'] = dim if hi else 0                 # the arrows are dark where they cannot go
        return {t.BUTTON_LED[n]: v for n, v in L.items() if n in t.BUTTON_LED}

    def can_move(self):
        if self.mode in GRID: return self.page[self.mode] > 0, self.page[self.mode] < self.pages() - 1
        if self.target in ('plugin', 'browser'): return True, True
        c = self.chan(); return c > 0, c < (call(channels, 'channelCount', default=1) or 1) - 1

    def strip_leds(self):
        """The 25 strip LEDs: the encoder target's value as a bar (pan from the centre), else the song position while FL plays."""
        n = t.STRIP_LEDS; bar = [0] * n
        if not cfg.STRIP_BAR: return {}
        v = self.target_fraction()
        if v is not None:
            col = STRIP_COLOUR.get(self.target, 17)
            if self.target == 'pan':
                mid = n // 2; end = int(round(mid + v * mid))
                for k in range(min(mid, end), max(mid, end) + 1): bar[k] = out.code(col, 2)
            else:
                for k in range(int(round(v * n))): bar[k] = out.code(col, 2)
        elif call(transport, 'isPlaying', default=False):
            pos = call(transport, 'getSongPos', default=0) or 0
            bar[min(n - 1, int(pos * n))] = out.code(out.WHITE, 2)
        return {t.STRIP_LED0 + k: bar[k] for k in range(n)}

    def target_fraction(self):
        """The encoder target's value as 0..1 (pan: -1..1), or None."""
        c = self.chan(); tg = self.target; g = self.mode == 'group'
        if tg == 'volume': return call(mixer, 'getTrackVolume', self.track(), default=0) if g else call(channels, 'getChannelVolume', c, default=0)
        if tg == 'pan': return call(mixer, 'getTrackPan', self.track(), default=0) if g else call(channels, 'getChannelPan', c, default=0)
        if tg == 'tempo':
            v = call(mixer, 'getCurrentTempo', default=None)
            if isinstance(v, (int, float)): v = v / 1000.0 if v >= 1000 else v; return clamp((v - 10) / 512.0, 0, 1)
        if tg == 'plugin' and call(plugins, 'isValid', c, default=False): return call(plugins, 'getParamValue', self.param, c, default=0)
        return None

    def refresh(self, full=False):
        if not self.active: return
        self.dirty = False; self.refresh_t = now()
        if full: self.leds = {}
        want = {t.PAD_LED[p]: v for p, v in self.pad_leds().items()}
        want.update(self.button_leds()); want.update(self.strip_leds())
        for led, v in sorted(want.items()):
            if self.leds.get(led) != v: self.led(led, v)
        self.lines = self.screen()
        self.draw()

    def led(self, led, v):
        st, d1, d2 = out.led_msg(led, v)
        call(device, 'midiOutMsg', st | (d1 << 8) | (d2 << 16)); self.leds[led] = v

    def draw(self):
        if self.host_ok is None: return                              # (waiting for the answer to HOST)
        lines = [out.clean(x) for x in self.lines]
        if self.host_ok:
            for n in range(4):
                if self.sent_lines[n] != lines[n]: self.sysex(out.text_line(n, lines[n])); self.sent_lines[n] = lines[n]
        elif lines != self.sent_lines:
            changed = [h for h in (0, 1) if lines[2 * h:2 * h + 2] != self.sent_lines[2 * h:2 * h + 2]]
            self.px_queue = [m for h in changed for m in out.regions(lines, h)]
            self.sent_lines = lines; self.px_drawn = now()

    def send_host(self):
        """Host mode: our text on the screen, and the pads as a grid while a grid mode is on (else they play whatever the device's mode is)."""
        f = t.HOST_SCREEN | (t.HOST_RAW if self.mode in GRID else 0)
        if self.host_ok is False or f == self.host_flags: return
        self.sysex(out.host(f)); self.host_flags = f              # (the answer confirms it)

def clamp(v, lo, hi): return lo if v < lo else hi if v > hi else v
def pan_text(v):
    p = int(round(abs(v) * 100))
    return 'CENTRE' if p == 0 else ('%d%% LEFT' % p if v < 0 else '%d%% RIGHT' % p)
def swing_module():
    for mod in (transport, patterns, channels, mixer, general):
        if has(mod, 'set_swing') and has(mod, 'get_swing'): return mod
    return None
