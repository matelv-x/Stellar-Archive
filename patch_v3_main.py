#!/usr/bin/env python3
import argparse
from pathlib import Path

BEGIN = "# STELLAR_ARCHIVE_BRIDGE_BEGIN"
END = "# STELLAR_ARCHIVE_BRIDGE_END"
ANCHOR = "stargate = StargateSG1()"
BLOCK = """# STELLAR_ARCHIVE_BRIDGE_BEGIN
try:
    from stellar_archive_bridge import start_stellar_archive_bridge
    start_stellar_archive_bridge(stargate)
except Exception as ex:
    print('Stellar Archive bridge failed to start: {}'.format(ex))
    log('sg1.log', 'Stellar Archive bridge failed to start: {}'.format(ex))
# STELLAR_ARCHIVE_BRIDGE_END"""


def patch(source):
    if BEGIN in source or END in source:
        raise ValueError("main.py already contains a Stellar Archive bridge marker")
    if source.count(ANCHOR) != 1:
        raise ValueError("expected exactly one StargateSG1 construction anchor")
    return source.replace(ANCHOR, ANCHOR + "\n\n" + BLOCK)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(args.file)
    updated = patch(path.read_text(encoding="utf-8"))
    if not args.check:
        path.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
