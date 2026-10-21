// Tests of mmk3.js (the browser UI's protocol layer) with node:
//  1. against vectors made by the Python host library (vectors.json): every pure function must give the same bytes
//  2. optionally end to end: the real JS client against the patched firmware in the emulator, through tools/ui/emu_bridge.py
//
//   node tools/ui/test_mmk3.mjs                                       (vectors only)
//   node tools/ui/test_mmk3.mjs <python> <patched.bin> <data_init.bin>  (and the emulator)
import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as M from './mmk3.js';

const here = dirname(fileURLToPath(import.meta.url));
let ok = true;
const check = (name, cond, detail = '') => { ok &&= !!cond; console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '  ' + detail)); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const V = JSON.parse(readFileSync(join(here, 'vectors.json'), 'utf8'));

// ---- 1. vectors ----
check('default configs equal the Python library\'s, byte for byte (default, CC transport, MMC transport, NI pads, LEDs off)',
  Object.entries(V.defaults).every(([k, h]) => M.hex(M.defaultCfg(k)) === h), Object.keys(V.defaults));
check(`pack7 / unpack7 on ${V.pack7.length} inputs`, V.pack7.every((c) => M.hex(M.pack7(M.fromHex(c.data))) === c.packed && M.hex(M.unpack7(M.fromHex(c.packed))) === c.data));
check('crc16 (CRC-16/CCITT-FALSE) on 4 inputs, incl. "123456789" = 0x29B1', V.crc.every((c) => M.crc16(M.fromHex(c.data)) === c.crc) && M.crc16(new TextEncoder().encode('123456789')) === 0x29b1);
const D = M.defaultCfg();
check('request messages: INFO, GET, SAVE, RESET, RESET+erase, SET(defaults)', M.hex(M.infoRequest()) === V.requests.info && M.hex(M.getRequest()) === V.requests.get && M.hex(M.saveRequest()) === V.requests.save
  && M.hex(M.resetRequest()) === V.requests.reset && M.hex(M.resetRequest(true)) === V.requests.reset_erase && M.hex(M.setRequest(D)) === V.requests.set_default
  && M.hex(M.peekRequest(0x1FFFF7E0, 16)) === V.requests.peek && M.hex(M.peekRequest(0x0800CD20, 64)) === V.requests.peek_flash);
check('a slot store with a name matches Python; display names: capitals and font characters, 20 at most, ? outside the font', M.hex(M.slotStoreRequest(1, 'BeatMaker 3 (draft)')) === V.requests.slot_store_named && ['BeatMaker 3 (draft)', 'a{b', 'x'.repeat(40), '  Spaced  '].every((n, i) => M.displayName(n) === V.requests.display_names[i]), JSON.stringify(V.requests.display_names));
check('the name a preset has on the screen: its own display name, else made from its name', [{ name: 'BeatMaker 3 (draft)' }, { name: 'Maschine-like modes' }, { name: 'Mine', display: 'my drums' }, { name: 'x'.repeat(56) }].every((p, i) => M.presetDisplayName(p) === V.requests.preset_display_names[i]), JSON.stringify(V.requests.preset_display_names));
check('slot request messages: store 3, load 4, list', M.hex(M.slotStoreRequest(2)) === V.requests.slot_store && M.hex(M.slotLoadRequest(3)) === V.requests.slot_load && M.hex(M.slotsRequest()) === V.requests.slots);
const norm = (o) => JSON.parse(JSON.stringify(o, (k, v) => (v instanceof Uint8Array ? M.hex(v) : v)));
check(`parseReply on ${V.replies.length} replies`, V.replies.every((r) => same(norm(M.parseReply(M.fromHex(r.hex))), r.parsed)), V.replies.map((r) => same(norm(M.parseReply(M.fromHex(r.hex))), r.parsed)));
let threw = false; try { M.parseReply(Uint8Array.from([0xf0, 0x41, 1, 2, 0xf7])); } catch (e) { threw = e instanceof M.ProtocolError; }
check('parseReply refuses other devices\' SysEx', threw);
const bad = V.check.filter((c) => M.check(M.fromHex(c.cfg)) !== c.offset);
check(`check() gives the same offset (or null) as the Python library on ${V.check.length} configs`, bad.length === 0, bad.length + ' differ');
check('buildRecord equals the Python record on 3 configs', V.records.every((r) => M.hex(M.buildRecord(M.fromHex(r.cfg))) === r.record));
check('parseRecord: the good page gives the config, a flipped bit and a blank page give null',
  V.parse_record.every((r) => { const got = M.parseRecord(M.fromHex(r.page)); return (got ? M.hex(got) : null) === r.cfg; }));
check('toDict / fromDict round trip and equal to Python\'s dict', same(M.toDict(M.fromHex(V.dict.cfg)), V.dict.dict) && M.hex(M.fromDict(V.dict.dict)) === V.dict.cfg);
check('noteName: 36 = C1, 60 = C3, 12 = C-1, 127 = G8', [36, 60, 12, 127].map(M.noteName).join(' ') === 'C1 C3 C-1 G8', [36, 60, 12, 127].map(M.noteName));
check('the data tables: 41 buttons named, 16 pad labels, 17 colours, all actions, 9 velocity curves', M.D.BUTTON_NAMES.length === 41 && M.D.PAD_LABEL.length === 16 && M.D.COLOUR_NAMES.length === 17 && M.D.ACTION_NAMES.length === M.D.ACT_LAST + 1 && M.D.VEL_CURVES.length === 9);

