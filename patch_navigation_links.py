#!/usr/bin/env python3
"""Add the Stand-alone Stellar Archive link to existing SG1_v4 navigation."""

import argparse
import re
from pathlib import Path


MARKER = "STELLAR_ARCHIVE_STANDALONE_LINK"
ORIGINAL_LINK = '''          <!-- STELLAR_ARCHIVE_STANDALONE_LINK -->
          <li class="nav-item stellar-archive-standalone-link">
            <a class="nav-link" href="/stellar-archive/">Stellar Archive</a>
          </li>
'''
RETRO_LINK = '''        <a href="/stellar-archive/" class="stellar-archive-standalone-link">Stellar Archive</a><!-- STELLAR_ARCHIVE_STANDALONE_LINK -->
'''


def patch_original(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return False
    help_item = re.compile(
        r'(?P<item>\s*<li\b[^>]*class=["\'][^"\']*nav-item[^"\']*["\'][^>]*>\s*'
        r'<a\b[^>]*href=["\']/?help\.htm["\'][^>]*>.*?</a>\s*</li>)',
        re.I | re.S,
    )
    match = help_item.search(text)
    if match:
        text = text[:match.start()] + "\n" + ORIGINAL_LINK + text[match.start():]
    else:
        navbar = re.search(r'(<ul\b[^>]*class=["\'][^"\']*navbar-nav[^"\']*["\'][^>]*>)(.*?)(</ul>)', text, re.I | re.S)
        if not navbar:
            return False
        text = text[:navbar.end(2)] + "\n" + ORIGINAL_LINK + text[navbar.end(2):]
    path.write_text(text, encoding="utf-8")
    return True


def patch_retro(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER in text:
        return False
    address_link = re.search(
        r'(?P<link><a\s+\$\{isActive\(["\']/retro/address_book\.html["\']\)\}>\s*Address Book\s*</a>)',
        text,
        re.I,
    )
    if not address_link:
        return False
    text = text[:address_link.end()] + "\n" + RETRO_LINK.rstrip("\n") + text[address_link.end():]
    path.write_text(text, encoding="utf-8")
    return True


def remove_link(path, kind):
    text = path.read_text(encoding="utf-8", errors="replace")
    if kind == "retro":
        updated = re.sub(
            r'\s*<a\b[^>]*class=["\'][^"\']*stellar-archive-standalone-link[^"\']*["\'][^>]*>.*?</a>\s*'
            r'<!--\s*STELLAR_ARCHIVE_STANDALONE_LINK\s*-->\s*',
            "\n",
            text,
            flags=re.I | re.S,
        )
    else:
        updated = text.replace("\n" + ORIGINAL_LINK, "\n").replace(ORIGINAL_LINK, "")
    if updated == text and MARKER in text:
        raise SystemExit(f"could not safely remove {kind} navigation marker from {path}")
    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("original", "retro"), required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    if not args.file.is_file():
        raise SystemExit(f"navigation file missing: {args.file}")
    if args.remove:
        changed = remove_link(args.file, args.kind)
        print(f"Stellar Archive link removed: {args.file}")
        return
    changed = patch_original(args.file) if args.kind == "original" else patch_retro(args.file)
    if not changed and MARKER not in args.file.read_text(encoding="utf-8", errors="replace"):
        raise SystemExit(f"could not locate {args.kind} navigation in {args.file}")
    print(f"Stellar Archive link ready: {args.file}")


if __name__ == "__main__":
    main()
