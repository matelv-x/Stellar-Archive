#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
TARGET="$TEST_ROOT/sg1_v4/web"

cleanup() {
  if [[ -n "${TEST_ROOT:-}" && -d "$TEST_ROOT" ]]; then find "$TEST_ROOT" -depth -delete; fi
  return 0
}
trap cleanup EXIT

mkdir -p "$TARGET/retro/js" "$TARGET/stellar-archive" "$TARGET/js" "$TEST_ROOT/sg1_v4/classes"
cp "$PACKAGE_DIR/tests/fixtures/web_server.py" "$TEST_ROOT/sg1_v4/classes/web_server.py"
web_server_hash="$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/web_server.py" | awk '{print $1}')"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav><script src="/js/address_book.js"></script>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav>' > "$TARGET/index.htm"
printf 'RETRO PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a ${isActive('\''/retro/address_book.html'\'')}>Address Book</a><a href="/help.htm">Help</a></div>`;' > "$TARGET/retro/js/navigation.js"
touch "$TARGET/retro/dial.html" "$TARGET/retro/dial9.html"
printf '%s\n' 'function go(address_string) { window.location = '\''/stargate/dial?address='\'' + address_string; }' > "$TARGET/js/address_book.js"
touch "$TARGET/help.htm"
printf 'PREVIOUS ARCHIVE\n' > "$TARGET/stellar-archive/old.txt"

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
grep -q 'STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE' "$TARGET/js/address_book.js"
grep -q 'stellar_archive_addons' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'stellar_archive_addon_install' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'start_addon_install(self, data)' "$TEST_ROOT/sg1_v4/classes/web_server.py"
grep -q 'stellar_archive_restart' "$TEST_ROOT/sg1_v4/classes/web_server.py"
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
grep -q 'address_book.js?v=stellar-archive-1.5.6-extended-route' "$TARGET/address_book.htm"

# Reproduce the exact interrupted 1.3.0 validation state reported by ***:
# new Archive/API files are present, while state and managed snapshots still
# describe 1.2.8. The repair release must recover without manual deletion.
printf '1.2.8\n' > "$TARGET/.stellar-archive-addon/version"
perl -pi -e 's/sg1-universal-1\.5\.6/sg1-universal-1.3.0/g' "$TARGET/stellar-archive/index.html"
perl -pi -e 's/stellar-archive-1\.5\.6-extended-route/stellar-archive-1.3.0-extended-route/g' "$TARGET/address_book.htm" "$TARGET/js/address_book.js"
recovery_output="$("$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both)"
grep -q 'recover the interrupted 1.3.0 validation run' <<<"$recovery_output"
grep -q '^1.5.6$' "$TARGET/.stellar-archive-addon/version"
grep -q 'mode=original' "$TARGET/address_book.htm"
grep -q 'mode=retro' "$TARGET/retro/address_book.html"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
[[ ! -d "$TARGET/.stellar-archive-addon" ]]
[[ "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" = "$original_hash" ]]
[[ "$(shasum -a 256 "$TARGET/retro/address_book.html" | awk '{print $1}')" = "$retro_hash" ]]
[[ "$(shasum -a 256 "$TARGET/js/address_book.js" | awk '{print $1}')" = "$address_js_hash" ]]
[[ "$(shasum -a 256 "$TEST_ROOT/sg1_v4/classes/web_server.py" | awk '{print $1}')" = "$web_server_hash" ]]
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
