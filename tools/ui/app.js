// The page: edit the Mikro MK3's mapping, send it to the device (Web MIDI SysEx), keep it there, and flash the patched firmware (WebUSB DFU).
// Everything runs in the browser; nothing is uploaded. The protocol is mmk3.js, the flashing is dfu.js + patch.js.
import * as M from './mmk3.js';
import * as P from './patch.js';
import * as F from './dfu.js';
import * as PR from './presets.js';
import { makeMock } from './mock.js';

const D = M.D, FD = D.FIELDS;
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== false && v !== null) e.setAttribute(k, v === true ? '' : v);
  }
  e.append(...kids);
  return e;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- state ----
const state = { cfg: M.defaultCfg(), deviceCfg: null, info: null, client: null, name: '', mock: null, midi: null, live: false, presetId: 'default' };
const store = new PR.PresetStore({ storage: (() => { try { return window.localStorage; } catch { return null; } })() });
const syncers = [];
const addSync = (fn) => { syncers.push(fn); fn(); return fn; };
let sendTimer = null;

function say(text, error = false) {
  const s = $('status-text'); s.textContent = text; $('status').classList.toggle('error', error);
  $('log').textContent += `${new Date().toLocaleTimeString()}  ${text}\n`; $('log').scrollTop = $('log').scrollHeight;
}

const fieldAt = (off) => { for (const [n, [o, c]] of Object.entries(FD)) if (off >= o && off < o + c) return c > 1 ? `${n}[${off - o}]` : n; return `byte ${off}`; };

// ---- widgets ----
function numField({ get, set, min, max, none = false, noneLabel = 'none', label }) {
  const input = el('input', { type: 'number', min, max, 'aria-label': label || '' });
  const cb = none ? el('input', { type: 'checkbox', 'aria-label': `${label || ''}: ${noneLabel}` }) : null;
  let last = min;
  const sync = () => {
    const v = get();
    input.classList.remove('bad');
    if (none && v === 0xff) { cb.checked = true; input.disabled = true; input.value = ''; }
    else { input.disabled = false; input.value = v; last = v; if (cb) cb.checked = false; }
  };
  input.addEventListener('input', () => {
    const n = Number(input.value);
    if (input.value !== '' && Number.isInteger(n) && n >= min && n <= max) { input.classList.remove('bad'); set(n); edited(); } else input.classList.add('bad');
  });
  input.addEventListener('change', sync);
  if (cb) cb.addEventListener('change', () => { set(cb.checked ? 0xff : last); edited(); sync(); });
  addSync(sync);
  return el('span', { class: 'field' }, input, ...(cb ? [cb, el('span', { text: noneLabel })] : []));
}

function selectField(sel, options, get, set) {
  for (const [v, text] of options) sel.append(el('option', { value: String(v), text }));
  sel.addEventListener('change', () => { set(Number(sel.value)); edited(); });
  addSync(() => { sel.value = String(get()); });
}

function checkField(cb, get, set) {
  cb.addEventListener('change', () => { set(cb.checked); edited(); });
  addSync(() => { cb.checked = get(); });
}

// ---- config accessors ----
const byte = (name, i = 0) => ({ get: () => state.cfg[FD[name][0] + i], set: (v) => { state.cfg[FD[name][0] + i] = v; } });
const ledFlag = (bit) => ({ get: () => !!(state.cfg[FD.led_flags[0]] & bit), set: (on) => { state.cfg[FD.led_flags[0]] = on ? state.cfg[FD.led_flags[0]] | bit : state.cfg[FD.led_flags[0]] & ~bit; } });

// ---- buttons ----
const ACTIONS = [['cc', 'Control Change (CC)'], ['note', 'Note'], ['start', 'MIDI Start'], ['continue', 'MIDI Continue'], ['stop', 'MIDI Stop'], ['mmc', 'MMC command'], ['none', 'Nothing'],
  ['padmode', 'Pad Mode: drum notes'], ['keys', 'Keyboard: chromatic notes'], ['fixvel', 'Fixed Vel (every note at one velocity)'], ['vel16', '16 Velocities'],
  ['curve', 'Velocity curve: step'], ['transpose', 'Transpose pads'], ['panic', 'Panic: all notes off'], ['shift', 'Shift (hold)'],
  ['scale', 'Scale: step'], ['chords', 'Chords mode'], ['chordtype', 'Chord type: step'], ['strip', 'Touch strip mode'], ['enctgt', 'Encoder target'], ['program', 'Program Change'],
  ['tap', 'Tap tempo'], ['clockout', 'MIDI clock out (on / off)'], ['arp', 'Arp / Note Repeat (on / off)'], ['arptype', 'Arp pattern: step'], ['rate', 'Arp rate: step'], ['arpoct', 'Arp octaves: step'],
  ['latch', 'Arp latch (hold)'], ['mute', 'Mute pads (edit)'], ['solo', 'Solo pads (edit)'], ['clear', 'Clear mutes and solos'], ['snap', 'Snapshot (Lock)'],
  ['channel', 'MIDI channel: step'], ['slot', 'Preset slot (load / store)'], ['step', 'Step sequencer mode'], ['seqrun', 'Sequencer start / restart'], ['seqsel', 'Sequencer: select track (hold)'],
  ['seqpat', 'Sequencer pattern: step'], ['seqclear', 'Sequencer clear'], ['seqsave', 'Sequencer: keep patterns']];
