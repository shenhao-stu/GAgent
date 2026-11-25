import Foundation

/// Coordinates authenticated requests with the lifetime of one Broadcast Upload Extension session.
/// The UI can display the last known status. Input always obtains its own live proof at the write boundary.
@MainActor final class ReplayScreen {
    private let client = ReplayCaptureClient()
    private(set) var sessionID: String?
    private(set) var generation = -1 // AirPlay generations are nonnegative.
    private(set) var lastSample: ReplayCaptureFrame?
    private(set) var diagnostics: ReplayWire.Diagnostics?
    var onSessionChange: ((Bool) -> Void)?

    func reset() { transition(to: nil, force: true) }

    private func transition(to session: String?, force: Bool = false) {
        guard force || session != sessionID else { return }
        let wasSharing = sessionID != nil
        sessionID = session
        generation -= 1
        lastSample = nil
        diagnostics = nil
        onSessionChange?(wasSharing)
    }

    /// keep: seconds the extension keeps the newest sample as a picture from now on (ReplayWire.Request.keep).
    @discardableResult func verify(expected: Int? = nil, keep: Double? = nil) async throws -> Int {
        let startedIn = generation
        if let expected, expected != startedIn { throw ScreenObservation.Failure.frameChanged }
        let state: ReplayCaptureStatus
        do { state = try await client.status(keep: keep) }
        catch {
            if !Task.isCancelled, startedIn == generation { transition(to: nil) }
            throw error
        }
        try Task.checkCancellation()
        guard generation == startedIn else { throw ScreenObservation.Failure.frameChanged }
        transition(to: state.active ? state.sessionID : nil)
        diagnostics = state.diagnostics
        guard sessionID != nil else { throw DeviceError(message: "Start sharing the screen with GAgent") }
        if let expected, expected != generation { throw ScreenObservation.Failure.frameChanged }
        return generation
    }

    func snapshot(after uptime: Double?, expected: Int?,
                  stimulus: (@MainActor () async throws -> Void)? = nil) async throws -> ReplayCaptureFrame {
        let verified = try await verify(expected: expected)
        guard let sessionID else { throw ScreenObservation.Failure.frameChanged }
        let frame = try await client.snapshot(afterUptime: uptime, expectedSession: sessionID, stimulus: stimulus)
        try Task.checkCancellation()
        guard generation == verified, frame.sessionID == sessionID,
              uptime.map({ frame.uptime >= $0 }) ?? true else { throw ScreenObservation.Failure.frameChanged }
        lastSample = frame
        return frame
    }
}
