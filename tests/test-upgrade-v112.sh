#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
TARGET="$TEST_ROOT/sg1_v4/web"
STATE="$TARGET/.stellar-archive-addon"

cleanup() {
  if [[ -n "${TEST_ROOT:-}" && -d "$TEST_ROOT" ]]; then find "$TEST_ROOT" -depth -delete; fi
  return 0
}
trap cleanup EXIT

mkdir -p "$TARGET/retro/js" "$TARGET/stellar-archive" "$STATE/originals" "$TEST_ROOT/sg1_v4/classes"
cp "$PACKAGE_DIR/tests/fixtures/web_server.py" "$TEST_ROOT/sg1_v4/classes/web_server.py"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav>' > "$TARGET/address_book.htm"
printf '%s\n' '<nav><ul class="navbar-nav"><li class="nav-item"><a class="nav-link" href="address_book.htm">Address Book</a></li><li class="nav-item"><a class="nav-link" href="help.htm">Help</a></li></ul></nav>' > "$TARGET/index.htm"
printf 'RETRO PAGE\n' > "$TARGET/retro/address_book.html"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a ${isActive('\''/retro/address_book.html'\'')}>Address Book</a><a href="/help.htm">Help</a></div>`;' > "$TARGET/retro/js/navigation.js"
printf 'OLD ARCHIVE\n' > "$TARGET/stellar-archive/old.txt"
touch "$TARGET/help.htm"

cp "$TARGET/address_book.htm" "$STATE/originals/address_book.htm"
cp "$TARGET/retro/address_book.html" "$STATE/originals/retro-address_book.html"
printf '0\n' > "$STATE/had-archive"
printf 'standalone\n' > "$STATE/current-mode"
printf '1.1.2\n' > "$STATE/version"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace standalone >/dev/null
grep -q '^1.3.1$' "$STATE/version"
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/address_book.htm"
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/index.htm"
grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/retro/js/navigation.js"

"$PACKAGE_DIR/install.sh" --target "$TARGET" --replace original >/dev/null
grep -q 'mode=original' "$TARGET/address_book.htm"
if grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/index.htm" "$TARGET/retro/js/navigation.js"; then
  printf 'Stand-alone link survived mode switch\n' >&2
  exit 1
fi

"$PACKAGE_DIR/install.sh" --target "$TARGET" --uninstall >/dev/null
grep -q 'Address Book' "$TARGET/address_book.htm"
if grep -q 'STELLAR_ARCHIVE_STANDALONE_LINK' "$TARGET/address_book.htm" "$TARGET/index.htm" "$TARGET/retro/js/navigation.js"; then
  printf 'Stand-alone link survived upgraded uninstall\n' >&2
  exit 1
fi

printf 'v1.1.2 upgrade tests: PASS\n'
