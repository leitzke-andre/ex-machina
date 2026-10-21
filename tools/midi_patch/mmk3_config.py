#!/usr/bin/env python3
"""Host side of the run-time configuration of the Mikro MK3 USB-MIDI patch (protocol: docs/remap-protocol.md).

The config block layout (struct cfg in translate.c, 274 bytes), its defaults, the range check the firmware applies, the SysEx
messages (INFO / GET / SET / SAVE / RESET), the saved flash record, and a small client on top of mido. Standard library only,
except for the client, which needs `pip install mido python-rtmidi`. build_patch.py takes its defaults from here, the emulator
tests talk to the firmware with these functions, and the planned browser UI repeats the same logic in JavaScript (checked against
the vectors this file produces).

    mmk3_config.py info                        what the device says about itself
    mmk3_config.py get [FILE.json]             print (or save) the active config
    mmk3_config.py set FILE.json               send a config (active at once, not saved)
    mmk3_config.py button Play start           change one button: cc N | note N | start | continue | stop | mmc N | none | padmode | keys | fixvel |
                                               vel16 | curve|scale|chordtype|arptype|rate|channel [next|prev] | chords | strip 0..3 | enctgt 0|1|2 | program 0|1|2 | snap 0|1 | tap | clockout | arp | arpoct | latch | mute | solo | clear | transpose SEMITONES | panic | shift;  add --shift to change what it does while Shift is held
    mmk3_config.py pad 1 40                    pad 1 sends note 40
    mmk3_config.py hal all | none | MASK         our own hardware drivers instead of NI's (1 LEDs, 2 display, 4 buttons, 8 strip, 16 pads, 32 reports, 64 LED colours, 256 main loop, 512 SysTick; until the next power cycle)
    mmk3_config.py slot list | store N [name] | load N   the four preset slots in the device (N = 1..4): store the active config under a name (shown when the slot is loaded with the buttons) / make a slot active (not saved)
    mmk3_config.py mode [standalone | fl]    the device's mode (Shift + Project switches it on the device; FL Studio mode = the built-in FL mapping)
    mmk3_config.py host [screen] [raw] [quiet] | host off   host mode, as a DAW script sets it (until the next power cycle, SET, RESET or slot load)
    mmk3_config.py text 1..4 WORDS | text clear           a line of text on the screen while host mode 'screen' is on
    mmk3_config.py save | reset [--erase]      keep the active config across power cycles | back to the defaults
    mmk3_config.py preset list [FILE]          the built-in presets (and those in a preset file)
    mmk3_config.py preset apply NAME [FILE] [--save]   send a preset (by id or name; from FILE if it is not built in), optionally keep it
"""
import json, struct, sys, time

CFG_SIZE = 274
PROTO_VERSION = 2
FW_NAME, FW_VERSION = 'Ex-Machina', 0                  # the firmware's name and version (the idle screen shows EX-MACHINA / V0; INFO reports the version)

# ---- button actions, local LED flags (enum / defines in translate.c) ----
(ACT_CC, ACT_NOTE, ACT_START, ACT_CONT, ACT_STOP, ACT_MMC, ACT_NONE,
 ACT_PADMODE, ACT_KEYS, ACT_FIXVEL, ACT_VEL16, ACT_CURVE, ACT_TRANSPOSE, ACT_PANIC, ACT_SHIFT,
 ACT_SCALE, ACT_CHORDS, ACT_CHORDTYPE, ACT_STRIP, ACT_ENCTGT, ACT_PROGRAM,
 ACT_TAP, ACT_CLOCKOUT, ACT_ARP, ACT_ARPTYPE, ACT_RATE, ACT_ARPOCT, ACT_LATCH, ACT_MUTE, ACT_SOLO, ACT_CLEAR, ACT_SNAP,
 ACT_CHANNEL, ACT_SLOT, ACT_STEP, ACT_SEQRUN, ACT_SEQSEL, ACT_SEQPAT, ACT_SEQCLEAR, ACT_SEQSAVE, ACT_PAGE, ACT_ENCPAGE) = range(42)
ACT_LAST = ACT_ENCPAGE
ACTION_NAMES = ('cc', 'note', 'start', 'continue', 'stop', 'mmc', 'none', 'padmode', 'keys', 'fixvel', 'vel16', 'curve', 'transpose', 'panic', 'shift',
                'scale', 'chords', 'chordtype', 'strip', 'enctgt', 'program',
                'tap', 'clockout', 'arp', 'arptype', 'rate', 'arpoct', 'latch', 'mute', 'solo', 'clear', 'snap',
                'channel', 'slot', 'step', 'seqrun', 'seqsel', 'seqpat', 'seqclear', 'seqsave', 'page', 'encpage')
ARP_TYPES = ('repeat', 'up', 'down', 'up-down', 'played', 'random')                           # cfg.arp_type 0..5
ARP_RATES = ('1/4', '1/8', '1/8T', '1/16', '1/16T', '1/32', '1/32T')                          # cfg.arp_rate 0..6
SCALE_NAMES = ('chromatic', 'major', 'minor', 'harmonic minor', 'melodic minor', 'dorian', 'phrygian', 'lydian', 'mixolydian', 'locrian', 'major penta',
               'minor penta', 'blues', 'whole tone', 'diminished W-H', 'diminished H-W', 'hungarian minor', 'phryg dominant', 'double harmonic',
               'hirajoshi', 'in-sen', 'major blues', 'bebop dominant', 'neapolitan min')   # cfg.scale 0..23 (the masks are in build_patch.SCALES)
CHORD_NAMES = ('triad', 'seventh', 'sus2', 'sus4', 'power', 'minor', 'maj 9', 'maj 11')     # cfg.chord_type 0..7: 0-4 from the scale, 5-7 fixed shapes
VEL_CURVES = ('soft3', 'soft2', 'soft1', 'linear', 'hard1', 'hard2', 'hard3', 'fixed', 'custom')   # cfg.vel_curve 0..8
PRESS_MODES = ('poly aftertouch', 'channel pressure', 'control change', 'off')                      # cfg.press_mode 0..3
LF_BTN_IDLE, LF_BTN_PRESS, LF_PAD_IDLE, LF_PAD_HIT, LF_STRIP = 1, 2, 4, 8, 16
BTN_PLAY, BTN_REC, BTN_STOP = 22, 23, 24

# Button ids of report 1 (bit k = button k) and the names NI prints on them; 39 and 40 are the encoder's push and touch.
BUTTON_NAMES = ['Project', 'Favorites', 'Browser', 'Volume', 'Swing', 'Tempo', 'Plug-in', 'Sampling', 'Left', 'Right', 'Pitch', 'Mod',
                'Perform', 'Notes', 'Group', 'Auto', 'Lock', 'Note Repeat', 'Restart', 'Erase', 'Tap', 'Follow', 'Play', 'Rec', 'Stop',
                'Shift', 'Fixed Vel', 'Pad Mode', 'Keyboard', 'Chords', 'Step', 'Scene', 'Pattern', 'Events', 'Variation', 'Duplicate',
                'Select', 'Solo', 'Mute', 'Encoder Push', 'Encoder Touch']
assert len(BUTTON_NAMES) == 41

# LED colours (colour code = colour * 4 + brightness 0..3; verified by eye on the real unit): names of colours 1..17.
COLOUR_NAMES = ['red', 'orange', 'light orange', 'warm yellow', 'yellow', 'lime', 'green', 'mint', 'cyan', 'turquoise', 'blue', 'plum', 'violet',
                'purple', 'magenta', 'fuchsia', 'white']

# Pad index in HID report 2 -> the number printed on the pad (index 0 is the top-left pad "13").
PAD_LABEL = [13, 14, 15, 16, 9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4]

