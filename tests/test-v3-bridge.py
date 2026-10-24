#!/usr/bin/env python3
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from stellar_archive_bridge import StellarArchiveBridge


class FakeGate:
    def __init__(self):
        self.wormhole = False
        self.address_buffer_outgoing = []
        self.address_buffer_incoming = []
        self.centre_button_outgoing = False
        self.last_activity_time = None
        self.local_stargate_address = [2, 3, 4, 5, 6, 7]
        self.fan_gates = {}
        self.logs = []

    def valid_planet(self, address):
        return address == [27, 7, 15, 32, 12, 30, 1]

    def time(self):
        return 123.5

    def log(self, filename, message):
        self.logs.append((filename, message))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        Path(self.temp.name, "index.html").write_text("archive", encoding="utf-8")
        self.gate = FakeGate()
        self.bridge = StellarArchiveBridge(self.gate, self.temp.name, host="127.0.0.1", port=0)
        self.server = self.bridge.build_server()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=2)

    def post(self, payload, origin=True):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = self.base
        request = urllib.request.Request(
            self.base + "/stellar-archive/api/dial",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return urllib.request.urlopen(request, timeout=2)

    def test_static_status_and_safe_dial(self):
        self.assertEqual(self.get("/stellar-archive/").read(), b"archive")
        status = json.loads(self.get("/stargate/get/dialing_status").read())
        self.assertEqual(status["platform"], "sg1_v3")
        response = self.post({"address": "27-7-15-32-12-30"})
        self.assertEqual(response.status, 202)
        self.assertEqual(self.gate.address_buffer_outgoing, [27, 7, 15, 32, 12, 30, 1])
        self.assertTrue(self.gate.centre_button_outgoing)
        self.assertEqual(self.gate.last_activity_time, 123.5)

    def test_get_never_dials(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/stellar-archive/api/dial?address=27-7-15-32-12-30")
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(self.gate.address_buffer_outgoing, [])

    def test_rejects_cross_origin_unknown_and_busy(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"address": "27-7-15-32-12-30"}, origin=False)
        self.assertEqual(caught.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"address": "2-3-4-5-6-7"})
        self.assertEqual(caught.exception.code, 422)
        self.gate.address_buffer_outgoing = [9]
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"address": "27-7-15-32-12-30"})
        self.assertEqual(caught.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
