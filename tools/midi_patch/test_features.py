"""Feature tests of the translator and the LED code in the emulator: transport actions (MIDI Start/Stop, MMC, CC), the other button
actions (note, continue, none), the local LED behaviour (resting colours, press / hit feedback, toggle state), its interplay with LEDs
the host sets, and the bounds of the output buffer.

Configurations are tried by replacing the config block in the emulated flash, so one image tests them all; the block comes from
build_patch.default_cfg (which tests that function too).
Usage: test_features.py <patched.bin> <data_init.bin>"""
import os, struct, sys
from unicorn import *
from unicorn.arm_const import *

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import build_patch as bp

FL = 0x08003000
fw = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

# config block layout (struct cfg in translate.c)
O_CHAN, O_PADNOTE, O_BTNCC, O_ENCCC, O_LEDCH, O_PADLED, O_BTNMODE, O_BTNACT, O_LEDFLAGS, O_IDLE, O_ON, O_PADCOL, O_STRIPCOL = 4, 5, 21, 69, 72, 73, 95, 96, 144, 145, 146, 147, 148
ACT_CC, ACT_NOTE, ACT_START, ACT_CONT, ACT_STOP, ACT_MMC, ACT_NONE = range(7)
LF_BTN_IDLE, LF_BTN_PRESS, LF_PAD_IDLE, LF_PAD_HIT, LF_STRIP = 1, 2, 4, 8, 16
PLAY, REC, STOP, VOLUME = bp.BTN_PLAY, bp.BTN_REC, bp.BTN_STOP, 3
assert bp.CFG_SIZE == 274 and (bp.ACT_CC, bp.ACT_NOTE, bp.ACT_START, bp.ACT_CONT, bp.ACT_STOP, bp.ACT_MMC, bp.ACT_NONE) == (0, 1, 2, 3, 4, 5, 6)
IMG_CFG = fw[bp.CFG_ADDR - FL:][:bp.CFG_SIZE]
assert IMG_CFG[O_BTNACT + PLAY] == ACT_START and IMG_CFG[O_BTNCC + VOLUME] == 44, 'the offsets above match the image under test'

def cfg_with(base=None, **kw):
    """The config block with fields replaced: scalar fields by offset name, ('btn_cc'|'btn_act', index) by tuple key."""
    c = bytearray(base if base is not None else IMG_CFG)
    for k, v in kw.items():
        if k.startswith('btn_act_'): c[O_BTNACT + int(k[8:])] = v
        elif k.startswith('btn_cc_'): c[O_BTNCC + int(k[7:])] = v
        else: c[{'channel': O_CHAN, 'btn_mode': O_BTNMODE, 'led_flags': O_LEDFLAGS, 'idle': O_IDLE, 'on': O_ON, 'pad_colour': O_PADCOL,
                 'strip_colour': O_STRIPCOL, 'led_channel': O_LEDCH}[k]] = v
    return bytes(c)

import devsim
from devsim import report1, report2, CC, usb_packets, STRUCT, LED_BUF, LED_FLAG
def Dev(cfg=None): return devsim.Dev(fw, data, cfg)

# ---- transport ---------------------------------------------------------------------------------------------------------------------
d = Dev()
d.translate(report1())                                           # baseline
check('default build: Play press -> one MIDI Start (single-byte realtime packet 0F FA)', d.translate(report1([PLAY])), [(0x0F, 0xFA, 0, 0)])
check('... and nothing on release', d.translate(report1()), [])
check('default build: Stop press -> MIDI Stop (0F FC), nothing on release', (d.translate(report1([STOP])), d.translate(report1())), ([(0x0F, 0xFC, 0, 0)], []))
check('default build: Rec stays a CC (58, gate: 127 on press, 0 on release)', (d.translate(report1([REC])), d.translate(report1())), ([CC(58, 127)], [CC(58, 0)]))

d = Dev(bp.default_cfg(transport='cc')); d.translate(report1())
check('transport cc: Play = CC57, Rec = CC58, Stop = CC59, 127 on press and 0 on release',
      [d.translate(report1([b])) + d.translate(report1()) for b in (PLAY, REC, STOP)], [[CC(n, 127), CC(n, 0)] for n in (57, 58, 59)])