# NI's documented MIDI-mode map for the Mikro MK3 (Maschine_Mikro_MK3_Manual p. 75), by button id
# (id order from the community drivers). NI sends nothing for the arrows, Shift and the encoder touch; those get spare CCs.
NI_BUTTON_CC = {
    0: 38, 1: 39, 2: 40,                       # Project, Favorites, Browser
    3: 44, 4: 46, 5: 48, 6: 45, 7: 47,         # Volume, Swing, Tempo, Plug-in, Sampling
    8: 41, 9: 42,                              # arrow left/right (NI: none)
    10: 49, 11: 50, 12: 51, 13: 52,            # Pitch, Mod, Perform, Notes
    14: 34, 15: 35, 16: 36, 17: 37,            # Group, Auto, Lock, Note Repeat
    18: 53, 19: 54, 20: 55, 21: 56,            # Restart, Erase, Tap, Follow
    22: 57, 23: 58, 24: 59, 25: 43,            # Play, Rec, Stop, Shift (NI: none)
    26: 80, 27: 81, 28: 82, 29: 84, 30: 83,    # Fixed Vel, Pad Mode, Keyboard, Chords, Step
    31: 85, 32: 86, 33: 87, 34: 88,            # Scene, Pattern, Events, Variation
    35: 89, 36: 90, 37: 91, 38: 92,            # Duplicate, Select, Solo, Mute
    39: 8,                                     # encoder press
    40: 9,                                     # encoder touch (NI: none)
}

# ---- the config block ----
# name: (offset, count in bytes). Scalars have count 1; boot_ms is a u16 (little endian).
FIELDS = {
    'magic': (0, 4), 'channel': (4, 1), 'pad_note': (5, 16), 'btn_cc': (21, 48), 'enc_cc': (69, 1), 'strip_cc': (70, 1),
    'vel_shift': (71, 1), 'led_channel': (72, 1), 'pad_led': (73, 16), 'enc_mode': (89, 1), 'flags': (90, 1), 'sens': (91, 1),
    'enc_init': (92, 1), 'boot_ms': (93, 2), 'btn_mode': (95, 1), 'btn_act': (96, 48), 'led_flags': (144, 1), 'btn_led_idle': (145, 1),
    'btn_led_on': (146, 1), 'pad_colour': (147, 1), 'strip_colour': (148, 1),
    'vel_curve': (149, 1), 'fixvel': (150, 1), 'keys_root': (151, 1), 'press_mode': (152, 1), 'press_cc': (153, 1),
    'btn_act2': (154, 48), 'btn_cc2': (202, 48), 'scale': (250, 1), 'chord_type': (251, 1), 'enc_tgt_cc': (252, 3),
    'arp_type': (255, 1), 'arp_rate': (256, 1), 'arp_oct': (257, 1), 'tempo': (258, 1),
    'btn_mode_ovr': (259, 12), 'enc_pages': (271, 1), 'enc_page_step': (272, 1), 'enc_accel': (273, 1),
}
# the allowed values: (lowest, highest, 0xFF also allowed). The firmware's cfg_check() applies exactly these.
RANGES = {
    'channel': (0, 15, False), 'pad_note': (0, 127, False), 'btn_cc': (0, 127, True), 'btn_act': (0, ACT_LAST, False),
    'enc_cc': (0, 127, True), 'strip_cc': (0, 127, True), 'vel_shift': (1, 8, False), 'led_channel': (0, 15, False),
    'pad_led': (0, 79, True), 'enc_mode': (0, 2, False), 'flags': (0, 1, False), 'sens': (0, 100, True), 'enc_init': (0, 127, False),
    'btn_mode': (0, 2, False), 'led_flags': (0, 31, False), 'btn_led_idle': (0, 127, False), 'btn_led_on': (0, 127, False),
    'pad_colour': (0, 17, False), 'strip_colour': (0, 17, False),
    'vel_curve': (0, 8, False), 'fixvel': (1, 127, False), 'keys_root': (0, 127, False), 'press_mode': (0, 3, False), 'press_cc': (0, 127, False),
    'btn_act2': (0, ACT_LAST, False), 'btn_cc2': (0, 127, True), 'scale': (0, 23, False), 'chord_type': (0, len(CHORD_NAMES) - 1, False), 'enc_tgt_cc': (0, 127, True),
    'arp_type': (0, 5, False), 'arp_rate': (0, 6, False), 'arp_oct': (1, 4, False), 'tempo': (0, 255, False),
    'btn_mode_ovr': (0, 255, False), 'enc_pages': (1, 8, False), 'enc_page_step': (1, 32, False), 'enc_accel': (0, 3, False),
}
ENC_MODES = ('relative-offset', 'absolute', 'relative')        # cfg.enc_mode 0, 1, 2
BTN_MODES = ('gate', 'toggle', 'trigger')                       # cfg.btn_mode 0, 1, 2


def default_cfg(sens=0xFF, boot_ms=0xFFFF, pad_base=36, enc_mode=1, enc_init=0, btn_mode=0, vel_shift=5, transport='realtime',
                local_leds=True, pad_colour=11, strip_colour=17, vel_curve=3):
    """The build-time defaults, as written to flash at CFG_ADDR by build_patch.py (and the config the device starts with)."""
    btn = bytearray([0xFF] * 48)
    for k, cc in NI_BUTTON_CC.items(): btn[k] = cc
    c = bytearray(b'MMK3')
    c += bytes([0])                                   # MIDI channel 1
    c += bytes(pad_base - 1 + n for n in PAD_LABEL)   # pad n -> note pad_base-1+n (36: pad 1 = 36 ... pad 16 = 51; NI's template: 12)
    c += btn
    c += bytes([7, 1, vel_shift])                     # encoder CC7, strip CC1, vel_shift (5: velocity index = value12 >> 4, pressure = value12 >> 5)
    c += bytes([1])                                   # LED channel: MIDI channel 2, note n -> LED n
    c += bytes(range(39, 55))                         # pad report index p -> LED 39+p (same order)
    c += bytes([enc_mode, 0])                         # encoder mode (1 absolute, 0 relative-offset, 2 relative), no strip-release CC
    c += bytes([sens, enc_init]) + struct.pack('<H', boot_ms)  # sensitivity (0xff: keep stored), encoder start value, boot delay (0xffff: keep stock)
    c += bytes([btn_mode])                            # 0 gate, 1 toggle (NI's default), 2 trigger
    act = bytearray([ACT_CC] * 48)                    # what each button does; the CC numbers in btn_cc stay as NI's
    if transport == 'realtime':                       # Play / Stop become MIDI Start / Stop (Rec stays CC 58)
        act[BTN_PLAY], act[BTN_STOP] = ACT_START, ACT_STOP
    elif transport == 'mmc':                          # MIDI Machine Control: play 2, stop 1, record strobe 6 (the command byte goes in btn_cc)
        for b, cmd in ((BTN_PLAY, 2), (BTN_REC, 6), (BTN_STOP, 1)):
            act[b] = ACT_MMC; c[21 + b] = cmd
    c += act
    c += bytes([(LF_BTN_IDLE | LF_BTN_PRESS | LF_PAD_IDLE | LF_PAD_HIT | LF_STRIP) if local_leds else 0])   # local LED behaviour
    c += bytes([0x7C, 0x7F, pad_colour, strip_colour])   # button LED at rest (dim) and pressed (bright); pad colour 1..17; strip LED colour
    c += bytes([vel_curve, 127, 60, 0, 11])           # velocity curve (3 = linear), Fixed Vel value, Keyboard root (60 = C3), pad pressure = polyphonic aftertouch (CC 11 if switched to CC)
    c += bytes([ACT_NONE] * 48) + bytes([0xFF] * 48)  # the shifted layer: nothing, every button keeps its normal action
    c += bytes([0, 0, 7, 10, 11])                     # scale (chromatic), chord type (triad), the CCs of the three encoder targets (volume, pan, expression)
    c += bytes([0, 3, 1, 100])                        # arp: repeat, 1/16, one octave; start tempo 120 BPM (stored minus 20)
    c += bytes(12) + bytes([1, 3, 0])                 # every button on the global CC mode; encoder pages: 1 page, 3 CCs per page, no acceleration
    assert len(c) == CFG_SIZE, len(c)                 # must match sizeof(struct cfg) in translate.c
    return fix_project(c)