const PARAM_CHOICES = {
  curve: [[0, 'Next curve'], [1, 'Previous curve']], scale: [[0, 'Next scale'], [1, 'Previous scale']], chordtype: [[0, 'Next type'], [1, 'Previous type']],
  strip: [[0, 'The configured CC'], [1, 'Pitch bend'], [2, 'Mod wheel (holds, bar)'], [3, 'Strum notes']],
  channel: [[0, 'Next channel'], [1, 'Previous channel']], seqrun: [[0, 'Start / stop'], [1, 'Restart']], seqpat: [[0, 'Next pattern'], [1, 'Previous pattern']], seqclear: [[0, 'The selected track'], [1, 'The whole pattern']],
  slot: [[0, 'Load slot 1'], [1, 'Load slot 2'], [2, 'Load slot 3'], [3, 'Load slot 4'], [4, 'Store in slot 1'], [5, 'Store in slot 2'], [6, 'Store in slot 3'], [7, 'Store in slot 4']],
  arptype: [[0, 'Next pattern'], [1, 'Previous pattern']], rate: [[0, 'Next rate'], [1, 'Previous rate']], snap: [[0, 'Store, then recall'], [1, 'Store again']], enctgt: [[0, 'Target 1'], [1, 'Target 2'], [2, 'Target 3']], program: [[0, 'Next'], [1, 'Previous'], [2, 'Back to 0']],
};
const MMC = [[1, 'Stop'], [2, 'Play'], [4, 'Fast forward'], [5, 'Rewind'], [6, 'Record strobe'], [9, 'Pause']];
const HINTS = { padmode: 'the pads play the notes of the Pads tab', keys: 'pad 1 = the first note (Pads tab), chromatic upwards', fixvel: 'toggle · lit while on', vel16: 'toggle · all pads, one note',
  panic: 'All Sound Off + All Notes Off', shift: 'hold, then press another button', chords: 'a chord on each pad (scale and type below)', scale: 'Keyboard and Chords mode follow it',
  chordtype: 'triad, seventh, sus2, sus4, power', strip: 'mod: the strip shows the value as a bar; strum: the strip plays the held pads\' notes', tap: 'tap the beat; ignored while a MIDI clock comes in', clockout: '24 pulses per beat, Start / Stop on switching',
  arp: 'held pads play in time (pattern and rate below)', arpoct: 'steps 1 to 4 octaves', latch: 'the arp goes on after the pads are released', mute: 'then hit pads to mute them', solo: 'then hit pads to solo them', clear: 'all pads play again', channel: 'kept when unplugged; a panic is sent on the old channel', slot: 'four configs in the device\'s flash', step: 'pads = the 16 steps of the selected track', seqrun: 'follows the tempo / clock', seqsel: 'hold, then hit a pad', seqpat: '4 patterns', seqclear: 'on the pattern shown', seqsave: 'patterns come back at power-up', enctgt: 'CCs are on the Encoder & strip tab; again = back', program: 'message on the screen' };
const GROUPS = [
  ['Transport', [22, 23, 24]], ['Pad modes', [26, 27, 28, 29, 30]], ['Scenes and patterns', [14, 31, 32, 33, 34]], ['Edit', [35, 36, 37, 38, 18, 19, 20, 21]],
  ['Pages', [3, 4, 5, 6, 7, 10, 11, 12, 13]], ['Navigation', [8, 9, 25, 0, 1, 2]], ['Performance', [15, 16, 17]], ['Encoder', [39, 40]],
];
const niCc = (id) => D.NI_BUTTON_CC[String(id)] ?? 0;
const anyShifted = (cfg) => { for (let id = 0; id < 41; id++) { const a = cfg[FD.btn_act2[0] + id]; if (D.ACTION_NAMES[a] !== 'none' && !(D.ACTION_NAMES[a] === 'cc' && cfg[FD.btn_cc2[0] + id] === 0xff)) return true; } return false; };

function buildButtons() {
  const list = $('blist');
  list.append(el('div', { class: 'head', text: 'Button' }), el('div', { class: 'head', text: 'Sends / does' }), el('div', { class: 'head', text: 'Number' }), el('div', { class: 'head', text: '' }));
  for (const [title, ids] of GROUPS) {
    list.append(el('div', { class: 'grp', text: title }));
    for (const id of ids) list.append(...buttonRow(id, 0), ...buttonRow(id, 1));
  }
  const cb = $('show-shift');
  cb.addEventListener('change', () => list.classList.toggle('noshift', !cb.checked));
  addSync(() => { if (anyShifted(state.cfg)) cb.checked = true; list.classList.toggle('noshift', !cb.checked); });
}

/** One row of the button list: layer 0 = what the button does, layer 1 = what it does while a Shift button is held ("Nothing" there = the normal action). */
function buttonRow(id, layer) {
  const A = FD[layer ? 'btn_act2' : 'btn_act'][0] + id, C = FD[layer ? 'btn_cc2' : 'btn_cc'][0] + id, tag = `${D.BUTTON_NAMES[id]}${layer ? ' with Shift' : ''}`;
  const name = layer ? el('div', { class: 'name sub' }, el('i'), el('span', { text: 'with Shift' })) : el('div', { class: 'name' }, el('i'), el('span', { text: D.BUTTON_NAMES[id] }));
  const sel = el('select', { 'aria-label': `${tag}: sends` });
  const numWrap = el('div');
  const num = el('input', { type: 'number', min: 0, max: 127, 'aria-label': `${tag}: number` });
  const mmc = el('select', { 'aria-label': `${tag}: MMC command` });
  const curve = el('select', { 'aria-label': `${tag}: choice` });
  const semi = el('input', { type: 'number', min: -64, max: 63, 'aria-label': `${tag}: semitones`, title: 'Semitones (+12 = one octave up)' });
  for (const [v, t] of MMC) mmc.append(el('option', { value: v, text: t }));
  const hint = el('div', { class: 'hint' });
  for (const [v, t] of ACTIONS) sel.append(el('option', { value: v, text: v === 'none' && layer ? 'Same as without Shift' : t }));
  numWrap.append(num, mmc, curve, semi);
  const effective = () => (state.cfg[A] === 0 && state.cfg[C] === 0xff ? 'none' : D.ACTION_NAMES[state.cfg[A]]);
  const sync = () => {
    const act = effective(), p = state.cfg[C];
    sel.value = act;
    num.hidden = !(act === 'cc' || act === 'note'); mmc.hidden = act !== 'mmc'; curve.hidden = !(act in PARAM_CHOICES); semi.hidden = act !== 'transpose';
    if (!num.hidden) { num.value = p > 127 ? '' : p; num.classList.remove('bad'); }
    if (!mmc.hidden) mmc.value = String(MMC.some(([v]) => v === p) ? p : 2);
    if (!curve.hidden) {
      if (curve.dataset.for !== act) { curve.replaceChildren(...PARAM_CHOICES[act].map(([v, t]) => el('option', { value: v, text: t }))); curve.dataset.for = act; }
      curve.value = String(PARAM_CHOICES[act].some(([v]) => v === p) ? p : 0);
    }
    if (!semi.hidden) { semi.value = p > 127 ? 0 : p - 64; semi.classList.remove('bad'); }
    hint.textContent = act === 'note' && p <= 127 ? M.noteName(p) : act === 'cc' ? (p <= 127 ? `CC ${p}` : '') : act === 'mmc' ? 'F0 7F 7F 06 …' : act === 'none' ? '' : act === 'curve' ? 'message on the screen' : act === 'transpose' ? 'semitones; applies to the pads' : HINTS[act] ?? 'on press';
    $('blist').querySelectorAll(`[data-btn="${id}${layer ? 's' : ''}"]`).forEach((n) => n.classList.toggle('changed', !!state.deviceCfg && (state.cfg[A] !== state.deviceCfg[A] || state.cfg[C] !== state.deviceCfg[C])));
  };
  sel.addEventListener('change', () => {
    const v = sel.value;
    if (v === 'none') { state.cfg[A] = D.ACTION_NAMES.indexOf('none'); state.cfg[C] = 0xff; }
    else {
      state.cfg[A] = D.ACTION_NAMES.indexOf(v);
      if (v === 'cc' && state.cfg[C] > 127) state.cfg[C] = niCc(id);
      else if (v === 'note' && state.cfg[C] > 127) state.cfg[C] = 60;
      else if (v === 'mmc' && !MMC.some(([m]) => m === state.cfg[C])) state.cfg[C] = 2;
      else if (v in PARAM_CHOICES) state.cfg[C] = 0;
      else if (v === 'transpose') state.cfg[C] = 65;
      else if (!['cc', 'note', 'mmc'].includes(v)) state.cfg[C] = 0xff;
    }
    edited();
  });
  num.addEventListener('input', () => {
    const n = Number(num.value);
    if (num.value !== '' && Number.isInteger(n) && n >= 0 && n <= 127) { num.classList.remove('bad'); state.cfg[C] = n; edited(); } else num.classList.add('bad');
  });
  num.addEventListener('change', sync);
  mmc.addEventListener('change', () => { state.cfg[C] = Number(mmc.value); edited(); });
  curve.addEventListener('change', () => { state.cfg[C] = Number(curve.value); edited(); });
  semi.addEventListener('input', () => {
    const n = Number(semi.value);
    if (semi.value !== '' && Number.isInteger(n) && n >= -64 && n <= 63) { semi.classList.remove('bad'); state.cfg[C] = 64 + n; edited(); } else semi.classList.add('bad');
  });
  semi.addEventListener('change', sync);
  const cells = [name, el('div', {}, sel), numWrap, hint];
  cells.forEach((c) => { c.setAttribute('data-btn', `${id}${layer ? 's' : ''}`); if (layer) c.classList.add('srow'); });
  addSync(sync);
  return cells;
}

// ---- pads ----
function buildPads() {
  const grid = $('pads');
  for (const row of [[13, 14, 15, 16], [9, 10, 11, 12], [5, 6, 7, 8], [1, 2, 3, 4]]) {
    for (const n of row) {
      const p = D.PAD_LABEL.indexOf(n), O = FD.pad_note[0] + p;
      const nn = el('span', { class: 'nn' });
      const input = el('input', { type: 'number', min: 0, max: 127, 'aria-label': `Pad ${n}: note` });
      const cell = el('div', { class: 'pad' }, el('span', { class: 'no', text: String(n) }), input, nn);
      input.addEventListener('input', () => {
        const v = Number(input.value);
        if (input.value !== '' && Number.isInteger(v) && v >= 0 && v <= 127) { input.classList.remove('bad'); state.cfg[O] = v; edited(); } else input.classList.add('bad');
      });
      input.addEventListener('change', resyncAll);
      grid.append(cell);
      addSync(() => {
        input.value = state.cfg[O]; input.classList.remove('bad'); nn.textContent = M.noteName(state.cfg[O]);
        cell.classList.toggle('changed', !!state.deviceCfg && state.cfg[O] !== state.deviceCfg[O]);
        const colour = state.cfg[FD.pad_colour[0]] || 17;
        cell.style.setProperty('--padc', COLOURS[colour - 1]);
      });
    }
  }
  const apply = (base) => {
    if (!(base >= 0 && base <= 112)) { say('The first note must be between 0 and 112 so that all 16 pads fit.', true); return; }
    D.PAD_LABEL.forEach((n, p) => { state.cfg[FD.pad_note[0] + p] = base + n - 1; });
    edited();
  };
  $('padbase-apply').addEventListener('click', () => apply(Number($('padbase').value)));
  document.querySelectorAll('[data-padbase]').forEach((b) => b.addEventListener('click', () => { $('padbase').value = b.dataset.padbase; apply(Number(b.dataset.padbase)); }));
}
const resyncAll = () => syncers.forEach((f) => f());

// ---- the other tabs ----
const COLOURS = ['#ff3b30', '#ff7a1a', '#ffa64d', '#ffcc33', '#f2ee3a', '#aee83a', '#2fd35c', '#3fe0a6', '#33d6e0', '#2bb3d9', '#2f6dff', '#8d52d9', '#a560f0', '#c24fe3', '#ea3fb6', '#ff5a9a', '#f1f1ee'];
const CURVE_LABELS = ['Soft 3 (softest)', 'Soft 2', 'Soft 1', 'Linear (NI\'s default)', 'Hard 1', 'Hard 2', 'Hard 3 (hardest)', 'Fixed (always 127)', 'Custom table (if built in)'];
const PRESS_LABELS = ['Polyphonic aftertouch (per pad)', 'Channel pressure (one value)', 'Control Change (choose the CC)', 'Off'];
const LEVELS = [[0, 'Off'], [0x7c, 'Dim'], [0x7e, 'Normal'], [0x7f, 'Bright']];

function swatches(host, name) {
  const buttons = D.COLOUR_NAMES.map((cname, i) => {
    const b = el('button', { type: 'button', title: cname, 'aria-label': cname, style: `--sw:${COLOURS[i]}`, class: i === 16 ? 'white' : '' });
    b.addEventListener('click', () => { state.cfg[FD[name][0]] = i + 1; edited(); });
    host.append(b);
    return b;
  });
  addSync(() => { const v = state.cfg[FD[name][0]] || 17; buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(v === i + 1))); });
}

