import UIKit
import XCTest
@testable import BoardKitHarness

final class ScreenObservationTests: XCTestCase {
    private func picture(marker: CGRect? = nil) -> Data {
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 100, height: 200))
        return renderer.pngData { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 100, height: 200))
            UIColor.black.setFill()
            if let marker { context.fill(marker) }
        }
    }

    func testSameVisiblePixelsKeepObservationWithoutAnExpiryClock() throws {
        var observation = ScreenObservation()
        let original = picture()
        let id = observation.capture(original, generation: 1)
        // Different encoded bytes, identical visible pixels. There is deliberately no timestamp input.
        let recoded = try XCTUnwrap(UIImage(data: original)?.jpegData(compressionQuality: 0.8))
        XCTAssertNotEqual(original, recoded)
        XCTAssertTrue(observation.samePage(recoded, generation: 1))
        XCTAssertNotEqual(observation.capture(recoded, generation: 1), id, "element numbers always identify exact image bytes")
        XCTAssertFalse(try observation.require(id, current: recoded, generation: 1,
                                               target: CGPoint(x: 0.5, y: 0.6)))
    }

    func testChangedSmallControlRejectsTheModelsOldObservation() throws {
        var observation = ScreenObservation()
        let id = observation.capture(picture(), generation: 1)
        let changed = observation.capture(picture(marker: CGRect(x: 40, y: 100, width: 5, height: 5)), generation: 1)
        XCTAssertNotEqual(changed, id)
        XCTAssertThrowsError(try observation.require(id)) {
            XCTAssertEqual($0 as? ScreenObservation.Failure, .frameChanged)
        }
        XCTAssertNoThrow(try observation.require(changed))
    }

    func testStatusBarActivityAloneDoesNotInvalidateTheObservedApp() {
        var observation = ScreenObservation()
        _ = observation.capture(picture(), generation: 1)
        let clockChanged = picture(marker: CGRect(x: 0, y: 0, width: 100, height: 8))
        XCTAssertTrue(observation.samePage(clockChanged, generation: 1))
    }

    func testChangedIslandIsCheckedWhenTheIslandItselfIsTheTarget() {
        var observation = ScreenObservation()
        let id = observation.capture(picture(), generation: 1)
        let island = picture(marker: CGRect(x: 38, y: 4, width: 24, height: 8))
        XCTAssertTrue(observation.samePage(island, generation: 1), "progress does not invalidate the app below")
        XCTAssertThrowsError(try observation.require(id, current: island, generation: 1,
                                                     target: CGPoint(x: 0.5, y: 0.04)),
                             "when aiming at the island, its own changed controls cannot be masked out")
    }

    func testReconnectInvalidatesEvenIdenticalPixels() throws {
        var observation = ScreenObservation()
        let image = picture(), id = observation.capture(image, generation: 1)
        XCTAssertNotEqual(observation.capture(image, generation: 2), id)
        XCTAssertThrowsError(try observation.require(id))
    }

    func testNoPriorObservationFailsAndLegacyDiagnosticsRemainCompatible() throws {
        let observation = ScreenObservation()
        XCTAssertThrowsError(try observation.require("unseen"))
        XCTAssertNoThrow(try observation.require(nil))
        XCTAssertNil(try ScreenObservation.requestedID(nil))
        XCTAssertEqual(try ScreenObservation.requestedID("A_1-2:3"), "A_1-2:3")
        for invalid: Any in ["", "a b", "中文", "\n", String(repeating: "a", count: 129), 12, NSNull()] {
            XCTAssertThrowsError(try ScreenObservation.requestedID(invalid))
        }
    }

    func testPointerNudgeOrFadeKeepsTheObservationButOtherChangesDoNot() {
        var observation = ScreenObservation()
        let pointer = CGPoint(x: 0.5, y: 0.5)
        _ = observation.capture(picture(marker: CGRect(x: 48, y: 98, width: 5, height: 5)), generation: 1, pointer: pointer)
        XCTAssertTrue(observation.samePage(picture(), generation: 1, pointer: pointer), "pointer faded")
        XCTAssertTrue(observation.samePage(picture(marker: CGRect(x: 50, y: 98, width: 5, height: 5)), generation: 1,
                                           pointer: CGPoint(x: 0.52, y: 0.5)), "pointer nudged")
        XCTAssertFalse(observation.samePage(picture(marker: CGRect(x: 10, y: 150, width: 5, height: 5)), generation: 1,
                                              pointer: pointer), "content away from the pointer changed")
    }

    func testBlinkingCaretAndSystemActivityBannerKeepTheObservation() {
        var observation = ScreenObservation()
        // Proportions of the real 720x1560 frames: a caret is under 1 % of the width and about 3 % of the height.
        _ = observation.capture(picture(marker: CGRect(x: 30, y: 120, width: 1, height: 8)), generation: 1)
        XCTAssertTrue(observation.samePage(picture(), generation: 1), "caret off")
        XCTAssertTrue(observation.samePage(picture(marker: CGRect(x: 10, y: 4, width: 80, height: 16)), generation: 1),
                       "Dynamic Island progress banner")
        XCTAssertFalse(observation.samePage(picture(marker: CGRect(x: 30, y: 120, width: 12, height: 8)), generation: 1),
                          "a typed character next to the caret")
    }

    func testReturningFromAnalysisRechecksConsentGenerationAndCancellation() async {
        XCTAssertNoThrow(try ScreenObservation.requireAccess(consent: true, generation: 3, expected: 3))
        XCTAssertThrowsError(try ScreenObservation.requireAccess(consent: false, generation: 3, expected: 3))
        XCTAssertThrowsError(try ScreenObservation.requireAccess(consent: true, generation: 4, expected: 3))
        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            try ScreenObservation.requireAccess(consent: true, generation: 3, expected: 3)
        }
        do { try await cancelled.value; XCTFail("cancelled recognition must not publish its frame") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    func testLatestPresentedIDCannotBypassChangedTargetOrGeneration() {
        var observation = ScreenObservation()
        let image = picture(), id = observation.capture(image, generation: 1)
        let target = CGPoint(x: 0.5, y: 0.5)
        let moved = picture(marker: CGRect(x: 40, y: 90, width: 20, height: 20))
        XCTAssertThrowsError(try observation.require(id, current: moved, generation: 1, target: target))
        XCTAssertThrowsError(try observation.require(id, current: image, generation: 2))
    }

    func testInputWithoutATargetAsksOnlyThatItsObservationStillStands() {
        var observation = ScreenObservation()
        let old = observation.capture(picture(), generation: 1)
        _ = observation.capture(picture(marker: CGRect(x: 0, y: 40, width: 100, height: 40)), generation: 1)
        XCTAssertNoThrow(try observation.requireKnown(old, generation: 1), "keys and system gestures aim at no point of the page")
        XCTAssertThrowsError(try observation.requireKnown(old, generation: 2), "another sharing session")
        XCTAssertThrowsError(try observation.requireKnown("unseen", generation: 1)) {
            XCTAssertEqual($0 as? ScreenObservation.Failure, .frameChanged)
        }
        XCTAssertThrowsError(try observation.require(old), "the whole page, when a caller compares it")
    }

    /// The target is checked once the pointer has reached it, so the newest picture shows the pointer on the target.
    func testPointerRestingOnTheTargetIsNotAChangedTarget() throws {
        var observation = ScreenObservation()
        let seen = observation.capture(picture(), generation: 1, pointer: CGPoint(x: 0.2, y: 0.2))
        let target = CGPoint(x: 0.5, y: 0.5)
        let arrived = picture(marker: CGRect(x: 48, y: 98, width: 5, height: 5))
        XCTAssertNoThrow(try observation.require(seen, current: arrived, generation: 1,
                                                 target: target, pointer: target))
        let relabelled = picture(marker: CGRect(x: 40, y: 91, width: 20, height: 4))
        XCTAssertThrowsError(try observation.require(seen, current: relabelled, generation: 1,
                                                     target: target, pointer: target), "the control beside it changed")
    }

    func testPointerMaskKeepsItsScreenSizeAtAnEdgeTarget() {
        let blank = picture()
        let pointer = CGPoint(x: 0.015, y: 0.5)
        let moved = picture(marker: CGRect(x: 5, y: 99, width: 1, height: 2))
        XCTAssertFalse(Vision.changed(blank, moved, ignore: [pointer]))
        XCTAssertFalse(Vision.changed(blank, moved, near: pointer, ignore: [pointer]),
                       "clipping the target neighbourhood must not shrink the pointer mask")
        let outside = picture(marker: CGRect(x: 9, y: 99, width: 2, height: 2))
        XCTAssertTrue(Vision.changed(blank, outside, near: pointer, ignore: [pointer]),
                      "content outside the pointer mask is still checked")
    }

    /// The clock and the Dynamic Island change by themselves, right above a navigation bar the model aims at.
    func testStatusBarActivityAboveATargetIsNotAChangedTarget() throws {
        var observation = ScreenObservation()
        let seen = observation.capture(picture(), generation: 1)
        let back = CGPoint(x: 0.12, y: 0.09)
        let clock = picture(marker: CGRect(x: 8, y: 4, width: 14, height: 6))
        XCTAssertNoThrow(try observation.require(seen, current: clock, generation: 1, target: back))
        let banner = picture(marker: CGRect(x: 0, y: 4, width: 100, height: 22))
        XCTAssertThrowsError(try observation.require(seen, current: banner, generation: 1, target: back),
                             "a banner that reaches over the bar covers the target")
    }

    /// A busy WeChat group: new messages kept arriving above, so whole-screen comparison never let the model tap
    /// the input field at the bottom.
    func testTapStaysValidWhileOnlyContentAwayFromTheTargetChanged() throws {
        var observation = ScreenObservation()
        let seen = observation.capture(picture(), generation: 1)
        let newMessage = picture(marker: CGRect(x: 10, y: 40, width: 80, height: 30))
        _ = observation.capture(newMessage, generation: 1)
        let input = CGPoint(x: 0.45, y: 0.93)
        XCTAssertTrue(try observation.require(seen, current: newMessage, generation: 1, target: input),
                      "valid, and reported as a changed page")
        XCTAssertThrowsError(try observation.require(seen, current: newMessage, generation: 1,
                                                     target: CGPoint(x: 0.5, y: 0.27)), "the target itself moved")
        XCTAssertThrowsError(try observation.require(seen, current: newMessage, generation: 2, target: input),
                             "a new stream voids every observation")
    }
}