BTN_PROJECT = 0
def fix_project(cfg, fl=False):
    """Project (top left) is fixed: in Standalone mode it loads the next preset slot, in FL Studio mode (fl) it sends CC 38 for the script; with Shift
    it switches the mode. The firmware enforces it on every config it takes (cfg_fixed() in translate.c), so every config made here carries it too and
    reads back unchanged."""
    c = bytearray(cfg)
    c[FIELDS['btn_act'][0] + BTN_PROJECT] = ACT_CC if fl else ACT_SLOT; c[FIELDS['btn_cc'][0] + BTN_PROJECT] = 38 if fl else 8
    c[FIELDS['btn_act2'][0] + BTN_PROJECT] = ACT_NONE; c[FIELDS['btn_cc2'][0] + BTN_PROJECT] = 0xFF     # with Shift: the same
    return bytes(c)


def btn_mode_of(cfg, k):
    """The mode of a CC button: 0 gate, 1 toggle, 2 trigger (its own setting, else the global one)."""
    o = (cfg[FIELDS['btn_mode_ovr'][0] + (k >> 2)] >> ((k & 3) * 2)) & 3
    return o - 1 if o else cfg[FIELDS['btn_mode'][0]]

def set_btn_mode(cfg, k, mode):
    """Gives button k its own CC mode (0 gate, 1 toggle, 2 trigger) or, with None, the global one again. Returns the new config."""
    c = bytearray(cfg); i = FIELDS['btn_mode_ovr'][0] + (k >> 2); sh = (k & 3) * 2
    c[i] = (c[i] & ~(3 << sh)) | (((0 if mode is None else mode + 1) & 3) << sh)
    return bytes(c)

def check(cfg):
    """The firmware's range check (cfg_check in translate.c): None if the block is usable, else the offset of the first bad byte, in the
    order the device checks them (so the offset equals the one in the device's reply to SET)."""
    cfg = bytes(cfg)
    if len(cfg) != CFG_SIZE or cfg[:4] != b'MMK3': return 0
    def bad(name, i=0):
        lo, hi, ff = RANGES[name]; v = cfg[FIELDS[name][0] + i]
        return not (lo <= v <= hi or (ff and v == 0xFF))
    order = [('channel', 0)] + [('pad_note', i) for i in range(16)]
    for i in range(48): order += [('btn_cc', i), ('btn_act', i)]
    order += [('enc_cc', 0), ('strip_cc', 0), ('vel_shift', 0), ('led_channel', 0)] + [('pad_led', i) for i in range(16)]
    order += [(n, 0) for n in ('enc_mode', 'flags', 'sens', 'enc_init', 'btn_mode', 'led_flags', 'btn_led_idle', 'btn_led_on', 'pad_colour', 'strip_colour',
                               'vel_curve', 'fixvel', 'keys_root', 'press_mode', 'press_cc')]
    for i in range(48): order += [('btn_cc2', i), ('btn_act2', i)]
    order += [('scale', 0), ('chord_type', 0)] + [('enc_tgt_cc', i) for i in range(3)] + [('arp_type', 0), ('arp_rate', 0), ('arp_oct', 0), ('enc_pages', 0), ('enc_page_step', 0), ('enc_accel', 0)]
    for name, i in order:
        if bad(name, i): return FIELDS[name][0] + i
        if name in ('btn_act', 'btn_act2') and cfg[FIELDS[name][0] + i] in (ACT_NOTE, ACT_MMC):    # a note / MMC button needs its number (0xFF would go out as a status byte)
            p = 'btn_cc' if name == 'btn_act' else 'btn_cc2'
            if cfg[FIELDS[p][0] + i] > 127: return FIELDS[p][0] + i
    return None


# ---- config <-> dict (raw values) ----
def to_dict(cfg):
    cfg = bytes(cfg); d = {}
    for name, (off, n) in FIELDS.items():
        if name == 'magic': continue
        if name == 'boot_ms': d[name] = struct.unpack_from('<H', cfg, off)[0]
        else: d[name] = list(cfg[off:off + n]) if n > 1 else cfg[off]
    return d

def from_dict(d, base=None):
    c = bytearray(base if base is not None else default_cfg())
    for name, v in d.items():
        off, n = FIELDS[name]
        if name == 'boot_ms': struct.pack_into('<H', c, off, v)
        elif n > 1:
            if len(v) != n: raise ValueError(f'{name}: {n} values expected, got {len(v)}')
            c[off:off + n] = bytes(v)
        else: c[off] = v
    return bytes(c)


# ---- 7-bit packing and SysEx messages ----
def pack7(data):
    """Groups of up to 7 data bytes behind one byte that holds their high bits (bit k = bit 7 of data byte k)."""
    out = bytearray()
    for i in range(0, len(data), 7):
        g = data[i:i + 7]
        out.append(sum(((v >> 7) & 1) << k for k, v in enumerate(g)))
        out += bytes(v & 0x7F for v in g)
    return bytes(out)

def unpack7(data):
    out = bytearray()
    for i in range(0, len(data), 8):
        hi = data[i]
        for j, v in enumerate(data[i + 1:i + 8]): out.append((v & 0x7F) | (((hi >> j) & 1) << 7))
    return bytes(out)

MANUFACTURER = bytes([0x7D, 0x4D, 0x4B])             # 7D = non-commercial use, then "MK"
CMD_INFO, CMD_GET, CMD_SET, CMD_SAVE, CMD_RESET, CMD_PEEK = 0x10, 0x11, 0x12, 0x13, 0x14, 0x1E
CMD_SLOT_STORE, CMD_SLOT_LOAD, CMD_SLOTS = 0x15, 0x16, 0x17          # the four preset slots in the device's flash
REPLY = 0x40                                         # a reply carries the request's command + 0x40
STATUS = {0: 'ok', 1: 'wrong length', 2: 'value out of range', 3: 'flash error', 4: 'empty slot'}

def message(cmd, payload=b''):
    return bytes([0xF0]) + MANUFACTURER + bytes([cmd]) + bytes(payload) + bytes([0xF7])

def info_request(): return message(CMD_INFO)
def get_request(): return message(CMD_GET)
def set_request(cfg): return message(CMD_SET, pack7(fix_project(cfg)))
def save_request(): return message(CMD_SAVE)
def reset_request(erase=False): return message(CMD_RESET, bytes([1]) if erase else b'')
NAME_MAX = 20                                       # characters of a preset's display name: what the screen's detail line shows whole (6 pixels each from x = 4)

def display_name(text):
    """A text as the device shows it: capitals and the characters of its 5x7 font (32-95), at most NAME_MAX of them."""
    return ''.join(ch if 32 <= ord(ch) <= 95 else '?' for ch in str(text).upper()).strip()[:NAME_MAX]

def preset_display_name(p):
    """The name a preset has on the device's screen: its own `display_name`, else one made from the name ("(draft)" dropped)."""
    own = display_name(p.get('display_name', ''))
    return own or display_name(str(p['name']).replace(' (draft)', '').replace('-like modes', ' modes'))

