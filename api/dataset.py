"""Vercel serverless function for GET /api/dataset?seed=&rows=.

File-based Python function: `handler` is a BaseHTTPRequestHandler subclass,
so Vercel maps this file to /api/dataset and serves the same JSON the local
`server.py` produces.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metric_prediction_generator import build_lake_dataset  # noqa: E402


def _dataset(seed, rows):
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = 42
    try:
        rows = min(max(int(rows), 50), 3000)
    except (TypeError, ValueError):
        rows = 500
    return build_lake_dataset(seed, cells_target=rows)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/dataset":
            q = parse_qs(url.query)
            seed = q.get("seed", ["42"])[0]
            rows = q.get("rows", ["500"])[0]
            data = _dataset(seed, rows)
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404, "not found")

    def log_message(self, *args):
        pass