function buildOthers() {
  $('f-enc_cc').replaceWith(numField({ ...byte('enc_cc'), min: 0, max: 127, none: true, noneLabel: 'nothing', label: 'Encoder CC' }));
  $('f-strip_cc').replaceWith(numField({ ...byte('strip_cc'), min: 0, max: 127, none: true, noneLabel: 'nothing', label: 'Strip CC' }));
  selectField($('f-enc_mode'), [[1, 'Absolute 0–127 (no wrap)'], [0, 'Relative: 64 ± steps'], [2, 'Relative: 1…63 up, 127…65 down']], () => state.cfg[FD.enc_mode[0]], (v) => { state.cfg[FD.enc_mode[0]] = v; });
  $('f-enc_init').addEventListener('input', (e) => { const n = Number(e.target.value); if (e.target.value !== '' && Number.isInteger(n) && n >= 0 && n <= 127) { e.target.classList.remove('bad'); state.cfg[FD.enc_init[0]] = n; edited(); } else e.target.classList.add('bad'); });
  addSync(() => { $('f-enc_init').value = state.cfg[FD.enc_init[0]]; });
  checkField($('f-flags0'), () => !!(state.cfg[FD.flags[0]] & 1), (on) => { state.cfg[FD.flags[0]] = on ? 1 : 0; });
  selectField($('f-channel'), Array.from({ length: 16 }, (_, i) => [i, String(i + 1)]), () => state.cfg[FD.channel[0]], (v) => { state.cfg[FD.channel[0]] = v; });
  selectField($('f-btn_mode'), [[0, 'Gate: 127 while held, 0 when released'], [1, 'Toggle: 127 / 0 on alternate presses'], [2, 'Trigger: 127 on press only']], () => state.cfg[FD.btn_mode[0]], (v) => { state.cfg[FD.btn_mode[0]] = v; });
  selectField($('f-vel_shift'), [[1, '1: most sensitive'], [2, '2'], [3, '3'], [4, '4'], [5, '5: default'], [6, '6'], [7, '7'], [8, '8: least sensitive']], () => state.cfg[FD.vel_shift[0]], (v) => { state.cfg[FD.vel_shift[0]] = v; });
  selectField($('f-vel_curve'), D.VEL_CURVES.map((n, i) => [i, CURVE_LABELS[i] ?? n]), () => state.cfg[FD.vel_curve[0]], (v) => { state.cfg[FD.vel_curve[0]] = v; });
  $('f-fixvel').replaceWith(numField({ ...byte('fixvel'), min: 1, max: 127, label: 'Fixed Vel value' }));
  $('f-keys_root').replaceWith(numField({ ...byte('keys_root'), min: 0, max: 127, label: 'Keyboard mode: first note' }));
  addSync(() => { $('keys-root-name').textContent = M.noteName(state.cfg[FD.keys_root[0]]); });
  selectField($('f-scale'), D.SCALE_NAMES.map((n, i) => [i, n[0].toUpperCase() + n.slice(1)]), () => state.cfg[FD.scale[0]], (v) => { state.cfg[FD.scale[0]] = v; });
  selectField($('f-chord_type'), D.CHORD_NAMES.map((n, i) => [i, n[0].toUpperCase() + n.slice(1)]), () => state.cfg[FD.chord_type[0]], (v) => { state.cfg[FD.chord_type[0]] = v; });
  for (let i = 0; i < 3; i++) $(`f-enc_tgt${i}`).replaceWith(numField({ ...byte('enc_tgt_cc', i), min: 0, max: 127, none: true, noneLabel: 'nothing', label: `Encoder target ${i + 1} CC` }));
  selectField($('f-arp_type'), D.ARP_TYPES.map((n, i) => [i, n[0].toUpperCase() + n.slice(1)]), () => state.cfg[FD.arp_type[0]], (v) => { state.cfg[FD.arp_type[0]] = v; });
  selectField($('f-arp_rate'), D.ARP_RATES.map((n, i) => [i, n]), () => state.cfg[FD.arp_rate[0]], (v) => { state.cfg[FD.arp_rate[0]] = v; });
  selectField($('f-arp_oct'), [1, 2, 3, 4].map((n) => [n, String(n)]), () => state.cfg[FD.arp_oct[0]], (v) => { state.cfg[FD.arp_oct[0]] = v; });
  $('f-tempo').replaceWith(numField({ get: () => state.cfg[FD.tempo[0]] + 20, set: (v) => { state.cfg[FD.tempo[0]] = v - 20; }, min: 20, max: 275, label: 'Start tempo' }));
  selectField($('f-press_mode'), D.PRESS_MODES.map((n, i) => [i, PRESS_LABELS[i] ?? n]), () => state.cfg[FD.press_mode[0]], (v) => { state.cfg[FD.press_mode[0]] = v; });
  $('f-press_cc').replaceWith(numField({ ...byte('press_cc'), min: 0, max: 127, label: 'Pressure CC' }));
  addSync(() => { $('press-cc-row').hidden = state.cfg[FD.press_mode[0]] !== 2; });
  $('f-sens').replaceWith(numField({ ...byte('sens'), min: 0, max: 100, none: true, noneLabel: 'device default', label: 'Pad sensitivity' }));
  for (let b = 0; b < 5; b++) checkField($(`f-led${b}`), ledFlag(1 << b).get, ledFlag(1 << b).set);
  swatches($('sw-pad'), 'pad_colour'); swatches($('sw-strip'), 'strip_colour');
  selectField($('f-btn_led_idle'), LEVELS, () => state.cfg[FD.btn_led_idle[0]], (v) => { state.cfg[FD.btn_led_idle[0]] = v; });
  selectField($('f-btn_led_on'), LEVELS, () => state.cfg[FD.btn_led_on[0]], (v) => { state.cfg[FD.btn_led_on[0]] = v; });
  selectField($('f-led_channel'), Array.from({ length: 16 }, (_, i) => [i, String(i + 1)]), () => state.cfg[FD.led_channel[0]], (v) => { state.cfg[FD.led_channel[0]] = v; });
  // an LED level the select does not know (a config made elsewhere) still shows up
  for (const id of ['f-btn_led_idle', 'f-btn_led_on']) {
    const sel = $(id);
    addSync(() => { if (![...sel.options].some((o) => o.value === sel.value)) { sel.append(el('option', { value: sel.value || '0', text: `code ${sel.value}` })); } });
  }
}

// ---- chrome: chips, buttons ----
function refreshAll() { syncers.forEach((f) => f()); updateChrome(); }
function edited() { state.touched = true; refreshAll(); if (state.live && state.client) { clearTimeout(sendTimer); sendTimer = setTimeout(() => sendToDevice(true).catch((e) => say(e.message, true)), 200); } }

function syncState() {
  if (!state.client) return ['Editing offline', ''];
  if (!state.deviceCfg || !M.equal(state.cfg, state.deviceCfg)) return ['Edited, not sent', 'edit'];
  if (state.info?.unsaved_changes) return ['On the device, not saved', 'warn'];
  return state.info?.saved ? ['Saved on the device', 'ok'] : ['Device defaults', 'ok'];
}

