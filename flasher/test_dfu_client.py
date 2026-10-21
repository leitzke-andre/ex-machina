"""Tests the DFU client against a mock DFU device (no hardware). Usage: test_dfu_client.py [image.bin ...]"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dfu_client as D

ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

class MockDfu:
    """A DFU 1.1 device: dfuIDLE -> DNLOAD-SYNC -> DNBUSY -> DNLOAD-IDLE ... manifest -> idle."""
    def __init__(self, busy_ms=0, fail_at=None, start_state=D.S_IDLE, verify_error=False, reset_on_manifest=False, drop_at=None):
        self.state, self.status = start_state, 0
        self.received, self.blocks, self.busy_ms, self.fail_at, self.verify_error = bytearray(), [], busy_ms, fail_at, verify_error
        self.reset_on_manifest, self.drop_at = reset_on_manifest, drop_at
        self.polls = 0
    def ctrl_out(self, request, value, data=b''):
        if request == D.DFU_CLRSTATUS: self.state, self.status = D.S_IDLE, 0
        elif request == D.DFU_ABORT: self.state = D.S_IDLE
        elif request == D.DFU_DNLOAD:
            if self.state not in (D.S_IDLE, D.S_DNLOAD_IDLE): self.status, self.state = 0x0E, D.S_ERROR; raise IOError('stall')
            self.blocks.append(value)
            if len(data) == 0: self.state = D.S_MANIFEST_SYNC
            else:
                if self.fail_at is not None and len(self.blocks) - 1 == self.fail_at: self.status, self.state = 0x03, D.S_ERROR; return
                self.received += data; self.state = D.S_DNLOAD_SYNC
    def ctrl_in(self, request, length):
        assert request == D.DFU_GETSTATUS and length == 6
        self.polls += 1
        st = self.state
        if st == D.S_MANIFEST_SYNC and self.reset_on_manifest: raise IOError(5, 'Input/Output Error')   # the chip reset itself
        if st == D.S_MANIFEST_SYNC and getattr(self, 'stall_on_manifest', False): raise IOError(32, 'Pipe error')      # a STALL: still there, refusing
        if st in (D.S_DNLOAD_SYNC, D.S_DNBUSY) and getattr(self, 'busy_forever', False): self.state = D.S_DNBUSY; return bytes([0, 100, 0, 0, D.S_DNBUSY, 0])
        if st == D.S_DNLOAD_SYNC and self.drop_at is not None and len(self.blocks) - 1 == self.drop_at: raise IOError('[Errno 5] Input/Output Error')
        if st == D.S_DNLOAD_SYNC:
            self.state = D.S_DNBUSY if self.busy_ms else D.S_DNLOAD_IDLE
        elif st == D.S_DNBUSY: self.state = D.S_DNLOAD_IDLE
        elif st == D.S_MANIFEST_SYNC:
            if self.verify_error: self.status, self.state = 0x07, D.S_ERROR
            else: self.state = D.S_MANIFEST
        elif st == D.S_MANIFEST: self.state = D.S_MANIFEST_WAIT_RESET
        poll = self.busy_ms if st == D.S_DNLOAD_SYNC else 0
        return bytes([self.status, poll & 255, (poll >> 8) & 255, 0, self.state, 0])

DEVDESC = bytes([0x12, 0x01, 0x00, 0x02, 0, 0, 0, 0x40, 0xcc, 0x17, 0x00, 0x17, 0x51, 0x00, 1, 2, 3, 1])     # 17cc:1700, bcdDevice 0x0051
def image(n, desc=True):
    b = bytearray(struct.pack('<II', 0x20001c18, 0x080031c1) + bytes((i * 7) & 255 for i in range(n - 8)))
    if desc and n >= 0x200: b[0x100:0x112] = DEVDESC
    return bytes(b)

img = image(1000)
m = MockDfu(); naps = []
state = D.download(m, img, sleep=naps.append)
check('image arrives byte for byte', bytes(m.received) == img)
check('blocks are numbered 0..n-1 and a zero-length block follows', m.blocks == list(range((len(img) + 63) // 64 + 1)), m.blocks[-3:])
check('finishes in manifest-wait-reset', state == D.S_MANIFEST_WAIT_RESET, state)

m = MockDfu(busy_ms=20); naps = []
D.download(m, img, sleep=naps.append)
check('honours the device poll timeout (sleeps 20 ms per block)', naps.count(0.02) >= (len(img) + 63) // 64, naps[:4])
check('image still intact with busy states', bytes(m.received) == img)

m = MockDfu(start_state=D.S_ERROR); m.status = 0x0E
D.download(m, img, sleep=lambda s: None)
check('a device left in dfuERROR is cleared and then programmed', bytes(m.received) == img)

for what, kw in (('a device error while writing', dict(fail_at=5)), ('a manifestation (verify) error', dict(verify_error=True))):
    try: D.download(MockDfu(**kw), img, sleep=lambda s: None); check(what + ' raises DfuError', False)
    except D.DfuError as e: check(what + ' raises DfuError', True)

# the real bootloader resets the chip right after the last block (first flash, 2026-10-17): the final status poll fails with an I/O error
m = MockDfu(reset_on_manifest=True)
check('a device that resets itself after the last block ends the download with "reset", image complete', D.download(m, img, sleep=lambda s: None) == 'reset' and bytes(m.received) == img)
try: D.download(MockDfu(drop_at=5), img, sleep=lambda s: None); check('an I/O error in the middle of the transfer is still raised', False)
except IOError: check('an I/O error in the middle of the transfer is still raised', True)
class Dev:
    def __init__(self, pid): self.idProduct = pid
calls = []
def fake_find(idVendor, idProduct):
    calls.append(idProduct); return Dev(idProduct) if len(calls) >= 5 and idProduct == D.PID_RUNTIME else None
naps = []
dev = D.wait_for_device(fake_find, (D.PID_RUNTIME, D.PID_DFU), timeout=10, sleep=naps.append)
check('wait_for_device polls both product ids until the runtime device shows up', dev is not None and dev.idProduct == D.PID_RUNTIME and len(naps) >= 2, (calls, naps))
check('wait_for_device gives up after the timeout', D.wait_for_device(lambda **k: None, (D.PID_RUNTIME,), timeout=2, sleep=lambda s: None) is None)
check('validate_image accepts a plausible image', D.validate_image(image(40392)) == [])
check('validate_image rejects an SP outside RAM', any('stack pointer' in p for p in D.validate_image(struct.pack('<II', 0x1000, 0x080031c1) + bytes(1000))))
check('validate_image rejects a reset vector outside the image', any('reset vector' in p for p in D.validate_image(struct.pack('<II', 0x20001c18, 0x08100001) + bytes(1000))))
small = D.MIKRO_MK3._replace(app_limit=D.MIKRO_MK3.app_base + 0x400)
check('validate_image takes another profile: 0x500 bytes fit the Mikro MK3 but not a 0x400-byte area', D.validate_image(image(0x500)) == [] and any('larger' in p for p in D.validate_image(image(0x500), small)))
check('validate_image rejects images larger than the application area', any('larger' in p for p in D.validate_image(image(0x1D000))))
check('the application area ends at 0x0801D800 (the Ex-Machina data pages below NI\'s settings): 0x1A800 bytes fit, one more does not',
      D.validate_image(image(0x1A800)) == [] and any('larger' in p for p in D.validate_image(image(0x1A801))))
check('validate_image: an image without a device descriptor for 17cc:1700 is not a firmware for this device', any('descriptor' in p for p in D.validate_image(image(0x1000, desc=False))))
check('device_descriptors: the bcdDevice of each 17cc:1700 descriptor', D.device_descriptors(image(0x1000)) == [0x51])
m = MockDfu(); m.stall_on_manifest = True
try: D.download(m, img, sleep=lambda s: None); check('a STALL after the last block is a DfuError, not the "reset" ending', False)
except D.DfuError: check('a STALL after the last block is a DfuError, not the "reset" ending', True)
m = MockDfu(); m.busy_forever = True; slept = []
try: D.download(m, img, sleep=slept.append); check('a device that stays busy gives up after 10 s of polling', False)
except D.DfuError: check('a device that stays busy gives up after 10 s of polling', sum(slept) <= 11, sum(slept))
# DFU functional descriptor of the stock device (the same 9 bytes are in the patched configuration): attributes 0x09 = can
# download + will detach, detach timeout 255 ms, transfer size 64, DFU version 1.10. The first run on the real device exposed a
# parser that read the version (0x0110 = 272) as the transfer size.
STOCK_DFU_FUNC = bytes([9, 0x21, 0x09, 0xFF, 0x00, 0x40, 0x00, 0x10, 0x01])
check('parse_dfu_functional: attributes, timeout, transfer size 64 (not the version), version 1.10',
      D.parse_dfu_functional(STOCK_DFU_FUNC) == (0x09, 255, 64, 0x0110), D.parse_dfu_functional(STOCK_DFU_FUNC))
check('parse_dfu_functional rejects short or wrong-type descriptors',
      D.parse_dfu_functional(STOCK_DFU_FUNC[:8]) is None and D.parse_dfu_functional(bytes([9, 0x24]) + STOCK_DFU_FUNC[2:]) is None)
class FakeIntf:
    def __init__(self, number, cls, sub, proto, extra=b''):
        self.bInterfaceNumber, self.bInterfaceClass, self.bInterfaceSubClass, self.bInterfaceProtocol, self.extra_descriptors = number, cls, sub, proto, extra
stock = [[FakeIntf(0, 3, 0, 0), FakeIntf(1, 0xFE, 1, 1, STOCK_DFU_FUNC)]]      # a device is a list of configurations of interfaces
check('find_dfu_interface on the stock layout (HID 0, DFU runtime 1): (1, runtime, 0x09, 255, 64)',
      D.find_dfu_interface(stock) == (1, True, 0x09, 255, 64), D.find_dfu_interface(stock))
check('find_dfu_interface on a DFU-mode interface (protocol 2) is not runtime', D.find_dfu_interface([[FakeIntf(0, 0xFE, 1, 2, STOCK_DFU_FUNC)]])[1] is False)
try: D.find_dfu_interface([[FakeIntf(0, 3, 0, 0)]]); check('no DFU interface raises DfuError', False)
except D.DfuError: check('no DFU interface raises DfuError', True)
for path in sys.argv[1:]:
    p = D.validate_image(open(path, 'rb').read()); check(f'{os.path.basename(path)} passes validate_image', p == [], p)
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
