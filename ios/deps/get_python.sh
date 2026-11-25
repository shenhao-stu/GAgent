#!/usr/bin/env bash
# Prepare iOS bundle dependencies (gitignored; run automatically by deploy_device.sh or before xcodegen):
#   ios/Vendor/Python.xcframework   BeeWare Python-Apple-support 3.13 (device + simulator slices)
#   ios/Resources/python/           PYTHONHOME: stdlib + arm64 lib-dynload from Python.xcframework
#   ios/Resources/site-packages/    Cross-target wheels (cp313-iphoneos): requests, websockets,
#                                   cryptography (PC Link X25519/AESGCM), Pillow, rubicon-objc, bs4, numpy, pip
#   ios/Resources/gacore/           Pruned signed iOS runtime staged from app/src/main/assets/ga_runtime
#   ios/Vendor/*.xcframework + ios/Vendor/shell/   Built-in POSIX shell via deps/get_shell.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ONLY_GACORE="${1:-}"
PYV="3.13"
PY_BUILD="${PY_BUILD:-b16}"
TAG="${PYV}-${PY_BUILD}"
mkdir -p Vendor Resources/site-packages

if [ "$ONLY_GACORE" != "gacore" ]; then
echo "== [1/4] Python.xcframework (BeeWare $TAG) =="
if [ ! -d Vendor/Python.xcframework ]; then
  URL="https://github.com/beeware/Python-Apple-support/releases/download/${TAG}/Python-${PYV}-iOS-support.${PY_BUILD}.tar.gz"
  echo "  fetch $URL"
  TMP_TAR="$(mktemp -t py-ios.XXXXXX.tar.gz)"
  trap 'rm -f "$TMP_TAR"' EXIT
  curl -fL "$URL" -o "$TMP_TAR"
  tar -xzf "$TMP_TAR" -C Vendor
  echo "  -> Vendor/Python.xcframework"
else
  echo "  (exists, skip)"
fi

echo "== [2/4] PYTHONHOME (stdlib) =="
SLICE="$(ls -d Vendor/Python.xcframework/ios-arm64* 2>/dev/null | grep -v simulator | head -1 || true)"
if [ -n "$SLICE" ] && [ -d Vendor/Python.xcframework/lib ] && [ -d "$SLICE/lib-arm64" ]; then
  rm -rf Resources/python && mkdir -p Resources/python/lib
  rsync -a --exclude 'libpython*.dylib' Vendor/Python.xcframework/lib/ Resources/python/lib/
  rsync -a --exclude 'libpython*.dylib' "$SLICE/lib-arm64/" Resources/python/lib/
  echo "  -> Resources/python/lib/python${PYV} (shared lib + $SLICE/lib-arm64)"
elif [ -n "$SLICE" ] && [ -d "$SLICE/lib" ]; then
  rm -rf Resources/python && mkdir -p Resources/python
  cp -R "$SLICE/lib" Resources/python/
  echo "  -> Resources/python/lib/python${PYV} (from $SLICE)"
else
  echo "  !! device slice lib missing — check xcframework layout"
fi
[ -d "Resources/python/lib/python${PYV}/encodings" ] || {
  echo "  !! Resources/python missing stdlib (encodings)"; exit 1;
}

echo "== [3/4] site-packages (pure-Python + iOS arm64 binary wheels) =="
rm -rf Resources/site-packages && mkdir -p Resources/site-packages
PIP_XTARGET=(--target Resources/site-packages --no-compile --only-binary=:all:
             --python-version 3.13 --implementation cp
             --abi cp313 --abi abi3 --abi none
             --platform ios_13_0_arm64_iphoneos)
python3 -m pip install "${PIP_XTARGET[@]}" \
  requests certifi urllib3 charset-normalizer idna websockets
python3 -m pip install "${PIP_XTARGET[@]}" \
  --extra-index-url https://pypi.anaconda.org/beeware/simple \
  "cryptography==47.0.0" || \
  echo "  !! cryptography iOS wheel install failed: PC Link pairing encryption will be unavailable"
python3 -m pip install "${PIP_XTARGET[@]}" \
  "pillow==13.0.0" "rubicon-objc==0.5.7" "beautifulsoup4==4.15.0" "pip==26.3" || \
  echo "  !! code_run helper libraries install failed (PIL / rubicon-objc / bs4 / pip)"
python3 -m pip install "${PIP_XTARGET[@]}" \
  --extra-index-url https://pypi.anaconda.org/beeware/simple \
  "numpy==2.5.2.post1" || \
  echo "  !! numpy iOS wheel install failed"
rm -rf Resources/site-packages/bin

BAD=""
while IFS= read -r so; do
  plat="$(otool -l "$so" 2>/dev/null | awk '/LC_BUILD_VERSION/{f=1} f&&$1=="platform"{print $2; exit}')"
  [ "$plat" = "2" ] || BAD="$BAD$so (platform=${plat:-?})"$'\n'
done < <(find Resources/site-packages -name '*.so')
if [ -n "$BAD" ]; then
  echo "  !! non-iOS Mach-O binaries detected in site-packages:"
  printf '%s' "$BAD"
  exit 1
fi
echo "  -> Resources/site-packages ($(du -sh Resources/site-packages | cut -f1))"
fi

bash deps/get_shell.sh

echo "== [4/4] Stage signed iOS runtime =="
rm -rf Resources/gacore && mkdir -p Resources/gacore
python3 deps/stage_runtime.py Resources/gacore
echo "  -> Resources/gacore ($(du -sh Resources/gacore | cut -f1), signed iOS host)"
