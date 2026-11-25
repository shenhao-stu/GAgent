import XCTest
@testable import BoardKitHarness

/// A board that answers every command like the firmware does.
@MainActor final class FakeBoard: BoardTransport {
    var isConnected = true
    var lines: [String] = []
    var silent = false
    weak var channel: CommandChannel?

    func write(_ line: String) throws {
        lines.append(line)
        guard !silent else { return }
        let parts = line.split(separator: " ", maxSplits: 1).map(String.init)
        let reply = parts[1] == "bad" ? "\(parts[0]) err unknown command" : "\(parts[0]) ok"
        Task { @MainActor in self.channel?.handleReply(reply) }
    }

}

/// Port of server/tests/test_device.py, with a fake BLE transport instead of a TCP socket.
@MainActor final class DeviceTests: XCTestCase {
    func testProbeFitIsNotVerifiedUntilACheckTapArrives() {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let device = FakeDevice(), pointer = Pointer(device: FakeDevice(), calibrationFile: file)
        let line = ProbeFit.Line(a: 0.001, b: 0.02, rms: 0.001)
        pointer.applyProbe(x: line, y: line, samples: [(200, 200, 0.22, 0.22), (500, 500, 0.52, 0.52)])
        XCTAssertTrue(pointer.calibrated)
        XCTAssertNil(pointer.quality, "a fitted line cannot prove that the final verification tap arrived")
        XCTAssertNil(Pointer(device: device, calibrationFile: file).quality, "interruption or restart must not validate an unchecked fit")
        pointer.setQuality(0.002)
        XCTAssertEqual(Pointer(device: device, calibrationFile: file).quality, 0.002)
    }

