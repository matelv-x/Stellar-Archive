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

mkdir -p "$TARGET/js" "$TEST_ROOT/sg1_v4/classes"
cp "$PACKAGE_DIR/tests/fixtures/web_server.py" "$TEST_ROOT/sg1_v4/classes/web_server.py"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav><script src="/js/address_book.js"></script>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav>' > "$TARGET/index.htm"
touch "$TARGET/help.htm"
printf '%s\n' 'function go(address_string) { window.location = '\''index.htm?address='\'' + address_string; }' > "$TARGET/js/address_book.js"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/address_book.htm" "$TARGET/index.htm"
[[ ! -e "$TARGET/retro" ]]
grep -q 'return `/index.htm?address=' "$TARGET/stellar-archive/app.js"
grep -q '"dialTarget":"original"' "$TARGET/stellar-archive/data/integration-nav.js"

if "$PACKAGE_DIR/install.sh" --target "$TARGET" --replace retro --dry-run >/dev/null 2>&1; then
  printf 'Retro mode was accepted without Retro installed\n' >&2
  exit 1
fi

# Retro may be installed later; the same Archive installation must adopt it.
mkdir -p "$TARGET/retro/js"
printf 'RETRO ADDRESS PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a ${isActive('\''/retro/address_book.html'\'')}>Address Book</a></div>`;' > "$TARGET/retro/js/navigation.js"
touch "$TARGET/retro/dial.html" "$TARGET/retro/dial9.html"
"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/retro/js/navigation.js"
[[ -f "$TARGET/.stellar-archive-addon/originals/retro-address_book.html" ]]
grep -q '"dialTarget":"retro"' "$TARGET/stellar-archive/data/integration-nav.js"
grep -q 'STELLAR_ARCHIVE_EXTENDED_ADDRESS_ROUTE' "$TARGET/js/address_book.js"
grep -q 'address_book.js?v=stellar-archive-1.5.0-extended-route' "$TARGET/address_book.htm"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace original >/dev/null
grep -q 'mode=original' "$TARGET/address_book.htm"
if grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/index.htm" "$TARGET/retro/js/navigation.js"; then
  printf 'Stand-alone link survived Original mode switch\n' >&2
  exit 1
fi

"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
grep -q 'Address Book' "$TARGET/address_book.htm"
grep -q 'RETRO ADDRESS PAGE' "$TARGET/retro/address_book.html"

printf 'Original-only compatibility tests: PASS\n'
