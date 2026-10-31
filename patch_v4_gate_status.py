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
                data['local_address'] = self.stargate.addr_manager.get_book().get_local_address()
                data['status_freshness'] = self.stargate.addr_manager.get_fan_status_freshness()
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

MANAGER_IMPORTS = """# STELLAR_ARCHIVE_GATE_STATUS_PROBE_IMPORT_BEGIN
import concurrent.futures as stellar_archive_futures
import ipaddress as stellar_archive_ipaddress
import subprocess as stellar_archive_subprocess
import threading as stellar_archive_threading
# STELLAR_ARCHIVE_GATE_STATUS_PROBE_IMPORT_END"""

MANAGER_STATE = """        # STELLAR_ARCHIVE_DIRECTORY_RETRY_BEGIN
        self._fan_directory_retry_delay_minutes = 0
        self._fan_directory_retry_at = None
        stargate.app.schedule.every(1).minutes.do(self.retry_fan_gates_from_api)
        self._fan_status_probe_lock = stellar_archive_threading.Lock()
        self._fan_status_probe_last_success = None
        self._fan_status_probe_error = None
        stargate.app.schedule.every(5).minutes.do(self.start_fan_gate_status_probe)
        self.start_fan_gate_status_probe()
        # STELLAR_ARCHIVE_DIRECTORY_RETRY_END
"""

