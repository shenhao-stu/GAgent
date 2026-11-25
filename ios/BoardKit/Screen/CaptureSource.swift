import CoreGraphics
import Foundation

/// When the last input left for the phone, on the two clocks the sources use. A frame sampled before it cannot
/// show that input's result. This time is the only thing the screen side ever learns about input.
struct InputMark {
    var wall: Double?    // now(): seconds since 1970
    var uptime: Double?  // ProcessInfo.systemUptime
}

/// One picture of the phone, with the sharing session it came from.
struct CapturedFrame {
    let jpeg: Data
    let generation: Int
    let capturedAt: Double
    let size: CGSize
    var sequence: UInt64? = nil
    var sampleUptime: Double? = nil
    /// Where a visible pointer was when the frame was taken; masked when frames are compared.
    var pointer: CGPoint? = nil
}

/// A small pointer movement that presses nothing: the only way to make a still screen emit a frame.
/// The screen side asks for it through this protocol and never learns which device moves the pointer.
@MainActor protocol ScreenStimulus: AnyObject {
    var stimulusReady: Bool { get }
    /// A fixed, unobserved step authorized for one sharing generation. Returns the step to undo.
    func refresh(generation: Int) async throws -> Int
    func undoRefresh(_ step: Int, generation: Int) async throws
    /// An observed step: it moves the input mark, so only frames after it count as proof. Returns the step to undo.
    func nudge(_ units: Int) async throws -> Int
    func unnudge(_ step: Int) async throws
    /// A stimulus failed halfway: the pointer is no longer where it was believed to be.
    func stimulusFailed()
}

/// One way of getting the phone's pixels (ReplayKit, AirPlay, ...). It never sends input.
@MainActor protocol CaptureSource: AnyObject {
    var name: String { get }
    /// Changes whenever the sharing session does; frames and observations of another generation are void.
    var generation: Int { get }
    var sharing: Bool { get }
    var preview: Data? { get }

    /// Injected by the coordinator: user consent and takeover, the last input's time, and the stimulus.
    var access: @MainActor () throws -> Void { get set }
    var inputMark: @MainActor () -> InputMark { get set }
    var stimulus: ScreenStimulus? { get set }

    /// Throws when no session can deliver frames now.
    func requireSharing() throws
    /// Whether the newest frame is proven to be the current screen.
    func freshness() -> FrameFreshness.Verdict
    /// A frame sampled after the last input. May use the stimulus when a still screen sends nothing.
    func frame() async throws -> CapturedFrame
    /// After slow work on `original` (recognition): the frame that may be presented now, itself or a newer one.
    func presentable(_ original: CapturedFrame) async throws -> CapturedFrame
    /// Whether `frame` was taken after the last input and its live proof still holds.
    func proves(_ frame: CapturedFrame) -> Bool
    /// After an input that left at uptime `sent`: wait until its result can have reached this source.
    func settle(since sent: Double, minimum: Double) async
    /// Before a read that follows no input: wait, within a bound, for a screen that is moving (an app opening,
    /// a page loading) to come to rest. A source that cannot tell returns at once.
    func comeToRest() async
    /// Proof at the write boundary that the session is live, before any input is written.
    func proveLive(generation: Int, forStimulus: Bool) async throws

    /// The user chose this source, or another one.
    func setSelected(_ selected: Bool)
    /// The input device's link came up or went down. Sources that receive frames through it follow.
    func linkUp()
    func linkLost()
    var diagnostics: [String: Any] { get }
}

extension CaptureSource {
    func comeToRest() async {}

    /// Re-evaluated after every suspension: an earlier frame grants no ongoing permission.
    func requireReadable(generation expected: Int? = nil) throws {
        try access()
        if let expected, expected != generation { throw ScreenObservation.Failure.frameChanged }
        try requireSharing()
    }
}
