import XCTest
@testable import BoardKitHarness

final class PhoneTakeoverTests: XCTestCase {
    func testOnlyTheMatchingHandoffCanReturnControl() {
        var state = PhoneTakeover()
        XCTAssertFalse(state.paused)
        let token = state.pause()
        XCTAssertTrue(state.paused)
        XCTAssertFalse(state.resume("another-conversation"))
        XCTAssertTrue(state.paused)
        XCTAssertTrue(state.resume(token))
        XCTAssertFalse(state.paused)
        XCTAssertFalse(state.resume(token))
    }

    func testOldResumeCannotReleaseANewerHandoff() {
        var state = PhoneTakeover()
        let old = state.pause()
        let current = state.pause()
        XCTAssertFalse(state.resume(old))
        XCTAssertTrue(state.paused)
        XCTAssertTrue(state.resume(current))
        XCTAssertFalse(state.paused)
        XCTAssertFalse(state.resume(current))
    }
}
