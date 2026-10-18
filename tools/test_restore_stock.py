"""tools/restore_stock.sh only ever hands NI's exact firmware 1.20 to the flash script. Usage: test_restore_stock.py <stock.bin>
(the flash script is replaced by a stub, nothing is flashed)"""
import os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
stock = open(sys.argv[1], 'rb').read()
ok = True
def check(name, cond, detail=''):
    global ok; ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else '  ' + str(detail)))

with tempfile.TemporaryDirectory() as d:
    log = os.path.join(d, 'calls.txt'); stub = os.path.join(d, 'stub.sh')
    open(stub, 'w').write(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n'); os.chmod(stub, 0o755)
    def run(*args):
        if os.path.exists(log): os.remove(log)
        r = subprocess.run([os.path.join(HERE, 'restore_stock.sh'), *args], capture_output=True, text=True, env={**os.environ, 'FLASH_GUARDED': stub})
        calls = open(log).read().split('\n')[:-1] if os.path.exists(log) else []
        return r.returncode, r.stdout + r.stderr, calls
    good = os.path.join(d, 'good.bin'); open(good, 'wb').write(stock)
    rc, out, calls = run(good, 'python3')
    check('the exact stock image is handed to the flash script, with the python given', rc == 0 and calls == [f'{good} python3'], (rc, calls, out))
    check('... and it says what it is', "NI's original firmware 1.20" in out, out)
    bad = os.path.join(d, 'bad.bin'); open(bad, 'wb').write(stock[:1000] + bytes([stock[1000] ^ 1]) + stock[1001:])
    rc, out, calls = run(bad)
    check('an image with one flipped bit is refused and nothing is flashed', rc == 2 and calls == [] and 'refusing' in out, (rc, calls, out))
    patched = os.path.join(d, 'longer.bin'); open(patched, 'wb').write(stock + b'\0' * 16)
    rc, out, calls = run(patched)
    check('a longer image (e.g. a patched one) is refused', rc == 2 and calls == [], (rc, calls))
    rc, out, calls = run(os.path.join(d, 'missing.bin'))
    check('a missing file is refused with a hint', rc == 2 and calls == [] and 'carve_fw' in out, (rc, out))
    default = os.path.join(HERE, '..', 'research', 'MM3_firmware_1.20_stock.bin')
    if os.path.exists(default):
        rc, out, calls = run()
        check('without arguments it uses the copy saved in proprietary/', rc == 0 and len(calls) == 1 and calls[0].split()[0].endswith('proprietary/MM3_firmware_1.20_stock.bin'), (rc, calls))
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
