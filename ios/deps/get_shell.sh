#!/usr/bin/env bash
# Fetch built-in POSIX shell binaries for code_run (gitignored under ios/Vendor):
#   ios/Vendor/{ios_system,shell,files,text,awk,dash}.xcframework
#   ios/Vendor/shell/commandDictionary.plist
#   ios/Vendor/shell/bin/<command>
set -euo pipefail
cd "$(dirname "$0")/.."
RELEASES="https://github.com/holzschu/ios_system/releases/download"
FRAMEWORKS=(
  "v3.0.5/ios_system d429e68102926f58bedd8e8b7105dcd169478cd6da1cef494a5f468482d1c8f5"
  "v3.0.5/shell      855ff9b12bfbbdbd5298324377d91e18e6ac97dbb19d3c9311ce5a023ee51b2e"
  "v3.0.5/files      b0ee1f58c65ba306f178cd559fd6bce79ec8f275280526908c2a992bfcafedd5"
  "v3.0.5/text       6fed763c6e941817b2a2af2051871bdfb8a1af4177fad1ab7837f72023dffb79"
  "v3.0.5/awk        283f368df6c44ed9d49d15651ca4281706cdd86eb2b6ddb81808c8a3b18a4f7d"
  "Auxiliary/dash    9a30ac6b3780dd68d2268d10467902214e32333e980c59090faa6099f0d250fc"
)
DICTIONARY="v3.0.5/commandDictionary.plist"
DICTIONARY_SHA="7911fe0e7b1a9eb2c1ba761fe728fc3ede50093d29beb9735c0d8bb4201100b3"

DOWNLOADS="$(mktemp -d)"
trap 'rm -rf "$DOWNLOADS"' EXIT

fetch() {
  curl -fsSL "$RELEASES/$1" -o "$3"
  echo "$2  $3" | shasum -a 256 -c - >/dev/null || { echo "  !! SHA-256 mismatch: $1"; exit 1; }
}

echo "== Built-in shell: ios_system v3.0.5 + dash =="
mkdir -p Vendor/shell
for entry in "${FRAMEWORKS[@]}"; do
  read -r path checksum <<< "$entry"
  name="$(basename "$path")"
  if [ -d "Vendor/$name.xcframework" ]; then echo "  $name.xcframework (exists, skip)"; continue; fi
  fetch "$path.xcframework.zip" "$checksum" "$DOWNLOADS/$name.zip"
  unzip -q "$DOWNLOADS/$name.zip" -d Vendor
  echo "  -> Vendor/$name.xcframework"
done

if [ -f Vendor/shell/commandDictionary.plist ]; then echo "  Vendor/shell (exists, skip)"; exit 0; fi
fetch "$DICTIONARY" "$DICTIONARY_SHA" "$DOWNLOADS/commandDictionary.plist"
rm -rf Vendor/shell/bin && mkdir -p Vendor/shell/bin
python3 - "$DOWNLOADS/commandDictionary.plist" Vendor/shell <<'PY'
import pathlib
import plistlib
import sys

source, target = sys.argv[1], pathlib.Path(sys.argv[2])
with open(source, 'rb') as file:
    released = plistlib.load(file)

shipped = {'SELF'} | {f'{name}.framework/{name}' for name in ('shell', 'files', 'text', 'awk')}
unavailable = {'open', 'openurl'}
commands = {name: entry for name, entry in released.items()
            if entry[0] in shipped and name not in unavailable}
commands.update({
    'dash': ['dash.framework/dash', 'main', 'efIimnsxvVECabu', 'no'],
    'sleep': ['shell.framework/shell', 'sleep_main', '', 'none'],
    'basename': ['shell.framework/shell', 'basename_main', '', 'file'],
    'dirname': ['shell.framework/shell', 'dirname_main', '', 'file'],
    'realpath': ['shell.framework/shell', 'realpath_main', 'q', 'file'],
    'id': ['shell.framework/shell', 'id_main', '', 'no'],
    'base64': ['files.framework/files', 'base64_main', 'edtl', 'file'],
    'sha1': ['text.framework/text', 'md5_main', 'pqrs:tx', 'file'],
    'sha256': ['text.framework/text', 'md5_main', 'pqrs:tx', 'file'],
})
with open(target / 'commandDictionary.plist', 'wb') as file:
    plistlib.dump(commands, file)
for name in commands:
    (target / 'bin' / name).touch()
print(f'  -> Vendor/shell: {len(commands)} commands')
PY
