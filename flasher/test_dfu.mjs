// Tests of dfu.js (USB DFU 1.1 over WebUSB) against a mock DFU device, the same behaviour flasher/test_dfu_client.py checks for the Python client.
// No firmware image is needed:   node flasher/test_dfu.mjs
import * as F from './dfu.js';

let ok = true;
const check = (name, cond, detail = '') => { ok &&= !!cond; console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '  ' + detail)); };
const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');
class MockDfu {
  constructor({ busy = 0, failAt = null, startState = F.S.IDLE, verifyError = false, resetOnManifest = false, dropAt = null } = {}) {
    Object.assign(this, { busy, failAt, verifyError, resetOnManifest, dropAt });
    this.state = startState; this.status = startState === F.S.ERROR ? 0x0e : 0; this.received = []; this.blocks = [];
  }
  async ctrlOut(request, value, data = new Uint8Array(0)) {
    if (request === F.REQ.CLRSTATUS) { this.state = F.S.IDLE; this.status = 0; }
    else if (request === F.REQ.ABORT) this.state = F.S.IDLE;
    else if (request === F.REQ.DNLOAD) {
      if (![F.S.IDLE, F.S.DNLOAD_IDLE].includes(this.state)) { this.status = 0x0e; this.state = F.S.ERROR; throw new Error('stall'); }
      this.blocks.push(value);
      if (data.length === 0) this.state = F.S.MANIFEST_SYNC;
      else {
        if (this.failAt !== null && this.blocks.length - 1 === this.failAt) { this.status = 3; this.state = F.S.ERROR; return; }
        this.received.push(...data); this.state = F.S.DNLOAD_SYNC;
      }
    }
  }
  async ctrlIn(request, length) {
    if (request !== F.REQ.GETSTATUS || length !== 6) throw new Error('unexpected request');
    const st = this.state;
    if (st === F.S.MANIFEST_SYNC && this.resetOnManifest) throw new Error('device gone');
    if (st === F.S.DNLOAD_SYNC && this.dropAt !== null && this.blocks.length - 1 === this.dropAt) throw new Error('I/O error');
    if (st === F.S.DNLOAD_SYNC) this.state = this.busy ? F.S.DNBUSY : F.S.DNLOAD_IDLE;
    else if (st === F.S.DNBUSY) this.state = F.S.DNLOAD_IDLE;
    else if (st === F.S.MANIFEST_SYNC) { if (this.verifyError) { this.status = 7; this.state = F.S.ERROR; } else this.state = F.S.MANIFEST; }
    else if (st === F.S.MANIFEST) this.state = F.S.MANIFEST_WAIT_RESET;
    const poll = st === F.S.DNLOAD_SYNC ? this.busy : 0;
    return Uint8Array.from([this.status, poll & 255, (poll >> 8) & 255, 0, this.state, 0]);
  }
}
const image = (n) => { const a = new Uint8Array(n); new DataView(a.buffer).setUint32(0, 0x20001c18, true); new DataView(a.buffer).setUint32(4, 0x080031c1, true); for (let i = 8; i < n; i++) a[i] = (i * 7) & 255; return a; };
const img = image(1000), nBlocks = Math.ceil(1000 / 64);
let m = new MockDfu();
let state = await F.download(m, img, { sleep: async () => {} });
check('DFU: the image arrives byte for byte', hex(Uint8Array.from(m.received)) === hex(img));
check('DFU: blocks are numbered 0..n-1 and a zero-length block follows', JSON.stringify(m.blocks) === JSON.stringify(Array.from({ length: nBlocks + 1 }, (_, i) => i)), m.blocks.slice(-3));
check('DFU: finishes in manifest-wait-reset', state === F.S.MANIFEST_WAIT_RESET, state);
m = new MockDfu({ busy: 20 }); const naps = [];
await F.download(m, img, { sleep: async (ms) => { naps.push(ms); } });
check('DFU: honours the poll timeout (20 ms per block) and the image is intact', naps.filter((x) => x === 20).length >= nBlocks && hex(Uint8Array.from(m.received)) === hex(img));
m = new MockDfu({ startState: F.S.ERROR });
await F.download(m, img, { sleep: async () => {} });
check('DFU: a device left in dfuERROR is cleared and then programmed', hex(Uint8Array.from(m.received)) === hex(img));
for (const [what, kw] of [['a device error while writing', { failAt: 5 }], ['a manifestation (verify) error', { verifyError: true }]]) {
  let e; try { await F.download(new MockDfu(kw), img, { sleep: async () => {} }); } catch (x) { e = x; }
  check(`DFU: ${what} raises DfuError`, e instanceof F.DfuError, String(e));
}
m = new MockDfu({ resetOnManifest: true });
check('DFU: a device that resets itself after the last block ends the download with "reset", image complete', (await F.download(m, img, { sleep: async () => {} })) === 'reset' && hex(Uint8Array.from(m.received)) === hex(img));
let e2; try { await F.download(new MockDfu({ dropAt: 5 }), img, { sleep: async () => {} }); } catch (x) { e2 = x; }
check('DFU: an I/O error in the middle of the transfer is still raised', e2 instanceof Error && e2.message === 'I/O error', String(e2));
let progress = []; await F.download(new MockDfu(), img, { sleep: async () => {}, progress: (d, n) => progress.push([d, n]) });
check('DFU: progress reports every block and ends at the full size', progress.length === nBlocks && JSON.stringify(progress.at(-1)) === '[1000,1000]', JSON.stringify(progress.at(-1)));

