import CoreGraphics
import Foundation

/// Input backend: the ESP32 board as a Bluetooth (or USB) mouse and keyboard. The mouse is relative, so
/// coordinates go through the calibrated `Pointer`; Home, Back, Search and Control Center are edge flicks.
/// Pointer actions need AssistiveTouch and calibration; keyboard input needs only the connected HID transport.
@MainActor final class BoardInput: InputBackend {
    let name = "esp32"
    let board: BoardLink
    let pointer: Pointer
    private var commands: CommandChannel { board.commands }

    init(board: BoardLink, pointer: Pointer) {
        self.board = board
        self.pointer = pointer
        pointer.boardSettles = { [weak board] in board?.status?.hid_caps?.contains("settle") == true }
    }

    var connected: Bool { board.connected }
    var ready: Bool { board.status?.inputReady ?? false }
    var transport: String { board.status?.hid ?? "usb" }
    var revision: Int { commands.actionRevision }
    var lastInput: InputMark { InputMark(wall: commands.observationAfter, uptime: commands.observationAfterUptime) }
    var pointerLocation: CGPoint? { pointer.location }

    func tap(_ x: Double, _ y: Double, count: Int) async throws { try await pointer.tap(x, y, count: count) }

    func longPress(_ x: Double, _ y: Double, seconds: Double) async throws {
        try await pointer.longPress(x, y, seconds: seconds)
    }

    func swipe(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, seconds: Double?, hold: Double, flick: Bool) async throws {
        if flick { try await pointer.flick(x1, y1, x2, y2, duration: seconds, startHold: hold, aimed: true) }
        else { try await pointer.swipe(x1, y1, x2, y2, duration: seconds ?? 0, startHold: hold) }
    }

    func type(_ text: String) async throws { try await pointer.type(text) }
    func key(_ combo: String) async throws { try await pointer.key(combo) }

    func press(_ button: InputButton) async throws {
        switch button {
        case .home: try await pointer.goHome()
        case .back: try await pointer.goBack()
        case .search: try await pointer.openSearch()
        case .controlCenter: try await pointer.openControlCenter()
        }
    }

    func nudge(_ units: Int) async throws -> Int { try await pointer.nudge(units) }
    func unnudge(_ step: Int) async throws { try await pointer.unnudge(step) }

    func refresh(by step: Int, authorize: @escaping @MainActor () async throws -> InputPermit) async throws {
        try await pointer.stayAfterClick()
        try await commands.refreshPointer(by: step, authorize: authorize)
    }

    func invalidatePointer() { pointer.invalidatePosition() }

    /// `stop` bypasses the command FIFO so the firmware can interrupt a paced move or typing loop.
    func halt() throws {
        pointer.invalidatePosition()
        guard board.connected else { return }
        try board.write("0 stop")
        try board.write("0 release") // old USB firmware can still release a held mouse
    }
}
