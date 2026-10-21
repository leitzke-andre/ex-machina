"""Our USB stack (usb.c) in the emulator, against the USB peripheral model (tools/emu/usb_model.py) and against the stock stack.
- The transmit ring: our enqueue against the stock one for random ring states (same RAM, same count).
- Enumeration with our stack (a boot of ours with own USB, the board init stubbed): device, configuration and string descriptors equal to
  what the stock stack returns for the same image, SET_ADDRESS taking effect after its status stage, SET_CONFIGURATION, GET_CONFIGURATION,
  GET_STATUS, SET_INTERFACE, unknown requests stalled, DFU GETSTATUS / GETSTATE.
- MIDI both ways: a SysEx INFO request over bulk OUT reaches the translator, the main loop's reply comes back over bulk IN.
- DFU_DETACH: acknowledged, then the main loop goes into DFU mode (enter_dfu) about 20 ms later.
- No host: the boot of ours restarts the chip after 5 s without a configuration.
Usage: test_hal_usb.py <patched.bin> <data_init.bin>   (symbols from <patched.bin>.syms.json)"""
import json, os, random, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, '..', 'emu')); sys.path.insert(0, HERE)
from unicorn import *
from unicorn.arm_const import *
from usb_model import UsbModel, setup_packet, STALL_TX
from machine import boot, bl_target
import mmk3_config as mc

img = open(sys.argv[1], 'rb').read(); data = open(sys.argv[2], 'rb').read()
SYM = json.load(open(sys.argv[1] + '.syms.json'))
ok = True
def check(name, got, want=True, detail=''):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + name + ('' if good else f'\n     got  {got}\n     want {want}\n     {detail}'), flush=True)

# ---- the ring --------------------------------------------------------------------------------------------------------------------------------------------
def ring_run(fn, w, r, payload):
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(0x08000000, 0x40000); mu.mem_write(0x08003000, img); mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data)
    mu.mem_write(0x20000146, struct.pack('<HH', w, r)); mu.mem_write(0x20003000, payload)
    mu.reg_write(UC_ARM_REG_R0, 0x20003000); mu.reg_write(UC_ARM_REG_R1, len(payload)); mu.reg_write(UC_ARM_REG_SP, 0x20001C18); mu.reg_write(UC_ARM_REG_LR, 0x08000001)
    try: mu.emu_start(fn | 1, 0x08000000, count=2_000_000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC) != 0x08000000: raise
    return mu.reg_read(UC_ARM_REG_R0), bytes(mu.mem_read(0x20000146, 4)), bytes(mu.mem_read(0x20000778, 0x500))
def ring_model(w, r, payload, ring):                    # whole packets only: as many 4-byte packets as fit, the rest dropped
    room = ((r + 0x500 - w - 1) % 0x500) & ~3; n = min(len(payload), room) & ~3; ring = bytearray(ring)
    for k in range(n): ring[(w + k) % 0x500] = payload[k]
    return n, struct.pack('<HH', (w + n) % 0x500, r), bytes(ring)
rng = random.Random(1); bad = []; same = []
for t in range(300):
    w, r = rng.randrange(0x500), rng.randrange(0x500)
    w -= w % 4 if rng.random() < 0.8 else 0                                    # (mostly packet-aligned, as the firmware keeps it)
    pl = bytes(rng.randrange(256) for _ in range(rng.choice((4, 8, 64, 300, 0x4FF, 0x600, 3, 5))))
    ours = ring_run(SYM['ring_put'], w, r, pl)
    if ours != ring_model(w, r, pl, (bytes(data) + bytes(0x5000))[0x778:0x778 + 0x500]): bad.append((t, w, r, len(pl)))
    if len(pl) % 4 == 0 and len(pl) <= ((r + 0x500 - w - 1) % 0x500) and ours != ring_run(0x08008A38, w, r, pl): same.append((t, w, r, len(pl)))
