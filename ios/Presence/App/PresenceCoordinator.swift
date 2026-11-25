import Combine
import UIKit

/// The status UI's only moving part. While a task is live it reads the engine about once a second, folds
/// the snapshot into one `PresenceState` and hands that state to the surfaces. It observes: the engine does
/// not know it exists, and what it may ask of the engine is in `PresenceActions`.
///
/// Reading a snapshot, instead of receiving events, means a missed read loses nothing and nothing can
/// arrive out of order.
@MainActor final class PresenceCoordinator {
    static let shared = PresenceCoordinator()

    private var tracker = PresenceTracker()
    private let live = LiveActivitySurface()
    private let notes = NotificationSurface()
    private let web = WebSurface()
    private var loop: Task<Void, Never>?
    private var reads = 0
    private var seen: PresenceSnapshot?   // the last read, for the moment GAgent leaves the front
    private var watching: Set<AnyCancellable> = []

    /// How long the in-app strip keeps showing an outcome.
    static let linger = 8.0

    var copy: PresenceCopy { PresenceCopy(english: (tracker.state ?? live.leftover)?.english ?? false) }

    func start() {
        guard watching.isEmpty else { return }
        PresenceIntentRouter.perform = { command, cid, text, token in
            await PresenceActions.perform(command, cid: cid, text: text, replyToken: token)
        }
        notes.install()
        let center = NotificationCenter.default
        center.publisher(for: Notification.Name("GAgentOpenURL"))
            .sink { [weak self] note in
                guard let url = note.object as? URL, let cid = PresenceLink.conversation(url) else { return }
                self?.web.open(cid)
                self?.wake()
            }.store(in: &watching)
        center.publisher(for: UIApplication.didBecomeActiveNotification)
            .sink { [weak self] _ in self?.cameToFront() }.store(in: &watching)
        center.publisher(for: UIApplication.willResignActiveNotification)
            .sink { [weak self] _ in self?.leaving() }.store(in: &watching)
        // The first phone action of a task is the moment to start following it.
        PhoneRunActivity.shared.$state.removeDuplicates().sink { [weak self] _ in self?.wake() }.store(in: &watching)
        wake()
    }

    /// GAgent is leaving the front, the last moment the system lets it start a Live Activity. A task that runs
    /// but has not touched the phone yet is followed from now: otherwise a user who leaves right after sending
    /// would get no card at all, since the first phone action then comes when GAgent is already behind.
    private func leaving() {
        if tracker.state?.ended ?? true, let seen {
            let old = tracker.state
            if let state = tracker.fold(seen, now: Date(), phoneActive: true), state != old { present(state, after: old) }
        }
        wake()
    }

    /// Read now, and keep reading for as long as there is something to follow.
    func wake() {
        loop?.cancel()
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let pause = await self.tick() else { return }
                try? await Task.sleep(for: .seconds(pause))
            }
        }
    }

    /// A switch on the settings page changed: the island follows at once.
    func settingsChanged() { live.restart(tracker.state) }

    func stopRequested() {
        if tracker.state == nil { live.show(nil, ring: false) } else { tracker.stopRequested() }
    }

    /// A turn was just sent for `cid` from a card that outlived its task: follow that task again.
    func adopt(_ cid: String) {
        if tracker.state == nil, let leftover = live.leftover, leftover.cid == cid { tracker.adopt(leftover) }
    }

    private func cameToFront() {
        if tracker.state == nil {
            live.show(nil, ring: false)     // a card that outlived its task: the chat takes over
            notes.prepare()                 // never while a task runs: the agent would meet the system's prompt
        }
        web.show(tracker.state)
        wake()
    }

    /// One read of the engine. Returns the wait before the next one, or nil when there is nothing to follow.
    private func tick() async -> Double? {
        reads += 1
        let ticket = reads
        web.install()
        guard PyRuntime.shared.ready else { return 2 }
        let request = PhoneRunActivity.shared.requestIdentifier
        let json = await Task.detached { PyRuntime.shared.call(fn: "presence_snapshot", args: []) }.value
        guard ticket == reads else { return nil }       // a newer read is already on its way
        let old = tracker.state, now = Date()
        if let old, old.ended, now.timeIntervalSince(old.phaseSince) > Self.linger { tracker.dismiss() }
        let phoneActive = ["starting", "running"].contains(PhoneRunActivity.shared.state)
        // A failed read cannot prove that the engine stopped processing.
        guard let data = json?.data(using: .utf8),
              let snapshot = try? JSONDecoder().decode(PresenceSnapshot.self, from: data) else { return 2 }
        seen = snapshot
        let state = tracker.fold(snapshot, now: now, phoneActive: phoneActive)
        if state != old { present(state, after: old) }
        let continuing = snapshot.needsContinuation
        PhoneRunActivity.shared.observeContinuation(continuing, request: request)
        let front = UIApplication.shared.applicationState == .active
        guard let state else { return front || continuing ? 2 : nil }
        return state.running ? 1 : state.ended && !front && !continuing ? nil : 2
    }

    private func present(_ state: PresenceState?, after old: PresenceState?) {
        let front = UIApplication.shared.applicationState == .active
        let alert = state?.alert(after: old, appActive: front, liveActivity: live.active) ?? .none
        live.show(state, ring: alert == .island)
        notes.show(state, ring: alert == .notification)
        web.show(state)
        // One place says how far the task is: the island while it shows the task, and otherwise the system's own
        // progress entry, which by itself only ever says "task in progress".
        if let state, state.running, !live.active {
            PhoneRunActivity.shared.caption(title: "GAgent · " + PresenceCopy(english: state.english).stepLabel(state),
                                            subtitle: state.now)
        } else { PhoneRunActivity.shared.caption() }
    }
}

/// Reached by name from PresenceBoot.m, so that nothing in the app has to call into Presence.
@objc(GAPresenceEntry) final class PresenceEntry: NSObject {
    @objc static func start() { MainActor.assumeIsolated { PresenceCoordinator.shared.start() } }
}
