import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .logger import get_logger

logger = get_logger(__name__)


class MonitorServer:
    """Lightweight HTTP server that exposes sync status as JSON."""

    def __init__(self, port=8080):
        self._lock = threading.Lock()
        self._port = port
        self._start_time = time.time()
        self._state = {
            "status": "starting",
            "product_sync": {
                "status": "waiting",
                "last_sync": "never",
                "last_sync_duration_seconds": 0,
                "last_sync_results": {
                    "created": 0,
                    "updated": 0,
                    "deactivated": 0,
                    "skipped": 0,
                    "errors": 0,
                },
                "next_sync_in_seconds": 0,
            },
        }
        self._server = None

    def _build_response(self):
        with self._lock:
            snapshot = {
                "status": self._state["status"],
                "uptime_seconds": round(time.time() - self._start_time, 1),
                "product_sync": dict(self._state["product_sync"]),
            }
            if "order_sync" in self._state:
                snapshot["order_sync"] = dict(self._state["order_sync"])
        return snapshot

    def start(self):
        parent = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5

            def do_GET(self):
                try:
                    if self.path in ("/", "/status"):
                        body = json.dumps(parent._build_response(), indent=2).encode()
                        self.send_response(200)
                    elif self.path == "/health":
                        with parent._lock:
                            healthy = parent._state["status"] != "starting"
                        body = json.dumps({"healthy": healthy}).encode()
                        self.send_response(200 if healthy else 503)
                    else:
                        self.send_error(404)
                        return
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def log_message(self, format, *args):
                pass

        try:
            self._server = ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        except OSError as e:
            logger.error(f"Failed to start monitor server on port {self._port}: {e}")
            return

        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Monitor server started on port {self._port}.")

    def set_ready(self):
        with self._lock:
            if self._state["status"] == "starting":
                self._state["status"] = "ok"

    def set_running(self):
        with self._lock:
            self._state["product_sync"]["status"] = "running"
            if self._state["status"] == "starting":
                self._state["status"] = "ok"

    def set_product_waiting(self, next_sync_in):
        with self._lock:
            self._state["product_sync"]["status"] = "waiting"
            self._state["product_sync"]["next_sync_in_seconds"] = round(next_sync_in)

    def set_order_waiting(self, next_sync_in):
        with self._lock:
            if "order_sync" not in self._state:
                self._state["order_sync"] = {
                    "status": "waiting",
                    "last_sync": "never",
                    "last_sync_duration_seconds": 0,
                    "last_sync_results": {
                        "new_orders": 0,
                        "submitted": 0,
                        "fulfilled": 0,
                        "poll_checked": 0,
                        "errors": 0,
                    },
                    "next_sync_in_seconds": round(next_sync_in),
                }
            else:
                self._state["order_sync"]["status"] = "waiting"
                self._state["order_sync"]["next_sync_in_seconds"] = round(next_sync_in)

    def update_status(self, sync_results, duration, next_sync_in=None):
        with self._lock:
            errors = sync_results.get("errors", 0)
            self._state["product_sync"]["status"] = "error" if errors > 0 else "ok"
            self._state["product_sync"]["last_sync"] = datetime.now(timezone.utc).isoformat()
            self._state["product_sync"]["last_sync_duration_seconds"] = round(duration, 2)
            self._state["product_sync"]["last_sync_results"] = {
                "created": sync_results.get("created", 0),
                "updated": sync_results.get("updated", 0),
                "deactivated": sync_results.get("deactivated", 0),
                "skipped": sync_results.get("skipped", 0),
                "errors": errors,
            }
            if next_sync_in is not None:
                self._state["product_sync"]["next_sync_in_seconds"] = round(next_sync_in)
            # Update top-level status
            self._state["status"] = "error" if errors > 0 else "ok"

    def update_order_status(self, order_results, duration, next_sync_in=None):
        with self._lock:
            errors = order_results.get("errors", 0)
            self._state["order_sync"] = {
                "status": "error" if errors > 0 else "ok",
                "last_sync": datetime.now(timezone.utc).isoformat(),
                "last_sync_duration_seconds": round(duration, 2),
                "last_sync_results": {
                    "new_orders": order_results.get("new_orders", 0),
                    "submitted": order_results.get("submitted", 0),
                    "fulfilled": order_results.get("fulfilled", 0),
                    "poll_checked": order_results.get("poll_checked", 0),
                    "errors": errors,
                },
                "next_sync_in_seconds": round(next_sync_in) if next_sync_in else 0,
            }
            # Update top-level status
            if errors > 0:
                self._state["status"] = "error"
            elif self._state["status"] != "error":
                self._state["status"] = "ok"