/** The preset the editor shows: the one with exactly these bytes, else the one it was loaded from (then it is "modified"), else none. */
function currentPreset() {
  const exact = store.find(state.cfg);
  if (exact) return { preset: exact, modified: false };
  const from = state.presetId && store.get(state.presetId);
  return from ? { preset: from, modified: true } : { preset: null, modified: false };
}

function updatePresetChrome() {
  const { preset, modified } = currentPreset();
  if (preset && !modified) state.presetId = preset.id;                  // from here on edits show as "<preset> (modified)"
  const sel = $('preset-select');
  if (sel.dataset.sig !== store.list().map((p) => p.id + p.name).join('|') + (preset ? '' : '|custom')) {
    sel.replaceChildren();
    const g1 = el('optgroup', { label: 'Built-in' }), g2 = el('optgroup', { label: 'My presets' });
    for (const p of store.list()) (p.builtin ? g1 : g2).append(el('option', { value: p.id, text: p.name }));
    sel.append(g1); if (g2.children.length) sel.append(g2);
    if (!preset) sel.append(el('option', { value: '', text: 'Custom (not a preset)' }));
    sel.dataset.sig = store.list().map((p) => p.id + p.name).join('|') + (preset ? '' : '|custom');
  }
  sel.value = preset ? preset.id : '';
  $('preset-mod').hidden = !modified;
  $('cur-name').textContent = preset ? preset.name : 'Custom configuration';
  $('cur-note').textContent = modified ? '(changed since it was loaded)' : preset ? '' : '(not saved as a preset)';
  $('btn-pupdate').disabled = !(preset && !preset.builtin && modified);
  $('btn-prevert').disabled = !(preset && modified);
  if (!$('tab-presets').hidden) renderPresetCards();
}

function updateChrome() {
  updatePresetChrome();
  const connected = !!state.client;
  const cc = $('chip-conn'); cc.textContent = connected ? `Connected${state.mock ? ' (demo device)' : ''}` : 'Not connected'; cc.className = 'chip ' + (connected ? 'ok' : '');
  const [text, cls] = syncState(); $('chip-sync').textContent = text; $('chip-sync').className = 'chip ' + cls;
  const bad = M.check(state.cfg) !== null;
  const same = state.deviceCfg && M.equal(state.cfg, state.deviceCfg);
  $('btn-connect').hidden = connected;
  $('btn-read').disabled = !connected; $('btn-send').disabled = !connected || bad || !!same;
  $('btn-save').disabled = !connected || bad || (!!same && !state.info?.unsaved_changes);
  $('btn-defaults').disabled = !connected; $('btn-erase').disabled = !connected;
  const kv = $('devinfo'); kv.replaceChildren();
  const rows = connected && state.info ? [['Device', state.name], ...(state.info.version != null ? [['Firmware', `${D.FW_NAME} v${state.info.version}`]] : []), ['Protocol', String(state.info.protocol)], ['Saved settings', state.info.saved ? 'yes' : 'no'], ['Unsaved changes', state.info.unsaved_changes ? 'yes' : 'no'], ['Loaded from saved at power-up', state.info.loaded_from_flash ? 'yes' : 'no']] : [['Device', 'not connected']];
  for (const [k, v] of rows) kv.append(el('dt', { text: k }), el('dd', { text: v }));
  renderSlots();
}

// ---- device operations ----
async function refreshInfo() { state.info = await state.client.info(); }

/** The four preset slots in the device's flash: which hold a configuration, and the buttons to store the current one / make one the active one. */
async function refreshSlots() {
  try { state.slots = state.client ? await state.client.slots() : null; } catch { state.slots = null; }
  renderSlots();
}
function renderSlots() {
  const host = $('slots'); if (!host) return;
  host.replaceChildren();
  for (let i = 0; i < 4; i++) {
    const used = state.slots ? state.slots[i] : null, conn = !!state.client && state.slots !== null;
    const store = el('button', { type: 'button', text: 'Store current', disabled: !conn || undefined, onclick: () => slotAction(i, true) });
    const load = el('button', { type: 'button', text: 'Make active', disabled: !conn || !used || undefined, onclick: () => slotAction(i, false) });
    host.append(el('div', { class: 'row' }, el('strong', { text: `Slot ${i + 1}`, style: 'min-width:60px' }), el('span', { class: 'tag' + (used ? ' dev' : ''), text: state.slots ? (used ? 'holds a configuration' : 'empty') : 'not connected' }), el('span', { class: 'grow' }), store, load));
  }
}
async function slotAction(i, store) {
  try {
    const r = store ? await state.client.slotStore(i) : await state.client.slotLoad(i);
    if (r.status !== 0) { say(`Slot ${i + 1}: ${r.status_text}.`, true); return; }
    if (store) say(`Stored the active configuration in slot ${i + 1} on the device.`);
    else { await readFromDevice(); say(`Slot ${i + 1} is the active configuration now (not saved as the power-up one: Save on device keeps it).`); }
    await refreshSlots();
  } catch (e) { say(e.message, true); }
}

async function afterConnect() {
  await refreshInfo();
  await refreshSlots();
  const dev = await state.client.get();
  state.deviceCfg = Uint8Array.from(dev);
  if (!state.touched) { state.cfg = Uint8Array.from(dev); state.presetId = null; }               // edits made before connecting are kept (they show as "not sent")
  refreshAll();
}

async function readFromDevice() {
  const cfg = await state.client.get();
  state.deviceCfg = Uint8Array.from(cfg); state.cfg = Uint8Array.from(cfg); state.touched = false; state.presetId = null;
  await refreshInfo(); refreshAll(); say('Read the configuration from the device.');
}

async function sendToDevice(quiet = false) {
  const bad = M.check(state.cfg);
  if (bad !== null) { say(`This configuration cannot be sent: ${fieldAt(bad)} is out of range.`, true); return false; }
  const r = await state.client.set(state.cfg);
  if (r.status !== 0) { say(`The device refused the configuration: ${r.status_text}${r.offset != null ? ` (${fieldAt(r.offset)})` : ''}.`, true); return false; }
  state.deviceCfg = Uint8Array.from(state.cfg);
  await refreshInfo(); refreshAll();
  if (!quiet) say('Sent. The device uses the new mapping now (not saved yet).');
  return true;
}

async function saveOnDevice() {
  if (!state.deviceCfg || !M.equal(state.cfg, state.deviceCfg)) { if (!(await sendToDevice(true))) return; }
  const r = await state.client.save();
  await refreshInfo(); refreshAll();
  if (r.status === 0) say('Saved on the device. It keeps this mapping when it is unplugged.'); else say(`Saving failed: ${r.status_text}.`, true);
}

