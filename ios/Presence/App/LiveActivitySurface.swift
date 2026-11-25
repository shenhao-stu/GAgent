import ActivityKit
import os
import UIKit

/// The user's two choices, both on unless switched off on the settings page.
enum PresenceSettings {
    static let names = ["live", "lockDetail"]
    private static func key(_ name: String) -> String { "gagent.presence." + name }
    private static func on(_ name: String) -> Bool { UserDefaults.standard.object(forKey: key(name)) as? Bool ?? true }
    static var liveActivity: Bool { on("live") }
    static var lockDetail: Bool { on("lockDetail") }
    static var values: [String: Bool] { Dictionary(uniqueKeysWithValues: names.map { ($0, on($0)) }) }

    static func set(_ name: String, _ value: Bool) -> Bool {
        guard names.contains(name) else { return false }
        UserDefaults.standard.set(value, forKey: key(name))
        return true
    }
}

/// The Dynamic Island and the Lock Screen Live Activity surface.
@MainActor final class LiveActivitySurface {
    private var activity: Activity<PresenceAttributes>?
    private var sent: PresenceState?
    private var sentAt = Date.distantPast
    private var later: Task<Void, Never>?

    static let available: Bool = {
        let plugins = Bundle.main.builtInPlugInsURL.flatMap {
            try? FileManager.default.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)
        } ?? []
        return plugins.contains {
            let point = (Bundle(url: $0)?.object(forInfoDictionaryKey: "NSExtension") as? [String: Any])?["NSExtensionPointIdentifier"]
            return point as? String == "com.apple.widgetkit-extension"
        }
    }()

    static let gap = 0.8
    static let staleAfter = 180.0
    static let glance = 8.0
    static let linger = 600.0

    init() {
        let found = Activity<PresenceAttributes>.activities
        activity = found.first
        for extra in found.dropFirst() { Task { await extra.end(nil, dismissalPolicy: .immediate) } }
    }

    var active: Bool { activity != nil }
    var leftover: PresenceState? { sent == nil ? activity?.content.state : nil }

    func show(_ state: PresenceState?, ring: Bool) {
        later?.cancel(); later = nil
        guard let state, Self.available, PresenceSettings.liveActivity else { return finish(nil, ring: false) }
        if state.ended { return finish(state, ring: ring) }
        guard let activity, activity.attributes.cid == state.cid else { return begin(state) }
        let wait = Self.gap - Date().timeIntervalSince(sentAt)
        if ring || state.phase != sent?.phase || wait <= 0 { return push(state, to: activity, ring: ring) }
        later = Task { [weak self] in
            try? await Task.sleep(for: .seconds(wait))
            if !Task.isCancelled { self?.push(state, to: activity, ring: false) }
        }
    }

    func restart(_ state: PresenceState?) {
        finish(nil, ring: false)
        show(state, ring: false)
    }

    private func begin(_ state: PresenceState) {
        finish(nil, ring: false)
        guard UIApplication.shared.applicationState != .background,
              ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let attributes = PresenceAttributes(cid: state.cid, lockDetail: PresenceSettings.lockDetail)
        do {
            activity = try Activity.request(attributes: attributes, content: Self.content(state), pushType: nil)
            sent = state; sentAt = Date()
        } catch {
            Logger(subsystem: Bundle.main.bundleIdentifier ?? "io.github.shenhaostu.gagent", category: "presence")
                .error("live activity not started: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func push(_ state: PresenceState, to activity: Activity<PresenceAttributes>, ring: Bool) {
        sent = state; sentAt = Date()
        let content = Self.content(state), alert = ring ? Self.alert(state) : nil
        Task { await activity.update(content, alertConfiguration: alert) }
    }

    private func finish(_ state: PresenceState?, ring: Bool) {
        guard let activity else { return }
        self.activity = nil; sent = nil
        guard let state else { Task { await activity.end(nil, dismissalPolicy: .immediate) }; return }
        let content = Self.content(state), alert = ring ? Self.alert(state) : nil
        let stay = state.phase == .stopped ? 30 : Self.linger
        let hold = UIApplication.shared.beginBackgroundTask(expirationHandler: nil)
        Task {
            if ring {
                await activity.update(content, alertConfiguration: alert)
                try? await Task.sleep(for: .seconds(Self.glance))
            }
            await activity.end(content, dismissalPolicy: .after(Date() + stay))
            UIApplication.shared.endBackgroundTask(hold)
        }
    }

    private static func content(_ state: PresenceState) -> ActivityContent<PresenceState> {
        ActivityContent(state: state, staleDate: state.running ? Date() + staleAfter : nil,
                        relevanceScore: state.phase == .asking ? 100 : 50)
    }

    private static func alert(_ state: PresenceState) -> AlertConfiguration {
        AlertConfiguration(title: LocalizedStringResource(stringLiteral: PresenceCopy(english: state.english).status(state)),
                           body: LocalizedStringResource(stringLiteral: state.now), sound: .default)
    }
}
