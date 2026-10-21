"""A stand-in for FL Studio's MIDI scripting modules (channels, patterns, mixer, transport, plugins, ui, general, device, midi), for testing the
Ex-Machina script without FL Studio. A small project (channels with step grids and plug-ins, patterns, mixer tracks, the transport) answers the
functions the script calls, with the signatures of FL's API reference (https://il-group.github.io/FL-Studio-API-Stubs/); every call is logged.
install() puts the modules into sys.modules, so `import channels` in the script gets them. Swing is offered as transport.get_swing / set_swing
(FL Studio 2026 added the functions; where they live is not documented yet, the script looks for them), install(fl2026=False) leaves them out."""
import sys, types

class Project:
    def __init__(self):
        self.ch = [dict(name=n, color=c, vol=0.78, pan=0.0, mute=False, solo=False, grid=set(), plugin=p, params=[], fpc=[])
                   for n, c, p in (('Kick', 0xFF3030, 'FPC'), ('Clap', 0x30FF30, 'Sampler'), ('Hat', 0x3030FF, 'Sampler'), ('Bass', 0xFFFF00, '3x Osc'))]
        self.ch[0]['fpc'] = [(36 + i, 0x0000FF if i % 2 else 0x00FF00) for i in range(16)]
        self.ch[3]['params'] = [['Osc 1 coarse', 0.5], ['', 0.0], ['Osc 2 coarse', 0.25], ['Osc 3 coarse', 0.75]]
        self.ch[3]['presets'] = 0
        self.sel = 0
        self.pat = [dict(name='Pattern 1', color=0xFF8000, length=4), dict(name='Pattern 2', color=0x8000FF, length=4)]
        self.cur = 1
        self.tracks = [dict(name='Master' if i == 0 else 'Insert %d' % i, color=0x808080 if i == 0 else 0xFF0000 + i, vol=0.8, pan=0.0) for i in range(126)]
        self.track = 1
        self.playing = self.recording = False; self.loop = 0; self.pos = 0; self.step = 0
        self.tempo = 140.0; self.metronome = False; self.swing = 0
        self.hint = ''; self.log = []; self.out = []; self.windows = set()

P = None

def _mod(name, **fns):
    m = types.ModuleType(name)
    for k, f in fns.items(): setattr(m, k, f)
    return m