d = Dev(bp.default_cfg(transport='mmc')); d.translate(report1())
mmc = lambda cmd: [(0x04, 0xF0, 0x7F, 0x7F), (0x07, 0x06, cmd, 0xF7)]
check('transport mmc: Play = F0 7F 7F 06 02 F7, Rec = ... 06 F7 (record strobe), Stop = ... 01 F7; press only',
      [d.translate(report1([b])) + d.translate(report1()) for b in (PLAY, REC, STOP)], [mmc(2), mmc(6), mmc(1)])

# ---- other actions ------------------------------------------------------------------------------------------------------------------
d = Dev(cfg_with(btn_act_3=ACT_CONT, btn_act_4=ACT_NOTE, btn_cc_4=60, btn_act_5=ACT_NONE, btn_cc_6=0xFF, channel=2)); d.translate(report1())
check('ACT_CONT: 0F FB on press only', (d.translate(report1([3])), d.translate(report1())), ([(0x0F, 0xFB, 0, 0)], []))
check('ACT_NOTE: Note On (velocity 127) while pressed, Note Off on release, on the configured channel (3 here)',
      (d.translate(report1([4])), d.translate(report1())), ([(0x09, 0x92, 60, 127)], [(0x08, 0x82, 60, 0)]))
check('ACT_NONE and an unassigned CC (0xFF): silent', (d.translate(report1([5])), d.translate(report1()), d.translate(report1([6])), d.translate(report1())), ([], [], [], []))
check('ACT_CC still sends on the configured channel (button 0 = CC 38 on channel 3)', d.translate(report1([0])), [CC(38, 127, 2)])

# ---- local LEDs ---------------------------------------------------------------------------------------------------------------------
PADCOL = IMG_CFG[O_PADCOL]
REST_BTN, HIT_BTN = IMG_CFG[O_IDLE], IMG_CFG[O_ON]
PAD_REST, PAD_HIT = PADCOL * 4 + 1, PADCOL * 4 + 3
assert all(k in bp.NI_BUTTON_CC for k in range(39))
def idle_frame(rest=REST_BTN, pad=PAD_REST):
    f = bytearray([0xFF] * 80)
    for k in range(39): f[k] = rest
    for p in range(16): f[39 + p] = pad
    return f
d = Dev(); d.boot2()
check('stage-2 init only prepares the resting state: the LED buffer is not touched and no frame is flagged (the stock startup would wipe it)',
      (d.led(), d.flag()), (bytes(80), 0))
d.tick(6000); d.tick(1)
check('... the main-loop tick does nothing while the stock startup countdown runs', (d.led(), d.flag(), d.watchdog), (bytes(80), 0, 2))
d.tick(0)
check('... and when the countdown reaches 0 it writes the resting frame: every button in the dim code, all 16 pads in their colour (LEDs 39..54), flagged',
      (d.led(), d.flag(), d.watchdog), (bytes(idle_frame()), 1, 3), d.led().hex())
d.consume(); d.tick(0); d.tick(0)
check('... once only (the stock watchdog kick is still called every time)', (d.flag(), d.watchdog), (0, 5))
d.translate(report1())
orig = idle_frame()
f = d.translate(report1([VOLUME])); led = bytearray(d.led())
check('local LEDs: pressing a button lights exactly that LED (bright), keeps the CC, and flags the frame',
      (f, led[VOLUME], d.flag(), bytes(led[:VOLUME]) + bytes(led[VOLUME + 1:]) == bytes(orig[:VOLUME]) + bytes(orig[VOLUME + 1:])), ([CC(44, 127)], HIT_BTN, 1, True))
d.consume(); d.translate(report1())
check('... and releasing it returns to the resting code', (d.led()[VOLUME], d.flag()), (REST_BTN, 1))
d.consume(); d.translate(report1([PLAY]))
check('Play (MIDI Start, no CC) lights while held too, then rests again', (d.led()[PLAY], (d.translate(report1()), d.led()[PLAY])), (HIT_BTN, ([], REST_BTN)))
d.consume()
d.translate(report1([39])); led = d.led()
check('encoder press (button id 39) and touch (40) do not touch any LED: LED 39 is a PAD, not a button', (led[39], d.flag()), (PAD_REST, 0))
d.translate(report1([], touch=1)); d.translate(report1())
check('...  (touch, the same)', (d.led()[39], d.flag()), (PAD_REST, 0))