MANAGER_METHODS = '''    def get_fan_status_freshness(self):
        """Prefer direct Subspace reachability; retain central-directory fallback."""
        probe_last = getattr(self, '_fan_status_probe_last_success', None)
        probe_age = None
        if probe_last is not None:
            probe_age = (datetime.now() - probe_last).total_seconds()
        if probe_age is not None and -60 <= probe_age <= 420:
            return {
                'source': 'subspace_probe',
                'last_success': str(probe_last),
                'age_seconds': round(probe_age, 1),
                'stale': False,
                'last_error': getattr(self, '_fan_status_probe_error', None),
            }

        last = self.cfg.get('fan_gate_last_update')
        try:
            interval = max(60.0, float(self.cfg.get('fan_gate_refresh_interval')) * 60.0)
        except (TypeError, ValueError):
            interval = 1800.0
        age = None
        try:
            age = (datetime.now() - datetime.fromisoformat(str(last))).total_seconds()
        except (TypeError, ValueError):
            pass
        return {
            'source': 'central_directory',
            'last_success': str(last) if last else None,
            'age_seconds': round(age, 1) if age is not None else None,
            'stale': (
                not bool(self.cfg.get('fan_gate_refresh_enable'))
                or age is None
                or age < -60
                or age > interval + 120
            ),
            'last_error': (
                getattr(self, '_fan_status_probe_error', None)
                or getattr(self, '_fan_directory_error', None)
            ),
        }

    def start_fan_gate_status_probe(self):
        """Refresh cached FAN statuses without blocking the scheduler."""
        if not self._fan_status_probe_lock.acquire(blocking=False):
            return False

        def run_probe():
            try:
                self.update_fan_gate_statuses_from_subspace()
            finally:
                self._fan_status_probe_lock.release()

        stellar_archive_threading.Thread(target=run_probe, daemon=True).start()
        return True

    @staticmethod
    def _probe_fan_gate_ip(ip_value):
        """Return ICMP reachability for a private Subspace address, or None on probe error."""
        try:
            ip = stellar_archive_ipaddress.ip_address(str(ip_value))
            if ip not in stellar_archive_ipaddress.ip_network('172.30.0.0/16'):
                return None
            result = stellar_archive_subprocess.run(
                ['/bin/ping', '-c', '1', '-W', '1', str(ip)],
                stdout=stellar_archive_subprocess.DEVNULL,
                stderr=stellar_archive_subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
            return result.returncode == 0
        except (OSError, ValueError, stellar_archive_subprocess.SubprocessError):
            return None

    def update_fan_gate_statuses_from_subspace(self):
        """Probe existing FAN peers and atomically update only their online flags."""
        fan_gates = self.address_book.get_fan_gates()
        local_address = self.address_book.get_local_address()
        candidates = {
            name: gate for name, gate in fan_gates.items()
            if gate.get('gate_address') != local_address and gate.get('ip_address')
        }
        if not candidates:
            self._fan_status_probe_error = 'NoFanGates'
            return False

        results = {}
        with stellar_archive_futures.ThreadPoolExecutor(
            max_workers=min(24, len(candidates))
        ) as executor:
            futures = {
                executor.submit(self._probe_fan_gate_ip, gate.get('ip_address')): name
                for name, gate in candidates.items()
            }
            for future in stellar_archive_futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    results[futures[future]] = result

        online_count = sum(results.values())
        if not results or online_count == 0:
            self._fan_status_probe_error = 'NoReachableFanGates'
            self.log.log('Fan Gate Status Probe: FAILED (no reachable Subspace peers)')
            return False

        updated = {}
        changed = 0
        for name, gate in fan_gates.items():
            clean_gate = {key: value for key, value in gate.items() if key != 'type'}
            if name in results:
                next_status = '1' if results[name] else '0'
                if str(clean_gate.get('is_gate_online')) != next_status:
                    changed += 1
                clean_gate['is_gate_online'] = next_status
            updated[name] = clean_gate
        self.address_book.datastore.set('fan_gates', updated)
        self.fan_gates = self.address_book.get_fan_gates()
        self._fan_status_probe_last_success = datetime.now()
        self._fan_status_probe_error = None
        self.log.log(
            'Fan Gate Status Probe: Success! '
            + str(online_count) + '/' + str(len(results))
            + ' reachable; ' + str(changed) + ' status change(s)'
        )
        return True

    def _schedule_fan_directory_retry(self, error_name):
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
        updated, count = re.subn(
            r"                # STELLAR_ARCHIVE_GATE_STATUS_BEGIN\n.*?"
            r"                # STELLAR_ARCHIVE_GATE_STATUS_END",
            WEB_DATA,
            text,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise ValueError("expected exactly one SG1_v4 gate-status block")
        if updated == text:
            return False
        path.write_text(updated, encoding="utf-8")
        return True
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
    original_text = text
    import_anchor = "from datetime import datetime"
    schedule_anchor = (
        "            stargate.app.schedule.every(update_interval).minutes.do( "
        "self.update_fan_gates_from_api )"
    )
    if "STELLAR_ARCHIVE_GATE_STATUS_PROBE_IMPORT_BEGIN" not in text:
        json_anchor = "import json"
        if text.count(json_anchor) != 1:
            raise ValueError("expected exactly one SG1_v4 json import anchor")
        text = text.replace(json_anchor, json_anchor + "\n" + MANAGER_IMPORTS, 1)
    if MANAGER_MARKER in text:
        text, state_count = re.subn(
            r"        # STELLAR_ARCHIVE_DIRECTORY_RETRY_BEGIN\n.*?"
            r"        # STELLAR_ARCHIVE_DIRECTORY_RETRY_END",
            MANAGER_STATE.rstrip(),
            text,
            count=1,
            flags=re.DOTALL,
        )
        if state_count != 1:
            raise ValueError("expected exactly one SG1_v4 retry state block")
    else:
        if text.count(schedule_anchor) != 1:
            raise ValueError("expected exactly one SG1_v4 fan-directory schedule anchor")
        text = text.replace(schedule_anchor, schedule_anchor + "\n\n" + MANAGER_STATE.rstrip(), 1)
    if "from datetime import datetime, timedelta" not in text:
        if text.count(import_anchor) != 1:
            raise ValueError("expected exactly one SG1_v4 datetime import anchor")
        text = text.replace(import_anchor, "from datetime import datetime, timedelta", 1)
    method_start = (
        r"    def get_fan_status_freshness\(self\):\n"
        if "def get_fan_status_freshness" in text
        else r"    def update_fan_gates_from_api\(self\):\n"
    )
    method_pattern = re.compile(
        method_start + r".*?"
        r"(?=    def start_lan_gate_discovery\(self\):)",
        re.DOTALL,
    )
    text, count = method_pattern.subn(MANAGER_METHODS, text, count=1)
    if count != 1:
        raise ValueError("expected exactly one SG1_v4 fan-directory update method")
    if text == original_text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def patch_html(path):
    if not path or not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    updated, count = re.subn(
        r'src=["\']/js/address_book\.js(?:\?[^"\']*)?["\']',
        'src="/js/address_book.js?v=stellar-archive-1.5.24-status"',
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