async function resetDevice(erase) {
  const r = await state.client.reset(erase);
  if (r.status !== 0) { say(`Reset failed: ${r.status_text}.`, true); return; }
  await readFromDevice(); say(erase ? 'The saved settings are erased; the defaults are active.' : 'The defaults are active (not saved).');
}

function attach(name, transport) {
  state.client = new M.Mk3(transport); state.name = name; state.slots = null;
  afterConnect().then(() => say(`Connected to ${name}.`)).catch((e) => { say(`Connected to ${name}, but it does not answer as a patched Mikro MK3 (${e.message}). Is the patched firmware flashed?`, true); state.client = null; updateChrome(); });
}

async function connect() {
  try {
    if (new URLSearchParams(location.search).has('mock')) {
      state.mock = makeMock(); attach('demo device', state.mock.transport); return;
    }
    if (!navigator.requestMIDIAccess) throw new Error('This browser has no Web MIDI. Use Chrome or Edge.');
    state.midi = await navigator.requestMIDIAccess({ sysex: true });
    state.midi.onstatechange = pickPorts;
    pickPorts();
    if (!state.client) say('No Maschine Mikro MK3 found among the MIDI ports. Plug it in (it must run the patched firmware) and close other programs that use it.', true);
  } catch (e) { say(`Could not use MIDI: ${e.message}`, true); }
}

function pickPorts() {
  const find = (map) => [...map.values()].find((p) => /maschine mikro mk3/i.test(p.name) && p.state === 'connected');
  const inp = find(state.midi.inputs), out = find(state.midi.outputs);
  if (inp && out && (!state.client || state.port !== inp.id)) {
    state.port = inp.id;
    let listener = () => {};
    inp.onmidimessage = (e) => { if (e.data[0] === 0xf0) listener(e.data); };
    attach(inp.name, { send: (msg) => out.send(msg), listen: (cb) => { listener = cb; } });
  } else if (!inp || !out) {
    if (state.client) { state.client = null; state.port = null; say('The Maschine was unplugged.'); refreshAll(); }
  }
}

// ---- presets ----
function applyTransport(name) {                     // Play, Rec and Stop only; everything else stays as it is
  const src = M.defaultCfg(name);
  for (const id of [D.BTN_PLAY, D.BTN_REC, D.BTN_STOP]) { state.cfg[FD.btn_act[0] + id] = src[FD.btn_act[0] + id]; state.cfg[FD.btn_cc[0] + id] = src[FD.btn_cc[0] + id]; }
  edited();
}

/** Asks for a name and a description in the page's own dialog; resolves to { name, description } or null if cancelled. */
function askDetails({ title, name = '', description = '', ok = 'Save' }) {
  const dlg = $('dlg');
  $('dlg-title').textContent = title; $('dlg-name').value = name; $('dlg-desc').value = description; $('dlg-ok').textContent = ok;
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok' ? { name: $('dlg-name').value.trim(), description: $('dlg-desc').value.trim() } : null), { once: true });
    dlg.returnValue = 'cancel';
    dlg.showModal(); $('dlg-name').focus(); $('dlg-name').select();
  });
}

/** Puts a preset into the editor and, with the device connected, sends it (not saved on the device). */
async function usePreset(id) {
  const p = store.get(id);
  if (!p) return;
  state.cfg = Uint8Array.from(p.cfg); state.presetId = p.id; state.touched = true;
  refreshAll();
  if (!state.client) { say(`Preset "${p.name}" is in the editor. Connect to send it to the device.`); return; }
  if (await sendToDevice(true)) say(`Preset "${p.name}" is on the device now (not saved there yet: Save on device keeps it).`);
}

async function savePresetAs() {
  const cur = currentPreset().preset;
  const r = await askDetails({ title: 'Save as preset', name: cur ? `${cur.name} (mine)` : 'My preset', description: cur && !cur.builtin ? cur.description : '' });
  if (!r || !r.name) return;
  const p = store.add({ name: r.name, description: r.description, cfg: state.cfg });
  state.presetId = p.id; refreshAll(); say(`Saved the preset "${p.name}"${store.persistent ? '' : ' (this browser cannot keep it after the page is closed: export it)'}.`);
}

function updatePreset() {
  const { preset, modified } = currentPreset();
  if (!preset || preset.builtin || !modified) return;
  store.update(preset.id, { cfg: state.cfg }); refreshAll(); say(`The preset "${preset.name}" now holds the current configuration.`);
}

function revertPreset() {
  const { preset } = currentPreset();
  if (preset) { state.cfg = Uint8Array.from(preset.cfg); state.touched = true; refreshAll(); say(`Back to the preset "${preset.name}" (in the editor; the device is unchanged until you send).`); }
}

function downloadText(name, text) {
  const a = el('a', { href: URL.createObjectURL(new Blob([text], { type: 'application/json' })), download: name }); a.click(); URL.revokeObjectURL(a.href);
}

async function presetAction(act, id) {
  const p = store.get(id);
  try {
    if (act === 'use') await usePreset(id);
    else if (act === 'dup') { const c = store.duplicate(id); refreshAll(); say(`Made "${c.name}", a copy you can change.`); }
    else if (act === 'edit') {
      const r = await askDetails({ title: 'Rename preset', name: p.name, description: p.description, ok: 'Save' });
      if (r && r.name) { store.update(id, { name: r.name, description: r.description }); refreshAll(); }
    } else if (act === 'export') downloadText(`mikro-mk3-preset-${p.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'preset'}.json`, store.exportJSON([id]));
    else if (act === 'del') {
      if (!confirm(`Delete the preset "${p.name}"? This cannot be undone.`)) return;
      store.remove(id); if (state.presetId === id) state.presetId = null; refreshAll(); say(`Deleted the preset "${p.name}".`);
    }
  } catch (e) { say(e.message, true); }
}

