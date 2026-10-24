#!/usr/bin/env python3
"""Compile Python sources in memory without creating __pycache__ files."""

import sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: validate_python_sources.py FILE [FILE ...]")
    for name in sys.argv[1:]:
        path = Path(name)
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    main()
