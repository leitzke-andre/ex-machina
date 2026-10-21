#!/usr/bin/env python3
"""Writes patch_bundle.json: what the browser needs to turn the user's OWN copy of NI's stock firmware into the patched image, without
any NI code in the repository. The bundle holds the SHA-256 of the stock image it applies to (the page refuses anything else), the
replacement bytes at the hook sites inside the stock image (our instructions), the bytes appended behind it (config, descriptors,
velocity tables, display font and texts, our code), the regions of the appended part that are COPIED from the stock image in the browser
(the LED colour tables our LED driver uses: NI's data, so they are not in the bundle), and the SHA-256 of the result, which the page checks
again before it flashes anything. make() refuses a tail that still contains a run of NI's bytes.

    make_bundle.py <stock.bin> <patched.bin> [out.json]      write the bundle (default tools/ui/patch_bundle.json)
    make_bundle.py --check <stock.bin> <patched.bin>         fail if the committed bundle does not describe these two images"""
import hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'midi_patch'))
import build_patch as bp
STOCK_LEN = 0x9DC8                       # NI's firmware image, 40,392 bytes (build_patch.STOCK_LEN)
STOCK_SHA256 = '76ebf72d33961639a0bd042ba32354dd8dc07569be69175546eb9fc06e5c5917'   # NI's firmware 1.20 for the Mikro MK3 (tools/restore_stock.sh checks the same)

def make(stock, patched):
    assert len(stock) == STOCK_LEN and hashlib.sha256(stock).hexdigest() == STOCK_SHA256, "not NI's firmware 1.20 (the bundle is made for exactly that image)"
    assert patched[:2] and len(patched) > len(stock)
    edits, i = [], 0                                    # runs of bytes that differ; no unchanged (NI) byte is copied into the bundle
    while i < len(stock):
        if stock[i] != patched[i]:
            j = i
            while j < len(stock) and stock[j] != patched[j]: j += 1
            edits.append({'offset': i, 'hex': patched[i:j].hex()}); i = j
        else: i += 1
    tail = bytearray(patched[len(stock):])
    copies = []
    for dst, src, n in ((bp.LEDTAB_ADDR, bp.LEDTAB_SRC, bp.LEDTAB_LEN),):
        d, s_ = dst - 0x08003000, src - 0x08003000
        if d + n <= len(patched) and patched[d:d + n] == stock[s_:s_ + n]:
            copies.append({'offset': d, 'stock_offset': s_, 'length': n}); tail[d - len(stock):d - len(stock) + n] = bytes(n)
    # No run of 32 of NI's bytes may be left in the part the bundle carries. One region is exempt: the button wiring (build_patch.hw_blob:
    # which key sits at which matrix position, written down in build_patch.py and docs/hardware-map.md), a fact about the board that is
    # necessarily the same numbers as NI's table.
    hw0, hw1 = bp.HW_ADDR - 0x08003000 - len(stock), bp.LEDTAB_ADDR - 0x08003000 - len(stock)
    for k in range(0, len(tail) - 32, 16):
        if k + 32 > hw0 and k < hw1: continue
        w = bytes(tail[k:k + 32])
        if w.count(0) < 24 and w.count(0xFF) < 24 and w in stock: raise SystemExit(f'the tail holds NI bytes at image offset {len(stock) + k:#x}')
    return {
        'format': 1,
        'description': 'Maschine Mikro MK3 USB-MIDI patch (hooks, config, descriptors, velocity tables, display font and texts, code); apply to the NI firmware v1.20 image',
        'stock_len': len(stock), 'stock_sha256': hashlib.sha256(stock).hexdigest(),
        'base_address': 0x08003000,
        'edits': edits,
        'tail_offset': len(stock), 'tail_hex': bytes(tail).hex(), 'copies': copies,
        'result_len': len(patched), 'result_sha256': hashlib.sha256(patched).hexdigest(),
    }

def apply(stock, bundle):
    img = bytearray(stock)
    for e in bundle['edits']: img[e['offset']:e['offset'] + len(e['hex']) // 2] = bytes.fromhex(e['hex'])
    img += bytes.fromhex(bundle['tail_hex'])
    for c in bundle.get('copies', []): img[c['offset']:c['offset'] + c['length']] = stock[c['stock_offset']:c['stock_offset'] + c['length']]
    return bytes(img)

if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if x != '--check']
    stock, patched = open(a[0], 'rb').read(), open(a[1], 'rb').read()      # (the whole file: a longer one is not NI's image)
    b = make(stock, patched)
    assert apply(stock, b) == patched, 'the bundle does not rebuild the image'
    path = a[2] if len(a) > 2 else os.path.join(HERE, 'patch_bundle.json')
    text = json.dumps(b, indent=1) + '\n'
    if '--check' in sys.argv:
        ok = os.path.exists(path) and open(path).read() == text
        print('patch_bundle.json describes these images' if ok else 'patch_bundle.json is out of date: run tools/ui/make_bundle.py <stock.bin> <patched.bin>'); sys.exit(0 if ok else 1)
    open(path, 'w').write(text)
    print(f'written {path}: {len(b["edits"])} edit regions ({sum(len(e["hex"]) // 2 for e in b["edits"])} bytes), tail {len(b["tail_hex"]) // 2} bytes, result {b["result_len"]} bytes, sha256 {b["result_sha256"][:16]}...')
