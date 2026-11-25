import UIKit
import XCTest
@testable import BoardKitHarness

/// The two tools behind fakes: a screen source that never sends input, an input backend that never reads pixels.
@MainActor private final class FakeSource: CaptureSource {
    let name = "fake"
    var generation = 1
    var sharing = true
    var preview: Data?
    var access: @MainActor () throws -> Void = {}
    var inputMark: @MainActor () -> InputMark = { InputMark() }
    var stimulus: ScreenStimulus?
    var pictures: [Data] = []
    var settled: [(since: Double, minimum: Double)] = []
    var selections: [Bool] = []
    var frameRequests = 0
    var presented: Data?

    func requireSharing() throws {
        guard sharing else { throw DeviceError(message: "not sharing") }
    }
    func freshness() -> FrameFreshness.Verdict { .current }
    func frame() async throws -> CapturedFrame {
        frameRequests += 1
        try requireReadable()
        let jpeg = pictures.count > 1 ? pictures.removeFirst() : pictures[0]
        return CapturedFrame(jpeg: jpeg, generation: generation, capturedAt: now(), size: CGSize(width: 100, height: 200))
    }
    func presentable(_ original: CapturedFrame) async throws -> CapturedFrame {
        guard let presented else { return original }
        return CapturedFrame(jpeg: presented, generation: generation, capturedAt: now(), size: original.size)
    }
    func proves(_ frame: CapturedFrame) -> Bool { true }
    func settle(since sent: Double, minimum: Double) async { settled.append((sent, minimum)) }
    func proveLive(generation: Int, forStimulus: Bool) async throws {}
    func setSelected(_ selected: Bool) { selections.append(selected) }
    func linkUp() {}
    func linkLost() {}
    var diagnostics: [String: Any] { [:] }
}

@MainActor private final class FakeBackend: InputBackend {
    let name = "fake"
    var connected = true
    var ready = true
    var transport = "ble"
    var revision = 0
    var lastInput = InputMark()
    var pointerLocation: CGPoint?
    var sent: [String] = []

    private func record(_ line: String) { sent.append(line); revision += 1 }
    func tap(_ x: Double, _ y: Double, count: Int) async throws { record("tap \(x) \(y)" + (count == 1 ? "" : " x\(count)")) }
    func longPress(_ x: Double, _ y: Double, seconds: Double) async throws { record("long \(x) \(y) \(seconds)") }
    func swipe(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, seconds: Double?, hold: Double, flick: Bool) async throws {
        record("\(flick ? "flick" : "swipe") \(x1) \(y1) \(x2) \(y2) \(seconds.map { "\($0)" } ?? "-") hold \(hold)")
    }
    func type(_ text: String) async throws { record("type \(text)") }
    func key(_ combo: String) async throws { record("key \(combo)") }
    func press(_ button: InputButton) async throws { record("button \(button.rawValue)") }
    func nudge(_ units: Int) async throws -> Int { units }
    func unnudge(_ step: Int) async throws {}
    func refresh(by step: Int, authorize: @escaping @MainActor () async throws -> InputPermit) async throws {}
    func invalidatePointer() {}
    func halt() throws { sent.append("halt") }
}

