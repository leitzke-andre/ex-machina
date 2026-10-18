// Presets: a named, complete configuration. The built-in ones come from the Python library (mmk3_data.js); the user's own live in the
// browser (localStorage) and can be exported to a file and imported again (the same file format the command line reads:
// {"format": "mmk3-presets-1", "presets": [{"name", "description", "cfg": hex}]}). Also: a plain-words description of a configuration
// and the list of differences between two, which the page shows on every preset card.
import * as M from './mmk3.js';

const D = M.D, FD = D.FIELDS;
export const STORAGE_KEY = 'mmk3.presets.v1';
const byte = (cfg, name, i = 0) => cfg[FD[name][0] + i];

/** A config from stored hex: a block shorter than today's layout (an older tool) is laid over the defaults, like the firmware does with an
 *  older saved record; anything longer, malformed or out of range gives null. */
export function cfgFromHex(hex) {
  if (typeof hex !== 'string' || hex.length % 2 || /[^0-9a-f]/i.test(hex)) return null;
  const raw = M.fromHex(hex.toLowerCase());
  if (raw.length < 4 || raw.length > M.CFG_SIZE) return null;
  const cfg = M.defaultCfg(); cfg.set(raw);
  return M.check(cfg) === null ? cfg : null;
}

// ---- in words ----
const MMC_NAMES = { 1: 'stop', 2: 'play', 4: 'fast forward', 5: 'rewind', 6: 'record', 9: 'pause' };

/** What a button does in words; layer 1 = while Shift is held ("nothing" there means: the normal action). */
export function describeButton(cfg, id, layer = 0) {
  const a = D.ACTION_NAMES[byte(cfg, layer ? 'btn_act2' : 'btn_act', id)], p = byte(cfg, layer ? 'btn_cc2' : 'btn_cc', id);
  if (a === 'padmode') return 'Pad Mode (drum notes)';
  if (a === 'keys') return 'Keyboard mode';
  if (a === 'fixvel') return 'Fixed Vel';
  if (a === 'vel16') return '16 Velocities';
  if (a === 'curve') return p === 1 ? 'previous velocity curve' : 'next velocity curve';
  if (a === 'transpose') return p > 127 ? 'nothing' : `transpose ${p >= 64 ? '+' : ''}${p - 64}`;
  if (a === 'panic') return 'panic (all notes off)';
  if (a === 'shift') return 'Shift';
  if (a === 'scale') return p === 1 ? 'previous scale' : 'next scale';
  if (a === 'chords') return 'Chords mode';
  if (a === 'chordtype') return p === 1 ? 'previous chord type' : 'next chord type';
  if (a === 'strip') return `strip: ${['configured CC', 'pitch bend', 'mod wheel', 'strum notes'][p] ?? 'configured CC'}`;
  if (a === 'enctgt') return `encoder drives target ${p + 1}`;
  if (a === 'channel') return p === 1 ? 'previous MIDI channel' : 'next MIDI channel';
  if (a === 'slot') return p > 7 ? 'nothing' : p > 3 ? `store in slot ${p - 3}` : `load slot ${p + 1}`;
  if (a === 'step') return 'step sequencer mode';
  if (a === 'seqrun') return p === 1 ? 'sequencer restart' : 'sequencer start / stop';
  if (a === 'seqsel') return 'sequencer: select track (hold)';
  if (a === 'seqpat') return p === 1 ? 'previous pattern' : 'next pattern';
  if (a === 'seqclear') return p === 1 ? 'clear pattern' : 'clear track';
  if (a === 'seqsave') return 'keep the patterns';
  if (a === 'page') return ['next pad page', 'previous pad page', 'pad page 1'][p] ?? 'next pad page';
  if (a === 'encpage') return ['next encoder page', 'previous encoder page', 'encoder page 1'][p] ?? 'next encoder page';
  if (a === 'tap') return 'tap tempo';
  if (a === 'clockout') return 'MIDI clock out on / off';
  if (a === 'arp') return 'arp / Note Repeat on / off';
  if (a === 'arptype') return p === 1 ? 'previous arp pattern' : 'next arp pattern';
  if (a === 'rate') return p === 1 ? 'previous arp rate' : 'next arp rate';
  if (a === 'arpoct') return 'arp octaves';
  if (a === 'latch') return 'arp latch';
  if (a === 'mute') return 'mute pads';
  if (a === 'solo') return 'solo pads';
  if (a === 'clear') return 'clear mutes and solos';
  if (a === 'snap') return p === 1 ? 'store snapshot' : 'snapshot: store / recall';
  if (a === 'program') return ['next program', 'previous program', 'program 0'][p] ?? 'next program';
  if (a === 'cc') return p === 0xff ? 'nothing' : `CC ${p}`;
  if (a === 'note') return p > 127 ? 'nothing' : `note ${p} (${M.noteName(p)})`;
  if (a === 'start') return 'MIDI Start';
  if (a === 'continue') return 'MIDI Continue';
  if (a === 'stop') return 'MIDI Stop';
  if (a === 'mmc') return `MMC ${MMC_NAMES[p] ?? `command ${p}`}`;
  return 'nothing';
}

