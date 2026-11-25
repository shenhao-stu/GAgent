import UIKit
import WebKit

/// Presence inside the chat page while GAgent itself is in front: the handoff strip above the composer (the
/// chat shows everything else about its own run) and the two switches on the settings page. The page is the
/// shared web UI; this surface adds its own script and style to the loaded page and edits none of the page's files. Buttons and switches come back through a message
/// handler of its own, not through the app's GA bridge.
@MainActor final class WebSurface: NSObject, WKScriptMessageHandler {
    private weak var hooked: WKWebView?
    private var added = false       // the page has answered that the script ran
    private var drawn = "null"      // what the strip was last asked to draw
    private var pendingConversation: String?  // a card opened while the chat page was still loading

    private lazy var script: String = {
        func text(_ ext: String) -> String {
            Bundle.main.url(forResource: "presence", withExtension: ext).flatMap { try? String(contentsOf: $0, encoding: .utf8) } ?? ""
        }
        let words = ["zh": PresenceCopy(english: false).settings, "en": PresenceCopy(english: true).settings]
        return "window.__gaPresence=" + Self.json(["css": text("css"), "words": words]) + ";\n" + text("js")
    }()

    /// Puts the script into the page: now, and on every later load of it. A page that is still loading is
    /// asked again on the next call, until it answers.
    func install() {
        guard let web = NativeKit.shared.webView, UIApplication.shared.applicationState != .background else { return }
        if hooked !== web {
            let controller = web.configuration.userContentController
            controller.add(self, name: "gaPresence")
            controller.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentEnd, forMainFrameOnly: true))
            (hooked, added) = (web, false)
        }
        guard !added else { openPending(); return }
        web.evaluateJavaScript(script + "\n!!window.GAPresence") { [weak self] result, _ in
            if result as? Bool == true { self?.added = true; self?.openPending() }
        }
    }

    func show(_ state: PresenceState?) {
        drawn = state.map(Self.payload) ?? "null"
        install()
        draw()
    }

    private func draw() {
        guard UIApplication.shared.applicationState != .background else { return }
        hooked?.evaluateJavaScript("window.GAPresence&&GAPresence.render(\(drawn))")
        openPending()
    }

    func open(_ cid: String) {
        pendingConversation = cid
        install()
    }

    private func openPending() {
        guard added, UIApplication.shared.applicationState == .active, let cid = pendingConversation else { return }
        hooked?.evaluateJavaScript("!!window.GAPresence && GAPresence.openConversation(\(Self.json(cid)))") { [weak self] result, _ in
            if result as? Bool == true, self?.pendingConversation == cid { self?.pendingConversation = nil }
        }
    }

    /// The state with its words already chosen, so the page holds no copy of its own.
    private static func payload(_ state: PresenceState) -> String {
        let copy = PresenceCopy(english: state.english)
        return json(["cid": state.cid, "phase": state.phase.rawValue, "running": state.running,
                     "status": copy.status(state), "now": state.now,
                     "labels": ["takeOver": copy.takeOver, "handBack": copy.handBack,
                                "handingBack": copy.handingBack, "end": copy.end, "released": copy.released]])
    }

    /// JSON that is also safe inside a script: the two line separators JSON allows but JavaScript did not.
    private static func json(_ value: Any) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: value, options: .fragmentsAllowed)) ?? Data("null".utf8)
        return String(decoding: data, as: UTF8.self)
            .replacingOccurrences(of: "\u{2028}", with: "\\u2028").replacingOccurrences(of: "\u{2029}", with: "\\u2029")
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        let page = NativeKit.shared.gaDir?.appendingPathComponent("webui/index.html").standardizedFileURL
        guard message.frameInfo.isMainFrame, message.frameInfo.request.url?.standardizedFileURL == page,
              let body = message.body as? [String: Any] else { return }
        if body["ready"] != nil {
            // The script has just run, at launch or after a reload: give it the task, and the switches'
            // values when there is an island for them to govern (the rows stay hidden until then).
            added = true
            if LiveActivitySurface.available {
                hooked?.evaluateJavaScript("GAPresence.configure(" + Self.json(PresenceSettings.values) + ")")
            }
            draw()
        } else if let name = body["setting"] as? String, let on = body["value"] as? Bool {
            if PresenceSettings.set(name, on) { PresenceCoordinator.shared.settingsChanged() }
        } else if let cid = body["cid"] as? String,
                  let command = (body["command"] as? String).flatMap(PresenceCommand.init), command != .answer {
            let request = body["request"] as? String
            Task { await PresenceActions.perform(command, cid: cid, text: "") { [weak self] in await self?.handBack($0, $1, request) } }
        }
    }

    /// The turn that goes on after a hand-back asked for on the page, sent by the page as its own.
    private func handBack(_ cid: String, _ text: String, _ request: String?) async -> Bool? {
        guard let web = hooked, UIApplication.shared.applicationState != .background else { return nil }
        let call = "window.GAPresence ? GAPresence.handBack(..." + Self.json([cid, text, request ?? ""]) + ") : null"
        // An evaluation failure cannot prove that startTask did not already send the turn.
        do { return try await web.evaluateJavaScript(call) as? Bool }
        catch { DebugLog.write("presence: hand-back page failed: \(error.localizedDescription)"); return false }
    }
}
