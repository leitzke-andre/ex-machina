"""Host mode in the emulator (generation 11, for DAW scripts such as the FL Studio one in integrations/fl_studio): SysEx 20 HOST sets who owns the screen
and the pads, SysEx 21 TEXT puts text lines on the screen. Checks the reply, the host's picture pixel by pixel (computed independently of the firmware's
renderer), the firmware's own messages on top of it (and their absence with QUIET), the raw grid notes whatever the pad mode, the release of held notes
when the meaning of the pads changes, the end of host mode with SET / RESET / a slot load, and TEXT arriving in the middle of a screen write.
Usage: test_host.py <patched.bin> <data_init.bin>"""
import os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', 'emu'))
import mmk3_config as mc
import devsim, dispsim
from devsim import report1, report2
from dispsim import reference, idle, Screen, MS16

fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

B = {n: i for i, n in enumerate(mc.BUTTON_NAMES)}
PADIDX = {n: mc.PAD_LABEL.index(n) for n in range(1, 17)}
FL = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'fl-studio')
MODES = next(p['cfg'] for p in mc.builtin_presets() if p['id'] == 'maschine-modes')
BLANK = bytes([0xFF]) * 512

def host_picture(lines):
    """The host's text: line n on rows 8n..8n+6, 6-pixel cells from x = 1 (21 characters)."""
    lit = set()
    for n, t in enumerate(lines): dispsim._text(lit, t, 1, 8 * n)
    return dispsim._pack(lit)

class T:
    def __init__(self, c=FL):
        self.d = devsim.Dev(fw, data, c)
        self.d.translate(report1()); self.d.start()
        self.sc = Screen(self.d); self.sc.settle()
    def host(self, flags):
        r = self.d.ask(mc.host_request(flags)); return mc.parse_reply(r[0]) if r else None
    def text(self, line, t, col=0): self.d.send_sysex(mc.text_request(line, t, col))
    def press(self, *names): return self.d.translate(report1([B[n] for n in names]))
    def release(self): return self.d.translate(report1())
    def tap(self, *names): a = self.press(*names); return a, self.release()
    def hit(self, pad, val=3000): return self.d.translate(report2([(PADIDX[pad], 1, val)]))
    def lift(self, pad): return self.d.translate(report2([(PADIDX[pad], 3, 0)]))
    def notes_on(self, out): return [m[2] for m in out if m[0] == 0x09]
    def notes_off(self, out): return [m[2] for m in out if m[0] == 0x08]
    def note(self, pad):
        on = self.notes_on(self.hit(pad)); self.lift(pad); return on[0] if on else None

# ---- HOST: the reply ------------------------------------------------------------------------------------------------------------------------------
x = T()
r = x.host(mc.HOST_SCREEN | mc.HOST_RAW)
check('HOST 3 is answered: 60 status 0, flags 3', (r['cmd'], r['status'], r['host']), (mc.CMD_HOST, 0, 3))
r = x.host(9)
check('HOST with an unknown flag is refused (status 1), the flags stay', (r['status'], r['host']), (1, 3))
r = mc.parse_reply(x.d.ask(mc.message(mc.CMD_HOST))[0])
check('HOST without its byte is refused (status 1)', (r['status'], r['host']), (1, 3))
r = x.host(0); check('HOST 0 ends it', (r['status'], r['host']), (0, 0))
x.sc.settle(); check('... and the idle screen is back', x.sc.fb() == idle('DRUMS CH1 120'))

