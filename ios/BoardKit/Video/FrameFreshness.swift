import Foundation

/// When a captured frame may be shown to the model as the phone's current screen.
enum FrameFreshness {
    static let proofWindow = 2.0
    static let stimulusTimeout = 3.0
    static let caughtUpBytes = 8_192

    enum Verdict: Equatable {
        case current
        case probe              // no live proof: nudge the pointer, then wait for its frame
        case awaitingFrame      // the latest stimulus has not reached a received frame yet
        case catchingUp(Int)    // older frames still in flight (bytes)
        case unavailable(String)
    }

    static func verdict(now: Double, capturedAt: Double, stimulusAt: Double?, statusAt: Double,
                        lag: Int?) -> Verdict {
        guard now - statusAt < 3 else { return .unavailable("board status is stale") }
        if let lag, lag > caughtUpBytes { return .catchingUp(lag) }
        guard let stimulusAt else { return .probe }
        if capturedAt >= stimulusAt { return now - capturedAt <= proofWindow ? .current : .probe }
        return now - stimulusAt <= stimulusTimeout ? .awaitingFrame : .probe
    }
}
