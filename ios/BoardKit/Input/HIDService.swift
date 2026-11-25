import CoreGraphics
import Foundation
import UIKit

/// The `hid` tool: parses one action and delivers it through the input backend. It sends only; it never
/// looks at the screen, and returns as soon as the input has left.
@MainActor final class HIDService {
    static let inputs: Set<String> = ["tap", "long_press", "swipe", "type", "key", "button"]
    let backend: InputBackend
    /// The text GAgent last put on the pasteboard; Cmd+V in another app inserts it.
    private var staged: StagedPaste?
    /// The text a `type` is pasting right now.
    private var pasting: String?
    /// Injected by the coordinator: user consent, whether GAgent is in front, and how to hide its keyboard.
    var access: () throws -> Void = {}
    var foreground: () -> Bool = { UIApplication.shared.applicationState == .active }
    /// Ends text editing in GAgent: a software keyboard over the bottom edge turns the Home flick into App Switcher.
    var dismissKeyboard: () -> Void = {}

    init(backend: InputBackend) { self.backend = backend }

    /// Seconds the screen needs before it can show this action's result. A transition between apps takes longest.
    /// After a Back swipe the page finishes sliding, or springs back when iOS did not take the swipe; Safari showed
    /// the previous page 0.1-0.2 s after the stroke (2026-11-12), and the wait leaves a margin over that.
    static func settleTime(_ action: String, _ args: [String: Any]) -> Double {
        guard action == "button" else { return 0.2 }
        return args["name"] as? String == InputButton.back.rawValue ? 0.5 : 0.7
    }

    /// The point a pointer action aims at, when it has one.
    static func target(_ args: [String: Any]) -> CGPoint? {
        guard let x = (args["x"] as? NSNumber)?.doubleValue, let y = (args["y"] as? NSNumber)?.doubleValue else { return nil }
        return CGPoint(x: x, y: y)
    }

    func perform(_ action: String, _ args: [String: Any]) async throws {
        func coordinate(_ key: String) throws -> Double {
            guard let number = args[key] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue.isFinite, (0...1).contains(number.doubleValue) else {
                throw DeviceError(message: "\(key) must be a normalized number between 0 and 1")
            }
            return number.doubleValue
        }
        func duration(_ fallback: Double, least: Double, key: String = "duration_ms") throws -> Double {
            guard args[key] == nil || (args[key] is NSNumber && CFGetTypeID(args[key] as! NSNumber) != CFBooleanGetTypeID()) else {
                throw DeviceError(message: "\(key) must be a number")
            }
            let ms = (args[key] as? NSNumber)?.doubleValue ?? fallback
            guard ms.isFinite, (least...120_000).contains(ms) else {
                throw DeviceError(message: "\(key) must be \(Int(least))–120000 ms (native request deadline)")
            }
            return ms / 1000
        }
        switch action {
        case "tap":
            let number = args["count"] as? NSNumber ?? 1
            guard args["count"] == nil || args["count"] is NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  let count = Int(exactly: number.doubleValue), count > 0 else {
                throw DeviceError(message: "count must be a positive whole number")
            }
            try await backend.tap(coordinate("x"), coordinate("y"), count: count)
        case "swipe":
            let flick = args["flick"] as? NSNumber
            guard args["flick"] == nil || flick.map({ CFGetTypeID($0) == CFBooleanGetTypeID() }) == true else {
                throw DeviceError(message: "flick must be true or false")
            }
            try await backend.swipe(coordinate("x"), coordinate("y"), coordinate("x2"), coordinate("y2"),
                                    seconds: args["duration_ms"] == nil ? nil : duration(0, least: 50),
                                    hold: duration(0, least: 0, key: "hold_ms"), flick: flick?.boolValue ?? false)
        case "long_press":
            try await backend.longPress(coordinate("x"), coordinate("y"), seconds: duration(800, least: 100))
        case "type":
            let text = try Self.typedText(args["text"])
            let method = args["method"] as? String ?? "paste"
            guard args["method"] == nil || args["method"] is String,
                  ["paste", "keys"].contains(method) else { throw DeviceError(message: "method must be paste or keys") }
            if method == "keys" {
                guard Self.typeable(text) else {
                    throw DeviceError(message: "method keys types printable ASCII; use paste for Unicode")
                }
                try await backend.type(text)
            } else {
                try await paste(text)
            }
        case "key":
            guard let combo = args["combo"] as? String, !combo.isEmpty, combo.count <= 40,
                  combo.range(of: "^[!-~]+$", options: .regularExpression) != nil else {
                throw DeviceError(message: "Invalid keyboard shortcut")
            }
            try await backend.key(combo)
        case "button":
            guard let button = (args["name"] as? String).flatMap(InputButton.init(rawValue:)) else {
                throw DeviceError(message: "button name must be home, back, search or control_center")
            }
            if button == .home { try await leaveGAgentKeyboard() }
            try await backend.press(button)
        default:
            throw DeviceError(message: "Unsupported hid action: \(action)")
        }
    }

    /// iOS lets only the foreground app write the pasteboard, so text for another app is staged before GAgent
    /// leaves the screen. The item is device-local and expires, so it never syncs or lingers for other apps.
    func stage(_ text: String) throws {
        try access()
        guard foreground() else { throw ScreenObservation.Failure.textNotStaged }
        let pasteboard = UIPasteboard.general
        let expires = Date().addingTimeInterval(600)
        pasteboard.setItems([["public.utf8-plain-text": text]], options: [.localOnly: true, .expirationDate: expires])
        staged = StagedPaste(text: text, changeCount: pasteboard.changeCount, expires: expires)
    }

    /// The pasteboard still holds what GAgent staged (and, when given, exactly `expected`).
    func requireStaged(_ expected: String? = nil) throws {
        guard let staged, staged.valid(changeCount: UIPasteboard.general.changeCount, now: Date()),
              expected == nil || staged.text == expected else { throw ScreenObservation.Failure.textNotStaged }
    }

    /// At the write: a `type` pastes only while the pasteboard still holds its text. A bare cmd+v from the model
    /// is the system's own Paste, of whatever an app copied.
    func requirePaste() throws { if let pasting { try requireStaged(pasting) } }

    func forgetStaged() { staged = nil }

    /// Unicode input through the system paste command: HID keys cannot type Chinese and IMEs rewrite them. In another
    /// app only text staged from GAgent can be pasted, and iOS may first ask to allow pasting from GAgent; allowing
    /// completes this paste (WeChat, 2026-10-24).
    private func paste(_ text: String) async throws {
        if foreground() { try stage(text) }
        try requireStaged(text)
        pasting = text
        defer { pasting = nil }
        try await backend.key("cmd+v")
    }

    private func leaveGAgentKeyboard() async throws {
        guard foreground() else { return }
        dismissKeyboard()
        try await Task.sleep(for: .milliseconds(450))  // the keyboard's hide animation
    }

    /// Text for the focused field: newlines and tabs are allowed; secrets stay with the user.
    nonisolated static func typedText(_ value: Any?) throws -> String {
        guard let text = value as? String, !text.isEmpty,
              !text.unicodeScalars.contains(where: { $0.properties.generalCategory == .control && !"\n\r\t".unicodeScalars.contains($0) }) else {
            throw DeviceError(message: "text must be nonempty; only newline and tab control characters are allowed")
        }
        return text
    }

    nonisolated static func typeable(_ text: String) -> Bool {
        !text.isEmpty && text.unicodeScalars.allSatisfy { (32...126).contains($0.value) }
    }
}
