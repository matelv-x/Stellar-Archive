#!/usr/bin/env python3

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "payload" / "stellar-archive"


class CatalogueContentTests(unittest.TestCase):
    def test_public_manifest_matches_packaged_catalogue(self):
        manifest = json.loads((ROOT / "catalogue" / "manifest.json").read_text(encoding="utf-8"))
        worlds = json.loads((ARCHIVE / "data/worlds.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["revision"], worlds["catalogueRevision"])
        records = {item["path"]: item for item in manifest["files"]}
        self.assertEqual(len(records), len(manifest["files"]))
        for required in ("data/worlds.json", "data/worlds.js", "world-styles.css", "thumbnail-sprite.css"):
            self.assertIn(required, records)
        for world in worlds["worlds"]:
            self.assertIn("assets/" + world["visualAsset"], records)
        for relative, record in records.items():
            path = ARCHIVE / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(path.stat().st_size, record["size"], relative)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), record["sha256"], relative)


if __name__ == "__main__":
    unittest.main()
