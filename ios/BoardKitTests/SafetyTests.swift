import XCTest
@testable import BoardKitHarness

@MainActor final class FakeDevice: HIDDevice {
    var links = 1
    var connected = true
    var sent: [String] = []
    func send(_ command: String) async throws -> String { try Task.checkCancellation(); sent.append(command); return "" }
    func waitConnected(_ timeout: TimeInterval) async -> Bool { connected }
}

@MainActor final class SafetyTests: XCTestCase {
    func testBLEReadinessNeverFallsBackToPowerCableUSB() throws {
        let s = try XCTUnwrap(BoardStatus.decode(Data(#"{"hid":"ble","usb":"ok","hid_ready":false}"#.utf8)))
        XCTAssertFalse(s.inputReady)
        let missing = try XCTUnwrap(BoardStatus.decode(Data(#"{"hid":"ble","usb":"ok"}"#.utf8)))
        XCTAssertFalse(missing.inputReady)
        let old = try XCTUnwrap(BoardStatus.decode(Data(#"{"usb":"ok"}"#.utf8)))
        XCTAssertTrue(old.inputReady)
    }

    func testShortStatusPreservesHIDCapabilitiesAndUpdatesReadiness() throws {
        let full = try XCTUnwrap(BoardStatus.decode(Data(#"{"hid":"ble","hid_ready":true,"ble_hid":"ready","hid_caps":"mouse,keyboard,consumer"}"#.utf8)))
        let brief = try XCTUnwrap(BoardStatus.decode(Data(#"{"hid_ready":false,"ble_hid":"pairing"}"#.utf8)))
        let merged = full.merged(with: brief)
        XCTAssertEqual(merged.hid, "ble")
        XCTAssertEqual(merged.hid_caps, "mouse,keyboard,consumer")
        XCTAssertFalse(merged.inputReady)
    }

    func testDisconnectClearsPreviousBoardStatus() throws {
        let board = BoardLink(mock: true)
        board.mockStatus(try XCTUnwrap(BoardStatus.decode(Data(#"{"hid":"ble","hid_ready":true,"usb":"off"}"#.utf8))))
        XCTAssertNotNil(board.status)
        board.forget()
        XCTAssertNil(board.status)
        let legacy = try XCTUnwrap(BoardStatus.decode(Data(#"{"usb":"ok"}"#.utf8)))
        let next = board.status?.merged(with: legacy) ?? legacy
        XCTAssertNil(next.hid)
        XCTAssertTrue(next.inputReady)
    }

    func testChangedTransportCannotInheritReadyFromPreviousTransport() throws {
        for (before, after) in [("ble", "usb"), ("usb", "ble")] {
            let old = try XCTUnwrap(BoardStatus.decode(Data("{\"hid\":\"\(before)\",\"hid_ready\":true,\"ble_hid\":\"ready\"}".utf8)))
            let changed = try XCTUnwrap(BoardStatus.decode(Data("{\"hid\":\"\(after)\"}".utf8)))
            let merged = old.merged(with: changed)
            XCTAssertEqual(merged.hid, after)
            XCTAssertNil(merged.hid_ready)
            XCTAssertFalse(merged.inputReady)
            XCTAssertEqual(merged.ble_hid, "ready")
        }
    }

    func testCancelledQueuedCommandNeverWrites() async throws {
        let board = FakeBoard(), channel = CommandChannel()
        channel.transport = board; board.channel = channel; board.silent = true
        let first = Task { try await channel.send("move 100 0") }
        try await Task.sleep(for: .milliseconds(20))
        let second = Task { try await channel.send("click") }
        try await Task.sleep(for: .milliseconds(20))
        second.cancel(); first.cancel()
        _ = try? await first.value; _ = try? await second.value
        XCTAssertEqual(board.lines.count, 1)
        XCTAssertTrue(board.lines[0].contains("move 100 0"))
    }

    func testTimeoutDoesNotReplayAnUncertainClick() async throws {
        let board = FakeBoard(), channel = CommandChannel()
        channel.transport = board; board.channel = channel; board.silent = true
        do { _ = try await channel.send("click", timeout: 0.02); XCTFail("Expected timeout") }
        catch { XCTAssertTrue(error is BoardTimeout) }
        XCTAssertEqual(board.lines.count, 1)
        XCTAssertEqual(channel.actionRevision, 1)
    }

    private func verdict(now: Double, capturedAt: Double, after: Double?, statusAt: Double? = nil,
                         lag: Int? = 0) -> FrameFreshness.Verdict {
        FrameFreshness.verdict(now: now, capturedAt: capturedAt, stimulusAt: after, statusAt: statusAt ?? now, lag: lag)
    }

    func testBacklogBlocksEvenARecentlyReceivedFrame() {
        XCTAssertEqual(verdict(now: 100, capturedAt: 99.9, after: 99, lag: 900_000), .catchingUp(900_000))
    }

    func testStillFrameWithFreshCaughtUpHeartbeatStillNeedsAProbe() {
        XCTAssertEqual(verdict(now: 100, capturedAt: 10, after: nil), .probe)
        XCTAssertEqual(verdict(now: 100, capturedAt: 10, after: 5), .probe, "proof of liveness expires")
        XCTAssertEqual(verdict(now: 100, capturedAt: 10, after: 5, statusAt: 90), .unavailable("board status is stale"))
    }

    func testFrameAfterAStimulusIsCurrentOnlyWhileRecent() {
        XCTAssertEqual(verdict(now: 101, capturedAt: 100, after: 99.8), .current)
        XCTAssertEqual(verdict(now: 100 + FrameFreshness.proofWindow + 0.1, capturedAt: 100, after: 99.8), .probe)
    }

    func testActionRejectsItsPreActionFrameAndHeartbeat() {
        XCTAssertEqual(verdict(now: 100, capturedAt: 99.5, after: 99.8), .awaitingFrame)
        XCTAssertEqual(verdict(now: 99.8 + FrameFreshness.stimulusTimeout + 0.1, capturedAt: 99.5, after: 99.8), .probe)
        XCTAssertEqual(verdict(now: 170, capturedAt: 99.5, after: 99.8), .probe)
        XCTAssertEqual(verdict(now: 100.5, capturedAt: 100, after: 99.8), .current)
    }

    func testInputObservationBoundaryExistsBeforeAckAndSurvivesFailureStopAndReconnect() async throws {
        let board = FakeBoard(), channel = CommandChannel(transport: nil)
        channel.transport = board; board.channel = channel; board.silent = true
        let oldFrame = now() - 10
        let input = Task { try await channel.send("type test", timeout: 0.05) }
        while board.lines.isEmpty { await Task.yield() }
        let boundary = try XCTUnwrap(channel.observationAfter)
        XCTAssertGreaterThan(boundary, oldFrame)
        XCTAssertNotEqual(verdict(now: now(), capturedAt: oldFrame, after: channel.observationAfter), .current)
        do { _ = try await input.value; XCTFail("Expected uncertain input timeout") }
        catch { XCTAssertTrue(error is BoardTimeout) }
        XCTAssertEqual(channel.observationAfter, boundary)
        board.silent = false
        try await channel.send("stop")
        channel.linkDown(); channel.linkUp()
        try await channel.send("ping")
        XCTAssertEqual(channel.observationAfter, boundary)
        XCTAssertEqual(verdict(now: boundary + 70, capturedAt: oldFrame, after: channel.observationAfter), .probe)
        XCTAssertEqual(verdict(now: boundary + 70, capturedAt: 0, after: channel.observationAfter), .probe)
        XCTAssertEqual(verdict(now: boundary + 1.5, capturedAt: boundary + 1, after: channel.observationAfter), .current)
    }

    func testNewFrameBeforeDelayedAckRemainsUsableAfterActionSettles() async throws {
        let board = FakeBoard(), channel = CommandChannel(transport: nil)
        channel.transport = board; board.channel = channel; board.silent = true
        let input = Task { try await channel.send("click") }
        while board.lines.isEmpty { await Task.yield() }
        let boundary = try XCTUnwrap(channel.observationAfter), capturedAt = boundary + 0.001
        try await Task.sleep(for: .milliseconds(20))
        let id = try XCTUnwrap(board.lines.first?.split(separator: " ").first)
        channel.handleReply("\(id) ok")
        _ = try await input.value
        XCTAssertEqual(channel.observationAfter, boundary, "An ACK or post-tap delay is not another input")
        XCTAssertEqual(verdict(now: now(), capturedAt: capturedAt, after: channel.observationAfter), .current)
    }

    func testCancelledQueuedInputLeavesNoObservationBoundary() async throws {
        let board = FakeBoard(), channel = CommandChannel(transport: nil)
        channel.transport = board; board.channel = channel; board.silent = true
        let ping = Task { try await channel.send("ping") }
        while board.lines.isEmpty { await Task.yield() }
        let input = Task { try await channel.send("click") }
        await Task.yield()
        input.cancel(); ping.cancel()
        _ = try? await ping.value; _ = try? await input.value
        XCTAssertEqual(board.lines.count, 1)
        XCTAssertNil(channel.observationAfter)
        XCTAssertEqual(verdict(now: 100, capturedAt: 10, after: channel.observationAfter), .probe)
    }

    func testEveryInputIncludingHomeAdvancesTheObservationBoundary() async throws {
        let board = FakeBoard(), channel = CommandChannel(transport: nil)
        channel.transport = board; board.channel = channel
        for command in ["move 1 0", "home", "click", "press", "release", "type a", "key a", "homescreen", "scroll 1 0"] {
            let before = now()
            try await channel.send(command)
            let boundary = try XCTUnwrap(channel.observationAfter)
            XCTAssertGreaterThanOrEqual(boundary, before, command)
            XCTAssertNotEqual(verdict(now: now(), capturedAt: before - 1, after: channel.observationAfter), .current, command)
        }
    }

    func testReturningAProbeNudgeIsNotAnObservationBoundary() async throws {
        let board = FakeBoard(), channel = CommandChannel(transport: nil)
        channel.transport = board; board.channel = channel
        try await channel.send("move 12 0")
        let probe = try XCTUnwrap(channel.observationAfter)
        try await channel.sendUnobserved("move -12 0")
        XCTAssertEqual(channel.observationAfter, probe, "the pointer's return changes no page state")
        XCTAssertEqual(board.lines.count, 2)
        XCTAssertEqual(verdict(now: probe + 1, capturedAt: probe + 0.5, after: channel.observationAfter), .current)
    }
}
