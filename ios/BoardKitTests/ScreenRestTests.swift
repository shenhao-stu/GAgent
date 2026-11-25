import XCTest
@testable import BoardKitHarness

@MainActor final class ScreenRestTests: XCTestCase {
    /// A clock that only `sleep` advances, and a screen whose samples arrive at the listed times.
    private func wait(samples: [Double], from start: Double = 10, source: Bool = true) async -> (ended: Double, looks: Int) {
        var clock = start, looks = 0
        await ScreenRest.wait(from: start, now: { clock },
                              newestSample: {
                                  looks += 1
                                  return source ? samples.last { $0 <= clock } : nil
                              },
                              sleep: { clock += $0 })
        return (clock, looks)
    }

    func testAStillScreenIsReadAtOnce() async {
        let result = await wait(samples: [9.0])
        XCTAssertEqual(result.ended, 10)
        XCTAssertEqual(result.looks, 1)
    }

    func testItWaitsOnlyUntilTheLastSampleIsQuietEnough() async {
        let result = await wait(samples: [9.9])
        XCTAssertEqual(result.ended, 9.9 + ScreenRest.quiet, accuracy: 1e-9)
        XCTAssertEqual(result.looks, 2)
    }

    func testATransitionIsWaitedOutAndThenTheQuietTime() async {
        let frames = stride(from: 9.9, through: 10.5, by: 1.0 / 60).map { $0 }  // a transition running until 10.5
        let result = await wait(samples: frames)
        XCTAssertEqual(result.ended, frames.last! + ScreenRest.quiet, accuracy: 1e-9)
    }

    func testAScreenThatNeverRestsIsReadAfterTheLimit() async {
        let video = stride(from: 9.0, through: 20, by: 1.0 / 30).map { $0 }
        let result = await wait(samples: video)
        XCTAssertEqual(result.ended, 10 + ScreenRest.limit, accuracy: 1e-9)
    }

    func testASourceThatCannotTellEndsTheWait() async {
        let result = await wait(samples: [], source: false)
        XCTAssertEqual(result.ended, 10)
    }

    func testASourceThatHasNoSampleYetEndsTheWait() async {
        let result = await wait(samples: [])
        XCTAssertEqual(result.ended, 10)
    }

    func testARestedScreenNeedsAStimulusUnlessItsLastPictureWasKept() {
        // Still changing: the next sample answers the request.
        XCTAssertFalse(ScreenRest.needsStimulus(still: 0.1, keptAfterInput: false))
        // At rest with the transition's last picture kept: handed over as it is.
        XCTAssertFalse(ScreenRest.needsStimulus(still: 0.4, keptAfterInput: true))
        // At rest with nothing kept: no sample will come by itself (waiting for one cost 2.7 s).
        XCTAssertTrue(ScreenRest.needsStimulus(still: 0.4, keptAfterInput: false))
        // Too old to stand for the screen, kept or not.
        XCTAssertTrue(ScreenRest.needsStimulus(still: 1.2, keptAfterInput: true))
    }
}
