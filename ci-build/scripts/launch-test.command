#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
mode="${1:-hidden}"
case "$mode" in
  hidden|visible) ;;
  *) echo 'Usage: launch-test.command [hidden|visible]' >&2; exit 2 ;;
esac
profile="$(mktemp -d "${TMPDIR:?TMPDIR must be set}/window-buttons-${mode}.XXXXXX")"
printf 'Fresh test profile: %s\nMode: %s\n' "$profile" "$mode"
args=(
  "--user-data-dir=$profile"
  --use-mock-keychain
  --no-first-run
  --disable-background-networking
  --disable-component-update
  --disable-sync
)
if [[ "$mode" == hidden ]]; then
  args+=(--hide-window-buttons)
fi
exec "$root/Chromium.app/Contents/MacOS/Chromium" "${args[@]}" about:blank
