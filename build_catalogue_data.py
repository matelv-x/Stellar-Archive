#!/usr/bin/env python3
"""Generate the browser catalogue from the reviewed JSON source."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "payload" / "stellar-archive" / "data" / "worlds.json"
OUTPUT = SOURCE.with_suffix(".js")


def main() -> None:
    archive = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUTPUT.write_text(
        "window.STELLAR_ARCHIVE_DATA="
        + json.dumps(archive, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print("records={} revision={}".format(len(archive.get("worlds", [])), archive.get("catalogueRevision", "")))
    print(OUTPUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