# ---- the screen -----------------------------------------------------------------------------------------------------------------------------------
x = T()
check('before host mode: the idle screen', x.sc.fb() == idle('DRUMS CH1 120'))
x.host(mc.HOST_SCREEN); x.sc.settle()
check('HOST screen: the picture starts blank', x.sc.fb() == BLANK)
lines = ['FL STUDIO   PATTERN 1', 'Kick', 'STEP 1-16', '128 BPM  PLAY']
for n, t in enumerate(lines): x.text(n, t.ljust(21))
x.sc.settle()
check('four TEXT lines are drawn, pixel by pixel', x.sc.fb() == host_picture(lines))
x.text(1, 'Snare'); x.sc.settle()
check('TEXT replaces only the characters it carries (line 2 = "Snare" over "Kick")', x.sc.fb() == host_picture([lines[0], 'Snare', lines[2], lines[3]]))
x.text(2, 'ABCDEFG', col=18); x.sc.settle()
check('TEXT from column 18 keeps to the line (3 characters)', x.sc.fb() == host_picture([lines[0], 'Snare', 'STEP 1-16'.ljust(18) + 'ABC', lines[3]]))
x.text(None, ''); x.sc.settle()
check('TEXT 7F: all four lines blank', x.sc.fb() == BLANK)
x.text(0, 'lower case'); x.sc.settle()
check('lower case shows as capitals (the font has none)', x.sc.fb() == host_picture(['LOWER CASE']))
before = x.sc.regions; x.sc.run(50, 10)
check('nothing changes: no region is sent again', x.sc.regions, before)
x.text(0, 'LOWER CASE'); x.sc.settle()
check('the same text again: drawn again (TEXT always redraws), the picture is the same', (x.sc.regions > before, x.sc.fb() == host_picture(['LOWER CASE'])), (True, True))

x = T(); x.host(mc.HOST_SCREEN); x.text(0, 'HOST'); x.sc.settle()
x.tap('Keyboard'); x.sc.run(6, 10)
check('a message of the firmware (Keyboard) still shows over the host\'s picture', x.sc.fb() == reference('KEYBOARD', 'C3-D#4'))
x.sc.settle()
check('... and then the host\'s text comes back, not the idle screen', x.sc.fb() == host_picture(['HOST']))
x.press('Shift', 'Keyboard'); x.release(); x.sc.settle()
check('... also after a scale change (the status line of the idle screen would have changed)', x.sc.fb() == host_picture(['HOST']))
x.host(mc.HOST_SCREEN | mc.HOST_QUIET); x.sc.settle(); x.text(0, 'QUIET'); x.sc.settle()
regions = x.sc.regions; x.tap('Pad Mode'); x.sc.run(6, 10)
check('QUIET: no message of the firmware, the host\'s text stays', (x.sc.fb() == host_picture(['QUIET']), x.sc.regions), (True, regions))
x.host(mc.HOST_SCREEN); x.sc.settle()
check('the text survives a change of the other flags', x.sc.fb() == host_picture(['QUIET']))
x.host(0); x.sc.settle(); x.host(mc.HOST_SCREEN); x.sc.settle()
check('entering host mode again starts blank', x.sc.fb() == BLANK)
x = T(); x.text(0, 'EARLY'); x.sc.settle()
check('TEXT without host mode: stored, the idle screen stays', x.sc.fb() == idle('DRUMS CH1 120'))