slot_name = display_name                            # (the name kept with a preset slot)
def slot_store_request(n, name=None): return message(CMD_SLOT_STORE, bytes([n]) + (display_name(name).encode('ascii') if name else b''))
def slot_load_request(n): return message(CMD_SLOT_LOAD, bytes([n]))
def slots_request(): return message(CMD_SLOTS)
CMD_CAPTURE, CMD_HANG = 0x1D, 0x1F                    # diagnostics (docs/clean-firmware-plan.md): raw pad capture, the watchdog test
CAP_BASE, CAP_END = 0x20001C20, 0x20004000            # where the capture lands in the device's RAM (header of 16 bytes, then the frames; above it the FL mode stash)
def capture_request(mask, period_ms=1): return message(CMD_CAPTURE, bytes([mask & 0x7F, (mask >> 7) & 0x7F, (mask >> 14) & 3, period_ms & 0x7F]))
def hang_request(): return message(CMD_HANG, b'HANG')     # send it with Device.hang(): once, never retried
CMD_HAL = 0x1C                                         # which of our own drivers (hal.c) replace the stock ones: bit 0 LED refresh, bit 1 display sender, bit 2 button scan, bit 3 strip read, bit 4 pads, bit 5 reports and dispatcher, bit 6 LED colours; a second byte 1 = run our LED chip start-up once
HAL_LED, HAL_DISP, HAL_BTN, HAL_STRIP, HAL_PADS, HAL_REPORTS, HAL_COLOUR = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
HAL_ALL = 0x7F
HAL_FLAG_LED_INIT, HAL_FLAG_NEXT_BOOT, HAL_FLAG_REBOOT, HAL_FLAG_NEXT_BOOT_USB = 0x01, 0x02, 0x04, 0x08   # (flags byte) our LED chip start-up now; our board init on the next boot (once); reboot now; our board init AND USB stack on the next boot (once)
HAL2_LOOP, HAL2_TICK = 0x01, 0x02                     # the second mask byte: our main-loop work, our SysTick handler
HAL2_ALL = 0x03
def hal_request(mask, flags=0, mask2=0): return message(CMD_HAL, bytes([mask & 0x7F]) + (bytes([flags & 0x7F, mask2 & 0x7F]) if flags or mask2 else b''))
CMD_MODE = 0x22                                        # the two modes (Shift + Project on the device): Standalone and FL Studio
MODE_NAMES = ('standalone', 'fl')
def mode_request(mode=None):
    """MODE: without an argument a query, else 'standalone' / 'fl' (or 0 / 1). The device answers 62 <status> <mode>, and sends the same message,
    unasked, after every switch (Shift + Project, or a mapping from a host ending FL Studio mode)."""
    if mode is None: return message(CMD_MODE)
    return message(CMD_MODE, bytes([MODE_NAMES.index(mode) if isinstance(mode, str) else int(mode)]))
CMD_HOST, CMD_TEXT = 0x20, 0x21                        # host mode for a DAW script (docs/remap-protocol.md): who owns the screen and the pads; text lines on the screen
HOST_SCREEN, HOST_RAW, HOST_QUIET = 1, 2, 4            # the picture is the host's text / pads send 36 + their number - 1 whatever the mode / no firmware messages
TEXT_COLS = 21
def host_request(flags): return message(CMD_HOST, bytes([flags & 0x7F]))
def text_request(line, text, col=0):
    """Text on line 0..3 from column `col` (at most 21 - col characters; shown while HOST_SCREEN is set). line None: all four lines blank."""
    if line is None: return message(CMD_TEXT, bytes([0x7F]))
    t = ''.join(ch if 32 <= ord(ch) <= 126 else '?' for ch in str(text))[:TEXT_COLS - col]
    return message(CMD_TEXT, bytes([line & 3, col]) + t.encode('ascii'))
def peek_request(addr, length):
    """Read-only diagnostic: `length` (1..64) bytes at `addr` (flash, RAM, chip ID registers; the firmware refuses anything else)."""
    return message(CMD_PEEK, bytes((addr >> (28 - 7 * i)) & 0x7F for i in range(5)) + bytes([length]))

class ProtocolError(Exception): pass

def parse_reply(msg):
    """msg: a complete SysEx message, with or without F0 / F7. Returns a dict with 'cmd' (the request it answers) and the fields."""
    m = bytes(msg)
    if m[:1] == b'\xF0': m = m[1:]
    if m[-1:] == b'\xF7': m = m[:-1]
    if m[:3] != MANUFACTURER or len(m) < 4 or m[3] < REPLY: raise ProtocolError(f'not a reply of this device: {m.hex()}')
    cmd, data = m[3] - REPLY, m[4:]
    if cmd == CMD_INFO:
        proto, size, flags = data[0], data[1] | (data[2] << 7), data[3]
        return {'cmd': cmd, 'protocol': proto, 'cfg_size': size, 'saved': bool(flags & 1), 'unsaved_changes': bool(flags & 2), 'loaded_from_flash': bool(flags & 4), 'version': data[4] if len(data) > 4 else None,
                'mode': MODE_NAMES[data[5]] if len(data) > 5 and data[5] < len(MODE_NAMES) else None}
    if cmd == CMD_GET: return {'cmd': cmd, 'cfg': unpack7(data)}
    if cmd == CMD_PEEK:
        addr = 0
        for b in data[1:6]: addr = (addr << 7) | b
        return {'cmd': cmd, 'status': data[0], 'addr': addr, 'data': unpack7(data[6:])[:] if data[0] == 0 else b''}
    if cmd == CMD_SLOTS:       # after the mask: NAME_MAX characters per slot (0 = padding); an older firmware sends none
        names = [bytes(data[2 + NAME_MAX * i:2 + NAME_MAX * (i + 1)]).rstrip(b'\0').decode('ascii', 'replace') for i in range(4)]
        return {'cmd': cmd, 'status': data[0], 'used': [bool(data[1] >> i & 1) for i in range(4)], 'names': names}
    if cmd == CMD_HAL:
        n = lambda o: data[o] | data[o + 1] << 7 | data[o + 2] << 14 if len(data) >= o + 3 else None
        return {'cmd': cmd, 'status': data[0], 'hal': data[1] if len(data) > 1 else None, 'led_ok': n(2), 'led_fail': n(5), 'strip_ok': n(8), 'strip_fail': n(11), 'hal2': data[14] if len(data) > 14 else None, 'own_init': data[15] if len(data) > 15 else None, 'own_usb': data[16] if len(data) > 16 else None}
    if cmd == CMD_MODE: return {'cmd': cmd, 'status': data[0], 'status_text': STATUS.get(data[0], '?'), 'mode': MODE_NAMES[data[1]] if len(data) > 1 and data[1] < 2 else None}
    if cmd == CMD_HOST: return {'cmd': cmd, 'status': data[0], 'status_text': STATUS.get(data[0], '?'), 'host': data[1] if len(data) > 1 else None}
    if cmd in (CMD_SET, CMD_SAVE, CMD_RESET, CMD_SLOT_STORE, CMD_SLOT_LOAD, CMD_CAPTURE, CMD_HANG):
        r = {'cmd': cmd, 'status': data[0], 'status_text': STATUS.get(data[0], '?')}
        if cmd == CMD_SET and data[0] == 2: r['offset'] = data[1] | (data[2] << 7)
        return r
    raise ProtocolError(f'unknown reply {cmd:#x}')


# ---- the saved record in flash (struct rec in translate.c) ----
REC_MAGIC = 0x46434B4D                               # b'MKCF'
REC_VERSION = 1
REC_SIZE = 288

def crc16(data, crc=0xFFFF):                         # CRC-16/CCITT-FALSE
    for b in data:
        crc ^= b << 8
        for _ in range(8): crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def build_record(cfg):
    cfg = bytes(cfg)
    data = cfg + bytes(276 - len(cfg))
    return struct.pack('<IHHHH', REC_MAGIC, REC_VERSION, len(cfg), crc16(cfg), 0xFFFF) + data

def parse_record(page, defaults=None):
    """The config the device would load from the saved page (page = the first 288 bytes at SAVE_PAGE), or None if there is no valid one."""
    page = bytes(page)
    magic, ver, ln, crc, _ = struct.unpack_from('<IHHHH', page, 0)
    if magic != REC_MAGIC or ver != REC_VERSION or not 4 <= ln <= CFG_SIZE or crc16(page[12:12 + ln]) != crc: return None
    c = bytearray(defaults if defaults is not None else default_cfg()); c[:ln] = page[12:12 + ln]
    return None if check(bytes(c)) is not None else fix_project(c)     # (as the firmware's rec_load)


