#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class AdoptManagedAddonChangesTests(unittest.TestCase):
    def test_adopts_only_declared_files_for_detected_installed_addon(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sg1_v4"
            web = root / "web"
            managed = web / ".stellar-archive-addon" / "managed"
            (web / "retro" / "js").mkdir(parents=True)
            managed.mkdir(parents=True)
            (web / "retro" / "js" / "retro_visuals.js").write_text("active", encoding="utf-8")
            current = web / "retro" / "js" / "navigation.js"
            snapshot = managed / "retro-navigation.js"
            current.write_text("Visuals", encoding="utf-8")
            snapshot.write_text("Before", encoding="utf-8")
            unrelated = web / "address_book.htm"
            unrelated_snapshot = managed / "address_book.htm"
            unrelated.write_text("Unrelated edit", encoding="utf-8")
            unrelated_snapshot.write_text("Original", encoding="utf-8")
            backend = root / "classes" / "web_server.py"
            backend.parent.mkdir(parents=True)
            backend.write_text("Retro Visuals backend", encoding="utf-8")
            backend_snapshot = managed / "web_server.py"
            backend_snapshot.write_text("Archive backend", encoding="utf-8")
            address_manager = root / "classes" / "stargate_address_manager.py"
            address_manager.write_text("LAN status integration", encoding="utf-8")
            address_manager_snapshot = managed / "stargate_address_manager.py"
            address_manager_snapshot.write_text("Archive status manager", encoding="utf-8")
            state = root / "state.json"
            state.write_text(json.dumps({"retro-visuals": {"revision": "a" * 40}}), encoding="utf-8")
            registry = root / "registry.json"
            registry.write_text(json.dumps({"addons": [{
                "id": "retro-visuals",
                "detect": {"all": [{"path": "web/retro/js/retro_visuals.js"}]},
                "archive_integration_files": [
                    "classes/web_server.py",
                    "classes/stargate_address_manager.py",
                    "web/retro/js/navigation.js",
                ],
            }]}), encoding="utf-8")
            script = Path(__file__).resolve().parent.parent / "adopt_managed_addon_changes.py"
            overlay = managed.parent / "addon-overlay"
            subprocess.run([
                "python3", str(script), "--target", str(web), "--managed", str(managed),
                "--state", str(state), "--registry", str(registry), "--overlay", str(overlay),
            ], check=True)
            self.assertEqual(snapshot.read_text(encoding="utf-8"), "Visuals")
            self.assertEqual(backend_snapshot.read_text(encoding="utf-8"), "Retro Visuals backend")
            self.assertEqual(address_manager_snapshot.read_text(encoding="utf-8"), "LAN status integration")
            self.assertEqual(unrelated_snapshot.read_text(encoding="utf-8"), "Original")
            self.assertEqual((overlay / "classes" / "web_server.py").read_text(encoding="utf-8"), "Retro Visuals backend")
            self.assertEqual((overlay / "web" / "retro" / "js" / "navigation.js").read_text(encoding="utf-8"), "Visuals")


if __name__ == "__main__":
    unittest.main()
