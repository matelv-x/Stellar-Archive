#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
TARGET="/home/pi/sg1_v4/web"
MODE=""
DRY_RUN=0
UNINSTALL=0

usage() {
  cat <<'EOF'
SG1_v4 adapter — Stellar Archive universal installer 1.5.22

Usage:
  ./install.sh [--replace original|retro|both|standalone] [--target PATH] [--dry-run]
  ./install.sh --uninstall [--target PATH] [--dry-run]

Without --replace, the installer asks which SG1_v4 address page Stellar Archive
should replace. Run the installer again at any time to switch the selection.

Options:
  --replace MODE  original, retro, both, or standalone (replace neither)
  --target PATH   SG1_v4 web root (default: /home/pi/sg1_v4/web)
  --dry-run       validate and print the plan without changing files
  --uninstall     restore the pages and Archive captured before first install
  --help          show this help
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

while (($#)); do
  case "$1" in
    --replace) (($# >= 2)) || die '--replace needs a value'; MODE="$2"; shift 2 ;;
    --target) (($# >= 2)) || die '--target needs a path'; TARGET="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$TARGET" = /* ]] || die '--target must be an absolute path'
TARGET="${TARGET%/}"
case "$TARGET" in
  ''|'/'|'/home'|'/home/pi'|'/home/pi/sg1_v4') die "unsafe target: $TARGET" ;;
esac

PAYLOAD="$SCRIPT_DIR/payload"
ARCHIVE_PAYLOAD="$PAYLOAD/stellar-archive"
INTEGRATION_PAYLOAD="$PAYLOAD/integration"
STATE="$TARGET/.stellar-archive-addon"
SITE_HOME_ROUTES="$STATE/home-routes.json"
ORIGINALS="$STATE/originals"
MANAGED="$STATE/managed"
NAV_ORIGINALS="$ORIGINALS/original-nav-pages"
RETRO_NAV="$TARGET/retro/js/navigation.js"
ORIGINAL_ADDRESS_JS="$TARGET/js/address_book.js"
ORIGINAL_PAGE="$TARGET/address_book.htm"
RETRO_PAGE="$TARGET/retro/address_book.html"
ARCHIVE_DIR="$TARGET/stellar-archive"
SG1_ROOT="$(dirname -- "$TARGET")"
WEB_SERVER="$SG1_ROOT/classes/web_server.py"
ADDRESS_MANAGER="$SG1_ROOT/classes/stargate_address_manager.py"
MAINTENANCE="$SG1_ROOT/classes/stellar_archive_maintenance.py"
MAINTENANCE_CONFIG="$SG1_ROOT/classes/.stellar-archive-maintenance.json"
ADDON_MANAGER="$SG1_ROOT/classes/matelv_addon_manager.py"
ADDON_REGISTRY="$SG1_ROOT/classes/matelv_addons.json"
ADDON_STATE="$SG1_ROOT/classes/.matelv-addon-state.json"
# Use a per-process overlay. A fixed path can survive an interrupted or dry-run
# update and must never be replayed over a later surgical add-on uninstall.
ADDON_OVERLAY="$STATE/addon-overlay-$$"
RESTART_SERVICE=""
for unit_path in /etc/systemd/system/*.service; do
  [[ -f "$unit_path" ]] || continue
  if grep -Fq -- "$SG1_ROOT/main.py" "$unit_path"; then
    unit_name="$(basename -- "$unit_path")"
    [[ "$unit_name" =~ ^[A-Za-z0-9_.@-]+\.service$ ]] || continue
    if [[ -n "$RESTART_SERVICE" && "$RESTART_SERVICE" != "$unit_name" ]]; then
      RESTART_SERVICE=""
      break
    fi
    RESTART_SERVICE="$unit_name"
  fi
done
HAS_RETRO=0
if [[ -f "$RETRO_PAGE" && -f "$RETRO_NAV" ]]; then HAS_RETRO=1; fi
HAS_EXTENDED_RETRO=0
if ((HAS_RETRO)) && [[ -f "$TARGET/retro/dial.html" && -f "$TARGET/retro/dial9.html" ]]; then HAS_EXTENDED_RETRO=1; fi

if ((UNINSTALL == 0)); then
  [[ -f "$ARCHIVE_PAYLOAD/index.html" && -f "$ARCHIVE_PAYLOAD/app.js" ]] || die 'Archive payload is incomplete'
  [[ -f "$INTEGRATION_PAYLOAD/original-address-book.htm" ]] || die 'Original integration payload is missing'
  [[ -f "$INTEGRATION_PAYLOAD/retro-address-book.html" ]] || die 'Retro integration payload is missing'
fi
[[ -d "$TARGET" ]] || die "target does not exist: $TARGET"
[[ -f "$ORIGINAL_PAGE" ]] || die "not an SG1_v4 web root (address_book.htm missing): $TARGET"
[[ -f "$ORIGINAL_ADDRESS_JS" ]] || die "not an SG1_v4 web root (js/address_book.js missing): $TARGET"
[[ -f "$WEB_SERVER" ]] || die "SG1_v4 API server was not found: $WEB_SERVER"
[[ -f "$ADDRESS_MANAGER" ]] || die "SG1_v4 address manager was not found: $ADDRESS_MANAGER"

if ((UNINSTALL == 0)) && [[ -z "$MODE" ]]; then
  [[ -t 0 ]] || die 'non-interactive use requires --replace original|retro|both|standalone'
  if ((HAS_RETRO)); then cat <<'EOF'

Where should Stellar Archive replace the current address book?
  1) Original interface
  2) Retro interface
  3) Both Original and Retro
  4) Stand-alone Archive (replace neither)
EOF
    read -r -p 'Selection [1-4]: ' selection
    case "$selection" in
      1) MODE=original ;;
      2) MODE=retro ;;
      3) MODE=both ;;
      4) MODE=standalone ;;
      *) die 'invalid selection' ;;
    esac
  else cat <<'EOF'

Retro is not installed. Choose the integration mode:
  1) Replace the Original address book
  2) Stand-alone Archive (keep Original and add a navigation link)
EOF
    read -r -p 'Selection [1-2]: ' selection
    case "$selection" in
      1) MODE=original ;;
      2) MODE=standalone ;;
      *) die 'invalid selection' ;;
    esac
  fi
fi

if ((UNINSTALL == 0)); then
  [[ "$MODE" = 'none' ]] && MODE='standalone'
  case "$MODE" in original|retro|both|standalone) ;; *) die "invalid replacement mode: $MODE" ;; esac
  if [[ "$MODE" = 'retro' || "$MODE" = 'both' ]]; then
    ((HAS_RETRO)) || die 'Retro mode requested, but a complete Retro interface was not detected'
  fi
fi

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

matches_wrapper() {
  local installed="$1" expected="$2"
  [[ -f "$installed" ]] && [[ "$(sha256_file "$installed")" = "$(sha256_file "$expected")" ]]
}

remove_exact_tree() {
  local path="$1" expected_parent="$2"
  [[ -n "$path" && "$path" != '/' && "$(dirname -- "$path")" = "$expected_parent" ]] || die "refusing unsafe removal: $path"
  [[ ! -e "$path" ]] || find "$path" -depth -delete
}

run_copy() {
  local source="$1" destination="$2"
  cp -a "$source" "$destination"
}

current_mode="none"
if [[ -f "$STATE/current-mode" ]]; then current_mode="$(<"$STATE/current-mode")"; fi

validate_managed_pages() {
  local expected_original="$ORIGINALS/address_book.htm"
  local expected_retro=""
  [[ -f "$ORIGINALS/retro-address_book.html" ]] && expected_retro="$ORIGINALS/retro-address_book.html"
  case "$current_mode" in
    original)
      expected_original="$INTEGRATION_PAYLOAD/original-address-book.htm"
      ;;
    retro)
      ((HAS_RETRO)) || die 'installed state expects Retro, but Retro is no longer installed'
      [[ -n "$expected_retro" ]] || die 'installed state expects Retro, but its original page is missing'
      expected_retro="$INTEGRATION_PAYLOAD/retro-address-book.html"
      ;;
    both)
      ((HAS_RETRO)) || die 'installed state expects Retro, but Retro is no longer installed'
      [[ -n "$expected_retro" ]] || die 'installed state expects Retro, but its original page is missing'
      expected_original="$INTEGRATION_PAYLOAD/original-address-book.htm"
      expected_retro="$INTEGRATION_PAYLOAD/retro-address-book.html"
      ;;
    none|standalone|'') ;;
    *) die "invalid installed state: $current_mode" ;;
  esac
  if [[ -f "$MANAGED/address_book.htm" ]]; then expected_original="$MANAGED/address_book.htm"; fi
  if [[ -f "$MANAGED/retro-address_book.html" ]]; then expected_retro="$MANAGED/retro-address_book.html"; fi
  matches_wrapper "$ORIGINAL_PAGE" "$expected_original" || die 'managed Original page was changed; preserve it manually or restore the latest backup before continuing'
  if ((HAS_RETRO)) && [[ -n "$expected_retro" ]]; then matches_wrapper "$RETRO_PAGE" "$expected_retro" || die 'managed Retro page was changed; preserve it manually or restore the latest backup before continuing'; fi
  if [[ -d "$MANAGED/original-nav-pages" ]]; then
    for expected in "$MANAGED/original-nav-pages"/*.htm; do
      [[ -e "$expected" ]] || continue
      matches_wrapper "$TARGET/$(basename -- "$expected")" "$expected" || die "managed Original navigation page was changed: $(basename -- "$expected")"
    done
  fi
  if ((HAS_RETRO)) && [[ -f "$MANAGED/retro-navigation.js" ]]; then
    matches_wrapper "$RETRO_NAV" "$MANAGED/retro-navigation.js" || die 'managed Retro navigation was changed; preserve it manually or restore the latest backup before continuing'
  fi
  if [[ -f "$MANAGED/address_book.js" ]]; then
    matches_wrapper "$ORIGINAL_ADDRESS_JS" "$MANAGED/address_book.js" || die 'managed Original address-book routing was changed; preserve it manually or restore the latest backup before continuing'
  fi
  if [[ -f "$MANAGED/web_server.py" ]]; then
    matches_wrapper "$WEB_SERVER" "$MANAGED/web_server.py" || die 'managed SG1_v4 web_server.py was changed; preserve it manually before continuing'
  fi
  if [[ -f "$MANAGED/stargate_address_manager.py" ]]; then
    matches_wrapper "$ADDRESS_MANAGER" "$MANAGED/stargate_address_manager.py" || die 'managed SG1_v4 stargate_address_manager.py was changed; preserve it manually before continuing'
  fi
  if [[ -f "$MANAGED/stellar_archive_maintenance.py" ]]; then
    matches_wrapper "$MAINTENANCE" "$MANAGED/stellar_archive_maintenance.py" || die 'managed SG1_v4 maintenance module was changed; preserve it manually before continuing'
  fi
  if [[ -f "$MANAGED/matelv_addon_manager.py" ]]; then
    matches_wrapper "$ADDON_MANAGER" "$MANAGED/matelv_addon_manager.py" || die 'managed matelv-x add-on manager was changed; preserve it manually before continuing'
  fi
  if [[ -f "$MANAGED/matelv_addons.json" ]]; then
    matches_wrapper "$ADDON_REGISTRY" "$MANAGED/matelv_addons.json" || die 'managed matelv-x add-on registry was changed; preserve it manually before continuing'
  fi
}

INTERRUPTED_UNIVERSAL_130=0
if [[ -d "$STATE" && -f "$STATE/version" && "$(<"$STATE/version")" = '1.2.8' \
  && -f "$ARCHIVE_DIR/index.html" && -f "$ORIGINALS/web_server.py" \
  && -f "$WEB_SERVER" && -f "$MAINTENANCE" \
  ]] && grep -q 'sg1-universal-1.3.0' "$ARCHIVE_DIR/index.html" \
  && grep -q 'STELLAR_ARCHIVE_MAINTENANCE_IMPORT_BEGIN' "$WEB_SERVER"; then
  INTERRUPTED_UNIVERSAL_130=1
fi

if [[ -d "$STATE" ]]; then
  [[ -f "$ORIGINALS/address_book.htm" ]] || die "incomplete installer state: $STATE"
  if ((INTERRUPTED_UNIVERSAL_130)); then
    note 'Detected and will recover the interrupted 1.3.0 validation run.'
  else
    command -v python3 >/dev/null 2>&1 || die 'python3 is required to validate installed add-on integration'
    python3 "$SCRIPT_DIR/adopt_managed_addon_changes.py" --target "$TARGET" --managed "$MANAGED" --state "$ADDON_STATE" --registry "$SCRIPT_DIR/matelv_addons.json" --overlay "$ADDON_OVERLAY"
    validate_managed_pages
  fi
elif ((UNINSTALL)); then
  die 'Stellar Archive add-on is not installed by this installer'
fi

action="install mode '$MODE'"
((UNINSTALL)) && action='uninstall and restore pre-install files'
note "SG1_v4 web root: $TARGET"
note "Planned action: $action"
note 'No service restart or hardware command is used.'
if ((DRY_RUN)); then
  [[ ! -d "$ADDON_OVERLAY" ]] || remove_exact_tree "$ADDON_OVERLAY" "$STATE"
  note 'Dry run complete: no files changed.'
  exit 0
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
backup="$TARGET/backups/stellar-archive-addon-$timestamp"
backup_base="$backup"
backup_index=1
while [[ -e "$backup" ]]; do
  backup="${backup_base}-$backup_index"
  backup_index=$((backup_index + 1))
done
mkdir -p "$backup/retro" "$backup/original-nav" "$backup/js"
[[ -f "$ORIGINAL_PAGE" ]] && run_copy "$ORIGINAL_PAGE" "$backup/address_book.htm"
[[ -f "$RETRO_PAGE" ]] && run_copy "$RETRO_PAGE" "$backup/retro/address_book.html"
[[ -d "$ARCHIVE_DIR" ]] && run_copy "$ARCHIVE_DIR" "$backup/stellar-archive"
[[ -f "$RETRO_NAV" ]] && run_copy "$RETRO_NAV" "$backup/retro/navigation.js"
[[ -f "$ORIGINAL_ADDRESS_JS" ]] && run_copy "$ORIGINAL_ADDRESS_JS" "$backup/js/address_book.js"
mkdir -p "$backup/classes"
run_copy "$WEB_SERVER" "$backup/classes/web_server.py"
run_copy "$ADDRESS_MANAGER" "$backup/classes/stargate_address_manager.py"
[[ -f "$MAINTENANCE" ]] && run_copy "$MAINTENANCE" "$backup/classes/stellar_archive_maintenance.py"
[[ -f "$MAINTENANCE_CONFIG" ]] && run_copy "$MAINTENANCE_CONFIG" "$backup/classes/maintenance-config.json"
[[ -f "$ADDON_MANAGER" ]] && run_copy "$ADDON_MANAGER" "$backup/classes/matelv_addon_manager.py"
[[ -f "$ADDON_REGISTRY" ]] && run_copy "$ADDON_REGISTRY" "$backup/classes/matelv_addons.json"
for page in "$TARGET"/*.htm; do
  [[ -f "$page" ]] || continue
  if grep -q 'navbar-nav' "$page"; then run_copy "$page" "$backup/original-nav/$(basename -- "$page")"; fi
done

if [[ ! -d "$STATE" ]]; then
  mkdir -p "$ORIGINALS"
  run_copy "$ORIGINAL_PAGE" "$ORIGINALS/address_book.htm"
  [[ -f "$ORIGINAL_ADDRESS_JS" ]] && run_copy "$ORIGINAL_ADDRESS_JS" "$ORIGINALS/address_book.js"
  if ((HAS_RETRO)); then run_copy "$RETRO_PAGE" "$ORIGINALS/retro-address_book.html"; fi
  if [[ -d "$ARCHIVE_DIR" ]]; then
    run_copy "$ARCHIVE_DIR" "$ORIGINALS/stellar-archive"
    printf '1\n' > "$STATE/had-archive"
  else
    printf '0\n' > "$STATE/had-archive"
  fi
  printf 'none\n' > "$STATE/current-mode"
  run_copy "$WEB_SERVER" "$ORIGINALS/web_server.py"
  if [[ -f "$MAINTENANCE" ]]; then run_copy "$MAINTENANCE" "$ORIGINALS/stellar_archive_maintenance.py"; printf '1\n' > "$STATE/had-maintenance"; else printf '0\n' > "$STATE/had-maintenance"; fi
  if [[ -f "$MAINTENANCE_CONFIG" ]]; then run_copy "$MAINTENANCE_CONFIG" "$ORIGINALS/maintenance-config.json"; printf '1\n' > "$STATE/had-maintenance-config"; else printf '0\n' > "$STATE/had-maintenance-config"; fi
fi

# v1.4 introduces the common matelv-x add-on manager. Capture any pre-existing
# files exactly once so uninstall can restore the pre-Archive state.
if [[ ! -f "$STATE/addon-manager-baseline-captured" ]]; then
  if [[ -f "$ADDON_MANAGER" ]]; then run_copy "$ADDON_MANAGER" "$ORIGINALS/matelv_addon_manager.py"; printf '1\n' > "$STATE/had-addon-manager"; else printf '0\n' > "$STATE/had-addon-manager"; fi
  if [[ -f "$ADDON_REGISTRY" ]]; then run_copy "$ADDON_REGISTRY" "$ORIGINALS/matelv_addons.json"; printf '1\n' > "$STATE/had-addon-registry"; else printf '0\n' > "$STATE/had-addon-registry"; fi
  if [[ -f "$ADDON_STATE" ]]; then run_copy "$ADDON_STATE" "$ORIGINALS/matelv-addon-state.json"; printf '1\n' > "$STATE/had-addon-state"; else printf '0\n' > "$STATE/had-addon-state"; fi
  printf '1\n' > "$STATE/addon-manager-baseline-captured"
fi

# Upgrade from a pre-universal Archive state: capture the untouched API server
# before this release begins managing the About maintenance endpoints.
if [[ ! -f "$ORIGINALS/web_server.py" ]]; then
  run_copy "$WEB_SERVER" "$ORIGINALS/web_server.py"
  if [[ -f "$MAINTENANCE" ]]; then run_copy "$MAINTENANCE" "$ORIGINALS/stellar_archive_maintenance.py"; printf '1\n' > "$STATE/had-maintenance"; else printf '0\n' > "$STATE/had-maintenance"; fi
  if [[ -f "$MAINTENANCE_CONFIG" ]]; then run_copy "$MAINTENANCE_CONFIG" "$ORIGINALS/maintenance-config.json"; printf '1\n' > "$STATE/had-maintenance-config"; else printf '0\n' > "$STATE/had-maintenance-config"; fi
fi

# v1.2.4 starts managing the Original address-book route. Capture the existing
# script on upgrade before applying the first extended-address patch.
if [[ -f "$ORIGINAL_ADDRESS_JS" && ! -f "$ORIGINALS/address_book.js" ]]; then
  run_copy "$ORIGINAL_ADDRESS_JS" "$ORIGINALS/address_book.js"
fi

# v1.5.15 starts managing bounded central-directory retries. Capture the
# existing address manager exactly once so uninstall remains lossless.
if [[ ! -f "$ORIGINALS/stargate_address_manager.py" ]]; then
  run_copy "$ADDRESS_MANAGER" "$ORIGINALS/stargate_address_manager.py"
fi

# If Retro was added after an Original-only Archive installation, adopt its
# current files as the untouched baseline before managing it.
if ((HAS_RETRO)) && [[ ! -f "$ORIGINALS/retro-address_book.html" ]]; then
  run_copy "$RETRO_PAGE" "$ORIGINALS/retro-address_book.html"
fi

# v1.2 navigation baseline. On upgrade from v1.1, these are captured before
# Stellar Archive begins managing the Stand-alone links.
if [[ ! -d "$NAV_ORIGINALS" ]]; then
  mkdir -p "$NAV_ORIGINALS"
  for page in "$TARGET"/*.htm; do
    [[ -f "$page" ]] || continue
    [[ "$(basename -- "$page")" = 'address_book.htm' ]] && continue
    if grep -q 'navbar-nav' "$page"; then run_copy "$page" "$NAV_ORIGINALS/$(basename -- "$page")"; fi
  done
fi
if ((HAS_RETRO)) && [[ ! -f "$ORIGINALS/retro-navigation.js" ]]; then
  run_copy "$RETRO_NAV" "$ORIGINALS/retro-navigation.js"
fi

# Restore the two address-book pages before applying the selected replacement.
# On an update, keep the current shared backend, address manager, routing and
# navigation files in place: they are the surgical post-uninstall truth. The
# captured pre-Archive copies may still contain an add-on removed much later.
run_copy "$ORIGINALS/address_book.htm" "$ORIGINAL_PAGE"
if ((HAS_RETRO)); then run_copy "$ORIGINALS/retro-address_book.html" "$RETRO_PAGE"; fi
if ((UNINSTALL)); then
  for original_nav in "$NAV_ORIGINALS"/*.htm; do
    [[ -e "$original_nav" ]] || continue
    run_copy "$original_nav" "$TARGET/$(basename -- "$original_nav")"
  done
  if ((HAS_RETRO)); then run_copy "$ORIGINALS/retro-navigation.js" "$RETRO_NAV"; fi
  if [[ -f "$ORIGINALS/address_book.js" ]]; then run_copy "$ORIGINALS/address_book.js" "$ORIGINAL_ADDRESS_JS"; fi
  run_copy "$ORIGINALS/web_server.py" "$WEB_SERVER"
  run_copy "$ORIGINALS/stargate_address_manager.py" "$ADDRESS_MANAGER"
  if [[ -f "$ADDON_OVERLAY/classes/web_server.py" ]]; then run_copy "$ADDON_OVERLAY/classes/web_server.py" "$WEB_SERVER"; fi
  if ((HAS_RETRO)) && [[ -f "$ADDON_OVERLAY/web/retro/js/navigation.js" ]]; then run_copy "$ADDON_OVERLAY/web/retro/js/navigation.js" "$RETRO_NAV"; fi
else
  for original_nav in "$NAV_ORIGINALS"/*.htm; do
    [[ -e "$original_nav" ]] || continue
    current_nav="$TARGET/$(basename -- "$original_nav")"
    if [[ -f "$current_nav" ]] && grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$current_nav"; then
      python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind original --file "$current_nav" --remove
    fi
  done
  if ((HAS_RETRO)) && grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$RETRO_NAV"; then
    python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind retro --file "$RETRO_NAV" --remove
  fi
fi

if ((UNINSTALL)); then
  if ((HAS_RETRO)) && grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$RETRO_NAV"; then
    python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind retro --file "$RETRO_NAV" --remove
  fi
  had_archive="$(<"$STATE/had-archive")"
  had_maintenance="$(<"$STATE/had-maintenance")"
  had_maintenance_config="$(<"$STATE/had-maintenance-config")"
  had_addon_manager="$(<"$STATE/had-addon-manager")"
  had_addon_registry="$(<"$STATE/had-addon-registry")"
  had_addon_state="$(<"$STATE/had-addon-state")"
  remove_exact_tree "$ARCHIVE_DIR" "$TARGET"
  if [[ "$had_archive" = '1' ]]; then run_copy "$ORIGINALS/stellar-archive" "$ARCHIVE_DIR"; fi
  [[ ! -f "$MAINTENANCE" ]] || find "$MAINTENANCE" -delete
  [[ ! -f "$MAINTENANCE_CONFIG" ]] || find "$MAINTENANCE_CONFIG" -delete
  [[ ! -f "$ADDON_MANAGER" ]] || find "$ADDON_MANAGER" -delete
  [[ ! -f "$ADDON_REGISTRY" ]] || find "$ADDON_REGISTRY" -delete
  [[ ! -f "$ADDON_STATE" ]] || find "$ADDON_STATE" -delete
  if [[ "$had_maintenance" = '1' ]]; then run_copy "$ORIGINALS/stellar_archive_maintenance.py" "$MAINTENANCE"; fi
  if [[ "$had_maintenance_config" = '1' ]]; then run_copy "$ORIGINALS/maintenance-config.json" "$MAINTENANCE_CONFIG"; fi
  if [[ "$had_addon_manager" = '1' ]]; then run_copy "$ORIGINALS/matelv_addon_manager.py" "$ADDON_MANAGER"; fi
  if [[ "$had_addon_registry" = '1' ]]; then run_copy "$ORIGINALS/matelv_addons.json" "$ADDON_REGISTRY"; fi
  if [[ "$had_addon_state" = '1' ]]; then run_copy "$ORIGINALS/matelv-addon-state.json" "$ADDON_STATE"; fi
  remove_exact_tree "$STATE" "$TARGET"
  note "Uninstalled. Pre-install pages and Archive state were restored."
  note "Safety backup: $backup"
  note 'Restart SG1_v4 once to remove the maintenance endpoints from the running API.'
  exit 0
fi

staged="$TARGET/.stellar-archive-stage-$timestamp"
old="$TARGET/.stellar-archive-old-$timestamp"
remove_exact_tree "$staged" "$TARGET"
run_copy "$ARCHIVE_PAYLOAD" "$staged"
# Some SG1_v4 virtual hosts use fan113.html as DirectoryIndex for every
# directory. Preserve the established Archive alias across updates so opening
# /stellar-archive/ continues to resolve to index.html on those hosts.
if [[ -L "$ARCHIVE_DIR/fan113.html" ]] && [[ "$(readlink "$ARCHIVE_DIR/fan113.html")" = 'index.html' ]]; then
  ln -s index.html "$staged/fan113.html"
fi
command -v python3 >/dev/null 2>&1 || die 'python3 is required to detect installed navigation buttons'
navigation_args=(--target "$TARGET" --mode "$MODE" --output "$staged/data/integration-nav.js")
[[ -f "$SITE_HOME_ROUTES" ]] && navigation_args+=(--home-routes-file "$SITE_HOME_ROUTES")
python3 "$SCRIPT_DIR/build_navigation.py" "${navigation_args[@]}"
find "$staged" -type d -exec chmod 755 {} +
find "$staged" -type f -exec chmod 644 {} +
if [[ -d "$ARCHIVE_DIR" ]]; then mv "$ARCHIVE_DIR" "$old"; fi
mv "$staged" "$ARCHIVE_DIR"
remove_exact_tree "$old" "$TARGET"

case "$MODE" in
  original)
    run_copy "$INTEGRATION_PAYLOAD/original-address-book.htm" "$ORIGINAL_PAGE"
    ;;
  retro)
    ((HAS_RETRO)) || die 'Retro disappeared during installation'
    run_copy "$INTEGRATION_PAYLOAD/retro-address-book.html" "$RETRO_PAGE"
    ;;
  both)
    ((HAS_RETRO)) || die 'Retro disappeared during installation'
    run_copy "$INTEGRATION_PAYLOAD/original-address-book.htm" "$ORIGINAL_PAGE"
    run_copy "$INTEGRATION_PAYLOAD/retro-address-book.html" "$RETRO_PAGE"
    ;;
  standalone)
    python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind original --file "$ORIGINAL_PAGE"
    for original_nav in "$NAV_ORIGINALS"/*.htm; do
      [[ -e "$original_nav" ]] || continue
      python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind original --file "$TARGET/$(basename -- "$original_nav")"
    done
    if ((HAS_RETRO)); then python3 "$SCRIPT_DIR/patch_navigation_links.py" --kind retro --file "$RETRO_NAV"; fi
    ;;
esac
if ((HAS_EXTENDED_RETRO)) && [[ -f "$ORIGINAL_ADDRESS_JS" ]]; then
  python3 "$SCRIPT_DIR/patch_address_book_routes.py" --file "$ORIGINAL_ADDRESS_JS" --html-file "$ORIGINAL_PAGE"
fi
run_copy "$SCRIPT_DIR/stellar_archive_maintenance.py" "$MAINTENANCE"
run_copy "$SCRIPT_DIR/matelv_addon_manager.py" "$ADDON_MANAGER"
run_copy "$SCRIPT_DIR/matelv_addons.json" "$ADDON_REGISTRY"
python3 "$SCRIPT_DIR/patch_v4_web_server.py" --file "$WEB_SERVER"
note 'Refreshed the owned Stellar Archive web-server blocks and preserved all other integrations.'
python3 "$SCRIPT_DIR/patch_v4_gate_status.py" \
  --web-server "$WEB_SERVER" \
  --address-js "$ORIGINAL_ADDRESS_JS" \
  --address-manager "$ADDRESS_MANAGER" \
  --html-file "$ORIGINAL_PAGE"
python3 "$SCRIPT_DIR/validate_python_sources.py" "$WEB_SERVER" "$ADDRESS_MANAGER" "$MAINTENANCE" "$ADDON_MANAGER"
chmod 644 "$ORIGINAL_PAGE"
if ((HAS_RETRO)); then chmod 644 "$RETRO_PAGE"; fi
if [[ -f "$ORIGINAL_ADDRESS_JS" ]]; then chmod 644 "$ORIGINAL_ADDRESS_JS"; fi
chmod 644 "$WEB_SERVER" "$ADDRESS_MANAGER" "$MAINTENANCE" "$ADDON_MANAGER" "$ADDON_REGISTRY"
remove_exact_tree "$MANAGED" "$STATE"
mkdir -p "$MANAGED/original-nav-pages"
run_copy "$ORIGINAL_PAGE" "$MANAGED/address_book.htm"
if ((HAS_RETRO)); then run_copy "$RETRO_PAGE" "$MANAGED/retro-address_book.html"; fi
for original_nav in "$NAV_ORIGINALS"/*.htm; do
  [[ -e "$original_nav" ]] || continue
  run_copy "$TARGET/$(basename -- "$original_nav")" "$MANAGED/original-nav-pages/$(basename -- "$original_nav")"
done
if ((HAS_RETRO)); then run_copy "$RETRO_NAV" "$MANAGED/retro-navigation.js"; fi
if [[ -f "$ORIGINAL_ADDRESS_JS" ]]; then run_copy "$ORIGINAL_ADDRESS_JS" "$MANAGED/address_book.js"; fi
run_copy "$WEB_SERVER" "$MANAGED/web_server.py"
run_copy "$ADDRESS_MANAGER" "$MANAGED/stargate_address_manager.py"
run_copy "$MAINTENANCE" "$MANAGED/stellar_archive_maintenance.py"
run_copy "$ADDON_MANAGER" "$MANAGED/matelv_addon_manager.py"
run_copy "$ADDON_REGISTRY" "$MANAGED/matelv_addons.json"
printf '%s\n' "$MODE" > "$STATE/current-mode"
printf '1.5.22\n' > "$STATE/version"

updater="$STATE/updater"
mkdir -p "$updater/payload"
for file in install.sh install-v3.sh install-v4.sh patch_v3_main.py patch_v4_web_server.py patch_v4_gate_status.py patch_address_book_routes.py patch_navigation_links.py build_navigation.py adopt_managed_addon_changes.py stellar_archive_bridge.py stellar_archive_maintenance.py matelv_addon_manager.py matelv_addons.json validate_python_sources.py; do
  [[ -f "$SCRIPT_DIR/$file" ]] && run_copy "$SCRIPT_DIR/$file" "$updater/$file"
done
run_copy "$INTEGRATION_PAYLOAD" "$updater/payload/integration"
chmod 755 "$updater/install.sh" "$updater/install-v3.sh" "$updater/install-v4.sh"
cat > "$MAINTENANCE_CONFIG" <<EOF
{"version":"1.5.22","platform":"v4","target":"$TARGET","mode":"$MODE","repository":"matelv-x/Stellar-Archive","installer":"$updater/install.sh","restart_service":"$RESTART_SERVICE"}
EOF
chmod 644 "$MAINTENANCE_CONFIG"

note "Installed Stellar Archive 1.5.22 for SG1_v4 with replacement mode: $MODE"
if ((HAS_RETRO)); then note 'Detected interfaces: Original + Retro'; else note 'Detected interface: Original (Retro not installed)'; fi
if ((HAS_EXTENDED_RETRO)); then note 'Extended addresses: direct Retro dial9 routing enabled for Archive and Original address book'; fi
note "Archive URL: /stellar-archive/"
host_name="$(hostname -s 2>/dev/null || true)"
host_ip="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[[ -n "$host_ip" ]] && note "LAN URL: http://$host_ip/stellar-archive/"
[[ -n "$host_name" ]] && note "Local-name URL: http://$host_name.local/stellar-archive/"
note "Safety backup: $backup"
note 'Run this installer again to switch modes, or use --uninstall to restore the pre-install state.'
note 'Restart SG1_v4 once to activate the About update and uninstall controls.'
[[ ! -d "$ADDON_OVERLAY" ]] || remove_exact_tree "$ADDON_OVERLAY" "$STATE"
