#!/usr/bin/env python3
"""Build Stellar Archive navigation from the SG1_v4 pages present at install time."""

import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path


BASE_LABELS = {"HOME", "ADDRESS BOOK", "SYMBOLS", "ADMIN", "HELP"}


class OriginalNavParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_nav = False
        self.anchor = None
        self.items = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "nav":
            self.in_nav = True
        if self.in_nav and tag == "a":
            classes = set(attributes.get("class", "").split())
            if "navbar-brand" in classes or "nav-link" in classes:
                self.anchor = {"attrs": attributes, "text": []}

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            label = " ".join("".join(self.anchor["text"]).split())
            self.items.append((label, self.anchor["attrs"]))
            self.anchor = None
        if tag == "nav":
            self.in_nav = False


def normalized_href(href, prefix="/"):
    href = html.unescape((href or "").strip())
    if not href or href == "#" or href.lower().startswith("javascript:"):
        return None
    if href.startswith(("http://", "https://", "/")):
        return href
    return f"{prefix.rstrip('/')}/{href.lstrip('/')}"


def make_item(label, href=None, action=None, addon=False, title=None):
    item = {"label": label.upper()}
    if href:
        item["href"] = href
    if action:
        item["action"] = action
    if addon:
        item["addon"] = True
    if title:
        item["title"] = title
    return item


def admin_item(target, retro=False):
    candidates = [
        ("Testing / Debug", "/debug.htm"),
        ("Sound Board", "/sound_board.htm"),
        ("Connection History", "/connection_history.htm"),
        ("Configuration", "/config.htm"),
        ("Visuals", "/retro/visual_settings.html"),
        ("System Information", "/retro/info.html" if retro else "/info.htm"),
    ]
    children = [make_item(label, href=href) for label, href in candidates if installed_link_exists(target, href)]
    children.extend([
        make_item("Restart Software", action="restart"),
        make_item("Reboot Raspberry Pi", action="reboot"),
        make_item("Shutdown Raspberry Pi", action="shutdown"),
    ])
    return {"label": "ADMIN", "children": children}


def installed_link_exists(target, href):
    if not href or href.startswith(("http://", "https://", "#")):
        return True
    local_path = href.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    return bool(local_path) and (target / local_path).is_file()


def original_items(target):
    source = target / "address_book.htm"
    if not source.is_file():
        return []
    parser = OriginalNavParser()
    parser.feed(source.read_text(encoding="utf-8", errors="replace"))
    result = []
    for label, attrs in parser.items:
        upper = label.upper()
        if not label or upper in {"STARGATE COMMAND", "ADDRESS BOOK"}:
            continue
        href = normalized_href(attrs.get("href"))
        if upper == "HOME":
            href = "/index.htm"
        elif upper == "ADMIN":
            result.append(admin_item(target, retro=False))
            continue
        if href and installed_link_exists(target, href):
            result.append(make_item(label, href=href, addon=upper not in BASE_LABELS))
    return result


def retro_items(target):
    navigation = target / "retro/js/navigation.js"
    if not navigation.is_file():
        return []
    text = navigation.read_text(encoding="utf-8", errors="replace")
    result = [
        make_item("Home", href="/retro/dial.html"),
        make_item("Symbols", href="/retro/symbol_overview.html"),
        admin_item(target, retro=True),
    ]
    literal_links = re.findall(r'<a\s+href=["\']([^"\']+)["\'][^>]*>\s*([^<${}]+?)\s*</a>', text, re.I | re.S)
    for href, label in literal_links:
        label = " ".join(label.split())
        upper = label.upper()
        if not label or upper in {"HOME", "ADDRESS BOOK", "SYMBOLS"}:
            continue
        resolved = normalized_href(href, "/retro")
        if resolved and installed_link_exists(target, resolved):
            result.append(make_item(label, href=resolved, addon=upper not in BASE_LABELS))
    return result


def deduplicate(items):
    result = []
    seen = set()
    for item in items:
        key = item["label"].upper()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("original", "retro", "both", "standalone"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    originals = original_items(args.target)
    retros = retro_items(args.target)
    if args.mode == "original":
        items = originals
    elif args.mode == "retro":
        items = retros
    else:
        items = deduplicate(originals + retros)
    has_extended_retro = (
        (args.target / "retro/dial.html").is_file()
        and (args.target / "retro/dial9.html").is_file()
    )
    if args.mode == "retro":
        dial_target = "retro"
    elif args.mode == "original":
        dial_target = "original"
    else:
        dial_target = "retro" if has_extended_retro else "original"
    payload = {"mode": args.mode, "dialTarget": dial_target, "items": items}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.STELLAR_ARCHIVE_NAV=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print("Detected Archive header buttons: " + (", ".join(item["label"] for item in items) or "none"))


if __name__ == "__main__":
    main()
