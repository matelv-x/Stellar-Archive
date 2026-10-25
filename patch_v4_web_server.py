#!/usr/bin/env python3
import argparse
from pathlib import Path

IMPORT_ANCHOR = "from http.server import SimpleHTTPRequestHandler"
GET_ANCHOR = "            request_path, get_vars = self.parse_get_vars()"
POST_ANCHOR = "            if self.path == '/do/shutdown':"
IMPORT_BLOCK = """# STELLAR_ARCHIVE_MAINTENANCE_IMPORT_BEGIN
from stellar_archive_maintenance import get_maintenance_controller
# STELLAR_ARCHIVE_MAINTENANCE_IMPORT_END"""
GET_BLOCK = """            # STELLAR_ARCHIVE_MAINTENANCE_GET_BEGIN
            if request_path == "/get/stellar_archive_update":
                self.send_json_response(get_maintenance_controller().check())
                return
            if request_path == "/get/stellar_archive_addons":
                self.send_json_response(get_maintenance_controller().list_addons())
                return
            # STELLAR_ARCHIVE_MAINTENANCE_GET_END

"""
POST_BLOCK = """            # STELLAR_ARCHIVE_MAINTENANCE_POST_BEGIN
            if self.path == '/do/stellar_archive_update':
                self.send_json_response(get_maintenance_controller().start_update(self))
                return
            if self.path == '/do/stellar_archive_uninstall':
                self.send_json_response(get_maintenance_controller().start_uninstall(self))
                return
            if self.path == '/do/stellar_archive_addon_update':
                self.send_json_response(get_maintenance_controller().start_addon_update(self))
                return
            if self.path == '/do/stellar_archive_addon_uninstall':
                self.send_json_response(get_maintenance_controller().start_addon_uninstall(self))
                return
            # STELLAR_ARCHIVE_MAINTENANCE_POST_END

"""


def patch(source):
    if "STELLAR_ARCHIVE_MAINTENANCE_" in source:
        raise ValueError("web_server.py already contains Stellar Archive maintenance markers")
    for anchor in (IMPORT_ANCHOR, GET_ANCHOR, POST_ANCHOR):
        if source.count(anchor) != 1:
            raise ValueError("expected exactly one anchor: {}".format(anchor))
    source = source.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + "\n" + IMPORT_BLOCK)
    source = source.replace(GET_ANCHOR, GET_ANCHOR + "\n\n" + GET_BLOCK.rstrip())
    source = source.replace(POST_ANCHOR, POST_BLOCK + POST_ANCHOR)
    return source


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
