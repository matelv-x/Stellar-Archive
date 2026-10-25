"""Safe maintenance manager for installed matelv-x Stargate add-ons.

The manager never guesses a shell command.  It accepts only declarative
manifests from the installer-owned registry or a checkout whose origin is a
matelv-x GitHub repository.  Commands are argument arrays and are executed
without a shell.
"""

from __future__ import print_function

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


REPOSITORY_RE = re.compile(
    r"^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"matelv-x/([A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
ADDON_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_BODY_BYTES = 4096
MAX_OUTPUT_CHARS = 1600


class MatelvAddonManager:
    def __init__(self, config_provider, operation_lock=None, registry_path=None):
        self.config_provider = config_provider
        self.operation_lock = operation_lock or threading.Lock()
        self.registry_path = Path(registry_path or Path(__file__).with_name("matelv_addons.json"))
        self.state_path = Path(__file__).with_name(".matelv-addon-state.json")
        self.task_lock = threading.Lock()
        self.tasks = {}
        self.remote_cache = {}

    def config(self):
        config = dict(self.config_provider())
        platform = config.get("platform")
        target = Path(config.get("target", "")).resolve()
        if platform == "v4":
            sg1_root = target.parent
        elif platform == "v3":
            sg1_root = target
        else:
            raise ValueError("unsupported configured platform")
        return {
            "platform": platform,
            "target": target,
            "sg1_root": sg1_root,
            "home_root": sg1_root.parent,
            "mode": config.get("mode", "standalone"),
        }

    def _refresh_archive_navigation(self, context):
        """Rebuild SG1_v4 Archive navigation after an add-on changes pages."""
        if context["platform"] != "v4":
            return False
        target = context["target"]
        state_dir = target / ".stellar-archive-addon"
        builder = state_dir / "updater" / "build_navigation.py"
        output = target / "stellar-archive" / "data" / "integration-nav.js"
        mode_file = state_dir / "current-mode"
        if not builder.is_file() or not output.parent.is_dir() or not mode_file.is_file():
            return False
        mode = mode_file.read_text(encoding="utf-8").strip()
        if mode not in ("original", "retro", "both", "standalone"):
            raise RuntimeError("Archive integration mode is invalid")
        temporary = output.with_name(output.name + ".tmp")
        result = self._run([
            sys.executable,
            str(builder),
            "--target", str(target),
            "--mode", mode,
            "--output", str(temporary),
        ], timeout=30)
        if result.returncode:
            try:
                temporary.unlink()
            except OSError:
                pass
            detail = (result.stderr or result.stdout).strip()[-400:]
            raise RuntimeError("Archive navigation refresh failed: {}".format(detail or "unknown error"))
        os.replace(str(temporary), str(output))
        return True

    def _registry(self):
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if payload.get("schema") != 1 or not isinstance(payload.get("addons"), list):
            raise ValueError("invalid matelv-x add-on registry")
        result = {}
        for manifest in payload["addons"]:
            normalized = self._validate_manifest(manifest)
            result[normalized["id"]] = normalized
        return result

    @staticmethod
    def _validate_manifest(manifest):
        if not isinstance(manifest, dict):
            raise ValueError("add-on manifest must be an object")
        addon_id = str(manifest.get("id", ""))
        repository = str(manifest.get("repository", ""))
        if not ADDON_ID_RE.fullmatch(addon_id):
            raise ValueError("invalid add-on id")
        if not repository.lower().startswith("matelv-x/") or repository.count("/") != 1:
            raise ValueError("add-on repository must belong to matelv-x")
        if not manifest.get("name") or not isinstance(manifest.get("platforms"), list):
            raise ValueError("incomplete add-on manifest")
        for action in ("install", "uninstall"):
            value = manifest.get(action)
            if value is None:
                continue
            if not isinstance(value, dict) or not isinstance(value.get("argv"), list) or not value["argv"]:
                raise ValueError("{} command must be an argument array".format(action))
            if any(not isinstance(item, str) or not item for item in value["argv"]):
                raise ValueError("{} command contains an invalid argument".format(action))
            command_env = value.get("env", {})
            if not isinstance(command_env, dict) or any(
                not isinstance(key, str) or not key or not isinstance(item, str)
                for key, item in command_env.items()
            ):
                raise ValueError("{} command contains an invalid environment".format(action))
        return dict(manifest)

    @staticmethod
    def _repo_from_remote(remote):
        match = REPOSITORY_RE.fullmatch(str(remote).strip())
        return "matelv-x/{}".format(match.group(1)) if match else None

    @staticmethod
    def _run(command, cwd=None, timeout=30, env=None):
        process_env = os.environ.copy()
        process_env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
        if env:
            process_env.update(env)
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=process_env,
        )

    def _checkout_map(self, home_root):
        result = {}
        if not home_root.is_dir():
            return result
        for candidate in home_root.iterdir():
            if not candidate.is_dir() or not (candidate / ".git").is_dir():
                continue
            remote = self._run(["git", "-C", str(candidate), "remote", "get-url", "origin"], timeout=5)
            if remote.returncode:
                continue
            repository = self._repo_from_remote(remote.stdout)
            if repository:
                result.setdefault(repository.lower(), {"path": candidate, "origin": remote.stdout.strip()})
        return result

    def _manifests(self, checkouts):
        manifests = self._registry()
        for repository_key, checkout in checkouts.items():
            path = checkout["path"] / "stargate-addon.json"
            if not path.is_file():
                continue
            try:
                manifest = self._validate_manifest(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if manifest["repository"].lower() != repository_key:
                continue
            manifests[manifest["id"]] = manifest
        return manifests

    def _state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def _write_state(self, value):
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(temporary), str(self.state_path))

    @staticmethod
    def _expand(value, context):
        allowed = {
            "sg1_root": str(context["sg1_root"]),
            "web_root": str(context["sg1_root"] / "web"),
            "home_root": str(context["home_root"]),
        }
        output = str(value)
        for key, replacement in allowed.items():
            output = output.replace("{" + key + "}", replacement)
        if "{" in output or "}" in output:
            raise ValueError("unsupported command placeholder")
        return output

    def _path_rule_matches(self, rule, context):
        if not isinstance(rule, dict) or not rule.get("path"):
            return False
        path = Path(self._expand(rule["path"], context))
        if not path.is_absolute():
            path = context["sg1_root"] / path
        if not path.exists():
            return False
        contains = rule.get("contains")
        if contains is None:
            return True
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            return False
        try:
            return str(contains) in path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False

    def _is_installed(self, manifest, context):
        detection = manifest.get("detect", {})
        all_rules = detection.get("all", [])
        any_rules = detection.get("any", [])
        if not all_rules and not any_rules:
            return False
        if all_rules and not all(self._path_rule_matches(rule, context) for rule in all_rules):
            return False
        if any_rules and not any(self._path_rule_matches(rule, context) for rule in any_rules):
            return False
        return True

    def _local_revision(self, checkout):
        if not checkout:
            return None
        result = self._run(["git", "-C", str(checkout["path"]), "rev-parse", "HEAD"], timeout=5)
        value = result.stdout.strip().lower()
        return value if result.returncode == 0 and SHA_RE.fullmatch(value) else None

    def _remote_revision(self, repository, checkout):
        now = time.time()
        cached = self.remote_cache.get(repository.lower())
        if cached and now - cached[0] < 300:
            return cached[1], cached[2]
        origin = checkout["origin"] if checkout else "https://github.com/{}.git".format(repository)
        result = self._run(["git", "ls-remote", origin, "HEAD"], timeout=20)
        value = result.stdout.split()[0].lower() if result.returncode == 0 and result.stdout.split() else ""
        revision = value if SHA_RE.fullmatch(value) else None
        error = "" if revision else ((result.stderr or result.stdout).strip()[-400:] or "repository access unavailable")
        self.remote_cache[repository.lower()] = (now, revision, error)
        return revision, error

    def list_addons(self, check_remote=True):
        context = self.config()
        checkouts = self._checkout_map(context["home_root"])
        saved_state = self._state()
        platform_manifests = [
            manifest for manifest in self._manifests(checkouts).values()
            if context["platform"] in manifest["platforms"]
        ]
        remote_results = {}
        if check_remote and platform_manifests:
            workers = min(4, len(platform_manifests))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self._remote_revision,
                        manifest["repository"],
                        checkouts.get(manifest["repository"].lower()),
                    ): manifest["repository"]
                    for manifest in platform_manifests
                }
                for future in as_completed(futures):
                    repository = futures[future]
                    try:
                        remote_results[repository.lower()] = future.result()
                    except Exception as error:
                        remote_results[repository.lower()] = (None, str(error))
        installed_addons = []
        available_addons = []
        for manifest in platform_manifests:
            checkout = checkouts.get(manifest["repository"].lower())
            installed = self._is_installed(manifest, context)
            current = None
            if installed:
                current = saved_state.get(manifest["id"], {}).get("revision") or self._local_revision(checkout)
            latest = None
            error = ""
            if check_remote:
                latest, error = remote_results.get(manifest["repository"].lower(), (None, "update check unavailable"))
            task = dict(self.tasks.get(manifest["id"], {"state": "idle", "message": "Ready"}))
            item = {
                "id": manifest["id"],
                "name": manifest["name"],
                "repository": manifest["repository"],
                "repository_url": "https://github.com/{}".format(manifest["repository"]),
                "current_revision": current[:12] if current else None,
                "latest_revision": latest[:12] if latest else None,
                "installed": installed,
                "update_available": None if not installed or not current or not latest else current != latest,
                "check_error": error,
                "can_install": not installed and bool(manifest.get("install")) and bool(manifest.get("uninstall")),
                "can_update": installed and bool(manifest.get("install")),
                "can_uninstall": installed and bool(manifest.get("uninstall")),
                "restart_required": bool(manifest.get("restart_required", True)),
                "task": task,
            }
            (installed_addons if installed else available_addons).append(item)
        installed_addons.sort(key=lambda item: item["name"].lower())
        available_addons.sort(key=lambda item: item["name"].lower())
        return {"success": True, "addons": installed_addons, "available": available_addons}

    @staticmethod
    def _read_request(handler):
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = 0
        if length < 2 or length > MAX_BODY_BYTES:
            raise ValueError("invalid request size")
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
        addon_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(addon_id, str) or not ADDON_ID_RE.fullmatch(addon_id):
            raise ValueError("invalid add-on id")
        return addon_id

    def start(self, handler, action, same_origin, payload=None):
        if not same_origin(handler):
            return {"success": False, "message": "same-origin request required"}
        if action not in ("install", "update", "uninstall"):
            return {"success": False, "message": "unsupported add-on action"}
        try:
            if payload is None:
                addon_id = self._read_request(handler)
            else:
                addon_id = payload.get("id") if isinstance(payload, dict) else None
                if not isinstance(addon_id, str) or not ADDON_ID_RE.fullmatch(addon_id):
                    raise ValueError("invalid add-on id")
            context = self.config()
            checkouts = self._checkout_map(context["home_root"])
            manifest = self._manifests(checkouts).get(addon_id)
            if not manifest or context["platform"] not in manifest["platforms"]:
                raise ValueError("unknown add-on")
            installed = self._is_installed(manifest, context)
            if action in ("update", "uninstall") and not installed:
                raise ValueError("add-on is not installed")
            if action == "install" and installed:
                raise ValueError("add-on is already installed")
            if action == "install" and not manifest.get("uninstall"):
                raise ValueError("installation is blocked until a safe uninstall procedure is available")
            command = manifest.get("install" if action in ("install", "update") else "uninstall")
            if not command:
                raise ValueError("{} is not supported safely for this add-on".format(action))
            checkout = checkouts.get(manifest["repository"].lower())
            with self.task_lock:
                if any(task.get("state") == "running" for task in self.tasks.values()):
                    raise ValueError("another add-on maintenance task is already running")
                self.tasks[addon_id] = {
                    "state": "running",
                    "action": action,
                    "phase": "prepare",
                    "progress": 5,
                    "message": "Preparing {}".format(action),
                }
            thread = threading.Thread(
                target=self._run_action,
                args=(addon_id, action, manifest, context, checkout),
                name="matelv-addon-{}-{}".format(addon_id, action),
            )
            thread.daemon = True
            thread.start()
            return {"success": True, "message": "{} started".format(action.capitalize()), "task": dict(self.tasks[addon_id])}
        except Exception as error:
            return {"success": False, "message": str(error)}

    def _run_action(self, addon_id, action, manifest, context, checkout):
        temp = tempfile.mkdtemp(prefix="matelv-addon-{}-".format(action))
        try:
            acquired = self.operation_lock.acquire(timeout=1)
            if not acquired:
                raise RuntimeError("another maintenance operation is already running")
            origin = checkout["origin"] if checkout else "https://github.com/{}.git".format(manifest["repository"])
            clone = Path(temp) / "repository"
            self.tasks[addon_id] = {
                "state": "running", "action": action, "phase": "download", "progress": 20,
                "message": "Downloading repository",
            }
            cloned = self._run(["git", "clone", "--depth", "1", origin, str(clone)], timeout=180)
            if cloned.returncode:
                raise RuntimeError("repository download failed: {}".format((cloned.stderr or cloned.stdout)[-600:]))
            self.tasks[addon_id] = {
                "state": "running", "action": action, "phase": "verify", "progress": 50,
                "message": "Verifying maintenance contract",
            }
            remote = self._run(["git", "-C", str(clone), "remote", "get-url", "origin"], timeout=5)
            cloned_repository = None if remote.returncode else self._repo_from_remote(remote.stdout)
            if not cloned_repository or cloned_repository.lower() != manifest["repository"].lower():
                raise RuntimeError("downloaded repository identity does not match the manifest")
            remote_manifest_path = clone / "stargate-addon.json"
            if not remote_manifest_path.is_file():
                raise RuntimeError("the repository has no signed maintenance contract; use its documented manual procedure")
            remote_manifest = self._validate_manifest(json.loads(remote_manifest_path.read_text(encoding="utf-8")))
            if remote_manifest.get("maintenance_contract") != 1:
                raise RuntimeError("the repository maintenance contract is unsupported")
            if remote_manifest["id"] != manifest["id"] or remote_manifest["repository"].lower() != manifest["repository"].lower():
                raise RuntimeError("remote add-on manifest identity mismatch")
            manifest = remote_manifest
            if action == "install" and not remote_manifest.get("uninstall"):
                raise RuntimeError("installation is blocked: the current repository has no safe uninstall procedure")
            command_spec = manifest.get("install" if action in ("install", "update") else "uninstall")
            if not command_spec:
                raise RuntimeError("the current repository does not support this action")
            argv = [self._expand(part, context) for part in command_spec["argv"]]
            executable = clone / argv[0]
            if argv[0].startswith("./"):
                executable = clone / argv[0][2:]
                if not executable.is_file():
                    raise RuntimeError("manifest command is missing from the repository")
                executable.chmod(executable.stat().st_mode | 0o100)
                argv[0] = str(executable)
            self.tasks[addon_id] = {
                "state": "running", "action": action, "phase": "install", "progress": 75,
                "message": "Running verified {} procedure".format(action),
            }
            command_env = {
                str(key): self._expand(value, context)
                for key, value in command_spec.get("env", {}).items()
            }
            command_env["STARGATE_ADDON_NO_RESTART"] = "1"
            result = self._run(
                argv,
                cwd=clone,
                timeout=int(command_spec.get("timeout", 900)),
                env=command_env,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout)[-MAX_OUTPUT_CHARS:]
                raise RuntimeError("{} failed: {}".format(action, detail.strip()))
            state = self._state()
            if action in ("install", "update"):
                revision_result = self._run(["git", "-C", str(clone), "rev-parse", "HEAD"], timeout=5)
                revision = revision_result.stdout.strip().lower()
                if SHA_RE.fullmatch(revision):
                    state[addon_id] = {"repository": manifest["repository"], "revision": revision}
                    self._write_state(state)
            else:
                state.pop(addon_id, None)
                self._write_state(state)
            navigation_refreshed = self._refresh_archive_navigation(context)
            restart = " Restart Stargate software once." if manifest.get("restart_required", True) else ""
            navigation = " Archive navigation refreshed." if navigation_refreshed else ""
            self.tasks[addon_id] = {
                "state": "complete",
                "action": action,
                "phase": "complete",
                "progress": 100,
                "message": "{} completed.{}{}".format(action.capitalize(), navigation, restart),
            }
            self.remote_cache.pop(manifest["repository"].lower(), None)
        except Exception as error:
            self.tasks[addon_id] = {
                "state": "failed", "action": action, "phase": "failed", "progress": 100,
                "message": str(error),
            }
        finally:
            if "acquired" in locals() and acquired:
                self.operation_lock.release()
            shutil.rmtree(temp, ignore_errors=True)