const buttonKind = (cfg, id) => {
  const a = D.ACTION_NAMES[byte(cfg, 'btn_act', id)], p = byte(cfg, 'btn_cc', id);
  if (a === 'cc') return p === 0xff ? 'unassigned' : 'cc';
  if (a === 'note') return p > 127 ? 'unassigned' : 'note';
  if (['padmode', 'keys', 'fixvel', 'vel16', 'curve', 'transpose', 'panic', 'shift', 'scale', 'chords', 'chordtype', 'strip', 'enctgt', 'program', 'tap', 'clockout', 'arp', 'arptype', 'rate', 'arpoct', 'latch', 'mute', 'solo', 'clear', 'snap', 'channel', 'slot', 'step', 'seqrun', 'seqsel', 'seqpat', 'seqclear', 'seqsave', 'page', 'encpage'].includes(a)) return 'function';
  return a === 'none' ? 'unassigned' : 'transport';
};
/** True if the button does something while Shift is held (its second action is set). */
const shiftedKind = (cfg, id) => { const a = D.ACTION_NAMES[byte(cfg, 'btn_act2', id)]; return a !== 'none' && !(a === 'cc' && byte(cfg, 'btn_cc2', id) === 0xff); };

/** The pad notes in the order of the printed pad numbers 1..16. */
export const padNotes = (cfg) => Array.from({ length: 16 }, (_, i) => byte(cfg, 'pad_note', D.PAD_LABEL.indexOf(i + 1)));
const consecutive = (a) => a.every((v, i) => v === a[0] + i);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const colour = (n) => D.COLOUR_NAMES[(n || 17) - 1];
const LEVEL = { 0: 'off', 0x7c: 'dim', 0x7e: 'normal', 0x7f: 'bright' };

/** A configuration as a few lines of plain words: [{label, text}]. */
export function describeCfg(cfg) {
  const out = [];
  out.push({ label: 'Transport', text: `Play ${describeButton(cfg, D.BTN_PLAY)} · Rec ${describeButton(cfg, D.BTN_REC)} · Stop ${describeButton(cfg, D.BTN_STOP)}` });
  const notes = padNotes(cfg);
  out.push({ label: 'Pads', text: consecutive(notes) ? `1–16 play notes ${notes[0]}–${notes[15]} (${M.noteName(notes[0])}–${M.noteName(notes[15])})` : `custom notes: ${notes.join(', ')}` });
  const kinds = {};
  for (let id = 0; id < 41; id++) { const k = buttonKind(cfg, id); kinds[k] = (kinds[k] || 0) + 1; }
  const parts = [];
  if (kinds.cc) parts.push(plural(kinds.cc, 'Control Change', 'Control Changes'));
  if (kinds.note) parts.push(plural(kinds.note, 'note', 'notes'));
  if (kinds.transport) parts.push(plural(kinds.transport, 'transport message', 'transport messages'));
  if (kinds.function) parts.push(plural(kinds.function, 'function of the device', 'functions of the device'));
  if (kinds.unassigned) parts.push(`${kinds.unassigned} unassigned`);
  out.push({ label: 'Buttons', text: parts.join(' · ') });
  let shifted = 0; for (let id = 0; id < 41; id++) if (shiftedKind(cfg, id)) shifted++;
  const hasFn = kinds.function || shifted;
  if (hasFn) out.push({ label: 'Modes', text: `${shifted ? `${plural(shifted, 'button does', 'buttons do')} something else with Shift held · ` : ''}velocity curve ${D.VEL_CURVES[byte(cfg, 'vel_curve')] ?? '?'}${byte(cfg, 'press_mode') ? ` · pad pressure ${D.PRESS_MODES[byte(cfg, 'press_mode')]}` : ''}` });
  const enc = byte(cfg, 'enc_cc'), strip = byte(cfg, 'strip_cc');
  out.push({ label: 'Encoder, strip', text: `encoder ${enc === 0xff ? 'nothing' : `CC ${enc}, ${D.ENC_MODES[byte(cfg, 'enc_mode')]}`} · strip ${strip === 0xff ? 'nothing' : `CC ${strip}`} · channel ${byte(cfg, 'channel') + 1}` });
  const lf = byte(cfg, 'led_flags'), L = D.LED_FLAGS, lights = [];
  if (lf & L.BTN_IDLE) lights.push(`buttons ${LEVEL[byte(cfg, 'btn_led_idle')] ?? 'lit'} at rest`);
  if (lf & L.BTN_PRESS) lights.push('buttons light when pressed');
  if (lf & L.PAD_IDLE) lights.push(`pads ${colour(byte(cfg, 'pad_colour'))}`);
  if (lf & L.PAD_HIT) lights.push('pads flash when hit');
  if (lf & L.STRIP) lights.push(`strip ${colour(byte(cfg, 'strip_colour'))}`);
  out.push({ label: 'Lighting', text: lights.length ? lights.join(' · ') : 'off (only what apps send)' });
  return out;
}

