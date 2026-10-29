#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
TARGET="$TEST_ROOT/sg1_v4/web"

if grep -Eq 'RewriteCond.*HTTP_HOST' "$PACKAGE_DIR/payload/stellar-archive/.htaccess"; then
  printf 'public Archive payload contains a deployment-specific host redirect\n' >&2
  exit 1
fi

cleanup() {
  if [[ -n "${TEST_ROOT:-}" && -d "$TEST_ROOT" ]]; then find "$TEST_ROOT" -depth -delete; fi
  return 0
}
trap cleanup EXIT

mkdir -p "$TARGET/retro/js" "$TARGET/stellar-archive" "$TARGET/js" "$TEST_ROOT/sg1_v4/classes"
cp "$PACKAGE_DIR/tests/fixtures/web_server.py" "$TEST_ROOT/sg1_v4/classes/web_server.py"
cp "$PACKAGE_DIR/tests/fixtures/stargate_address_manager.py" "$TEST_ROOT/sg1_v4/classes/stargate_address_manager.py"
web_server_hash="$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/web_server.py" | awk '{print $1}')"
address_manager_hash="$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/stargate_address_manager.py" | awk '{print $1}')"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav><script src="/js/address_book.js"></script>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav>' > "$TARGET/index.htm"
printf 'RETRO PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a ${isActive('\''/retro/address_book.html'\'')}>Address Book</a><a href="/help.htm">Help</a></div>`;' > "$TARGET/retro/js/navigation.js"
touch "$TARGET/retro/dial.html" "$TARGET/retro/dial9.html"
cp "$PACKAGE_DIR/tests/fixtures/address_book.js" "$TARGET/js/address_book.js"
touch "$TARGET/help.htm"
printf 'PREVIOUS ARCHIVE\n' > "$TARGET/stellar-archive/old.txt"
ln -s index.html "$TARGET/stellar-archive/fan113.html"

original_hash="$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')"
retro_hash="$(shasum -a 256 "$TARGET/retro/address_book.html" | awk '{print $1}')"
address_js_hash="$(shasum -a 256 "$TARGET/js/address_book.js" | awk '{print $1}')"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace original --dry-run >/dev/null
[[ ! -d "$TARGET/.stellar-archive-addon" ]]
[[ "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" = "$original_hash" ]]

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace original >/dev/null
grep -q 'mode=original' "$TARGET/address_book.htm"
[[ "$(shasum -a 256 "$TARGET/retro/address_book.html" | awk '{print $1}')" = "$retro_hash" ]]
[[ -f "$TARGET/stellar-archive/index.html" ]]
[[ -L "$TARGET/stellar-archive/fan113.html" ]]
[[ "$(readlink "$TARGET/stellar-archive/fan113.html")" = 'index.html' ]]
grep -q 'STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE' "$TARGET/js/address_book.js"
grep -q 'stellar_archive_addons' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'stellar_archive_addon_install' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'start_addon_install(self, data)' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'stellar_archive_restart' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'STELLAR_ARCHIVE_GATE_STATUS_BEGIN' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'STELLAR_ARCHIVE_DIRECTORY_RETRY_BEGIN' "$TEST_ROOT/sg1_v4/classes/stargate_address_manager.py"
grep -q 'STELLAR_ARCHIVE_GATE_STATUS START' "$TARGET/js/address_book.js"
grep -q "status_freshness" "$TARGET/js/address_book.js"
grep -q 'maintenance_contract' "$TEST_ROOT/sg1_v4/classes/matelv_addon_manager.py"
python3 -m json.tool "$TEST_ROOT/sg1_v4/classes/matelv_addons.json" >/dev/null
python3 -c 'import json,sys; assert "restart_service" in json.load(open(sys.argv[1]))' "$TEST_ROOT/sg1_v4/classes/.stellar-archive-maintenance.json"
grep -q '"dialTarget":"original"' "$TARGET/stellar-archive/data/integration-nav.js"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace retro >/dev/null
[[ "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" = "$original_hash" ]]
grep -q 'mode=retro' "$TARGET/retro/address_book.html"
grep -q '"dialTarget":"retro"' "$TARGET/stellar-archive/data/integration-nav.js"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both >/dev/null
grep -q 'mode=original' "$TARGET/address_book.htm"
grep -q 'mode=retro' "$TARGET/retro/address_book.html"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
[[ "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" = "$original_hash" ]]
[[ "$(shasum -a 256 "$TARGET/retro/address_book.html" | awk '{print $1}')" = "$retro_hash" ]]
[[ -f "$TARGET/stellar-archive/index.html" ]]
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/address_book.htm"
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/index.htm"
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/retro/js/navigation.js"
grep -q '"dialTarget":"retro"' "$TARGET/stellar-archive/data/integration-nav.js"
grep -q 'symbolCount > 6 ? "/retro/dial9.html" : "/retro/dial.html"' "$TARGET/js/address_book.js"
grep -q 'address_book.js?v=stellar-archive-1.5.19-status' "$TARGET/address_book.htm"

# A managed add-on installed after Archive may legitimately extend the shared
# backend and Retro navigation. A later Archive update must preserve those
# declared files while retaining strict validation for everything else.
touch "$TARGET/retro/js/retro_visuals.js" "$TARGET/retro/visual_settings.html"
printf '\n# RETRO_VISUALS_TEST_BACKEND\n' >> "$TEST_ROOT/sg1_v4/classes/web_server.py"
printf '\nconst retroVisualsTest = `<a href="/retro/visual_settings.html">Visuals</a>`;\n' >> "$TARGET/retro/js/navigation.js"
printf '%s\n' '{"retro-visuals":{"repository":"matelv-x/Retro-Visuals","revision":"491a406144d3c119145fa9fe476ab10d9af06e35"}}' > "$TEST_ROOT/sg1_v4/classes/.matelv-addon-state.json"
addon_update_output="$("$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both)"
grep -q 'Accepted installed add-on integration: classes/web_server.py' <<<"$addon_update_output"
grep -q 'RETRO_VISUALS_TEST_BACKEND' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'retroVisualsTest' "$TARGET/retro/js/navigation.js"
grep -q '"label":"VISUALS"' "$TARGET/stellar-archive/data/integration-nav.js"

# A stale overlay left by an older interrupted/dry-run installer must never be
# replayed after a surgical add-on uninstall. New operations use a unique path.
mkdir -p "$TARGET/.stellar-archive-addon/addon-overlay/classes"
cp "$TEST_ROOT/sg1_v4/classes/web_server.py" "$TARGET/.stellar-archive-addon/addon-overlay/classes/web_server.py"
printf '\n# STALE_FIXED_OVERLAY_MUST_NOT_RETURN\n' >> "$TARGET/.stellar-archive-addon/addon-overlay/classes/web_server.py"
"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both >/dev/null
if grep -q 'STALE_FIXED_OVERLAY_MUST_NOT_RETURN' "$TEST_ROOT/sg1_v4/classes/web_server.py"; then
  printf 'stale fixed add-on overlay was replayed\n' >&2
  exit 1
fi

# The original pre-Archive snapshot may contain an add-on that was removed
# later. A normal Archive update must keep the clean current backend rather than
# restoring that historical hook from originals.
printf '\n# REMOVED_ADDON_HISTORICAL_HOOK\n' >> "$TARGET/.stellar-archive-addon/originals/web_server.py"
"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both >/dev/null
if grep -q 'REMOVED_ADDON_HISTORICAL_HOOK' "$TEST_ROOT/sg1_v4/classes/web_server.py"; then
  printf 'normal update restored a removed add-on from originals\n' >&2
  exit 1
fi
perl -ni -e 'print unless /REMOVED_ADDON_HISTORICAL_HOOK/' "$TARGET/.stellar-archive-addon/originals/web_server.py"

# Reproduce the exact interrupted 1.3.0 validation state reported by ***:
# new Archive/API files are present, while state and managed snapshots still
# describe 1.2.8. The repair release must recover without manual deletion.
printf '1.2.8\n' > "$TARGET/.stellar-archive-addon/version"
perl -pi -e 's/sg1-universal-1\.5\.19/sg1-universal-1.3.0/g' "$TARGET/stellar-archive/index.html"
perl -pi -e 's/stellar-archive-1\.5\.19-status/stellar-archive-1.3.0-extended-route/g' "$TARGET/address_book.htm" "$TARGET/js/address_book.js"
recovery_output="$("$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both)"
grep -q 'recover the interrupted 1.3.0 validation run' <<<"$recovery_output"
grep -q '^1.5.19$' "$TARGET/.stellar-archive-addon/version"
grep -q 'mode=original' "$TARGET/address_book.htm"
grep -q 'mode=retro' "$TARGET/retro/address_book.html"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
[[ ! -d "$TARGET/.stellar-archive-addon" ]]
[[ "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" = "$original_hash" ]]
[[ "$(shasum -a 256 "$TARGET/retro/address_book.html" | awk '{print $1}')" = "$retro_hash" ]]
[[ "$(shasum -a 256 "$TARGET/js/address_book.js" | awk '{print $1}')" = "$address_js_hash" ]]
[[ "$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/web_server.py" | awk '{print $1}')" = "$web_server_hash" ]]
[[ "$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/stargate_address_manager.py" | awk '{print $1}')" = "$address_manager_hash" ]]
[[ ! -e "$TEST_ROOT/sg1_v4/classes/stellar_archive_maintenance.py" ]]
grep -q 'PREVIOUS ARCHIVE' "$TARGET/stellar-archive/old.txt"
if grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/address_book.htm" "$TARGET/index.htm" "$TARGET/retro/js/navigation.js"; then
  printf 'Stand-alone navigation link survived uninstall\n' >&2
  exit 1
fi

if "$PACKAGE_DIR/install.sh" --target / --replace none --dry-run >/dev/null 2>&1; then
  printf 'unsafe target was accepted\n' >&2
  exit 1
fi

printf 'installer tests: PASS\n'
