from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os
import shutil
import threading

PORT = int(os.environ.get("PORT", "8000"))
MESSAGE = os.environ.get("MESSAGE", "hello")
APP_VERSION = os.environ.get("APP_VERSION", "dev")
STATE_FILE = os.environ.get("STATE_FILE", "/data/state.json")
DATA_DIR = os.path.dirname(STATE_FILE)

ROUTE = "/disk"

lock = threading.Lock()


def load_count():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("requests", 0))
    except FileNotFoundError:
        return 0


def save_count(count):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"requests": count}, f)
    os.replace(tmp, STATE_FILE)


def increment():
    with lock:
        count = load_count() + 1
        save_count(count)
        return count


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/health":
            try:
                load_count()
                shutil.disk_usage(DATA_DIR)
            except (OSError, ValueError, TypeError, AttributeError):
                self.send_json(503, {"status": "error"})
                return
            self.send_json(200, {"status": "ok", "version": APP_VERSION})
            return

        try:
            count = increment()
        except (OSError, ValueError, TypeError, AttributeError):
            self.send_json(503, {"error": "State unavailable"})
            return

        if path == ROUTE:
            usage = shutil.disk_usage(DATA_DIR)
            self.send_json(200, {
                "message": MESSAGE,
                "version": APP_VERSION,
                "path": DATA_DIR,
                "free_gb": round(usage.free / 1024**3, 2),
                "total_gb": round(usage.total / 1024**3, 2),
                "requests": count,
            })
        else:
            self.send_json(404, {"error": "Not Found", "requests": count})


if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Listening on 0.0.0.0:{PORT}, route {ROUTE}, state {STATE_FILE}", flush=True)
    server.serve_forever()