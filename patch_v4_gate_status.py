#!/usr/bin/env python3
"""Add fail-closed central-directory freshness to SG1_v4 address books."""

import argparse
import re
from pathlib import Path


WEB_MARKER = "STELLAR_ARCHIVE_GATE_STATUS"
WEB_IMPORT_ANCHOR = "from http.server import SimpleHTTPRequestHandler"
WEB_DATA_ANCHOR = "                data['galaxy_path'] = self.stargate.galaxy_path"
WEB_IMPORT = """# STELLAR_ARCHIVE_GATE_STATUS_IMPORT_BEGIN
from datetime import datetime as stellar_archive_datetime
# STELLAR_ARCHIVE_GATE_STATUS_IMPORT_END"""
WEB_DATA = """                # STELLAR_ARCHIVE_GATE_STATUS_BEGIN
                last_success = self.stargate.cfg.get('fan_gate_last_update')
                try:
                    refresh_seconds = max(
                        60.0,
                        float(self.stargate.cfg.get('fan_gate_refresh_interval')) * 60.0
                    )
                except (TypeError, ValueError):
                    refresh_seconds = 1800.0
                age_seconds = None
                try:
                    age_seconds = (
                        stellar_archive_datetime.now()
                        - stellar_archive_datetime.fromisoformat(str(last_success))
                    ).total_seconds()
                except (TypeError, ValueError):
                    pass
                refresh_enabled = bool(self.stargate.cfg.get('fan_gate_refresh_enable'))
                data['local_address'] = self.stargate.addr_manager.get_book().get_local_address()
                data['status_freshness'] = {
                    'source': 'central_directory',
                    'last_success': str(last_success) if last_success else None,
                    'age_seconds': round(age_seconds, 1) if age_seconds is not None else None,
                    'stale': (
                        not refresh_enabled
                        or age_seconds is None
                        or age_seconds < -60
                        or age_seconds > refresh_seconds + 120
                    )
                }
                # STELLAR_ARCHIVE_GATE_STATUS_END"""

JS_MARKER = "STELLAR_ARCHIVE_GATE_STATUS"
JS_HELPER = """// STELLAR_ARCHIVE_GATE_STATUS START
var stellarArchiveLocalAddress = [];
var stellarArchiveStatusFreshness = {stale: true};

function stellarArchiveAddressesMatch(first, second) {
    return Array.isArray(first) && Array.isArray(second) && first.join('-') === second.join('-');
}

function stellarArchiveGateIsOnline(value) {
    if (stellarArchiveAddressesMatch(value.gate_address, stellarArchiveLocalAddress)) return true;
    if (value.type === 'lan') return String(value.is_gate_online) === '1';
    if (stellarArchiveStatusFreshness.stale !== false) return false;
    if (value.type === 'standard') return true;
    if (value.type === 'fan') return String(value.is_gate_online) === '1';
    return false;
}
// STELLAR_ARCHIVE_GATE_STATUS END

"""


def patch_web_server(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if WEB_MARKER in text:
        return False
    if text.count(WEB_IMPORT_ANCHOR) != 1:
        raise ValueError("expected exactly one SG1_v4 web-server import anchor")
    if text.count(WEB_DATA_ANCHOR) != 1:
        raise ValueError("expected exactly one SG1_v4 address-book response anchor")
    text = text.replace(WEB_IMPORT_ANCHOR, WEB_IMPORT_ANCHOR + "\n" + WEB_IMPORT, 1)
    text = text.replace(WEB_DATA_ANCHOR, WEB_DATA_ANCHOR + "\n" + WEB_DATA, 1)
    path.write_text(text, encoding="utf-8")
    return True


def patch_address_js(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if JS_MARKER in text:
        return False
    galaxy_anchor = "          galaxy_path = json['galaxy_path']"
    if text.count(galaxy_anchor) != 1:
        raise ValueError("expected exactly one SG1_v4 address-book JSON anchor")
    text = text.replace(
        galaxy_anchor,
        galaxy_anchor
        + "\n          stellarArchiveLocalAddress = json['local_address'] || []"
        + "\n          stellarArchiveStatusFreshness = json['status_freshness'] || {stale: true}",
        1,
    )
    status_pattern = re.compile(
        r"        is_gate_online = value\.is_gate_online\s*\n"
        r"        if \(is_gate_online == 0\)\{\s*\n"
        r"\s*is_gate_online = \"\"\s*\n"
        r"        \} else \{is_gate_online = \"Online\"\}"
    )
    text, count = status_pattern.subn(
        '        is_gate_online = stellarArchiveGateIsOnline(value) ? "Online" : ""',
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("expected exactly one SG1_v4 online-status block")
    path.write_text(JS_HELPER + text, encoding="utf-8")
    return True


def patch_html(path):
    if not path or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    updated, count = re.subn(
        r'src=["\']/js/address_book\.js(?:\?[^"\']*)?["\']',
        'src="/js/address_book.js?v=stellar-archive-1.5.14-status"',
        text,
        count=1,
    )
    if count:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-server", required=True, type=Path)
    parser.add_argument("--address-js", required=True, type=Path)
    parser.add_argument("--html-file", type=Path)
    args = parser.parse_args()
    for path in (args.web_server, args.address_js):
        if not path.is_file():
            raise SystemExit("required SG1_v4 file missing: {}".format(path))
    patch_web_server(args.web_server)
    patch_address_js(args.address_js)
    patch_html(args.html_file)
    print("Fail-closed gate status ready: {}".format(args.address_js))


if __name__ == "__main__":
    main()
