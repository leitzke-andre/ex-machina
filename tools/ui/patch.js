// Builds the patched firmware image in the browser from the user's OWN copy of NI's stock firmware and the patch bundle
// (patch_bundle.json: our replacement bytes and hashes only). Nothing leaves the machine; nothing of NI's is in the repository.
import { hex } from './mmk3.js';

export const STOCK_SIGNATURE = Uint8Array.from([0x18, 0x1c, 0x00, 0x20, 0xc1, 0x31, 0x00, 0x08]);   // initial SP 0x20001c18, reset vector 0x080031c1

export async function sha256Hex(bytes) {
  return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)));
}

/** The stock image inside a file the user chose: the 40,392-byte image itself, or any container that holds it (NI's firmware updater for
 *  Mac or Windows). Candidates are found by the start of the vector table and accepted only if the SHA-256 matches the bundle's. */
export async function findStockImage(file, bundle) {
  const n = bundle.stock_len;
  if (file.length === n && (await sha256Hex(file)) === bundle.stock_sha256) return file;
  for (let i = 0; i + n <= file.length; i++) {
    if (file[i] !== STOCK_SIGNATURE[0]) continue;
    let k = 1;
    while (k < STOCK_SIGNATURE.length && file[i + k] === STOCK_SIGNATURE[k]) k++;
    if (k < STOCK_SIGNATURE.length) continue;
    const cand = file.slice(i, i + n);
    if ((await sha256Hex(cand)) === bundle.stock_sha256) return cand;
  }
  return null;
}

/** stock + bundle -> the patched image; both hashes are checked, the stock one before and the result one after. */
export async function buildImage(stock, bundle) {
  if (stock.length !== bundle.stock_len || (await sha256Hex(stock)) !== bundle.stock_sha256) throw new Error('this is not the firmware image the patch was made for');
  const tail = Uint8Array.from(bundle.tail_hex.match(/../g) || [], (h) => parseInt(h, 16));
  const img = new Uint8Array(bundle.tail_offset + tail.length);
  img.set(stock);
  for (const e of bundle.edits) img.set(Uint8Array.from(e.hex.match(/../g), (h) => parseInt(h, 16)), e.offset);
  img.set(tail, bundle.tail_offset);
  for (const c of bundle.copies || []) img.set(stock.slice(c.stock_offset, c.stock_offset + c.length), c.offset);   // NI's own tables, from the user's image
  if (img.length !== bundle.result_len || (await sha256Hex(img)) !== bundle.result_sha256) throw new Error('the patched image does not match its checksum; not using it');
  return img;
}
