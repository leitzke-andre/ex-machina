// The Maschine Mikro MK3 patch's run-time configuration, host side, for the browser and for node: the config block, its range check, the
// SysEx protocol (docs/remap-protocol.md), the saved record, and a client on top of any transport that can send and receive SysEx.
// The tables come from mmk3_data.js (generated from tools/midi_patch/mmk3_config.py); test_mmk3.mjs checks every function here against
// vectors made by the Python library and against the firmware running in the emulator.

import * as D from './mmk3_data.js';
export { D };
export const CFG_SIZE = D.CFG_SIZE;

// ---- bytes <-> hex ----
export const hex = (u8) => Array.from(u8, (b) => b.toString(16).padStart(2, '0')).join('');
export const fromHex = (s) => Uint8Array.from(s.match(/../g) || [], (h) => parseInt(h, 16));
export const equal = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// ---- the config block ----
export const defaultCfg = (preset = 'default') => fromHex(D.PRESETS_HEX[preset]);

/** Offset of the first byte the firmware would refuse, in the order the device checks, or null if the block is usable. */
export function check(cfg) {
  if (cfg.length !== CFG_SIZE || cfg[0] !== 0x4d || cfg[1] !== 0x4d || cfg[2] !== 0x4b || cfg[3] !== 0x33) return 0; // "MMK3"
  const bad = (name, i = 0) => {
    const [lo, hi, ff] = D.RANGES[name];
    const v = cfg[D.FIELDS[name][0] + i];
    return !((v >= lo && v <= hi) || (ff && v === 0xff));
  };
  const order = [['channel', 0]];
  for (let i = 0; i < 16; i++) order.push(['pad_note', i]);
  for (let i = 0; i < 48; i++) order.push(['btn_cc', i], ['btn_act', i]);
  order.push(['enc_cc', 0], ['strip_cc', 0], ['vel_shift', 0], ['led_channel', 0]);
  for (let i = 0; i < 16; i++) order.push(['pad_led', i]);
  for (const n of ['enc_mode', 'flags', 'sens', 'enc_init', 'btn_mode', 'led_flags', 'btn_led_idle', 'btn_led_on', 'pad_colour', 'strip_colour', 'vel_curve', 'fixvel', 'keys_root', 'press_mode', 'press_cc']) order.push([n, 0]);
  for (let i = 0; i < 48; i++) order.push(['btn_cc2', i], ['btn_act2', i]);
  order.push(['scale', 0], ['chord_type', 0], ['enc_tgt_cc', 0], ['enc_tgt_cc', 1], ['enc_tgt_cc', 2], ['arp_type', 0], ['arp_rate', 0], ['arp_oct', 0]);
  for (const [name, i] of order) if (bad(name, i)) return D.FIELDS[name][0] + i;
  return null;
}

/** The config as an object of raw values (arrays for the array fields; boot_ms as a number). */
export function toDict(cfg) {
  const d = {};
  for (const [name, [off, n]] of Object.entries(D.FIELDS)) {
    if (name === 'magic') continue;
    if (name === 'boot_ms') d[name] = cfg[off] | (cfg[off + 1] << 8);
    else d[name] = n > 1 ? Array.from(cfg.slice(off, off + n)) : cfg[off];
  }
  return d;
}

export function fromDict(d, base = defaultCfg()) {
  const c = Uint8Array.from(base);
  for (const [name, v] of Object.entries(d)) {
    if (!(name in D.FIELDS) || name === 'magic') throw new Error(`unknown field ${name}`);
    const [off, n] = D.FIELDS[name];
    if (name === 'boot_ms') { c[off] = v & 0xff; c[off + 1] = (v >> 8) & 0xff; }
    else if (n > 1) {
      if (!Array.isArray(v) || v.length !== n) throw new Error(`${name}: ${n} values expected`);
      v.forEach((x, i) => { c[off + i] = x; });
    } else c[off] = v;
  }
  return c;
}

