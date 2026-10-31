#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
OLD_PACKAGE="${STELLAR_ARCHIVE_V1513_DIR:-$PACKAGE_DIR/../sg1-v3-v4-stellar-archive-universal-v1.5.13}"
if [[ ! -x "$OLD_PACKAGE/install.sh" ]]; then
  printf 'v1.5.13 upgrade tests: SKIP (set STELLAR_ARCHIVE_V1513_DIR to an unpacked v1.5.13 package)\n'
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
cp "$PACKAGE_DIR/tests/fixtures/address_book.js" "$TARGET/js/address_book.js"
printf '%s\n' '<nav><ul class="navbar-nav"><li><a href="address_book.htm">Address Book</a></li></ul></nav><script src="/js/address_book.js"></script>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li><a href="address_book.htm">Address Book</a></li></ul></nav>' > "$TARGET/index.htm"
printf 'RETRO PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a ${isActive('\''/retro/address_book.html'\'')}>Address Book</a></div>`;' > "$TARGET/retro/js/navigation.js"
touch "$TARGET/retro/dial.html" "$TARGET/retro/dial9.html"

original_page="$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')"
original_script="$(shasum -a 256 "$TARGET/js/address_book.js" | awk '{print $1}')"
original_server="$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py" | awk '{print $1}')"
original_manager="$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/stargate_address_manager.py" | awk '{print $1}')"

"$OLD_PACKAGE/install.sh" --target "$TARGET" --replace standalone >/dev/null
grep -q '^1.5.13$' "$TARGET/.stellar-archive-addon/version"
if grep -q 'STELLAR_ARCHIVE_GATE_STATUS' "$TARGET/js/address_book.js" "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py"; then
  printf 'v1.5.13 unexpectedly contains the gate-status freshness fix\n' >&2
  exit 1
fi

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
grep -q '^1.5.23$' "$TARGET/.stellar-archive-addon/version"
grep -q 'STELLAR_ARCHIVE_GATE_STATUS START' "$TARGET/js/address_book.js"
grep -q 'STELLAR_ARCHIVE_GATE_STATUS_BEGIN' "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py"
grep -q 'STELLAR_ARCHIVE_DIRECTORY_RETRY_BEGIN' "$TEST_ROOT/home/pi/sg1_v4/classes/stargate_address_manager.py"
grep -q 'address_book.js?v=stellar-archive-1.5.23-status' "$TARGET/address_book.htm"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
[[ "$original_page" = "$(shasum -a 256 "$TARGET/address_book.htm" | awk '{print $1}')" ]]
[[ "$original_script" = "$(shasum -a 256 "$TARGET/js/address_book.js" | awk '{print $1}')" ]]
[[ "$original_server" = "$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/web_server.py" | awk '{print $1}')" ]]
[[ "$original_manager" = "$(shasum -a 256 "$TEST_ROOT/home/pi/sg1_v4/classes/stargate_address_manager.py" | awk '{print $1}')" ]]

printf 'v1.5.13 upgrade tests: PASS\n'