const SCALARS = [
  ['channel', 'MIDI channel', (v) => v + 1], ['enc_cc', 'Encoder CC', (v) => (v === 0xff ? 'nothing' : v)], ['enc_mode', 'Encoder mode', (v) => D.ENC_MODES[v]],
  ['enc_init', 'Encoder start value', (v) => v], ['strip_cc', 'Strip CC', (v) => (v === 0xff ? 'nothing' : v)], ['flags', 'Strip sends 0 on release', (v) => (v & 1 ? 'yes' : 'no')],
  ['vel_shift', 'Pad velocity gain', (v) => v], ['sens', 'Pad sensitivity', (v) => (v === 0xff ? 'device default' : v)], ['btn_mode', 'CC button mode', (v) => D.BTN_MODES[v]],
  ['led_channel', 'LED message channel', (v) => v + 1], ['btn_led_idle', 'Button level at rest', (v) => LEVEL[v] ?? v], ['btn_led_on', 'Button level when pressed', (v) => LEVEL[v] ?? v],
  ['pad_colour', 'Pad colour', colour], ['strip_colour', 'Strip colour', colour],
  ['vel_curve', 'Velocity curve', (v) => D.VEL_CURVES[v] ?? v], ['fixvel', 'Fixed Vel value', (v) => v], ['keys_root', 'Keyboard mode: first note', (v) => `${v} (${M.noteName(v)})`],
  ['press_mode', 'Pad pressure', (v) => D.PRESS_MODES[v] ?? v], ['press_cc', 'Pad pressure CC', (v) => v],
  ['scale', 'Scale', (v) => D.SCALE_NAMES[v] ?? v], ['chord_type', 'Chord type', (v) => D.CHORD_NAMES[v] ?? v],
  ['arp_type', 'Arp pattern', (v) => D.ARP_TYPES[v] ?? v], ['arp_rate', 'Arp rate', (v) => D.ARP_RATES[v] ?? v], ['arp_oct', 'Arp octaves', (v) => v], ['tempo', 'Start tempo (BPM)', (v) => v + 20],
  ['enc_pages', 'Encoder pages', (v) => v], ['enc_page_step', 'Encoder CC step per page', (v) => v], ['enc_accel', 'Encoder acceleration', (v) => ['off', 'gentle', 'medium', 'strong'][v] ?? v],
];
const LED_BITS = [[D.LED_FLAGS.BTN_IDLE, 'buttons rest dimly lit'], [D.LED_FLAGS.BTN_PRESS, 'buttons light when pressed'], [D.LED_FLAGS.PAD_IDLE, 'pads rest in their colour'],
                  [D.LED_FLAGS.PAD_HIT, 'pads flash when hit'], [D.LED_FLAGS.STRIP, 'strip LED follows the finger']];

