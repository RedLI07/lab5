import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.start()

    def start(self):
        env = dict(os.environ, PORT=str(self.port), STATE_FILE=str(self.state), APP_VERSION="v1.0.0")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "main.py")], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.get("/health")
                return
            except OSError:
                time.sleep(.03)
        self.fail("Server did not start")

    def stop(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_health_does_not_change_counter(self):
        self.assertEqual(self.get("/health"), (200, {"status": "ok", "version": "v1.0.0"}))
        self.assertFalse(self.state.exists())

    def test_disk_function(self):
        code, body = self.get("/disk")
        self.assertEqual(code, 200)
        self.assertGreater(body["total_gb"], 0)
        self.assertLessEqual(body["free_gb"], body["total_gb"])
        self.assertEqual(body["requests"], 1)

    def test_missing_route(self):
        self.assertEqual(self.get("/missing")[0], 404)

    def test_state_survives_restart(self):
        self.get("/disk")
        self.stop()
        self.start()
        self.assertEqual(self.get("/disk")[1]["requests"], 2)

    def test_corrupt_state_is_not_overwritten(self):
        self.state.write_text("broken")
        self.assertEqual(self.get("/health")[0], 503)
        self.assertEqual(self.get("/disk")[0], 503)
        self.assertEqual(self.state.read_text(), "broken")

    def test_query_string(self):
        self.assertEqual(self.get("/disk?check=1")[0], 200)

if __name__ == "__main__":
    unittest.main()
