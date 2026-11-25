import ActivityKit
import Foundation

/// The Live Activity of one task. Its content is the same state every other surface draws.
struct PresenceAttributes: ActivityAttributes {
    typealias ContentState = PresenceState

    var cid: String
    /// Whether the Lock Screen may show step text and the question. Fixed when the task starts.
    var lockDetail: Bool
}
