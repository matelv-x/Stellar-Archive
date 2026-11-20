#!/usr/bin/env python3
"""Build the public, content-only Stellar Archive update manifest."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "payload" / "stellar-archive"
WORLDS = ARCHIVE / "data" / "worlds.json"
OUTPUT = ROOT / "catalogue" / "manifest.json"
SPRITE_RE = re.compile(r"assets/optimized/([0-9a-f]{64}\.webp)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    archive = json.loads(WORLDS.read_text(encoding="utf-8"))
    revision = str(archive.get("catalogueRevision", "")).strip()
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,64}", revision):
        raise SystemExit("worlds.json has no safe catalogueRevision")

    sprite_css = (ARCHIVE / "thumbnail-sprite.css").read_text(encoding="utf-8")
    sprite_match = SPRITE_RE.search(sprite_css)
    if not sprite_match:
        raise SystemExit("thumbnail-sprite.css has no content-addressed sprite")

    targets = {
        "data/worlds.json",
        "data/worlds.js",
        "world-styles.css",
        "thumbnail-sprite.css",
        "assets/optimized/{}".format(sprite_match.group(1)),
    }
    for world in archive.get("worlds", []):
        asset = str(world.get("visualAsset", ""))
        if not re.fullmatch(r"archive-(?:approved|concept)-[0-9a-z-]+-v[0-9]+\.png", asset):
            raise SystemExit("unsafe or missing visualAsset for {}".format(world.get("id", "unknown")))
        targets.add("assets/{}".format(asset))

    files = []
    for target in sorted(targets):
        path = ARCHIVE / target
        if not path.is_file():
            raise SystemExit("missing catalogue file: {}".format(path))
        files.append({
            "path": target,
            "source": "payload/stellar-archive/{}".format(target),
            "sha256": sha256(path),
            "size": path.stat().st_size,
        })

    generated_date = str(archive.get("generatedAt", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", generated_date):
        raise SystemExit("worlds.json has no safe generatedAt date")

    payload = {
        "schemaVersion": 1,
        "revision": revision,
        "generatedAt": generated_date + "T00:00:00Z",
        "files": files,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("revision={} files={} bytes={}".format(revision, len(files), sum(item["size"] for item in files)))
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
