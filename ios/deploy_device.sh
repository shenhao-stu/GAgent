#!/usr/bin/env bash
# Build, sign, install, and launch GAgent on a connected iPhone:
#   APPLE_TEAM_ID=XXXXXXXXXX bash ios/deploy_device.sh
#
# Configuration (none checked into Git):
#   Team ID         : $APPLE_TEAM_ID, $IOS_TEAM_ID, or ios/.team_id (Xcode -> Settings -> Accounts)
#   Bundle ID       : $IOS_BUNDLE_ID or ios/.bundle_id (defaults to io.github.shenhaostu.gagent.<team>)
#   Device UDID     : $IOS_DEVICE_UDID (defaults to the first connected physical iPhone in xctrace)
#   WITHOUT_WIDGETS : set WITHOUT_WIDGETS=1 on free Personal Team accounts if you hit the 3-App-ID weekly limit
set -euo pipefail
cd "$(dirname "$0")"

TEAM="${APPLE_TEAM_ID:-${IOS_TEAM_ID:-$(cat .team_id 2>/dev/null || true)}}"
[ -n "$TEAM" ] || { echo "Missing Team ID: export APPLE_TEAM_ID=XXXXXXXXXX or write ios/.team_id"; exit 1; }
DEFAULT_BUNDLE="io.github.shenhaostu.gagent.$(printf '%s' "$TEAM" | tr '[:upper:]' '[:lower:]')"
BUNDLE_ID="${IOS_BUNDLE_ID:-$(cat .bundle_id 2>/dev/null || echo "$DEFAULT_BUNDLE")}"

UDID="${IOS_DEVICE_UDID:-$(xcrun xctrace list devices 2>/dev/null \
  | sed -n '/^== Devices ==/,/^== /p' | sed '/^== Devices Offline/,$d' \
  | grep -oE '\(0000[0-9A-F]{4}-[0-9A-F]{16}\)' | tr -d '()' | head -1 || true)}"
[ -n "$UDID" ] || { echo "No online iPhone found: connect via USB, unlock the phone, and enable Developer Mode."; exit 1; }

SPEC="project.presence.yml"
if [ "${WITHOUT_WIDGETS:-0}" = "1" ]; then
  SPEC="project.presence-app.yml"
fi
echo "team=$TEAM bundle=$BUNDLE_ID device=$UDID spec=$SPEC"

[ -d Vendor/Python.xcframework ] || bash deps/get_python.sh
bash deps/get_python.sh gacore
xcodegen generate -s "$SPEC"

STAMP="$(date +%y%m%d%H%M)"
xcodebuild -project GAgentWithPresence.xcodeproj -scheme GAgent -configuration Debug \
  -destination "id=$UDID" \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration \
  -derivedDataPath build \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM="$TEAM" \
  GAGENT_APP_ID="$BUNDLE_ID" \
  CURRENT_PROJECT_VERSION="$STAMP" \
  build

APP=build/Build/Products/Debug-iphoneos/GAgent.app
xcrun devicectl device install app --device "$UDID" "$APP"
xcrun devicectl device process launch --terminate-existing --device "$UDID" "$BUNDLE_ID" || {
  echo "Launch blocked: unlock the iPhone; on first install trust your developer certificate in Settings -> General -> VPN & Device Management."
  exit 1
}
echo "done: $BUNDLE_ID installed and launched (asset stamp $STAMP)"