# ---- presets: a named, complete config ----
PRESET_FILE_FORMAT = 'mmk3-presets-1'

def _groove_rider_2():
    """For the iOS app Groove Rider 2 (JimAudio), made from its manual and forum posts and tried on an iPad (2026-10-18): the app maps pads 1-16 to
    notes 36-51 in its Trigger / Slices layout (the default here), has CC 74 = filter cutoff, CC 91 / 92 = Part sends A / B, CC 120 = sounds
    off as defaults, and a "Last Knob Control" that lets one CC drive whichever knob was touched last. Transport and mute / solo cannot be
    controlled by a generic MIDI controller in the app (forum, unverified)."""
    c = bytearray(default_cfg())
    c[FIELDS['strip_cc'][0]] = 74                       # touch strip = filter cutoff
    c[FIELDS['enc_cc'][0]] = 20                         # encoder = Last Knob Control (set that CC to 20 in the app)
    c[FIELDS['enc_mode'][0]] = 2                        # relative, two's complement (the app auto-detects relative CCs)
    c[FIELDS['btn_cc'][0] + BUTTON_NAMES.index('Erase')] = 120   # Erase = sounds off (panic)
    c[FIELDS['btn_act'][0] + BUTTON_NAMES.index('Encoder Touch')] = ACT_NONE   # the knob's touch sensor sends CC 9 BEFORE the first turn, and the app's
    return bytes(c)                                     # Last Knob Control learned that instead of the turn (iPad test 2026-10-18); the push stays CC 8                                     # Solo / Mute keep NI's CC 91 / 92: hold to throw the Part into send A / B

def _app_preset(buttons, pad_base=36, btn_mode=0, enc=(7, 100), strip=1):
    """A preset for an app: every button sends nothing except those given as {name: (action, parameter)}, the encoder touch and push send
    nothing (an app's MIDI learn would grab the touch, found with Groove Rider 2), `enc` = (CC, start value) of the absolute encoder,
    `btn_mode` is global (0 gate, 1 toggle, 2 trigger) and applies to the buttons that send a CC."""
    c = bytearray(default_cfg(pad_base=pad_base, btn_mode=btn_mode))
    for k in range(41): c[FIELDS['btn_act'][0] + k] = ACT_NONE
    for name, (act, par) in buttons.items():
        k = BUTTON_NAMES.index(name); c[FIELDS['btn_act'][0] + k] = act; c[FIELDS['btn_cc'][0] + k] = par
    c[FIELDS['enc_cc'][0]], c[FIELDS['enc_init'][0]], c[FIELDS['enc_mode'][0]] = enc[0], enc[1], 1
    c[FIELDS['strip_cc'][0]] = strip
    return bytes(c)

def _cc(**kw): return {n.replace('_', ' '): (ACT_CC, v) for n, v in kw.items()}

def _maschine_modes():
    """NI's own pad modes on the device itself, with feedback on the screen (docs/native-features.md): Pad Mode = the drum layout (the configured
    pad notes), Keyboard = chromatic from C3 on pad 1, Fixed Vel (every note at the fixed velocity), Shift + Fixed Vel = 16 Velocities, Shift + Volume /
    Swing = next / previous velocity curve (kept across power cycles), Shift + Mute = panic, the arrows transpose by a semitone (an octave with Shift);
    Shift + Keyboard / Pad Mode = next / previous scale, Chords = chord mode, Shift + Chords / Select = next / previous chord type, Pitch / Mod / Perform = strip
    modes (pitch bend, mod wheel that holds its value with a bar, the configured CC, Notes = strum), Volume / Swing / Tempo = the encoder drives CC 7 / 10 / 11
    (press again to go back), Favorites / Browser = Program Change next / previous (Shift + Browser: back to 0), Project = the next preset slot, Tap = tap tempo (Shift: MIDI clock out), Note Repeat = arp /
    repeat (Shift: rate), Follow = arp pattern, Auto = octaves, Lock = latch (Shift: snapshot), Mute / Solo = mute / solo pads (Shift + Solo clears). Everything else is the default; the buttons used here no longer send their CC."""
    c = bytearray(default_cfg())
    def act(name, a, par=0xFF, shifted=False):
        k = BUTTON_NAMES.index(name)
        c[FIELDS['btn_act2' if shifted else 'btn_act'][0] + k] = a; c[FIELDS['btn_cc2' if shifted else 'btn_cc'][0] + k] = par
    act('Pad Mode', ACT_PADMODE); act('Keyboard', ACT_KEYS); act('Fixed Vel', ACT_FIXVEL); act('Fixed Vel', ACT_VEL16, shifted=True)
    act('Shift', ACT_SHIFT)
    act('Volume', ACT_CURVE, 0, shifted=True); act('Swing', ACT_CURVE, 1, shifted=True)
    act('Mute', ACT_PANIC, shifted=True)
    act('Left', ACT_TRANSPOSE, 63); act('Right', ACT_TRANSPOSE, 65)
    act('Left', ACT_TRANSPOSE, 52, shifted=True); act('Right', ACT_TRANSPOSE, 76, shifted=True)
    act('Chords', ACT_CHORDS); act('Chords', ACT_CHORDTYPE, 0, shifted=True); act('Select', ACT_CHORDTYPE, 1, shifted=True)   # phase 2: chords and scales (Select is also the sequencer's track select)
    act('Keyboard', ACT_SCALE, 0, shifted=True); act('Pad Mode', ACT_SCALE, 1, shifted=True)
    act('Pitch', ACT_STRIP, 1); act('Mod', ACT_STRIP, 2); act('Perform', ACT_STRIP, 0)                                     # the touch strip modes
    act('Volume', ACT_ENCTGT, 0); act('Swing', ACT_ENCTGT, 1); act('Tempo', ACT_ENCTGT, 2)                                  # what the encoder turns
    act('Favorites', ACT_PROGRAM, 0); act('Browser', ACT_PROGRAM, 1); act('Browser', ACT_PROGRAM, 2, shifted=True)          # Program Change: next, previous, Shift: back to 0
    act('Notes', ACT_STRIP, 3)                                                                                              # phase 3: strum
    act('Tap', ACT_TAP); act('Tap', ACT_CLOCKOUT, 0xFF, shifted=True)                                                       # tap tempo, Shift: MIDI clock out
    act('Note Repeat', ACT_ARP); act('Note Repeat', ACT_RATE, 0, shifted=True)                                              # arp / repeat, Shift: rate
    act('Follow', ACT_ARPTYPE, 0); act('Follow', ACT_ARPTYPE, 1, shifted=True)                                              # arp pattern next / previous
    act('Auto', ACT_ARPOCT); act('Auto', ACT_RATE, 1, shifted=True)                                                         # arp octaves, Shift: rate back
    act('Lock', ACT_LATCH); act('Lock', ACT_SNAP, 0, shifted=True)                                                          # latch, Shift: snapshot store / recall
    act('Mute', ACT_MUTE); act('Solo', ACT_SOLO); act('Solo', ACT_CLEAR, 0xFF, shifted=True)                                # mute / solo pads, Shift + Solo clears
    act('Step', ACT_STEP); act('Step', ACT_SEQRUN, 0, shifted=True)                                                         # the step sequencer: edit mode, Shift: start / stop
    act('Select', ACT_SEQSEL)                                                                                               #   hold + pad = pick the track
    act('Plug-in', ACT_SEQPAT, 0); act('Sampling', ACT_SEQPAT, 1)                                                           #   pattern next / previous (4 patterns)
    act('Erase', ACT_SEQCLEAR, 0); act('Erase', ACT_SEQCLEAR, 1, shifted=True)                                              #   clear the track, Shift: the pattern
    act('Restart', ACT_SEQRUN, 1); act('Restart', ACT_SEQSAVE, 0xFF, shifted=True)                                          #   restart, Shift: keep the patterns in flash
    act('Group', ACT_CHANNEL, 0); act('Group', ACT_CHANNEL, 1, shifted=True)                                                # MIDI channel next / previous (kept when unplugged)
    return bytes(c)