/** What changes when the configuration `a` becomes `b`: a list of short lines. */
export function diffCfg(a, b) {
  const out = [];
  for (let id = 0; id < 41; id++) {
    if (byte(a, 'btn_act', id) !== byte(b, 'btn_act', id) || byte(a, 'btn_cc', id) !== byte(b, 'btn_cc', id)) {
      const x = describeButton(a, id), y = describeButton(b, id);
      if (x !== y) out.push(`${D.BUTTON_NAMES[id]}: ${x} → ${y}`);
    }
    if (byte(a, 'btn_act2', id) !== byte(b, 'btn_act2', id) || byte(a, 'btn_cc2', id) !== byte(b, 'btn_cc2', id)) {
      const x = shiftedKind(a, id) ? describeButton(a, id, 1) : 'as without Shift', y = shiftedKind(b, id) ? describeButton(b, id, 1) : 'as without Shift';
      if (x !== y) out.push(`${D.BUTTON_NAMES[id]} with Shift: ${x} → ${y}`);
    }
  }
  const modeOf = (c, id) => { const o = (byte(c, 'btn_mode_ovr', id >> 2) >> ((id & 3) * 2)) & 3; return D.BTN_MODES[o ? o - 1 : byte(c, 'btn_mode')]; };
  for (let id = 0; id < 41; id++) { const x = modeOf(a, id), y = modeOf(b, id); if (x !== y && (D.ACTION_NAMES[byte(b, 'btn_act', id)] === 'cc' || D.ACTION_NAMES[byte(a, 'btn_act', id)] === 'cc')) out.push(`${D.BUTTON_NAMES[id]}: CC mode ${x} → ${y}`); }
  const pa = padNotes(a), pb = padNotes(b), changed = pa.map((v, i) => i).filter((i) => pa[i] !== pb[i]);
  if (changed.length) {
    if (consecutive(pa) && consecutive(pb)) out.push(`Pad notes: ${pa[0]}–${pa[15]} → ${pb[0]}–${pb[15]}`);
    else if (changed.length <= 4) for (const i of changed) out.push(`Pad ${i + 1}: note ${pa[i]} → ${pb[i]}`);
    else out.push(`${changed.length} pads play other notes`);
  }
  for (const [name, label, f] of SCALARS) {
    const x = byte(a, name), y = byte(b, name);
    if (x !== y && f(x) !== f(y)) out.push(`${label}: ${f(x)} → ${f(y)}`);
  }
  for (let i = 0; i < 3; i++) { const x = byte(a, 'enc_tgt_cc', i), y = byte(b, 'enc_tgt_cc', i); if (x !== y) out.push(`Encoder target ${i + 1} CC: ${x === 0xff ? 'nothing' : x} → ${y === 0xff ? 'nothing' : y}`); }
  const la = byte(a, 'led_flags'), lb = byte(b, 'led_flags');
  for (const [bit, text] of LED_BITS) if ((la & bit) !== (lb & bit)) out.push(`Lighting: ${text} → ${lb & bit ? 'on' : 'off'}`);
  const rest = (c) => M.hex(c.slice(FD.pad_led[0], FD.pad_led[0] + 16)) + M.hex(c.slice(FD.boot_ms[0], FD.boot_ms[0] + 2));
  if (rest(a) !== rest(b)) out.push('Other settings (pad LED map, start-up delay)');
  return out;
}

