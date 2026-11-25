"""Compile the production action dispatcher against a deterministic engine and surfaces."""
import subprocess
from pathlib import Path


PRESENCE = Path(__file__).resolve().parents[1]


def test_answers_require_their_question_and_only_adopt_accepted_sends(tmp_path):
    harness = tmp_path / "Harness.swift"
    harness.write_text(r'''
import Foundation

enum PresenceCommand: String { case stop, pause, resume, answer }
@MainActor enum DebugLog {
    static var lines: [String] = []
    static func write(_ line: String) { lines.append(line) }
}
@MainActor final class PresenceCoordinator {
    static let shared = PresenceCoordinator()
    struct Copy { let resumePrompt = "Continue the original task" }
    let copy = Copy()
    var adopted: [String] = [], wakes = 0
    func adopt(_ cid: String) { adopted.append(cid) }
    func wake() { wakes += 1 }
    func stopRequested() {}
}
@MainActor final class PhoneRunActivity {
    static let shared = PhoneRunActivity()
    var cancellations = 0
    func cancel() { cancellations += 1 }
}
final class PyRuntime: @unchecked Sendable {
    static let shared = PyRuntime()
    var ready = true
    private static let lock = NSLock()
    private static var response: String? = ""
    private static var paused = true
    private static var resumeGate: DispatchSemaphore?
    private static var resumeAccepted = false
    private static var retrying = false
    private static var log: [[String]] = []
    static var calls: [[String]] { lock.withLock { log } }
    static var waitingForResume: Bool { lock.withLock { resumeAccepted } }
    static func rejectHandoffChanges(_ value: Bool) { lock.withLock { retrying = value } }
    static func delayResume() -> DispatchSemaphore {
        lock.withLock { let gate = DispatchSemaphore(value: 0); resumeGate = gate; resumeAccepted = false; return gate }
    }
    static func reset(_ value: String?, paused: Bool) { lock.withLock { response = value; self.paused = paused; log = [] } }
    func call(fn: String, args: [String]) -> String? {
        if fn == "phone_takeover", args[1] == "resume", let gate = Self.lock.withLock({ Self.resumeGate }) {
            Self.lock.withLock { Self.log.append([fn] + args); Self.paused = false; Self.resumeAccepted = true }
            gate.wait()
            Self.lock.withLock { Self.resumeGate = nil }
            return #"{"ok":true}"#
        }
        return Self.lock.withLock {
            Self.log.append([fn] + args)
            if fn == "phone_takeover" {
                if args[1] == "status" { return Self.paused ? #"{"paused":true,"token":"handoff"}"# : #"{"paused":false}"# }
                if Self.retrying { return #"{"ok":false}"# }
                Self.paused = false
                return #"{"ok":true}"#
            }
            return Self.response
        }
    }
}
@main struct Checks {
    @MainActor static func reset(_ response: String? = "", paused: Bool = true) {
        PyRuntime.reset(response, paused: paused)
        PresenceCoordinator.shared.adopted = []
        PresenceCoordinator.shared.wakes = 0
        DebugLog.lines = []
    }
    @MainActor static func main() async {
        let coordinator = PresenceCoordinator.shared
        for token: String? in [nil, ""] {
            reset()
            await PresenceActions.perform(.answer, cid: "a", text: "Green", replyToken: token)
            precondition(PyRuntime.calls.isEmpty && coordinator.adopted.isEmpty)
            precondition(coordinator.wakes == 1 && !DebugLog.lines.isEmpty)
        }
        for rejected: String? in ["Question expired", nil] {
            reset(rejected)
            await PresenceActions.perform(.answer, cid: "a", text: "Green", replyToken: "old:41")
            precondition(PyRuntime.calls == [["send2", "a", "Green", "old:41"]])
            precondition(coordinator.adopted.isEmpty && coordinator.wakes == 1 && !DebugLog.lines.isEmpty)
        }
        for text in ["/clear", "Keep  all", "  Keep files  ", "Line one\nline two", "Use\tcurrent"] {
            reset()
            await PresenceActions.perform(.answer, cid: "a", text: text, replyToken: "current:42")
            precondition(PyRuntime.calls == [["send2", "a", text, "current:42"]])
            precondition(coordinator.adopted == ["a"] && coordinator.wakes == 1)
        }
        reset()
        await PresenceActions.perform(.resume, cid: "a", text: "")
        precondition(PyRuntime.calls == [["phone_takeover", "a", "status"],
            ["phone_takeover", "a", "resume", "handoff"], ["send2", "a", coordinator.copy.resumePrompt]])
        precondition(coordinator.adopted == ["a"])
        await PresenceActions.perform(.resume, cid: "a", text: "")
        precondition(PyRuntime.calls.filter { $0[0] == "send2" }.count == 1, "repeated hand-back cannot start another turn")
        reset(paused: false)
        await PresenceActions.perform(.resume, cid: "a", text: "")
        precondition(PyRuntime.calls == [["phone_takeover", "a", "status"]])
        precondition(coordinator.adopted.isEmpty && coordinator.wakes == 1 && !DebugLog.lines.isEmpty)
        reset("Task busy")
        await PresenceActions.perform(.resume, cid: "a", text: "")
        precondition(coordinator.adopted.isEmpty && coordinator.wakes == 1)
        precondition(!DebugLog.lines.contains { $0.contains("handed back;") })
        reset()
        await PresenceActions.perform(.resume, cid: "a", text: "", page: { cid, text in
            precondition(cid == "a" && text == coordinator.copy.resumePrompt)
            return true
        })
        precondition(!PyRuntime.calls.contains { $0[0] == "send2" }, "a page-owned turn must not send twice")
        reset()
        await PresenceActions.perform(.resume, cid: "a", text: "", page: { _, _ in false })
        precondition(!PyRuntime.calls.contains { $0[0] == "send2" }, "a cancelled or failed page send must not be retried by the native surface")
        precondition(coordinator.adopted.isEmpty)
        reset()
        await PresenceActions.perform(.resume, cid: "a", text: "", page: { _, _ in nil })
        precondition(PyRuntime.calls.filter { $0[0] == "send2" }.count == 1, "an unavailable page can hand sending to the native surface")
        reset(paused: true)
        PyRuntime.shared.ready = false
        let stopped = Task { await PresenceActions.perform(.stop, cid: "a", text: "") }
        try? await Task.sleep(for: .milliseconds(40))
        precondition(PhoneRunActivity.shared.cancellations == 1, "native input must stop before the engine is ready")
        PyRuntime.shared.ready = true
        await stopped.value
        precondition(PyRuntime.calls.contains(["phone_takeover", "a", "cancel", "handoff"]))
        // Native hand-back completed, but its reply is still in flight when the user ends the task.
        reset(paused: true)
        let gate = PyRuntime.delayResume()
        let resuming = Task { await PresenceActions.perform(.resume, cid: "a", text: "") }
        for _ in 0..<100 where !PyRuntime.waitingForResume {
            try? await Task.sleep(for: .milliseconds(10))
        }
        precondition(PyRuntime.waitingForResume)
        await PresenceActions.perform(.stop, cid: "a", text: "")
        gate.signal()
        await resuming.value
        precondition(!PyRuntime.calls.contains { $0[0] == "send2" }, "a late hand-back reply must not restart a stopped task")
        precondition(coordinator.adopted.isEmpty)
        reset(paused: true)
        PyRuntime.shared.ready = false
        let earlyResume = Task { await PresenceActions.perform(.resume, cid: "a", text: "") }
        try? await Task.sleep(for: .milliseconds(20))
        let earlyStop = Task { await PresenceActions.perform(.stop, cid: "a", text: "") }
        try? await Task.sleep(for: .milliseconds(20))
        PyRuntime.shared.ready = true
        await earlyResume.value
        await earlyStop.value
        precondition(!PyRuntime.calls.contains { $0[0] == "send2" || $0 == ["phone_takeover", "a", "resume", "handoff"] },
                     "stop during engine startup must cancel an earlier hand-back")
        reset(paused: true)
        PyRuntime.rejectHandoffChanges(true)
        var retryFinished = false
        let retry = Task { await PresenceActions.perform(.resume, cid: "a", text: ""); retryFinished = true }
        for _ in 0..<100 where !PyRuntime.calls.contains(["phone_takeover", "a", "resume", "handoff"]) {
            try? await Task.sleep(for: .milliseconds(10))
        }
        await PresenceActions.perform(.stop, cid: "a", text: "")
        let attempts = PyRuntime.calls.filter { $0 == ["phone_takeover", "a", "resume", "handoff"] }.count
        try? await Task.sleep(for: .milliseconds(650))
        precondition(retryFinished, "a stopped hand-back must not keep retrying if native cancellation was rejected")
        precondition(PyRuntime.calls.filter { $0 == ["phone_takeover", "a", "resume", "handoff"] }.count == attempts)
        PyRuntime.rejectHandoffChanges(false)
        await retry.value
        print("PASS: bound answers, rejected/no-result sends, preserved text, paused handback and page-owned send")
    }
}
''')
    executable = tmp_path / "actions"
    compiled = subprocess.run(
        ["xcrun", "swiftc", str(PRESENCE / "App/PresenceActions.swift"), str(harness), "-o", str(executable)],
        capture_output=True, text=True, timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "PASS: bound answers" in result.stdout


def test_old_notification_callbacks_cannot_restore_replaced_questions(tmp_path):
    source = (PRESENCE / "App/NotificationSurface.swift").read_text()
    # Compile the actual display/routing methods with a local notification-centre recorder.
    methods = source[source.index("    func show("):source.index("    // MARK:")]
    methods = methods.replace("UNNotificationResponse", "Response").replace("UNTextInputNotificationResponse", "TextResponse")
    harness = tmp_path / "Notifications.swift"
    harness.write_text(r'''
import Foundation
import UserNotifications
enum PresenceCommand: String { case stop, pause, resume, answer }
struct Notice { let request: UNNotificationRequest }
class Response {
    let notification: Notice, actionIdentifier: String
    init(_ request: UNNotificationRequest, _ action: String) { notification = Notice(request: request); actionIdentifier = action }
}
class TextResponse: Response {
    let userText: String
    init(_ request: UNNotificationRequest, text: String) { userText = text; super.init(request, "reply") }
}
@MainActor final class Centre {
    var callbacks: [(Set<UNNotificationCategory>) -> Void] = []
    var added: [UNNotificationRequest] = [], removed: [String] = [], pending: [String] = []
    var categories = 0
    func getNotificationCategories(_ callback: @escaping (Set<UNNotificationCategory>) -> Void) { callbacks.append(callback) }
    func setNotificationCategories(_ values: Set<UNNotificationCategory>) { categories += 1 }
    func removeDeliveredNotifications(withIdentifiers ids: [String]) { removed += ids }
    func removePendingNotificationRequests(withIdentifiers ids: [String]) { pending += ids }
    func add(_ request: UNNotificationRequest) { added.append(request) }
}
@MainActor final class NotificationSurface {
    private var asked: String?
    private static let prefix = "ga.presence.", category = "ga.presence.ask"
    let center = Centre()
    func route(_ response: Response) -> (PresenceCommand, String)? { Self.command(response) }
''' + methods + r'''
}
@main struct Checks {
    @MainActor static func state(_ cid: String, _ token: String) -> PresenceState {
        PresenceState(cid: cid, phase: .asking, title: "Task", step: 1, now: "Question", trail: [],
            ask: .init(question: "Question", choices: ["Yes", "  Keep files  "], replyToken: token),
            startedAt: .distantPast, phaseSince: .distantPast, english: true)
    }
    @MainActor static func settle() async { try? await Task.sleep(for: .milliseconds(10)) }
    @MainActor static func main() async {
        let surface = NotificationSurface(), center = surface.center
        surface.show(state("a", "old:41"), ring: true)
        surface.show(state("a", "new:42"), ring: true)
        precondition(center.removed == ["ga.presence.ask.a.old:41"])
        precondition(center.pending == center.removed)
        center.callbacks[0]([])
        await settle()
        precondition(center.added.isEmpty && center.categories == 0, "late old callbacks must do nothing")
        center.callbacks[1]([])
        await settle()
        precondition(center.added.map(\.identifier) == ["ga.presence.ask.a.new:42"])
        let content = center.added[0].content
        precondition(content.userInfo["reply_token"] as? String == "new:42")
        precondition(content.userInfo["resume_prompt"] as? String == PresenceCopy(english: true).resumePrompt)
        let done = surface.route(Response(center.added[0], "resume"))
        precondition(done?.0 == .answer && done?.1 == PresenceCopy(english: true).resumePrompt)
        let choice = surface.route(Response(center.added[0], "choice.1"))
        precondition(choice?.0 == .answer && choice?.1 == "  Keep files  ")
        let typed = surface.route(TextResponse(center.added[0], text: "/clear"))
        precondition(typed?.0 == .answer && typed?.1 == "/clear")
        surface.show(state("b", "other:1"), ring: true)
        precondition(center.removed.last == "ga.presence.ask.a.new:42", "another conversation removes the previous question")
        surface.show(nil, ring: false)
        precondition(center.removed.last == "ga.presence.ask.b.other:1")
        center.callbacks[2]([])
        await settle()
        precondition(center.added.count == 1 && center.categories == 1, "a cleared question cannot return")
        print("PASS: question replacement, foreign conversation, cleared question, token payload, late callbacks")
    }
}
''')
    executable = tmp_path / "notifications"
    compiled = subprocess.run(
        ["xcrun", "swiftc", str(PRESENCE / "Core/PresenceState.swift"),
         str(PRESENCE / "Core/PresenceSnapshot.swift"), str(PRESENCE / "Core/PresenceCopy.swift"),
         str(harness), "-o", str(executable)],
        capture_output=True, text=True, timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "PASS: question replacement" in result.stdout
