"""Run the real lifecycle against a deterministic scheduler, without hardware or keepalive tricks."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phone_run_activity(tmp_path):
    source = (ROOT / 'ios/GAgent/PhoneRunActivity.swift').read_text()
    source = source.replace('import BackgroundTasks', 'import Foundation').replace('import UIKit', '')
    board = (ROOT / 'ios/BoardKit/BoardSession.swift').read_text()
    native_stop = '    @discardableResult func stop' + board.split('    @discardableResult func stop', 1)[1].split('\n    }', 1)[0] + '\n    }'
    fixture = r'''
@MainActor final class UIApplication {
    static let shared = UIApplication()
    enum State { case active, background }
    var applicationState = State.active
}
class BGTask {
    var expirationHandler: (() -> Void)?
    var results: [Bool] = []
    func setTaskCompleted(success: Bool) { results.append(success) }
}
final class BGContinuedProcessingTask: BGTask {
    let progress = Progress(totalUnitCount: 1)
    var captions: [String] = []
    func updateTitle(_ title: String, subtitle: String) { captions.append(title + " | " + subtitle) }
}
class BGContinuedProcessingTaskRequest {
    enum Strategy { case fail }
    var strategy = Strategy.fail
    let identifier: String
    init(identifier: String, title: String, subtitle: String) { self.identifier = identifier }
}
@MainActor final class BGTaskScheduler {
    static let shared = BGTaskScheduler()
    var handlers: [String: (BGTask) -> Void] = [:]
    var submitted: [String] = [], cancelled: [String] = []
    var reject = false
    func register(forTaskWithIdentifier id: String, using: DispatchQueue?, launchHandler: @escaping (BGTask) -> Void) -> Bool {
        handlers[id] = launchHandler; return true
    }
    func submit(_ request: BGContinuedProcessingTaskRequest) throws {
        if reject { throw NSError(domain: "test", code: 1) }; submitted.append(request.identifier)
    }
    func cancel(taskRequestWithIdentifier id: String) { cancelled.append(id) }
    func grant(_ id: String) -> BGContinuedProcessingTask {
        let task = BGContinuedProcessingTask(); handlers[id]!(task); return task
    }
}
@MainActor final class BoardSession {
    var onActivity: ((String) -> Void)?
    var backgroundRunState: () -> String = { "" }
    final class Screen { var forgotten = 0; func forget() { forgotten += 1 } }
    final class Input {
        var halts = 0
        var connected = true
        func halt() throws { halts += 1 }
    }
    final class Calibrator { var boardOpen = false; func cancel() { boardOpen = false } }
    let screen = Screen(), input = Input(), calibrator = Calibrator()
    var unsettled: Int? = nil
    var active: Task<Void, Never>?
    var stops: Int { input.halts }
    // NATIVE_STOP
}
final class PyRuntime: @unchecked Sendable {
    static let shared = PyRuntime()
    func call(fn: String, args: [String]) -> String { "ok" }
}
enum DebugLog { static func write(_ text: String) {} }
@MainActor var testTime = 0.0
@MainActor func now() -> Double { testTime }
'''
    main = r'''
@main struct Test {
    @MainActor static func main() async {
        UserDefaults.standard.removeObject(forKey: "gagent.systemProgress")
        let run = PhoneRunActivity(), board = BoardSession(), scheduler = BGTaskScheduler.shared
        run.attach(board)
        precondition(run.enabled)
        board.onActivity?("status"); precondition(scheduler.submitted.isEmpty)
        board.onActivity?("shot"); precondition(run.state == "starting")
        let id = scheduler.submitted.last!, task = scheduler.grant(id)
        precondition(run.state == "running")
        run.caption(title: "GAgent", subtitle: "step 1"); precondition(task.captions == ["GAgent | step 1"])
        run.caption(); precondition(task.captions.last == "GAgent · iPhone | 任务进行中") // Its own words again.
        board.onActivity?("completed"); precondition(task.progress.completedUnitCount == 1)
        board.onActivity?("status")
        try? await Task.sleep(for: .milliseconds(3200))
        precondition(task.progress.completedUnitCount == 1) // No timer-generated progress.
        board.stop(); precondition(task.results == [true] && scheduler.cancelled.contains(id))
        precondition(run.state == "idle")
        run.caption(title: "GAgent", subtitle: "late"); precondition(task.captions.count == 2) // No entry, no caption.
        board.onActivity?("completed") // A cancelled action cannot advance the next run.
        board.onActivity?("shot"); let oldID = scheduler.submitted.last!
        board.stop(); board.onActivity?("shot"); let newID = scheduler.submitted.last!
        let late = scheduler.grant(oldID); precondition(late.results == [true])
        precondition(run.state == "starting")
        let current = scheduler.grant(newID)
        precondition(current.progress.completedUnitCount == 0)
        current.expirationHandler?()
        try? await Task.sleep(for: .milliseconds(50))
        // The system ending its progress entry closes only the entry: the run itself is not stopped.
        precondition(current.results == [false] && run.state == "idle" && board.stops == 2)
        board.onActivity?("shot"); let disabled = scheduler.grant(scheduler.submitted.last!)
        run.setEnabled(false)
        precondition(disabled.results == [true] && run.state == "off" && board.stops == 2)
        board.onActivity?("shot"); precondition(run.state == "off")
        run.setEnabled(true); scheduler.reject = true
        board.onActivity?("shot"); precondition(run.state.hasPrefix("unavailable:"))
        scheduler.reject = false
        UIApplication.shared.applicationState = .background
        let count = scheduler.submitted.count
        board.onActivity?("shot"); precondition(scheduler.submitted.count == count)
        // Thinking for longer than the old idle budget retains background execution and never aborts.
        UIApplication.shared.applicationState = .active
        board.onActivity?("shot"); let thinking = scheduler.grant(scheduler.submitted.last!)
        run.observeContinuation(false, request: id)
        precondition(thinking.results.isEmpty, "an old idle snapshot cannot finish a new lease")
        run.observeContinuation(true, request: run.requestIdentifier)
        testTime += PhoneRunActivity.idleLimit + 1
        try? await Task.sleep(for: .milliseconds(3200))
        precondition(thinking.results.isEmpty && run.state == "running" && board.stops == 2)
        // An unanswered turn still needs the lease for a later answer from the background.
        run.observeContinuation(true, request: run.requestIdentifier)
        precondition(thinking.results.isEmpty)
        // Asking releases actual input and observations, while retaining the lease for a background answer.
        board.unsettled = 1
        let forgotten = board.screen.forgotten, halts = board.stops
        let released = board.stop(endRun: false)
        precondition(released["ok"] as? Bool == true && board.stops == halts + 1)
        precondition(board.screen.forgotten == forgotten + 1 && board.unsettled == nil)
        precondition(thinking.results.isEmpty && run.state == "running")
        // All turns have completed or explicitly handed over: no stale failure card, no abort.
        run.observeContinuation(false, request: run.requestIdentifier)
        precondition(thinking.results == [true] && run.state == "idle" && board.stops == 3)
        run.observeContinuation(false, request: run.requestIdentifier); precondition(thinking.results == [true])
        board.onActivity?("shot"); let idle = scheduler.grant(scheduler.submitted.last!)
        testTime += PhoneRunActivity.idleLimit + 1
        try? await Task.sleep(for: .milliseconds(3200))
        precondition(idle.results == [true] && run.state == "idle" && board.stops == 3)
        // Explicit stop still releases the input and aborts, separately from lease retirement.
        board.onActivity?("shot"); let cancelled = scheduler.grant(scheduler.submitted.last!)
        run.cancel(); precondition(cancelled.results == [false] && board.stops == 4)
        UserDefaults.standard.removeObject(forKey: "gagent.systemProgress")
        print("PASS: foreground request, real progress, caption, stop, stale grant, expiry, disable and denial")
    }
}
'''
    swift = tmp_path / 'PhoneRun.swift'
    swift.write_text('import Foundation\nlet testDefaults = UserDefaults(suiteName: \"gagent-run-test-\\(ProcessInfo.processInfo.processIdentifier)\")!\n' + (fixture.replace('    // NATIVE_STOP', native_stop) + source + main).replace('UserDefaults.standard', 'testDefaults'))
    binary = tmp_path / 'check'
    result = subprocess.run(['xcrun', 'swiftc', '-DGAGENT_RUN_ACTIVITY_TEST', '-parse-as-library', str(swift), '-o', str(binary)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    assert 'PASS:' in result.stdout
