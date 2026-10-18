// USB DFU 1.1 for the Native Instruments Maschine Mikro MK3 bootloader in the browser (WebUSB): a port of dfu_client.py, which flashed this device from
// the command line. The protocol part works on any transport with ctrlOut / ctrlIn and is tested against a mock device in test_dfu.mjs;
// webUsbTransport() is the real one. What is specific to a device is the profile MIKRO_MK3 (USB ids, the flash area an image may occupy).


export const MIKRO_MK3 = { name: 'Maschine Mikro MK3', vid: 0x17cc, pidRuntime: 0x1700, pidDfu: 0x1702, appBase: 0x08003000, appLimit: 0x0801f000 };   // NI's settings pages start at 0x0801f000
export const VID = MIKRO_MK3.vid, PID_RUNTIME = MIKRO_MK3.pidRuntime, PID_DFU = MIKRO_MK3.pidDfu, APP_BASE = MIKRO_MK3.appBase, APP_LIMIT = MIKRO_MK3.appLimit;
export const REQ = { DETACH: 0, DNLOAD: 1, GETSTATUS: 3, CLRSTATUS: 4, GETSTATE: 5, ABORT: 6 };
export const S = { APP_IDLE: 0, APP_DETACH: 1, IDLE: 2, DNLOAD_SYNC: 3, DNBUSY: 4, DNLOAD_IDLE: 5, MANIFEST_SYNC: 6, MANIFEST: 7, MANIFEST_WAIT_RESET: 8, UPLOAD_IDLE: 9, ERROR: 10 };

export class DfuError extends Error {}
const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

/** Sanity checks on an application image for a device (default: the Mikro MK3); returns a list of problems. */
export function validateImage(img, profile = MIKRO_MK3) {
  const APP_BASE = profile.appBase, APP_LIMIT = profile.appLimit;
  const problems = [];
  if (img.length < 0x200) problems.push('image is too small to contain a vector table');
  if (img.length > APP_LIMIT - APP_BASE) problems.push(`image is larger than the application area (${(APP_LIMIT - APP_BASE).toString(16)} bytes)`);
  if (img.length >= 8) {
    const v = new DataView(img.buffer, img.byteOffset, img.byteLength);
    const sp = v.getUint32(0, true), reset = v.getUint32(4, true);
    if (!(sp >= 0x20000000 && sp <= 0x20005000 && sp % 4 === 0)) problems.push(`initial stack pointer ${sp.toString(16)} is not in RAM`);
    if (!((reset & 1) && reset >= APP_BASE && reset < APP_BASE + img.length)) problems.push(`reset vector ${reset.toString(16)} is not Thumb code inside the image`);
  }
  return problems;
}

/** DFU 1.1 functional descriptor (9 bytes: length, 0x21, attributes, detach timeout, transfer size, version) -> object or null. */
export function parseDfuFunctional(b) {
  if (b.length < 9 || b[1] !== 0x21) return null;
  return { attributes: b[2], detachTimeout: b[3] | (b[4] << 8), transferSize: b[5] | (b[6] << 8), version: b[7] | (b[8] << 8) };
}

/** The DFU interface in a raw configuration descriptor: { number, runtime, functional } or null. */
export function findDfuInterface(cfg) {
  let i = 0, cur = null;
  while (i + 2 <= cfg.length && cfg[i] > 0) {
    const len = cfg[i], type = cfg[i + 1];
    if (type === 4) cur = (cfg[i + 5] === 0xfe && cfg[i + 6] === 1 && (cfg[i + 7] === 1 || cfg[i + 7] === 2)) ? { number: cfg[i + 2], runtime: cfg[i + 7] === 1, functional: null } : null;
    else if (type === 0x21 && cur) { cur.functional = parseDfuFunctional(cfg.slice(i, i + len)); return cur; }
    i += len;
  }
  return null;
}