# ---- raw pads ---------------------------------------------------------------------------------------------------------------------------------------
x = T(); x.tap('Keyboard')
check('Keyboard mode: pad 1 = C3 (60)', x.note(1), 60)
x.host(mc.HOST_RAW)
check('HOST raw: pad 1 = 36, pad 16 = 51, whatever the pad mode', (x.note(1), x.note(16)), (36, 51))
check('... every pad: 36 + its number - 1', [x.note(n) for n in range(1, 17)], list(range(36, 52)))
out = x.hit(5); off = x.lift(5)
check('a hit sends Note On 40 on channel 1, the release Note Off 40', ([m for m in out if m[0] == 9], x.notes_off(off)), ([(0x09, 0x90, 40, out[0][3])], [40]))
check('... with a velocity from the curve (not 0)', 0 < out[0][3] <= 127)
x.host(0)
check('raw off: Keyboard mode again (pad 1 = 60)', x.note(1), 60)
x = T(); x.hit(3); held = x.d.translate(report1())
r = x.d.ask(mc.host_request(mc.HOST_RAW))
offs = [m for b in x.d.all_sent for m in (tuple(b[k:k + 4]) for k in range(0, len(b), 4)) if m[0] == 0x08]
check('a pad held while raw comes on is released at once (Note Off 38)', [m[2] for m in offs], [38])
check('... and its later release sends nothing', x.notes_off(x.lift(3)), [])
x.hit(2); x.d.all_sent.clear(); x.d.ask(mc.host_request(0))
offs = [m for b in x.d.all_sent for m in (tuple(b[k:k + 4]) for k in range(0, len(b), 4)) if m[0] == 0x08]
check('a grid note held while raw goes off is released at once (Note Off 37)', [m[2] for m in offs], [37])
check('... and its later release sends nothing', x.notes_off(x.lift(2)), [])
x = T(MODES); x.tap('Mute'); x.hit(1); x.lift(1); x.tap('Mute')
check('mute pads (Maschine-like modes): pad 1 is silent', x.note(1), None)
x.host(mc.HOST_RAW)
check('... raw: a muted pad still sends its grid note', x.note(1), 36)
x.host(0); x.tap('Note Repeat'); x.host(mc.HOST_RAW)
check('... with the arp on: the grid note goes out at once (not through the arp)', x.note(2), 37)
x.host(0); x.tap('Note Repeat'); x.tap('Step'); x.host(mc.HOST_RAW)
check('... in the step sequencer\'s edit mode: the grid note, no step toggled', x.note(4), 39)

# ---- the end of host mode ------------------------------------------------------------------------------------------------------------------------------
def ended(x): x.sc.settle(); return x.sc.fb() == idle('DRUMS CH1 120') and x.note(1) == 36
x = T(); x.tap('Keyboard'); x.host(7); x.d.ask(mc.set_request(FL))
check('a SET from the host ends host mode (idle screen, pads in Pad Mode)', ended(x))
x = T(); x.host(3); r = mc.parse_reply(x.d.ask(mc.set_request(FL[:4] + b'\x77' + FL[5:]))[0])
x.sc.settle(); check('a refused SET leaves it on', (r['status'], x.sc.fb() == BLANK, x.note(1)), (2, True, 36))
x = T(); x.host(3); x.d.ask(mc.reset_request()); x.tap('Keyboard'); x.tap('Pad Mode')
check('RESET ends it', ended(x))
x = T(); x.d.ask(mc.slot_store_request(0)); x.host(3); x.d.ask(mc.slot_load_request(0))
check('a slot load from the host ends it', ended(x))
x = T(); x.host(3); r = mc.parse_reply(x.d.ask(mc.slot_load_request(2))[0]); x.sc.settle()
check('a slot load that fails (empty slot) leaves it on', (r['status'], x.sc.fb() == BLANK), (4, True))
x = T(); x.d.ask(mc.slot_store_request(0)); x.host(1); x.text(0, 'STAYS'); x.tap('Project'); x.sc.settle()
check('the Project button\'s slot change does not end it (the script is still there)', x.sc.fb() == host_picture(['STAYS']))

# ---- TEXT in the middle of a screen write -----------------------------------------------------------------------------------------------------------
fails, points = [], 0
for after in range(5, 4000, 37):
    x = T(); x.host(mc.HOST_SCREEN); x.text(0, 'AAAA'); x.sc.settle()
    x.text(0, 'BBBB')                                                    # a redraw is due: the next ticks write the halves
    x.sc.advance(3)
    hit = x.d.tick_interrupted(after, lambda sp: x.d.send_sysex(mc.text_request(1, 'CCCC'), sp=sp))
    if not hit: break                                                    # (the tick ended before `after` instructions: every point was tried)
    points += 1; x.sc.apply(); x.sc.settle()
    if x.sc.fb() != host_picture(['BBBB', 'CCCC']): fails.append(after)
check(f'TEXT arriving at any point of a screen write ({points} points): the final picture holds both lines', (fails, points > 20), ([], True))

print('ALL PASS' if ok else 'SOME TESTS FAILED')
sys.exit(0 if ok else 1)