d = Dev(); d.start(); d.consume(); d.translate(report1())
hit = d.translate(report2([(12, 1, 3000)])); led = d.led()
check('local LEDs: a pad hit lights that pad in the bright variant (pad index 12 = printed pad 1 = LED 51), the note is unaffected',
      (hit[0][:2], led[51], d.flag(), [led[39 + p] for p in range(16) if p != 12] == [PAD_REST] * 15), ((9, 0x90), PAD_HIT, 1, True))
d.consume(); d.translate(report2([(12, 3, 0)]))
check('... and the note off returns it to its resting colour', (d.led()[51], d.flag()), (PAD_REST, 1))
d.consume(); d.translate(report2([(12, 1, 3000)])); d.consume(); d.translate(report2([(12, 2, 0)]))
check('... a press-off (type 2) does the same', d.led()[51], PAD_REST)

# toggle mode: the LED shows the on/off state
d = Dev(cfg_with(btn_mode=1)); d.start(); d.consume(); d.translate(report1())
a = d.translate(report1([VOLUME])); la = d.led()[VOLUME]; d.consume()
b = d.translate(report1()); lb = d.led()[VOLUME]; fb = d.flag()
c = d.translate(report1([VOLUME])); lc = d.led()[VOLUME]; d.consume()
e = d.translate(report1())
check('toggle mode: press -> CC 127 and LED on, release -> nothing and LED stays on, next press -> CC 0 and LED back to rest',
      (a, la, b, lb, fb, c, lc, e), ([CC(44, 127)], HIT_BTN, [], HIT_BTN, 0, [CC(44, 0)], REST_BTN, []))

# flags: everything off / selected parts
d = Dev(cfg_with(led_flags=0)); d.start(); d.translate(report1()); d.translate(report1([VOLUME])); d.translate(report2([(12, 1, 3000)])); d.translate(report1(pos=100))
check('led_flags = 0 (--local-leds off): no LED is written and the frame is never flagged', (d.led(), d.flag()), (bytes(80), 0))
d = Dev(cfg_with(led_flags=LF_BTN_IDLE | LF_PAD_IDLE)); d.start(); d.consume(); d.translate(report1()); d.translate(report1([VOLUME])); d.translate(report2([(12, 1, 3000)]))
check('only the idle bits: resting colours without press / hit feedback', (d.led()[VOLUME], d.led()[51], d.flag()), (REST_BTN, PAD_REST, 0))
d = Dev(cfg_with(led_flags=LF_BTN_PRESS | LF_PAD_HIT)); d.start(); d.consume(); d.translate(report1()); d.translate(report1([VOLUME])); d.translate(report2([(12, 1, 3000)]))
check('only the feedback bits: dark at rest, bright while pressed / hit', (d.led()[VOLUME], d.led()[51]), (HIT_BTN, PAD_HIT))
d.translate(report1()); d.translate(report2([(12, 3, 0)]))
check('... and dark again afterwards (the rest state is "off")', (d.led()[VOLUME], d.led()[51]), (0, 0))

# unassigned buttons stay dark, a different pad colour
d = Dev(cfg_with(btn_cc_6=0xFF, btn_act_7=ACT_NONE, pad_colour=5)); d.start()
led = d.led()
check('an unassigned button (CC 0xFF) and an ACT_NONE button get no resting light, the pad colour option is used (colour 5: rest 21, hit 23)',
      (led[6], led[7], led[VOLUME], led[39]), (0xFF, 0xFF, REST_BTN, 5 * 4 + 1))
d.consume(); d.translate(report2([(0, 1, 4000)]))
check('... hit code 23', d.led()[39], 5 * 4 + 3)
d = Dev(cfg_with(pad_colour=0)); d.start()
check('pad colour 0 means white (17: rest 69)', d.led()[39], 17 * 4 + 1)

