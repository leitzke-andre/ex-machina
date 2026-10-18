#!/usr/bin/env python3
"""Apply the Mikro MK3 USB-MIDI patch to a carved firmware image (flash base 0x08003000).
Usage: build_patch.py <fw.bin> <out.bin> [--stage 1|2|3] [--vid --pid --bcd --max-power]
         [--pad-base 36] [--transport realtime|cc|mmc] [--local-leds on|off] [--pad-colour 0..17] [--strip-colour 0..17]
         [--enc-mode absolute|relative-offset|relative] [--enc-init N] [--btn-mode gate|toggle|trigger]
         [--vel-curve NAME | --vel-table FILE] [--vel-shift 1..8] [--sens N] [--boot-ms N]
Needs clang with the ARM target and pyelftools. The output contains NI code: keep it local.

Patches (all addresses are flash addresses in the stock image):
  1. 0x08004036  bl ring-enqueue  -> mmk3_translate   HID input reports -> USB-MIDI packets (and the local LED feedback)
  2. 0x08008cf8  bl board-init    -> mmk3_init        reset translator state, repoint device/config descriptors in RAM
  3. 0x08008cfc  bl stage-2 init  -> mmk3_boot2       sensitivity / boot delay overrides, resting state of the local LEDs
  4. 0x08004aba  bl out-parser    -> mmk3_rx          host MIDI Note On/Off, CC, SysEx -> LEDs and display, else stock parser
  5. 0x08008526  asrs r1,r5,#3    -> movs r1,#0       EP1 type interrupt (0x600) -> bulk (0)
  6. 0x08008460  interface check  -> accept interfaces 0..2 in Get_Interface_Setting
  7. 0x08008d06  bl watchdog kick -> mmk3_tick        main-loop tick: re-applies the LEDs once the stock startup is over
  new flash: config block, device + configuration descriptors, the velocity curve tables, display font and texts, translator code (last)
Everything else (ADC/DMA pad scan, linearisation, button matrix, strip I2C, LED chips, DFU) is untouched."""
import argparse, os, re, struct, subprocess, sys, tempfile
from elftools.elf.elffile import ELFFile

BASE = 0x08003000
STOCK_LEN = 0x9DC8
SAVE_PAGE = 0x0801EC00               # the page the run-time config is saved to (translate.c); the image must end below it
SLOT_BASE = 0x0801D800                # the four preset slots (one page each), the step pattern page and the save page follow; the image must end below this
PAT_PAGE = 0x0801E800
APP_LIMIT = SLOT_BASE
CFG_ADDR = 0x0800CE00
CFG_SIZE = 274                       # sizeof(struct cfg) in translate.c
# Layout of the new flash content: fixed-size data first, the code LAST, so the code can grow and the image simply ends with it.
DESC_DEV_ADDR = 0x0800CF20           # 256 bytes are reserved for the config block at CFG_ADDR
DESC_CFG_ADDR = 0x0800CF40
VEL_TABLE_ADDR = 0x0800D000          # 9 curves x 256 bytes: Note On velocity tables (VEL_TABLES in translate.c)
CURVE_COUNT_ADDR = 0x0800D900        # one byte: how many curves ACT_CURVE steps through (8, or 9 with a custom table)
FONT_ADDR = 0x0800D940               # 64 characters x 5 column bytes
TXT_ADDR = 0x0800DA80                # the display texts, 16 bytes each (at most 192)
SCALES_ADDR = 0x0800E6C0             # 24 scales as little-endian 16-bit masks (bit n = semitone n)
CODE_ADDR = 0x0800E700

