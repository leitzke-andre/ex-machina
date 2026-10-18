// Tests of presets.js: the words for a configuration, the differences between two, and the preset store (built-in and the user's own,
// stored in the browser, exported and imported). Run: node tools/ui/test_presets.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as M from './mmk3.js';
import * as P from './presets.js';

const here = dirname(fileURLToPath(import.meta.url));
let ok = true;
const check = (name, cond, detail = '') => { ok &&= !!cond; console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '  ' + detail)); };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const V = JSON.parse(readFileSync(join(here, 'vectors.json'), 'utf8'));
const D = M.defaultCfg(), F = M.D.FIELDS;
const set = (cfg, name, v, i = 0) => { const c = Uint8Array.from(cfg); c[F[name][0] + i] = v; return c; };

// ---- in words ----
const d = Object.fromEntries(P.describeCfg(D).map((x) => [x.label, x.text]));
check('describeCfg(default): transport', d.Transport === 'Play MIDI Start · Rec CC 58 · Stop MIDI Stop', d.Transport);
check('describeCfg(default): pads', d.Pads === '1–16 play notes 36–51 (C1–D#2)', d.Pads);
check('describeCfg(default): buttons, encoder, lighting', d.Buttons === '39 Control Changes · 2 transport messages' && d['Encoder, strip'] === 'encoder CC 7, absolute · strip CC 1 · channel 1'
  && d.Lighting === 'buttons dim at rest · buttons light when pressed · pads blue · pads flash when hit · strip white', JSON.stringify(d));
check('describeButton: notes, MMC, none, unassigned', [
  P.describeButton(set(set(D, 'btn_act', 1, 3), 'btn_cc', 60, 3), 3) === 'note 60 (C3)',
  P.describeButton(M.defaultCfg('transport_mmc'), 22) === 'MMC play', P.describeButton(M.defaultCfg('transport_mmc'), 24) === 'MMC stop',
  P.describeButton(set(D, 'btn_act', 6, 3), 3) === 'nothing', P.describeButton(set(D, 'btn_cc', 255, 3), 3) === 'nothing'].every(Boolean));
check('describeCfg: custom pad notes, no lighting, an unassigned button', (() => {
  let c = set(D, 'pad_note', 99, 12); c = set(c, 'led_flags', 0); c = set(c, 'btn_cc', 255, 0);
  const x = Object.fromEntries(P.describeCfg(c).map((y) => [y.label, y.text]));
  return /^custom notes: /.test(x.Pads) && x.Lighting === 'off (only what apps send)' && /1 unassigned/.test(x.Buttons);
})());

// ---- differences ----
check('diff of a configuration with itself is empty', P.diffCfg(D, D).length === 0);
check('diff default -> CC transport: Play and Stop only', same(P.diffCfg(D, M.defaultCfg('transport_cc')), ['Play: MIDI Start → CC 57', 'Stop: MIDI Stop → CC 59']), JSON.stringify(P.diffCfg(D, M.defaultCfg('transport_cc'))));
check('diff default -> NI pad notes', same(P.diffCfg(D, M.defaultCfg('pads_ni')), ['Pad notes: 36–51 → 12–27']), JSON.stringify(P.diffCfg(D, M.defaultCfg('pads_ni'))));
check('diff default -> lighting off lists the five lighting options', P.diffCfg(D, M.defaultCfg('leds_off')).length === 5 && P.diffCfg(D, M.defaultCfg('leds_off')).every((l) => /^Lighting: .* → off$/.test(l)));
check('diff: one pad, the channel, the encoder, a colour', same(P.diffCfg(D, set(set(set(set(D, 'pad_note', 99, 12), 'channel', 4), 'enc_cc', 255), 'pad_colour', 5)),
  ['Pad 1: note 36 → 99', 'MIDI channel: 1 → 5', 'Encoder CC: 7 → nothing', 'Pad colour: blue → yellow']), JSON.stringify(P.diffCfg(D, set(set(set(set(D, 'pad_note', 99, 12), 'channel', 4), 'enc_cc', 255), 'pad_colour', 5))));
check('diff: many pads that change are summarised', same(P.diffCfg(D, (() => { let c = D; for (let i = 0; i < 16; i += 2) c = set(c, 'pad_note', 100 + i, i); return c; })()), ['8 pads play other notes']));

// ---- the store ----
const memory = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v), raw: m }; };
let t = 1000, n = 0;
const make = (storage) => new P.PresetStore({ storage, now: () => ++t, newId: () => `u-${++n}` });
const st = memory(); let s = make(st);
check('the built-in presets: "Default" is the default configuration, "Groove Rider 2" differs from it in exactly the documented places',
  s.list().length === M.D.BUILTIN_PRESETS.length && s.list()[0].id === 'default' && s.list()[0].builtin && M.equal(s.get('default').cfg, D) && s.list()[1].id === 'maschine-modes' && s.list()[2].id === 'groove-rider-2'
  && same(P.diffCfg(D, s.get('groove-rider-2').cfg), ['Erase: CC 54 → CC 120', 'Shift: CC 43 → Shift', 'Scene with Shift: as without Shift → load slot 1', 'Pattern with Shift: as without Shift → load slot 2', 'Events with Shift: as without Shift → load slot 3', 'Variation with Shift: as without Shift → load slot 4', 'Encoder Touch: CC 9 → nothing', 'Encoder CC: 7 → 20', 'Encoder mode: absolute → relative', 'Strip CC: 1 → 74']), JSON.stringify(P.diffCfg(D, s.get('groove-rider-2').cfg)));
