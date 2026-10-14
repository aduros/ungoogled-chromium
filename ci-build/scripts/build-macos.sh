#!/bin/bash
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
mkdir -p "$root/logs" "$root/dist"
exec > >(tee -a "$root/logs/build.log") 2>&1

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo 'This experiment requires an ARM Mac runner' >&2; exit 1;
}
[[ "$root" != *' '* && "${RUNNER_TEMP:?}" != *' '* ]] || {
  echo 'Chromium paths must not contain spaces' >&2; exit 1;
}
case "${VARIANT:?}" in explicit|short|both) ;; *) exit 2 ;; esac

# This is an operator budget, not an asserted/documented Chromium minimum.
python3 - "$RUNNER_TEMP" "${MIN_FREE_GIB:?}" "${BUILD_JOBS:?}" "$root/logs/jobs" <<'PY'
import os, shutil, subprocess, sys
free = shutil.disk_usage(sys.argv[1]).free / 1024**3
minimum = int(sys.argv[2]); requested = int(sys.argv[3])
if minimum < 1 or not 0 <= requested <= 256:
    raise SystemExit('Invalid resource configuration')
memory = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'])) / 1024**3
jobs = requested or max(1, min(os.cpu_count() or 1, int((memory - 4) / 3)))
print(f'Actual free disk: {free:.1f} GiB; operator budget: {minimum} GiB; RAM: {memory:.1f} GiB; jobs: {jobs}')
if free < minimum:
    raise SystemExit('Runner has insufficient headroom for the selected budget; no Chromium download started')
with open(sys.argv[4], 'w') as out:
    out.write(str(jobs))
PY
jobs="$(< "$root/logs/jobs")"
xcodebuild -version
sdk="$(xcrun --sdk macosx --show-sdk-version)"
python3 - "$sdk" <<'PY'
import sys
if int(sys.argv[1].split('.')[0]) < 15:
    raise SystemExit('Chromium 155 requires at least macOS SDK 15')
PY
command -v git
command -v codesign
command -v ditto
command -v xcrun

work="$(mktemp -d "$RUNNER_TEMP/window-buttons-ci.XXXXXX")"
echo "Build workspace: $work"
deadline="$(( $(date +%s) + 300 * 60 ))"
run() { python3 "$root/ci-build/scripts/deadline.py" "$deadline" "$@"; }
chromium_revision=3ff7ac5a9224be9156d7f8703a06e22890aafd34
chromium_version=155.0.8059.39
depot_revision=62e584abc425b8b79f3f346471cff217d9fe1853

mkdir "$work/depot_tools"
git -C "$work/depot_tools" init -q
git -C "$work/depot_tools" remote add origin https://chromium.googlesource.com/chromium/tools/depot_tools.git
run git -C "$work/depot_tools" fetch --depth=1 origin "$depot_revision"
git -C "$work/depot_tools" checkout --detach FETCH_HEAD
export PATH="$PATH:$work/depot_tools"
export DEPOT_TOOLS_UPDATE=0 DEPOT_TOOLS_METRICS=0
mkdir "$work/chromium"
cd "$work/chromium"
cat > .gclient <<'CONFIG'
solutions = [{
  "name": "src",
  "url": "https://chromium.googlesource.com/chromium/src.git",
  "managed": False,
  "deps_file": "DEPS",
  "custom_deps": {},
  "custom_vars": {"checkout_pgo_profiles": False},
}]
target_os = ["mac"]
CONFIG
run "$work/depot_tools/gclient" sync --no-history --shallow --revision="src@$chromium_revision"
cd src
[[ "$(git rev-parse HEAD)" == "$chromium_revision" ]]
python3 - "$chromium_version" <<'PY'
from pathlib import Path
import sys
values = dict(line.split('=', 1) for line in Path('chrome/VERSION').read_text().splitlines())
assert '.'.join(values[k] for k in ('MAJOR', 'MINOR', 'BUILD', 'PATCH')) == sys.argv[1]
PY
native=components/remote_cocoa/app_shim/browser_native_widget_window_mac.mm
cp "$native" "$work/native-original.mm"
patch_file="$root/ci-build/patches/window-buttons-ui.patch"
git apply --check "$patch_file"
git apply "$patch_file"
cp "$native" "$work/native-explicit.mm"

