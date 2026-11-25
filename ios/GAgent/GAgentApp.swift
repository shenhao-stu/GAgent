import SwiftUI
import WebKit
import UserNotifications

/// 前台通知呈现: iOS 默认抑制前台横幅, 而 webui 在前台运行 ⇒ GA.notify 需此 delegate 才可见。
final class NotifDelegate: NSObject, UNUserNotificationCenterDelegate {
    func userNotificationCenter(_ c: UNUserNotificationCenter, willPresent n: UNNotification,
                                withCompletionHandler h: @escaping (UNNotificationPresentationOptions) -> Void) {
        h([.banner, .sound])
    }
}

// GAgent iOS 壳:
//   资产解包 → WKWebView(file:// 加载 gaDir/webui) → 后台线程 PyRuntime.boot(嵌入式 CPython 跑签名 gacore)。
// GA 桥(JS→原生) = window.prompt() 同步拦截(BridgeRouter, WKUIDelegate), 契约同 Android JavascriptInterface。
// webui 与 Android 共享，iOS 展示按平台启用；ios_bridge.js 注入 window.GA(atDocumentStart)。

@main
struct GAgentApp: App {
    @Environment(\.scenePhase) private var phase
    @State private var boot = Boot.run()
#if DEBUG
    @State private var showBoardSetup = ProcessInfo.processInfo.arguments.contains("-board-setup")
#endif
    private let notif = NotifDelegate()

    init() {
        UNUserNotificationCenter.current().delegate = notif
        PhoneRunActivity.shared.attach(BoardSession.shared)
        BoardSession.shared.dismissKeyboard = {
            UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        }
    }

    var body: some Scene {
        WindowGroup {
            WebHost(boot: boot).ignoresSafeArea()
                .onOpenURL { url in
                    NotificationCenter.default.post(name: Notification.Name("GAgentOpenURL"), object: url)
                }
#if DEBUG
                .sheet(isPresented: $showBoardSetup) { BoardSetupView() }
#endif
        }
            .onChange(of: phase) { _, p in
                guard p == .active else { return }
                DispatchQueue.global().async {
                    // 回前台 nudge 一次 pclink: keeper 自愈重连提速(失败无害)
                    if PyRuntime.shared.ready { _ = PyRuntime.shared.call(fn: "send", args: ["/pclink.status"]) }
                }
            }
    }
}

/// 启动编排结果(App 生命周期内一次)
struct Boot {
    let gaDir: URL
    let err: String?

    static func run() -> Boot {
        do {
            let gaDir = try Assets.extract()                            // Bundle/gacore → AppSupport/ga (含 webui)
            NativeKit.shared.gaDir = gaDir
            Thread.detachNewThread {                                    // Py 启动秒级, 不挡首帧; 就绪前桥答"引擎未就绪"
                let b = Bundle.main.bundlePath
                let home = b + "/python"
                let paths = [home + "/lib/python3.13",                  // stdlib(目录形态)
                             home + "/lib/python3.13/lib-dynload",      // C 扩展(_ssl/_sqlite3...)
                             home + "/lib/python313.zip",               // stdlib(zip 形态, 候选)
                             b + "/py",                                 // bootstrap_ios.py
                             b + "/site-packages",                      // requests/websockets/certifi...
                             b + "/gacore"]                             // signed, immutable engine code
                _ = PyRuntime.shared.boot(gaDir: gaDir.path, pyHome: home, paths: paths)
            }
            return Boot(gaDir: gaDir, err: nil)
        } catch {
            return Boot(gaDir: URL(fileURLWithPath: "/"), err: String(describing: error))
        }
    }
}

struct WebHost: UIViewRepresentable {
    let boot: Boot

    func makeCoordinator() -> BridgeRouter { BridgeRouter() }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true
        cfg.allowsInlineMediaPlayback = true
        if let js = Bundle.main.url(forResource: "ios_bridge", withExtension: "js"),
           let src = try? String(contentsOf: js, encoding: .utf8) {
            // atDocumentStart: 先于 app.js 的 typeof GA 检测 ⇒ demo 垫片不激活
            cfg.userContentController.addUserScript(
                WKUserScript(source: src, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        let web = WKWebView(frame: .zero, configuration: cfg)
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.scrollView.bounces = false
        web.scrollView.delegate = context.coordinator
        web.allowsLinkPreview = false
        web.isOpaque = false
        web.uiDelegate = context.coordinator
        NativeKit.shared.webView = web
        if let e = boot.err {
            web.loadHTMLString("<h3 style='font-family:-apple-system;padding:40px'>启动失败: \(e)</h3>", baseURL: nil)
        } else {
            let index = boot.gaDir.appendingPathComponent("webui/index.html")
            web.loadFileURL(index, allowingReadAccessTo: boot.gaDir)
        }
        return web
    }
    func updateUIView(_ web: WKWebView, context: Context) {}
}

/// GA 桥同步路由: 拦截 ios_bridge.js 的 window.prompt(SENTINEL, JSON{fn,kind,args})。
final class BridgeRouter: NSObject, WKUIDelegate, UIScrollViewDelegate {
    private static let SENTINEL = "\u{0001}GABRIDGE"

    func scrollViewDidScroll(_ scrollView: UIScrollView) {
        guard !scrollView.isZooming, abs(scrollView.zoomScale - 1) < 0.01,
              scrollView.contentOffset != .zero else { return }
        scrollView.setContentOffset(.zero, animated: false)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let expected = NativeKit.shared.gaDir?.appendingPathComponent("webui/index.html").standardizedFileURL
        guard frame.isMainFrame, frame.request.url?.standardizedFileURL == expected,
              webView.url?.standardizedFileURL == expected,
              prompt == Self.SENTINEL,
              let raw = defaultText?.data(using: .utf8),
              let msg = try? JSONSerialization.jsonObject(with: raw) as? [String: Any],
              let fn = msg["fn"] as? String, let kind = msg["kind"] as? String else {
            completionHandler(nil); return
        }
        let args = (msg["args"] as? [Any] ?? []).map { a -> String in
            if let s = a as? String { return s }
            if let n = a as? NSNumber {
                return CFGetTypeID(n) == CFBooleanGetTypeID() ? (n.boolValue ? "true" : "false") : n.stringValue
            }
            if let b = a as? Bool { return b ? "true" : "false" }
            return ""
        }
        func finish(_ s: String?) { DispatchQueue.main.async { completionHandler(s) } }
        switch kind {
        case "engine":
            if fn == "ready" { completionHandler(PyRuntime.shared.bootMsg); return }
            guard PyRuntime.shared.ready else { completionHandler(fn.hasPrefix("poll") ? nil : "引擎未就绪"); return }
            DispatchQueue.global().async { finish(PyRuntime.shared.call(fn: fn, args: args)) }
        case "native":
            DispatchQueue.global().async { finish(NativeKit.shared.handle(fn: fn, args: args)) }
        default:
            completionHandler(nil)
        }
    }
}