def install(fl2026=True):
    global P
    P = Project()
    log = lambda *a: P.log.append(a)
    C = lambda i: P.ch[i]
    def setgrid(i, pos, v, g=False):
        log('setGridBit', i, pos, v); (C(i)['grid'].add if v else C(i)['grid'].discard)(pos)
    def mute(i, value=-1, g=False): C(i)['mute'] = (not C(i)['mute']) if value == -1 else bool(value); log('muteChannel', i)
    def solo(i, g=False):
        on = not C(i)['solo']
        for c in P.ch: c['solo'] = False
        C(i)['solo'] = on; log('soloChannel', i)
    def sel1(i, g=False): P.sel = i; log('selectOneChannel', i)
    def setvol(i, v, pick=0, g=False): C(i)['vol'] = v; log('setChannelVolume', i, v)
    def setpan(i, v, pick=0, g=False): C(i)['pan'] = v; log('setChannelPan', i, v)
    channels = _mod('channels', selectedChannel=lambda canBeNone=False, offset=0, g=False: P.sel, channelCount=lambda g=False: len(P.ch),
                    getChannelName=lambda i, g=False: C(i)['name'], getChannelColor=lambda i, g=False: C(i)['color'],
                    isChannelMuted=lambda i, g=False: C(i)['mute'], muteChannel=mute, isChannelSolo=lambda i, g=False: C(i)['solo'], soloChannel=solo,
                    selectOneChannel=sel1, getChannelVolume=lambda i, mode=False, g=False: C(i)['vol'], setChannelVolume=setvol,
                    getChannelPan=lambda i, g=False: C(i)['pan'], setChannelPan=setpan,
                    getGridBit=lambda i, pos, g=False: pos in C(i)['grid'], setGridBit=setgrid, showEditor=lambda i, v=-1: log('showEditor', i))
    def jump(i): log('jumpToPattern', i); P.cur = i; (P.pat.append(dict(name='Pattern %d' % i, color=0x5F748B, length=4)) if i == len(P.pat) + 1 else None)
    def clone(index=None): log('clonePattern', index); P.pat.append(dict(P.pat[P.cur - 1])); P.cur = len(P.pat)
    pat_fns = dict(patternNumber=lambda: P.cur, patternCount=lambda: len(P.pat), patternMax=lambda: 999, getPatternName=lambda i: P.pat[i - 1]['name'],
                   getPatternColor=lambda i: P.pat[i - 1]['color'], getPatternLength=lambda i: P.pat[i - 1]['length'], jumpToPattern=jump, clonePattern=clone)
    if fl2026:
        def setlen(i, n): log('setPatternLength', i, n); P.pat[i - 1]['length'] = n
        pat_fns['setPatternLength'] = setlen
    patterns = _mod('patterns', **pat_fns)
    T = lambda i: P.tracks[i]
    def settv(i, v, pick=0): T(i)['vol'] = v; log('setTrackVolume', i, v)
    def settp(i, v, pick=0): T(i)['pan'] = v; log('setTrackPan', i, v)
    def settn(i, flags=0): P.track = i; log('setTrackNumber', i)
    mixer = _mod('mixer', trackNumber=lambda: P.track, setTrackNumber=settn, getTrackName=lambda i: T(i)['name'], getTrackColor=lambda i: T(i)['color'],
                 getTrackVolume=lambda i, mode=0: T(i)['vol'], setTrackVolume=settv, getTrackPan=lambda i: T(i)['pan'], setTrackPan=settp,
                 getCurrentTempo=lambda asInt=False: int(P.tempo * 1000) if asInt else P.tempo, getSongStepPos=lambda: P.step)
    def gt(cmd, value, pme=0, flags=0):
        log('globalTransport', cmd, value)
        if cmd == FPT_Metronome: P.metronome = not P.metronome
        if cmd == FPT_TempoJog: P.tempo += value / 10.0
        return 1
    def start(): P.playing = not P.playing; log('start')
    def stop(): P.playing = False; P.pos = 0; log('stop')
    def record(): P.recording = not P.recording; log('record')
    def setpos(p, mode=-1): P.pos = p; log('setSongPos', p)
    def setloop(): P.loop ^= 1; log('setLoopMode')
    tr = dict(start=start, stop=stop, record=record, isPlaying=lambda: P.playing, isRecording=lambda: P.recording, setSongPos=setpos,
              getSongPos=lambda mode=-1: P.pos, globalTransport=gt, getLoopMode=lambda: P.loop, setLoopMode=setloop)
    if fl2026:
        def setsw(v): P.swing = v; log('set_swing', v)
        tr.update(get_swing=lambda: P.swing, set_swing=setsw)
    transport = _mod('transport', **tr)
    def params(i): return C(i)['params']
    def setparam(v, p, i, slot=-1, pick=0, g=False): params(i)[p][1] = v; log('setParamValue', v, p, i)
    def nextp(i, slot=-1, g=False): C(i)['presets'] = C(i).get('presets', 0) + 1; log('nextPreset', i)
    def prevp(i, slot=-1, g=False): C(i)['presets'] = C(i).get('presets', 0) - 1; log('prevPreset', i)
    def padinfo(i, slot=-1, opt=0, idx=-1):
        f = C(i)['fpc']
        return len(f) if opt == 0 else f[idx][0] if opt == 1 else f[idx][1]
    plugins = _mod('plugins', isValid=lambda i, slot=-1, g=False: C(i)['plugin'] is not None, getPluginName=lambda i, slot=-1, user=False, g=False: C(i)['plugin'],
                   getParamCount=lambda i, slot=-1, g=False: len(params(i)), getParamName=lambda p, i, slot=-1, g=False: params(i)[p][0],
                   getParamValue=lambda p, i, slot=-1, g=False: params(i)[p][1], setParamValue=setparam,
                   getParamValueString=lambda p, i, slot=-1, pick=0, g=False: '%d st' % round(params(i)[p][1] * 48 - 24),
                   nextPreset=nextp, prevPreset=prevp, getPadInfo=padinfo, getName=lambda i, slot=-1, flag=0, p=0, g=False: 'Preset %d' % C(i).get('presets', 0))
    def win(name): return lambda *a: log(name, *a)
    ui = _mod('ui', jog=win('jog'), next=win('next'), previous=win('previous'), enter=win('enter'), left=win('left'), right=win('right'),
              showWindow=lambda w: (P.windows.add(w), log('showWindow', w)), hideWindow=lambda w: (P.windows.discard(w), log('hideWindow', w)),
              setFocused=win('setFocused'), getHintMsg=lambda: P.hint, isMetronomeEnabled=lambda: P.metronome)
    general = _mod('general', undoUp=win('undoUp'), undoDown=win('undoDown'), getVersion=lambda: 40)
    device = _mod('device', midiOutMsg=lambda m, *a: P.out.append(('msg', m)), midiOutSysex=lambda b: P.out.append(('sysex', bytes(b))),
                  isAssigned=lambda: True, getName=lambda: 'Maschine Mikro MK3')
    midi = _mod('midi', FPT_TapTempo=106, FPT_Metronome=110, FPT_TempoJog=105, widMixer=0, widChannelRack=1, widPlaylist=2, widPianoRoll=3, widBrowser=4, widPlugin=5)
    for m in (channels, patterns, mixer, transport, plugins, ui, general, device, midi): sys.modules[m.__name__] = m
    return P

FPT_TapTempo, FPT_Metronome, FPT_TempoJog = 106, 110, 105

class Event:
    """FL's event object, as far as the script reads it."""
    def __init__(self, status, data1=0, data2=0, sysex=b''):
        self.status, self.data1, self.data2, self.sysex, self.handled = status, data1, data2, bytes(sysex), False
