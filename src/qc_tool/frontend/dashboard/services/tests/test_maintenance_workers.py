"""Worker control deadlines must hold even for a stalled/trickling peer."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPException
from threading import Event, Lock, Thread
from time import monotonic
from unittest.mock import patch

from django.test import SimpleTestCase

from qc_tool.common import CONFIG
from qc_tool.frontend.dashboard.services.maintenance import control, workers


class WorkerTransportTests(SimpleTestCase):
    def test_trickling_headers_are_interrupted_by_total_request_deadline(self):
        release = Event()

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                # Every byte arrives inside the socket timeout, so only an
                # overall deadline can stop this response promptly.
                for byte in b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n":
                    try:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                    except OSError:
                        return
                    if release.wait(0.02):
                        return

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            with patch.dict(CONFIG, worker_port=port), patch.object(workers, "REQUEST_TIMEOUT_SECONDS", 0.1), patch.object(workers, "get_worker_token", return_value="test-token"):
                started = monotonic()
                with self.assertRaises((HTTPException, OSError, ValueError)):
                    workers.request_worker_state("http://127.0.0.1:{}/".format(port), {"enabled": True, "generation": 1})
                self.assertLess(monotonic() - started, 1)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_readiness_deadline_does_not_wait_for_pending_worker_results(self):
        release = Event()
        started = Event()
        try:
            def delayed_probe(*args):
                started.set()
                release.wait(3)
                return True

            with patch.object(control, "_worker_state", side_effect=delayed_probe), patch.object(control, "READINESS_TIMEOUT_SECONDS", 0.05):
                before = monotonic()
                blockers = control._worker_blockers(["http://127.0.0.1:8000/"], {"enabled": True, "generation": 1})
                self.assertTrue(started.is_set())
                self.assertLess(monotonic() - before, 1)
                self.assertIn("deadline", blockers[0])
        finally:
            release.set()

    def test_worker_probes_run_concurrently_with_fixed_capacity(self):
        release = Event()
        two_started = Event()
        lock = Lock()
        active = 0
        maximum = 0

        def probe(*args):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active >= 2:
                    two_started.set()
            release.wait(2)
            with lock:
                active -= 1
            return True

        def permit_completion():
            two_started.wait(2)
            release.set()

        releaser = Thread(target=permit_completion)
        releaser.start()
        try:
            with patch.object(control, "_worker_state", side_effect=probe):
                blockers = control._worker_blockers(["worker-{}".format(index) for index in range(12)], {"enabled": True, "generation": 1})
            self.assertEqual(blockers, [])
            self.assertGreaterEqual(maximum, 2)
            self.assertLessEqual(maximum, control.MAX_PROBE_WORKERS)
        finally:
            release.set()
            releaser.join(2)