async function getStatus(t) {
  const r = await t.ctrlIn(REQ.GETSTATUS, 6);
  if (r.length !== 6) throw new DfuError(`short GETSTATUS reply (${r.length} bytes)`);
  return { status: r[0], poll: r[1] | (r[2] << 8) | (r[3] << 16), state: r[4] };
}

async function clearToIdle(t) {
  let s = await getStatus(t);
  if (s.state === S.ERROR) { await t.ctrlOut(REQ.CLRSTATUS, 0); s = await getStatus(t); }
  if ([S.DNLOAD_IDLE, S.UPLOAD_IDLE, S.DNLOAD_SYNC].includes(s.state)) { await t.ctrlOut(REQ.ABORT, 0); s = await getStatus(t); }
  if (s.state !== S.IDLE) throw new DfuError(`device is not in dfuIDLE (state ${s.state}, status ${s.status})`);
}

/** Standard DFU download: blocks of `block` bytes, GETSTATUS polling after each, then the zero-length block that starts the
 *  manifestation. Returns 'reset' when the device resets itself after the last block (this bootloader does: the status poll then fails,
 *  which is the normal ending), else the final state. */
export async function download(t, img, { block = 64, progress = () => {}, sleep = sleepMs } = {}) {
  await clearToIdle(t);
  let n = 0;
  for (let off = 0; off < img.length; off += block) {
    await t.ctrlOut(REQ.DNLOAD, n++, img.slice(off, off + block));
    for (;;) {
      const s = await getStatus(t);
      if (s.status !== 0) throw new DfuError(`device reported status ${s.status.toString(16)} after block ${n - 1} (state ${s.state})`);
      if (s.state === S.DNBUSY) { await sleep(Math.min(s.poll, 1000)); continue; }
      if (s.state === S.DNLOAD_IDLE) break;
      throw new DfuError(`unexpected state ${s.state} after block ${n - 1}`);
    }
    progress(Math.min(off + block, img.length), img.length);
  }
  await t.ctrlOut(REQ.DNLOAD, n, new Uint8Array(0));                 // zero length: end of data
  for (let i = 0; i < 100; i++) {
    let s;
    try { s = await getStatus(t); } catch (e) { return 'reset'; }     // the chip reset itself: the normal ending
    if (s.status !== 0) throw new DfuError(`device rejected the image: status ${s.status.toString(16)} (state ${s.state})`);
    if ([S.APP_IDLE, S.IDLE, S.MANIFEST_WAIT_RESET].includes(s.state)) return s.state;
    if (s.state === S.MANIFEST_SYNC || s.state === S.MANIFEST) { await sleep(Math.min(Math.max(s.poll, 10), 1000)); continue; }
    throw new DfuError(`unexpected state ${s.state} during manifestation`);
  }
  throw new DfuError('manifestation did not finish');
}

/** A transport over WebUSB for one interface of an opened and claimed device. */
export function webUsbTransport(device, interfaceNumber) {
  return {
    async ctrlOut(request, value, data = new Uint8Array(0)) {
      const r = await device.controlTransferOut({ requestType: 'class', recipient: 'interface', request, value, index: interfaceNumber }, data);
      if (r.status !== 'ok') throw new DfuError(`control request ${request} failed: ${r.status}`);
    },
    async ctrlIn(request, length) {
      const r = await device.controlTransferIn({ requestType: 'class', recipient: 'interface', request, value: 0, index: interfaceNumber }, length);
      if (r.status !== 'ok') throw new DfuError(`control request ${request} failed: ${r.status}`);
      return new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
    },
  };
}

/** The raw configuration descriptor of an opened WebUSB device (WebUSB does not expose the class-specific descriptors otherwise). */
export async function readConfigDescriptor(device) {
  const head = await device.controlTransferIn({ requestType: 'standard', recipient: 'device', request: 6, value: 0x0200, index: 0 }, 9);
  const total = head.data.getUint16(2, true);
  const full = await device.controlTransferIn({ requestType: 'standard', recipient: 'device', request: 6, value: 0x0200, index: 0 }, total);
  return new Uint8Array(full.data.buffer, full.data.byteOffset, full.data.byteLength);
}