function renderPresetCards() {
  const host = $('preset-cards'), { preset: cur, modified } = currentPreset();
  host.replaceChildren();
  for (const p of store.list()) {
    const onDevice = !!state.client && !!state.deviceCfg && M.equal(state.deviceCfg, p.cfg);
    const facts = el('ul', { class: 'facts' }, ...PR.describeCfg(p.cfg).map((f) => el('li', {}, el('b', { text: f.label }), el('span', { text: f.text }))));
    const diff = PR.diffCfg(state.cfg, p.cfg);
    const details = diff.length ? el('details', {}, el('summary', { text: `${diff.length} ${diff.length === 1 ? 'setting differs' : 'settings differ'} from the editor` }), el('ul', {}, ...diff.map((l) => el('li', { text: l })))) : null;
    const isCur = cur && cur.id === p.id;
    const head = el('div', { class: 'phead' }, el('h3', { text: p.name }), el('span', { class: 'tag', text: p.builtin ? 'built-in' : 'mine' }));
    if (isCur) head.append(el('span', { class: 'tag on', text: modified ? 'in editor, changed' : 'in editor' }));
    if (onDevice) head.append(el('span', { class: 'tag dev', text: 'on device' }));
    const btn = (act, text, cls = '', title = '') => el('button', { type: 'button', class: cls, title, onclick: () => presetAction(act, p.id) , text });
    const btns = el('div', { class: 'btns' }, btn('use', 'Use', 'primary', 'Load it into the editor and send it to the device if connected'), btn('dup', 'Duplicate'));
    if (!p.builtin) btns.append(btn('edit', 'Rename…'), btn('export', 'Export'), btn('del', 'Delete', 'danger'));
    else btns.append(btn('export', 'Export'));
    host.append(el('article', { class: 'pcard' + (isCur ? ' current' : '') }, head, el('p', { class: 'desc', text: p.description || 'No description.' }), facts, ...(details ? [details] : []), btns));
  }
}

async function importPresets(files) {
  let added = 0, skipped = 0;
  for (const f of files) {
    try { const r = store.importJSON(await f.text()); added += r.added.length; skipped += r.skipped; }
    catch (e) { say(`Could not import ${f.name}: ${e.message}`, true); return; }
  }
  refreshAll(); say(`Imported ${added} preset${added === 1 ? '' : 's'}${skipped ? `, ${skipped} already here` : ''}.`);
}

// ---- firmware ----
const fw = { bundle: null, stock: null, image: null, usb: null, mode: 'midi' };
const setStep = (id, { done = false, off = false } = {}) => { const li = $(id); li.classList.toggle('done', done); li.classList.toggle('off', off); };

async function chooseFirmware(file) {
  $('fw-result').textContent = 'Looking for the firmware…'; fw.image = null; fw.stock = null; $('btn-keep').hidden = true; $('keep-result').textContent = '';
  setStep('st-file'); setStep('st-image', { off: true }); setStep('st-usb', { off: true }); setStep('st-flash', { off: true });
  $('btn-usb').disabled = true; $('btn-flash').disabled = true;
  try {
    fw.bundle ||= await (await fetch('patch_bundle.json')).json();
    const bytes = new Uint8Array(await file.arrayBuffer());
    fw.stock = await P.findStockImage(bytes, fw.bundle);
    if (!fw.stock) { $('fw-result').textContent = `Not found: this file does not contain NI's firmware 1.20 for the Mikro MK3 (the patch is made for exactly that version, SHA-256 ${fw.bundle.stock_sha256.slice(0, 16)}…).`; return; }
    $('fw-result').textContent = `Found NI's firmware 1.20 (${fw.stock.length} bytes, SHA-256 ${fw.bundle.stock_sha256.slice(0, 16)}…).`;
    $('btn-keep').hidden = false;
    await prepareImage();
  } catch (e) { $('fw-result').textContent = `Problem: ${e.message}`; }
}

/** The image for the chosen mode: the patched one, or NI's original as it is. */
async function prepareImage() {
  fw.image = null; setStep('st-image', { off: true }); setStep('st-usb', { off: true }); setStep('st-flash', { off: true }); $('btn-usb').disabled = true; $('btn-flash').disabled = true;
  if (!fw.stock) return;
  try {
    fw.image = fw.mode === 'stock' ? fw.stock : await P.buildImage(fw.stock, fw.bundle);
    const problems = F.validateImage(fw.image);
    if (problems.length) throw new Error(problems.join('; '));
    const sha = fw.mode === 'stock' ? fw.bundle.stock_sha256 : fw.bundle.result_sha256;
    $('img-result').textContent = fw.mode === 'stock'
      ? `NI's original firmware: ${fw.image.length} bytes, SHA-256 ${sha.slice(0, 16)}… (checked). The device will be the plain NI device again (no MIDI), as before the patch.`
      : `Patched image: ${fw.image.length} bytes, SHA-256 ${sha.slice(0, 16)}… (checked), flash 0x${F.APP_BASE.toString(16)}–0x${(F.APP_BASE + fw.image.length - 1).toString(16)}. The original firmware can be restored from this page.`;
    $('ack-text').textContent = fw.mode === 'stock'
      ? 'I know the device will stop being a MIDI device until the MIDI firmware is flashed again, and I will not unplug it while this runs.'
      : 'I have a copy of NI\'s original firmware saved (step 1) so that I can restore it, and I will not unplug the device while this runs.';
    setStep('st-file', { done: true }); setStep('st-image', { done: true }); setStep('st-usb');
    $('btn-usb').disabled = !navigator.usb;
    if (!navigator.usb) $('usb-result').textContent = 'This browser has no WebUSB. Use Chrome or Edge.';
  } catch (e) { $('img-result').textContent = `Problem: ${e.message}`; }
}

function keepCopy() {
  const a = el('a', { href: URL.createObjectURL(new Blob([fw.stock], { type: 'application/octet-stream' })), download: 'MM3_firmware_1.20_stock.bin' });
  a.click(); URL.revokeObjectURL(a.href);
  $('keep-result').textContent = `Saved as MM3_firmware_1.20_stock.bin (${fw.stock.length} bytes). Keep it somewhere safe: it restores the original firmware, here or with tools/restore_stock.sh. Its SHA-256 must be ${fw.bundle.stock_sha256}.`;
}

async function openDfu(dev) {
  await dev.open();
  if (dev.configuration === null) await dev.selectConfiguration(1);
  const di = F.findDfuInterface(await F.readConfigDescriptor(dev));
  if (!di) throw new Error('this device has no DFU interface');
  await dev.claimInterface(di.number);
  return { dev, di };
}

async function selectUsb(productId) {
  const filters = [{ vendorId: F.VID, ...(productId ? { productId } : {}) }];
  return openDfu(await navigator.usb.requestDevice({ filters }));
}

