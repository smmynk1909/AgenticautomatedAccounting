"""A `/metrics` + `/healthz` HTTP endpoint for agents — doc 10 HLD C19's
`Prometheus` needs something to scrape, but every agent (`AgentApp.run_forever`)
is a pure bus-consumer loop with no HTTP server otherwise. Stdlib
`http.server` in a daemon thread rather than pulling in FastAPI/uvicorn as a
new dependency just for one endpoint (`awp-agent-base` has neither today).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from awp_shared.metrics import CONTENT_TYPE_LATEST, render_latest

DEFAULT_METRICS_PORT = 9100


class _MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        pass  # the audit log is the real record; don't double-log scrape traffic

    def do_GET(self) -> None:  # noqa: N802 - stdlib method name
        if self.path == "/metrics":
            body = render_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/healthz":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def start_metrics_server(port: int = DEFAULT_METRICS_PORT) -> ThreadingHTTPServer:
    """Starts serving on a daemon thread and returns the server (callers don't
    need to hold onto it — the thread dies with the process)."""
    server = ThreadingHTTPServer(("0.0.0.0", port), _MetricsHandler)  # noqa: S104 - container-internal only, never published to the host
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
