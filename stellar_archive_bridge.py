"""Dependency-free SG1_v3 web bridge for Stellar Archive.

The bridge runs inside the existing SG1_v3 process so accepted web requests
reach the same StargateSG1 object as the physical DHD. It never starts a dial
from a GET request; dialing requires a same-origin JSON POST.
"""

from __future__ import print_function

import json
import mimetypes
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from stellar_archive_maintenance import get_maintenance_controller


ADDRESS_RE = re.compile(r"^[0-9]+(?:-[0-9]+){5,7}$")


class StellarArchiveBridge:
    def __init__(self, stargate, archive_root, host="0.0.0.0", port=80):
        self.stargate = stargate
        self.archive_root = os.path.realpath(archive_root)
        self.host = host
        self.port = int(port)
        self.dial_lock = threading.Lock()
        self.server = None

    def build_server(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "StellarArchiveV3/1.4"

            def log_message(self, fmt, *args):
                logger = getattr(bridge.stargate, "log", None)
                if callable(logger):
                    logger("sg1.log", "Stellar Archive HTTP: " + (fmt % args))

            def send_json(self, status, payload):
                data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def redirect(self, location):
                self.send_response(303)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self.redirect("/stellar-archive/")
                    return
                if parsed.path == "/stargate/get/dialing_status":
                    self.send_json(200, bridge.dialing_status())
                    return
                if parsed.path == "/stargate/get/address_book":
                    self.send_json(200, bridge.address_book())
                    return
                if parsed.path == "/stargate/get/stellar_archive_update":
                    self.send_json(200, get_maintenance_controller().check())
                    return
                if parsed.path == "/stargate/get/stellar_archive_addons":
                    self.send_json(200, get_maintenance_controller().list_addons())
                    return
                if parsed.path == "/stellar-archive":
                    self.redirect("/stellar-archive/")
                    return
                if parsed.path.startswith("/stellar-archive/"):
                    bridge.serve_static(self, parsed.path)
                    return
                self.send_error(404)

            def do_HEAD(self):
                parsed = urlparse(self.path)
                if parsed.path.startswith("/stellar-archive/"):
                    bridge.serve_static(self, parsed.path, head_only=True)
                    return
                self.send_error(404)

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path == "/stargate/do/stellar_archive_update":
                    self.send_json(200, get_maintenance_controller().start_update(self))
                    return
                if parsed.path == "/stargate/do/stellar_archive_uninstall":
                    self.send_json(200, get_maintenance_controller().start_uninstall(self))
                    return
                if parsed.path == "/stargate/do/stellar_archive_addon_update":
                    self.send_json(200, get_maintenance_controller().start_addon_update(self))
                    return
                if parsed.path == "/stargate/do/stellar_archive_addon_uninstall":
                    self.send_json(200, get_maintenance_controller().start_addon_uninstall(self))
                    return
                if parsed.path != "/stellar-archive/api/dial":
                    self.send_error(404)
                    return
                if not bridge.same_origin(self):
                    self.send_json(403, {"ok": False, "error": "same-origin request required"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length < 2 or length > 512:
                    self.send_json(400, {"ok": False, "error": "invalid request size"})
                    return
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    address = payload.get("address")
                    accepted = bridge.queue_dial(address)
                except ValueError as error:
                    self.send_json(422, {"ok": False, "error": str(error)})
                    return
                except RuntimeError as error:
                    self.send_json(409, {"ok": False, "error": str(error)})
                    return
                self.send_json(202, {"ok": True, "address": accepted, "message": "Dial accepted by SG1_v3"})

        self.server = ThreadingHTTPServer((self.host, self.port), Handler)
        return self.server

    def start(self):
        server = self.build_server()
        thread = threading.Thread(target=server.serve_forever, name="stellar-archive-http")
        thread.daemon = True
        thread.start()
        return thread

    def same_origin(self, handler):
        source = handler.headers.get("Origin") or handler.headers.get("Referer")
        host = handler.headers.get("Host", "")
        if not source or not host:
            return False
        return urlparse(source).netloc.lower() == host.lower()

    def serve_static(self, handler, request_path, head_only=False):
        relative = unquote(request_path[len("/stellar-archive/"):]) or "index.html"
        candidate = os.path.realpath(os.path.join(self.archive_root, relative))
        if candidate != self.archive_root and not candidate.startswith(self.archive_root + os.sep):
            handler.send_error(403)
            return
        if not os.path.isfile(candidate):
            handler.send_error(404)
            return
        size = os.path.getsize(candidate)
        content_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(size))
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Cache-Control", "no-cache" if candidate.endswith((".html", ".js")) else "public, max-age=86400")
        handler.end_headers()
        if not head_only:
            with open(candidate, "rb") as source:
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    handler.wfile.write(chunk)

    def parse_address(self, value):
        if not isinstance(value, str) or not ADDRESS_RE.fullmatch(value):
            raise ValueError("address must contain 6 to 8 hyphen-separated glyph numbers")
        address = [int(part) for part in value.split("-")]
        if any(symbol < 1 or symbol > 39 for symbol in address):
            raise ValueError("glyph numbers must be between 1 and 39")
        if len(set(address)) != len(address):
            raise ValueError("an SG1_v3 address cannot repeat a glyph")
        if 1 in address:
            raise ValueError("stored address must not contain Earth point of origin glyph 1")
        return address

    def queue_dial(self, value):
        stored = self.parse_address(value)
        complete = stored + [1]
        with self.dial_lock:
            gate = self.stargate
            if getattr(gate, "wormhole", False):
                raise RuntimeError("Stargate already has an active wormhole")
            if getattr(gate, "address_buffer_outgoing", []) or getattr(gate, "address_buffer_incoming", []):
                raise RuntimeError("Stargate is already dialing")
            validator = getattr(gate, "valid_planet", None)
            if not callable(validator) or not validator(complete):
                raise ValueError("address is not known to this SG1_v3 installation")
            gate.address_buffer_outgoing = complete
            gate.centre_button_outgoing = True
            timer = getattr(gate, "time", None)
            if callable(timer):
                gate.last_activity_time = timer()
            logger = getattr(gate, "log", None)
            if callable(logger):
                logger("sg1.log", "Stellar Archive queued outgoing address: {}".format(complete))
        return stored

    def dialing_status(self):
        return {
            "platform": "sg1_v3",
            "gate_name": socket.gethostname(),
            "local_address": list(getattr(self.stargate, "local_stargate_address", [])),
            "dialing": bool(getattr(self.stargate, "address_buffer_outgoing", [])),
            "wormhole": bool(getattr(self.stargate, "wormhole", False)),
        }

    def address_book(self):
        entries = {}
        try:
            from hardcoded_addresses import known_planets
        except ImportError:
            known_planets = {}
        for index, (name, address) in enumerate(known_planets.items()):
            entries["standard-{:03d}".format(index + 1)] = {
                "name": name,
                "type": "standard",
                "gate_address": list(address),
                "is_gate_online": None,
            }
        for index, (name, record) in enumerate(getattr(self.stargate, "fan_gates", {}).items()):
            address = record[0] if isinstance(record, (list, tuple)) and record else []
            if isinstance(address, list):
                entries["fan-{:03d}".format(index + 1)] = {
                    "name": name,
                    "type": "fan",
                    "gate_address": list(address),
                    "is_gate_online": None,
                }
        local = list(getattr(self.stargate, "local_stargate_address", []))
        if local:
            entries["local"] = {"name": socket.gethostname(), "type": "lan", "gate_address": local, "is_gate_online": 1}
        return {"platform": "sg1_v3", "address_book": entries}


def start_stellar_archive_bridge(stargate):
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stellar-archive")
    port = int(os.environ.get("STELLAR_ARCHIVE_PORT", "80"))
    bridge = StellarArchiveBridge(stargate, root, port=port)
    bridge.start()
    setattr(stargate, "stellar_archive_bridge", bridge)
    logger = getattr(stargate, "log", None)
    if callable(logger):
        logger("sg1.log", "Stellar Archive bridge listening on port {}".format(bridge.server.server_port))
    return bridge
