#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PLATFORM="auto"
TARGET=""
FORWARDED=()

usage() {
  cat <<'EOF'
Stellar Archive universal SG1_v3 / SG1_v4 installer

Usage:
  ./install.sh [--platform auto|v3|v4] [platform options]

Automatic detection checks the supplied --target first, then the standard
SG1_v4 and SG1_v3 installation paths. SG1_v4 retains the Original, Retro,
Both and Stand-alone choices. SG1_v3 installs its required stand-alone web
bridge because that release has no native web address book to replace.

Common options:
  --platform NAME  auto (default), v3, or v4
  --target PATH    v4 web root or v3 application root
  --dry-run        validate without changing files
  --uninstall      restore the captured pre-install state
  --help           show this help

SG1_v4 additionally accepts --replace original|retro|both|standalone.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

while (($#)); do
  case "$1" in
    --platform)
      (($# >= 2)) || die '--platform needs auto, v3, or v4'
      PLATFORM="$2"
      shift 2
      ;;
    --target)
      (($# >= 2)) || die '--target needs a path'
      TARGET="$2"
      FORWARDED+=("$1" "$2")
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      FORWARDED+=("$1")
      shift
      ;;
  esac
done

case "$PLATFORM" in auto|v3|v4) ;; *) die "invalid platform: $PLATFORM" ;; esac

if [[ "$PLATFORM" = auto && -n "$TARGET" ]]; then
  if [[ -f "$TARGET/main.py" && -f "$TARGET/classes/STARGATE_SG1.py" ]]; then
    PLATFORM=v3
  elif [[ -f "$TARGET/address_book.htm" ]]; then
    PLATFORM=v4
  else
    die "cannot identify SG1 version at target: $TARGET"
  fi
fi

if [[ "$PLATFORM" = auto ]]; then
  if [[ -f /home/pi/sg1_v4/web/address_book.htm && -d /home/pi/sg1_v4/web/js ]]; then
    PLATFORM=v4
  elif [[ -f /home/sg1/sg1/main.py && -f /home/sg1/sg1/classes/STARGATE_SG1.py ]]; then
    PLATFORM=v3
  else
    die 'no supported SG1_v3 or SG1_v4 installation was detected; use --target or --platform'
  fi
fi

printf 'Detected platform: SG1_%s\n' "$PLATFORM"
case "$PLATFORM" in
  v3) exec "$SCRIPT_DIR/install-v3.sh" "${FORWARDED[@]}" ;;
  v4) exec "$SCRIPT_DIR/install-v4.sh" "${FORWARDED[@]}" ;;
esac
