#!/usr/bin/env bash
# 在 iOS 模拟器里用真实的 ios_system + dash 二进制检验 GAgent/ShellBridge.m(内置 shell 的运行、取消与已知限制)。
# 用法: bash ios/tests/shell_harness.sh [模拟器 UDID]   需要 deps/get_shell.sh 已取回 Vendor, 以及一个 arm64 模拟器运行时。
# dash 只发布了真机 arm64 切片: 这里把它的平台标记改成模拟器再临时签名, 机器码不变, 仅供本检验使用。
set -euo pipefail
cd "$(dirname "$0")/.."
DEVICE="${1:-$(xcrun simctl list devices available | grep -oE '[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}' | head -1)}"
[ -n "$DEVICE" ] || { echo "没有可用的模拟器"; exit 1; }
[ -f Vendor/shell/commandDictionary.plist ] || bash deps/get_shell.sh

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/Frameworks"
for name in ios_system shell files text awk; do
  cp -R "Vendor/$name.xcframework/ios-arm64_x86_64-simulator/$name.framework" "$BUILD/Frameworks/"
done
cp -R Vendor/dash.xcframework/ios-arm64/dash.framework "$BUILD/Frameworks/"
xcrun vtool -set-build-version iossim 14.0 16.2 -replace \
  -output "$BUILD/Frameworks/dash.framework/dash" "$BUILD/Frameworks/dash.framework/dash" >/dev/null
codesign -f -s - "$BUILD/Frameworks/dash.framework" 2>/dev/null
cp Vendor/shell/commandDictionary.plist "$BUILD/"
cp -R Vendor/shell/bin "$BUILD/bin"
xcrun --sdk iphonesimulator clang -arch arm64 -mios-simulator-version-min=17.0 -fobjc-arc -framework Foundation \
  tests/shell_harness.m GAgent/ShellBridge.m -o "$BUILD/harness" -Wl,-rpath,@executable_path/Frameworks
codesign -f -s - "$BUILD/harness" 2>/dev/null

xcrun simctl bootstatus "$DEVICE" -b >/dev/null
# 命令行工具方式启动: 主 bundle 即 $BUILD, 与 App 里 Frameworks/、commandDictionary.plist、bin/ 的相对位置一致。
xcrun simctl spawn "$DEVICE" "$BUILD/harness" 2>/dev/null