// ---- the client against a transport that never answers ----
{
  const sent = [];
  const c = new M.Mk3({ send: (m) => sent.push(m), listen: () => {} }, { timeout: 30, retries: 2 });
  let err; try { await c.info(); } catch (e) { err = e; }
  check('no reply: the request is repeated twice, then a ProtocolError', err instanceof M.ProtocolError && sent.length === 3, `${sent.length} sends`);
  // a reply that arrives for another command is not taken for the answer
  let cb; const sent2 = [];
  const c3 = new M.Mk3({ send: (m) => { sent2.push(m); setTimeout(() => { cb(M.fromHex('f07d4d4b5300f7')); cb(M.fromHex('f07d4d4b50027a01' + '05f7')); }, 1); }, listen: (f) => { cb = f; } }, { timeout: 200, retries: 0 });
  const got = await c3.info();
  check('a reply to another command is ignored, the right one is parsed', got.cmd === 16 && got.protocol === 2 && got.cfg_size === 250 && got.saved === true && got.loaded_from_flash === true && got.unsaved_changes === false, JSON.stringify(got));
}

// ---- 2. the firmware in the emulator ----
if (process.argv.length >= 5) {
  const [py, bin, dataBin] = process.argv.slice(2, 5);
  const child = spawn(py, [join(here, 'emu_bridge.py'), bin, dataBin], { stdio: ['pipe', 'pipe', 'inherit'] });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const call = async (obj) => { child.stdin.write(JSON.stringify(obj) + '\n'); const { value } = await lines.next(); return JSON.parse(value); };
  let listener = () => {};
  const transport = { listen: (f) => { listener = f; }, send: async (msg) => { const r = await call({ op: 'sysex', hex: M.hex(msg) }); for (const h of r.replies) setImmediate(() => listener(M.fromHex(h))); } };
  const dev = new M.Mk3(transport, { timeout: 2000 });

  const info = await dev.info();
  check('emulated device: INFO (protocol 2, 274 bytes, nothing saved, Standalone mode)', same(info, { cmd: 16, protocol: 2, cfg_size: 274, saved: false, unsaved_changes: false, loaded_from_flash: false, version: 0, mode: 'standalone' }), JSON.stringify(info));
  check('GET returns the defaults', M.equal(await dev.get(), D));
  let cfg = M.fromDict({ channel: 4 }, D);
  const b = M.D.FIELDS.btn_cc[0], a = M.D.FIELDS.btn_act[0];
  cfg[a + M.D.BTN_PLAY] = 0; cfg[b + M.D.BTN_PLAY] = 77;             // Play sends CC 77 (action CC)
  check('SET: accepted', (await dev.set(cfg)).status === 0);
  check('GET returns what was set', M.equal(await dev.get(), cfg));
  const r = await call({ op: 'report1', pressed: [M.D.BTN_PLAY] });
  check('the new mapping is live: Play sends CC 77 on channel 5', same(r.packets, [[11, 0xb4, 77, 127]]), JSON.stringify(r.packets));
  const refused = M.fromDict({ vel_shift: 12 }, cfg);
  const rr = await dev.set(refused);
  check('SET with a bad value: status 2 and the offset the host library computes', rr.status === 2 && rr.offset === M.check(refused) && rr.offset === M.D.FIELDS.vel_shift[0], JSON.stringify(rr));
  check('... and nothing changed', M.equal(await dev.get(), cfg));
  check('SAVE: status 0, the page holds the record the JS library builds', (await dev.save()).status === 0 && (await call({ op: 'page' })).hex.startsWith(M.hex(M.buildRecord(cfg))));
  await call({ op: 'reboot' });
  const after = await dev.info();
  check('after a power cycle: saved, loaded from flash', after.saved && after.loaded_from_flash && !after.unsaved_changes, JSON.stringify(after));
  check('... and the saved config is active', M.equal(await dev.get(), cfg));
  const [i1, g1, i2] = await Promise.all([dev.info(), dev.get(), dev.info()]);
  check('requests made at the same time are answered one by one, each with its own reply', i1.cmd === 16 && g1.length === 274 && i2.cmd === 16 && M.equal(g1, cfg));
  // the preset slots against the firmware in the emulator
  check('slots: all empty on a new device', same(await dev.slots(), [false, false, false, false]));
  const rs = await dev.slotStore(1);
  check('slot 2 stores the active config: status 0, listed as used', rs.status === 0 && same(await dev.slots(), [false, true, false, false]), JSON.stringify(rs));
  check('a store with a name: the JS client lists it (BEATMAKER 3) next to the unnamed slot', (await dev.slotStore(2, 'BeatMaker 3')).status === 0 && same(await dev.slotNames(), ['', '', 'BEATMAKER 3', '']), JSON.stringify(await dev.slotNames()));
  const other = M.fromDict({ channel: 9 }, D); await dev.set(other);
  check('loading slot 2 brings the stored config back', (await dev.slotLoad(1)).status === 0 && M.equal(await dev.get(), cfg));
  check('an empty slot answers "empty slot", a bad number "value out of range"', (await dev.slotLoad(3)).status_text === 'empty slot' && (await dev.slotStore(7)).status === 2);
  check('RESET + erase: defaults, page blank', (await dev.reset(true)).status === 0 && M.equal(await dev.get(), D) && (await call({ op: 'page' })).hex === 'ff'.repeat(1024));
  const v = await call({ op: 'violations' });
  check('the flash model saw nothing outside the save page', v.violations.length === 0, JSON.stringify(v));
  child.stdin.end();
}
console.log(ok ? 'ALL PASS' : 'SOME FAILED');
process.exit(ok ? 0 : 1);
