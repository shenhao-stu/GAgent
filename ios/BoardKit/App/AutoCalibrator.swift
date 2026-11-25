import Foundation
import UIKit

/// Calibrates the pointer like a 3D printer's auto bed levelling, on the foreground calibration overlay:
/// the board homes the pointer, clicks at known mouse distances and the app catches the taps (`TouchProbe`),
/// then fits mouse units → screen fraction per axis and verifies an independent check tap.
@MainActor final class AutoCalibrator: ObservableObject {
    enum Phase: Equatable {
        case idle, homing, probeA, probeB, verifying, done, needsTap, failed

        var step: Int? {
            switch self {
            case .homing: return 1
            case .probeA: return 2
            case .probeB: return 3
            case .verifying: return 4
            default: return nil
            }
        }
    }

    struct Progress: Equatable { var done: Int, total: Int }

    static let tolerance = 0.015  // fraction of the screen; a bigger miss calibrates again

    @Published var phase = Phase.idle
    @Published var reason = ""
    @Published var progress: Progress?
    @Published var problem: String?
    @Published private(set) var boardOpen = false
    @Published var toast = false
    unowned let app: BoardSession
    var link = -1
    private var hide: Task<Void, Never>?
    private var current: Task<Void, Never>?

    init(app: BoardSession) { self.app = app }

    var busy: Bool { phase.step != nil }
    var boardReady: Bool { app.board.connected && app.inputAvailable && app.consent && !app.testingLink }

    var needed: Bool {
        let p = app.pointer
        guard p.calibrated else { return true }
        if let aspect = p.aspect, abs(aspect - DeviceScreen.aspect) > 0.02 { return true }
        return (p.quality ?? .infinity) > Self.tolerance
    }

    var offer: Bool { needed && boardReady && !busy && !boardOpen }

    func calibrate(why: String = String(localized: "requested")) {
        guard !busy, boardReady else { return }
        Task { await run(why: why) }
    }

    func ensureCalibrated() async -> Bool {
        while busy { try? await Task.sleep(nanoseconds: 200_000_000) }
        if !app.pointer.calibrated && boardReady { await run(why: String(localized: "before a run")) }
        return app.pointer.calibrated
    }

    func run(why: String) async {
        guard boardReady, DeviceScreen.foreground else { return }
        reason = why
        problem = nil
        progress = nil
        toast = false
        if DeviceScreen.foreground { openBoard() }
        let job = Task { await runOnce() }
        current = job
        await job.value
        current = nil
    }

    private func openBoard() {
        boardOpen = true
        app.probe.begin()
    }

    private func closeBoard() {
        boardOpen = false
        app.probe.end()
    }

    func cancel() {
        current?.cancel()
        if busy || phase == .needsTap { app.say("calibration: cancelled") }
        progress = nil
        phase = app.pointer.calibrated ? .done : .idle
        closeBoard()
        if app.board.connected { try? app.board.write("0 stop"); try? app.board.write("0 release") }
    }

    private func runOnce() async {
        app.say("calibration: \(reason)")
        guard boardOpen else { return failed("请保持 GAgent 在前台后重试校准。") }
        do {
            switch try await touchCalibrate(full: true) {
            case .done(let error): finished(error)
            case .noTaps: failed(Self.noTapsText)
            case .failed(let why):
                app.say("calibration: touch probe failed: \(why)")
                failed(why)
            }
        } catch {
            if Task.isCancelled { return }
            app.say("calibration: touch probe: \(error.localizedDescription)")
            failed(error.localizedDescription)
        }
    }

    static var noTapsText: String {
        String(localized: "Clicks are not reaching the screen. Enable AssistiveTouch and pair the board as a Bluetooth input device.")
    }

    func finished(_ error: Double) {
        guard !Task.isCancelled else { return }
        guard error <= Self.tolerance else { return failed("Calibration error exceeds 1.5%; retry calibration") }
        app.pointer.setQuality(error)
        app.confirmCalibration()
        link = app.board.commands.links
        progress = nil
        problem = nil
        phase = .done
        app.say(String(format: "calibration: ±%.1f%%", error * 100))
        closeBoard()
        toast = true
        hide?.cancel()
        hide = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            guard !Task.isCancelled else { return }
            self?.toast = false
        }
    }

    private func failed(_ why: String) {
        progress = nil
        problem = why
        phase = .failed
        app.say("calibration failed: \(why)")
    }
}