def c_define(name):
    """The first hex literal of `#define NAME ...` in translate.c: the C source is the one place that knows the addresses it uses."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translate.c')).read()
    return int(re.search(r'#define\s+' + name + r'\b[^\n]*?(0x[0-9A-Fa-f]+)', src).group(1), 16)
STATE_ADDR = c_define('ST_ADDR')                 # translator / LED / request state in RAM
assert (c_define('CFG_DEFAULTS'), c_define('VEL_TABLES'), c_define('CURVE_COUNT'), c_define('FONT_ADDR'), c_define('TXT_ADDR'), c_define('SCALES'), c_define('DESC_DEV_ADDR'),
        c_define('DESC_CFG_ADDR'), c_define('SAVE_PAGE'), c_define('SLOT_BASE'), c_define('PAT_PAGE')) == \
       (CFG_ADDR, VEL_TABLE_ADDR, CURVE_COUNT_ADDR, FONT_ADDR, TXT_ADDR, SCALES_ADDR, DESC_DEV_ADDR, DESC_CFG_ADDR, SAVE_PAGE, SLOT_BASE, PAT_PAGE), 'the layout constants of build_patch.py and translate.c differ'

# The config block layout, its defaults and the action / LED-flag numbers live in mmk3_config.py (the host side of the protocol)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mmk3_config import (ACT_CC, ACT_NOTE, ACT_START, ACT_CONT, ACT_STOP, ACT_MMC, ACT_NONE, BTN_PLAY, BTN_REC, BTN_STOP,
                         LF_BTN_IDLE, LF_BTN_PRESS, LF_PAD_IDLE, LF_PAD_HIT, LF_STRIP, PAD_LABEL, NI_BUTTON_CC, FW_NAME as _FW_NAME, FW_VERSION, SCALE_NAMES, ARP_TYPES, ARP_RATES, default_cfg, CFG_SIZE as _CFG_SIZE)
assert _CFG_SIZE == CFG_SIZE, 'mmk3_config.CFG_SIZE and build_patch.CFG_SIZE differ'
assert c_define('FW_VERSION') == FW_VERSION, 'FW_VERSION differs between mmk3_config.py and translate.c'

def bl(src, dst):
    off = dst - (src + 4)
    s = (off >> 24) & 1
    i1 = (off >> 23) & 1; i2 = (off >> 22) & 1
    j1 = (~(i1 ^ s)) & 1; j2 = (~(i2 ^ s)) & 1
    hw1 = 0xF000 | (s << 10) | ((off >> 12) & 0x3FF)
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | ((off >> 1) & 0x7FF)
    return struct.pack('<HH', hw1, hw2)

def compile_c(here, work):
    obj = os.path.join(work, 'translate.o')
    subprocess.check_call(['clang', '--target=thumbv7m-none-eabi', '-mcpu=cortex-m3', '-Os', '-ffreestanding',
                           '-fno-builtin', '-fno-stack-protector', '-Wall', '-c',
                           os.path.join(here, 'translate.c'), '-o', obj])
    with open(obj, 'rb') as f:
        elf = ELFFile(f)
        text = elf.get_section_by_name('.text')
        for n in ('.rel.text', '.rela.text', '.rodata', '.data'):
            sec = elf.get_section_by_name(n)
            if sec is not None and sec.data_size:
                raise SystemExit(f'translate.o has {n}; use fixed addresses and no tables')
        syms = {s.name: s['st_value'] & ~1 for s in elf.get_section_by_name('.symtab').iter_symbols()}
        return text.data(), syms

# NI's velocity curves (Controller Editor 2.8.2, PadControl::calcPadVelocity_f, read from the decompiled jump table; the
# names are the editor's menu labels). Slots 0..7 of its VelocityCurve enum, x = pad value normalised to 0..1, t = 1 - x:
#   Hard n: a*x + (1-a)*x^3        Soft n: 1 - (a*t + (1-a)*t^3)        a = 0.7, 0.4, 0.1 for n = 1, 2, 3
#   Linear: x (NI's default, slot 3)                                    fixed: constant 1.0 (slot 7)
VEL_CURVES = ('soft3', 'soft2', 'soft1', 'linear', 'hard1', 'hard2', 'hard3', 'fixed')
_BLEND = {'1': 0.7, '2': 0.4, '3': 0.1}

def vel_curve(name, x):
    if name == 'linear': return x
    if name == 'fixed': return 1.0
    a, t = _BLEND[name[-1]], 1.0 - x
    if name.startswith('hard'): return a * x + (1 - a) * x ** 3
    return 1.0 - (a * t + (1 - a) * t ** 3)

def vel_table(name):
    """256 bytes: Note On velocity for table index i = (12-bit value) >> (vel_shift - 1), so i / 256 is the normalised value.
    floor(128 * f(x)) at the bin centre: 'linear' is exactly `value >> 5` at vel_shift 5, what the patch did before curves."""
    return bytes(min(127, int(128 * vel_curve(name, (i + 0.5) / 256))) for i in range(256))

def read_vel_table(path):
    """Custom curve: 128 integers 0..127 (output velocity for each input velocity, i.e. value >> 5 at vel_shift 5) or 256
    (index = value >> 4); separated by whitespace or commas, '#' starts a comment."""
    text = ''.join(l.split('#')[0] + ' ' for l in open(path).read().splitlines())
    try: vals = [int(v, 0) for v in text.replace(',', ' ').split()]
    except ValueError as e: raise SystemExit(f'{path}: {e}')
    if len(vals) not in (128, 256) or not all(0 <= v <= 127 for v in vals):
        raise SystemExit(f'{path}: need 128 or 256 integers in 0..127, found {len(vals)}')
    return bytes(v for v in vals for _ in range(2)) if len(vals) == 128 else bytes(vals)

# The display font: the classic 5 x 7 dot-matrix font for ASCII 32..95 (space to underscore; lower case is shown as upper case), five column
# bytes per character, bit 0 = top row.
FONT = bytes.fromhex(
    '0000000000' '00005f0000' '0007000700' '147f147f14' '242a7f2a12' '2313086462' '3649562050' '0000070000'     # space ! " # $ % & '
    '001c224100' '0041221c00' '14083e0814' '08083e0808' '0050300000' '0808080808' '0060600000' '2010080402'     # ( ) * + , - . /
    '3e5149453e' '00427f4000' '4261514946' '2141454b31' '1814127f10' '2745454539' '3c4a494930' '0171090503'     # 0 1 2 3 4 5 6 7
    '3649494936' '064949291e' '0036360000' '0056360000' '0814224100' '1414141414' '0041221408' '0201510906'     # 8 9 : ; < = > ?
    '324979413e' '7e1111117e' '7f49494936' '3e41414122' '7f4141221c' '7f49494941' '7f09090901' '3e41494979'     # @ A B C D E F G
    '7f0808087f' '00417f4100' '2040413f01' '7f08142241' '7f40404040' '7f020c027f' '7f0408107f' '3e4141413e'     # H I J K L M N O
    '7f09090906' '3e4151215e' '7f09192946' '4649494931' '01017f0101' '3f4040403f' '1f2040201f' '3f4038403f'     # P Q R S T U V W
    '6314081463' '0708700807' '6151494543' '007f414100' '0204081020' '0041417f00' '0402010204' '4040404040')     # X Y Z [ \\ ] ^ _
assert len(FONT) == 64 * 5, len(FONT)

# The texts of the display messages, in the order of the enum in translate.c (checked by test_modes.py). At most 15 characters each.
TEXTS = {
    'T_PADMODE': 'PAD MODE', 'T_KEYBOARD': 'KEYBOARD', 'T_FIXVEL': 'FIXED VEL', 'T_VEL16': '16 VELS', 'T_VELOCITY': 'VELOCITY', 'T_TRANSPOSE': 'TRANSPOSE',
    'T_PANIC': 'PANIC', 'T_GROUP': 'GROUP', 'T_ON': 'ON', 'T_OFF': 'OFF', 'T_ALLOFF': 'ALL NOTES OFF', 'T_BASE': 'BASE', 'T_ROOT': 'ROOT',
    **{f'T_NOTE{i}': n for i, n in enumerate(['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'])},
    **{f'T_CURVE{i}': n for i, n in enumerate(['SOFT 3', 'SOFT 2', 'SOFT 1', 'LINEAR', 'HARD 1', 'HARD 2', 'HARD 3', 'FIXED', 'CUSTOM'])},
    'T_CHORDS': 'CHORDS', 'T_SCALE': 'SCALE', 'T_CHORD': 'CHORD TYPE', 'T_ENCODER': 'ENCODER', 'T_STRIP': 'STRIP', 'T_PITCH': 'PITCH BEND', 'T_MOD': 'MOD WHEEL',
    'T_NORMAL': 'CONFIGURED CC', 'T_PROGRAM': 'PROGRAM', 'T_PC': 'PC', 'T_VALUE': 'VALUE', 'T_CC': 'CC',
    'T_TRIAD': 'TRIAD', 'T_SEVENTH': 'SEVENTH', 'T_SUS2': 'SUS2', 'T_SUS4': 'SUS4', 'T_POWER': 'POWER',
    **{f'T_SCALE{i}': n.upper() for i, n in enumerate(SCALE_NAMES)},
    'T_PAGE': 'PAGE', 'T_ENCPAGE': 'ENC PAGE', 'T_STEP': 'STEP', 'T_TRK': 'TRK', 'T_PAT': 'PAT', 'T_RUN': 'RUN', 'T_STOP': 'STOP', 'T_TRACK': 'TRACK', 'T_PATTERN': 'PATTERN', 'T_CLEAR': 'CLEAR', 'T_PATTERNS': 'PATTERNS', 'T_CHANNEL': 'CHANNEL', 'T_SLOT': 'SLOT', 'T_LOADED': 'LOADED', 'T_SAVED': 'SAVED', 'T_EMPTY': 'EMPTY', 'T_ERROR': 'FLASH ERROR', 'T_EXNAME': _FW_NAME.upper(), 'T_VER': f'V{FW_VERSION}', 'T_M0': 'DRUMS', 'T_M1': 'KEYS', 'T_M2': 'CHORDS', 'T_CH': 'CH', 'T_CLK': 'CLK', 'T_SEQ': 'SEQ',
    'T_ARP': 'ARP', 'T_ARPTYPE': 'ARP TYPE', 'T_RATE': 'RATE', 'T_OCT': 'OCTAVES', 'T_LATCH': 'LATCH', 'T_TEMPO': 'TEMPO', 'T_BPM': 'BPM', 'T_CLOCK': 'CLOCK OUT',
    'T_MUTE': 'MUTE', 'T_SOLO': 'SOLO', 'T_CLEARED': 'CLEARED', 'T_LOCK': 'LOCK', 'T_STORED': 'STORED', 'T_RECALLED': 'RECALLED', 'T_EXT': 'EXT CLOCK', 'T_STRUM': 'STRUM NOTES',
    **{f'T_AT{i}': n.upper() for i, n in enumerate(ARP_TYPES)}, **{f'T_RATE{i}': n for i, n in enumerate(ARP_RATES)},
}

# The scales: the semitones above the root (bit n = n semitones); the order is mmk3_config.SCALE_NAMES.
SCALE_SEMITONES = [
    range(12), (0, 2, 4, 5, 7, 9, 11), (0, 2, 3, 5, 7, 8, 10), (0, 2, 3, 5, 7, 8, 11), (0, 2, 3, 5, 7, 9, 11), (0, 2, 3, 5, 7, 9, 10), (0, 1, 3, 5, 7, 8, 10),
    (0, 2, 4, 6, 7, 9, 11), (0, 2, 4, 5, 7, 9, 10), (0, 1, 3, 5, 6, 8, 10), (0, 2, 4, 7, 9), (0, 3, 5, 7, 10), (0, 3, 5, 6, 7, 10), (0, 2, 4, 6, 8, 10),
    (0, 2, 3, 5, 6, 8, 9, 11), (0, 1, 3, 4, 6, 7, 9, 10), (0, 2, 3, 6, 7, 8, 11), (0, 1, 4, 5, 7, 8, 10), (0, 1, 4, 5, 7, 8, 11), (0, 2, 3, 7, 8),
    (0, 1, 5, 7, 10), (0, 2, 3, 4, 7, 9), (0, 2, 4, 5, 7, 9, 10, 11), (0, 1, 3, 5, 7, 8, 11)]
assert len(SCALE_SEMITONES) == len(SCALE_NAMES) == 24
SCALES = [sum(1 << n for n in sc) for sc in SCALE_SEMITONES]
def scales_blob(): return b''.join(struct.pack('<H', m) for m in SCALES)

def text_blob():
    """The texts as 16-byte NUL padded slots in the order of the C enum (the one place the order is defined is translate.c)."""
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'translate.c')).read()
    names = re.findall(r'\bT_[A-Z0-9]+\b', re.search(r'enum \{ T_PADMODE.*?\};', src, re.S).group(0))
    assert names[-1] == 'T_COUNT', names[-3:]
    names = names[:-1]
    assert sorted(names) == sorted(TEXTS), (set(names) ^ set(TEXTS))
    assert len(names) <= 192 and all(len(TEXTS[n]) <= 15 for n in names)
    return b''.join(TEXTS[n].encode().ljust(16, b'\0') for n in names), names

def descriptors(vid, pid, bcd, max_ma):
    dev = struct.pack('<BBHBBBBHHHBBBB', 18, 1, 0x0200, 0, 0, 0, 64, vid, pid, bcd, 1, 2, 3, 1)
    cfg = bytearray()
    cfg += bytes([9, 4, 0, 0, 0, 1, 1, 0, 0])                     # interface 0: Audio Control
    cfg += bytes([9, 0x24, 1, 0, 1, 9, 0, 1, 1])                  #   header, bcdADC 1.0, streaming iface 1
    cfg += bytes([9, 4, 1, 0, 2, 1, 3, 0, 0])                     # interface 1: MIDI Streaming, 2 bulk EPs
    ms = bytearray()
    ms += bytes([6, 0x24, 2, 2, 1, 0])                            #   IN  jack, external, id 1
    ms += bytes([9, 0x24, 3, 1, 2, 1, 1, 1, 0])                   #   OUT jack, embedded, id 2 <- 1 (to host)
    ms += bytes([6, 0x24, 2, 1, 3, 0])                            #   IN  jack, embedded, id 3 (from host)
    ms += bytes([9, 0x24, 3, 2, 4, 1, 3, 1, 0])                   #   OUT jack, external, id 4 <- 3
    ms_len = 7 + len(ms) + 2 * (9 + 5)
    cfg += bytes([7, 0x24, 1, 0, 1]) + struct.pack('<H', ms_len) + ms
    cfg += bytes([9, 5, 0x01, 2, 64, 0, 0, 0, 0]) + bytes([5, 0x25, 1, 1, 3])   # EP1 OUT bulk -> jack 3
    cfg += bytes([9, 5, 0x81, 2, 64, 0, 0, 0, 0]) + bytes([5, 0x25, 1, 1, 2])   # EP1 IN  bulk <- jack 2
    cfg += bytes([9, 4, 2, 0, 0, 0xFE, 1, 1, 0])                  # interface 2: DFU runtime (unchanged)
    cfg += bytes([9, 0x21, 0x09, 0xFF, 0x00, 0x40, 0x00, 0x10, 0x01])
    head = bytes([9, 2]) + struct.pack('<H', 9 + len(cfg)) + bytes([3, 1, 0, 0x80, max_ma // 2])
    return dev, head + bytes(cfg)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    # Defaults keep the stock IDs so NI's own updater can still find the device and restore stock
    # firmware. Pass other IDs (e.g. 0x1209/0x0001, the pid.codes test pair) to avoid NI drivers.
    ap.add_argument('--vid', type=lambda x: int(x, 0), default=0x17CC)
    ap.add_argument('--pid', type=lambda x: int(x, 0), default=0x1700)
    # NI's updater only offers "update" when bcdDevice < 0x0052 (MM3UpdaterUpgradeLogic::getDeviceInfo),
    # so a patched device must report an older version to stay restorable with the stock updater.
    ap.add_argument('--bcd', type=lambda x: int(x, 0), default=0x0051)
    ap.add_argument('--max-power', type=int, default=480, help='declared bus current in mA (stock: 480)')
    ap.add_argument('--stage', type=int, choices=(1, 2, 3), default=3,
                    help='hardware-day ladder: 1 = stock image with only bcdDevice lowered; 2 = stage 1 + the new flash content '
                         '(config, code, descriptors) appended but unused, to test size acceptance; 3 = full patch (default)')
    ap.add_argument('--pad-base', type=int, default=36, help="MIDI note of pad 1 (default 36 = General MIDI drum layout, what GarageBand's and most iOS drum kits listen to; NI's own MIDI mode and Controller Editor template use 12)")
    ap.add_argument('--transport', choices=('realtime', 'cc', 'mmc'), default='realtime',
                    help="what Play / Stop (and Rec for mmc) send: realtime = MIDI Start / Stop (Rec stays CC 58); cc = NI's Control Changes only; mmc = MIDI Machine Control SysEx")
    ap.add_argument('--local-leds', choices=('on', 'off'), default='on',
                    help='the device lights itself: assigned buttons rest dimly lit and brighten while pressed (toggle: while on), pads rest in --pad-colour and flash when hit')
    ap.add_argument('--pad-colour', type=int, default=11, choices=range(0, 18), metavar='0..17',
                    help='pad colour for the local LEDs: 1 red, 2 orange, 3 light orange, 4 warm yellow, 5 yellow, 6 lime, 7 green, 8 mint, 9 cyan, 10 turquoise, 11 blue, 12 plum, 13 violet, 14 purple, 15 magenta, 16 fuchsia, 17 or 0 white')
    ap.add_argument('--strip-colour', type=int, default=17, choices=range(0, 18), metavar='0..17',
                    help='colour of the touch-strip LED that follows the finger (same numbering as --pad-colour; default 17 = white; part of --local-leds)')
    ap.add_argument('--enc-init', type=int, default=0, help='starting value of the absolute encoder (NI template: 0)')
    ap.add_argument('--btn-mode', choices=('gate', 'toggle', 'trigger'), default='gate',
                    help="gate = 127 on press / 0 on release; toggle = NI's default (127 / 0 on alternate presses); trigger = 127 on press only")
    ap.add_argument('--enc-mode', choices=('absolute', 'relative-offset', 'relative'), default='absolute',
                    help="NI's three Control Change modes: absolute 0..127; relative-offset = 65/63 around 64; relative = 1/127 (two's complement)")
    ap.add_argument('--vel-curve', choices=VEL_CURVES, default='linear',
                    help="Note On velocity curve, NI's Controller Editor presets (soft3 = softest ... hard3 = hardest, fixed = always 127); NI's default is linear")
    ap.add_argument('--vel-table', metavar='FILE', help='custom velocity curve instead of --vel-curve: 128 or 256 integers 0..127 (see read_vel_table)')
    ap.add_argument('--vel-shift', type=int, choices=range(1, 9), default=5,
                    help='gain in front of the velocity curve and of the pressure messages: smaller = more sensitive, each step doubles (default 5: value12 >> 5 for the linear curve)')
    ap.add_argument('--sens', type=int, default=0xFF, help='pad sensitivity 0..100 to apply at boot (stock ROM default 80); omit to keep the stored value')
    ap.add_argument('--boot-ms', type=lambda x: int(x, 0), default=0xFFFF, help='shorten the startup countdown (stock 6000 ms; the stock LED fade-in ends it after about 1.8 s anyway; omit to keep)')
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    img = bytearray(open(a.src, 'rb').read()[:STOCK_LEN])

    def put(addr, data, expect=None):
        off = addr - BASE
        if off > len(img): img.extend(b'\xff' * (off - len(img)))
        if expect is not None: assert bytes(img[off:off + len(expect)]) == expect, f'unexpected bytes at {addr:#x}'
        img[off:off + len(data)] = data

    with tempfile.TemporaryDirectory() as work:
        code, syms = compile_c(here, work)
    texts, _ = text_blob()
    assert CFG_ADDR + CFG_SIZE <= DESC_DEV_ADDR and VEL_TABLE_ADDR + 9 * 256 <= CURVE_COUNT_ADDR and CURVE_COUNT_ADDR + 4 <= FONT_ADDR \
        and FONT_ADDR + len(FONT) <= TXT_ADDR and TXT_ADDR + 192 * 16 <= SCALES_ADDR and SCALES_ADDR + 48 <= CODE_ADDR and len(texts) <= 192 * 16, 'fixed-size data overlaps'
    assert CODE_ADDR + len(code) <= APP_LIMIT, 'image does not fit the application area'
    put(0x08003000 + 0x5d54 + 12, struct.pack('<H', a.bcd), bytes.fromhex('5200'))   # stock device descriptor bcdDevice
    dev, cfg = descriptors(a.vid, a.pid, a.bcd, a.max_power)
    assert len(cfg) == 119, len(cfg)             # must match DESC_CFG_LEN in translate.c
    assert DESC_CFG_ADDR + len(cfg) <= VEL_TABLE_ADDR, 'descriptors overlap the velocity table'
    # the eight curves of NI's editor, then a ninth slot: the custom table (--vel-table), else a copy of linear (ACT_CURVE then steps through 8)
    vtabs = [vel_table(n) for n in VEL_CURVES] + [read_vel_table(a.vel_table) if a.vel_table else vel_table('linear')]
    vtab = b''.join(vtabs)
    curve_index = 8 if a.vel_table else VEL_CURVES.index(a.vel_curve)
    if a.stage == 1:
        open(a.dst, 'wb').write(img)
        print(f'stage 1: stock image, bcdDevice {a.bcd:#06x}, {len(img)} B')
        return
    put(CFG_ADDR, default_cfg(a.sens, a.boot_ms, a.pad_base, {'absolute': 1, 'relative-offset': 0, 'relative': 2}[a.enc_mode], a.enc_init, {'gate': 0, 'toggle': 1, 'trigger': 2}[a.btn_mode], a.vel_shift, a.transport, a.local_leds == 'on', a.pad_colour, a.strip_colour, curve_index)); put(CODE_ADDR, code)
    put(DESC_DEV_ADDR, dev); put(DESC_CFG_ADDR, cfg); put(VEL_TABLE_ADDR, vtab)
    put(CURVE_COUNT_ADDR, bytes([9 if a.vel_table else 8]) + b'\0\0\0'); put(FONT_ADDR, FONT); put(TXT_ADDR, texts); put(SCALES_ADDR, scales_blob())
    if a.stage == 2:
        open(a.dst, 'wb').write(img)
        print(f'stage 2: stage 1 + unused patch payload, {len(img)} B')
        return
    f = lambda n: CODE_ADDR + syms[n] + 1
    put(0x08004036, bl(0x08004036, f('mmk3_translate')), bl(0x08004036, 0x08008A38))
    put(0x08008CF8, bl(0x08008CF8, f('mmk3_init')), bl(0x08008CF8, 0x08007EA2))
    put(0x08004ABA, bl(0x08004ABA, f('mmk3_rx')), bl(0x08004ABA, 0x08008798))
    put(0x08008CFC, bl(0x08008CFC, f('mmk3_boot2')), bl(0x08008CFC, 0x08008BAC))
    put(0x08008D06, bl(0x08008D06, f('mmk3_tick')), bl(0x08008D06, 0x08005414))
    put(0x08008526, bytes.fromhex('0021'), bytes.fromhex('e910'))
    put(0x08008460, bytes.fromhex('03 28 34 bf 00 20 02 20'.replace(' ', '')), bytes.fromhex('08b1 0220 7047 0020'.replace(' ', '')))
    open(a.dst, 'wb').write(img)
    print(f'code {len(code)} B at {CODE_ADDR:#x} (image ends at {CODE_ADDR + len(code):#x}, application area up to {APP_LIMIT:#x}); image {len(img)} B; '
          f'config {len(cfg)} B, VID:PID {a.vid:04x}:{a.pid:04x}, bcdDevice {a.bcd:#06x}, {a.max_power} mA, '
          f'velocity {"custom table" if a.vel_table else a.vel_curve}, vel-shift {a.vel_shift}, pad 1 = note {a.pad_base}, transport {a.transport}, local LEDs {a.local_leds}')

if __name__ == '__main__':
    main()
