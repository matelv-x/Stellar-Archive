#!/usr/bin/env python3
"""Adopt bounded UI changes declared by already managed Matelv-x add-ons."""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


SNAPSHOTS = {
    "classes/web_server.py": "web_server.py",
    "web/address_book.htm": "address_book.htm",
    "web/retro/address_book.html": "retro-address_book.html",
    "web/retro/js/navigation.js": "retro-navigation.js",
    "web/js/address_book.js": "address_book.js",
}
OVERLAY_FILES = {"classes/web_server.py", "web/retro/js/navigation.js"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rule_matches(rule, root):
    relative = str(rule.get("path", ""))
    if not relative or relative.startswith("/") or ".." in Path(relative).parts:
        return False
    path = root / relative
    if not path.exists():
        return False
    contains = rule.get("contains")
    if contains is None:
        return True
    return path.is_file() and str(contains) in path.read_text(encoding="utf-8", errors="replace")


def installed(manifest, root):
    detection = manifest.get("detect", {})
    all_rules = detection.get("all", [])
    any_rules = detection.get("any", [])
    return bool(all_rules or any_rules) and (not all_rules or all(rule_matches(rule, root) for rule in all_rules)) and (
        not any_rules or any(rule_matches(rule, root) for rule in any_rules)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--managed", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--overlay", type=Path)
    args = parser.parse_args()

    target = args.target.resolve()
    root = target.parent
    if not args.state.is_file() or not args.registry.is_file() or not args.managed.is_dir():
        return
    state = json.loads(args.state.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    manifests = {item.get("id"): item for item in registry.get("addons", []) if isinstance(item, dict)}
    allowed = set()
    for addon_id in state:
        manifest = manifests.get(addon_id)
        if not manifest or not installed(manifest, root):
            continue
        for relative in manifest.get("archive_integration_files", []):
            if relative in SNAPSHOTS:
                allowed.add(relative)

    if args.overlay:
        overlay = args.overlay.resolve()
        state_root = args.managed.resolve().parent
        if overlay.parent != state_root:
            raise ValueError("unsafe add-on overlay path")
        if overlay.exists():
            shutil.rmtree(str(overlay))
        overlay.mkdir()
        for relative in sorted(allowed & OVERLAY_FILES):
            source = root / relative
            if not source.is_file():
                continue
            destination = overlay / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(source), str(destination))
            print("Preserved installed add-on overlay: {}".format(relative))

    for relative in sorted(allowed):
        source = root / relative
        snapshot = args.managed / SNAPSHOTS[relative]
        if not source.is_file() or not snapshot.is_file() or digest(source) == digest(snapshot):
            continue
        temporary = snapshot.with_name(snapshot.name + ".tmp")
        shutil.copyfile(str(source), str(temporary))
        os.replace(str(temporary), str(snapshot))
        print("Accepted installed add-on integration: {}".format(relative))


if __name__ == "__main__":
    main()
