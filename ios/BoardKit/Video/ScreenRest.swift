import Foundation

/// Wait for substantial content changes to stop. Sources without a content clock can use sample time.
/// Freshness always uses the real sample timestamp independently of this waiting heuristic.
enum ScreenRest {
    /// Seconds without a substantial content change after which the screen counts as still.
    static let quiet = 0.3
    /// A whole-screen video or animation may never rest; the wait is bounded.
    static let limit = 1.0
    /// Seconds without a sample after which even a kept picture is too old to stand for the screen.
    static let stale = 1.0

    /// Whether a source that hands over pictures on request has none to give until the screen changes again, so
    /// that only a stimulus gets one: nothing was sampled for `stale` seconds, or the screen is at rest and its
    /// newest sample is not a picture kept after the last input.
    static func needsStimulus(still: Double, keptAfterInput: Bool) -> Bool {
        still > stale || (still >= quiet && !keptAfterInput)
    }

    /// Returns once the screen has been still for `quiet`, or `limit` after `start`. `newestSample` is the time of
    /// the source's newest substantial change (or sample, if unknown) on the clock of `now`; nil ends the wait.
    @MainActor static func wait(from start: Double, now: @MainActor () -> Double,
                                newestSample: @MainActor () async -> Double?,
                                sleep: @MainActor (Double) async -> Void) async {
        while !Task.isCancelled && now() - start < limit {
            guard let sample = await newestSample() else { return }
            let still = now() - sample
            if still >= quiet { return }
            await sleep(min(quiet - still, limit - (now() - start)))
        }
    }
}
