#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TEMP="$(mktemp -d)"
trap 'find "$TEMP" -depth -delete' EXIT
TARGET="$TEMP/home/sg1/sg1"
mkdir -p "$TARGET/classes"

cat > "$TARGET/main.py" <<'PY'
from helper_functions import log
from classes.STARGATE_SG1 import StargateSG1
stargate = StargateSG1()
stargate.update()
PY
cat > "$TARGET/classes/STARGATE_SG1.py" <<'PY'
class StargateSG1:
    pass
PY

before="$(shasum -a 256 "$TARGET/main.py" | awk '{print $1}')"
dry_run_output="$("$ROOT/install.sh" --target "$TARGET" --dry-run)"
grep -q 'Detected platform: SG1_v3' <<<"$dry_run_output"
[[ ! -e "$TARGET/stellar-archive" ]]

"$ROOT/install.sh" --target "$TARGET"
grep -q 'STELLAR_ARCHIVE_BRIDGE_BEGIN' "$TARGET/main.py"
grep -q '"dialTarget":"v3"' "$TARGET/stellar-archive/data/integration-nav.js"
grep -q '^1.5.2$' "$TARGET/.stellar-archive-addon-v3/version"
grep -q 'stellar_archive_addons' "$TARGET/stellar_archive_bridge.py"
grep -q 'maintenance_contract' "$TARGET/matelv_addon_manager.py"
python3 -m json.tool "$TARGET/matelv_addons.json" >/dev/null
python3 -m py_compile "$TARGET/main.py" "$TARGET/stellar_archive_bridge.py"

"$ROOT/install.sh" --target "$TARGET"
[[ "$(grep -c 'STELLAR_ARCHIVE_BRIDGE_BEGIN' "$TARGET/main.py")" = 1 ]]

"$ROOT/install.sh" --target "$TARGET" --uninstall
after="$(shasum -a 256 "$TARGET/main.py" | awk '{print $1}')"
[[ "$before" = "$after" ]]
[[ ! -e "$TARGET/stellar_archive_bridge.py" ]]
[[ ! -e "$TARGET/stellar-archive" ]]
[[ ! -e "$TARGET/.stellar-archive-addon-v3" ]]

printf 'SG1_v3 installer tests: PASS\n'