// ---- the store ----
const defaultId = () => `u-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export class PresetStore {
  /** storage: anything with getItem / setItem (localStorage), or null to keep the presets in memory only. */
  constructor({ storage = null, builtins = D.BUILTIN_PRESETS, now = Date.now, newId = defaultId } = {}) {
    this.storage = storage; this.now = now; this.newId = newId; this.persistent = !!storage;
    this.builtins = builtins.map((b) => ({ id: b.id, name: b.name, display: M.displayName(b.display_name || ''), description: b.description, cfg: cfgFromHex(b.cfg_hex), builtin: true }));
    this.user = [];
    try {
      const raw = storage?.getItem(STORAGE_KEY);
      if (raw) this.user = (JSON.parse(raw).presets || []).map((o) => this.fromStored(o)).filter(Boolean);
    } catch { this.persistent = false; }
  }

  fromStored(o) {
    const cfg = cfgFromHex(o?.cfg);
    if (!cfg || typeof o.name !== 'string' || !o.name.trim()) return null;
    return { id: typeof o.id === 'string' ? o.id : this.newId(), name: o.name.trim().slice(0, 60), display: M.displayName(o.display || ''), description: String(o.description || '').slice(0, 400), cfg, builtin: false, created: o.created || this.now(), modified: o.modified || this.now() };
  }

  persist() {
    try { this.storage?.setItem(STORAGE_KEY, JSON.stringify({ format: D.PRESET_FILE_FORMAT, presets: this.user.map((p) => ({ id: p.id, name: p.name, display: p.display, description: p.description, cfg: M.hex(p.cfg), created: p.created, modified: p.modified })) })); return true; }
    catch { this.persistent = false; return false; }
  }

  list() { return [...this.builtins, ...this.user]; }
  get(id) { return this.list().find((p) => p.id === id) || null; }
  /** The first preset whose configuration equals `cfg`, or null. */
  find(cfg) { return this.list().find((p) => M.equal(p.cfg, cfg)) || null; }

  /** `name` made unique among all presets (a number is added). */
  uniqueName(name, exceptId = null) {
    const base = (name || 'Preset').trim().slice(0, 56) || 'Preset', taken = new Set(this.list().filter((p) => p.id !== exceptId).map((p) => p.name.toLowerCase()));
    let n = base, i = 2;
    while (taken.has(n.toLowerCase())) n = `${base} ${i++}`;
    return n;
  }

  add({ name, display = '', description = '', cfg }) {
    if (M.check(cfg) !== null) throw new Error('this configuration is not valid');
    const p = { id: this.newId(), name: this.uniqueName(name), display: M.displayName(display), description: description.trim().slice(0, 400), cfg: Uint8Array.from(cfg), builtin: false, created: this.now(), modified: this.now() };
    this.user.push(p); this.persist();
    return p;
  }

  update(id, { name, display, description, cfg } = {}) {
    const p = this.user.find((x) => x.id === id);
    if (!p) throw new Error('only your own presets can be changed');
    if (name !== undefined) p.name = this.uniqueName(name, id);
    if (display !== undefined) p.display = M.displayName(display);
    if (description !== undefined) p.description = description.trim().slice(0, 400);
    if (cfg !== undefined) { if (M.check(cfg) !== null) throw new Error('this configuration is not valid'); p.cfg = Uint8Array.from(cfg); }
    p.modified = this.now(); this.persist();
    return p;
  }

  remove(id) {
    const i = this.user.findIndex((x) => x.id === id);
    if (i < 0) throw new Error('only your own presets can be deleted');
    this.user.splice(i, 1); this.persist();
  }

  duplicate(id) {
    const p = this.get(id);
    if (!p) throw new Error('no such preset');
    return this.add({ name: `${p.name} (copy)`, display: p.display, description: p.description, cfg: p.cfg });
  }

  /** The text of a preset file with the given presets (default: all of the user's own). */
  exportJSON(ids = null) {
    const list = ids ? ids.map((i) => this.get(i)).filter(Boolean) : this.user;
    return JSON.stringify({ format: D.PRESET_FILE_FORMAT, presets: list.map((p) => ({ name: p.name, display_name: M.presetDisplayName(p), description: p.description, cfg: M.hex(p.cfg) })) }, null, 1);
  }

  /** Adds the presets of a preset file (or of the older single-mapping file); returns { added: [presets], skipped }. Throws on a file that
   *  is not one of ours. A preset already here with the same name and configuration is skipped, a name that is taken gets a number. */
  importJSON(text) {
    const j = JSON.parse(text);
    let incoming;
    if (j.format === D.PRESET_FILE_FORMAT) incoming = j.presets;
    else if (j.format === 'mmk3-config-1') incoming = [{ name: 'Imported mapping', description: 'From a mapping file.', cfg: M.hex(M.fromDict(j.config)) }];
    else throw new Error('this is not a preset file from this tool');
    const added = []; let skipped = 0;
    for (const o of incoming) {
      const cfg = cfgFromHex(o.cfg);
      if (!cfg || typeof o.name !== 'string') throw new Error(`the preset "${o?.name}" in this file is not valid`);
      if (this.list().some((p) => p.name === o.name.trim() && M.equal(p.cfg, cfg))) { skipped++; continue; }
      added.push(this.add({ name: o.name, display: o.display_name || '', description: String(o.description || ''), cfg }));
    }
    return { added, skipped };
  }
}
