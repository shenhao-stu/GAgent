import Foundation

/// Screen source: frames sampled on this iPhone by the Broadcast Upload Extension, on request.
/// A still screen emits no samples, so a request may need the stimulus to produce one.
@MainActor final class ReplayCapture: CaptureSource {
    let name = "replaykit"
    /// Seconds the extension keeps pictures coming after each look at it while the screen settles: longer than
    /// the longest pause between two looks (the 0.7 s a transition between apps is given before the first).
    private static let keep = 1.5
    private let replay = ReplayScreen()
    private var monitor: Task<Void, Never>?
    private var selected = false

    var access: @MainActor () throws -> Void = {}
    var inputMark: @MainActor () -> InputMark = { InputMark() }
    weak var stimulus: ScreenStimulus?
    /// The sharing session started, stopped or was replaced; `wasSharing` tells whether one was running.
    var onSessionChange: ((Bool) -> Void)?
    var onChange: () -> Void = {}

    init() {
        replay.onSessionChange = { [weak self] wasSharing in self?.onSessionChange?(wasSharing) }
    }

    var generation: Int { replay.generation }
    var sharing: Bool { replay.sessionID != nil }
    var preview: Data? { replay.lastSample?.jpeg }

    func requireSharing() throws {
        guard sharing else { throw DeviceError(message: "Start sharing the screen with GAgent") }
    }

    func freshness() -> FrameFreshness.Verdict {
        guard sharing else { return .unavailable("ReplayKit sharing stopped") }
        guard let frame = replay.lastSample,
              frame.uptime >= (inputMark().uptime ?? 0),
              ProcessInfo.processInfo.systemUptime - frame.uptime <= FrameFreshness.proofWindow else { return .awaitingFrame }
        return .current
    }

    func frame() async throws -> CapturedFrame {
        try access()
        let captured: ReplayCaptureFrame
        do {
            try await replay.verify()
            // A static producer will not answer a fresh request until pixels change, and waiting for it to time
            // out took 2.7 s (2026-11-12): go straight to the stimulus when it has nothing to hand over.
            if let state = replay.diagnostics, let sample = state.sampleUptime {
                let kept = state.encodedSequence == state.samples && sample >= (inputMark().uptime ?? 0)
                if ScreenRest.needsStimulus(still: ProcessInfo.processInfo.systemUptime - sample, keptAfterInput: kept) {
                    throw ReplayWire.Fault.noFrame
                }
            }
            captured = try await replay.snapshot(after: inputMark().uptime, expected: nil)
        } catch ReplayWire.Fault.noFrame {
            guard let stimulus else {
                throw DeviceError(message: "The screen is still and no input device can refresh it; reconnect the input device and read again")
            }
            let expected = replay.generation
            // A static screen emits frames only during this brief movement. The extension keeps them while the
            // pointer goes aside and comes back, and the last one is taken: the pointer is then where it was, as
            // in a picture the screen gave by itself. Caught aside in one picture and at rest in the next, it made
            // two pictures of the same page differ.
            let began = ProcessInfo.processInfo.systemUptime
            try await replay.verify(expected: expected, keep: Self.keep)
            do {
                let step = try await stimulus.refresh(generation: expected)
                try await Task.sleep(for: .milliseconds(180))
                try await stimulus.undoRefresh(step, generation: expected)
            } catch {
                stimulus.stimulusFailed()
                throw error
            }
            await comeToRest()
            captured = try await replay.snapshot(after: began, expected: expected)
        }
        try requireReadable(generation: replay.generation)
        onChange()
        return CapturedFrame(jpeg: captured.jpeg, generation: replay.generation,
                             capturedAt: now() - (ProcessInfo.processInfo.systemUptime - captured.uptime),
                             size: CGSize(width: captured.width, height: captured.height),
                             sequence: captured.sequence, sampleUptime: captured.uptime)
    }

