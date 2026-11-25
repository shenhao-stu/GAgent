#!/usr/bin/env bash
# Host verification for Presence: Swift core, Python snapshot against the signed engine, and in-app strip.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
python="${PYTHON:-python3}"
mkdir -p "$here/build"
if ! swift test --package-path "$here" --build-path "$here/build/spm" > "$here/build/swift-test.log" 2>&1; then
  grep -E "error|failed" "$here/build/swift-test.log" || tail -20 "$here/build/swift-test.log"
  exit 1
fi
grep -E "Executed [0-9]+ tests" "$here/build/swift-test.log" | tail -1
( cd "$repo" && "$python" -m pytest -q ios/Presence/Tests/test_presence_snapshot.py ios/Presence/Tests/test_presence_actions.py )
node "$here/Tests/test_presence_web.cjs"
