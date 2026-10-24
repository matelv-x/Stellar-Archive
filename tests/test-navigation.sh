#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEST_ROOT="$(mktemp -d)"
TARGET="$TEST_ROOT/web"
OUTPUT="$TEST_ROOT/integration-nav.js"

cleanup() {
  if [[ -n "${TEST_ROOT:-}" && -d "$TEST_ROOT" ]]; then find "$TEST_ROOT" -depth -delete; fi
  return 0
}
trap cleanup EXIT

mkdir -p "$TARGET/retro/js"
printf '%s\n' '<nav><a class="navbar-brand" href="/">Stargate Command</a><a class="nav-link" href="index.htm">Home</a><a class="nav-link" href="address_book.htm">Address Book</a><a class="nav-link" href="symbol_overview.htm">Symbols</a><a class="nav-link" href="alarm_clock.htm">Alarm Clock</a><a class="nav-link" href="help.htm">Help</a></nav>' > "$TARGET/address_book.htm"
touch "$TARGET/index.htm" "$TARGET/symbol_overview.htm" "$TARGET/help.htm"
printf '%s\n' 'div.innerHTML = `<div class="navigation-menu"><a href="/">Home</a><a href="/alarm_clock.htm">Alarm Clock</a><a class="a-refresh">Refresh</a><a class="a-fullscreen">Full Screen</a></div>`;' > "$TARGET/retro/js/navigation.js"

python3 "$PACKAGE_DIR/build_navigation.py" --target "$TARGET" --mode original --output "$OUTPUT" >/dev/null
grep -q '"HOME"' "$OUTPUT"
grep -q '"dialTarget":"original"' "$OUTPUT"
if grep -q 'ALARM CLOCK' "$OUTPUT"; then
  printf 'Alarm Clock was detected without its installed page\n' >&2
  exit 1
fi

touch "$TARGET/alarm_clock.htm"
python3 "$PACKAGE_DIR/build_navigation.py" --target "$TARGET" --mode both --output "$OUTPUT" >/dev/null
grep -q 'ALARM CLOCK' "$OUTPUT"
if grep -Eq 'REFRESH|FANCY MODE|FULL SCREEN|"action":"(refresh|fancy|fullscreen)"' "$OUTPUT"; then
  printf 'Excluded Retro controls leaked into Archive navigation\n' >&2
  exit 1
fi

printf '%s\n' '<script type="module" src="js/iris.js"></script>' > "$TARGET/retro/dial.html"
touch "$TARGET/retro/dial9.html"
touch "$TARGET/retro/js/iris.js"
python3 "$PACKAGE_DIR/build_navigation.py" --target "$TARGET" --mode retro --output "$OUTPUT" >/dev/null
grep -q '"dialTarget":"retro"' "$OUTPUT"
if grep -q 'CLOSE IRIS' "$OUTPUT"; then
  printf 'Iris shortcut leaked into Archive navigation\n' >&2
  exit 1
fi

printf 'navigation detection tests: PASS\n'
