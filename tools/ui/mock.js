// A stand-in for the device's SysEx side, for developing and testing the page without hardware (open index.html?mock). It follows the
// protocol of docs/remap-protocol.md: INFO / GET / SET (range-checked with the same check() as the page) / SAVE / RESET, one request at a
// time, replies a few milliseconds later. It is not the firmware (the firmware is tested in the emulator); it only has to behave like it.
import * as M from './mmk3.js';

export function makeMock({ delay = 15 } = {}) {
  const defaults = M.defaultCfg();
  const dev = { cfg: Uint8Array.from(defaults), saved: null, loadedFromFlash: false, slots: [null, null, null, null], names: ['', '', '', ''] };
  let listener = () => {};
  const reply = (cmd, ...data) => setTimeout(() => listener(Uint8Array.from([0xf0, ...M.MANUFACTURER, cmd + M.REPLY, ...data, 0xf7])), delay);
  const unsaved = () => (dev.saved ? !M.equal(dev.cfg, dev.saved) : !M.equal(dev.cfg, defaults));
  const transport = {
    listen: (cb) => { listener = cb; },
    send(msg) {
      if (msg[1] !== 0x7d || msg[2] !== 0x4d || msg[3] !== 0x4b) return;
      const cmd = msg[4], payload = msg.slice(5, -1);
      if (cmd === M.CMD.INFO) reply(cmd, M.D.PROTO_VERSION, M.CFG_SIZE & 0x7f, M.CFG_SIZE >> 7, (dev.saved ? 1 : 0) | (unsaved() ? 2 : 0) | (dev.loadedFromFlash ? 4 : 0), M.D.FW_VERSION);
      else if (cmd === M.CMD.GET) reply(cmd, ...M.pack7(dev.cfg));
      else if (cmd === M.CMD.SLOTS) reply(cmd, 0, dev.slots.reduce((m, s, i) => m | (s ? 1 << i : 0), 0), ...dev.names.flatMap((nm) => Array.from({ length: M.NAME_MAX }, (_, k) => nm.charCodeAt(k) || 0)));
      else if (cmd === M.CMD.SLOT_STORE || cmd === M.CMD.SLOT_LOAD) {
        const n = payload[0];
        if (n > 3) reply(cmd, 2);
        else if (cmd === M.CMD.SLOT_STORE) { dev.slots[n] = Uint8Array.from(dev.cfg); dev.names[n] = String.fromCharCode(...payload.slice(1, 1 + M.NAME_MAX)); reply(cmd, 0); }
        else if (!dev.slots[n]) reply(cmd, 4);
        else { dev.cfg = Uint8Array.from(dev.slots[n]); reply(cmd, 0); }
      }
      else if (cmd === M.CMD.SET) {
        const cfg = M.unpack7(payload);
        if (cfg.length !== M.CFG_SIZE) reply(cmd, 1);
        else { const bad = M.check(cfg); if (bad === null) { dev.cfg = cfg; reply(cmd, 0); } else reply(cmd, 2, bad & 0x7f, bad >> 7); }
      } else if (cmd === M.CMD.SAVE) { dev.saved = M.equal(dev.cfg, defaults) ? null : Uint8Array.from(dev.cfg); reply(cmd, 0); }
      else if (cmd === M.CMD.RESET) { dev.cfg = Uint8Array.from(defaults); if (payload[0] === 1) dev.saved = null; reply(cmd, 0); }
    },
  };
  /** Power cycle: the saved config (if any) becomes the active one. */
  const reboot = () => { dev.cfg = dev.saved ? Uint8Array.from(dev.saved) : Uint8Array.from(defaults); dev.loadedFromFlash = !!dev.saved; };
  return { transport, dev, reboot };
}