check('validateImage rejects an SP outside RAM, a reset vector outside the image, an image that is too big',
  F.validateImage(Uint8Array.from([0, 16, 0, 0, 0xc1, 0x31, 0, 8, ...new Uint8Array(1000)])).some((p) => /stack pointer/.test(p))
  && F.validateImage(Uint8Array.from([0x18, 0x1c, 0, 0x20, 1, 0, 0, 0x10, ...new Uint8Array(1000)])).some((p) => /reset vector/.test(p))
  && F.validateImage(image(0x1d000)).some((p) => /larger/.test(p)));

// descriptors: the DFU functional descriptor and the interface search, on the real configuration descriptors
const STOCK_DFU_FUNC = Uint8Array.from([9, 0x21, 0x09, 0xff, 0x00, 0x40, 0x00, 0x10, 0x01]);
const f = F.parseDfuFunctional(STOCK_DFU_FUNC);
check('parseDfuFunctional: attributes 9, detach timeout 255, transfer size 64 (not the version 0x0110), version 1.10', f && f.attributes === 9 && f.detachTimeout === 255 && f.transferSize === 64 && f.version === 0x0110, JSON.stringify(f));
check('parseDfuFunctional refuses short or wrong-type descriptors', F.parseDfuFunctional(STOCK_DFU_FUNC.slice(0, 8)) === null && F.parseDfuFunctional(Uint8Array.from([9, 0x24, ...STOCK_DFU_FUNC.slice(2)])) === null);
check('findDfuInterface: none in a descriptor without one', F.findDfuInterface(Uint8Array.from([9, 2, 9, 0, 0, 1, 0, 0x80, 50])) === null);

// the WebUSB transport: the right setup packets, errors on a stalled transfer
const calls = [];
const fakeDevice = (mock) => ({
  async controlTransferOut(setup, data) { calls.push(setup); try { await mock.ctrlOut(setup.request, setup.value, data); return { status: 'ok' }; } catch (e) { return { status: 'stall' }; } },
  async controlTransferIn(setup, length) { calls.push(setup); const r = await mock.ctrlIn(setup.request, length); return { status: 'ok', data: new DataView(r.buffer, r.byteOffset, r.byteLength) }; },
});
m = new MockDfu();
await F.download(F.webUsbTransport(fakeDevice(m), 2), img, { sleep: async () => {} });
check('WebUSB transport: class requests to interface 2, DNLOAD blocks arrive intact', calls.every((c) => c.requestType === 'class' && c.recipient === 'interface' && c.index === 2) && hex(Uint8Array.from(m.received)) === hex(img));
m = new MockDfu({ startState: F.S.DNLOAD_IDLE });
let e3; try { await F.webUsbTransport(fakeDevice(new MockDfu({ startState: F.S.MANIFEST })), 2).ctrlOut(F.REQ.DNLOAD, 0, Uint8Array.from([1])); } catch (x) { e3 = x; }
check('WebUSB transport: a stalled request becomes a DfuError', e3 instanceof F.DfuError, String(e3));


// the interface search on a synthetic configuration descriptor: one DFU interface in runtime mode (protocol 1), then in DFU mode (protocol 2)
const cfgWith = (protocol, number) => Uint8Array.from([9, 2, 27, 0, 1, 1, 0, 0x80, 50, 9, 4, number, 0, 0, 0xfe, 1, protocol, 0, 9, 0x21, 0x09, 0xff, 0x00, 0x40, 0x00, 0x10, 0x01]);
const r1 = F.findDfuInterface(cfgWith(1, 3)), r2 = F.findDfuInterface(cfgWith(2, 0));
check('findDfuInterface on a synthetic descriptor: the interface number, runtime or DFU mode, the functional descriptor', r1 && r1.number === 3 && r1.runtime && r1.functional.transferSize === 64 && r2 && r2.number === 0 && !r2.runtime, JSON.stringify([r1, r2]));
// the device profile
check('the profile of the Mikro MK3 and the exported constants agree', F.MIKRO_MK3.vid === F.VID && F.MIKRO_MK3.pidDfu === F.PID_DFU && F.MIKRO_MK3.appBase === F.APP_BASE && F.MIKRO_MK3.appLimit === F.APP_LIMIT);
const small = { ...F.MIKRO_MK3, appLimit: 0x08003000 + 0x400 };
check('validateImage takes another profile: an image of 0x500 bytes fits the Mikro MK3 but not a 0x400-byte area', F.validateImage(image(0x500)).length === 0 && F.validateImage(image(0x500), small).some((p) => /larger/.test(p)));

console.log(ok ? 'ALL PASS' : 'SOME FAILED');
process.exit(ok ? 0 : 1);