async function onUsbSelected() {
  try {
    fw.usb = await selectUsb();
    const { dev, di } = fw.usb;
    $('usb-result').textContent = `${dev.productName || 'device'} (${di.runtime ? 'normal mode' : 'bootloader'}, DFU interface ${di.number}).`;
    setStep('st-usb', { done: true }); setStep('st-flash');
    $('btn-flash').disabled = !$('ack').checked;
  } catch (e) { $('usb-result').textContent = `Problem: ${e.message}`; }
}

async function download(dev, di) {
  const prog = $('prog'); prog.hidden = false; prog.value = 0;
  const t = F.webUsbTransport(dev, di.number);
  $('flash-result').textContent = 'Writing the firmware…';
  const result = await F.download(t, fw.image, { block: di.functional?.transferSize || 64, progress: (d, n) => { prog.value = (d / n) * 100; } });
  try { await dev.close(); } catch { /* the device is already gone */ }
  $('flash-result').textContent = result === 'reset' ? 'Written. The device restarted by itself. Waiting for it to come back…' : 'Written. Waiting for the device to restart…';
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    const back = (await navigator.usb.getDevices()).find((d) => d.vendorId === F.VID && d.productId === F.PID_RUNTIME);
    if (back) {
      const bcd = (back.deviceVersionMajor << 8) | (back.deviceVersionMinor << 4) | back.deviceVersionSubminor;
      const ver = `17cc:1700, version 0x${bcd.toString(16).padStart(4, '0')}`;
      $('flash-result').textContent = fw.mode === 'stock' ? `Done. The device is back (${ver}) and runs NI's original firmware again.` : `Done. The device is back (${ver}). It is a MIDI device now: press Connect to talk to it.`;
      say(fw.mode === 'stock' ? 'NI\'s original firmware restored.' : 'Firmware flashed.'); return;
    }
  }
  $('flash-result').textContent = 'The page cannot see the device again (the browser only shows devices you selected before the restart). Unplug and replug it: if it shows up as a MIDI device (press Connect) or as the plain NI device, the flash worked. If it stays silent, wait three minutes and replug once more; then restore the original firmware (tools/restore_stock.sh, or this page with the saved copy).';
  say('The device did not reappear in the page after flashing; replug it to check.', true);
}

async function flashNow() {
  $('btn-flash').disabled = true;
  try {
    const { dev, di } = fw.usb;
    if (di.runtime) {
      $('flash-result').textContent = 'Switching the device to its bootloader…';
      try { await F.webUsbTransport(dev, di.number).ctrlOut(F.REQ.DETACH, di.functional?.detachTimeout ?? 255); } catch { /* it resets itself */ }
      try { await dev.close(); } catch { /* gone */ }
      $('flash-result').textContent = 'The device is in its bootloader now. Click "Select the bootloader…" and choose it (the browser needs one more click).';
      $('btn-usb2').hidden = false; return;
    }
    await download(dev, di);
  } catch (e) { $('flash-result').textContent = `Problem: ${e.message}. Nothing is lost: unplug and replug the device, or restore the original firmware with NI's updater.`; say(`Flashing stopped: ${e.message}`, true); }
}

async function onBootloaderSelected() {
  try {
    $('btn-usb2').hidden = true;
    fw.usb = await selectUsb(F.PID_DFU);
    if (fw.usb.di.runtime) throw new Error('that is not the bootloader');
    await download(fw.usb.dev, fw.usb.di);
  } catch (e) { $('flash-result').textContent = `Problem: ${e.message}`; $('btn-usb2').hidden = false; say(`Flashing stopped: ${e.message}`, true); }
}

// ---- start ----
function init() {
  buildButtons(); buildPads(); buildOthers();
  $('tabs').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-tab]'); if (!b) return;
    document.querySelectorAll('#tabs button').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    document.querySelectorAll('main > section').forEach((s) => { s.hidden = s.id !== `tab-${b.dataset.tab}`; });
    if (b.dataset.tab === 'presets') renderPresetCards();
  });
  document.querySelectorAll('[data-transport]').forEach((b) => b.addEventListener('click', () => applyTransport(b.dataset.transport)));
  const guarded = (fn) => () => fn().catch((e) => say(e.message, true));
  $('btn-connect').addEventListener('click', connect);
  $('btn-read').addEventListener('click', guarded(readFromDevice));
  $('btn-send').addEventListener('click', guarded(sendToDevice));
  $('btn-save').addEventListener('click', guarded(saveOnDevice));
  $('btn-defaults').addEventListener('click', guarded(() => resetDevice(false)));
  $('btn-erase').addEventListener('click', guarded(() => resetDevice(true)));
  $('live').addEventListener('change', (e) => { state.live = e.target.checked; });
  $('preset-select').addEventListener('change', (e) => e.target.value && usePreset(e.target.value));
  $('btn-psave').addEventListener('click', () => savePresetAs());
  $('btn-pupdate').addEventListener('click', updatePreset);
  $('btn-prevert').addEventListener('click', revertPreset);
  $('btn-pexport').addEventListener('click', () => (store.user.length ? downloadText('mikro-mk3-presets.json', store.exportJSON()) : say('You have no presets of your own to export yet.', true)));
  $('file-pimport').addEventListener('change', (e) => { importPresets([...e.target.files]); e.target.value = ''; });
  if (!store.persistent) $('store-note').append(' This browser does not let the page keep presets between visits; export them to keep them.');
  $('file-fw').addEventListener('change', (e) => e.target.files[0] && chooseFirmware(e.target.files[0]));
  $('btn-usb').addEventListener('click', onUsbSelected);
  $('btn-keep').addEventListener('click', keepCopy);
  document.querySelectorAll('input[name=fwmode]').forEach((r) => r.addEventListener('change', () => { fw.mode = r.value; if (r.checked) prepareImage(); }));
  $('ack').addEventListener('change', () => { $('btn-flash').disabled = !(fw.usb && fw.image && $('ack').checked); });
  $('btn-flash').addEventListener('click', flashNow);
  $('btn-usb2').addEventListener('click', onBootloaderSelected);
  refreshAll(); renderPresetCards();
  // with the permission already given, connect at once
  if (navigator.permissions && navigator.requestMIDIAccess && !new URLSearchParams(location.search).has('mock')) {
    navigator.permissions.query({ name: 'midi', sysex: true }).then((s) => { if (s.state === 'granted') connect(); }).catch(() => {});
  }
  if (new URLSearchParams(location.search).has('mock')) { say('Demo mode: a stand-in device that behaves like the real one. Press Connect.'); }
  window.mk3 = { state, M, refreshAll, store, usePreset };                     // for the console and the tests
}
init();