@MainActor final class ScreenHIDServiceTests: XCTestCase {
    private func picture(marker: CGRect? = nil) -> Data {
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 100, height: 200))
        return renderer.jpegData(withCompressionQuality: 0.9) { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 100, height: 200))
            UIColor.black.setFill()
            if let marker { context.fill(marker) }
        }
    }

    private func service(_ source: FakeSource) -> ScreenService {
        let screen = ScreenService(source: source)
        screen.read = { _ in
            ScreenElements.Reading(texts: [.init(box: CGRect(x: 0.4, y: 0.5, width: 0.2, height: 0.05), string: "发送")],
                                   controls: [], ocr: .ok, detector: .unavailable)
        }
        return screen
    }

    func testScreenPublishesAnObservationWithoutAnyInputDevice() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        let first = try await screen.observe()
        XCTAssertEqual(first["capture_source"] as? String, "fake")
        XCTAssertEqual(first["same_as_previous"] as? Bool, false)
        XCTAssertEqual((first["elements"] as? [String])?.first, "1 发送 @0.500,0.525")
        XCTAssertNotNil(first["image_base64"])
        let second = try await screen.observe()
        XCTAssertEqual(second["frame_id"] as? String, first["frame_id"] as? String, "identical pixels keep their id")
        XCTAssertEqual(second["same_as_previous"] as? Bool, true)
    }

    func testTextOnlyObservationOmitsPixelsAndKeepsFrameAndRecognition() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        let text = try await screen.observe(image: false)
        XCTAssertNil(text["image_base64"])
        XCTAssertNil(text["mime_type"])
        XCTAssertEqual((text["elements"] as? [String])?.first, "1 发送 @0.500,0.525")
        let id = try XCTUnwrap(text["frame_id"] as? String)
        XCTAssertNoThrow(try screen.requireKnown(id))
        let current = try await screen.currentFrame()
        XCTAssertNoThrow(try screen.require(id, current: current, target: CGPoint(x: 0.5, y: 0.525)))
        screen.read = { _ in throw DeviceError(message: "same frame recognized twice") }
        let combined = try await screen.observe()
        XCTAssertEqual(combined["frame_id"] as? String, id)
        XCTAssertEqual(combined["elements"] as? [String], text["elements"] as? [String])
        XCTAssertNotNil(combined["image_base64"])
    }

    func testEmptyTextOnlyObservationDoesNotFallBackToAnUnrequestedImage() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        screen.read = { _ in .init(texts: [], controls: [], ocr: .ok, detector: .unavailable) }
        let text = try await screen.observe(image: false)
        XCTAssertEqual(text["elements"] as? [String], [])
        XCTAssertNil(text["image_base64"])
        XCTAssertEqual((text["element_sources"] as? [String: String])?["ocr"], "ok")
    }

    func testScreenWithoutRecognitionListsNoElements() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        screen.read = { _ in throw DeviceError(message: "visual read must not run OCR") }
        let seen = try await screen.observe(ocr: false)
        XCTAssertEqual((seen["elements"] as? [String])?.count, 0)
        XCTAssertEqual((seen["element_sources"] as? [String: String])?["ocr"], "skipped")
    }

    func testVisualOnlyReadPreservesRecognitionForTheExactFrame() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        let original = try await screen.observe()
        screen.read = { _ in throw DeviceError(message: "same frame recognized twice") }
        let visual = try await screen.observe(ocr: false)
        XCTAssertEqual(visual["frame_id"] as? String, original["frame_id"] as? String)
        XCTAssertEqual((visual["elements"] as? [String])?.count, 0)
        let repeated = try await screen.observe()
        XCTAssertEqual(repeated["elements"] as? [String], original["elements"] as? [String])
    }

    func testRecognitionCacheNeverFollowsTheSamePageHintOrAnotherGeneration() async throws {
        let original = picture()
        let recoded = try XCTUnwrap(UIImage(data: original)?.jpegData(compressionQuality: 0.8))
        XCTAssertNotEqual(recoded, original)
        let source = FakeSource()
        source.pictures = [original, recoded]
        let screen = service(source)
        _ = try await screen.observe()
        screen.read = { _ in .init(texts: [], controls: [], ocr: .ok, detector: .unavailable) }
        let recaptured = try await screen.observe()
        XCTAssertEqual(recaptured["same_as_previous"] as? Bool, true)
        XCTAssertEqual(recaptured["elements"] as? [String], [])
        source.generation += 1
        screen.read = { _ in throw DeviceError(message: "new sharing generation") }
        do { _ = try await screen.observe(); XCTFail("new generation must be recognized") }
        catch { XCTAssertEqual(error.localizedDescription, "new sharing generation") }
    }

    func testPictureAdvancingDuringRecognitionNeverGetsTheOldLabels() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let changed = picture(marker: CGRect(x: 40, y: 100, width: 20, height: 20))
        source.presented = changed
        let seen = try await service(source).observe()
        XCTAssertEqual(seen["image_base64"] as? String, changed.base64EncodedString())
        XCTAssertEqual(seen["elements"] as? [String], [])
        XCTAssertEqual((seen["element_sources"] as? [String: String])?["ocr"], "frame_changed")
    }

    func testScreenRefusesWhenAccessIsDeniedOrSharingStopped() async {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        source.access = { throw DeviceError(message: "paused") }
        do { _ = try await screen.observe(); XCTFail("expected a refusal") } catch {
            XCTAssertEqual(error.localizedDescription, "paused")
        }
        source.access = {}
        source.sharing = false
        do { _ = try await screen.observe(); XCTFail("expected a refusal") } catch {
            XCTAssertEqual(error.localizedDescription, "not sharing")
        }
    }

    func testInputPreconditionComparesTheTargetWithTheObservation() async throws {
        let source = FakeSource()
        source.pictures = [picture(), picture(marker: CGRect(x: 40, y: 100, width: 20, height: 20))]
        let screen = service(source)
        let seen = try await screen.observe()
        let id = try XCTUnwrap(seen["frame_id"] as? String)
        let changed = try await screen.currentFrame()
        XCTAssertThrowsError(try screen.require(id, current: changed, target: CGPoint(x: 0.5, y: 0.55))) {
            XCTAssertEqual($0 as? ScreenObservation.Failure, .frameChanged)
        }
        XCTAssertFalse(try screen.require(nil, current: changed, target: CGPoint(x: 0.5, y: 0.55)),
                       "without a frame id the caller takes responsibility")
        XCTAssertNoThrow(try screen.requireKnown(id), "keys and system gestures ask only that the observation stands")
        source.generation = 2
        XCTAssertThrowsError(try screen.requireKnown(id), "another sharing session")
        source.generation = 1
        screen.forget()
        XCTAssertThrowsError(try screen.requireKnown(id))
        XCTAssertThrowsError(try screen.require(id, current: changed, target: nil))
    }

    func testMaskedTargetIsReportedWithoutBlockingRepeatedTaps() async throws {
        let source = FakeSource()
        source.pictures = [picture()]
        let screen = service(source)
        screen.pointerLocation = { CGPoint(x: 0.5, y: 0.5) }
        let seen = try await screen.observe(ocr: false)
        let id = try XCTUnwrap(seen["frame_id"] as? String)
        XCTAssertTrue(screen.targetMasked(CGPoint(x: 0.5, y: 0.5), on: id))
        XCTAssertFalse(screen.targetMasked(CGPoint(x: 0.8, y: 0.5), on: id))
        let current = try await screen.currentFrame()
        XCTAssertNoThrow(try screen.require(id, current: current, target: CGPoint(x: 0.5, y: 0.5)))
    }

    func testSelectingASourceTellsBothSides() {
        let first = FakeSource(), second = FakeSource()
        let screen = ScreenService(source: first)
        screen.select(second)
        XCTAssertTrue(screen.source === second)
        XCTAssertEqual(first.selections, [false])
        XCTAssertEqual(second.selections, [true])
    }

    func testHIDDeliversEachActionThroughTheBackend() async throws {
        let backend = FakeBackend()
        let hid = HIDService(backend: backend)
        hid.foreground = { false }
        try await hid.perform("tap", ["x": 0.25, "y": 0.5])
        try await hid.perform("tap", ["x": 0.25, "y": 0.5, "count": 2])
        try await hid.perform("long_press", ["x": 0.25, "y": 0.5])
        try await hid.perform("swipe", ["x": 0.5, "y": 0.7, "x2": 0.5, "y2": 0.3, "duration_ms": 200])
        try await hid.perform("type", ["text": "hello", "method": "keys"])
        try await hid.perform("key", ["combo": "cmd+a"])
        try await hid.perform("button", ["name": "home"])
        try await hid.perform("button", ["name": "search"])
        try await hid.perform("button", ["name": "control_center"])
        XCTAssertEqual(backend.sent, ["tap 0.25 0.5", "tap 0.25 0.5 x2", "long 0.25 0.5 0.8", "swipe 0.5 0.7 0.5 0.3 0.2 hold 0.0",
                                      "type hello", "key cmd+a", "button home", "button search", "button control_center"])
        XCTAssertEqual(backend.revision, 9)
    }

    func testInputBudgetsDoNotRejectValidRequests() async throws {
        let backend = FakeBackend()
        let hid = HIDService(backend: backend)
        try await hid.perform("tap", ["x": 0.5, "y": 0.5, "count": 11])
        try await hid.perform("long_press", ["x": 0.5, "y": 0.5, "duration_ms": 6000])
        try await hid.perform("type", ["text": String(repeating: "a", count: 601), "method": "keys"])
        XCTAssertEqual(backend.sent.count, 3)
        XCTAssertEqual(try HIDService.typedText(String(repeating: "中文", count: 6000)).count, 12000)
    }

    func testHIDRejectsBadArgumentsBeforeAnythingIsSent() async {
        let backend = FakeBackend()
        let hid = HIDService(backend: backend)
        hid.foreground = { false }
        let bad: [(String, [String: Any])] = [
            ("tap", ["x": 1.2, "y": 0.5]), ("tap", ["x": true, "y": 0.5]), ("tap", ["x": 0.5]),
            ("tap", ["x": 0.5, "y": 0.5, "count": true]), ("tap", ["x": 0.5, "y": 0.5, "count": 1.5]),
            ("tap", ["x": 0.5, "y": 0.5, "count": 0]),
            ("swipe", ["x": 0.5, "y": 0.7, "x2": 0.5, "y2": 0.3, "flick": 1]),
            ("swipe", ["x": 0.5, "y": 0.7, "x2": 0.5, "y2": 0.3, "flick": "yes"]),
            ("swipe", ["x": 0.5, "y": 0.5, "x2": 0.5]), ("long_press", ["x": 0.5, "y": 0.5, "duration_ms": 50]),
            ("type", ["text": "中文", "method": "keys"]), ("type", ["text": "a\u{0000}b"]), ("key", ["combo": "cmd v"]),
            ("button", ["name": "power"]), ("open_app", ["name": "WeChat"]),
        ]
        for (action, args) in bad {
            do { try await hid.perform(action, args); XCTFail("\(action) \(args) was accepted") } catch {}
        }
        XCTAssertEqual(backend.sent, [])
    }

    func testHeldDragAndPunctuationShortcutReachTheBackend() async throws {
        let backend = FakeBackend()
        let service = HIDService(backend: backend)
        try await service.perform("swipe", ["x": 0.5, "y": 0.7, "x2": 0.5, "y2": 0.3, "hold_ms": 700])
        try await service.perform("key", ["combo": "cmd+["])
        XCTAssertEqual(backend.sent, ["swipe 0.5 0.7 0.5 0.3 - hold 0.7", "key cmd+["], "no duration: the device's own pace")
        try await service.perform("swipe", ["x": 0.5, "y": 0.7, "x2": 0.5, "y2": 0.3, "flick": true, "duration_ms": 150])
        XCTAssertEqual(backend.sent.last, "flick 0.5 0.7 0.5 0.3 0.15 hold 0.0")
        XCTAssertEqual(try HIDService.typedText("段一\n段二\t末尾"), "段一\n段二\t末尾")
        XCTAssertEqual(try HIDService.typedText("👨‍👩‍👧‍👦\u{200F}"), "👨‍👩‍👧‍👦\u{200F}", "Unicode formatting belongs to the pasted text")
        XCTAssertFalse(HIDService.typeable("a\nb"))
    }

    func testPasteNeedsTextStagedByGAgent() async throws {
        let backend = FakeBackend()
        let hid = HIDService(backend: backend)
        hid.foreground = { false }
        do { try await hid.perform("type", ["text": "你好"]); XCTFail("nothing was staged") } catch {
            XCTAssertEqual(error as? ScreenObservation.Failure, .textNotStaged)
        }
        XCTAssertThrowsError(try hid.stage("你好")) { XCTAssertEqual($0 as? ScreenObservation.Failure, .textNotStaged) }
        XCTAssertThrowsError(try hid.requireStaged())
        XCTAssertEqual(backend.sent, [], "type must never paste someone else's clipboard")
        XCTAssertNoThrow(try hid.requirePaste(), "outside a type, the write gate has no text to hold a paste to")
        try await hid.perform("key", ["combo": "cmd+v"])
        XCTAssertEqual(backend.sent, ["key cmd+v"], "a bare shortcut is the system's own Paste, the model's to choose")
    }

    func testStagingIsRefusedWithoutConsent() {
        let hid = HIDService(backend: FakeBackend())
        hid.foreground = { true }
        hid.access = { throw DeviceError(message: "no consent") }
        XCTAssertThrowsError(try hid.stage("text")) { XCTAssertEqual($0.localizedDescription, "no consent") }
    }

    func testAppTransitionsGetMoreSettleTimeThanInPageInput() {
        XCTAssertEqual(HIDService.settleTime("button", ["name": "home"]), 0.7)
        XCTAssertEqual(HIDService.settleTime("button", ["name": "search"]), 0.7)
        XCTAssertEqual(HIDService.settleTime("button", ["name": "back"]), 0.5)
        XCTAssertEqual(HIDService.settleTime("tap", ["x": 0.5, "y": 0.5]), 0.2)
        XCTAssertEqual(HIDService.target(["x": 0.25, "y": 0.5]), CGPoint(x: 0.25, y: 0.5))
        XCTAssertNil(HIDService.target(["combo": "cmd+a"]))
    }
}
