"""
Lightweight HTTP command server for the sandbox container.

Runs inside the ACI container so the backend can communicate directly
over the private VNet (no Azure exec WebSocket relay required).

Endpoints:
    POST /exec          {"command": "..."}              → {"exit_code", "stdout", "stderr"}
    POST /write         {"path": "...", "b64": "..."}   → {"ok": true}
    POST /read          {"path": "..."}                 → {"b64": "..."}
    POST /read-text     {"path": "..."}                 → {"text": "..."}
    POST /list          {"path": "..."}                 → {"files": [...]}
    GET  /health                                        → {"status": "ok"}
"""

import base64
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 443


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/health":
            self._json_response({"status": "ok"})
        else:
            self._json_response({"error": "not found"}, 404)

    def do_POST(self):
        try:
            body = self._read_body()

            if self.path == "/exec":
                cmd = body.get("command", "")
                timeout = body.get("timeout", 300)
                result = subprocess.run(
                    ["/bin/sh", "-c", cmd],
                    capture_output=True,
                    timeout=timeout,
                )
                self._json_response({
                    "exit_code": result.returncode,
                    "stdout": result.stdout.decode(errors="replace"),
                    "stderr": result.stderr.decode(errors="replace"),
                })

            elif self.path == "/write":
                path = body["path"]
                b64 = body["b64"]
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
                self._json_response({"ok": True})

            elif self.path == "/read":
                path = body["path"]
                with open(path, "rb") as f:
                    self._json_response({"b64": base64.b64encode(f.read()).decode()})

            elif self.path == "/read-text":
                path = body["path"]
                with open(path, "r") as f:
                    self._json_response({"text": f.read()})

            elif self.path == "/list":
                path = body.get("path", "/workspace")
                files = []
                for root, _, fnames in os.walk(path):
                    for fn in fnames:
                        files.append(os.path.join(root, fn))
                self._json_response({"files": files})

            else:
                self._json_response({"error": "not found"}, 404)

        except subprocess.TimeoutExpired:
            self._json_response({"exit_code": -1, "stdout": "", "stderr": "timeout"}, 200)
        except FileNotFoundError as e:
            self._json_response({"error": f"file not found: {e}"}, 404)
        except Exception as e:
            self._json_response({"error": str(e)}, 500)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Sandbox server listening on :{PORT}", file=sys.stderr, flush=True)
    server.serve_forever()