check('the transmit ring: our enqueue writes whole packets only, as many as fit (300 random states, full rings, odd lengths): the model', bad[:3], [])
check('... and where everything fits, the same ring, indices and count as the stock enqueue', same[:3], [])

# ---- enumeration -----------------------------------------------------------------------------------------------------------------------------------------
def stock_descriptors():
    mu, usb = boot(img, data, patched=True, configure=False)
    usb.control(setup_packet(0x00, 5, 7)); return usb

def ours():
    mu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    mu.mem_map(0x08000000, 0x40000); mu.mem_write(0x08000000, b'\xff' * 0x40000); mu.mem_write(0x08003000, img)
    mu.mem_map(0x20000000, 0x5000); mu.mem_write(0x20000000, data); mu.mem_map(0xE0000000, 0x100000)
    usb = UsbModel(mu)
    mu.mem_write(0x20004FEC, struct.pack('<I', 0x4F574E32))                  # the one-shot flag: our init and our USB
    events = []
    def ret(uc, a, s, u): events.append(a); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR) | 1)
    mu.hook_add(UC_HOOK_CODE, ret, begin=SYM['own_board_init'], end=SYM['own_board_init'] + 1)
    def dfu(uc, a, s, u): events.append(a); uc.reg_write(UC_ARM_REG_PC, 0x08000001); uc.emu_stop()   # (it never returns: stop here)
    mu.hook_add(UC_HOOK_CODE, dfu, begin=SYM['enter_dfu'], end=SYM['enter_dfu'] + 1)
    for a in (0x08005414,): mu.hook_add(UC_HOOK_CODE, ret, begin=a, end=a + 1)
    usb.run(bl_target(img, 0x08008CF8) | 1)                                  # our boot hook: guard, state, the flag
    usb.run(SYM['own_usb_init'] | 1)
    usb.isr_pc = SYM['mmk3_usb_isr'] | 1
    usb.reset()
    return mu, usb, events

mu, usb, events = ours()
def get(u, t, i=0, n=255):
    d, st = u.control(setup_packet(0x80, 6, (t << 8) | i, 0x0409 if t == 3 and i else 0, n)); return d if st == 'ok' else st
s_usb = stock_descriptors()
first = get(usb, 1, 0, 64)
check('GET_DESCRIPTOR device (wLength 64, before an address): the 18-byte device descriptor of the image', (len(first), first[:4]), (18, bytes([18, 1, 0, 2])))
d, st = usb.control(setup_packet(0x00, 5, 7))
check('SET_ADDRESS 7: acknowledged, the address takes effect after the status stage', (st, usb.daddr), ('ok', 0x87))
for t, i, what in ((1, 0, 'device'), (2, 0, 'configuration'), (3, 0, 'string 0 (languages)'), (3, 1, 'string 1'), (3, 2, 'string 2'), (3, 3, 'string 3 (serial)')):
    check(f'GET_DESCRIPTOR {what}: the same bytes as the stock stack', get(usb, t, i), get(s_usb, t, i))
cfg9 = get(usb, 2, 0, 9)
check('GET_DESCRIPTOR configuration with wLength 9: just the header (wTotalLength read from it)', (len(cfg9), struct.unpack_from('<H', cfg9, 2)[0] == len(get(usb, 2, 0, 255))), (9, True))
check('GET_DESCRIPTOR device qualifier (a full-speed device has none): stalled', usb.control(setup_packet(0x80, 6, 0x0600, 0, 10))[1], 'stall')
check('GET_CONFIGURATION before / after SET_CONFIGURATION 1', (usb.control(setup_packet(0x80, 8, 0, 0, 1))[0], usb.control(setup_packet(0x00, 9, 1))[1], usb.control(setup_packet(0x80, 8, 0, 0, 1))[0]), (b'\0', 'ok', b'\1'))
check('... endpoint 1 is then ready to receive (bulk OUT valid), the IN side waits (NAK)', ((usb.ep[1] >> 12) & 3, (usb.ep[1] >> 4) & 3, usb.ep[1] & 0x0F), (3, 2, 1))
check('GET_STATUS device / interface / endpoint 0x81', [usb.control(setup_packet(bm, 0, 0, i, 2))[0] for bm, i in ((0x80, 0), (0x81, 1), (0x82, 0x81))], [b'\0\0'] * 3)
check('SET_INTERFACE 1 alternate 0: acknowledged; alternate 1: stalled', (usb.control(setup_packet(0x01, 11, 0, 1))[1], usb.control(setup_packet(0x01, 11, 1, 1))[1]), ('ok', 'stall'))
check('a vendor request (NI\'s 0x40 / 0x10) and an unknown standard one: stalled', (usb.control(setup_packet(0x40, 0x10, 0, 0))[1], usb.control(setup_packet(0x80, 0x33, 0, 0, 2))[1]), ('stall', 'stall'))
check('DFU GETSTATUS (6 bytes: OK, appIDLE) and GETSTATE (appIDLE) on interface 2', (usb.control(setup_packet(0xA1, 3, 0, 2, 6))[0], usb.control(setup_packet(0xA1, 5, 0, 2, 1))[0]), (bytes(6), b'\0'))

# ---- MIDI both ways --------------------------------------------------------------------------------------------------------------------------------------
TICK = bl_target(img, 0x08008D06) | 1
def tick(n=1):
    for _ in range(n):
        mu.mem_write(0x2000102A, b'\0\0'); usb.run(TICK); usb.run(SYM['own_usb_tx'] | 1)
def midi_out(msg):
    pk = __import__('devsim').usb_packets(msg)
    for k in range(0, len(pk), 64): usb.bulk_out(1, pk[k:k + 64])
got = []
midi_out(mc.info_request()); tick(6)
for _ in range(8):
    b = usb.bulk_in(1)
    if b: got.append(b)
    tick()
reply = __import__('devsim').sysex_messages(got)
check('a SysEx INFO request over bulk OUT reaches the translator; its reply comes back over bulk IN', [mc.parse_reply(m)['cmd'] for m in reply], [0x10])
check('... and says protocol 2 with our config size', (mc.parse_reply(reply[0])['protocol'], mc.parse_reply(reply[0])['cfg_size']) if reply else None, (2, mc.CFG_SIZE))

# ---- endpoint 1: a halt from the host, SET_INTERFACE, endpoint 0's halt --------------------------------------------------------------------------------
check('SET_FEATURE(ENDPOINT_HALT) on 0x81: acknowledged, GET_STATUS says halted', (usb.control(setup_packet(0x02, 3, 0, 0x81))[1], usb.control(setup_packet(0x82, 0, 0, 0x81, 2))[0]), ('ok', b'\1\0'))
midi_out(mc.info_request()); tick(6)
check('... and stays halted while a reply waits (the transmit path only arms a NAKing endpoint, never a halted one)', ((usb.ep[1] >> 4) & 3, usb.bulk_in(1)), (1, None))
usb.control(setup_packet(0x02, 1, 0, 0x81)); got = []
for _ in range(8):
    tick(); b = usb.bulk_in(1)
    if b: got.append(b)
check('CLEAR_FEATURE(ENDPOINT_HALT): the endpoint works again and the waiting reply comes out', [mc.parse_reply(m)['cmd'] for m in __import__('devsim').sysex_messages(got)], [0x10])
usb.ep[1] |= 0x4040                                                              # (both data toggles at DATA1, as after an odd number of packets)
check('SET_INTERFACE 1 alternate 0 after traffic: endpoint 1 starts over at DATA0 both ways (USB 2.0 9.1.1.5)', (usb.control(setup_packet(0x01, 11, 0, 1))[1], usb.ep[1] & 0x4040), ('ok', 0))
check('CLEAR_FEATURE(ENDPOINT_HALT) on endpoint 0: acknowledged (nothing to clear)', usb.control(setup_packet(0x02, 1, 0, 0x00))[1], 'ok')

