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
import shlex
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
        command = [
            sys.executable,
            str(builder),
            "--target", str(target),
            "--mode", mode,
            "--output", str(temporary),
        ]
        home_routes = state_dir / "home-routes.json"
        if home_routes.is_file():
            command.extend(["--home-routes-file", str(home_routes)])
        result = self._run(command, timeout=30)
        if result.returncode:
            try:
                temporary.unlink()
            except OSError:
                pass
            detail = (result.stderr or result.stdout).strip()[-400:]
            raise RuntimeError("Archive navigation refresh failed: {}".format(detail or "unknown error"))
        os.replace(str(temporary), str(output))
        return True

    @staticmethod
    def _refresh_archive_managed_pages(context, manifest=None):
        """Accept verified add-on edits to Archive-managed navigation pages."""
        if context["platform"] != "v4":
            return 0
        target = context["target"]
        managed = target / ".stellar-archive-addon" / "managed"
        pairs = [
            (target / "address_book.htm", managed / "address_book.htm"),
            (target / "retro" / "address_book.html", managed / "retro-address_book.html"),
            (target / "retro" / "js" / "navigation.js", managed / "retro-navigation.js"),
            (target / "js" / "address_book.js", managed / "address_book.js"),
        ]
        declared = set((manifest or {}).get("archive_integration_files", []))
        if "classes/web_server.py" in declared:
            pairs.append((context["sg1_root"] / "classes" / "web_server.py", managed / "web_server.py"))
        if "classes/stargate_address_manager.py" in declared:
            pairs.append((
                context["sg1_root"] / "classes" / "stargate_address_manager.py",
                managed / "stargate_address_manager.py",
            ))
        original_navigation = managed / "original-nav-pages"
        if original_navigation.is_dir():
            for snapshot in original_navigation.glob("*.htm"):
                pairs.append((target / snapshot.name, snapshot))
        refreshed = 0
        for source, snapshot in pairs:
            if not source.is_file() or not snapshot.is_file():
                continue
            temporary = snapshot.with_name(snapshot.name + ".tmp")
            shutil.copyfile(str(source), str(temporary))
            os.replace(str(temporary), str(snapshot))
            refreshed += 1
        return refreshed

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
        dependencies = manifest.get("depends_on", [])
        if (not isinstance(dependencies, list)
                or any(not isinstance(item, str) or not ADDON_ID_RE.fullmatch(item)
                       for item in dependencies)
                or addon_id in dependencies
                or len(set(dependencies)) != len(dependencies)):
            raise ValueError("invalid add-on dependencies")
        if ("reapply_after_dependency_update" in manifest
                and not isinstance(manifest["reapply_after_dependency_update"], bool)):
            raise ValueError("invalid dependency reapply policy")
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
            registered = manifests.get(manifest["id"])
            if registered:
                merged = dict(registered)
                merged.update(manifest)
                manifest = self._validate_manifest(merged)
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

    def _checkout_is_clean(self, checkout):
        if not checkout:
            return False
        result = self._run(
            ["git", "-C", str(checkout["path"]), "status", "--porcelain", "--untracked-files=all"],
            timeout=10,
        )
        return result.returncode == 0 and not result.stdout.strip()

    def _cached_checkout(self, context, addon_id, expected_repository):
        path = context["target"] / ".stellar-archive-addon" / "addon-packages" / addon_id
        if not (path / ".git").is_dir():
            return None
        remote = self._run(["git", "-C", str(path), "remote", "get-url", "origin"], timeout=5)
        if remote.returncode:
            return None
        repository = self._repo_from_remote(remote.stdout)
        if not repository or repository.lower() != expected_repository.lower():
            return None
        return {"path": path, "origin": remote.stdout.strip()}

    def _clone_local_checkout(self, source, destination):
        result = self._run(
            ["git", "clone", "--depth", "1", "--no-hardlinks", str(source["path"]), str(destination)],
            timeout=60,
        )
        if result.returncode:
            return result
        return self._run(
            ["git", "-C", str(destination), "remote", "set-url", "origin", source["origin"]],
            timeout=5,
        )

    def _cache_verified_checkout(self, context, addon_id, checkout):
        cache_root = context["target"] / ".stellar-archive-addon" / "addon-packages"
        cache_root.mkdir(parents=True, exist_ok=True)
        destination = cache_root / addon_id
        temporary = cache_root / (addon_id + ".tmp")
        shutil.rmtree(str(temporary), ignore_errors=True)
        result = self._clone_local_checkout(checkout, temporary)
        if result.returncode:
            shutil.rmtree(str(temporary), ignore_errors=True)
            raise RuntimeError("could not cache the verified maintenance package")
        shutil.rmtree(str(destination), ignore_errors=True)
        os.replace(str(temporary), str(destination))

    def _repository_transport(self, repository, checkout):
        """Use an optional repository-scoped, read-only deployment identity.

        Credentials live outside the served web tree. Public repositories and
        installations without an identity retain their existing transport.
        No personal token, global Git setting, or unchecked host key is used.
        """
        origin = checkout["origin"] if checkout else "https://github.com/{}.git".format(repository)
        if self._repo_from_remote("https://github.com/{}.git".format(repository)) != repository:
            raise ValueError("invalid repository for scoped Git transport")
        directory = (self.config()["home_root"] / ".config" / "stellar-archive"
                     / "git-ssh" / repository.split("/", 1)[1])
        key = directory / "id_ed25519"
        hosts = directory / "known_hosts"
        if not key.exists() and not hosts.exists():
            return origin, {}
        if (not key.is_file() or key.is_symlink() or not hosts.is_file()
                or hosts.is_symlink() or key.stat().st_mode & 0o077):
            raise ValueError("scoped Git SSH identity is incomplete or has unsafe permissions")
        command = ["ssh", "-F", "/dev/null", "-i", str(key),
                   "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
                   "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                   "-o", "UserKnownHostsFile=" + str(hosts),
                   "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ConnectTimeout=10"]
        return "git@github.com:{}.git".format(repository), {
            "GIT_SSH_COMMAND": " ".join(shlex.quote(part) for part in command),
        }

    def _remote_revision(self, repository, checkout):
        now = time.time()
        cached = self.remote_cache.get(repository.lower())
        cache_seconds = 300 if cached and cached[1] else 5
        if cached and now - cached[0] < cache_seconds:
            return cached[1], cached[2]
        origin, transport_env = self._repository_transport(repository, checkout)
        result = None
        for attempt in range(3):
            result = self._run(["git", "ls-remote", origin, "HEAD"], timeout=20, env=transport_env)
            diagnostic = (result.stderr or result.stdout).lower()
            transient_dns = (
                "could not resolve host" in diagnostic
                or "temporary failure in name resolution" in diagnostic
            )
            if result.returncode == 0 or not transient_dns or attempt == 2:
                break
            time.sleep(0.25 * (attempt + 1))
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
            workers = min(2, len(platform_manifests))
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
        installed_by_id = {
            manifest["id"]: self._is_installed(manifest, context)
            for manifest in platform_manifests
        }
        names_by_id = {manifest["id"]: manifest["name"] for manifest in platform_manifests}
        installed_addons = []
        available_addons = []
        for manifest in platform_manifests:
            checkout = checkouts.get(manifest["repository"].lower())
            installed = installed_by_id[manifest["id"]]
            missing_dependencies = [
                dependency for dependency in manifest.get("depends_on", [])
                if not installed_by_id.get(dependency, False)
            ]
            installed_dependents = [
                candidate["name"] for candidate in platform_manifests
                if installed_by_id.get(candidate["id"], False)
                and manifest["id"] in candidate.get("depends_on", [])
            ]
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
                "can_install": (not installed and not missing_dependencies
                                and bool(manifest.get("install")) and bool(manifest.get("uninstall"))),
                "can_update": installed and not missing_dependencies and bool(manifest.get("install")),
                "can_uninstall": (installed and not installed_dependents
                                  and bool(manifest.get("uninstall"))),
                "depends_on": list(manifest.get("depends_on", [])),
                "dependency_names": [
                    names_by_id.get(dependency, dependency)
                    for dependency in manifest.get("depends_on", [])
                ],
                "missing_dependencies": missing_dependencies,
                "missing_dependency_names": [
                    names_by_id.get(dependency, dependency)
                    for dependency in missing_dependencies
                ],
                "installed_dependents": installed_dependents,
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
        operation_acquired = False
        task_created = False
        try:
            if payload is None:
                addon_id = self._read_request(handler)
            else:
                addon_id = payload.get("id") if isinstance(payload, dict) else None
                if not isinstance(addon_id, str) or not ADDON_ID_RE.fullmatch(addon_id):
                    raise ValueError("invalid add-on id")
            context = self.config()
            checkouts = self._checkout_map(context["home_root"])
            manifests = self._manifests(checkouts)
            manifest = manifests.get(addon_id)
            if not manifest or context["platform"] not in manifest["platforms"]:
                raise ValueError("unknown add-on")
            installed = self._is_installed(manifest, context)
            if action in ("update", "uninstall") and not installed:
                raise ValueError("add-on is not installed")
            if action == "install" and installed:
                raise ValueError("add-on is already installed")
            if action in ("install", "update"):
                missing_dependencies = [
                    dependency for dependency in manifest.get("depends_on", [])
                    if dependency not in manifests
                    or not self._is_installed(manifests[dependency], context)
                ]
                if missing_dependencies:
                    raise ValueError("install required add-on(s) first: {}".format(
                        ", ".join(missing_dependencies)))
            if action == "uninstall":
                installed_dependents = [
                    candidate["name"] for candidate in manifests.values()
                    if addon_id in candidate.get("depends_on", [])
                    and self._is_installed(candidate, context)
                ]
                if installed_dependents:
                    raise ValueError("uninstall dependent add-on(s) first: {}".format(
                        ", ".join(sorted(installed_dependents))))
            if action == "install" and not manifest.get("uninstall"):
                raise ValueError("installation is blocked until a safe uninstall procedure is available")
            command = manifest.get("install" if action in ("install", "update") else "uninstall")
            if not command:
                raise ValueError("{} is not supported safely for this add-on".format(action))
            checkout = checkouts.get(manifest["repository"].lower())
            with self.task_lock:
                if any(task.get("state") == "running" for task in self.tasks.values()):
                    raise ValueError("another add-on maintenance task is already running")
                operation_acquired = self.operation_lock.acquire(blocking=False)
                if not operation_acquired:
                    raise ValueError("another maintenance operation is already running")
                self.tasks[addon_id] = {
                    "state": "running",
                    "action": action,
                    "phase": "prepare",
                    "progress": 5,
                    "message": "Preparing {}".format(action),
                }
                task_created = True
            thread = threading.Thread(
                target=self._run_action,
                args=(addon_id, action, manifest, context, checkout, True),
                name="matelv-addon-{}-{}".format(addon_id, action),
            )
            thread.daemon = True
            thread.start()
            operation_acquired = False
            return {"success": True, "message": "{} started".format(action.capitalize()), "task": dict(self.tasks[addon_id])}
        except Exception as error:
            if operation_acquired:
                self.operation_lock.release()
            if task_created and self.tasks.get(addon_id, {}).get("state") == "running":
                self.tasks.pop(addon_id, None)
            return {"success": False, "message": str(error)}

    def _dependency_packages(self, addon_id, context):
        """Resolve installed dependents to the exact package revision we installed."""
        checkouts = self._checkout_map(context["home_root"])
        manifests = self._manifests(checkouts)
        state = self._state()
        packages = []
        for dependent in manifests.values():
            if (addon_id not in dependent.get("depends_on", [])
                    or not dependent.get("reapply_after_dependency_update", False)
                    or not self._is_installed(dependent, context)):
                continue
            revision = state.get(dependent["id"], {}).get("revision")
            if not revision or not SHA_RE.fullmatch(revision):
                raise RuntimeError(
                    "{} is installed but has no verified package revision; update it through Stellar Archive first".format(
                        dependent["name"]))
            checkout = None
            for candidate in (
                self._cached_checkout(context, dependent["id"], dependent["repository"]),
                checkouts.get(dependent["repository"].lower()),
            ):
                if (candidate and self._local_revision(candidate) == revision
                        and self._checkout_is_clean(candidate)):
                    checkout = candidate
                    break
            if not checkout:
                raise RuntimeError(
                    "the verified {} package is unavailable; refusing to update its dependency".format(
                        dependent["name"]))
            contract_path = checkout["path"] / "stargate-addon.json"
            if not contract_path.is_file():
                raise RuntimeError("{} has no cached maintenance contract".format(dependent["name"]))
            contract = self._validate_manifest(json.loads(contract_path.read_text(encoding="utf-8")))
            if (contract.get("maintenance_contract") != 1
                    or contract.get("uninstall_contract") != 2
                    or contract["id"] != dependent["id"]
                    or contract["repository"].lower() != dependent["repository"].lower()):
                raise RuntimeError("{} cached maintenance contract is invalid".format(dependent["name"]))
            merged = dict(dependent)
            merged.update(contract)
            packages.append({
                "id": dependent["id"],
                "name": dependent["name"],
                "manifest": self._validate_manifest(merged),
                "checkout": checkout,
                "revision": revision,
            })
        packages.sort(key=lambda package: package["name"].lower())
        return packages

    def _run_dependency_command(self, package, action, context):
        command_spec = package["manifest"].get(
            "install" if action == "install" else "uninstall")
        if not command_spec:
            raise RuntimeError("{} has no safe {} command".format(package["name"], action))
        argv = [self._expand(part, context) for part in command_spec["argv"]]
        if argv[0].startswith("./"):
            executable = package["checkout"]["path"] / argv[0][2:]
            if not executable.is_file():
                raise RuntimeError("{} {} command is missing".format(package["name"], action))
            executable.chmod(executable.stat().st_mode | 0o100)
            argv[0] = str(executable)
        command_env = {
            str(key): self._expand(value, context)
            for key, value in command_spec.get("env", {}).items()
        }
        command_env["STARGATE_ADDON_NO_RESTART"] = "1"
        return self._run(
            argv,
            cwd=package["checkout"]["path"],
            timeout=int(command_spec.get("timeout", 900)),
            env=command_env,
        )

    def _suspend_dependents(self, addon_id, context):
        packages = self._dependency_packages(addon_id, context)
        suspended = []
        for package in packages:
            self.tasks[addon_id] = {
                "state": "running", "action": "update", "phase": "dependencies", "progress": 60,
                "message": "Temporarily removing {}".format(package["name"]),
            }
            result = self._run_dependency_command(package, "uninstall", context)
            if result.returncode:
                rollback_failures = self._resume_dependents(addon_id, context, suspended)
                detail = (result.stderr or result.stdout).strip()[-MAX_OUTPUT_CHARS:]
                suffix = " Rollback failed for: {}.".format(", ".join(rollback_failures)) if rollback_failures else ""
                raise RuntimeError("could not safely remove {}: {}{}".format(
                    package["name"], detail or "unknown error", suffix))
            state = self._state()
            state.pop(package["id"], None)
            self._write_state(state)
            suspended.append(package)
        return suspended

    def _resume_dependents(self, addon_id, context, packages):
        failures = []
        for package in packages:
            self.tasks[addon_id] = {
                "state": "running", "action": "update", "phase": "dependencies", "progress": 90,
                "message": "Reapplying {}".format(package["name"]),
            }
            result = self._run_dependency_command(package, "install", context)
            if result.returncode:
                failures.append(package["name"])
                continue
            state = self._state()
            state[package["id"]] = {
                "repository": package["manifest"]["repository"],
                "revision": package["revision"],
            }
            self._write_state(state)
            self._refresh_archive_managed_pages(context, package["manifest"])
        return failures

    def _run_action(self, addon_id, action, manifest, context, checkout, operation_acquired=False):
        temp = None
        acquired = operation_acquired
        try:
            if not acquired:
                acquired = self.operation_lock.acquire(timeout=1)
            if not acquired:
                raise RuntimeError("another maintenance operation is already running")
            temp = tempfile.mkdtemp(prefix="matelv-addon-{}-".format(action))
            origin, transport_env = self._repository_transport(manifest["repository"], checkout)
            clone = Path(temp) / "repository"
            latest_revision = None
            local_source = None
            if action == "uninstall":
                self.tasks[addon_id] = {
                    "state": "running", "action": action, "phase": "download", "progress": 20,
                    "message": "Checking the latest uninstall procedure",
                }
                # Catalogue results may be cached for display, but removal
                # must always resolve GitHub again at operation time.
                self.remote_cache.pop(manifest["repository"].lower(), None)
                latest_revision, remote_error = self._remote_revision(manifest["repository"], checkout)
                if latest_revision:
                    for candidate in (
                        self._cached_checkout(context, addon_id, manifest["repository"]),
                        checkout,
                    ):
                        if candidate and self._repo_from_remote(candidate["origin"]) and self._local_revision(candidate) == latest_revision:
                            local_source = candidate
                            break
            if local_source:
                self.tasks[addon_id]["message"] = "Using the current verified uninstall procedure"
                cloned = self._clone_local_checkout(local_source, clone)
            else:
                self.tasks[addon_id] = {
                    "state": "running", "action": action, "phase": "download", "progress": 20,
                    "message": (
                        "Downloading the latest uninstall procedure from GitHub"
                        if action == "uninstall" else "Downloading repository"
                    ),
                }
                cloned = self._run(
                    ["git", "clone", "--depth", "1", origin, str(clone)],
                    timeout=180,
                    env=transport_env,
                )
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
            revision_result = self._run(["git", "-C", str(clone), "rev-parse", "HEAD"], timeout=5)
            verified_revision = revision_result.stdout.strip().lower()
            if not SHA_RE.fullmatch(verified_revision):
                raise RuntimeError("could not verify maintenance package revision")
            if action == "uninstall" and latest_revision and verified_revision != latest_revision:
                raise RuntimeError("the uninstall package is not the latest GitHub revision")
            remote_manifest_path = clone / "stargate-addon.json"
            if not remote_manifest_path.is_file():
                raise RuntimeError("the repository has no signed maintenance contract; use its documented manual procedure")
            remote_manifest = self._validate_manifest(json.loads(remote_manifest_path.read_text(encoding="utf-8")))
            if remote_manifest.get("maintenance_contract") != 1:
                raise RuntimeError("the repository maintenance contract is unsupported")
            if remote_manifest.get("uninstall_contract") != 2:
                raise RuntimeError("the repository has no verified surgical uninstall contract")
            if remote_manifest["id"] != manifest["id"] or remote_manifest["repository"].lower() != manifest["repository"].lower():
                raise RuntimeError("remote add-on manifest identity mismatch")
            for inherited_key in ("detect", "archive_integration_files"):
                if inherited_key not in remote_manifest and inherited_key in manifest:
                    remote_manifest[inherited_key] = manifest[inherited_key]
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
            self._cache_verified_checkout(
                context,
                addon_id,
                {"path": clone, "origin": remote.stdout.strip()},
            )
            self.tasks[addon_id] = {
                "state": "running", "action": action, "phase": "install", "progress": 75,
                "message": "Running verified {} procedure".format(action),
            }
            command_env = {
                str(key): self._expand(value, context)
                for key, value in command_spec.get("env", {}).items()
            }
            command_env["STARGATE_ADDON_NO_RESTART"] = "1"
            suspended = self._suspend_dependents(addon_id, context) if action == "update" else []
            try:
                result = self._run(
                    argv,
                    cwd=clone,
                    timeout=int(command_spec.get("timeout", 900)),
                    env=command_env,
                )
            except Exception as error:
                rollback_failures = self._resume_dependents(addon_id, context, suspended)
                suffix = " Dependency rollback failed for: {}.".format(
                    ", ".join(rollback_failures)) if rollback_failures else ""
                raise RuntimeError("{} failed: {}{}".format(action, error, suffix))
            if result.returncode:
                rollback_failures = self._resume_dependents(addon_id, context, suspended)
                detail = (result.stderr or result.stdout)[-MAX_OUTPUT_CHARS:]
                suffix = " Dependency rollback failed for: {}.".format(
                    ", ".join(rollback_failures)) if rollback_failures else ""
                raise RuntimeError("{} failed: {}{}".format(action, detail.strip(), suffix))
            reapply_failures = self._resume_dependents(addon_id, context, suspended)
            state = self._state()
            if action in ("install", "update"):
                if SHA_RE.fullmatch(verified_revision):
                    state[addon_id] = {"repository": manifest["repository"], "revision": verified_revision}
                    self._write_state(state)
            else:
                state.pop(addon_id, None)
                self._write_state(state)
            managed_pages_refreshed = self._refresh_archive_managed_pages(context, manifest)
            navigation_refreshed = self._refresh_archive_navigation(context)
            restart = " Restart Stargate software once." if manifest.get("restart_required", True) else ""
            navigation = " Archive navigation refreshed." if navigation_refreshed else ""
            snapshots = " Archive integration snapshots refreshed." if managed_pages_refreshed else ""
            dependencies = ""
            if suspended and not reapply_failures:
                dependencies = " Reapplied: {}.".format(
                    ", ".join(package["name"] for package in suspended))
            elif reapply_failures:
                dependencies = (
                    " Updated dependency is operational, but these add-ons remain safely disabled: {}."
                    .format(", ".join(reapply_failures))
                )
            self.tasks[addon_id] = {
                "state": "complete",
                "action": action,
                "phase": "complete",
                "progress": 100,
                "message": "{} completed.{}{}{}{}".format(
                    action.capitalize(), snapshots, navigation, dependencies, restart),
            }
            self.remote_cache.pop(manifest["repository"].lower(), None)
        except Exception as error:
            self.tasks[addon_id] = {
                "state": "failed", "action": action, "phase": "failed", "progress": 100,
                "message": str(error),
            }
        finally:
            if acquired:
                self.operation_lock.release()
            if temp:
                shutil.rmtree(temp, ignore_errors=True)