def fl_cfg():
    """The FL Studio mode's mapping, built into the firmware (build_patch.py writes it at CFG_FL_ADDR): the 'FL Studio' preset with Project as a plain CC."""
    return fix_project(_fl_studio(), fl=True)

def _beatmaker3():
    """BeatMaker 3 learns everything (Focus Actions: trigger pad 1-64, modes, macros 1-16, transport, bank / page / octave steps), so the numbers are free; what helps is
    that every control sends a distinct message once per press. Pads 1-16 = notes 0-15 (BeatMaker's Single Channel mode counts from note 0), Left / Right = the next / previous page of
    16 pads (pads 17-64 are pages 2-4), Plug-in / Sampling = the next / previous page of encoder targets: Volume / Swing / Tempo pick the target, 6 pages of 3 CCs (20-37) cover the
    16 macros, and a faster turn takes bigger steps."""
    c = bytearray(_app_preset({**_cc(Play=102, Stop=103, Rec=104, Tap=105, Restart=106, Mute=107, Solo=108, Select=109, Scene=110, Keyboard=111, Group=112, Pattern=113),
                               'Left': (ACT_PAGE, 1), 'Right': (ACT_PAGE, 0), 'Plug-in': (ACT_ENCPAGE, 0), 'Sampling': (ACT_ENCPAGE, 1),
                               'Volume': (ACT_ENCTGT, 0), 'Swing': (ACT_ENCTGT, 1), 'Tempo': (ACT_ENCTGT, 2)}, pad_base=0, btn_mode=2))
    c[FIELDS['enc_tgt_cc'][0]:FIELDS['enc_tgt_cc'][0] + 3] = bytes([20, 21, 22])
    c[FIELDS['enc_pages'][0]], c[FIELDS['enc_page_step'][0]], c[FIELDS['enc_accel'][0]] = 6, 3, 1
    return bytes(c)

FL_SHIFT_CC = {'Tap': 102, 'Left': 103, 'Right': 104, 'Plug-in': 105, 'Pattern': 106, 'Step': 107, 'Browser': 108, 'Erase': 109,
               'Play': 110, 'Encoder Push': 112, 'Rec': 113, 'Restart': 114, 'Solo': 115}   # what these buttons send with Shift held (the FL Studio script's second layer)
FL_SHIFT_REPORT_CC = 111                               # FL Studio mode: the firmware sends Shift down / up as this CC (translate.c FL_SHIFT_REPORT_CC)

def _fl_studio():
    """For the FL Studio device script (integrations/fl_studio/, docs/fl-studio.md). Every button the script uses sends NI's CC as a gate (the script sees
    press and release, so hold-gestures work), Play and Stop too; with Shift held a few send a second CC (FL_SHIFT_CC). The playing functions stay on the
    device, as in the preset 'Maschine-like modes': Pad Mode / Keyboard / Chords (Shift: scale and chord type), Fixed Vel (Shift: 16 Velocities), Note Repeat
    (Shift: rate), Auto (arp octaves), Lock (latch, Shift: snapshot), the strip modes on Pitch / Mod / Perform / Notes, Shift + Volume / Swing = velocity
    curve, Shift + Mute = panic. The encoder is relative (two's complement), so FL never jumps; its push is CC 8, its touch sends nothing."""
    c = bytearray(default_cfg(btn_mode=0, enc_mode=2))
    def act(name, a, par=0xFF, shifted=False):
        k = BUTTON_NAMES.index(name)
        c[FIELDS['btn_act2' if shifted else 'btn_act'][0] + k] = a; c[FIELDS['btn_cc2' if shifted else 'btn_cc'][0] + k] = par
    for name in ('Play', 'Stop'): act(name, ACT_CC, NI_BUTTON_CC[BUTTON_NAMES.index(name)])
    act('Shift', ACT_SHIFT); act('Encoder Touch', ACT_NONE)          # (FL's Link to controller would learn the touch instead of the turn)
    act('Pad Mode', ACT_PADMODE); act('Pad Mode', ACT_SCALE, 1, shifted=True)
    act('Keyboard', ACT_KEYS); act('Keyboard', ACT_SCALE, 0, shifted=True)
    act('Chords', ACT_CHORDS); act('Chords', ACT_CHORDTYPE, 0, shifted=True)
    act('Fixed Vel', ACT_FIXVEL); act('Fixed Vel', ACT_VEL16, shifted=True)
    act('Note Repeat', ACT_ARP); act('Note Repeat', ACT_RATE, 0, shifted=True)
    act('Auto', ACT_ARPOCT); act('Auto', ACT_RATE, 1, shifted=True)
    act('Lock', ACT_LATCH); act('Lock', ACT_SNAP, 0, shifted=True)
    act('Pitch', ACT_STRIP, 1); act('Mod', ACT_STRIP, 2); act('Perform', ACT_STRIP, 0); act('Notes', ACT_STRIP, 3)
    act('Volume', ACT_CURVE, 0, shifted=True); act('Swing', ACT_CURVE, 1, shifted=True)
    act('Mute', ACT_PANIC, shifted=True)
    for name, cc in FL_SHIFT_CC.items(): act(name, ACT_CC, cc, shifted=True)
    return bytes(c)