// ---- 7-bit packing, the SysEx messages ----
export function pack7(data) {
  const out = [];
  for (let i = 0; i < data.length; i += 7) {
    const g = data.slice(i, i + 7);
    out.push(g.reduce((acc, v, k) => acc | (((v >> 7) & 1) << k), 0));
    for (const v of g) out.push(v & 0x7f);
  }
  return Uint8Array.from(out);
}

export function unpack7(data) {
  const out = [];
  for (let i = 0; i < data.length; i += 8) {
    const hi = data[i];
    for (let j = 1; j < 8 && i + j < data.length; j++) out.push((data[i + j] & 0x7f) | (((hi >> (j - 1)) & 1) << 7));
  }
  return Uint8Array.from(out);
}

export const MANUFACTURER = [0x7d, 0x4d, 0x4b];
export const CMD = { INFO: 0x10, GET: 0x11, SET: 0x12, SAVE: 0x13, RESET: 0x14, SLOT_STORE: 0x15, SLOT_LOAD: 0x16, SLOTS: 0x17, PEEK: 0x1e };
export const REPLY = 0x40;
export const STATUS = { 0: 'ok', 1: 'wrong length', 2: 'value out of range', 3: 'flash error', 4: 'empty slot' };

export const message = (cmd, payload = []) => Uint8Array.from([0xf0, ...MANUFACTURER, cmd, ...payload, 0xf7]);
export const infoRequest = () => message(CMD.INFO);
export const getRequest = () => message(CMD.GET);
export const setRequest = (cfg) => message(CMD.SET, pack7(cfg));
export const saveRequest = () => message(CMD.SAVE);
export const slotStoreRequest = (n) => message(CMD.SLOT_STORE, [n]);
export const slotLoadRequest = (n) => message(CMD.SLOT_LOAD, [n]);
export const slotsRequest = () => message(CMD.SLOTS);
export const resetRequest = (erase = false) => message(CMD.RESET, erase ? [1] : []);
export const peekRequest = (addr, length) => message(CMD.PEEK, [...Array(5)].map((_, i) => Math.floor(addr / 2 ** (28 - 7 * i)) & 0x7f).concat([length]));

export class ProtocolError extends Error {}

/** A reply message (with or without F0 / F7) as an object, or a ProtocolError if it is not one of this device. */
export function parseReply(msg) {
  let m = Array.from(msg);
  if (m[0] === 0xf0) m = m.slice(1);
  if (m[m.length - 1] === 0xf7) m = m.slice(0, -1);
  if (m.length < 4 || m[0] !== 0x7d || m[1] !== 0x4d || m[2] !== 0x4b || m[3] < REPLY) throw new ProtocolError(`not a reply of this device: ${hex(Uint8Array.from(m))}`);
  const cmd = m[3] - REPLY, data = m.slice(4);
  if (cmd === CMD.INFO) {
    return { cmd, protocol: data[0], cfg_size: data[1] | (data[2] << 7), saved: !!(data[3] & 1), unsaved_changes: !!(data[3] & 2), loaded_from_flash: !!(data[3] & 4), version: data[4] ?? null };
  }
  if (cmd === CMD.GET) return { cmd, cfg: unpack7(Uint8Array.from(data)) };
  if (cmd === CMD.PEEK) {
    let addr = 0;
    for (const b of data.slice(1, 6)) addr = addr * 128 + b;
    return { cmd, status: data[0], addr, data: data[0] === 0 ? unpack7(Uint8Array.from(data.slice(6))) : new Uint8Array(0) };
  }
  if (cmd === CMD.SLOTS) return { cmd, status: data[0], used: [0, 1, 2, 3].map((i) => !!((data[1] >> i) & 1)) };
  if ([CMD.SET, CMD.SAVE, CMD.RESET, CMD.SLOT_STORE, CMD.SLOT_LOAD].includes(cmd)) {
    const r = { cmd, status: data[0], status_text: STATUS[data[0]] ?? '?' };
    if (cmd === CMD.SET && data[0] === 2) r.offset = data[1] | (data[2] << 7);
    return r;
  }
  throw new ProtocolError(`unknown reply ${cmd.toString(16)}`);
}

