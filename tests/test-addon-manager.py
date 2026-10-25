#!/usr/bin/env python3
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from matelv_addon_manager import MatelvAddonManager


class Handler:
    def __init__(self, addon_id, origin=True):
        body = json.dumps({"id": addon_id}).encode("utf-8")
        self.rfile = io.BytesIO(body)
        self.headers = {"Host": "gate.local", "Content-Length": str(len(body))}
        if origin:
            self.headers["Origin"] = "http://gate.local"


class AddonManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home" / "pi"
        self.root = self.home / "sg1_v4"
        self.web = self.root / "web"
        self.web.mkdir(parents=True)
        marker = self.web / "example.js"
        marker.write_text("EXAMPLE_ADDON_ACTIVE\n", encoding="utf-8")
        checkout = self.home / "Example-Addon"
        checkout.mkdir()
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.name", "Test"], check=True)
        (checkout / "install.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (checkout / "restore.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
        subprocess.run(["git", "-C", str(checkout), "commit", "-qm", "fixture"], check=True)
        subprocess.run([
            "git", "-C", str(checkout), "remote", "add", "origin",
            "https://github.com/matelv-x/Example-Addon.git",
        ], check=True)
        self.registry = Path(self.temp.name) / "registry.json"
        self.registry.write_text(json.dumps({
            "schema": 1,
            "addons": [{
                "id": "example-addon",
                "name": "Example Add-on",
                "repository": "matelv-x/Example-Addon",
                "platforms": ["v4"],
                "detect": {"all": [{"path": "web/example.js", "contains": "EXAMPLE_ADDON_ACTIVE"}]},
                "install": {"argv": ["./install.sh", "--target", "{sg1_root}"]},
                "uninstall": {"argv": ["./restore.sh", "--target", "{sg1_root}"]},
            }],
        }), encoding="utf-8")
        config = lambda: {"platform": "v4", "target": str(self.web)}
        self.manager = MatelvAddonManager(config, registry_path=self.registry)

    def tearDown(self):
        self.temp.cleanup()

    def test_detects_installed_matelv_checkout(self):
        payload = self.manager.list_addons(check_remote=False)
        self.assertTrue(payload["success"])
        self.assertEqual([item["id"] for item in payload["addons"]], ["example-addon"])
        self.assertTrue(payload["addons"][0]["can_update"])
        self.assertTrue(payload["addons"][0]["can_uninstall"])
        self.assertEqual(len(payload["addons"][0]["current_revision"]), 12)

    def test_non_matelv_remote_is_not_a_managed_checkout(self):
        checkout = self.home / "Example-Addon"
        subprocess.run([
            "git", "-C", str(checkout), "remote", "set-url", "origin",
            "https://github.com/someone-else/Example-Addon.git",
        ], check=True)
        payload = self.manager.list_addons(check_remote=False)
        self.assertIsNone(payload["addons"][0]["current_revision"])

    def test_cross_origin_action_is_rejected_before_execution(self):
        result = self.manager.start(Handler("example-addon", origin=False), "uninstall", lambda _handler: False)
        self.assertFalse(result["success"])

    def test_unsafe_manifest_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager._validate_manifest({
                "id": "bad-addon",
                "name": "Bad",
                "repository": "someone-else/Bad",
                "platforms": ["v4"],
            })


if __name__ == "__main__":
    unittest.main()
