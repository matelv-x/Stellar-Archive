"""Self-update and uninstall controller shared by SG1_v3 and SG1_v4."""

from __future__ import print_function

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import sys
import urllib.request
import zipfile
from pathlib import Path

from matelv_addon_manager import MatelvAddonManager


VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SHA_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
MAX_PACKAGE_BYTES = 300 * 1024 * 1024
_controller = None


class StellarArchiveMaintenance:
    def __init__(self, config_path=None):
        self.config_path = Path(config_path or Path(__file__).with_name(".stellar-archive-maintenance.json"))
        self.lock = threading.Lock()
        self.operation_lock = threading.Lock()
        self.task = {"state": "idle", "message": "Ready"}
        self.addons = MatelvAddonManager(self.config, self.operation_lock)

    def config(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        required = ("version", "platform", "target", "repository", "installer")
        if any(not data.get(key) for key in required):
            raise ValueError("maintenance configuration is incomplete")
        if data["platform"] not in ("v3", "v4"):
            raise ValueError("unsupported configured platform")
        return data

    @staticmethod
    def version_tuple(value):
        match = VERSION_RE.fullmatch(str(value).strip())
        if not match:
            raise ValueError("invalid release version: {}".format(value))
        return tuple(int(part) for part in match.groups())

    def github_json(self, url):
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Stellar-Archive-Updater/1.4",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def latest_release(self):
        config = self.config()
        release = self.github_json("https://api.github.com/repos/{}/releases/latest".format(config["repository"]))
        latest = str(release.get("tag_name", ""))
        self.version_tuple(latest)
        zip_name = "sg1_v3_v4_stellar_archive_universal_{}.zip".format(latest.lstrip("v"))
        assets = {asset.get("name"): asset.get("browser_download_url") for asset in release.get("assets", [])}
        if not assets.get(zip_name) or not assets.get(zip_name + ".sha256"):
            raise ValueError("latest release does not contain the universal ZIP and SHA-256 asset")
        return {
            "version": latest.lstrip("v"),
            "zip_name": zip_name,
            "zip_url": assets[zip_name],
            "sha_url": assets[zip_name + ".sha256"],
            "release_url": release.get("html_url", ""),
        }

    def check(self):
        try:
            config = self.config()
            latest = self.latest_release()
            current_tuple = self.version_tuple(config["version"])
            latest_tuple = self.version_tuple(latest["version"])
            return {
                "success": True,
                "current_version": config["version"],
                "latest_version": latest["version"],
                "update_available": latest_tuple > current_tuple,
                "release_url": latest["release_url"],
                "task": dict(self.task),
            }
        except Exception as error:
            return {"success": False, "message": str(error), "task": dict(self.task)}

    @staticmethod
    def same_origin(handler):
        host = handler.headers.get("Host", "")
        if not host:
            return False
        from urllib.parse import urlparse
        marker = handler.headers.get("X-Stellar-Archive-Request", "")
        fetch_site = handler.headers.get("Sec-Fetch-Site", "").lower()
        content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        # A cross-site browser request is always rejected.  The custom header
        # plus JSON content is accepted before Host comparison because Apache
        # reverse proxies commonly replace Host with localhost:8080, while
        # Safari/WebViews may also report the otherwise safe Origin as null.
        # Cross-origin pages cannot send this custom JSON request without a
        # successful CORS preflight, which the Stargate server never grants.
        if fetch_site == "cross-site":
            return False
        if marker == "same-origin" and content_type == "application/json":
            return True
        source = handler.headers.get("Origin") or handler.headers.get("Referer")
        if source and source != "null":
            return urlparse(source).netloc.lower() == host.lower()

        # Safari and some embedded WebViews omit Origin and Referer for a
        # same-origin JSON POST. A custom request header is the preferred proof;
        # application/json is the compatibility fallback. A cross-origin page
        # cannot send either without a successful CORS preflight, which this
        # local server does not grant.
        if fetch_site == "same-origin":
            return True
        return content_type == "application/json"

    def start_update(self, handler):
        if not self.same_origin(handler):
            return {"success": False, "message": "same-origin request required"}
        with self.lock:
            if self.task.get("state") == "running":
                return {"success": False, "message": "another maintenance task is already running", "task": dict(self.task)}
            release = self.latest_release()
            config = self.config()
            if self.version_tuple(release["version"]) <= self.version_tuple(config["version"]):
                return {"success": True, "message": "Stellar Archive is already up to date", "task": dict(self.task)}
            self.task = {"state": "running", "action": "update", "message": "Downloading {}".format(release["version"])}
            thread = threading.Thread(target=self._run_update, args=(config, release), name="stellar-archive-update")
            thread.daemon = True
            thread.start()
            return {"success": True, "message": "Update started", "task": dict(self.task)}

    def start_uninstall(self, handler):
        if not self.same_origin(handler):
            return {"success": False, "message": "same-origin request required"}
        with self.lock:
            if self.task.get("state") == "running":
                return {"success": False, "message": "another maintenance task is already running", "task": dict(self.task)}
            config = self.config()
            self.task = {"state": "running", "action": "uninstall", "message": "Restoring pre-install files"}
            thread = threading.Thread(target=self._run_uninstall, args=(config,), name="stellar-archive-uninstall")
            thread.daemon = True
            thread.start()
            return {"success": True, "message": "Uninstall started", "task": dict(self.task)}

    def list_addons(self):
        try:
            return self.addons.list_addons(check_remote=True)
        except Exception as error:
            return {"success": False, "message": str(error), "addons": [], "available": []}

    def start_addon_update(self, handler, payload=None):
        return self.addons.start(handler, "update", self.same_origin, payload)

    def start_addon_install(self, handler, payload=None):
        return self.addons.start(handler, "install", self.same_origin, payload)

    def start_addon_uninstall(self, handler, payload=None):
        return self.addons.start(handler, "uninstall", self.same_origin, payload)

    def restart_service(self, handler):
        if not self.same_origin(handler):
            return {"success": False, "message": "same-origin request required"}
        try:
            service = str(self.config().get("restart_service", ""))
            if not SERVICE_RE.fullmatch(service):
                raise ValueError("a safe Stargate service was not detected during installation")
            command = ["systemctl", "restart", service]
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                command = ["sudo", "-n"] + command
            helper = (
                "import subprocess,sys,time; time.sleep(1); "
                "raise SystemExit(subprocess.call(sys.argv[1:]))"
            )
            subprocess.Popen(
                [sys.executable, "-c", helper] + command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            return {"success": True, "message": "Restart scheduled", "service": service}
        except Exception as error:
            return {"success": False, "message": str(error)}

    def _download(self, url, destination):
        request = urllib.request.Request(url, headers={"User-Agent": "Stellar-Archive-Updater/1.5.11"})
        total = 0
        with urllib.request.urlopen(request, timeout=30) as response, open(destination, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("release asset exceeds the 300 MB safety limit")
                output.write(chunk)

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _safe_extract(archive_path, destination):
        root = os.path.realpath(destination)
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                candidate = os.path.realpath(os.path.join(root, info.filename))
                if candidate != root and not candidate.startswith(root + os.sep):
                    raise ValueError("release ZIP contains an unsafe path")
            archive.extractall(root)

    def _installer_command(self, installer, config, uninstall=False):
        command = [str(installer), "--platform", config["platform"], "--target", config["target"]]
        if uninstall:
            command.append("--uninstall")
        elif config["platform"] == "v4":
            command.extend(["--replace", config.get("mode", "standalone")])
        return command

    def _run_update(self, config, release):
        temp = tempfile.mkdtemp(prefix="stellar-archive-update-")
        acquired = False
        try:
            acquired = self.operation_lock.acquire(timeout=1)
            if not acquired:
                raise RuntimeError("another maintenance operation is already running")
            zip_path = os.path.join(temp, release["zip_name"])
            sha_path = zip_path + ".sha256"
            self._download(release["zip_url"], zip_path)
            self._download(release["sha_url"], sha_path)
            checksum_text = Path(sha_path).read_text(encoding="utf-8")
            match = SHA_RE.search(checksum_text)
            if not match or self._sha256(zip_path).lower() != match.group(1).lower():
                raise ValueError("release SHA-256 verification failed")
            extract_root = os.path.join(temp, "extracted")
            self._safe_extract(zip_path, extract_root)
            installers = list(Path(extract_root).glob("*/install.sh"))
            if len(installers) != 1:
                raise ValueError("release ZIP does not contain one universal installer")
            for script in installers[0].parent.glob("install*.sh"):
                script.chmod(0o755)
            result = subprocess.run(self._installer_command(installers[0], config), capture_output=True, text=True, timeout=900)
            if result.returncode:
                raise RuntimeError("installer failed: {}".format((result.stderr or result.stdout)[-1200:]))
            self.task = {"state": "complete", "action": "update", "message": "Updated to {}. Restart the Stargate software once.".format(release["version"])}
        except Exception as error:
            self.task = {"state": "failed", "action": "update", "message": str(error)}
        finally:
            if acquired:
                self.operation_lock.release()
            shutil.rmtree(temp, ignore_errors=True)

    def _run_uninstall(self, config):
        acquired = False
        try:
            acquired = self.operation_lock.acquire(timeout=1)
            if not acquired:
                raise RuntimeError("another maintenance operation is already running")
            installer = Path(config["installer"])
            if not installer.is_file():
                raise ValueError("cached uninstaller is missing")
            result = subprocess.run(self._installer_command(installer, config, uninstall=True), capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise RuntimeError("uninstaller failed: {}".format((result.stderr or result.stdout)[-1200:]))
            self.task = {"state": "complete", "action": "uninstall", "message": "Uninstalled. Restart the Stargate software once."}
        except Exception as error:
            self.task = {"state": "failed", "action": "uninstall", "message": str(error)}
        finally:
            if acquired:
                self.operation_lock.release()


def get_maintenance_controller():
    global _controller
    if _controller is None:
        _controller = StellarArchiveMaintenance()
    return _controller