    func testKeyboardNeedsNoPointerCalibrationAndPreservesChunkBoundaries() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        let pointer = Pointer(device: device, calibrationFile: file)
        XCTAssertFalse(pointer.calibrated)
        let text = String(repeating: " ab  cd ", count: 80)
        try await pointer.type(text)
        XCTAssertEqual(device.sent.map { String($0.dropFirst(5)) }.joined(), text)
        XCTAssertTrue(device.sent.allSatisfy { $0.hasPrefix("type ") && $0.utf8.count <= 205 })
        try await pointer.key("cmd+a")
        XCTAssertEqual(device.sent.last, "key cmd+a")
        XCTAssertFalse(device.sent.contains("home"))
    }

    func testTypingStopsAtFirstFailedChunkWithoutRetry() async throws {
        final class FailingKeyboard: HIDDevice {
            var links = 0
            var connected = true
            var sent: [String] = []
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if sent.count == 2 { throw DeviceError(message: "link lost") }
                return ""
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        let device = FailingKeyboard()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        let pointer = Pointer(device: device, calibrationFile: file)
        do {
            try await pointer.type(String(repeating: "a", count: 601))
            XCTFail("expected partial delivery failure")
        } catch { XCTAssertEqual(error.localizedDescription, "link lost") }
        XCTAssertEqual(device.sent.count, 2)
    }

    func testKnownPositionMovesDirectlyUntilExplicitlyInvalidated() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        try await pointer.point(0.4, 0.4)
        device.sent = []
        try await pointer.point(0.6, 0.6)
        XCTAssertFalse(device.sent.contains("home"))
        device.sent = []
        try await pointer.point(0.5, 0.5)
        XCTAssertFalse(device.sent.contains("home"))
        pointer.invalidatePosition()
        device.sent = []
        try await pointer.point(0.6, 0.6)
        XCTAssertEqual(device.sent.first, "home", "Only lost position needs a new anchor")
    }

    func testRepeatedTapClicksInPlaceWithNothingInBetween() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        try await pointer.tap(0.5, 0.5, count: 3)
        XCTAssertEqual(Array(device.sent.suffix(3)), ["click", "click", "click"])
        XCTAssertTrue(device.sent.dropLast(3).last?.hasPrefix("move ") == true)
    }

    /// The landings of a calibration start beside the corner (the screen's corner is round), so a pointer aimed at
    /// a fraction lands elsewhere. Frame comparisons mask the pointer where it is, not where it was aimed.
    func testLocationIsWhereThePointerLandedNotWhereItWasAimed() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        // landed = units / 1000 + 0.04 across, units / 2000 + 0.02 down
        pointer.applyProbe(x: ProbeFit.Line(a: 0.001, b: 0.04, rms: 0), y: ProbeFit.Line(a: 0.0005, b: 0.02, rms: 0),
                           samples: [(ux: 200, uy: 400, fx: 0.24, fy: 0.22), (ux: 800, uy: 1600, fx: 0.84, fy: 0.82)])
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.suffix(2), ["move 460 0", "move 0 960"], "aimed short of the target by the offset")
        let location = try XCTUnwrap(pointer.location)
        XCTAssertEqual(Double(location.x), 0.5, accuracy: 0.002)
        XCTAssertEqual(Double(location.y), 0.5, accuracy: 0.002)
        try await pointer.reset()  // in the corner the pointer rests at the offset, not at 0, 0
        let corner = try XCTUnwrap(pointer.location)
        XCTAssertEqual(Double(corner.x), 0.04, accuracy: 0.002)
        XCTAssertEqual(Double(corner.y), 0.02, accuracy: 0.002)
    }

    func testTimeoutGrowsWithMoveDistanceAndTextLength() {
        XCTAssertEqual(CommandChannel.timeout("click"), 5)
        XCTAssertGreaterThan(CommandChannel.timeout("move 1000 -20"), CommandChannel.timeout("move 10 10"))
        XCTAssertGreaterThanOrEqual(CommandChannel.timeout("move 10 10"), 5)
        XCTAssertGreaterThan(CommandChannel.timeout("type " + String(repeating: "x", count: 40)),
                             CommandChannel.timeout("type hi"))
    }

    func testSendWithoutBoardFailsFast() async {
        do {
            try await CommandChannel().send("ping")
            XCTFail("expected an error")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("not connected"))
        }
    }

    func testRoundTripWithAFakeBoard() async throws {
        let board = FakeBoard()
        let channel = CommandChannel(transport: board)
        board.channel = channel
        channel.linkUp()
        let ok = await channel.waitConnected(2)
        XCTAssertTrue(ok)
        try await channel.send("ping")
        do {
            try await channel.send("bad")
            XCTFail("expected an error")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("unknown command"))
        }
        XCTAssertEqual(channel.links, 1)
        let ids = board.lines.compactMap { Int($0.split(separator: " ")[0]) }  // request ids: random start, then +1
        XCTAssertEqual(board.lines.map { $0.split(separator: " ")[1] }, ["ping", "bad"])
        XCTAssertEqual(ids.count == 2 ? ids[1] - ids[0] : 0, 1)
    }

    func testPasteRequiresTheSameUnexpiredClipboardItem() {
        let expires = Date(timeIntervalSince1970: 600)
        let item = StagedPaste(text: "counter", changeCount: 7, expires: expires)
        XCTAssertTrue(item.valid(changeCount: 7, now: expires.addingTimeInterval(-1)))
        XCTAssertFalse(item.valid(changeCount: 8, now: expires.addingTimeInterval(-1)))
        XCTAssertFalse(item.valid(changeCount: 7, now: expires))
    }

    func testRevokedSharingStopsAnInFlightGestureBeforeItsNextWrite() async throws {
        let board = FakeBoard()
        let channel = CommandChannel(transport: board)
        board.channel = channel
        channel.linkUp()
        var sharing = true
        channel.beforeWrite = { command in
            if !sharing, command != "release", command != "ping" {
                throw DeviceError(message: "sharing stopped")
            }
            return {}
        }
        try await channel.send("move 20 20")
        let boundary = try XCTUnwrap(channel.observationAfterUptime)
        sharing = false
        do {
            try await channel.send("click")
            XCTFail("stopped sharing sent a click")
        } catch { XCTAssertEqual(error.localizedDescription, "sharing stopped") }
        XCTAssertEqual(channel.observationAfterUptime, boundary)
        XCTAssertEqual(channel.actionRevision, 1)
        try await channel.send("release")
        try await channel.send("ping")
        XCTAssertEqual(board.lines.map { $0.split(separator: " ")[1] }, ["move", "release", "ping"])
    }

    func testQueuedInputChecksSharingAfterAcquiringTheWriteSlot() async throws {
        let board = FakeBoard()
        let channel = CommandChannel(transport: board)
        board.channel = channel
        channel.linkUp()
        var sharing = true
        var pending: CheckedContinuation<Void, Never>?
        channel.beforeWrite = { command in
            if command == "ping" { await withCheckedContinuation { pending = $0 } }
            return {
                if command != "ping", !sharing { throw DeviceError(message: "sharing stopped") }
            }
        }
        let ping = Task { try await channel.send("ping") }
        while pending == nil { await Task.yield() }
        let click = Task { try await channel.send("click") }
        await Task.yield()
        sharing = false
        pending?.resume()
        _ = try await ping.value
        do {
            _ = try await click.value
            XCTFail("a queued click used earlier permission")
        } catch { XCTAssertEqual(error.localizedDescription, "sharing stopped") }
        XCTAssertEqual(board.lines.count, 1)
        XCTAssertNil(channel.observationAfterUptime)
    }

    func testScreenRefreshIsBoundedAndCannotAuthorizeAClick() async throws {
        let board = FakeBoard(), channel = CommandChannel()
        channel.transport = board; board.channel = channel; channel.linkUp()
        channel.beforeWrite = { _ in throw DeviceError(message: "no fresh pixels") }
        var sharing = true
        let authorize: @MainActor () async throws -> CommandChannel.WritePermit = {
            return { if !sharing { throw DeviceError(message: "sharing stopped") } }
        }
        try await channel.refreshPointer(by: 12, authorize: authorize)
        try await channel.refreshPointer(by: -12, authorize: authorize)
        XCTAssertEqual(channel.actionRevision, 2)
        XCTAssertNil(channel.observationAfterUptime, "Pointer-only changes must not advance the page-state boundary")
        do { try await channel.send("click"); XCTFail("refresh granted a click") }
        catch { XCTAssertEqual(error.localizedDescription, "no fresh pixels") }
        do { try await channel.refreshPointer(by: 1200, authorize: authorize); XCTFail("unbounded refresh") }
        catch { XCTAssertEqual(error.localizedDescription, "Invalid screen refresh movement") }
        sharing = false
        do { try await channel.refreshPointer(by: 12, authorize: authorize); XCTFail("stopped sharing moved") }
        catch { XCTAssertEqual(error.localizedDescription, "sharing stopped") }
        XCTAssertEqual(board.lines.count, 2)
    }

    func testQueuedScreenRefreshRechecksRevocationAtPhysicalWrite() async throws {
        let board = FakeBoard(), channel = CommandChannel()
        channel.transport = board; board.channel = channel; channel.linkUp()
        var sharing = true
        var pending: CheckedContinuation<Void, Never>?
        let probe = Task {
            try await channel.refreshPointer(by: 12) {
                await withCheckedContinuation { pending = $0 }
                return { if !sharing { throw DeviceError(message: "sharing stopped") } }
            }
        }
        while pending == nil { await Task.yield() }
        sharing = false
        pending?.resume()
        do { _ = try await probe.value; XCTFail("refresh used revoked permission") }
        catch { XCTAssertEqual(error.localizedDescription, "sharing stopped") }
        XCTAssertTrue(board.lines.isEmpty)
    }

    func testCommandsGoOneAtATime() async throws {
        let board = FakeBoard()
        let channel = CommandChannel(transport: board)
        board.channel = channel
        async let a: String = channel.send("move 1 0")
        async let b: String = channel.send("move -1 0")
        _ = try await (a, b)
        XCTAssertEqual(board.lines.count, 2)
    }

    /// A tap's moves cost one round trip, not one each: the board queues them and runs them back to back.
    func testMovesAreWrittenTogetherAndAnsweredTogether() async throws {
        let board = FakeBoard()
        board.silent = true
        let channel = CommandChannel(transport: board)
        board.channel = channel
        let moves = ["move -3 0", "move 50 0", "move 0 60"]
        let batch = Task { try await channel.sendAll(moves) }
        for _ in 0..<1000 where board.lines.count < 3 { await Task.yield() }
        XCTAssertEqual(board.lines.map { String($0.split(separator: " ", maxSplits: 1)[1]) }, moves,
                       "all written, in order, before any answer")
        for line in board.lines.reversed() { channel.handleReply("\(line.split(separator: " ")[0]) ok") }
        try await batch.value
        XCTAssertEqual(channel.actionRevision, 3)
        XCTAssertNotNil(channel.observationAfterUptime)
    }

    func testABatchFailsWhenAnyMoveFailsAndWhenRefused() async throws {
        let board = FakeBoard()
        let channel = CommandChannel(transport: board)
        board.channel = channel
        do { try await channel.sendAll(["move 1 0", "bad", "move 0 1"]); XCTFail("expected an error") }
        catch { XCTAssertTrue(error.localizedDescription.contains("unknown command")) }
        XCTAssertEqual(board.lines.count, 3, "the board was asked for all of them")
        board.lines = []
        channel.beforeWrite = { _ in throw DeviceError(message: "paused") }
        do { try await channel.sendAll(["move 1 0", "move 0 1"]); XCTFail("expected a refusal") }
        catch { XCTAssertEqual(error.localizedDescription, "paused") }
        XCTAssertTrue(board.lines.isEmpty, "a refused batch writes nothing")
        channel.beforeWrite = nil
        board.silent = true
        Task { @MainActor in try? await Task.sleep(nanoseconds: 50_000_000); channel.linkDown() }
        do { try await channel.sendAll(["move 1 0", "move 0 1"]); XCTFail("expected an error") }
        catch { XCTAssertTrue(error.localizedDescription.contains("disconnected")) }
    }

    func testLinkDownFailsCommandsInFlight() async {
        let board = FakeBoard()
        board.silent = true
        let channel = CommandChannel(transport: board)
        board.channel = channel
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 50_000_000)
            channel.linkDown()
        }
        do {
            try await channel.send("click")
            XCTFail("expected an error")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("disconnected"))
        }
    }

    func testReplyParsing() {
        XCTAssertEqual(BoardReply.parse("12 ok"), BoardReply(id: 12, ok: true, text: ""))
        XCTAssertEqual(BoardReply.parse("3 ok 812\n"), BoardReply(id: 3, ok: true, text: "812"))
        XCTAssertEqual(BoardReply.parse("4 err unknown command"), BoardReply(id: 4, ok: false, text: "unknown command"))
        XCTAssertNil(BoardReply.parse("ok"))
    }

    func testStatusDecoding() throws {
        let json = #"{"up":123456,"rst":"power-on","heap":81234,"psram":6200000,"usb":"ok","net":"ap","ip":"192.168.4.1","sta":1,"ap":"streaming","w":480,"h":1040,"kbps":180,"fps":4.8,"idr":2000,"gop":42000,"ble":{"mtu":247,"phy":2,"kbps":350,"drop":0}}"#
        let s = try XCTUnwrap(BoardStatus.decode(Data(json.utf8)))
        XCTAssertEqual(s.ap, "streaming")
        XCTAssertEqual(s.ble?.mtu, 247)
        XCTAssertEqual(s.fps, 4.8)
    }

    func testLostKeyframeRequiresRecoveryButHealthyTrimmedStreamDoesNot() throws {
        let stalled = try XCTUnwrap(BoardStatus.decode(Data(#"{"ap":"streaming","anc":0,"ovf":1,"trim":5,"lag":-1}"#.utf8)))
        XCTAssertTrue(stalled.needsMirrorRestart(frameUnavailable: true))
        XCTAssertTrue(stalled.needsMirrorRestart(frameUnavailable: false))
        let live = stalled.merged(with: BoardStatus(lag: 0))
        XCTAssertFalse(live.needsMirrorRestart(frameUnavailable: false))
        XCTAssertTrue(live.needsMirrorRestart(frameUnavailable: true))
        XCTAssertEqual(live.ovf, 1)
        XCTAssertEqual(live.trim, 5)
        XCTAssertFalse(live.merged(with: BoardStatus(ap: "idle")).needsMirrorRestart(frameUnavailable: true))
        XCTAssertFalse(live.merged(with: BoardStatus(anc: 1)).needsMirrorRestart(frameUnavailable: true))
        XCTAssertFalse(BoardStatus(ap: "streaming", lag: -1).needsMirrorRestart(frameUnavailable: true))
    }

    func testCorruptInputRequiresRecoveryEvenWithAnOldFrameAndNoBacklog() throws {
        let status = try XCTUnwrap(BoardStatus.decode(Data(#"{"ap":"failed","anc":1,"lag":0,"fps":0}"#.utf8)))
        XCTAssertTrue(status.needsMirrorRestart(frameUnavailable: false))
        XCTAssertTrue(status.needsMirrorRestart(frameUnavailable: true))
        XCTAssertFalse(status.merged(with: BoardStatus(ap: "idle")).needsMirrorRestart(frameUnavailable: false))
    }

    func testHomingStrategyStartsFromHomeAndMovesOneAxisAtATime() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.relativePositioning = false
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)  // span 400 x 800
        try await pointer.point(0.5, 0.5)
        try await pointer.point(0.5, 0.75)
        // A new link lets go first. iOS moves the pointer further per unit the larger a report is, and the board
        // sends both axes in one report until the shorter is done: "move 200 400" would land somewhere else.
        XCTAssertEqual(device.sent, ["release", "home", "move 200 0", "move 0 400", "home", "move 200 0", "move 0 600"])
        device.sent = []
        try await pointer.point(0, 0.5)
        XCTAssertEqual(device.sent, ["home", "move 0 400"], "An axis that does not move sends nothing")
    }

    func testADoubleTapClicksTwiceWithNothingMovingInBetween() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        try await pointer.tap(0.5, 0.5, count: 2)
        // A system alert takes only the click that follows another with no pointer movement in between.
        XCTAssertEqual(device.sent, ["release", "home", "move 200 0", "move 0 400", "click", "click"])
        device.sent = []
        try await pointer.tap(0.5, 0.5)
        XCTAssertEqual(device.sent, ["click"], "A known interior target stays in place")
    }

    func testRelativeMovePreservesReportTailsAndRecoversAfterInvalidation() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        XCTAssertTrue(pointer.relativePositioning)
        try await pointer.point(0.5075, 0.50125) // mouse units 203, 401
        device.sent = []
        try await pointer.point(0.6425, 0.57625) // 257, 461
        XCTAssertEqual(device.sent, ["move -3 0", "move 50 0", "move 7 0", "move 0 -1", "move 0 60", "move 0 1"])
        device.sent = []
        try await pointer.point(0.6425, 0.57625)
        XCTAssertTrue(device.sent.isEmpty, "same target stays in place")
        pointer.invalidatePosition()
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.first, "home", "unknown position must reanchor")
        device.sent = []
        try await pointer.point(0.01, 0.5)
        XCTAssertEqual(device.sent.first, "home", "edge clipping cannot be tracked")
        device.sent = []
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.first, "home", "leaving a clipped edge must reanchor")
        device.sent = []
        device.links += 1
        try await pointer.point(0.6, 0.5)
        XCTAssertEqual(Array(device.sent.prefix(2)), ["release", "home"])
    }

    func testHeldDragDoesNotMoveBeforeHoldAndReleasesOnCancellation() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        let drag = Task { try await pointer.swipe(0.5, 0.5, 0.7, 0.7, startHold: 5) }
        while !device.sent.contains("press") { await Task.yield() }
        XCTAssertEqual(device.sent.last, "press")
        drag.cancel()
        do { try await drag.value; XCTFail("cancelled hold completed") } catch is CancellationError {}
        XCTAssertEqual(Array(device.sent.suffix(2)), ["press", "release"], "cancelled hold releases without dragging")
    }

    /// span 400 x 800, no rests: the commands alone.
    private func calibrated() -> (FakeDevice, Pointer) {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        addTeardownBlock { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        return (device, pointer)
    }

    /// Every command is a link round trip during which the finger stands still. Cut into 8 moves, the swipes of
    /// a model run took 1.35-1.85 s instead of the 0.4 s asked for and advanced in jerks (iPhone 15 Pro Max,
    /// 2026-11-13); pulled down from the top edge, such a stroke pages through Control Center.
    func testAStraightSwipeIsOneContinuousMove() async throws {
        let (device, pointer) = calibrated()
        try await pointer.swipe(0.5, 0.75, 0.5, 0.25)
        XCTAssertEqual(Array(device.sent.suffix(3)), ["press", "move 0 -400", "release"])
        device.sent = []
        try await pointer.swipe(0.5, 0.75, 0.52, 0.25)  // a model's two points are rarely exactly in line
        XCTAssertEqual(Array(device.sent.suffix(4)), ["press", "move 0 -400", "move 8 0", "release"],
                       "the long leg first: a list takes its direction from how the finger sets off")
        device.sent = []
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.first, "home", "a stroke does not keep the tracked position")
    }

    func testASwipeIsCutOnlyToGoSlowerOrToFollowADiagonal() async throws {
        let (device, pointer) = calibrated()
        // 400 units take 0.32 s at the board's pace. Asked to take 0.55 s, the finger stands still twice.
        try await pointer.swipe(0.5, 0.75, 0.5, 0.25, hold: false, duration: 0.55)
        XCTAssertEqual(Array(device.sent.suffix(5)), ["press", "move 0 -130", "move 0 -140", "move 0 -130", "release"],
                       "cut on whole reports: iOS carries a short one a different distance")
        device.sent = []
        try await pointer.swipe(0.5, 0.75, 0.5, 0.25, hold: false, duration: 0.1)
        XCTAssertEqual(Array(device.sent.suffix(3)), ["press", "move 0 -400", "release"], "no faster than the board moves")
        device.sent = []
        try await pointer.swipe(0.5, 0.5, 0.25, 0.75, hold: false)
        let moves = device.sent.drop { $0 != "press" }.dropFirst().dropLast()
        XCTAssertEqual(Array(moves), ["move 0 70", "move -30 0", "move 0 60", "move -40 0", "move 0 70", "move -30 0"],
                       "one axis at a time, in legs short enough to stay near the line")
        XCTAssertEqual(device.sent.last, "release")
    }

    /// Lifting while the finger still moves is a gesture of its own: content keeps gliding, and the system's
    /// edges answer to it. Only one board command can do it: a round trip before the lift is a pause.
    func testAFlickIsOneBoardCommandWhoseSpeedComesFromItsDuration() async throws {
        let (device, pointer) = calibrated()
        try await pointer.flick(0.5, 0.75, 0.5, 0.25)
        XCTAssertEqual(device.sent.last, "flick 0 -400")
        XCTAssertFalse(device.sent.contains("press") || device.sent.dropFirst().contains("release"))
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 0.1)  // 12.5 reports of 8 ms
        XCTAssertEqual(device.sent.last, "flick 0 -400 32")
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 0.02)
        XCTAssertEqual(device.sent.last, "flick 0 -400 60", "the firmware's fastest")
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 5)
        XCTAssertEqual(device.sent.last, "flick 0 -400 1")
        device.sent = []
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, startHold: 0.01)
        XCTAssertEqual(Array(device.sent.suffix(2)), ["press", "flick 0 -400"], "held first, then flung")
    }

    /// iOS accelerates the pointer by the size of each report: a fast flick carried more than twice as far as the
    /// calibration says (`flick-gain`, 2026-11-13). An aimed flick picks the report size that gives the speed
    /// asked for once accelerated, and shortens its move by the same gain, so it ends where it was aimed.
    func testAnAimedFlickTakesIntoAccountHowFarFastReportsCarry() async throws {
        let (device, pointer) = calibrated()
        XCTAssertEqual(Pointer.gain(10), 1)
        XCTAssertEqual(Pointer.gain(26), 1.2, accuracy: 1e-9)
        XCTAssertEqual(Pointer.gain(80), Pointer.gain(60))
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 0.1, aimed: true)
        XCTAssertEqual(device.sent.last, "flick 0 -333 26", "26 units a report carry 1.2 times as far")
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 0.02, aimed: true)
        XCTAssertEqual(device.sent.last, "flick 0 -183 60", "faster than the board can go: its fastest, still aimed")
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 5, aimed: true)
        XCTAssertEqual(device.sent.last, "flick 0 -400 1")
        try await pointer.flick(0.5, 0.75, 0.5, 0.25, aimed: true)
        XCTAssertEqual(device.sent.last, "flick 0 -400", "the board's own pace is the calibrated one")
    }

    func testALongPressLiftsWhereItPressedAndKeepsThePosition() async throws {
        let (device, pointer) = calibrated()
        try await pointer.longPress(0.5, 0.5, seconds: 0.01)
        XCTAssertEqual(Array(device.sent.suffix(2)), ["press", "release"])
        device.sent = []
        try await pointer.point(0.6, 0.6)
        XCTAssertFalse(device.sent.contains("home"), "nothing moved")
    }

    /// Control Center is pulled from the top edge, right of the Dynamic Island: on the edge itself (the corner
    /// leaves the pointer 16 pt below it), a short way, lifting on the move. A long or slow pull pages on.
    func testControlCenterIsAShortFlickFromTheTopEdgeRightOfTheIsland() async throws {
        let (device, pointer) = calibrated()
        try await pointer.openControlCenter()
        XCTAssertEqual(device.sent, ["release", "home", "move 320 0", "move 0 -30", "flick 0 160"])
        device.sent = []
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.first, "home", "system gestures must discard the tracked position")
    }

    func testControlCenterOnFirmwareWithoutFlickStillPullsFromTheTopEdge() async throws {
        final class Old: HIDDevice {
            var links = 1, connected = true
            var sent: [String] = []
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick") { throw DeviceError(message: "err unknown command") }
                return ""
            }
        }
        let device = Old()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        try await pointer.openControlCenter()
        XCTAssertEqual(Array(device.sent.suffix(5)), ["move 0 -30", "flick 0 160", "press", "move 0 160", "release"])
    }

    func testControlCenterReleasesOnFailureOrCancellationWithoutRepeatingTheStroke() async throws {
        final class Interrupted: HIDDevice {
            var links = 1, connected = true
            var sent: [String] = []
            let waits: Bool
            init(waits: Bool) { self.waits = waits }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
            func send(_ command: String) async throws -> String {
                try Task.checkCancellation()
                sent.append(command)
                if command.hasPrefix("flick") {
                    if waits { try await Task.sleep(for: .seconds(30)) }
                    throw DeviceError(message: "link lost during flick")
                }
                return ""
            }
        }
        for waits in [false, true] {
            let device = Interrupted(waits: waits)
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
            defer { try? FileManager.default.removeItem(at: file) }
            let pointer = Pointer(device: device, calibrationFile: file)
            pointer.boardSettles = { true }
            pointer.finishCalibration(x: 0.5, y: 0.25)
            let gesture = Task { try await pointer.openControlCenter() }
            if waits {
                for _ in 0..<100 where !device.sent.contains(where: { $0.hasPrefix("flick") }) { await Task.yield() }
                XCTAssertTrue(device.sent.contains(where: { $0.hasPrefix("flick") }))
                gesture.cancel()
            }
            do { try await gesture.value; XCTFail("The interruption must reach the caller") }
            catch { XCTAssertEqual(error is CancellationError, waits) }
            XCTAssertEqual(device.sent.filter { $0.hasPrefix("flick") }.count, 1)
            XCTAssertEqual(device.sent.last, "release", "Even a cancelled caller must finish letting go")
        }
    }

    func testABoardThatDoesNotSettleGetsRestsAfterHomeAndBeforeThePress() async throws {
        final class TimedDevice: HIDDevice {
            var links = 0
            var connected = true
            var sent: [(command: String, at: Double)] = []
            func send(_ command: String) async throws -> String {
                sent.append((command, ProcessInfo.processInfo.systemUptime))
                return ""
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        func gaps(settles: Bool) async throws -> (afterHome: Double, beforeClick: Double) {
            let device = TimedDevice()
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
            defer { try? FileManager.default.removeItem(at: file) }
            let pointer = Pointer(device: device, calibrationFile: file)
            pointer.boardSettles = { settles }
            pointer.finishCalibration(x: 0.5, y: 0.25)
            try await pointer.tap(0.5, 0.5)
            XCTAssertEqual(device.sent.map(\.command), ["home", "move 200 0", "move 0 400", "click"])
            return (device.sent[1].at - device.sent[0].at, device.sent[3].at - device.sent[2].at)
        }
        // iOS clamps `home`'s last reports together with a move that arrives with them, and puts a press that
        // arrives with moves where the pointer was before them. New firmware waits by itself (`settle`).
        let rested = try await gaps(settles: false)
        XCTAssertGreaterThanOrEqual(rested.afterHome, Pointer.homeRest)
        XCTAssertGreaterThanOrEqual(rested.beforeClick, Pointer.pressRest)
        let direct = try await gaps(settles: true)
        XCTAssertLessThan(direct.afterHome, Pointer.homeRest / 2)
        XCTAssertLessThan(direct.beforeClick, Pointer.pressRest / 2)
    }

    func testCalibrationMadeWithTwoAxisMovesIsNotUsed() throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        // Written before moves went one axis at a time: its lines fit the two-axis pattern (up to 27 pt off now).
        try Data(#"{"w":510,"h":1174,"quality":0.0016,"aspect":0.46}"#.utf8).write(to: file)
        XCTAssertFalse(Pointer(device: FakeDevice(), calibrationFile: file).calibrated)
        try Data(#"{"w":543,"h":1180,"quality":0.0016,"aspect":0.46,"axes":true}"#.utf8).write(to: file)
        XCTAssertEqual(Pointer(device: FakeDevice(), calibrationFile: file).span, Pointer.Span(w: 543, h: 1180))
    }

    func testSearchUsesTheMarginOutsideHomeWidgets() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 0.5, y: 0.25)
        try await pointer.openSearch()
        XCTAssertEqual(device.sent, ["release", "home", "move 16 0", "move 0 336", "flick 0 192"])
        device.sent = []
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.first, "home", "system gestures must discard the tracked position")
    }

    func testHomeIsOneShortBottomEdgeStrokeAndInvalidatesPosition() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        try await pointer.goHome()
        XCTAssertFalse(device.sent.contains("homescreen"), "An ACK does not establish that iOS navigated home")
        XCTAssertFalse(device.sent.contains("press") || device.sent.contains("release") && device.sent.last == "release",
                       "A press, move and release over separate round trips pause the finger: App Switcher")
        let flick = try XCTUnwrap(device.sent.last)
        XCTAssertTrue(flick.hasPrefix("flick "))
        XCTAssertEqual(device.sent[device.sent.count - 3], "move 255 0")
        let start = device.sent[device.sent.count - 2].split(separator: " ").compactMap { Int($0) }
        XCTAssertEqual(start.first, 0)
        XCTAssertGreaterThan(start.last ?? 0, 1160, "Start inside the home bar")
        let stroke = flick.split(separator: " ").compactMap { Int($0) }
        XCTAssertEqual(stroke.count, 3, "dx, dy and the speed")
        XCTAssertEqual(stroke[0], 0)
        let rise = -stroke[1], step = stroke[2]
        XCTAssertGreaterThan(rise, 1174 / 5, "Travel at least a fifth of the screen")
        XCTAssertGreaterThanOrEqual(step, 30, "Slower than this the stroke sits near the App Switcher boundary")
        XCTAssertLessThanOrEqual(step, 60, "The firmware rejects a faster stroke")
        XCTAssertLessThanOrEqual(Double(rise) / Double(step) * 8, 120, "The whole stroke stays a flick (ms)")
        let homes = device.sent.filter { $0 == "home" }.count
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.filter { $0 == "home" }.count, homes + 1)
    }

    func testBackTouchesDownOnTheEdgeStartsSlowlyAndLiftsMovingFast() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        try await pointer.goBack()
        let stroke = Array(device.sent.suffix(4))
        XCTAssertEqual(stroke[0], "move -\(Pointer.edgePush) 0",
                       "Pushed past the edge, the pointer stops on it: where home leaves it, iOS sees no edge swipe")
        XCTAssertEqual(stroke[1], "press", "Its own command: the finger rests on the edge before it moves")
        XCTAssertEqual(stroke[2], "move \(Pointer.backStart) 0", "A slow start, or iOS does not take the stroke")
        let flick = stroke[3].split(separator: " ").compactMap { Int($0) }
        XCTAssertTrue(stroke[3].hasPrefix("flick "), "The lift belongs to the last moves: no round trip rests the finger")
        XCTAssertEqual(flick.count, 3, "dx, dy and the speed")
        XCTAssertEqual(flick[1], 0)
        XCTAssertGreaterThanOrEqual(flick[2], 30, "Lifted more slowly, the page slides back now and then")
        let end = Double(Pointer.backStart + flick[0]) / 510
        XCTAssertGreaterThan(end, 0.6, "Past the middle")
        XCTAssertLessThan(end, 0.8, "Bigger reports carry further than their units say: stay clear of the right edge")
        XCTAssertEqual(device.sent.lastIndex(of: "release").map { $0 < device.sent.count - 4 }, true,
                       "Only the release that begins a gesture on a new link: flick lifts by itself")
        let homes = device.sent.filter { $0 == "home" }.count
        try await pointer.point(0.5, 0.5)
        XCTAssertEqual(device.sent.filter { $0 == "home" }.count, homes + 1, "The edge clamped the pointer: re-home")
    }

    func testBackLetsGoWhenItsStrokeFails() async throws {
        final class Failing: HIDDevice {
            var links = 1
            var connected = true
            var sent: [String] = []
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick") { throw DeviceError(message: "board link lost during 'flick'") }
                return "ok"
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        let device = Failing()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        do { try await pointer.goBack(); XCTFail("The failure must reach the caller") } catch {}
        XCTAssertEqual(device.sent.last, "release", "The button went down in an earlier command: never leave it down")
    }

    func testBackOnFirmwareWithoutFlickMovesOnAndLifts() async throws {
        final class Old: HIDDevice {
            var links = 1
            var connected = true
            var sent: [String] = []
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick") { throw DeviceError(message: "err unknown command") }
                return "ok"
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        let device = Old()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        try await pointer.goBack()
        let tail = Array(device.sent.suffix(3))
        XCTAssertTrue(tail[0].hasPrefix("flick "))
        XCTAssertTrue(tail[1].hasPrefix("move ") && tail[1].hasSuffix(" 0"))
        XCTAssertEqual(tail[2], "release")
    }

    func testFirmwareWithoutFlickFallsBackToOneShortSwipe() async throws {
        final class OldFirmware: HIDDevice {
            var links = 1
            var connected = true
            var sent: [String] = []
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick") { throw DeviceError(message: "err unknown command") }
                return ""
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        let device = OldFirmware()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        try await pointer.goHome()
        let fallback = try XCTUnwrap(device.sent.firstIndex { $0.hasPrefix("flick") })
        XCTAssertEqual(Array(device.sent[(fallback + 1)...].filter { ["press", "release"].contains($0) }), ["press", "release"])
    }

    func testFirmwareWhoseFlickHasNoSpeedStillFlicksHome() async throws {
        final class SlowFirmware: HIDDevice {
            var links = 1
            var connected = true
            var sent: [String] = []
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick"), command.split(separator: " ").count > 3 {
                    throw DeviceError(message: "err invalid movement (dx dy required)")
                }
                return ""
            }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
        }
        let device = SlowFirmware()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.finishCalibration(x: 200.0 / 510, y: 200.0 / 1174)
        try await pointer.goHome()
        let flicks = device.sent.filter { $0.hasPrefix("flick") }
        XCTAssertEqual(flicks.count, 2)
        XCTAssertEqual(flicks[1], flicks[0].split(separator: " ").prefix(3).joined(separator: " "))
        XCTAssertFalse(device.sent.contains("press"), "The slower flick is still one atomic stroke")
    }

    func testAimedFlickKeepsItsEndpointWhenOlderFirmwareFallsBack() async throws {
        final class Old: HIDDevice {
            var links = 1, connected = true
            var sent: [String] = []
            let hasFlick: Bool
            init(_ hasFlick: Bool) { self.hasFlick = hasFlick }
            func waitConnected(_ timeout: TimeInterval) async -> Bool { true }
            func send(_ command: String) async throws -> String {
                sent.append(command)
                if command.hasPrefix("flick") {
                    if !hasFlick { throw DeviceError(message: "err unknown command") }
                    if command.split(separator: " ").count > 3 {
                        throw DeviceError(message: "err invalid movement (dx dy required)")
                    }
                }
                return ""
            }
        }
        for hasFlick in [true, false] {
            let device = Old(hasFlick)
            let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
            defer { try? FileManager.default.removeItem(at: file) }
            let pointer = Pointer(device: device, calibrationFile: file)
            pointer.boardSettles = { true }
            pointer.finishCalibration(x: 0.5, y: 0.25)
            try await pointer.flick(0.5, 0.75, 0.5, 0.25, duration: 0.1, aimed: true)
            let first = try XCTUnwrap(device.sent.firstIndex { $0.hasPrefix("flick") })
            XCTAssertEqual(device.sent[first], "flick 0 -333 26")
            XCTAssertTrue(device.sent.dropFirst(first + 1).contains(hasFlick ? "flick 0 -400" : "move 0 -400"),
                          "The fallback pace is calibrated: using the shortened -333 misses the endpoint.")
        }
    }

    func testCancelledDragReleasesEvenWhenDeviceRejectsCancelledCommands() async throws {
        let device = FakeDevice()
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        defer { try? FileManager.default.removeItem(at: file) }
        let pointer = Pointer(device: device, calibrationFile: file)
        pointer.boardSettles = { true }  // no rests: the press follows the moves at once
        pointer.finishCalibration(x: 0.5, y: 0.25)
        let gesture = Task { try await pointer.swipe(0.5, 0.9, 0.5, 0.8, duration: 10) }
        for _ in 0..<100 where !device.sent.contains("press") { await Task.yield() }
        XCTAssertTrue(device.sent.contains("press"))
        gesture.cancel()
        do {
            try await gesture.value
            XCTFail("The gesture must propagate cancellation")
        } catch is CancellationError {
        }
        XCTAssertEqual(device.sent.last, "release", "Cancellation must not leave the pointer pressed")
        XCTAssertEqual(device.sent.filter { $0 == "release" }.count, 2)
        XCTAssertEqual(device.sent.filter { $0 == "press" }.count, 1)
    }

    func testShortStatusNotifyIsMergedWithTheFullRead() throws {
        let full = try XCTUnwrap(BoardStatus.decode(Data(#"{"up":1,"heap":81234,"usb":"ok","net":"ap","sta":2,"ap":"idle","kbps":180,"ble":{"mtu":247,"phy":2}}"#.utf8)))
        let short = try XCTUnwrap(BoardStatus.decode(Data(#"{"up":2,"usb":"asleep","net":"ap","ap":"streaming","ble":{"mtu":23}}"#.utf8)))
        let m = full.merged(with: short)
        XCTAssertEqual(m.up, 2)
        XCTAssertEqual(m.usb, "asleep")
        XCTAssertEqual(m.ap, "streaming")
        XCTAssertEqual(m.heap, 81234)  // kept from the full read
        XCTAssertEqual(m.sta, 2)
        XCTAssertEqual(m.ble?.mtu, 23)
        XCTAssertEqual(m.ble?.phy, 2)
    }

    func testFreshCalibrationSurvivesARestart() {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".json")
        let pointer = Pointer(device: FakeDevice(), calibrationFile: file)
        XCTAssertFalse(pointer.calibrated)
        pointer.finishCalibration(x: 0.5, y: 0.25)
        let again = Pointer(device: FakeDevice(), calibrationFile: file)
        XCTAssertEqual(again.span, Pointer.Span(w: 400, h: 800))
    }

    func testProbeFitRecoversScaleAndOffset() {
        let samples: [(Double, Double)] = [150.0, 350, 60].map { u in (u, 0.02 + u / 400) }
        let line = ProbeFit.line(samples)
        XCTAssertEqual(line?.a ?? 0, 1 / 400, accuracy: 1e-9)
        XCTAssertEqual(line?.b ?? 0, 0.02, accuracy: 1e-9)
        XCTAssertEqual(line?.rms ?? 1, 0, accuracy: 1e-9)
        XCTAssertEqual(line?.units(for: 0.52), 200)
        XCTAssertNil(ProbeFit.line([(100, 0.3)]))
        XCTAssertFalse(ProbeFit.usable(0.995))  // stuck at the edge
    }

    func testAssistiveTouchFalseOutsideGuidedAccessIsUnknown() {
        XCTAssertEqual(AssistiveTouchState.observed(guidedAccess: false, running: false), .unknown)
        XCTAssertEqual(AssistiveTouchState.observed(guidedAccess: false, running: true), .unknown)
        XCTAssertEqual(AssistiveTouchState.observed(guidedAccess: true, running: false), .disabled)
        XCTAssertEqual(AssistiveTouchState.observed(guidedAccess: true, running: true), .enabled)
    }
}
