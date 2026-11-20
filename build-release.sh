#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'invalid VERSION: %s\n' "$VERSION" >&2; exit 1; }

OUTPUT_DIR="${1:-$ROOT/dist}"
PACKAGE="sg1_v3_v4_stellar_archive_universal_${VERSION}.zip"
PREFIX="sg1-v3-v4-stellar-archive-universal-v${VERSION}"
mkdir -p "$OUTPUT_DIR"

git -C "$ROOT" archive --format=zip --prefix="${PREFIX}/" --output="$OUTPUT_DIR/$PACKAGE" HEAD
python3 - "$OUTPUT_DIR/$PACKAGE" "$PREFIX" <<'PY'
import sys
import zipfile

archive_path, prefix = sys.argv[1:]
with zipfile.ZipFile(archive_path) as archive:
    names = archive.namelist()
expected = prefix + "/install.sh"
installers = [name for name in names if name.endswith("/install.sh")]
if installers != [expected]:
    raise SystemExit("release ZIP must contain exactly {} (found {})".format(expected, installers))
if any(not name.startswith(prefix + "/") for name in names):
    raise SystemExit("release ZIP contains a path outside its versioned top-level directory")
PY

digest="$(shasum -a 256 "$OUTPUT_DIR/$PACKAGE" | awk '{print $1}')"
printf '%s  %s\n' "$digest" "$PACKAGE" > "$OUTPUT_DIR/$PACKAGE.sha256"
printf 'Built %s\nSHA-256 %s\n' "$OUTPUT_DIR/$PACKAGE" "$digest"
