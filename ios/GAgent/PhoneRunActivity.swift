import BackgroundTasks
import Combine
import UIKit

/// The system-managed progress for a phone-control run (iOS 26 continued processing): keeps the agent, BLE link and
/// Wi-Fi video running while another app is in front, and gives the user the system's progress and cancel UI.
/// It begins only from the foreground, on the first phone action, and ends when the task finishes or yields control.
/// Without an engine observer, `idleLimit` only releases an idle system entry; it never cancels the agent.
/// When the system ends it (its time ran out, or the user dismissed it there), only this entry goes away:
/// the run itself continues on the remaining keep-alive (the board's BLE link) and stops through GAgent's own
/// stop controls. Ending the run with the entry aborted real tasks after 12 to 15 steps (2026-11-08).
/// System progress is visible and cancellable. It may cover screen content; observations must include it.
@MainActor final class PhoneRunActivity: ObservableObject {
    static let shared = PhoneRunActivity()
    static let idleLimit = 120.0

    @Published private(set) var state = "idle"
    @Published private(set) var enabled = UserDefaults.standard.object(forKey: enabledKey) as? Bool ?? true
    private var task: AnyObject?     // BGContinuedProcessingTask
    private(set) var requestIdentifier: String?
    private var steps: Int64 = 0
    private var lastAction = 0.0
    private var idleCheck: Task<Void, Never>?
    private var continuationNeeded = false
    private var onCancel: () -> Void = {}

    func setEnabled(_ value: Bool) {
        enabled = value
        UserDefaults.standard.set(value, forKey: Self.enabledKey)
        if !value && task != nil { finish(success: true) }
        if task == nil { state = value ? "idle" : "off" }
    }

    func attach(_ session: BoardSession) {
        session.onActivity = { [weak self] action in self?.record(action) }
        session.backgroundRunState = { [weak self] in
            guard let self else { return "idle" }
            return enabled ? state : "off"
        }
        onCancel = { [weak session] in
            session?.stop()
            DispatchQueue.global().async { _ = PyRuntime.shared.call(fn: "iphone_abort", args: []) }
        }
    }

    func cancel() { finish(success: false); onCancel() }

    /// Keep an unanswered turn's lease: an answer on the island cannot request a new one from the background.
    func observeContinuation(_ needed: Bool, request: String?) {
        guard request == requestIdentifier else { return }
        continuationNeeded = needed
        if !needed && task != nil { finish(success: true) }
    }

    /// What the system's progress entry says while it runs; the status UI (ios/Presence) supplies the words,
    /// and nil gives the entry its own words back. With no entry running this does nothing.
    func caption(title: String? = nil, subtitle: String? = nil) {
        #if compiler(>=6.2) || GAGENT_RUN_ACTIVITY_TEST
        guard #available(iOS 26.0, *), let task = task as? BGContinuedProcessingTask else { return }
        task.updateTitle(title ?? Self.title, subtitle: subtitle ?? Self.subtitle)
        #endif
    }

    private func record(_ action: String) {
        lastAction = now()
        if action == "stop" { return finish(success: true) }
        if action == "status" { return }  // keeps a run alive while the model waits, but never starts one
        if action == "completed" { advance(); return }
        if task == nil { begin() }
    }

    /// Count completed observations/actions only. A timer must not pretend that a stalled model made progress.
    private func advance() {
        guard task != nil else { return }
        steps += 1
        #if compiler(>=6.2) || GAGENT_RUN_ACTIVITY_TEST
        guard #available(iOS 26.0, *), let task = task as? BGContinuedProcessingTask else { return }
        task.progress.totalUnitCount = steps + 1
        task.progress.completedUnitCount = steps
        #endif
    }

    static let enabledKey = "gagent.systemProgress"

    private func begin() {
        guard enabled else { state = "off"; return }
        #if compiler(>=6.2) || GAGENT_RUN_ACTIVITY_TEST
        guard #available(iOS 26.0, *) else { state = "unavailable: requires iOS 26"; return }
        guard UIApplication.shared.applicationState == .active else { return }  // only a foreground request is valid
        let identifier = (Bundle.main.bundleIdentifier ?? "gagent") + ".agent." + UUID().uuidString
        let registered = BGTaskScheduler.shared.register(forTaskWithIdentifier: identifier, using: .main) { [weak self] granted in
            MainActor.assumeIsolated { self?.launched(granted, identifier: identifier) }
        }
        guard registered else { state = "unavailable: identifier not permitted"; return }
        let request = BGContinuedProcessingTaskRequest(identifier: identifier, title: Self.title, subtitle: Self.subtitle)
        request.strategy = .fail
        requestIdentifier = identifier
        task = NSNull()
        state = "starting"
        do {
            try BGTaskScheduler.shared.submit(request)
            watchIdle()
        } catch {
            task = nil; requestIdentifier = nil
            state = "unavailable: \(error.localizedDescription)"
            DebugLog.write("phone run: continued task not granted: \(error.localizedDescription)")
        }
        #else
        state = "unavailable: requires iOS 26 SDK"
        #endif
    }

    #if compiler(>=6.2) || GAGENT_RUN_ACTIVITY_TEST
    @available(iOS 26.0, *)
    private func launched(_ granted: BGTask, identifier: String) {
        guard let granted = granted as? BGContinuedProcessingTask else { return }
        guard requestIdentifier == identifier else { return granted.setTaskCompleted(success: true) }
        task = granted
        state = "running"
        granted.progress.totalUnitCount = steps + 1
        granted.progress.completedUnitCount = steps
        granted.expirationHandler = { [weak self, weak granted] in
            Task { @MainActor in
                guard let self, let granted, self.task === granted else { return }
                DebugLog.write("phone run: the system ended the continued task; the run goes on without its progress entry")
                self.finish(success: false)
            }
        }
    }
    #endif

    private func watchIdle() {
        idleCheck?.cancel()
        idleCheck = Task { [weak self] in
            while !Task.isCancelled {
                guard (try? await Task.sleep(for: .seconds(3))) != nil else { return }
                guard let self else { return }
                if !continuationNeeded && now() - lastAction > Self.idleLimit { finish(success: true); return }
            }
        }
    }

    private func finish(success: Bool) {
        idleCheck?.cancel(); idleCheck = nil
        if let requestIdentifier { BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: requestIdentifier) }
        requestIdentifier = nil
        #if compiler(>=6.2) || GAGENT_RUN_ACTIVITY_TEST
        if #available(iOS 26.0, *), let task = task as? BGContinuedProcessingTask {
            if success { task.progress.completedUnitCount = task.progress.totalUnitCount }
            task.setTaskCompleted(success: success)
        }
        #endif
        task = nil
        continuationNeeded = false
        steps = 0
        state = enabled ? "idle" : "off"
    }

    private static let title = "GAgent · iPhone"
    private static let subtitle = "任务进行中"
}
