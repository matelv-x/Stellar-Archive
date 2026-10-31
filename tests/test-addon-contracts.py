#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AddonContractTests(unittest.TestCase):
    def registry(self):
        return json.loads((ROOT / "matelv_addons.json").read_text(encoding="utf-8"))["addons"]

    def test_every_registered_addon_requires_surgical_uninstall_v2(self):
        addons = self.registry()
        self.assertEqual(len(addons), 15)
        for addon in addons:
            with self.subTest(addon=addon["id"]):
                self.assertEqual(addon.get("maintenance_contract"), 1)
                self.assertEqual(addon.get("uninstall_contract"), 2)
                self.assertIsInstance(addon.get("uninstall"), dict)
                self.assertTrue(addon["uninstall"].get("argv"))

    def test_lamp_mode_detection_uses_only_owned_markers(self):
        lamp = next(addon for addon in self.registry() if addon["id"] == "lamp-mode")
        self.assertEqual(lamp["detect"], {"any": [
            {"path": "web/js/debug.js", "contains": "Lamp Mode controls"},
            {"path": "classes/web_server.py", "contains": "# LAMP_MODE_WEB_START"},
        ]})

    def test_fan113_home_has_surgical_static_integration(self):
        addon = next(addon for addon in self.registry() if addon["id"] == "fan113-home")
        self.assertTrue(addon["restart_required"])
        self.assertEqual(addon["repository"], "matelv-x/FAN113-Home")
        self.assertIn("web/js/home_redirect.js", addon["archive_integration_files"])

    def test_alarm_clock_declares_every_archive_navigation_surface(self):
        addon = next(addon for addon in self.registry() if addon["id"] == "alarm-clock")
        self.assertIn("web/address_book.htm", addon["archive_integration_files"])
        self.assertIn("web/retro/js/navigation.js", addon["archive_integration_files"])

    def test_lan_discovery_declares_shared_status_manager(self):
        addon = next(addon for addon in self.registry() if addon["id"] == "lan-discovery")
        self.assertIn("classes/stargate_address_manager.py", addon["archive_integration_files"])

    def test_visual_volume_meter_preserves_shared_debug_page(self):
        addon = next(addon for addon in self.registry() if addon["id"] == "visual-volume-meter")
        self.assertFalse(addon["restart_required"])
        self.assertEqual(addon["archive_integration_files"], ["web/debug.htm"])
        self.assertEqual(addon["detect"]["all"][0]["contains"], "BEGIN STARGATE VISUAL VOLUME METER ADD-ON")


if __name__ == "__main__":
    unittest.main()
