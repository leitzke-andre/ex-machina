#!/usr/bin/env python3
"""Writes patch_bundle.json: what the browser needs to turn the user's OWN copy of NI's stock firmware into the patched image, without
any NI code in the repository. The bundle holds the SHA-256 of the stock image it applies to (the page refuses anything else), the
replacement bytes at the hook sites inside the stock image (our instructions), the bytes appended behind it (config, descriptors,
velocity tables, display font and texts, our code) and the SHA-256 of the result, which the page checks again before it flashes anything.

    make_bundle.py <stock.bin> <patched.bin> [out.json]      write the bundle (default tools/ui/patch_bundle.json)
    make_bundle.py --check <stock.bin> <patched.bin>         fail if the committed bundle does not describe these two images"""
import hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
STOCK_LEN = 0x9DC8                       # NI's firmware image, 40,392 bytes (build_patch.STOCK_LEN)

def make(stock, patched):
    assert len(stock) == STOCK_LEN, 'not the stock image'
    assert patched[:2] and len(patched) > len(stock)
    edits, i = [], 0                                    # runs of bytes that differ; no unchanged (NI) byte is copied into the bundle
    while i < len(stock):
        if stock[i] != patched[i]:
            j = i
            while j < len(stock) and stock[j] != patched[j]: j += 1
            edits.append({'offset': i, 'hex': patched[i:j].hex()}); i = j
        else: i += 1
    return {
        'format': 1,
        'description': 'Maschine Mikro MK3 USB-MIDI patch (hooks, config, descriptors, velocity tables, display font and texts, code); apply to the NI firmware v1.20 image',
        'stock_len': len(stock), 'stock_sha256': hashlib.sha256(stock).hexdigest(),
        'base_address': 0x08003000,
        'edits': edits,
        'tail_offset': len(stock), 'tail_hex': patched[len(stock):].hex(),
        'result_len': len(patched), 'result_sha256': hashlib.sha256(patched).hexdigest(),
    }

def apply(stock, bundle):
    img = bytearray(stock)
    for e in bundle['edits']: img[e['offset']:e['offset'] + len(e['hex']) // 2] = bytes.fromhex(e['hex'])
    return bytes(img) + bytes.fromhex(bundle['tail_hex'])

if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if x != '--check']
    stock, patched = open(a[0], 'rb').read()[:STOCK_LEN], open(a[1], 'rb').read()
    b = make(stock, patched)
    assert apply(stock, b) == patched, 'the bundle does not rebuild the image'
    path = a[2] if len(a) > 2 else os.path.join(HERE, 'patch_bundle.json')
    text = json.dumps(b, indent=1) + '\n'
    if '--check' in sys.argv:
        ok = os.path.exists(path) and open(path).read() == text
        print('patch_bundle.json describes these images' if ok else 'patch_bundle.json is out of date: run tools/ui/make_bundle.py <stock.bin> <patched.bin>'); sys.exit(0 if ok else 1)
    open(path, 'w').write(text)
    print(f'written {path}: {len(b["edits"])} edit regions ({sum(len(e["hex"]) // 2 for e in b["edits"])} bytes), tail {len(b["tail_hex"]) // 2} bytes, result {b["result_len"]} bytes, sha256 {b["result_sha256"][:16]}...')
