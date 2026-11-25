import CoreGraphics
import Foundation

/// Checked immediately before a physical write; throwing refuses it.
typealias InputPermit = @MainActor () throws -> Void

/// System destinations with no key of their own. Each backend realizes them its own way.
enum InputButton: String {
    case home, back, search
    case controlCenter = "control_center"
}

/// One way of delivering input to the phone (ESP32 pointer and keyboard, ...). It never reads the screen.
/// Coordinates are normalized 0..1 from the top-left corner.
@MainActor protocol InputBackend: AnyObject {
    var name: String { get }
    var connected: Bool { get }
    /// The phone accepts this device's input right now.
    var ready: Bool { get }
    /// How the input reaches the phone ("ble", "usb", ...), for status and pairing rules.
    var transport: String { get }
    /// Bumps on every input written, so a caller can tell whether a failed action may have reached the phone.
    var revision: Int { get }
    /// When the last observed input left; frames sampled earlier cannot show its result.
    var lastInput: InputMark { get }
    /// Where a visible pointer is on screen, nil when unknown or when the backend draws none.
    var pointerLocation: CGPoint? { get }

    /// count clicks that many times without moving in between (2: a double tap).
    func tap(_ x: Double, _ y: Double, count: Int) async throws
    func longPress(_ x: Double, _ y: Double, seconds: Double) async throws
    /// One stroke from the first point to the second. `seconds` is the travel time, nil for the device's own
    /// pace; `hold` rests at the start first; `flick` lifts while still moving instead of stopping at the end.
    func swipe(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, seconds: Double?, hold: Double, flick: Bool) async throws
    /// Printable ASCII, key by key.
    func type(_ text: String) async throws
    func key(_ combo: String) async throws
    func press(_ button: InputButton) async throws

    /// Pointer movements that press nothing, offered to the screen side as its stimulus.
    func nudge(_ units: Int) async throws -> Int
    func unnudge(_ step: Int) async throws
    func refresh(by step: Int, authorize: @escaping @MainActor () async throws -> InputPermit) async throws
    func invalidatePointer()

    /// Out of band: interrupt whatever is being sent and let go of every button and key.
    func halt() throws
}
