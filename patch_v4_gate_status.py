#!/usr/bin/env python3
"""Add fail-closed central-directory freshness to SG1_v4 address books."""

import argparse
import re
from pathlib import Path


WEB_MARKER = "STELLAR_ARCHIVE_GATE_STATUS"
MANAGER_MARKER = "STELLAR_ARCHIVE_DIRECTORY_RETRY"
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

MANAGER_STATE = """        # STELLAR_ARCHIVE_DIRECTORY_RETRY_BEGIN
        self._fan_directory_retry_delay_minutes = 0
        self._fan_directory_retry_at = None
        stargate.app.schedule.every(1).minutes.do(self.retry_fan_gates_from_api)
        # STELLAR_ARCHIVE_DIRECTORY_RETRY_END
"""

MANAGER_METHODS = '''    def _schedule_fan_directory_retry(self, error_name):
        """Schedule a bounded retry without changing the normal refresh interval."""
        previous_delay = getattr(self, '_fan_directory_retry_delay_minutes', 0)
        delay = 2 if previous_delay <= 0 else min(previous_delay * 2, 15)
        self._fan_directory_retry_delay_minutes = delay
        self._fan_directory_retry_at = datetime.now() + timedelta(minutes=delay)
        self._fan_directory_error = error_name
        self.log.log(
            "Fan Gate Update: retry scheduled in " + str(delay) + " minute(s)"
        )

    def retry_fan_gates_from_api(self):
        """Run a due retry; the one-minute scheduler only checks the deadline."""
        retry_at = getattr(self, '_fan_directory_retry_at', None)
        if retry_at is None or datetime.now() < retry_at:
            return self.fan_gates
        self._fan_directory_retry_at = None
        return self.update_fan_gates_from_api()

    def update_fan_gates_from_api(self):
        """
        Retrieve the central fan directory and preserve cached records on failure.
        A failed refresh is retried with bounded backoff instead of waiting for the
        next full refresh interval.
        """
        self.log.log(f"Updating Fan Gates from API: {self.galaxy} Galaxy")

        if not self.stargate.net_tools.has_internet_access():
            self.log.log("Fan Gate Update: FAILED (NoInternetAccess)")
            self._schedule_fan_directory_retry('NoInternetAccess')
            return self.fan_gates

        try:
            request = requests.get(
                self.info_api_url + "/get_fan_gates.php?galaxy=" + self.galaxy_path,
                timeout=5,
            )
            request.raise_for_status()
            data = json.loads(request.text)
            if not isinstance(data, list) or not data:
                raise ValueError('Invalid directory payload')
            for record in data:
                required = ('name', 'sg_address', 'ip', 'status')
                if not isinstance(record, dict) or not all(key in record for key in required):
                    raise ValueError('Invalid directory record')
                if str(record['status']) not in ('0', '1'):
                    raise ValueError('Invalid directory status')

            for gate_config in data:
                name = gate_config['name']
                gate_address = literal_eval(gate_config['sg_address'])
                ip_address = self.net_tools.get_ip(gate_config['ip'])
                is_gate_online = gate_config['status']
                self.address_book.set_fan_gate(
                    name, gate_address, ip_address, is_gate_online
                )

            self._fan_directory_error = None
            self._fan_directory_retry_delay_minutes = 0
            self._fan_directory_retry_at = None
            self.log.log("Fan Gate Update: Success!")
            self.cfg.set('fan_gate_last_update', str(datetime.now()))
        except Exception as error:
            error_name = type(error).__name__
            self.log.log("Fan Gate Update: FAILED (" + error_name + ")")
            self._schedule_fan_directory_retry(error_name)

        return self.fan_gates

'''


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


def patch_address_manager(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if MANAGER_MARKER in text:
        return False
    import_anchor = "from datetime import datetime"
    schedule_anchor = (
        "            stargate.app.schedule.every(update_interval).minutes.do( "
        "self.update_fan_gates_from_api )"
    )
    if text.count(import_anchor) != 1:
        raise ValueError("expected exactly one SG1_v4 datetime import anchor")
    if text.count(schedule_anchor) != 1:
        raise ValueError("expected exactly one SG1_v4 fan-directory schedule anchor")
    method_pattern = re.compile(
        r"    def update_fan_gates_from_api\(self\):\n.*?"
        r"(?=    def start_lan_gate_discovery\(self\):)",
        re.DOTALL,
    )
    text, count = method_pattern.subn(MANAGER_METHODS, text, count=1)
    if count != 1:
        raise ValueError("expected exactly one SG1_v4 fan-directory update method")
    text = text.replace(import_anchor, "from datetime import datetime, timedelta", 1)
    text = text.replace(schedule_anchor, schedule_anchor + "\n\n" + MANAGER_STATE.rstrip(), 1)
    path.write_text(text, encoding="utf-8")
    return True


def patch_html(path):
    if not path or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    updated, count = re.subn(
        r'src=["\']/js/address_book\.js(?:\?[^"\']*)?["\']',
        'src="/js/address_book.js?v=stellar-archive-1.5.17-status"',
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
    parser.add_argument("--address-manager", required=True, type=Path)
    parser.add_argument("--html-file", type=Path)
    args = parser.parse_args()
    for path in (args.web_server, args.address_js, args.address_manager):
        if not path.is_file():
            raise SystemExit("required SG1_v4 file missing: {}".format(path))
    patch_web_server(args.web_server)
    patch_address_js(args.address_js)
    patch_address_manager(args.address_manager)
    patch_html(args.html_file)
    print("Fail-closed gate status ready: {}".format(args.address_js))


if __name__ == "__main__":
    main()