def builtin_presets():
    """The presets that come with the tool, as dicts with id, name, description and cfg (bytes). The browser page shows the same list
    (tools/ui/gen_data.py writes it into mmk3_data.js). Each has a `display_name`: what the device's screen shows when its slot is loaded."""
    presets = [
        {'id': 'default', 'name': 'Default',
         'description': "What the firmware starts with: Play and Stop send MIDI Start and Stop, every other button sends NI's Control Change numbers, "
                        "pads 1-16 play notes 36-51 (General MIDI drums), encoder CC 7, touch strip CC 1, MIDI channel 1, local lighting on.",
         'cfg': default_cfg()},
        {'id': 'maschine-modes', 'name': 'Maschine-like modes',
         'description': "The controller's own functions, with a message on the screen: Pad Mode (drum notes), Keyboard (C3 on pad 1) with 24 scales (Shift + Keyboard / Pad Mode), Chords with eight chord types (Shift + Chords / Select), "
                        "Fixed Vel, Shift + Fixed Vel = 16 Velocities, Shift + Volume / Swing = velocity curve (kept when unplugged), Shift + Mute = panic, the arrows transpose (Shift: an octave), "
                        "Pitch / Mod / Perform / Notes = strip modes, Volume / Swing / Tempo = what the encoder turns, Favorites / Browser = Program Change (Shift + Browser: back to 0), Project = the next preset slot on the device (in every preset), Tap = tap tempo (Shift: MIDI clock out), "
                        "Note Repeat = arp / repeat (Shift: rate) with Follow = pattern, Auto = octaves, Lock = latch, Mute / Solo = mute / solo pads. The buttons used here no longer send their CCs; everything else is as in Default.",
         'cfg': _maschine_modes()},
        {'id': 'groove-rider-2', 'name': 'Groove Rider 2',
         'description': "Tried on an iPad: pads (Trigger, Keys), strip (cutoff), encoder (Last Knob Control), Solo / Mute (send A / B throws). Pads 1-16 = notes 36-51, strip = CC 74, "
                        "encoder = relative CC 20 (its touch sensor sends nothing, or the app learns that instead of the turn; push = CC 8), Solo / Mute = CC 91 / 92, Erase = CC 120. "
                        "In the app: Midi In Device = the Mikro, Single channel 1. The transport cannot be mapped there. Project (top left) loads the device's next preset slot, as in every preset.",
         'cfg': _groove_rider_2()},
        {'id': 'korg-gadget-3', 'name': 'Korg Gadget 3 (draft)',
         'description': "Draft, from Korg's manual and forum posts, not tried. Pads 36-51 into the track whose MIDI button is lit; Play / Stop / Rec / Restart / Tap = CC 3 / 119 / 2 / 118 / 117 "
                        "(press only) for Gadget's Transport CC settings, which you enter there; encoder CC 7 (level), strip CC 1. Encoder push and touch send nothing. Keep channel 16 free. Project (top left) loads the device's next preset slot, as in every preset.",
         'cfg': _app_preset({**_cc(Play=3, Stop=119, Rec=2, Restart=118, Tap=117)}, btn_mode=2)},
        {'id': 'beatmaker-3', 'name': 'BeatMaker 3 (draft)',
         'description': "Draft, from the BeatMaker 3 manual, not tried. BeatMaker maps everything by MIDI learn, so learn each control once: Auto Learn the pads (notes 0-15; Left / Right turn the page, "
                        "so pads 17-64 are pages 2-4), transport Play / Stop / Rec / Tap (CC 102-105), mode buttons Mute / Solo / Select / Scene / Keyboard (CC 107-111), bank steps on Group / Pattern. "
                        "Macros 1-16: press Volume / Swing / Tempo to choose which of three CCs the encoder turns (20-22), Plug-in / Sampling change the page (6 pages: CC 20-37); a fast turn takes bigger steps. Project (top left) loads the device's next preset slot, as in every preset.",
         'cfg': _beatmaker3()},
        {'id': 'fl-studio', 'name': 'FL Studio',
         'description': "For FL Studio on a computer with the Ex-Machina device script (integrations/fl_studio): the script turns the buttons into FL's transport, channel, pattern, step sequencer, "
                        "mute / solo, mixer, plug-in and browser controls and shows them on the screen and the LEDs. Pad Mode / Keyboard / Chords, Fixed Vel, Note Repeat (arp), Auto, Lock and the strip modes "
                        "stay on the device (Shift for their second function, as in Maschine-like modes); Shift + Volume / Swing = velocity curve, Shift + Mute = panic. Pads 1-16 = notes 36-51 (FPC's layout), "
                        "encoder relative CC 7, strip CC 1. Without the script every button just sends NI's CC.",
         'display_name': 'FL STUDIO', 'cfg': _fl_studio()},
        {'id': 'cubasis-3', 'name': 'Cubasis 3 (draft)',
         'description': "Draft, from Steinberg's help and forum posts, not tried. Pads 36-51 (GM kits). Buttons send CC 102-114 once per press (Play, Stop, Rec, Restart, Left, Right, Mute, Solo, Select, Follow, Tap, "
                        "Browser, Favorites): learn each one in Cubasis (Selected Track Mode on); do not declare the port Mackie/HUI. Encoder CC 20 (volume, Catch-Up), strip CC 21 (pan).",
         'cfg': _app_preset({**_cc(Play=102, Stop=103, Rec=104, Restart=105, Left=106, Right=107, Mute=108, Solo=109, Select=110, Follow=111, Tap=112, Browser=113, Favorites=114)}, btn_mode=2, enc=(20, 100), strip=21)},
        {'id': 'fl-studio-mobile', 'name': 'FL Studio Mobile (draft)',
         'description': "Draft, from Image-Line's manual and forum posts, not tried. Pads 48-63 (its drum pads start at note 48). Play / Stop / Restart / Rec = MMC play / stop / rewind / record "
                        "(its only transport input). Group..Tempo, Mute, Solo = CC 20-31 toggles to learn onto parameters. Encoder CC 102, push CC 103, strip CC 1. Touch sends nothing (learn would grab it).",
         'cfg': _app_preset({**{n: (ACT_MMC, v) for n, v in (('Play', 2), ('Stop', 1), ('Restart', 5), ('Rec', 6))},
                             **_cc(Mute=20, Solo=21, Group=22, Pattern=23, Scene=24, Events=25, Variation=26, Duplicate=27, Select=28, Volume=29, Swing=30, Tempo=31, Encoder_Push=103)},
                            pad_base=48, btn_mode=1, enc=(102, 64))},
        {'id': 'garageband', 'name': 'GarageBand (draft)',
         'description': "Draft, from Apple's guide and old forum posts, not tried. GarageBand has no MIDI learn: pads 36-51 (GM drum kits; use 48 for keyboard sounds), strip = mod wheel CC 1, encoder = volume CC 7, "
                        "Note Repeat = sustain CC 64 while held, Play / Stop / Rec = MMC (a forum claim; transport is otherwise only by keyboard). Turn MPE off. Everything else sends nothing.",
         'cfg': _app_preset({**{n: (ACT_MMC, v) for n, v in (('Play', 2), ('Stop', 1), ('Rec', 6))}, **_cc(Note_Repeat=64)}, btn_mode=0)},
    ]
    for p in presets: p['display_name'] = preset_display_name(p); p['cfg'] = fix_project(p['cfg'])
    return presets

def preset_file(presets):
    """The JSON text of a preset file (what the browser page exports and imports)."""
    return json.dumps({'format': PRESET_FILE_FORMAT, 'presets': [{'name': p['name'], 'description': p.get('description', ''), 'display_name': preset_display_name(p), 'cfg': bytes(p['cfg']).hex()} for p in presets]}, indent=1)

def read_preset_file(text):
    """The presets in a preset file (list of dicts with name, description, cfg bytes). A config shorter than the current layout (an older
    tool) is laid over the defaults, like the firmware does with an older saved record. Raises ValueError for anything unusable."""
    j = json.loads(text)
    if j.get('format') != PRESET_FILE_FORMAT: raise ValueError('not a preset file of this tool')
    out = []
    for p in j['presets']:
        raw = bytes.fromhex(p['cfg'])
        if len(raw) > CFG_SIZE or len(raw) < 4: raise ValueError(f"preset {p.get('name')!r}: the config has {len(raw)} bytes")
        cfg = bytearray(default_cfg()); cfg[:len(raw)] = raw; cfg = bytearray(fix_project(cfg))
        bad = check(bytes(cfg))
        if bad is not None: raise ValueError(f"preset {p.get('name')!r}: byte {bad} is out of range")
        out.append({'name': str(p['name']), 'description': str(p.get('description', '')), 'cfg': bytes(cfg), **({'display_name': display_name(p['display_name'])} if p.get('display_name') else {})})
    return out

def find_preset(name, files=()):
    """A preset by id or name (case-insensitive): the built-in ones first, then those in the given preset files."""
    pool = builtin_presets()
    for f in files: pool += read_preset_file(open(f).read())
    for p in pool:
        if name.lower() in (p.get('id', '').lower(), p['name'].lower()): return p
    raise KeyError(name)


