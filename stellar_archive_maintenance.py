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
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from matelv_addon_manager import MatelvAddonManager


VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SHA_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
MAX_PACKAGE_BYTES = 300 * 1024 * 1024
PARALLEL_DOWNLOAD_MIN_BYTES = 8 * 1024 * 1024
PARALLEL_DOWNLOAD_WORKERS = 4
CATALOGUE_MANIFEST_MAX_BYTES = 1024 * 1024
CATALOGUE_FILE_MAX_BYTES = 32 * 1024 * 1024
CATALOGUE_TOTAL_MAX_BYTES = 300 * 1024 * 1024
CATALOGUE_SYNC_INTERVAL_SECONDS = 6 * 60 * 60
CATALOGUE_REVISION_RE = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
CATALOGUE_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CATALOGUE_ASSET_RE = re.compile(r"^assets/(?:archive-(?:approved|concept)-[0-9a-z-]+-v[0-9]+\.png|optimized/[0-9a-f]{64}\.webp)$")
CATALOGUE_CORE_FILES = {"data/worlds.json", "data/worlds.js", "world-styles.css", "thumbnail-sprite.css"}
_controller = None


class ParallelDownloadUnavailable(Exception):
    pass


class StellarArchiveMaintenance:
    def __init__(self, config_path=None):
        self.config_path = Path(config_path or Path(__file__).with_name(".stellar-archive-maintenance.json"))
        self.lock = threading.Lock()
        self.operation_lock = threading.Lock()
        self.task = {"state": "idle", "message": "Ready"}
        self.addons = MatelvAddonManager(self.config, self.operation_lock)
        self.catalogue_lock = threading.Lock()
        self.catalogue_status = {"state": "idle", "message": "Packaged catalogue active"}
        self._start_catalogue_worker()

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

    def latest_release(self):
        config = self.config()
        release_url = "https://github.com/{}/releases/latest".format(config["repository"])
        request = urllib.request.Request(release_url, headers={
            "Accept": "text/html",
            "User-Agent": "Stellar-Archive-Updater/1.5",
        })
        with urllib.request.urlopen(request, timeout=15) as response:
            resolved_url = response.geturl()
        release_prefix = "https://github.com/{}/releases/tag/".format(config["repository"])
        if not resolved_url.startswith(release_prefix):
            raise ValueError("latest GitHub release redirect is unavailable")
        latest = resolved_url[len(release_prefix):].split("?", 1)[0].split("#", 1)[0]
        self.version_tuple(latest)
        version = latest.lstrip("v")
        zip_name = "sg1_v3_v4_stellar_archive_universal_{}.zip".format(version)
        asset_root = "https://github.com/{}/releases/download/{}".format(config["repository"], latest)
        return {
            "version": version,
            "zip_name": zip_name,
            "zip_url": "{}/{}".format(asset_root, zip_name),
            "sha_url": "{}/{}.sha256".format(asset_root, zip_name),
            "release_url": resolved_url,
        }

    def check(self):
        config = self.config()
        task = dict(self.task)
        if task.get("action") == "update" and task.get("state") in ("running", "complete", "failed"):
            latest_version = task.get("target_version") or config["version"]
            return {
                "success": True,
                "current_version": config["version"],
                "latest_version": latest_version,
                "update_available": self.version_tuple(latest_version) > self.version_tuple(config["version"]),
                "release_url": task.get("release_url", ""),
                "task": task,
            }
        try:
            latest = self.latest_release()
            current_tuple = self.version_tuple(config["version"])
            latest_tuple = self.version_tuple(latest["version"])
            return {
                "success": True,
                "current_version": config["version"],
                "latest_version": latest["version"],
                "update_available": latest_tuple > current_tuple,
                "release_url": latest["release_url"],
                "task": task,
            }
        except Exception as error:
            return {"success": False, "message": str(error), "task": task}

    @staticmethod
    def _archive_root(config):
        return Path(config["target"]) / "stellar-archive"

    @staticmethod
    def _catalogue_state_root(config):
        name = ".stellar-archive-addon-v3" if config["platform"] == "v3" else ".stellar-archive-addon"
        return Path(config["target"]) / name / "catalogue-content"

    def _start_catalogue_worker(self):
        try:
            config = self.config()
        except Exception:
            return
        if config.get("catalogue_autostart", True) is False:
            return
        if not config.get("catalogue_manifest_url") or not config.get("catalogue_base_url"):
            return
        thread = threading.Thread(target=self._catalogue_loop, name="stellar-catalogue-sync")
        thread.daemon = True
        thread.start()

    def _catalogue_loop(self):
        while True:
            try:
                self.sync_catalogue()
            except Exception as error:
                self.catalogue_status = {"state": "error", "message": str(error)}
            time.sleep(CATALOGUE_SYNC_INTERVAL_SECONDS)

    def catalogue_check(self):
        status = dict(self.catalogue_status)
        try:
            worlds = json.loads((self._archive_root(self.config()) / "data" / "worlds.json").read_text(encoding="utf-8"))
            status["revision"] = worlds.get("catalogueRevision", "packaged")
            status["records"] = len(worlds.get("worlds", []))
        except Exception as error:
            status.setdefault("message", str(error))
        return {"success": status.get("state") != "error", "catalogue": status}

    @staticmethod
    def _read_limited_json(url):
        request = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "Stellar-Archive-Catalogue/1.5.37",
        })
        with urllib.request.urlopen(request, timeout=20) as response:
            content = response.read(CATALOGUE_MANIFEST_MAX_BYTES + 1)
        if len(content) > CATALOGUE_MANIFEST_MAX_BYTES:
            raise ValueError("catalogue manifest exceeds the safety limit")
        return json.loads(content.decode("utf-8"))

    @staticmethod
    def _valid_catalogue_path(path):
        return path in CATALOGUE_CORE_FILES or CATALOGUE_ASSET_RE.fullmatch(path) is not None

    @classmethod
    def _validate_catalogue_manifest(cls, manifest):
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            raise ValueError("unsupported catalogue manifest")
        revision = str(manifest.get("revision", ""))
        if not CATALOGUE_REVISION_RE.fullmatch(revision):
            raise ValueError("invalid catalogue revision")
        files = manifest.get("files")
        if not isinstance(files, list) or not files or len(files) > 512:
            raise ValueError("invalid catalogue file list")
        validated = []
        seen = set()
        total = 0
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("invalid catalogue file record")
            path = str(item.get("path", ""))
            source = str(item.get("source", ""))
            digest = str(item.get("sha256", "")).lower()
            try:
                size = int(item.get("size", -1))
            except (TypeError, ValueError):
                raise ValueError("invalid catalogue file size")
            if path in seen or not cls._valid_catalogue_path(path):
                raise ValueError("unsafe or duplicate catalogue path: {}".format(path))
            if source != "payload/stellar-archive/{}".format(path):
                raise ValueError("catalogue source does not match its target")
            if not CATALOGUE_SHA_RE.fullmatch(digest) or size < 0 or size > CATALOGUE_FILE_MAX_BYTES:
                raise ValueError("invalid catalogue file integrity record")
            total += size
            seen.add(path)
            validated.append({"path": path, "source": source, "sha256": digest, "size": size})
        if not CATALOGUE_CORE_FILES.issubset(seen) or total > CATALOGUE_TOTAL_MAX_BYTES:
            raise ValueError("catalogue manifest is incomplete or too large")
        return revision, validated

    @staticmethod
    def _download_catalogue_file(url, destination, expected_size, expected_sha):
        request = urllib.request.Request(url, headers={
            "Accept-Encoding": "identity",
            "User-Agent": "Stellar-Archive-Catalogue/1.5.37",
        })
        digest = hashlib.sha256()
        total = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > expected_size or total > CATALOGUE_FILE_MAX_BYTES:
                    raise ValueError("catalogue file exceeds its declared size")
                digest.update(chunk)
                output.write(chunk)
        if total != expected_size or digest.hexdigest() != expected_sha:
            raise ValueError("catalogue file integrity verification failed")

    @staticmethod
    def _candidate_file(archive_root, stage_root, relative):
        staged = stage_root / relative
        return staged if staged.is_file() else archive_root / relative

    @classmethod
    def _validate_catalogue_payload(cls, archive_root, stage_root, file_records):
        record_by_path = {item["path"]: item for item in file_records}
        worlds_path = cls._candidate_file(archive_root, stage_root, "data/worlds.json")
        worlds = json.loads(worlds_path.read_text(encoding="utf-8"))
        entries = worlds.get("worlds")
        if not isinstance(entries, list) or worlds.get("count") != len(entries) or not entries:
            raise ValueError("catalogue record count is invalid")
        ids = [entry.get("id") for entry in entries]
        if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
            raise ValueError("catalogue record ids are invalid")
        for entry in entries:
            address = entry.get("storedAddress")
            full = entry.get("fullAddress")
            if not isinstance(address, list) or not address or any(not isinstance(glyph, int) or glyph < 1 or glyph > 39 for glyph in address):
                raise ValueError("catalogue address is invalid")
            if (
                not isinstance(full, list)
                or len(full) < 7
                or len(full) > 9
                or any(not isinstance(glyph, int) or glyph < 1 or glyph > 39 for glyph in full)
                or full[-1] != entry.get("pointOfOrigin")
            ):
                raise ValueError("catalogue full address is invalid")
            asset_path = "assets/{}".format(entry.get("visualAsset", ""))
            if asset_path not in record_by_path or not cls._candidate_file(archive_root, stage_root, asset_path).is_file():
                raise ValueError("catalogue visual asset is missing")
        js = cls._candidate_file(archive_root, stage_root, "data/worlds.js").read_text(encoding="utf-8")
        prefix = "window.STELLAR_ARCHIVE_DATA="
        if not js.startswith(prefix) or not js.rstrip().endswith(";"):
            raise ValueError("catalogue browser data is invalid")
        browser_worlds = json.loads(js[len(prefix):].rstrip()[:-1])
        if browser_worlds != worlds:
            raise ValueError("catalogue JSON and browser data do not match")
        return worlds

    def sync_catalogue(self):
        if not self.catalogue_lock.acquire(blocking=False):
            return False
        operation_acquired = False
        temp = None
        try:
            operation_acquired = self.operation_lock.acquire(blocking=False)
            if not operation_acquired:
                self.catalogue_status = {"state": "deferred", "message": "Catalogue sync deferred during maintenance"}
                return False
            config = self.config()
            archive_root = self._archive_root(config)
            state_root = self._catalogue_state_root(config)
            manifest = self._read_limited_json(config["catalogue_manifest_url"])
            revision, files = self._validate_catalogue_manifest(manifest)
            self.catalogue_status = {"state": "checking", "revision": revision, "message": "Checking catalogue content"}
            state_path = state_root / "state.json"
            previous_state = {}
            if state_path.is_file():
                try:
                    previous_state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    previous_state = {}
            state_root.parent.mkdir(parents=True, exist_ok=True)
            temp = tempfile.mkdtemp(prefix="stellar-catalogue-", dir=str(state_root.parent))
            stage_root = Path(temp) / "stage"
            changed = []
            for item in files:
                destination = archive_root / item["path"]
                if destination.is_file() and destination.stat().st_size == item["size"] and self._sha256(destination) == item["sha256"]:
                    continue
                source_url = urllib.parse.urljoin(config["catalogue_base_url"].rstrip("/") + "/", item["source"])
                staged = stage_root / item["path"]
                self._download_catalogue_file(source_url, staged, item["size"], item["sha256"])
                changed.append(item["path"])
            # Publish assets and styles first, browser data second, and the
            # JSON revision marker last.  A browser can therefore never observe
            # a new revision before every file needed by that revision exists.
            changed.sort(key=lambda path: 3 if path == "data/worlds.json" else 2 if path == "data/worlds.js" else 1)
            validated_worlds = self._validate_catalogue_payload(archive_root, stage_root, files)
            if validated_worlds.get("catalogueRevision") != revision:
                raise ValueError("catalogue revision does not match the manifest")
            current_paths = {item["path"] for item in files}
            removed = [path for path in previous_state.get("files", []) if path not in current_paths and self._valid_catalogue_path(path)]
            backup_root = state_root / "previous"
            if changed or removed:
                if backup_root.exists():
                    shutil.rmtree(str(backup_root))
                for relative in changed + removed:
                    existing = archive_root / relative
                    if existing.is_file():
                        backup = backup_root / relative
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(existing), str(backup))
            applied = []
            try:
                for relative in changed:
                    target = archive_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(stage_root / relative), str(target))
                    os.chmod(str(target), 0o644)
                    applied.append(relative)
                for relative in removed:
                    target = archive_root / relative
                    if target.is_file():
                        target.unlink()
                    applied.append(relative)
            except Exception:
                for relative in reversed(applied):
                    backup = backup_root / relative
                    target = archive_root / relative
                    if backup.is_file():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(backup), str(target))
                    elif target.exists():
                        target.unlink()
                raise
            state_root.mkdir(parents=True, exist_ok=True)
            state = {"revision": revision, "files": sorted(current_paths), "updatedAt": int(time.time())}
            temporary_state = state_path.with_suffix(".tmp")
            temporary_state.write_text(json.dumps(state, separators=(",", ":")) + "\n", encoding="utf-8")
            os.replace(str(temporary_state), str(state_path))
            self.catalogue_status = {
                "state": "current",
                "revision": revision,
                "records": len(json.loads((archive_root / "data/worlds.json").read_text(encoding="utf-8"))["worlds"]),
                "changed": len(changed),
                "message": "Catalogue content is current",
            }
            return True
        except Exception as error:
            self.catalogue_status = {"state": "error", "message": str(error)}
            return False
        finally:
            if temp:
                shutil.rmtree(temp, ignore_errors=True)
            if operation_acquired:
                self.operation_lock.release()
            self.catalogue_lock.release()

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
            if not self.operation_lock.acquire(blocking=False):
                return {"success": False, "message": "another maintenance operation is already running", "task": dict(self.task)}
            try:
                release = self.latest_release()
                config = self.config()
                if self.version_tuple(release["version"]) <= self.version_tuple(config["version"]):
                    self.operation_lock.release()
                    return {"success": True, "message": "Stellar Archive is already up to date", "task": dict(self.task)}
                self.task = {
                    "state": "running",
                    "action": "update",
                    "phase": "download",
                    "progress": 5,
                    "target_version": release["version"],
                    "release_url": release["release_url"],
                    "message": "Downloading {}".format(release["version"]),
                }
                thread = threading.Thread(
                    target=self._run_update,
                    args=(config, release, True),
                    name="stellar-archive-update",
                )
                thread.daemon = True
                thread.start()
                return {"success": True, "message": "Update started", "task": dict(self.task)}
            except Exception:
                self.task = {"state": "idle", "message": "Ready"}
                self.operation_lock.release()
                raise

    def start_uninstall(self, handler):
        if not self.same_origin(handler):
            return {"success": False, "message": "same-origin request required"}
        with self.lock:
            if self.task.get("state") == "running":
                return {"success": False, "message": "another maintenance task is already running", "task": dict(self.task)}
            if not self.operation_lock.acquire(blocking=False):
                return {"success": False, "message": "another maintenance operation is already running", "task": dict(self.task)}
            try:
                config = self.config()
                self.task = {"state": "running", "action": "uninstall", "message": "Restoring pre-install files"}
                thread = threading.Thread(target=self._run_uninstall, args=(config, True), name="stellar-archive-uninstall")
                thread.daemon = True
                thread.start()
                return {"success": True, "message": "Uninstall started", "task": dict(self.task)}
            except Exception:
                self.task = {"state": "idle", "message": "Ready"}
                self.operation_lock.release()
                raise

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

    def _set_update_progress(self, phase, progress, message):
        target_version = self.task.get("target_version")
        release_url = self.task.get("release_url", "")
        self.task = {
            "state": "running",
            "action": "update",
            "phase": phase,
            "progress": max(5, min(99, int(progress))),
            "target_version": target_version,
            "release_url": release_url,
            "message": message,
        }

    @staticmethod
    def _download_request(url, byte_range=None):
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": "Stellar-Archive-Updater/1.5.37",
        }
        if byte_range:
            headers["Range"] = "bytes={}-{}".format(*byte_range)
        return urllib.request.Request(url, headers=headers)

    def _download_sequential(self, url, destination, progress_range=None, message="Downloading update"):
        request = self._download_request(url)
        total = 0
        with urllib.request.urlopen(request, timeout=30) as response, open(destination, "wb") as output:
            expected = int(response.headers.get("Content-Length") or 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PACKAGE_BYTES:
                    raise ValueError("release asset exceeds the 300 MB safety limit")
                output.write(chunk)
                if progress_range and expected > 0:
                    start, end = progress_range
                    progress = start + ((end - start) * min(total, expected) / expected)
                    self._set_update_progress(
                        "download",
                        progress,
                        "{} · {}%".format(message, int(min(total, expected) * 100 / expected)),
                    )

    def _parallel_download_size(self, url):
        request = self._download_request(url, (0, 0))
        with urllib.request.urlopen(request, timeout=30) as response:
            status = getattr(response, "status", response.getcode())
            match = CONTENT_RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
            if status != 206 or not match or match.group(1) != "0" or match.group(2) != "0":
                return 0
            if len(response.read(2)) != 1:
                return 0
        total = int(match.group(3))
        if total > MAX_PACKAGE_BYTES:
            raise ValueError("release asset exceeds the 300 MB safety limit")
        return total

    def _download_parallel(self, url, destination, total, progress_range, message):
        workers = min(PARALLEL_DOWNLOAD_WORKERS, max(1, total))
        segment_size = (total + workers - 1) // workers
        segments = []
        for index in range(workers):
            start = index * segment_size
            end = min(total - 1, start + segment_size - 1)
            if start <= end:
                segments.append((start, end))

        with open(destination, "wb") as output:
            output.truncate(total)

        progress_lock = threading.Lock()
        downloaded = [0]

        def download_segment(segment):
            start, end = segment
            request = self._download_request(url, segment)
            with urllib.request.urlopen(request, timeout=30) as response:
                status = getattr(response, "status", response.getcode())
                match = CONTENT_RANGE_RE.fullmatch(response.headers.get("Content-Range", ""))
                if (
                    status != 206
                    or not match
                    or int(match.group(1)) != start
                    or int(match.group(2)) != end
                    or int(match.group(3)) != total
                ):
                    raise ParallelDownloadUnavailable("release server returned an invalid byte range")
                remaining = end - start + 1
                with open(destination, "r+b", buffering=0) as output:
                    output.seek(start)
                    while remaining:
                        chunk = response.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ParallelDownloadUnavailable("release byte range ended early")
                        output.write(chunk)
                        remaining -= len(chunk)
                        with progress_lock:
                            downloaded[0] += len(chunk)
                            low, high = progress_range
                            progress = low + ((high - low) * downloaded[0] / total)
                            self._set_update_progress(
                                "download",
                                progress,
                                "{} · {}% · {} connections".format(
                                    message,
                                    int(downloaded[0] * 100 / total),
                                    len(segments),
                                ),
                            )

        with ThreadPoolExecutor(max_workers=len(segments), thread_name_prefix="stellar-download") as executor:
            list(executor.map(download_segment, segments))

        if os.path.getsize(destination) != total or downloaded[0] != total:
            raise ParallelDownloadUnavailable("parallel release download is incomplete")

    def _download(self, url, destination, progress_range=None, message="Downloading update"):
        if progress_range:
            try:
                total = self._parallel_download_size(url)
                if total >= PARALLEL_DOWNLOAD_MIN_BYTES:
                    self._download_parallel(url, destination, total, progress_range, message)
                    return
            except ValueError:
                raise
            except (ParallelDownloadUnavailable, OSError):
                self._set_update_progress("download", progress_range[0], "Parallel download unavailable; retrying safely")
        self._download_sequential(url, destination, progress_range, message)

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

    def _run_update(self, config, release, operation_acquired=False):
        temp = None
        acquired = operation_acquired
        try:
            if not acquired:
                acquired = self.operation_lock.acquire(timeout=1)
            if not acquired:
                raise RuntimeError("another maintenance operation is already running")
            temp = tempfile.mkdtemp(prefix="stellar-archive-update-")
            zip_path = os.path.join(temp, release["zip_name"])
            sha_path = zip_path + ".sha256"
            self._download(
                release["zip_url"],
                zip_path,
                progress_range=(5, 68),
                message="Downloading {}".format(release["version"]),
            )
            self._set_update_progress("download", 70, "Downloading checksum")
            self._download(release["sha_url"], sha_path)
            self._set_update_progress("verify", 74, "Verifying release checksum")
            checksum_text = Path(sha_path).read_text(encoding="utf-8")
            match = SHA_RE.search(checksum_text)
            if not match or self._sha256(zip_path).lower() != match.group(1).lower():
                raise ValueError("release SHA-256 verification failed")
            self._set_update_progress("verify", 82, "Verifying and extracting the release")
            extract_root = os.path.join(temp, "extracted")
            self._safe_extract(zip_path, extract_root)
            installers = list(Path(extract_root).glob("*/install.sh"))
            if len(installers) != 1:
                raise ValueError("release ZIP does not contain one universal installer")
            for script in installers[0].parent.glob("install*.sh"):
                script.chmod(0o755)
            self._set_update_progress("install", 88, "Installing {}".format(release["version"]))
            result = subprocess.run(self._installer_command(installers[0], config), capture_output=True, text=True, timeout=900)
            if result.returncode:
                raise RuntimeError("installer failed: {}".format((result.stderr or result.stdout)[-1200:]))
            self.task = {
                "state": "complete",
                "action": "update",
                "phase": "complete",
                "progress": 100,
                "target_version": release["version"],
                "release_url": release["release_url"],
                "message": "Updated to {}. Restart the Stargate software once.".format(release["version"]),
            }
        except Exception as error:
            self.task = {
                "state": "failed",
                "action": "update",
                "phase": "failed",
                "progress": 100,
                "target_version": release["version"],
                "release_url": release["release_url"],
                "message": str(error),
            }
        finally:
            if acquired:
                self.operation_lock.release()
            if temp:
                shutil.rmtree(temp, ignore_errors=True)

    def _run_uninstall(self, config, operation_acquired=False):
        acquired = operation_acquired
        try:
            if not acquired:
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
