#!/usr/bin/env bash
# Build and flash the ESP32-S3 BLE/USB HID bridge (requires arduino-cli + esp32:esp32 core 3.3.x + NimBLE-Arduino).
# Usage: bash ios/firmware/flash.sh [port] [--debug] [--build-only]
#   --debug       log commands on USB serial
#   --build-only  compile only (prints flash/RAM usage)
set -euo pipefail
cd "$(dirname "$0")"
FQBN="esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=cdc,FlashSize=8M,PSRAM=opi,PartitionScheme=default_8MB"
ports() { for p in /dev/cu.usbmodem* /dev/ttyACM*; do [[ -e $p ]] && echo "$p"; done; return 0; }
PORT="" DEFS="" BUILD_ONLY=0
for a in "$@"; do
  case $a in
    --debug) DEFS+=" -DDEBUG_SERIAL=1" ;;
    --build-only) BUILD_ONLY=1 ;;
    *) PORT=$a ;;
  esac
done
[[ $PWD != *" "* ]] || { echo "the -include path below cannot contain spaces: $PWD"; exit 1; }
DEFS+=" -include $PWD/hid_bridge/nimble_cfg.h"
FLAGS=(--build-property "compiler.cpp.extra_flags=$DEFS" --build-property "compiler.c.extra_flags=$DEFS")

arduino-cli compile -b "$FQBN" "${FLAGS[@]}" --output-dir build hid_bridge
(( BUILD_ONLY )) && exit 0
BEFORE=$(ports)
PORT=${PORT:-$(head -n 1 <<<"$BEFORE")}
[[ -n $PORT ]] || { echo "no board found (looked for /dev/cu.usbmodem* and /dev/ttyACM*)"; exit 1; }
stty -f "$PORT" 1200 2>/dev/null || stty -F "$PORT" 1200 2>/dev/null || true
new_ports() { comm -13 <(sort <<<"$BEFORE") <(ports | sort); }
for _ in $(seq 20); do sleep 0.5; [[ -n $(new_ports) ]] && break; done
sleep 1
NEW=$(new_ports)
case $(grep -c . <<<"$NEW" || true) in
  0) [[ -e $PORT ]] || { echo "$PORT is gone after the reset and no new port appeared"; exit 1; } ;;
  1) PORT=$NEW ;;
  *) echo "several ports appeared after the reset, not guessing:" $NEW; exit 1 ;;
esac
arduino-cli upload -b "$FQBN" -p "$PORT" --input-dir build hid_bridge
