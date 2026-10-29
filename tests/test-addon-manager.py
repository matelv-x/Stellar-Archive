#!/usr/bin/env python3
import io
import json
import subprocess
import shutil
import tempfile
import unittest
from unittest import mock
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
        (checkout / "stargate-addon.json").write_text(json.dumps({
            "id": "example-addon",
            "maintenance_contract": 1,
            "uninstall_contract": 2,
            "name": "Example Add-on",
            "repository": "matelv-x/Example-Addon",
            "platforms": ["v4"],
            "detect": {"all": [{"path": "web/example.js", "contains": "EXAMPLE_ADDON_ACTIVE"}]},
            "install": {"argv": ["./install.sh", "--target", "{sg1_root}"]},
            "uninstall": {"argv": ["./restore.sh", "--target", "{sg1_root}"]},
        }), encoding="utf-8")
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
                "maintenance_contract": 1,
                "uninstall_contract": 2,
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
        self.manager.state_path = Path(self.temp.name) / "addon-state.json"

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
        checkout_manifest = self.home / "Example-Addon" / "stargate-addon.json"
        checkout_payload = json.loads(checkout_manifest.read_text(encoding="utf-8"))
        checkout_payload["uninstall"] = None
        checkout_manifest.write_text(json.dumps(checkout_payload), encoding="utf-8")
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

    def test_refreshes_managed_snapshots_after_verified_addon_changes(self):
        managed = self.web / ".stellar-archive-addon" / "managed"
        (managed / "original-nav-pages").mkdir(parents=True)
        (self.web / "retro" / "js").mkdir(parents=True)
        pairs = [
            (self.web / "address_book.htm", managed / "address_book.htm"),
            (self.web / "retro" / "address_book.html", managed / "retro-address_book.html"),
            (self.web / "retro" / "js" / "navigation.js", managed / "retro-navigation.js"),
            (self.web / "index.htm", managed / "original-nav-pages" / "index.htm"),
        ]
        for source, snapshot in pairs:
            source.write_text("ADDON EDIT " + source.name, encoding="utf-8")
            snapshot.write_text("OLD SNAPSHOT", encoding="utf-8")
        refreshed = self.manager._refresh_archive_managed_pages(self.manager.config())
        self.assertEqual(refreshed, len(pairs))
        for source, snapshot in pairs:
            self.assertEqual(snapshot.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))

    def test_refreshes_declared_backend_snapshot_only(self):
        managed = self.web / ".stellar-archive-addon" / "managed"
        managed.mkdir(parents=True)
        backend = self.root / "classes" / "web_server.py"
        backend.parent.mkdir(parents=True)
        backend.write_text("verified add-on edit", encoding="utf-8")
        snapshot = managed / "web_server.py"
        snapshot.write_text("old", encoding="utf-8")
        manifest = {"archive_integration_files": ["classes/web_server.py"]}
        self.manager._refresh_archive_managed_pages(self.manager.config(), manifest)
        self.assertEqual(snapshot.read_text(encoding="utf-8"), "verified add-on edit")

    def test_current_cached_uninstaller_uses_no_network_download(self):
        context = self.manager.config()
        checkout = self.manager._checkout_map(context["home_root"])["matelv-x/example-addon"]
        revision = self.manager._local_revision(checkout)
        self.manager._cache_verified_checkout(context, "example-addon", checkout)
        shutil.rmtree(str(checkout["path"]))
        manifest = self.manager._registry()["example-addon"]
        commands = []
        original_run = self.manager._run

        def tracked(command, **kwargs):
            commands.append(list(command))
            return original_run(command, **kwargs)

        with mock.patch.object(self.manager, "_run", side_effect=tracked), mock.patch.object(
            self.manager, "_remote_revision", return_value=(revision, "")
        ):
            self.manager._run_action("example-addon", "uninstall", manifest, context, None)

        self.assertEqual(self.manager.tasks["example-addon"]["state"], "complete")
        network_clones = [
            command for command in commands
            if command[:2] == ["git", "clone"] and any("github.com" in part for part in command)
        ]
        self.assertEqual(network_clones, [])
        cache = context["target"] / ".stellar-archive-addon" / "addon-packages" / "example-addon"
        self.assertEqual(self.manager._local_revision({"path": cache}), revision)

    def test_inconclusive_revision_check_downloads_fresh_github_uninstaller(self):
        context = self.manager.config()
        checkout = self.manager._checkout_map(context["home_root"])["matelv-x/example-addon"]
        manifest = self.manager._registry()["example-addon"]
        commands = []
        original_run = self.manager._run

        def tracked(command, **kwargs):
            commands.append(list(command))
            if command[:4] == ["git", "clone", "--depth", "1"] and "github.com" in command[4]:
                replacement = list(command)
                replacement[4] = str(checkout["path"])
                result = original_run(replacement, **kwargs)
                if result.returncode == 0:
                    original_run([
                        "git", "-C", command[5], "remote", "set-url", "origin", checkout["origin"],
                    ], timeout=5)
                return result
            return original_run(command, **kwargs)

        with mock.patch.object(self.manager, "_run", side_effect=tracked), mock.patch.object(
            self.manager, "_remote_revision", return_value=(None, "lightweight check unavailable")
        ):
            self.manager._run_action("example-addon", "uninstall", manifest, context, checkout)

        self.assertEqual(self.manager.tasks["example-addon"]["state"], "complete")
        github_clones = [
            command for command in commands
            if command[:4] == ["git", "clone", "--depth", "1"] and "github.com" in command[4]
        ]
        self.assertEqual(len(github_clones), 1)


if __name__ == "__main__":
    unittest.main()
