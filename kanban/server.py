"""Read-only benchmark kanban server."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)


def load_runs(directory):
    runs = []
    for path in sorted(directory.glob('*.json')):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('spec'), dict) or not isinstance(data.get('samples'), list):
                raise ValueError('Expected object with spec object and samples list')
            runs.append(data)
        except (ValueError, OSError) as error:
            LOGGER.warning('Skipping invalid result %s: %s', path.name, type(error).__name__)
    return runs


def page(title, content):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><body><main><h1>{escape(title)}</h1>'
            f'{content}</main></body></html>').encode()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, data_dir, **kwargs):
        self.data_dir = data_dir
        super().__init__(*args, directory=str(BASE / 'static'), **kwargs)

    def log_request(self, code='-', size='-'):
        LOGGER.info('%s %s %s', self.command, urlsplit(self.path).path, code)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        super().end_headers()

    def send_payload(self, payload, content_type='text/html; charset=utf-8', status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/health':
            self.send_payload(b'ok', 'text/plain; charset=utf-8')
            return
        if path == '/api/runs':
            self.send_payload(json.dumps(load_runs(self.data_dir), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        elif path == '/api/jobs':
            jobs = [json.loads(p.read_text()) for p in sorted((self.data_dir.parent / 'jobs').glob('*.json'))]
            self.send_payload(json.dumps(jobs, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        elif path == '/api/audits':
            directory = self.data_dir.parent / 'audits'
            rows = [json.loads(p.read_text()) for p in sorted(directory.glob('*.record.json'))] if directory.is_dir() else []
            self.send_payload(json.dumps(rows, ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        elif path in ('/', '/index.html', '/detail.html', '/summary.js', '/summary-model.mjs', '/detail-filters.mjs', '/visible-refresh.mjs', '/app.js', '/style.css', '/iteration.html', '/iteration.js', '/iteration-config.js', '/iteration.css', '/playground.html', '/playground.css', '/playground.mjs', '/mindspore-logo.svg'):
            if self.command == 'HEAD':
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_payload(page('未找到', '<p>页面不存在。</p>'), status=404)


def create_server(host, port, data_dir):
    return ThreadingHTTPServer((host, port), partial(Handler, data_dir=Path(data_dir)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DATA_DIR', BASE / 'data')))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    server = create_server(args.host, args.port, args.data_dir)
    with server:
        server.serve_forever()


if __name__ == '__main__':
    main()
