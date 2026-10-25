#!/usr/bin/env python3
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from matelv_addon_manager import MatelvAddonManager


class Handler:
    def __init__(self, addon_id, origin=True, content_type=False):
        body = json.dumps({"id": addon_id}).encode("utf-8")
        self.rfile = io.BytesIO(body)
        self.headers = {"Host": "gate.local", "Content-Length": str(len(body))}
        if origin:
            self.headers["Origin"] = "http://gate.local"
        if content_type:
            self.headers["Content-Type"] = "application/json"


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
        config = lambda: {"platform": "v4", "target": str(self.web), "mode": "both"}
        self.manager = MatelvAddonManager(config, registry_path=self.registry)

    def tearDown(self):
        self.temp.cleanup()

    def test_detects_installed_matelv_checkout(self):
        payload = self.manager.list_addons(check_remote=False)
        self.assertTrue(payload["success"])
        self.assertEqual([item["id"] for item in payload["addons"]], ["example-addon"])
        self.assertTrue(payload["addons"][0]["can_update"])
        self.assertTrue(payload["addons"][0]["can_uninstall"])
        self.assertFalse(payload["addons"][0]["can_install"])
        self.assertEqual(payload["available"], [])
        self.assertEqual(len(payload["addons"][0]["current_revision"]), 12)

    def test_not_installed_safe_addon_is_available_for_install(self):
        (self.web / "example.js").unlink()
        payload = self.manager.list_addons(check_remote=False)
        self.assertEqual(payload["addons"], [])
        self.assertEqual([item["id"] for item in payload["available"]], ["example-addon"])
        self.assertTrue(payload["available"][0]["can_install"])

    def test_install_is_blocked_without_safe_uninstall(self):
        (self.web / "example.js").unlink()
        registry = json.loads(self.registry.read_text(encoding="utf-8"))
        registry["addons"][0]["uninstall"] = None
        self.registry.write_text(json.dumps(registry), encoding="utf-8")
        payload = self.manager.list_addons(check_remote=False)
        self.assertFalse(payload["available"][0]["can_install"])
        result = self.manager.start(Handler("example-addon"), "install", lambda _handler: True)
        self.assertFalse(result["success"])
        self.assertIn("safe uninstall", result["message"])

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

    def test_already_parsed_payload_does_not_read_request_stream_twice(self):
        handler = Handler("wrong-addon")
        handler.rfile = io.BytesIO(b"")
        result = self.manager.start(
            handler,
            "uninstall",
            lambda _handler: True,
            {"id": "missing-addon"},
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "unknown add-on")

    def test_unsafe_manifest_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager._validate_manifest({
                "id": "bad-addon",
                "name": "Bad",
                "repository": "someone-else/Bad",
                "platforms": ["v4"],
            })

    def test_refreshes_archive_navigation_from_current_installed_pages(self):
        state = self.web / ".stellar-archive-addon"
        updater = state / "updater"
        archive_data = self.web / "stellar-archive" / "data"
        updater.mkdir(parents=True)
        archive_data.mkdir(parents=True)
        (state / "current-mode").write_text("both\n", encoding="utf-8")
        (updater / "build_navigation.py").write_text(
            "import argparse, pathlib\n"
            "p=argparse.ArgumentParser(); p.add_argument('--target'); p.add_argument('--mode'); p.add_argument('--output')\n"
            "a=p.parse_args(); pathlib.Path(a.output).write_text(a.mode + ':' + a.target, encoding='utf-8')\n",
            encoding="utf-8",
        )
        self.assertTrue(self.manager._refresh_archive_navigation(self.manager.config()))
        result = (archive_data / "integration-nav.js").read_text(encoding="utf-8")
        self.assertEqual(result, "both:" + str(self.web.resolve()))


if __name__ == "__main__":
    unittest.main()
