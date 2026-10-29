#!/usr/bin/env python3
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AddonContractTests(unittest.TestCase):
    def test_every_registered_addon_requires_surgical_uninstall_v2(self):
        payload = json.loads((ROOT / "matelv_addons.json").read_text(encoding="utf-8"))
        addons = payload["addons"]
        self.assertEqual(len(addons), 13)
        for addon in addons:
            with self.subTest(addon=addon["id"]):
                self.assertEqual(addon.get("maintenance_contract"), 1)
                self.assertEqual(addon.get("uninstall_contract"), 2)
                self.assertIsInstance(addon.get("uninstall"), dict)
                self.assertTrue(addon["uninstall"].get("argv"))


if __name__ == "__main__":
    unittest.main()
