#!/bin/bash
# PEP 730 post-build dylib processor (Xcode build phase, invoked from project.yml postBuildScripts).
# Converts CPython .so extensions in Resources into signed Frameworks/<module>.framework with .fwork pointers.
set -euo pipefail

APP="$CODESIGNING_FOLDER_PATH"
PRIVACY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/privacy"
PYLIB_VER="$(ls -1 "$APP/python/lib" 2>/dev/null | head -1 || true)"

make_framework () {
    local install_base="$1" full_ext="$2"
    local rel_ext="${full_ext#"$APP"/}"
    local py_ext="${rel_ext#"$install_base"}"
    local module_name; module_name="$(echo "$py_ext" | cut -d "." -f 1 | tr "/" ".")"
    local fw_dir="Frameworks/$module_name.framework"
    local bundle_id; bundle_id="$(echo "$PRODUCT_BUNDLE_IDENTIFIER.$module_name" | tr "_" "-")"

    if [ ! -d "$APP/$fw_dir" ]; then
        mkdir -p "$APP/$fw_dir"
        cat > "$APP/$fw_dir/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>$module_name</string>
  <key>CFBundleIdentifier</key><string>$bundle_id</string>
  <key>CFBundleName</key><string>$module_name</string>
  <key>CFBundlePackageType</key><string>FMWK</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleSupportedPlatforms</key><array><string>iPhoneOS</string></array>
  <key>MinimumOSVersion</key><string>17.0</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
</dict>
</plist>
EOF
    fi
    mv "$full_ext" "$APP/$fw_dir/$module_name"
    echo "$fw_dir/$module_name" > "${full_ext%.so}.fwork"
    echo "${rel_ext%.so}.fwork" > "$APP/$fw_dir/$module_name.origin"
}

n=0
for base in "python/lib/$PYLIB_VER/lib-dynload/" "site-packages/"; do
    [ -n "$PYLIB_VER" ] && [ -d "$APP/$base" ] || continue
    while IFS= read -r so; do
        make_framework "$base" "$so"
        n=$((n+1))
    done < <(find "$APP/$base" -name '*.so')
done
echo "[process_dylibs] packaged $n .so extensions into Frameworks/"

for module_name in Python _hashlib _ssl cryptography.hazmat.bindings._rust; do
    fw="$APP/Frameworks/$module_name.framework"
    [ -d "$fw" ] || continue
    if [ "$module_name" = "Python" ]; then
        manifest="python.xcprivacy"
    else
        manifest="file-timestamp.xcprivacy"
    fi
    cp "$PRIVACY_DIR/$manifest" "$fw/PrivacyInfo.xcprivacy"
done

if [ "${CODE_SIGNING_ALLOWED:-YES}" != "NO" ] && [ -n "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]; then
    while IFS= read -r fw; do
        /usr/bin/codesign --force --sign "$EXPANDED_CODE_SIGN_IDENTITY" \
            ${OTHER_CODE_SIGN_FLAGS:-} --timestamp=none \
            --preserve-metadata=identifier,entitlements,flags \
            --generate-entitlement-der "$fw"
    done < <(find "$APP/Frameworks" -maxdepth 1 -name '*.framework')
    echo "[process_dylibs] signed Frameworks/*.framework ($EXPANDED_CODE_SIGN_IDENTITY)"
else
    echo "[process_dylibs] skipping code signing (CODE_SIGNING_ALLOWED=${CODE_SIGNING_ALLOWED:-?})"
fi
