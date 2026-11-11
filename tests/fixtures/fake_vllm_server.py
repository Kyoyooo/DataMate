"""Stand-in for ``python -m vllm.entrypoints.openai.api_server`` (CPU tests only).

Accepts the real flags (unknown flags with one value are ignored but recorded),
serves ``GET /health`` and ``POST /v1/chat/completions`` on 127.0.0.1.
Behavior is controlled by environment variables, not by flags, so the argv under
test stays identical to production:
  FAKE_VLLM_STARTUP_S   seconds before the socket opens (default 0)
  FAKE_VLLM_EXIT_CODE   exit immediately with this code (simulates a crashed launch)
  FAKE_VLLM_DIE_AFTER_S exit after serving for this long (simulates a replica crash)
  FAKE_VLLM_MARKER      with FAKE_VLLM_EXIT_CODE: only the first start (marker file absent) fails;
                        it creates the marker, so a restart starts normally
  FAKE_VLLM_FAIL_GPUS   comma-separated CUDA_VISIBLE_DEVICES values whose launch always fails
                        (exit 4): one broken GPU among healthy ones
  FAKE_VLLM_REPLY_DELAY_S seconds to wait before answering a completion (a slow model)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main(argv: list[str]) -> int:
    flags: dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                flags[argv[i]] = argv[i + 1]
                i += 2
                continue
            flags[argv[i]] = ""
        i += 1
    failing = [g for g in os.environ.get("FAKE_VLLM_FAIL_GPUS", "").split(",") if g]
    if os.environ.get("CUDA_VISIBLE_DEVICES", "") in failing:
        print("fake vllm: simulated broken GPU", flush=True)
        return 4
    code = os.environ.get("FAKE_VLLM_EXIT_CODE")
    marker = os.environ.get("FAKE_VLLM_MARKER")
    if code and not (marker and os.path.exists(marker)):
        if marker:
            open(marker, "w").close()
        print("fake vllm: simulated launch failure", flush=True)
        return int(code)
    time.sleep(float(os.environ.get("FAKE_VLLM_STARTUP_S", "0")))
    print("fake vllm argv flags:", json.dumps(flags, sort_keys=True), flush=True)
    print("CUDA_VISIBLE_DEVICES=" + os.environ.get("CUDA_VISIBLE_DEVICES", ""), flush=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the captured log small
            pass

        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(float(os.environ.get("FAKE_VLLM_REPLY_DELAY_S", "0")))
            text = f"pong:{body['max_tokens']}"
            data = json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
                              ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((flags.get("--host", "127.0.0.1"), int(flags["--port"])), Handler)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    die = os.environ.get("FAKE_VLLM_DIE_AFTER_S")
    if die:
        threading.Timer(float(die), lambda: os._exit(3)).start()
    server.serve_forever()
    print("fake vllm: clean shutdown", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