# the stock startup ends by clearing every LED: whatever the host set during it is shown again at its end, and nothing is flagged without LEDs
d = Dev(cfg_with(led_flags=0)); d.boot2(); d.tick(3000)
d.rx(bytes([0x09, 0x91, 5, 99])); d.consume()                            # the host sets LED 5 during the animation; the stock startup then wipes the matrix
d.tick(0)
check('a LED the host set during the stock startup is written again when it ends (also with the local LEDs off)', (d.led()[5], d.flag()), (99, 1))
d = Dev(cfg_with(led_flags=0)); d.start()
check('led_flags = 0 and nothing set by the host: the end of the startup writes nothing', (d.led(), d.flag()), (bytes(80), 0))

# the touch strip LED under the finger (LEDs 55..79, positions 1..200)
STRIP0 = 55
d = Dev(); d.start(); d.consume(); d.translate(report1())
SC = IMG_CFG[O_STRIPCOL] * 4 + 3
check('strip LED: the default colour is white (17), shown bright', SC, 17 * 4 + 3)
d.translate(report1(pos=1)); led = d.led()
check('strip LED: touching the far left lights the first strip LED (55), nothing else changes, frame flagged',
      (led[STRIP0], bytes(led[STRIP0 + 1:]).count(0xFF), d.flag(), bytes(led[:55]) == bytes(idle_frame()[:55])), (SC, 24, 1, True))
d.consume(); d.translate(report1(pos=200)); led = d.led()
check('... the far right lights the last one (79) and the first goes dark again (an explicit "off", not "skip": the stock loop ignores 0xFF entries)', (led[STRIP0], led[STRIP0 + 24], d.flag()), (0, SC, 1))
lit = []
for pos in range(1, 201):
    d.translate(report1(pos=pos)); l = d.led(); lit.append([i for i in range(STRIP0, 80) if l[i] == SC])
check('every position 1..200 lights exactly one strip LED, from left to right, each LED covering 8 positions',
      (all(len(x) == 1 for x in lit), [x[0] - STRIP0 for x in lit] == sorted(x[0] - STRIP0 for x in lit), {x[0] - STRIP0 for x in lit} == set(range(25))), (True, True, True))
