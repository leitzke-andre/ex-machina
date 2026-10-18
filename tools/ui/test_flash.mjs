// Tests of patch.js (building the patched image from the user's own stock firmware) and of the flasher on our real images, with node:
//   node tools/ui/test_flash.mjs <stock.bin> <patched.bin> [<NI updater binary>]
// The flasher's own tests (a mock DFU device, no images) are flasher/test_dfu.mjs.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import * as P from './patch.js';
import * as F from '../../flasher/dfu.js';
import { hex } from './mmk3.js';

const here = dirname(fileURLToPath(import.meta.url));
let ok = true;
const check = (name, cond, detail = '') => { ok &&= !!cond; console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '  ' + detail)); };
const [stockPath, patchedPath, updaterPath] = process.argv.slice(2);
const bundle = JSON.parse(readFileSync(join(here, 'patch_bundle.json'), 'utf8'));
const stock = new Uint8Array(readFileSync(stockPath)).slice(0, bundle.stock_len);
const patched = new Uint8Array(readFileSync(patchedPath));

// ---- building the image ----
const built = await P.buildImage(stock, bundle);
check('buildImage(stock) reproduces the patched image byte for byte (the one build_patch.py makes)', hex(built) === hex(patched) && built.length === bundle.result_len, built.length);
check('the bundle holds no stock bytes: its edits are exactly the bytes that differ', bundle.edits.reduce((n, e) => n + e.hex.length / 2, 0) === stock.reduce((n, b, i) => n + (b !== patched[i] ? 1 : 0), 0));
const flipped = stock.slice(); flipped[1234] ^= 1;
let err = ''; try { await P.buildImage(flipped, bundle); } catch (e) { err = e.message; }
check('a stock image with one flipped bit is refused', /not the firmware image/.test(err), err);
err = ''; try { await P.buildImage(stock.slice(0, 1000), bundle); } catch (e) { err = e.message; }
check('a truncated image is refused', /not the firmware image/.test(err), err);
const tampered = JSON.parse(JSON.stringify(bundle)); tampered.tail_hex = tampered.tail_hex.slice(0, 100) + '00' + tampered.tail_hex.slice(102);
err = ''; try { await P.buildImage(stock, tampered); } catch (e) { err = e.message; }
check('a bundle that was tampered with is caught by the checksum of the result', /does not match its checksum/.test(err), err);

// ---- finding the stock image in a file the user chose ----
check('findStockImage: the bare 40,392-byte image', hex(await P.findStockImage(stock, bundle)) === hex(stock));
const filler = (n, seed) => Uint8Array.from({ length: n }, (_, i) => (i * 31 + seed) & 255);
const decoy = new Uint8Array(40392).fill(7); decoy.set(P.STOCK_SIGNATURE);                 // starts like the firmware but is not it
const container = new Uint8Array([...filler(5000, 1), ...decoy.slice(0, 20000), ...filler(777, 2), ...stock, ...filler(3000, 3)]);
const found = await P.findStockImage(container, bundle);
check('findStockImage: inside a larger file, after a decoy with the same first 8 bytes', found && hex(found) === hex(stock));
check('findStockImage: nothing found in an unrelated file', (await P.findStockImage(filler(100000, 9), bundle)) === null);
if (updaterPath) {
  const updater = new Uint8Array(readFileSync(updaterPath));
  const f = await P.findStockImage(updater, bundle);
  check(`findStockImage: in NI's updater (${updater.length} bytes)`, f && hex(f) === hex(stock));
}


// ---- the flasher on the real images ----
check('validateImage accepts the patched image and the stock image', F.validateImage(patched).length === 0 && F.validateImage(stock).length === 0, F.validateImage(patched));
const cfgAt = (img, addr, n) => img.slice(addr - 0x08003000, addr - 0x08003000 + n);
const patchedCfg = cfgAt(patched, 0x0800cf40, 119);
const di = F.findDfuInterface(patchedCfg);
check('findDfuInterface on the patched device\'s real configuration descriptor: interface 2, runtime, transfer size 64', di && di.number === 2 && di.runtime && di.functional.transferSize === 64 && di.functional.attributes === 9, JSON.stringify(di));
const stockCfg = cfgAt(stock, 0x08008d66, 59);
const ds = F.findDfuInterface(stockCfg);
check('... and on the stock device\'s (HID 0, DFU 1)', ds && ds.number === 1 && ds.runtime && ds.functional.transferSize === 64, JSON.stringify(ds));
console.log(ok ? 'ALL PASS' : 'SOME FAILED');
process.exit(ok ? 0 : 1);