const a = s.add({ name: 'Mine', description: ' my setup ', cfg: set(D, 'channel', 2) });
check('add: a user preset with trimmed description, stored', a.id === 'u-1' && a.description === 'my setup' && !a.builtin && st.raw.has(P.STORAGE_KEY));
const b = s.add({ name: 'mine', cfg: set(D, 'channel', 3) });
check('add: names stay unique, case-insensitively ("mine" becomes "mine 2")', b.name === 'mine 2', b.name);
check('add: the built-in name is taken too', s.add({ name: 'Default', cfg: D }).name === 'Default 2');
let e = ''; try { s.add({ name: 'x', cfg: set(D, 'channel', 40) }); } catch (x) { e = x.message; }
check('add: an invalid configuration is refused', /not valid/.test(e), e);
const s2 = make(st);
check('a new store on the same storage has the same presets and bytes', same(s2.list().map((p) => [p.id, p.name, p.description, M.hex(p.cfg)]), s.list().map((p) => [p.id, p.name, p.description, M.hex(p.cfg)])));
s.update('u-1', { name: 'Renamed', cfg: set(D, 'channel', 7) });
check('update: rename and new configuration', s.get('u-1').name === 'Renamed' && s.get('u-1').cfg[F.channel[0]] === 7 && make(st).get('u-1').name === 'Renamed');
check('update: renaming to its own name keeps it (no "2")', s.update('u-1', { name: 'Renamed' }).name === 'Renamed');
e = ''; try { s.update('default', { name: 'x' }); } catch (x) { e = x.message; }
check('the built-in preset cannot be changed or deleted', /only your own/.test(e) && (() => { try { s.remove('default'); } catch { return true; } return false; })());
const dup = s.duplicate('default');
check('duplicate: a copy of a built-in becomes a user preset "(copy)"', dup.name === 'Default (copy)' && !dup.builtin && M.equal(dup.cfg, D));
s.remove(dup.id);
check('remove: gone, and gone after a reload', !s.get(dup.id) && !make(st).get(dup.id));
check('find: the preset whose bytes equal a configuration (or null)', s.find(D).id === 'default' && s.find(set(D, 'channel', 7)).id === 'u-1' && s.find(set(D, 'channel', 9)) === null);

// ---- files ----
const text = s.exportJSON();
check('export: format and the user presets only, as hex', (() => { const j = JSON.parse(text); return j.format === 'mmk3-presets-1' && j.presets.length === s.user.length && j.presets[0].cfg === M.hex(s.user[0].cfg) && !('id' in j.presets[0]); })());
const other = make(memory()); const r = other.importJSON(text);
check('import into an empty store: all added, same names and bytes', r.added.length === s.user.length && r.skipped === 0 && same(other.user.map((p) => [p.name, M.hex(p.cfg)]), s.user.map((p) => [p.name, M.hex(p.cfg)])));
const r2 = other.importJSON(text);
check('importing the same file again adds nothing (same name and bytes are skipped)', r2.added.length === 0 && r2.skipped === s.user.length);
const clash = JSON.stringify({ format: 'mmk3-presets-1', presets: [{ name: 'Renamed', description: '', cfg: M.hex(set(D, 'channel', 12)) }] });
check('import: the same name with other bytes is added under a new name', other.importJSON(clash).added[0].name === 'Renamed 2');
const python = V.preset_file; const pstore = make(memory()); const pr = pstore.importJSON(python.text);
check('the file the Python library writes imports: the built-in presets are skipped, "Custom A" arrives with the right bytes', pr.skipped === python.builtin_ids.length && pr.added.length === 1 && pr.added[0].name === 'Custom A' && M.hex(pr.added[0].cfg) === python.custom_cfg && pr.added[0].description === 'for the tests');
check('the built-in ids match the Python library\'s', same(M.D.BUILTIN_PRESETS.map((p) => p.id), python.builtin_ids));
const old = JSON.stringify({ format: 'mmk3-config-1', config: M.toDict(set(D, 'channel', 4)) });
check('the older single-mapping file imports as one preset', make(memory()).importJSON(old).added[0].name === 'Imported mapping');
for (const [what, bad] of [['another tool\'s file', '{"format":"x"}'], ['a preset with a value out of range', JSON.stringify({ format: 'mmk3-presets-1', presets: [{ name: 'x', cfg: M.hex(set(D, 'channel', 40)) }] })],
                           ['a preset that is too long', JSON.stringify({ format: 'mmk3-presets-1', presets: [{ name: 'x', cfg: M.hex(D) + '00' }] })], ['not JSON at all', 'hello']]) {
  let err; try { make(memory()).importJSON(bad); } catch (x) { err = x; }
  check(`import refuses ${what}`, err instanceof Error);
}
const shortCfg = JSON.stringify({ format: 'mmk3-presets-1', presets: [{ name: 'Old', cfg: M.hex(set(D, 'channel', 4)).slice(0, 200) }] });
const sh = make(memory()).importJSON(shortCfg).added[0];
check('a preset from an older layout (shorter) is laid over the defaults', sh && sh.cfg.length === 274 && sh.cfg[F.channel[0]] === 4 && M.equal(sh.cfg.slice(100), D.slice(100)));

