#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_PACKAGE="${STELLAR_ARCHIVE_V131_DIR:-$PACKAGE_DIR/../sg1-v3-v4-stellar-archive-universal-v1.3.1}"
if [[ ! -x "$OLD_PACKAGE/install.sh" ]]; then
  printf 'v1.3.1 upgrade tests: SKIP (set STELLAR_ARCHIVE_V131_DIR to an unpacked v1.3.1 package)\n'
  exit 0
fi
OLD_PACKAGE="$(cd -- "$OLD_PACKAGE" && pwd -P)"
TEST_ROOT="$(mktemp -d)"
TARGET="$TEST_ROOT/home/pi/sg1_v4/web"
cleanup() { [[ ! -d "$TEST_ROOT" ]] || find "$TEST_ROOT" -depth -delete; }
trap cleanup EXIT

mkdir -p "$TARGET/retro/js" "$TARGET/js" "$TEST_ROOT/home/pi/sg1_v4/classes"
cp "$PACKAGE_DIR/tests/fixtures/web_server.py" "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py"
cp "$PACKAGE_DIR/tests/fixtures/stargate_address_manager.py" "$TEST_ROOT/home/pi/sg1_v4/classes/stargate_address_manager.py"
printf '%s\n' '<nav><ul class="navbar-nav"><li><a href="address_book.htm">Address Book</a></li></ul></nav><script src="/js/address_book.js"></script>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li><a href="address_book.htm">Address Book</a></li></ul></nav>' > "$TARGET/index.htm"
printf 'RETRO PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a href="/retro/address_book.html">Address Book</a></div>`;' > "$TARGET/retro/js/navigation.js"
touch "$TARGET/retro/dial.html" "$TARGET/retro/dial9.html"
cp "$PACKAGE_DIR/tests/fixtures/address_book.js" "$TARGET/js/address_book.js"

original_page="$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')"
original_server="$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py" | awk '{print $1}')"

"$OLD_PACKAGE/install.sh" --target "$TARGET" --replace both >/dev/null
grep -q '^1.3.1$' "$TARGET/.stellar-archive-addon/version"
[[ ! -e "$TEST_ROOT/home/pi/sg1_v4/classes/matelv_addon_manager.py" ]]

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace both >/dev/null
grep -q '^1.5.25$' "$TARGET/.stellar-archive-addon/version"
[[ -f "$TEST_ROOT/home/pi/sg1_v4/classes/matelv_addon_manager.py" ]]
[[ -f "$TEST_ROOT/home/pi/sg1_v4/classes/matelv_addons.json" ]]
grep -q 'stellar_archive_addons' "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
[[ ! -e "$TEST_ROOT/home/pi/sg1_v4/classes/matelv_addon_manager.py" ]]
[[ ! -e "$TEST_ROOT/home/pi/sg1_v4/classes/matelv_addons.json" ]]
[[ "$original_page" = "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" ]]
[[ "$original_server" = "$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py" | awk '{print $1}')" ]]

printf 'v1.3.1 upgrade tests: PASS\n'