// ---- the saved record ----
export const crc16 = (data, crc = 0xffff) => {
  for (const b of data) {
    crc ^= b << 8;
    for (let i = 0; i < 8; i++) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc;
};

export function buildRecord(cfg) {
  const rec = new Uint8Array(D.REC_SIZE).fill(0);
  const v = new DataView(rec.buffer);
  v.setUint32(0, D.REC_MAGIC, true); v.setUint16(4, D.REC_VERSION, true); v.setUint16(6, cfg.length, true);
  v.setUint16(8, crc16(cfg), true); v.setUint16(10, 0xffff, true);
  rec.set(cfg, 12);
  return rec;
}

export function parseRecord(page, defaults = defaultCfg()) {
  const v = new DataView(page.buffer, page.byteOffset, page.byteLength);
  const len = v.getUint16(6, true);
  if (v.getUint32(0, true) !== D.REC_MAGIC || v.getUint16(4, true) !== D.REC_VERSION || len < 4 || len > CFG_SIZE || crc16(page.slice(12, 12 + len)) !== v.getUint16(8, true)) return null;
  const c = Uint8Array.from(defaults); c.set(page.slice(12, 12 + len));
  return check(c) === null ? c : null;
}

// ---- the client ----
/** transport: { send(Uint8Array), listen(cb(Uint8Array)) }: every SysEx message the device sends (F0 ... F7) goes to cb. */
export class Mk3 {
  constructor(transport, { timeout = 1500, retries = 2 } = {}) {
    this.t = transport; this.timeout = timeout; this.retries = retries; this.waiting = null; this.queue = Promise.resolve();
    transport.listen((msg) => {
      if (msg[0] !== 0xf0 || msg[1] !== 0x7d || msg[2] !== 0x4d || msg[3] !== 0x4b || !this.waiting) return;
      if (msg[4] === this.waiting.cmd + REPLY) this.waiting.resolve(parseReply(msg));
    });
  }

  /** Sends a request and waits for its reply. Requests made at the same time are sent one after the other (the device serves one at a
   *  time and drops the others), and a missing reply is asked again (SET / GET / INFO are safe to repeat; SAVE and RESET too). */
  request(msg, cmd) {
    const run = () => this.exchange(msg, cmd);
    const p = this.queue.then(run, run);
    this.queue = p.catch(() => {});
    return p;
  }

  async exchange(msg, cmd) {
    let lastError;
    for (let attempt = 0; attempt <= this.retries; attempt++) {
      const reply = new Promise((resolve, reject) => {
        const timer = setTimeout(() => { this.waiting = null; reject(new ProtocolError(`no reply to command ${cmd.toString(16)}`)); }, this.timeout);
        this.waiting = { cmd, resolve: (r) => { clearTimeout(timer); this.waiting = null; resolve(r); } };
      });
      try { await this.t.send(msg); return await reply; } catch (e) { lastError = e; }
    }
    throw lastError;
  }

  info() { return this.request(infoRequest(), CMD.INFO); }
  async get() { return (await this.request(getRequest(), CMD.GET)).cfg; }
  set(cfg) { return this.request(setRequest(cfg), CMD.SET); }
  save() { return this.request(saveRequest(), CMD.SAVE); }
  reset(erase = false) { return this.request(resetRequest(erase), CMD.RESET); }
  async slots() { return (await this.request(slotsRequest(), CMD.SLOTS)).used; }
  slotStore(n) { return this.request(slotStoreRequest(n), CMD.SLOT_STORE); }
  slotLoad(n) { return this.request(slotLoadRequest(n), CMD.SLOT_LOAD); }
}

// ---- notes ----
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
/** Note name with middle C = C3 (note 60), the numbering NI and most iOS apps use: note 36 is C1. */
export const noteName = (n) => `${NOTE_NAMES[n % 12]}${Math.floor(n / 12) - 2}`;
