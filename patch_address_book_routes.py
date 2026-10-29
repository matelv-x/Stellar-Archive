#!/usr/bin/env python3
"""Route extended SG1_v4 address-book entries directly to Retro dial9."""

import argparse
import re
from pathlib import Path


MARKER = "STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE"
HELPER = """// STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE START
function stellarArchiveDialUrl(addressString) {
    const symbolCount = String(addressString).split("-").filter(Boolean).length;
    const page = symbolCount > 6 ? "/retro/dial9.html" : "/retro/dial.html";
    return page + "?address=" + encodeURIComponent(addressString);
}
// STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE END

"""


def patch(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return False
    embedded_pattern = (
        r"window\.location\s*=\s*\\'/?(?:stargate/dial|index\.htm)\?address='"
        r"\s*\+\s*address_string"
    )
    updated, count = re.subn(
        embedded_pattern,
        "window.location = \\'' + stellarArchiveDialUrl(address_string)",
        text,
        count=1,
    )
    if count:
        path.write_text(HELPER + updated, encoding="utf-8")
        return True
    patterns = (
        r"window\.location\s*=\s*'/?stargate/dial\?address='\s*\+\s*address_string",
        r"window\.location\s*=\s*'/?index\.htm\?address='\s*\+\s*address_string",
    )
    for pattern in patterns:
        updated, count = re.subn(
            pattern,
            "window.location = stellarArchiveDialUrl(address_string)",
            text,
            count=1,
        )
        if count:
            path.write_text(HELPER + updated, encoding="utf-8")
            return True
    raise SystemExit(f"could not locate SG1_v4 address-book route in {path}")


def patch_html(path):
    if not path or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    updated, count = re.subn(
        r'src=["\']/js/address_book\.js(?:\?[^"\']*)?["\']',
        'src="/js/address_book.js?v=stellar-archive-1.5.19-extended-route"',
        text,
        count=1,
    )
    if count:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--html-file", type=Path)
    args = parser.parse_args()
    if not args.file.is_file():
        raise SystemExit(f"address-book script missing: {args.file}")
    patch(args.file)
    patch_html(args.html_file)
    print(f"Extended address routing ready: {args.file}")


if __name__ == "__main__":
    main()
