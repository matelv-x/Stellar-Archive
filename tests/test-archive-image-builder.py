#!/usr/bin/env python3

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import archive_image_builder as builder


class ArchiveImageBuilderTests(unittest.TestCase):
    def setUp(self):
        self.archive = {
            "schemaVersion": 2,
            "generatedAt": "2026-10-30",
            "count": 2,
            "worlds": [
                {"id": "fan-001-alpha", "name": "Alpha", "category": "fan", "storedAddress": [1, 2, 3, 4, 5, 6]},
                {"id": "lan-001-seed", "name": "Seed", "category": "lan", "storedAddress": [7, 8, 9, 10, 11, 12, 13, 14]},
            ],
        }

    def test_detects_new_alias_and_changed_address_without_private_fields(self):
        payload = {"address_book": {
            "same": {"name": "Alpha", "type": "fan", "gate_address": [1, 2, 3, 4, 5, 6], "ip": "192.0.2.1"},
            "alias": {"name": "Alpha Two", "type": "fan", "gate_address": [1, 2, 3, 4, 5, 6], "ip": "192.0.2.2"},
            "changed": {"name": "Alpha", "type": "fan", "gate_address": [2, 3, 4, 5, 6, 7]},
            "new": {"name": "Beta", "type": "fan", "gate_address": [3, 4, 5, 6, 7, 8]},
        }}
        candidates = builder.detect_candidates(payload, self.archive)
        self.assertEqual([item["reason"] for item in candidates], ["alias-or-renamed", "address-changed", "new-address"])
        self.assertNotIn("192.0.2.2", json.dumps(candidates))
        self.assertEqual(candidates[0]["existingMatches"], ["Alpha"])

    def test_browser_export_is_accepted_and_offline_review_is_safe(self):
        pending = {"destinations": [{"name": "Beta", "category": "fan", "storedAddress": [3, 4, 5, 6, 7, 8], "reason": "new-address", "existingMatches": []}]}
        candidate = builder.detect_candidates(pending, self.archive)[0]
        record = builder.research_record(candidate, offline=True)
        self.assertEqual(record["approval"], {"generation": None, "archive": None})
        self.assertIn("No text", record["prompt"])
        self.assertEqual(record["evidenceLevel"], "fictional-placeholder")

    def test_apply_requires_approval_and_preserves_origin_convention(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_root = root / "payload" / "stellar-archive"
            data = archive_root / "data"
            assets = archive_root / "assets"
            data.mkdir(parents=True)
            assets.mkdir(parents=True)
            worlds_path = data / "worlds.json"
            builder.write_json(worlds_path, self.archive)
            (archive_root / "world-styles.css").write_text("/* existing */\n", encoding="utf-8")
            review_path = root / "review.json"
            image_path = root / "images" / "beta.png"
            image_path.parent.mkdir()
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            review = {
                "schemaVersion": 1,
                "destinations": [{
                    "name": "Beta", "category": "fan", "storedAddress": [3, 4, 5, 6, 7, 8], "reason": "new-address", "existingMatches": [],
                    "sources": [], "visualMode": "planet", "environment": "PLANETARY / ARTIST CONCEPT", "classification": "ARCHIVE WORLD",
                    "description": "Independent concept.", "evidenceLevel": "fictional-placeholder", "prompt": "prompt",
                    "approval": {"generation": "2026-10-31T00:00:00+00:00", "archive": "2026-10-31T00:01:00+00:00"},
                    "imagePath": "images/beta.png",
                }],
            }
            builder.write_json(review_path, review)
            args = argparse.Namespace(review=str(review_path), id="beta", worlds=str(worlds_path), no_sprite=True)
            with mock.patch.object(builder, "ARCHIVE", archive_root), mock.patch.object(builder, "ROOT", root):
                builder.command_apply(args)
            updated = builder.read_json(worlds_path)
            world = next(world for world in updated["worlds"] if world["name"] == "Beta")
            self.assertEqual(world["storedAddress"], [3, 4, 5, 6, 7, 8])
            self.assertEqual(world["fullAddress"], [3, 4, 5, 6, 7, 8, 1])
            self.assertEqual(world["pointOfOrigin"], 1)
            self.assertTrue((assets / world["visualAsset"]).is_file())
            self.assertIn(world["id"], (archive_root / "world-styles.css").read_text(encoding="utf-8"))
            self.assertTrue((data / "worlds.js").read_text(encoding="utf-8").startswith("window.STELLAR_ARCHIVE_DATA="))


if __name__ == "__main__":
    unittest.main()
