"""Verify the iOS bridge implements shared WebUI calls without advertising absent Android services."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IOS_BRIDGE = ROOT / "ios" / "GAgent" / "ios_bridge.js"
from signed_runtime import HOST
WEBUI = HOST / "webui"
MAINACT = ROOT / "app/src/main/java/com/ljq/ga/MainActivity.kt"


def ios_methods():
    src = IOS_BRIDGE.read_text(encoding="utf-8")
    i = src.index("window.GA = {") + len("window.GA = {")
    depth, keys, j = 1, set(), i
    while j < len(src) and depth > 0:
        ch = src[j]
        if ch in "{[(": depth += 1
        elif ch in "}])": depth -= 1
        elif depth == 1:
            m = re.match(r"\s*([A-Za-z_]\w*)\s*:", src[j:])
            if m: keys.add(m.group(1)); j += m.end() - 1
        j += 1
    return keys


def demanded():
    calls = set()
    for f in WEBUI.rglob("*.js"):
        calls |= set(re.findall(r"\bGA\.(\w+)\s*\(", f.read_text(encoding="utf-8", errors="replace")))
    return calls


def kotlin_methods():
    src = MAINACT.read_text(encoding="utf-8")
    return set(re.findall(r"@JavascriptInterface\s+fun\s+(\w+)\s*\(", src))


# Android-only services (accessibility, overlay float, OTA, self-ADB, GAnet mesh, etc.)
# are omitted from the signed Apple bridge. Any unclassified call fails this contract.
ABSENT_ON_IOS = set("""
    otaChannel otaManifest otaSetChannel otaDownload otaProgress otaInstall
    float floatState floatAlwaysOn setFloatAlwaysOn setFloatOpacity requestOverlayPerm openBrowser
    a11yEnabled openA11ySettings a11yPersistStatus setA11yPersist a11yReEnableNow
    a11yGrantViaSelfAdb a11yGrantResult adbSelfStatus openAdbDevSettings
    sttStart sttSend sttPoll sttStop sttCancel asrProbe asrStart asrPoll asrStop asrCancel
    offAsrDownload offAsrWav openPlanWeb openCamera renderHtmlToImage renderHtmlResult captureChat
    pdfRender pdfResult getNotifications replyNotification dismissNotification
    dismissNotificationsByPackage isNotificationServiceEnabled
    scanGanetQr ganetQrStatus
""".split())


def main():
    ios = ios_methods()
    forbidden = ios & ABSENT_ON_IOS
    if forbidden:
        sys.exit('Unsupported bridge methods exposed on iOS: ' + ', '.join(sorted(forbidden)))
    contract = (demanded() | kotlin_methods()) - ABSENT_ON_IOS
    missing = sorted(m for m in contract if m not in ios)
    print("ios_bridge.js 顶层暴露 %d 方法; 应有方法 %d" % (len(ios), len(contract)))
    if missing:
        print("FAIL 缺失方法(webui 调到会崩):")
        for m in missing:
            print("   -", m)
        sys.exit(1)
    print("PASS T2: shared calls covered, Android-only services absent")


if __name__ == "__main__":
    main()