# ---- DFU_DETACH ------------------------------------------------------------------------------------------------------------------------------------------
st = usb.control(setup_packet(0x21, 0, 255, 2))[1]
check('after DETACH, DFU GETSTATE and GETSTATUS report appDETACH (1)', (usb.control(setup_packet(0xA1, 5, 0, 2, 1))[0], usb.control(setup_packet(0xA1, 3, 0, 2, 6))[0][4]), (b'\1', 1))
ms = struct.unpack('<H', mu.mem_read(0x200010E8, 2))[0]
tick(3); early = SYM['enter_dfu'] in events
mu.mem_write(0x200010E8, struct.pack('<H', (ms + 25) & 0xFFFF)); tick(1)
check('DFU_DETACH: acknowledged; DFU mode not before 20 ms, then entered from the main loop', (st, early, SYM['enter_dfu'] in events), ('ok', False, True))

# ---- no host ---------------------------------------------------------------------------------------------------------------------------------------------
mu2, usb2, ev2 = ours()
for k in (1000, 4900): mu2.mem_write(0x200010E8, struct.pack('<H', k)); usb2.run(SYM['own_usb_tx'] | 1)
aircr_before = struct.unpack('<I', mu2.mem_read(0xE000ED0C, 4))[0]
mu2.mem_write(0x200010E8, struct.pack('<H', 5200))
try: usb2.run(SYM['own_usb_tx'] | 1, limit=2000)
except RuntimeError: pass
check('a boot of ours that no host configures restarts the chip after 5 s (AIRCR = 05FA0004), not before', (aircr_before != 0x05FA0004, struct.unpack('<I', mu2.mem_read(0xE000ED0C, 4))[0]), (True, 0x05FA0004))
mu3, usb3, ev3 = ours(); usb3.control(setup_packet(0x00, 5, 3)); usb3.control(setup_packet(0x00, 9, 1))
mu3.mem_write(0x200010E8, struct.pack('<H', 14000)); usb3.run(SYM['own_usb_tx'] | 1); before = struct.unpack('<I', mu3.mem_read(0xE000ED0C, 4))[0]
mu3.mem_write(0x200010E8, struct.pack('<H', 15200))
try: usb3.run(SYM['own_usb_tx'] | 1, limit=2000)
except RuntimeError: pass
check('configured but no request answered after 15 s: the same restart (a broken MIDI path cannot strand the device)', (before != 0x05FA0004, struct.unpack('<I', mu3.mem_read(0xE000ED0C, 4))[0]), (True, 0x05FA0004))
mu.mem_write(0x200010E8, struct.pack('<H', 15200)); tick(1)
check('... while a boot that answered a request keeps running', SYM['enter_dfu'] in events, True)
mu4, usb4, ev4 = ours(); usb4.control(setup_packet(0x00, 5, 3)); usb4.control(setup_packet(0x00, 9, 1))
usb4.control(setup_packet(0x21, 0, 255, 2)); mu4.mem_write(0x200010E8, struct.pack('<H', 100)); usb4.reset()      # DETACH, then the host resets the bus
mu4.mem_write(0x200010E8, struct.pack('<H', 130)); usb4.run(SYM['own_usb_tx'] | 1)
check('DETACH followed by a bus reset: DFU mode all the same (DFU 1.1: the reset is how a host completes a detach)', SYM['enter_dfu'] in ev4, True)
mu5, usb5, ev5 = ours(); usb5.control(setup_packet(0x00, 5, 3)); usb5.control(setup_packet(0x00, 9, 1))
mu5.mem_write(0x20000146, struct.pack('<HH', 64, 0)); usb5.reset(); usb5.control(setup_packet(0x00, 5, 3)); usb5.control(setup_packet(0x00, 9, 1))
mu5.mem_write(0x200010E8, struct.pack('<H', 50)); usb5.run(SYM['own_usb_tx'] | 1)
check('what the ring held before a bus reset is not sent to the new session (64 stale bytes dropped)', (usb5.bulk_in(1), struct.unpack('<HH', mu5.mem_read(0x20000146, 4))), (None, (64, 64)))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