// ---- storage that does not work ----
const broken = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('quota'); } };
const sb = make(broken);
check('without usable storage the store still works in memory and says it is not persistent', sb.persistent === false && sb.add({ name: 'x', cfg: D }).name === 'x' && sb.list().length === M.D.BUILTIN_PRESETS.length + 1);
check('corrupt stored data is ignored', make({ getItem: () => '{"presets": [{"name": "bad", "cfg": "zz"}, 5, null]}', setItem() {} }).list().length === M.D.BUILTIN_PRESETS.length);

// every built-in preset: valid, unique, and the lessons from the first tests hold
{
  const bi = s.builtins;
  check('every built-in preset is a valid configuration with a unique id and name and a description', bi.every((p) => M.check(p.cfg) === null && p.description.length > 20) && new Set(bi.map((p) => p.id)).size === bi.length && new Set(bi.map((p) => p.name)).size === bi.length);
  const noTouch = bi.filter((p) => !['default', 'maschine-modes'].includes(p.id)).every((p) => P.describeButton(p.cfg, 40) === 'nothing');
  check('no app preset lets the encoder touch send anything (an app\'s learn would grab it)', noTouch);
  const gb = s.get('garageband').cfg, fl = s.get('fl-studio-mobile').cfg;
  check('GarageBand: transport is MMC, Note Repeat is CC 64; FL Studio Mobile: pads start at 48, toggle mode, Play is MMC play', P.describeButton(gb, 22) === 'MMC play' && P.describeButton(gb, 17) === 'CC 64'
    && P.padNotes(fl)[0] === 48 && fl[F.btn_mode[0]] === 1 && P.describeButton(fl, 22) === 'MMC play');
  check('Gadget and Cubasis use the trigger mode (one message per press)', s.get('korg-gadget-3').cfg[F.btn_mode[0]] === 2 && s.get('cubasis-3').cfg[F.btn_mode[0]] === 2);
}

// the modes: described in words, listed in the differences, shifted layer included
{
  const mm = s.get('maschine-modes').cfg;
  check('describeButton: the mode actions in words', ['Pad Mode', 'Keyboard', 'Fixed Vel', 'Shift', 'Left', 'Right'].map((n) => P.describeButton(mm, M.D.BUTTON_NAMES.indexOf(n))).join(' | ')
    === 'Pad Mode (drum notes) | Keyboard mode | Fixed Vel | Shift | transpose -1 | transpose +1');
  check('... and in the Shift layer', ['Fixed Vel', 'Volume', 'Swing', 'Mute', 'Left', 'Right'].map((n) => P.describeButton(mm, M.D.BUTTON_NAMES.indexOf(n), 1)).join(' | ')
    === '16 Velocities | next velocity curve | previous velocity curve | panic (all notes off) | transpose -12 | transpose +12');
  const dm = Object.fromEntries(P.describeCfg(mm).map((x) => [x.label, x.text]));
  check('describeCfg of the Maschine-like preset names the functions, the Shift layer and the curve', /\d+ functions of the device/.test(dm.Buttons) && /\d+ buttons do something else with Shift held/.test(dm.Modes) && /velocity curve linear/.test(dm.Modes), JSON.stringify(dm));
  check('describeCfg of the default has no Modes line', !('Modes' in Object.fromEntries(P.describeCfg(D).map((x) => [x.label, x.text]))));
  const df = P.diffCfg(D, mm);
  check('diff default -> Maschine-like modes: the mode buttons, the Shift layer, nothing else', df.includes('Pad Mode: CC 81 → Pad Mode (drum notes)') && df.includes('Fixed Vel with Shift: as without Shift → 16 Velocities')
    && df.includes('Volume with Shift: as without Shift → next velocity curve') && df.includes('Left: CC 41 → transpose -1') && df.length > 30, JSON.stringify(df));
  check('diff: the curve and the pad pressure setting', same(P.diffCfg(D, set(set(D, 'vel_curve', 5), 'press_mode', 1)), ['Velocity curve: linear → hard2', 'Pad pressure: poly aftertouch → channel pressure']), JSON.stringify(P.diffCfg(D, set(set(D, 'vel_curve', 5), 'press_mode', 1))));
}

console.log(ok ? 'ALL PASS' : 'SOME FAILED');
process.exit(ok ? 0 : 1);
