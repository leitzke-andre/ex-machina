#!/usr/bin/env python3
"""Serves the page on http://localhost:8765/ (a secure context, which Web MIDI and WebUSB need) and opens it in the default browser.

    serve.py [port] [--mock]        --mock opens the page with a stand-in device (no hardware needed)
Use Chrome or Edge: Safari has neither Web MIDI nor WebUSB."""
import http.server, os, sys, webbrowser, functools
HERE = os.path.dirname(os.path.abspath(__file__))
args = [a for a in sys.argv[1:] if not a.startswith('--')]
port = int(args[0]) if args else 8765
class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, '.js': 'text/javascript', '.json': 'application/json', '.mjs': 'text/javascript'}
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store'); super().end_headers()
    def log_message(self, *a): pass
httpd = http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(Handler, directory=HERE))
url = f'http://localhost:{port}/' + ('?mock' if '--mock' in sys.argv else '')
print('serving', HERE, 'at', url, '(Ctrl-C to stop)')
if '--no-open' not in sys.argv: webbrowser.open(url)
try: httpd.serve_forever()
except KeyboardInterrupt: pass