    /// The extension took the original on demand, so recognition describes its exact pixels: revalidate the share,
    /// and request a replacement only if the sample itself has expired.
    func presentable(_ original: CapturedFrame) async throws -> CapturedFrame {
        try await replay.verify(expected: original.generation)
        try requireReadable(generation: original.generation)
        if let sample = original.sampleUptime, sample >= (inputMark().uptime ?? 0),
           ProcessInfo.processInfo.systemUptime - sample <= FrameFreshness.proofWindow {
            return original
        }
        return try await frame()
    }

    func proves(_ frame: CapturedFrame) -> Bool {
        frame.capturedAt >= (inputMark().wall ?? 0) && now() - frame.capturedAt <= FrameFreshness.proofWindow
    }

    /// Let UIKit commit the action, then let the screen come to rest. The following request independently
    /// enforces the post-input sample boundary.
    func settle(since sent: Double, minimum: Double) async {
        _ = try? await replay.verify(keep: Self.keep)  // keep what the input brings from now on
        let remaining = minimum - (ProcessInfo.processInfo.systemUptime - sent)
        if remaining > 0 { try? await Task.sleep(for: .seconds(remaining)) }
        await comeToRest()
    }

    /// Waits for substantial content changes to stop (ScreenRest). Cursor/clock changes below the thumbnail
    /// threshold do not restart the wait. Sample timestamps still independently prove freshness.
    /// Meanwhile the extension keeps the newest sample
    /// as a picture, so the frame a transition ends on is ready when the read asks for it and no pointer movement
    /// is needed to make the still screen emit another.
    func comeToRest() async {
        let uptime = { ProcessInfo.processInfo.systemUptime }
        await ScreenRest.wait(from: uptime(), now: uptime, newestSample: { [replay] in
            // A share that stopped ends the wait; the read that follows reports it.
            guard (try? await replay.verify(keep: Self.keep)) != nil else { return nil }
            return replay.diagnostics?.contentUptime ?? replay.diagnostics?.sampleUptime
        }, sleep: { try? await Task.sleep(for: .seconds($0)) })
    }

    /// A paused exporter may still answer pings. Long gestures and calibration must also have recent pixels.
    func proveLive(generation: Int, forStimulus: Bool) async throws {
        if forStimulus {
            try await replay.verify(expected: generation)
        } else if let sample = replay.lastSample,
                  ProcessInfo.processInfo.systemUptime - sample.uptime <= FrameFreshness.proofWindow {
            try await replay.verify(expected: generation)
        } else {
            // This is a liveness check during a gesture, not a post-action observation. A fresh real sample from
            // the pointer move can precede its ACK; the next model image still has to cross the input mark.
            _ = try await replay.snapshot(after: nil, expected: generation)
        }
    }

    func setSelected(_ selected: Bool) {
        self.selected = selected
        replay.reset()
        watch()
    }

    /// Keep the session state current while this source is selected: the UI shows it and input depends on it.
    func watch() {
        monitor?.cancel()
        monitor = nil
        guard selected else { return }
        monitor = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                _ = try? await replay.verify()
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
            }
        }
    }

    /// Selected at launch: start watching without discarding a session that may already be running.
    func start() {
        selected = true
        watch()
    }

    /// One status request, so a status reply reflects the session as it is now.
    func refresh() async { _ = try? await replay.verify() }

    func linkUp() {}
    func linkLost() { replay.reset() }

    var diagnostics: [String: Any] {
        guard selected else { return [:] }
        var result: [String: Any] = ["video_transport": "local"]
        if let d = replay.diagnostics {
            var capture: [String: Any] = ["samples": d.samples, "timeouts": d.timeouts, "clock_rejected": d.clockRejected]
            capture["callback_age_s"] = d.callbackUptime.map { ReplayWire.now - $0 }
            capture["sample_age_s"] = d.sampleUptime.map { ReplayWire.now - $0 }
            capture["encoded_sequence"] = d.encodedSequence
            capture["content_age_s"] = d.contentUptime.map { ReplayWire.now - $0 }
            capture["changed_fraction"] = d.changedFraction
            result["capture_diagnostics"] = capture
        }
        return result
    }
}