d.consume(); d.translate(report1(pos=100)); d.consume(); d.translate(report1(pos=100))
check('... a finger that stays put sends no new frame', d.flag(), 0)
d.translate(report1(pos=0)); l = d.led()
check('... lifting the finger turns the LED off again (back to its resting state)', ([i for i in range(STRIP0, 80) if l[i] == SC], d.flag()), ([], 1))
d.consume(); d.rx(bytes([0x09, 0x91, 60, 20])); d.consume()           # host colours strip LED 60
d.translate(report1(pos=1 + 5 * 8)); d.consume(); d.translate(report1(pos=0)); d.consume()          # LED 60 = strip LED 5: position 41..48
check('a host-coloured strip LED returns to the host colour after the finger leaves it', d.led()[60], 20)
d = Dev(cfg_with(strip_colour=5)); d.start(); d.translate(report1()); d.translate(report1(pos=1))
check('--strip-colour is used (colour 5: code 23)', d.led()[STRIP0], 5 * 4 + 3)
d = Dev(cfg_with(led_flags=LF_BTN_IDLE | LF_BTN_PRESS | LF_PAD_IDLE | LF_PAD_HIT)); d.start(); d.translate(report1()); d.consume(); d.translate(report1(pos=100))
check('without the strip flag the strip LEDs stay untouched (and no frame is flagged)', (d.led()[STRIP0:], d.flag()), (bytes([0xFF] * 25), 0))
d = Dev(); d.start(); d.consume(); d.translate(report1(pos=100)); d.consume()
cc = d.translate(report1(pos=120))
check('the strip CC messages are unaffected by the strip LED', cc, [CC(1, (120 - 1) * 127 // 199)])

# ---- interplay with LEDs the host sets -----------------------------------------------------------------------------------------------
d = Dev(); d.start(); d.consume(); d.translate(report1())
d.rx(bytes(CC(44, 50))); d.consume()                                 # host feedback: Volume LED normal (value 50 -> 0x7e)
d.translate(report1([VOLUME])); pressed = d.led()[VOLUME]; d.consume(); d.translate(report1())
check('host feedback becomes the resting state: Volume set to the normal level by CC feedback, a press and release returns to that (not to dim)',
      (pressed, d.led()[VOLUME]), (HIT_BTN, 0x7E))
d.consume(); d.rx(bytes(CC(44, 0))); d.consume(); d.translate(report1([VOLUME])); d.consume(); d.translate(report1())
check('a host-set LED that is OFF rests off after a press', d.led()[VOLUME], 0)
d.consume(); d.rx(bytes([0x09, 0x91, 51, 20])); d.consume()          # host colours pad 1 (LED 51) on the LED channel
d.translate(report2([(12, 1, 3000)])); hitcode = d.led()[51]; d.consume(); d.translate(report2([(12, 3, 0)]))
check('a host-coloured pad flashes on a hit and returns to the host colour', (hitcode, d.led()[51]), (PAD_HIT, 20))
d.consume(); d.rx(usb_packets(bytes([0xF0, 0x7D, 0x4D, 0x4B, 2]) + bytes((i * 3) & 0x7f for i in range(80)) + bytes([0xF7]))); d.consume()
d.translate(report1([VOLUME])); d.consume(); d.translate(report1())
check('a SysEx LED frame sets the resting state of all LEDs as well', d.led()[VOLUME], (VOLUME * 3) & 0x7f)
check('every flush writes the COMPLETE frame (nothing from earlier is lost): the LEDs of the SysEx frame are all there',
      d.led()[:VOLUME] + d.led()[VOLUME + 1:], bytes((i * 3) & 0x7f for i in range(80) if i != VOLUME))

# CC feedback no longer matches buttons whose action is not a CC
d = Dev(); d.start(); d.consume(); d.rx(bytes(CC(57, 127)))
check('CC 57 feedback is ignored by the default build (Play is MIDI Start, it has no CC)', (d.flag(), d.led()[PLAY]), (0, REST_BTN))
d = Dev(bp.default_cfg(transport='cc')); d.start(); d.consume(); d.rx(bytes(CC(57, 127)))
check('... but lights Play when the transport runs on CCs', (d.flag(), d.led()[PLAY]), (1, 0x7F))

# ---- output bounds ----------------------------------------------------------------------------------------------------------------
allmmc = bytearray(IMG_CFG)
for k in range(48): allmmc[O_BTNACT + k] = ACT_MMC; allmmc[O_BTNCC + k] = 2
allmmc[O_LEDFLAGS] = 0
ev21 = [(p, 1, 3000) for p in range(16)] + [(p, 1, 3000) for p in range(5)]          # 21 pad events: 16 first hits, then 5 retriggers
d = Dev(allmmc); d.translate(report1())
out = d.translate(report1(range(41)) + report2(ev21))
check('worst case: all 41 buttons as MMC (82 packets, 328 B) and 21 pad events (16 Note On + 5 x Note Off/On) in one buffer: 108 packets, all delivered',
      (len(out), len(d.sent[0])), (108, 432))
sx0 = d.out_ptr + 512
guard = bytes(d.mu.mem_read(sx0, 480))                              # sx[], led[] and base[] sit directly behind out[]
d.translate(report2(ev21) * 3)                                      # every pad is held now: each event is a Note Off + a Note On (8 B)
total = lambda: sum(len(b) for b in d.sent)
check('three full pad reports in one buffer (3 x 168 B = 504 B): all delivered (the buffer is handed to the ring when it runs low); nothing behind out[] is overwritten',
      (total(), bytes(d.mu.mem_read(sx0, 480)) == guard), (504, True))
d.translate(report2(ev21) * 5)
check('five of them (840 B): all delivered in several pieces, nothing lost, nothing behind out[] is overwritten',
      (total(), len(d.sent) > 1, bytes(d.mu.mem_read(sx0, 480)) == guard), (840, True, True))
d = Dev(allmmc); d.translate(report1())
check('two report-1s in one buffer after a 328 B first one (the second releases everything: nothing to send): 82 packets',
      (len(d.translate(report1(range(41)) + report1())), total()), (82, 328))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
