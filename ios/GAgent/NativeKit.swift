import UIKit
import WebKit
import AVFoundation
import UserNotifications
import Photos
import SwiftUI
import os.log

/// GA 桥原生方法: 契约对齐 Android MainActivity.Bridge 的 iOS 实现子集。
final class NativeKit {
    static let shared = NativeKit()
    weak var webView: WKWebView?
    var gaDir: URL!
    private let speech = AVSpeechSynthesizer()
    private let log = Logger(subsystem: Bundle.main.bundleIdentifier ?? "io.github.shenhaostu.gagent", category: "bridge")

    func handle(fn: String, args: [String]) -> String {
        let a = { (i: Int) in i < args.count ? args[i] : "" }
        switch fn {
        case "isDark":
            return onMain { (self.webView?.traitCollection ?? UITraitCollection.current).userInterfaceStyle == .dark } ? "true" : "false"
        case "appVersion":
            let v = Bundle.main.infoDictionary
            let name = v?["CFBundleShortVersionString"] as? String ?? "0"
            let codeStr = v?["CFBundleVersion"] as? String ?? "0"
            let code = Int(codeStr) ?? 0
            return #"{"name":"\#(name)","code":\#(code),"channel":"oss","buildChannel":"ios"}"#
        case "launchInfo":
            return #"{"src":"?","notif":false,"cid":""}"#
        case "offAsrStatus", "offAsrStart", "offAsrPoll", "offAsrStop", "offAsrCancel":
            return onMain {
                let voice = VoiceInput.shared
                let reply: [String: Any]
                switch fn {
                case "offAsrStatus": reply = voice.status(language: a(0))
                case "offAsrStart": reply = voice.start(language: a(0))
                case "offAsrPoll": reply = voice.poll(a(0))
                case "offAsrStop": voice.stop(a(0)); reply = voice.poll(a(0))
                default: voice.cancel(a(0)); reply = voice.poll(a(0))
                }
                let data = try? JSONSerialization.data(withJSONObject: reply)
                return data.flatMap { String(data: $0, encoding: .utf8) } ?? #"{"ok":false,"done":true,"error":"voice_bridge_error"}"#
            }
        case "boardStatus":
            return onMain {
                let state = MainActor.assumeIsolated { BoardSession.shared.statusJSON() }
                let data = try? JSONSerialization.data(withJSONObject: state)
                return data.flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
            }
        case "boardSetup":
            onMainVoid {
                MainActor.assumeIsolated { BoardSetupPresenter.present() }
            }
            return "ok"
        case "openUrl":
            guard let u = URL(string: a(0)), ["http", "https"].contains(u.scheme ?? "") else { return "" }
            DispatchQueue.main.async { UIApplication.shared.open(u) }
            return "ok"
        case "notify":
            let c = UNMutableNotificationContent()
            c.title = a(0); c.body = a(1)
            UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { ok, _ in
                guard ok else { return }
                UNUserNotificationCenter.current().add(
                    UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
            }
            return "ok"
        case "speak":
            let u = AVSpeechUtterance(string: a(0))
            if !a(1).isEmpty { u.voice = AVSpeechSynthesisVoice(language: a(1)) }
            onMainVoid { self.speech.speak(u) }
            return "ok"
        case "speakStop":
            onMainVoid { self.speech.stopSpeaking(at: .immediate) }
            return "ok"
        case "keepAwake":
            let on = a(0) == "true"
            DispatchQueue.main.async { UIApplication.shared.isIdleTimerDisabled = on }
            return "ok"
        case "track", "promptContribute":
            log.info("[\(fn, privacy: .public)] \(a(0).prefix(120), privacy: .private)")
            return "ok"
        case "logError":
            log.error("[js:\(a(0), privacy: .public)] \(a(1), privacy: .public)")
            return "ok"
        case "setUser":
            UserDefaults.standard.set(a(0), forKey: "ga.uid"); return "ok"
        case "clearUser":
            UserDefaults.standard.removeObject(forKey: "ga.uid"); return "ok"
        case "saveUpload":
            return saveUpload(name: a(0), dataUrl: a(1))
        case "saveImageToGallery", "saveToGallery":
            return saveToPhotos(arg: a(0))
        case "shareImage":
            return shareImage(dataUrl: a(0))
        case "scanQr":
            onMainVoid { QrScan.present(over: self.webView) }
            return ""
        case "previewHtml":
            guard let f = WorkspaceFile.resolve(a(0), in: gaDir) else { return "err:not-found" }
            onMainVoid { HtmlPreview.present(fileURL: f) }
            return "ok"
        case "openAppSysSettings":
            DispatchQueue.main.async {
                if let u = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(u) }
            }
            return "true"
        case "networkProxy":
            return NetworkEnvironment.currentJSON()
        case "openFile", "previewFile":
            return onMain {
                MainActor.assumeIsolated {
                    FilePreview.present(a(0), workspace: self.gaDir, shareUnsupported: fn == "openFile")
                }
            }
        case "logsUpload", "feedbackSubmit":
            return ""
        case "diagResult":
            return "err:ios_unsupported"
        default:
            return #"{"err":"unknown_native_fn"}"#
        }
    }

    private func saveUpload(name: String, dataUrl: String) -> String {
        guard let comma = dataUrl.firstIndex(of: ","),
              let data = Data(base64Encoded: String(dataUrl[dataUrl.index(after: comma)...])) else { return "" }
        let safe = name.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "..", with: "_")
        let dir = gaDir.appendingPathComponent("uploads")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let f = dir.appendingPathComponent(safe)
        guard (try? data.write(to: f)) != nil else { return "" }
        return f.path
    }

    private func saveToPhotos(arg: String) -> String {
        let data: Data?
        if arg.hasPrefix("data:"), let comma = arg.firstIndex(of: ",") {
            data = Data(base64Encoded: String(arg[arg.index(after: comma)...]))
        } else {
            data = try? Data(contentsOf: gaDir.appendingPathComponent(arg))
        }
        guard let d = data, let img = UIImage(data: d) else { return "err:decode" }
        let sem = DispatchSemaphore(value: 0); var out = "ok"
        PHPhotoLibrary.requestAuthorization(for: .addOnly) { st in
            guard st == .authorized || st == .limited else { out = "err:perm"; sem.signal(); return }
            PHPhotoLibrary.shared().performChanges({ PHAssetChangeRequest.creationRequestForAsset(from: img) }) { ok, _ in
                out = ok ? "ok" : "err:write"; sem.signal()
            }
        }
        _ = sem.wait(timeout: .now() + 15)
        return out
    }

    private func shareImage(dataUrl: String) -> String {
        guard let comma = dataUrl.firstIndex(of: ","),
              let d = Data(base64Encoded: String(dataUrl[dataUrl.index(after: comma)...])),
              let img = UIImage(data: d) else { return "err:decode" }
        onMainVoid {
            guard let root = self.webView?.window?.rootViewController else { return }
            let vc = UIActivityViewController(activityItems: [img], applicationActivities: nil)
            vc.popoverPresentationController?.sourceView = root.view
            root.present(vc, animated: true)
        }
        return "ok"
    }

    private func onMain<T>(_ f: @escaping () -> T) -> T {
        if Thread.isMainThread { return f() }
        var v: T!; let s = DispatchSemaphore(value: 0)
        DispatchQueue.main.async { v = f(); s.signal() }
        s.wait(); return v
    }
    private func onMainVoid(_ f: @escaping () -> Void) {
        if Thread.isMainThread { f() } else { DispatchQueue.main.async(execute: f) }
    }
}
