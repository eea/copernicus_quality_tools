"""Bounded, direct worker control requests with no proxy or redirect handling."""

from http.client import HTTPConnection, HTTPSConnection
import json
import socket
from threading import Timer
from time import monotonic
from urllib.parse import urlsplit

from qc_tool.common import CONFIG, WORKER_PORT, get_worker_token
from qc_tool.maintenance.protocol import MAX_MESSAGE_BYTES, decode_message, parse_acknowledgment
from qc_tool.worker_auth import build_worker_authorization, worker_maintenance_url


REQUEST_TIMEOUT_SECONDS = 5


def _interrupt_socket(sock):
    # A socket timeout alone is renewed by each read. Shutdown enforces a wall
    # deadline even if a peer keeps trickling response headers or body bytes.
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


def request_worker_state(worker_url, state):
    url = worker_maintenance_url(worker_url, expected_port=CONFIG.get("worker_port", WORKER_PORT))
    parsed = urlsplit(url)
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=REQUEST_TIMEOUT_SECONDS)
    deadline = monotonic() + REQUEST_TIMEOUT_SECONDS
    timer = None
    try:
        # Origins are literal IP addresses, so no ambient proxy or DNS can
        # redirect credentials. http.client does not follow HTTP redirects.
        connection.connect()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Worker maintenance deadline exceeded")
        timer = Timer(remaining, _interrupt_socket, args=(connection.sock,))
        timer.daemon = True
        timer.start()
        connection.request("PUT", parsed.path, body=json.dumps({
            "enabled": state["enabled"], "generation": state["generation"],
        }).encode(), headers={
            "Authorization": build_worker_authorization(get_worker_token()),
            "Content-Type": "application/json", "Accept": "application/json",
        })
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Worker rejected maintenance command")
        raw = response.read(MAX_MESSAGE_BYTES + 1)
        if monotonic() >= deadline:
            raise TimeoutError("Worker maintenance deadline exceeded")
        return parse_acknowledgment(decode_message(raw), expected_enabled=state["enabled"], expected_generation=state["generation"])
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()