out=out/WindowButtonsCI
mkdir -p "$out"
cat > "$out/args.gn" <<'ARGS'
is_debug = false
is_component_build = false
is_official_build = false
target_cpu = "arm64"
symbol_level = 0
blink_symbol_level = 0
chrome_pgo_phase = 0
use_thin_lto = false
use_remoteexec = false
use_siso = false
enable_updater = false
ARGS
cp "$out/args.gn" "$root/logs/args.gn"
run "$work/depot_tools/gn" gen "$out" --fail-on-unused-args

variants=("$VARIANT")
if [[ "$VARIANT" == both ]]; then variants=(explicit short); fi
for variant in "${variants[@]}"; do
  if [[ "$variant" == short ]]; then
    python3 "$root/ci-build/scripts/variant.py" "$work/native-original.mm" "$native"
  else
    cp "$work/native-explicit.mm" "$native"
  fi
  git diff --binary > "$root/logs/source-$variant.patch"
  run "$work/depot_tools/autoninja" -C "$out" -j "$jobs" chrome chrome/installer/mac:mac

  signed="$work/signed-$variant"
  run python3 "$out/Chromium Packaging/sign_chrome.py" \
    --identity - --development --input "$out" --output "$signed" \
    --disable-packaging --notarize none
  app="$signed/Chromium.app"
  codesign --verify --deep --strict --verbose=2 "$app"
  codesign --display --verbose=4 "$app" 2> "$root/logs/signature-$variant.txt"
  grep -q '^Signature=adhoc$' "$root/logs/signature-$variant.txt"
  archs="$(lipo -archs "$app/Contents/MacOS/Chromium")"
  [[ "$archs" == arm64 ]]

  payload="$work/ChromiumWindowButtons-$variant"
  mkdir "$payload"
  ditto "$app" "$payload/Chromium.app"
  cp "$root/ci-build/scripts/launch-test.command" "$payload/launch-test.command"
  chmod +x "$payload/launch-test.command"
  cp "$root/ci-build/TESTING.md" "$payload/TESTING.md"
  cp "$root/logs/args.gn" "$payload/args.gn"
  cp "$root/logs/source-$variant.patch" "$payload/applied-source.patch"
  python3 - "$payload/build-info.json" "$chromium_version" "$chromium_revision" "$depot_revision" "$variant" "$sdk" "$patch_file" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
info = dict(zip(['version', 'chromium_revision', 'depot_tools_revision', 'variant', 'sdk'], sys.argv[2:7]))
info.update(ui_only=True, ungoogled_build=False, signing='ad-hoc', notarized=False,
            ci_commit=os.environ.get('GITHUB_SHA'), run_id=os.environ.get('GITHUB_RUN_ID'),
            patch_sha256=hashlib.sha256(Path(sys.argv[7]).read_bytes()).hexdigest())
Path(sys.argv[1]).write_text(json.dumps(info, indent=2) + '\n')
PY
  artifact="$root/dist/chromium-$chromium_version-arm64-$variant-ui-only.zip"
  ditto -c -k --sequesterRsrc --keepParent "$payload" "$artifact"
  (cd "$root/dist" && shasum -a 256 "$(basename "$artifact")" > "$(basename "$artifact").sha256")
  echo "Completed signed artifact: $artifact"
done

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo '# Signed test app artifacts'
    echo "Chromium $chromium_version, ARM64, variant: $VARIANT."
    echo 'Upstream Chromium + UI-only patch; not a full ungoogled build.'
    echo 'Ad-hoc signed, not notarized. Native visual testing was NOT run in CI.'
    echo 'Download the artifact and follow TESTING.md with a fresh profile.'
  } >> "$GITHUB_STEP_SUMMARY"
fi
# Remove only this script's private temporary checkout, after artifact creation.
rm -rf -- "$work"
