"""Zero-dependency web server for the lake metric dashboard.

Serves the full-screen dashboard (static/index.html) and a JSON API that
returns the ~1 sq km lake grid dataset with every metric + prediction.
Run:  python server.py [port]
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from metric_prediction_generator import build_lake_dataset, METRIC_KEYS

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)

        if url.path in ("/", "/index.html"):
            path = os.path.join(STATIC, "index.html")
            if os.path.exists(path):
                body = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, "static/index.html not found")
            return

        if url.path == "/api/dataset":
            q = parse_qs(url.query)
            try:
                seed = int(q.get("seed", ["42"])[0])
            except ValueError:
                seed = 42
            try:
                rows = min(max(int(q.get("rows", ["500"])[0]), 50), 3000)
            except ValueError:
                rows = 500
            data = build_lake_dataset(seed, cells_target=rows)
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if url.path == "/api/metrics":
            body = json.dumps(METRIC_KEYS).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404, "not found")

    def log_message(self, *args):  # keep the console quiet
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving lake metric dashboard on http://127.0.0.1:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass