#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="/home/sg1/sg1"
DRY_RUN=0
UNINSTALL=0

usage() {
  cat <<'EOF'
SG1_v3 Stellar Archive bridge installer

Usage:
  ./install.sh [--platform v3] [--target PATH] [--dry-run]
  ./install.sh [--platform v3] --uninstall [--target PATH] [--dry-run]

SG1_v3 has no native web address book, so Archive is installed stand-alone at
/stellar-archive/ together with a dependency-free in-process HTTP bridge.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

while (($#)); do
  case "$1" in
    --target) (($# >= 2)) || die '--target needs a path'; TARGET="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --replace) die 'SG1_v3 has no Original or Retro web address book; replacement modes apply only to SG1_v4' ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown SG1_v3 option: $1" ;;
  esac
done

[[ "$TARGET" = /* ]] || die '--target must be an absolute path'
TARGET="${TARGET%/}"
case "$TARGET" in ''|'/'|'/home'|'/home/sg1') die "unsafe target: $TARGET" ;; esac

MAIN="$TARGET/main.py"
CLASS="$TARGET/classes/STARGATE_SG1.py"
ARCHIVE_DIR="$TARGET/stellar-archive"
BRIDGE="$TARGET/stellar_archive_bridge.py"
MAINTENANCE="$TARGET/stellar_archive_maintenance.py"
MAINTENANCE_CONFIG="$TARGET/.stellar-archive-maintenance.json"
ADDON_MANAGER="$TARGET/matelv_addon_manager.py"
ADDON_REGISTRY="$TARGET/matelv_addons.json"
ADDON_STATE="$TARGET/.matelv-addon-state.json"
RESTART_SERVICE=""
for unit_path in /etc/systemd/system/*.service; do
  [[ -f "$unit_path" ]] || continue
  if grep -Fq -- "$TARGET/main.py" "$unit_path"; then
    unit_name="$(basename -- "$unit_path")"
    [[ "$unit_name" =~ ^[A-Za-z0-9_.@-]+\.service$ ]] || continue
    if [[ -n "$RESTART_SERVICE" && "$RESTART_SERVICE" != "$unit_name" ]]; then
      RESTART_SERVICE=""
      break
    fi
    RESTART_SERVICE="$unit_name"
  fi
done
STATE="$TARGET/.stellar-archive-addon-v3"
ORIGINALS="$STATE/originals"
MANAGED="$STATE/managed"

[[ -f "$MAIN" && -f "$CLASS" ]] || die "not an SG1_v3 application root: $TARGET"
if ((UNINSTALL == 0)); then [[ -f "$SCRIPT_DIR/payload/stellar-archive/index.html" ]] || die 'Archive payload is incomplete'; fi
command -v python3 >/dev/null 2>&1 || die 'python3 is required'
python3 "$SCRIPT_DIR/patch_v3_main.py" --file "$MAIN" --check >/dev/null 2>&1 || {
  [[ -d "$STATE" ]] || die 'main.py cannot be patched safely or was modified by another installer'
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

matches() { [[ -f "$1" && -f "$2" && "$(sha256_file "$1")" = "$(sha256_file "$2")" ]]; }
remove_exact_tree() {
  local path="$1" expected_parent="$2"
  [[ -n "$path" && "$path" != '/' && "$(dirname -- "$path")" = "$expected_parent" ]] || die "refusing unsafe removal: $path"
  [[ ! -e "$path" ]] || find "$path" -depth -delete
}

if [[ -d "$STATE" ]]; then
  [[ -f "$ORIGINALS/main.py" && -f "$MANAGED/main.py" && -f "$MANAGED/stellar_archive_bridge.py" && -f "$MANAGED/stellar_archive_maintenance.py" ]] || die "incomplete installer state: $STATE"
  matches "$MAIN" "$MANAGED/main.py" || die 'managed SG1_v3 main.py was changed; preserve it manually before continuing'
  matches "$BRIDGE" "$MANAGED/stellar_archive_bridge.py" || die 'managed SG1_v3 bridge was changed; preserve it manually before continuing'
  matches "$MAINTENANCE" "$MANAGED/stellar_archive_maintenance.py" || die 'managed SG1_v3 maintenance module was changed; preserve it manually before continuing'
  [[ ! -f "$MANAGED/matelv_addon_manager.py" ]] || matches "$ADDON_MANAGER" "$MANAGED/matelv_addon_manager.py" || die 'managed matelv-x add-on manager was changed; preserve it manually before continuing'
  [[ ! -f "$MANAGED/matelv_addons.json" ]] || matches "$ADDON_REGISTRY" "$MANAGED/matelv_addons.json" || die 'managed matelv-x add-on registry was changed; preserve it manually before continuing'
elif ((UNINSTALL)); then
  die 'Stellar Archive v3 bridge is not installed by this installer'
fi

action='install or update the stand-alone SG1_v3 bridge'
((UNINSTALL)) && action='uninstall and restore the captured SG1_v3 files'
note "SG1_v3 application root: $TARGET"
note "Planned action: $action"
note 'The installer does not restart SG1_v3 and does not send a hardware command.'
if ((DRY_RUN)); then note 'Dry run complete: no files changed.'; exit 0; fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup="$TARGET/stellar-archive-backup-$timestamp"
suffix=1
while [[ -e "$backup" ]]; do backup="$TARGET/stellar-archive-backup-$timestamp-$suffix"; suffix=$((suffix + 1)); done
mkdir -p "$backup"
cp -a "$MAIN" "$backup/main.py"
[[ -f "$BRIDGE" ]] && cp -a "$BRIDGE" "$backup/stellar_archive_bridge.py"
[[ -d "$ARCHIVE_DIR" ]] && cp -a "$ARCHIVE_DIR" "$backup/stellar-archive"

if [[ ! -d "$STATE" ]]; then
  mkdir -p "$ORIGINALS" "$MANAGED"
  cp -a "$MAIN" "$ORIGINALS/main.py"
  if [[ -f "$BRIDGE" ]]; then cp -a "$BRIDGE" "$ORIGINALS/stellar_archive_bridge.py"; printf '1\n' > "$STATE/had-bridge"; else printf '0\n' > "$STATE/had-bridge"; fi
  if [[ -f "$MAINTENANCE" ]]; then cp -a "$MAINTENANCE" "$ORIGINALS/stellar_archive_maintenance.py"; printf '1\n' > "$STATE/had-maintenance"; else printf '0\n' > "$STATE/had-maintenance"; fi
  if [[ -f "$MAINTENANCE_CONFIG" ]]; then cp -a "$MAINTENANCE_CONFIG" "$ORIGINALS/maintenance-config.json"; printf '1\n' > "$STATE/had-maintenance-config"; else printf '0\n' > "$STATE/had-maintenance-config"; fi
  if [[ -d "$ARCHIVE_DIR" ]]; then cp -a "$ARCHIVE_DIR" "$ORIGINALS/stellar-archive"; printf '1\n' > "$STATE/had-archive"; else printf '0\n' > "$STATE/had-archive"; fi
fi

if [[ ! -f "$STATE/addon-manager-baseline-captured" ]]; then
  if [[ -f "$ADDON_MANAGER" ]]; then cp -a "$ADDON_MANAGER" "$ORIGINALS/matelv_addon_manager.py"; printf '1\n' > "$STATE/had-addon-manager"; else printf '0\n' > "$STATE/had-addon-manager"; fi
  if [[ -f "$ADDON_REGISTRY" ]]; then cp -a "$ADDON_REGISTRY" "$ORIGINALS/matelv_addons.json"; printf '1\n' > "$STATE/had-addon-registry"; else printf '0\n' > "$STATE/had-addon-registry"; fi
  if [[ -f "$ADDON_STATE" ]]; then cp -a "$ADDON_STATE" "$ORIGINALS/matelv-addon-state.json"; printf '1\n' > "$STATE/had-addon-state"; else printf '0\n' > "$STATE/had-addon-state"; fi
  printf '1\n' > "$STATE/addon-manager-baseline-captured"
fi

cp -a "$ORIGINALS/main.py" "$MAIN"

if ((UNINSTALL)); then
  had_bridge="$(<"$STATE/had-bridge")"
  had_maintenance="$(<"$STATE/had-maintenance")"
  had_maintenance_config="$(<"$STATE/had-maintenance-config")"
  had_archive="$(<"$STATE/had-archive")"
  had_addon_manager="$(<"$STATE/had-addon-manager")"
  had_addon_registry="$(<"$STATE/had-addon-registry")"
  had_addon_state="$(<"$STATE/had-addon-state")"
  [[ ! -f "$BRIDGE" ]] || find "$BRIDGE" -delete
  [[ ! -f "$MAINTENANCE" ]] || find "$MAINTENANCE" -delete
  [[ ! -f "$MAINTENANCE_CONFIG" ]] || find "$MAINTENANCE_CONFIG" -delete
  [[ ! -f "$ADDON_MANAGER" ]] || find "$ADDON_MANAGER" -delete
  [[ ! -f "$ADDON_REGISTRY" ]] || find "$ADDON_REGISTRY" -delete
  [[ ! -f "$ADDON_STATE" ]] || find "$ADDON_STATE" -delete
  remove_exact_tree "$ARCHIVE_DIR" "$TARGET"
  if [[ "$had_bridge" = 1 ]]; then cp -a "$ORIGINALS/stellar_archive_bridge.py" "$BRIDGE"; fi
  if [[ "$had_maintenance" = 1 ]]; then cp -a "$ORIGINALS/stellar_archive_maintenance.py" "$MAINTENANCE"; fi
  if [[ "$had_maintenance_config" = 1 ]]; then cp -a "$ORIGINALS/maintenance-config.json" "$MAINTENANCE_CONFIG"; fi
  if [[ "$had_addon_manager" = 1 ]]; then cp -a "$ORIGINALS/matelv_addon_manager.py" "$ADDON_MANAGER"; fi
  if [[ "$had_addon_registry" = 1 ]]; then cp -a "$ORIGINALS/matelv_addons.json" "$ADDON_REGISTRY"; fi
  if [[ "$had_addon_state" = 1 ]]; then cp -a "$ORIGINALS/matelv-addon-state.json" "$ADDON_STATE"; fi
  if [[ "$had_archive" = 1 ]]; then cp -a "$ORIGINALS/stellar-archive" "$ARCHIVE_DIR"; fi
  remove_exact_tree "$STATE" "$TARGET"
  note 'Uninstalled. The captured SG1_v3 main.py and pre-existing Archive files were restored.'
  note "Safety backup: $backup"
  note 'Restart SG1_v3 or reboot the Raspberry Pi to remove the running bridge.'
  exit 0
fi

staged="$TARGET/.stellar-archive-stage-$timestamp"
remove_exact_tree "$staged" "$TARGET"
cp -a "$SCRIPT_DIR/payload/stellar-archive" "$staged"
cat > "$staged/data/integration-nav.js" <<'EOF'
window.STELLAR_ARCHIVE_NAV={"mode":"v3","dialTarget":"v3","items":[{"label":"HOME","href":"/stellar-archive/"}]};
EOF
remove_exact_tree "$ARCHIVE_DIR" "$TARGET"
mv "$staged" "$ARCHIVE_DIR"
cp -a "$SCRIPT_DIR/stellar_archive_bridge.py" "$BRIDGE"
cp -a "$SCRIPT_DIR/stellar_archive_maintenance.py" "$MAINTENANCE"
cp -a "$SCRIPT_DIR/matelv_addon_manager.py" "$ADDON_MANAGER"
cp -a "$SCRIPT_DIR/matelv_addons.json" "$ADDON_REGISTRY"
python3 "$SCRIPT_DIR/patch_v3_main.py" --file "$MAIN"
python3 "$SCRIPT_DIR/validate_python_sources.py" "$MAIN" "$BRIDGE" "$MAINTENANCE" "$ADDON_MANAGER"

find "$ARCHIVE_DIR" -type d -exec chmod 755 {} +
find "$ARCHIVE_DIR" -type f -exec chmod 644 {} +
chmod 644 "$MAIN" "$BRIDGE" "$MAINTENANCE" "$ADDON_MANAGER" "$ADDON_REGISTRY"
if [[ -e "$TARGET" ]]; then
  owner="$(stat -c '%u:%g' "$TARGET" 2>/dev/null || true)"
  [[ -z "$owner" ]] || chown -R "$owner" "$ARCHIVE_DIR" "$BRIDGE" "$MAINTENANCE" "$ADDON_MANAGER" "$ADDON_REGISTRY" "$STATE"
fi

remove_exact_tree "$MANAGED" "$STATE"
mkdir -p "$MANAGED"
cp -a "$MAIN" "$MANAGED/main.py"
cp -a "$BRIDGE" "$MANAGED/stellar_archive_bridge.py"
cp -a "$MAINTENANCE" "$MANAGED/stellar_archive_maintenance.py"
cp -a "$ADDON_MANAGER" "$MANAGED/matelv_addon_manager.py"
cp -a "$ADDON_REGISTRY" "$MANAGED/matelv_addons.json"
updater="$STATE/updater"
mkdir -p "$updater"
for file in install.sh install-v3.sh install-v4.sh patch_v3_main.py patch_v4_web_server.py patch_address_book_routes.py patch_navigation_links.py build_navigation.py stellar_archive_bridge.py stellar_archive_maintenance.py matelv_addon_manager.py matelv_addons.json validate_python_sources.py; do
  [[ -f "$SCRIPT_DIR/$file" ]] && cp -a "$SCRIPT_DIR/$file" "$updater/$file"
done
chmod 755 "$updater/install.sh" "$updater/install-v3.sh" "$updater/install-v4.sh"
cat > "$MAINTENANCE_CONFIG" <<EOF
{"version":"1.5.20","platform":"v3","target":"$TARGET","repository":"matelv-x/Stellar-Archive","installer":"$updater/install.sh","restart_service":"$RESTART_SERVICE"}
EOF
chmod 644 "$MAINTENANCE_CONFIG"
printf '1.5.20\n' > "$STATE/version"

host_name="$(hostname -s 2>/dev/null || true)"
host_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
note 'Installed Stellar Archive 1.5.20 for SG1_v3.'
[[ -n "$host_ip" ]] && note "LAN URL after restart: http://$host_ip/stellar-archive/"
[[ -n "$host_name" ]] && note "Local-name URL after restart: http://$host_name.local/stellar-archive/"
note "Safety backup: $backup"
note 'Restart SG1_v3 or reboot the Raspberry Pi once to activate the web bridge.'
