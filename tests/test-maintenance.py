#!/usr/bin/env python3
import hashlib
import json
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from stellar_archive_maintenance import StellarArchiveMaintenance


class Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class Handler:
    def __init__(self, same_origin=True):
        self.headers = Headers({"Host": "gate.local"})
        if same_origin:
            self.headers["Origin"] = "http://gate.local"


class TestController(StellarArchiveMaintenance):
    def __init__(self, config_path, release, assets):
        super().__init__(config_path)
        self.release = release
        self.assets = assets

    def latest_release(self):
        return dict(self.release)

    def _download(self, url, destination):
        shutil.copy2(self.assets[url], destination)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.marker = self.root / "args.txt"
        package = self.root / "package"
        package.mkdir()
        installer = package / "install.sh"
        installer.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > '{}'\n".format(self.marker), encoding="utf-8")
        installer.chmod(0o755)
        self.zip_path = self.root / "release.zip"
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(installer, "sg1-v3-v4-stellar-archive-universal-v1.5.19/install.sh")
        digest = hashlib.sha256(self.zip_path.read_bytes()).hexdigest()
        self.sha_path = self.root / "release.zip.sha256"
        self.sha_path.write_text("{}  release.zip\n".format(digest), encoding="utf-8")
        self.cached = self.root / "cached-install.sh"
        self.cached.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > '{}'\n".format(self.root / "uninstall.txt"), encoding="utf-8")
        self.cached.chmod(0o755)
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps({
            "version": "1.2.9",
            "platform": "v4",
            "target": "/tmp/example-web",
            "mode": "standalone",
            "repository": "example/archive",
            "installer": str(self.cached),
            "restart_service": "stargate-test.service",
        }), encoding="utf-8")
        release = {"version": "1.5.19", "zip_name": "release.zip", "zip_url": "zip", "sha_url": "sha", "release_url": "https://example.invalid"}
        self.controller = TestController(self.config_path, release, {"zip": self.zip_path, "sha": self.sha_path})

    def tearDown(self):
        self.temp.cleanup()

    def wait(self):
        for _ in range(100):
            if self.controller.task.get("state") != "running":
                return
            time.sleep(0.02)
        self.fail("maintenance task did not complete")

    def test_verified_update_runs_platform_installer(self):
        result = self.controller.start_update(Handler())
        self.assertTrue(result["success"])
        self.wait()
        self.assertEqual(self.controller.task["state"], "complete")
        args = self.marker.read_text(encoding="utf-8").splitlines()
        self.assertEqual(args, ["--platform", "v4", "--target", "/tmp/example-web", "--replace", "standalone"])

    @mock.patch("stellar_archive_maintenance.urllib.request.urlopen")
    def test_latest_release_uses_public_redirect_without_github_api(self, urlopen):
        response = mock.MagicMock()
        response.geturl.return_value = "https://github.com/example/archive/releases/tag/v1.5.19"
        urlopen.return_value.__enter__.return_value = response
        release = StellarArchiveMaintenance(self.config_path).latest_release()
        self.assertEqual(release["version"], "1.5.19")
        self.assertEqual(
            release["zip_url"],
            "https://github.com/example/archive/releases/download/v1.5.19/sg1_v3_v4_stellar_archive_universal_1.5.19.zip",
        )
        self.assertEqual(release["sha_url"], release["zip_url"] + ".sha256")
        requested = urlopen.call_args.args[0]
        self.assertEqual(requested.full_url, "https://github.com/example/archive/releases/latest")
        self.assertNotIn("api.github.com", requested.full_url)

    @mock.patch("stellar_archive_maintenance.urllib.request.urlopen")
    def test_latest_release_rejects_redirect_outside_configured_repository(self, urlopen):
        response = mock.MagicMock()
        response.geturl.return_value = "https://example.invalid/releases/tag/v9.9.9"
        urlopen.return_value.__enter__.return_value = response
        with self.assertRaisesRegex(ValueError, "redirect is unavailable"):
            StellarArchiveMaintenance(self.config_path).latest_release()

    def test_uninstall_uses_cached_installer(self):
        result = self.controller.start_uninstall(Handler())
        self.assertTrue(result["success"])
        self.wait()
        args = (self.root / "uninstall.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(args, ["--platform", "v4", "--target", "/tmp/example-web", "--uninstall"])

    def test_cross_origin_is_rejected(self):
        result = self.controller.start_update(Handler(False))
        self.assertFalse(result["success"])

    def test_safari_json_post_without_origin_is_accepted(self):
        handler = Handler(False)
        handler.headers["Content-Type"] = "application/json; charset=UTF-8"
        self.assertTrue(self.controller.same_origin(handler))

    def test_explicit_foreign_origin_is_rejected_even_for_json(self):
        handler = Handler(False)
        handler.headers["Origin"] = "https://attacker.invalid"
        handler.headers["Content-Type"] = "application/json"
        handler.headers["X-Stellar-Archive-Request"] = "same-origin"
        handler.headers["Sec-Fetch-Site"] = "cross-site"
        self.assertFalse(self.controller.same_origin(handler))

    def test_proxy_mismatched_origin_accepts_marked_same_origin_json(self):
        handler = Handler(False)
        handler.headers["Host"] = "localhost:8080"
        handler.headers["Origin"] = "http://198.51.100.20"
        handler.headers["Content-Type"] = "application/json"
        handler.headers["X-Stellar-Archive-Request"] = "same-origin"
        handler.headers["Sec-Fetch-Site"] = "same-origin"
        self.assertTrue(self.controller.same_origin(handler))

    def test_opaque_mobile_origin_accepts_marked_same_origin_json(self):
        handler = Handler(False)
        handler.headers["Origin"] = "null"
        handler.headers["Content-Type"] = "application/json"
        handler.headers["X-Stellar-Archive-Request"] = "same-origin"
        self.assertTrue(self.controller.same_origin(handler))

    @mock.patch("stellar_archive_maintenance.subprocess.Popen")
    def test_restart_uses_only_configured_service(self, popen):
        result = self.controller.restart_service(Handler())
        self.assertTrue(result["success"])
        self.assertEqual(result["service"], "stargate-test.service")
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-3:], ["systemctl", "restart", "stargate-test.service"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @mock.patch("stellar_archive_maintenance.subprocess.Popen")
    def test_restart_rejects_unsafe_service_name(self, popen):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        config["restart_service"] = "stargate.service; reboot"
        self.config_path.write_text(json.dumps(config), encoding="utf-8")
        result = self.controller.restart_service(Handler())
        self.assertFalse(result["success"])
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