# ---- the client (mido) ----
class Device:
    def __init__(self, name=None, timeout=3.0):
        import mido
        self.mido, self.timeout = mido, timeout
        name_in = name or next((n for n in mido.get_input_names() if 'aschine' in n or 'Mikro' in n), None)
        name_out = name or next((n for n in mido.get_output_names() if 'aschine' in n or 'Mikro' in n), None)
        if not name_in or not name_out: raise SystemExit('no Maschine Mikro MK3 among the MIDI ports')
        self.inp, self.out = mido.open_input(name_in), mido.open_output(name_out)

    def request(self, msg, cmd, retries=2):
        """Sends a request and waits for its reply; a missing reply is asked again (the device drops a request that arrives while it is busy,
        and a long series of PEEKs showed it can happen). Every request type is safe to repeat."""
        for attempt in range(retries + 1):
            for _ in self.inp.iter_pending(): pass       # drop anything old
            self.out.send(self.mido.Message('sysex', data=msg[1:-1]))
            t0 = time.monotonic()
            while time.monotonic() - t0 < self.timeout:
                for m in self.inp.iter_pending():
                    if m.type == 'sysex' and bytes(m.data[:3]) == MANUFACTURER and len(m.data) > 3 and m.data[3] == cmd + REPLY:
                        return parse_reply(bytes(m.data))
                time.sleep(0.002)
        raise ProtocolError(f'no reply to command {cmd:#x} within {self.timeout} s (asked {retries + 1} times)')

    def info(self): return self.request(info_request(), CMD_INFO)
    def get(self): return self.request(get_request(), CMD_GET)['cfg']
    def set(self, cfg): return self.request(set_request(cfg), CMD_SET)
    def save(self): return self.request(save_request(), CMD_SAVE)
    def reset(self, erase=False): return self.request(reset_request(erase), CMD_RESET)
    def slots(self): return self.request(slots_request(), CMD_SLOTS)['used']
    def slot_names(self): return self.request(slots_request(), CMD_SLOTS)['names']
    def slot_store(self, n, name=None): return self.request(slot_store_request(n, name), CMD_SLOT_STORE)
    def slot_load(self, n): return self.request(slot_load_request(n), CMD_SLOT_LOAD)

    def hang(self):
        """The watchdog test: the device confirms, then stops until its watchdog resets it. Sent once and never retried: a retry would reach the
        restarted device and hang it again, and three watchdog resets in a row put it into DFU mode."""
        return self.request(hang_request(), CMD_HANG, retries=0)

    def peek(self, addr, length):
        """Bytes from the device's memory (any length: asked for in pieces of 64). Raises ProtocolError if the firmware refuses a range."""
        out = bytearray()
        while length > 0:
            n = min(64, length); r = self.request(peek_request(addr + len(out), n), CMD_PEEK)
            if r['status'] != 0: raise ProtocolError(f'the device refuses to read {addr + len(out):#x} ({n} bytes): status {r["status"]}')
            out += r['data'][:n]; length -= n
        return bytes(out)


def _button_index(name):
    if name.isdigit(): return int(name)
    low = [n.lower() for n in BUTTON_NAMES]
    if name.lower() in low: return low.index(name.lower())
    raise SystemExit(f'unknown button {name!r}; names: ' + ', '.join(BUTTON_NAMES))

def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ('-h', '--help'): print(__doc__); return 0
    cmd, rest = a[0], a[1:]
    dev = Device()
    def show(r): print(json.dumps({k: (v.hex() if isinstance(v, bytes) else v) for k, v in r.items()}))
    if cmd == 'info': show(dev.info())
    elif cmd == 'get':
        d = to_dict(dev.get())
        if rest: json.dump(d, open(rest[0], 'w'), indent=1); print('written', rest[0])
        else: print(json.dumps(d))
    elif cmd == 'set': show(dev.set(from_dict(json.load(open(rest[0])), base=dev.get())))
    elif cmd == 'button':
        shifted = '--shift' in rest; rest = [r for r in rest if r != '--shift']
        idx, action = _button_index(rest[0]), rest[1].lower()
        cfg = bytearray(dev.get())
        if action not in ACTION_NAMES: raise SystemExit('action: ' + ', '.join(ACTION_NAMES))
        if idx == BTN_PROJECT: raise SystemExit('Project always loads the next preset slot (fixed in the firmware)')
        cfg[FIELDS['btn_act2' if shifted else 'btn_act'][0] + idx] = ACTION_NAMES.index(action)
        par = cfg_par = None
        if action in ('cc', 'note', 'mmc'): par = int(rest[2])
        elif action in ('curve', 'scale', 'chordtype', 'arptype', 'rate', 'channel', 'page', 'encpage'): par = 1 if len(rest) > 2 and rest[2].lower().startswith('prev') else 2 if len(rest) > 2 and rest[2].lower() in ('first', 'reset') and action in ('page', 'encpage') else 0
        elif action in ('strip', 'enctgt', 'program', 'snap'): par = int(rest[2]) if len(rest) > 2 else 0
        elif action == 'slot': par = 8 if len(rest) < 3 or rest[2] == 'next' else int(rest[2]) - 1 if rest[2] in '1234' else 3 + int(rest[2][5:]) if rest[2][:5] == 'store' and rest[2][5:] in '1234' else 8
        elif action == 'transpose': par = 64 + int(rest[2])
        elif shifted and action == 'none': par = 0xFF
        if par is not None: cfg[FIELDS['btn_cc2' if shifted else 'btn_cc'][0] + idx] = par
        show(dev.set(bytes(cfg)))
    elif cmd == 'pad':
        cfg = bytearray(dev.get()); cfg[FIELDS['pad_note'][0] + PAD_LABEL.index(int(rest[0]))] = int(rest[1]); show(dev.set(bytes(cfg)))
    elif cmd == 'preset':
        files = [r for r in rest[2:] if not r.startswith('--')]
        if rest[0] == 'list':
            files = [r for r in rest[1:] if not r.startswith('--')]
            for p in builtin_presets() + [q for f in files for q in read_preset_file(open(f).read())]: print(f"{p.get('id', '-'):12s} {p['name']}: {p['description']}")
        elif rest[0] == 'apply':
            try: p = find_preset(rest[1], files)
            except KeyError: raise SystemExit(f'no preset {rest[1]!r}; see: mmk3_config.py preset list')
            show(dev.set(p['cfg']))
            if '--save' in rest: show(dev.save())
        else: raise SystemExit('preset list | preset apply NAME [FILE] [--save]')
    elif cmd == 'hal':                                   # our own hardware drivers (hal.c): hal [all | none | mask]; RAM only, stock again after a power cycle
        m = (HAL_ALL | HAL2_ALL << 8) if rest and rest[0] == 'all' else 0 if rest and rest[0] == 'none' else int(rest[0], 0) if rest else None
        if m is None: raise SystemExit('hal all | none | <mask: 1 LEDs, 2 display, 4 buttons, 8 strip, 16 pads, 32 reports, 64 LED colours, 256 main loop, 512 SysTick>')
        print(json.dumps(dev.request(hal_request(m & 0x7F, 0, m >> 8), CMD_HAL)))
    elif cmd == 'slot':
        if rest[0] == 'list': r = dev.request(slots_request(), CMD_SLOTS); print(json.dumps({'slots_used': r['used'], 'names': r['names']}))
        elif rest[0] == 'store' and len(rest) > 1 and rest[1] in '1234': show(dev.slot_store(int(rest[1]) - 1, ' '.join(rest[2:]) or None))
        elif rest[0] == 'load' and len(rest) > 1 and rest[1] in '1234': show(dev.slot_load(int(rest[1]) - 1))
        else: raise SystemExit('slot list | slot store 1..4 [name] | slot load 1..4')
    elif cmd == 'mode':                                  # mode [standalone | fl]: which mode the device is in, or switch (Shift + Project on the device)
        if rest and rest[0] not in MODE_NAMES: raise SystemExit('mode [standalone | fl]')
        print(json.dumps(dev.request(mode_request(rest[0] if rest else None), CMD_MODE)))
    elif cmd == 'host':                                  # host mode: host [screen] [raw] [quiet] | host off (what a DAW script sets; RAM only)
        f = 0
        words = {'screen': HOST_SCREEN, 'raw': HOST_RAW, 'quiet': HOST_QUIET, 'off': 0}
        for w in rest: f |= words[w.lower()] if w.lower() in words else int(w, 0)
        show(dev.request(host_request(f), CMD_HOST))
    elif cmd == 'text':                                  # text LINE WORDS... (line 1..4) | text clear: a line on the screen while host mode 'screen' is on
        if rest and rest[0] == 'clear': dev.out.send(dev.mido.Message('sysex', data=text_request(None, '')[1:-1]))
        elif rest and rest[0] in '1234': dev.out.send(dev.mido.Message('sysex', data=text_request(int(rest[0]) - 1, ' '.join(rest[1:]).ljust(TEXT_COLS))[1:-1]))
        else: raise SystemExit('text 1..4 WORDS | text clear')
    elif cmd == 'save': show(dev.save())
    elif cmd == 'reset': show(dev.reset('--erase' in rest))
    else: raise SystemExit(f'unknown command {cmd!r}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
