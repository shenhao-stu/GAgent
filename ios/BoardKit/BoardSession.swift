import Combine
import Foundation
import UIKit

/// The coordinator between the two phone tools: `screen` (`ScreenService`, ReplayKit Broadcast Extension)
/// reads pixels and `hid` (`HIDService`, ESP32-S3 BLE HID) sends input; neither knows the other.
/// This session owns consent, user takeover, one request at a time, calibration, and the write gate.
@MainActor final class BoardSession: ObservableObject, ScreenStimulus {
    static let shared = BoardSession()
    let board = BoardLink()
    let metrics = Metrics()
    let probe = TouchProbe()
    let pointer: Pointer
    let screen: ScreenService
    let hid: HIDService
    private let input: BoardInput
    private let replay = ReplayCapture()
    lazy var calibrator = AutoCalibrator(app: self)
    @Published private(set) var busy = false
    @Published var testingLink = false
    @Published var lastError = ""
    @Published var consent: Bool {
        didSet {
            UserDefaults.standard.set(consent, forKey: "gagent.boardConsent")
            if !consent { hid.forgetStaged(); stop() }
        }
    }
    private var takeover = PhoneTakeover()
    private var active: Task<[String: Any], Error>?
    private var inputGeneration: Int?
    private var pointerAction = false
    private var actionBaseline: Int?
    private var unsettled: (sent: Double, minimum: Double)?
    private var heartbeat: Task<Void, Never>?
    private var accessibilityObserver: AnyCancellable?
    var onActivity: ((String) -> Void)?
    var backgroundRunState: () -> String = { "unsupported" }
    var dismissKeyboard: () -> Void = {}

    init() {
        consent = UserDefaults.standard.bool(forKey: "gagent.boardConsent")
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("BoardKit", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let pointer = Pointer(device: board.commands, calibrationFile: directory.appendingPathComponent("calibration.json"))
        let input = BoardInput(board: board, pointer: pointer)
        self.pointer = pointer
        self.input = input
        hid = HIDService(backend: input)
        screen = ScreenService(source: replay)

        pointer.screenAspect = { DeviceScreen.aspect }
        board.log = DebugLog.write
        pointer.log = DebugLog.write
        board.commands.log = DebugLog.write

        replay.access = { [weak self] in try self?.requireAccess() }
        replay.inputMark = { [weak self] in self?.input.lastInput ?? InputMark() }
        replay.stimulus = self
        screen.pointerLocation = { [weak self] in self?.input.pointerLocation }
        replay.onSessionChange = { [weak self] wasSharing in
            guard let self else { return }
            screen.forget()
            if wasSharing { stop() }
            objectWillChange.send()
        }
        replay.onChange = { [weak self] in self?.objectWillChange.send() }

        hid.access = { [weak self] in
            guard let self else { throw CancellationError() }
            try ScreenObservation.requireAccess(consent: consent, generation: 0)
        }
        hid.dismissKeyboard = { [weak self] in self?.dismissKeyboard() }
        board.commands.beforeWrite = { [weak self] command in
            guard let self else { throw CancellationError() }
            return try await authorizeWrite(command)
        }

        board.onStatus = { [weak self] status in
            guard let self else { return }
            metrics.status(status)
            objectWillChange.send()
        }
        board.onLinkUp = { [weak self] in
            guard let self else { return }
            self.replay.linkUp()
            try? board.write("0 stop")
        }
        board.onLinkDown = { [weak self] in
            guard let self else { return }
            active?.cancel()
            self.replay.linkLost()
        }
        accessibilityObserver = NotificationCenter.default.publisher(for: UIAccessibility.assistiveTouchStatusDidChangeNotification)
            .receive(on: DispatchQueue.main).sink { [weak self] _ in
                guard let self else { return }
                stop()
                UserDefaults.standard.removeObject(forKey: "gagent.calibratedBoard")
                objectWillChange.send()
            }
        replay.start()
        heartbeat = Task { [weak self] in
            while !Task.isCancelled {
                guard (try? await Task.sleep(for: .seconds(2))) != nil else { return }
                guard let self else { return }
                metrics.tick()
                if board.connected { _ = try? await board.commands.send("ping") }
            }
        }
    }

    // MARK: Sources and readiness

    var previewFrame: Data? { screen.preview }
    var screenSharingActive: Bool { screen.sharing }

    /// Local ReplayKit capture pairs exclusively with wireless Bluetooth HID so power cables never send clicks elsewhere.
    var hidReady: Bool { input.ready && input.transport == "ble" }
    var inputAvailable: Bool { hidReady && DeviceScreen.assistiveTouch != .disabled }
    private func requireSystemInput(pointer: Bool = true) throws {
        guard pointer ? hidReady : input.transport == "ble" else {
            throw DeviceError(message: "Bluetooth input is unavailable")
        }
        guard !pointer || DeviceScreen.assistiveTouch != .disabled else {
            throw DeviceError(message: "Enable AssistiveTouch in iPhone Settings → Accessibility → Touch")
        }
    }
    var calibrationReady: Bool {
        let defaults = UserDefaults.standard
        guard pointer.calibrated, !calibrator.needed, pointer.quality != nil,
              defaults.string(forKey: "gagent.calibratedBoard") == calibrationIdentity else { return false }
        return defaults.string(forKey: "gagent.verifiedReplayBoard") == calibrationIdentity
    }
    private var calibrationIdentity: String { "\(board.pairedID?.uuidString ?? "none"):\(input.transport)" }
    func confirmCalibration() {
        let defaults = UserDefaults.standard
        defaults.set(calibrationIdentity, forKey: "gagent.calibratedBoard")
        defaults.set(calibrationIdentity, forKey: "gagent.verifiedReplayBoard")
    }
    var inputReady: Bool { consent && board.connected && inputAvailable && calibrationReady }
    var ready: Bool { inputReady && screen.sharing }

    private func requireAccess() throws {
        guard !takeover.paused else { throw DeviceError(message: "Phone control is paused for the user") }
        try ScreenObservation.requireAccess(consent: consent, generation: 0)
    }

    private func requireReady(movement: Bool, generation: Int? = nil) throws {
        try requireAccess()
        guard input.connected else { throw DeviceError(message: "ESP32 board is not connected") }
        if let generation {
            guard generation == screen.generation else { throw ScreenObservation.Failure.frameChanged }
            try screen.source.requireSharing()
        }
        if movement {
            try requireSystemInput()
            guard calibrationReady else { throw DeviceError(message: "Complete pointer calibration in iPhone control setup") }
        }
    }

    // MARK: The gate every input write passes

    private func authorizeWrite(_ command: String, refreshGeneration: Int? = nil) async throws -> InputPermit {
        let name = String(command.split(separator: " ").first ?? "")
        guard CommandChannel.inputCommands.contains(name), name != "release" else { return {} }
        let expected = refreshGeneration ?? inputGeneration
        let calibrationWrite = calibrator.boardOpen || calibrator.busy
        func requireCalibrationOverlay() throws {
            if calibrationWrite && (!DeviceScreen.foreground || !calibrator.boardOpen) {
                throw DeviceError(message: "Return to the foreground calibration screen before moving the pointer")
            }
        }
        try requireCalibrationOverlay()
        try requireReady(movement: false, generation: expected)
        try requireSystemInput(pointer: name != "key" && name != "type")
        let source = screen.source
        if refreshGeneration != nil, command != "move 12 0", command != "move -12 0" {
            throw ScreenObservation.Failure.frameChanged
        }
        if let expected { try await source.proveLive(generation: expected, forStimulus: refreshGeneration != nil) }
        return { [self] in
            guard expected == nil || screen.source === source else { throw ScreenObservation.Failure.frameChanged }
            try requireCalibrationOverlay()
            try requireReady(movement: pointerAction, generation: expected)
            try requireSystemInput(pointer: name != "key" && name != "type")
            try hid.requirePaste()
        }
    }

    // MARK: ScreenStimulus

    var stimulusReady: Bool { hidReady }

    func refresh(generation: Int) async throws -> Int {
        let step = (input.pointerLocation?.x ?? 0.5) > 0.8 ? -12 : 12
        try await input.refresh(by: step) { [self] in
            try await authorizeWrite("move \(step) 0", refreshGeneration: generation)
        }
        return step
    }

    func undoRefresh(_ step: Int, generation: Int) async throws {
        try await input.refresh(by: -step) { [self] in
            try await authorizeWrite("move \(-step) 0", refreshGeneration: generation)
        }
    }

    func nudge(_ units: Int) async throws -> Int { try await input.nudge(units) }
    func unnudge(_ step: Int) async throws { try await input.unnudge(step) }
    func stimulusFailed() { input.invalidatePointer() }

    // MARK: Status and stop

    func statusJSON() -> [String: Any] {
        var result: [String: Any] = [
            "ok": true, "paired": board.pairedID != nil, "connected": board.connected,
            "consent": consent, "calibrated": calibrationReady,
            "ready": ready, "input_ready": inputReady, "busy": busy, "hid_transport": input.transport,
            "hid_ready": hidReady, "board_name": board.name,
            "wireless_requires_power": true, "coordinate_system": "normalized_top_left"
        ]
        result["keyboard_ready"] = consent && !takeover.paused && board.connected ? (hidReady ? true as Any : NSNull()) : false
        result["ios_version"] = UIDevice.current.systemVersion
        result["gagent_foreground"] = UIApplication.shared.applicationState == .active
        result["capture_source"] = screen.source.name
        result["input_backend"] = input.name
        result["screen_sharing_active"] = screen.sharing
        result.merge(replay.diagnostics) { _, new in new }
        result["calibration_error"] = pointer.quality
        result["assistive_touch"] = DeviceScreen.assistiveTouch.rawValue
        result["system_input_ready"] = inputAvailable && calibrationReady
        result["ble_hid"] = board.status?.ble_hid
        result["background_run"] = backgroundRunState()
        result["thermal"] = ["nominal", "fair", "serious", "critical"][min(ProcessInfo.processInfo.thermalState.rawValue, 3)]
        result["low_power_mode"] = ProcessInfo.processInfo.isLowPowerModeEnabled
        result["element_detector"] = false
        result["observation"] = switch screen.source.freshness() {
        case .current: "current"
        case .probe: "verified_on_next_observation"
        case .awaitingFrame: "awaiting_frame_after_input"
        case .catchingUp(let bytes): "catching_up_\(bytes / 1024)_kb"
        case .unavailable(let reason): "unavailable: \(reason)"
        }
        if !lastError.isEmpty { result["last_error"] = lastError }
        return result
    }

    func say(_ message: String) { DebugLog.write(message) }

    @discardableResult func stop(endRun: Bool = true) -> [String: Any] {
        screen.forget()
        unsettled = nil
        if endRun { onActivity?("stop") }
        active?.cancel()
        if calibrator.boardOpen { calibrator.cancel() }
        do {
            try input.halt()
            return ["ok": true, "stopped": true, "release_sent": input.connected]
        } catch { return ["ok": false, "stopped": true, "error": error.localizedDescription] }
    }

    // MARK: Tool entry points

    func tool(_ request: [String: Any]) async -> [String: Any] {
        let args = request["args"] as? [String: Any] ?? [:]
        switch request["tool"] as? String {
        case "screen": return await traced("screen") { await readScreen(args) }
        case "hid": return await traced(args["action"] as? String ?? "status") { await sendInput(args) }
        case "takeover": return handoff(args)
        default: return ["ok": false, "error": "Unknown phone tool"]
        }
    }

    private func traced(_ action: String, _ body: () async -> [String: Any]) async -> [String: Any] {
        let monotonicStart = ProcessInfo.processInfo.systemUptime
        var result = await body()
        var timing = result["timing_ms"] as? [String: Int] ?? [:]
        timing["native_total"] = Int((ProcessInfo.processInfo.systemUptime - monotonicStart) * 1000)
        result["timing_ms"] = timing
        return result
    }

    private func handoff(_ args: [String: Any]) -> [String: Any] {
        switch args["action"] as? String {
        case "pause":
            let result = stop()
            guard result["ok"] as? Bool == true else { return result }
            return ["ok": true, "token": takeover.pause()]
        case "resume", "cancel":
            let ending = args["action"] as? String == "cancel"
            guard (ending || !busy), let token = args["token"] as? String, takeover.resume(token) else {
                return ["ok": false, "error": "Handoff expired or an input is still stopping"]
            }
            if ending { return stop() }
            return ["ok": true, "needs_observation": true]
        default:
            return ["ok": false, "error": "Unknown handoff action"]
        }
    }

    private static let pausedReply: [String: Any] = [
        "ok": false, "error": "User is controlling the phone; wait for explicit resume", "action_sent": false]

    private func readScreen(_ args: [String: Any], textBoxes: Bool = false) async -> [String: Any] {
        guard !takeover.paused else { return Self.pausedReply }
        return await exclusive("screen") { [self] in
            let started = ProcessInfo.processInfo.systemUptime
            if let pending = unsettled {
                await screen.source.settle(since: pending.sent, minimum: pending.minimum)
                unsettled = nil
            } else {
                await screen.source.comeToRest()
            }
            let settled = ProcessInfo.processInfo.systemUptime
            var result = try await screen.observe(marks: args["marks"] as? Bool == true, ocr: args["ocr"] as? Bool ?? true,
                                                  region: args["region"] as? [String: Any], textBoxes: textBoxes,
                                                  image: args["image"] as? Bool ?? true)
            var timing = result["timing_ms"] as? [String: Int] ?? [:]
            timing["settle"] = Int((settled - started) * 1000)
            timing["total"] = Int((ProcessInfo.processInfo.systemUptime - started) * 1000)
            result["timing_ms"] = timing
            return result
        }
    }

    private func sendInput(_ args: [String: Any]) async -> [String: Any] {
        let action = args["action"] as? String ?? "status"
        if action == "status" {
            onActivity?("status")
            await replay.refresh()
            return statusJSON()
        }
        if action == "stop" { return stop(endRun: args["end_run"] as? Bool ?? true) }
        guard !takeover.paused else { return Self.pausedReply }
        if action == "stage_text" {
            guard !busy else { return ["ok": false, "error": "Wait for the current phone action before staging new text"] }
            do { try hid.stage(try HIDService.typedText(args["text"])); return ["ok": true, "staged": true] }
            catch { return ["ok": false, "error": error.localizedDescription, "action_sent": false, "safe_to_retry": true] }
        }
        guard HIDService.inputs.contains(action) else {
            return ["ok": false, "error": "Unsupported hid action: \(action)", "action_sent": false]
        }
        return await exclusive(action) { [self] in try await deliver(action, args) }
    }

    private func exclusive(_ action: String,
                           _ body: @escaping @MainActor () async throws -> [String: Any]) async -> [String: Any] {
        guard !busy, !testingLink, !calibrator.busy, !calibrator.boardOpen else {
            return ["ok": false, "error": "Board is busy; stop it before starting another action", "action_sent": false]
        }
        busy = true
        actionBaseline = nil
        onActivity?(action)
        let operation = Task { try await body() }
        active = operation
        defer { active = nil; busy = false; inputGeneration = nil; pointerAction = false }
        do {
            let result = try await operation.value
            onActivity?("completed")
            lastError = ""
            return result
        }
        catch {
            let message = error is CancellationError ? "Operation stopped" : error.localizedDescription
            lastError = error is CancellationError ? "" : message
            let sent = actionBaseline.map { input.revision != $0 } ?? false
            if sent { input.invalidatePointer() }
            var result: [String: Any] = ["ok": false, "error": message, "action_sent": sent, "safe_to_retry": !sent]
            if let failure = error as? ScreenObservation.Failure { result["error_code"] = failure.rawValue }
            return result
        }
    }

    private func deliver(_ action: String, _ args: [String: Any]) async throws -> [String: Any] {
        let checkStarted = ProcessInfo.processInfo.systemUptime
        let expectedFrameID = try ScreenObservation.requestedID(args["frame_id"])
        var result: [String: Any] = ["ok": true]
        pointerAction = action != "type" && action != "key"
        if let expectedFrameID {
            let generation = screen.generation
            try requireReady(movement: pointerAction, generation: generation)
            inputGeneration = generation
            if let target = HIDService.target(args) {
                let current = try await screen.currentFrame()
                try requireReady(movement: pointerAction, generation: generation)
                guard screen.source.freshness() == .current else { throw ScreenObservation.Failure.frameChanged }
                if try screen.require(expectedFrameID, current: current, target: target) {
                    result["page_changed_since_observation"] = true
                }
                if screen.targetMasked(target, on: expectedFrameID) {
                    result["target_check"] = "pointer_masked: target centre was excluded from image comparison"
                }
            } else {
                try screen.requireKnown(expectedFrameID)
            }
        } else {
            try requireReady(movement: pointerAction)
        }
        let baseline = input.revision
        actionBaseline = baseline
        let settle = HIDService.settleTime(action, args)
        let inputStarted = ProcessInfo.processInfo.systemUptime
        do {
            try await hid.perform(action, args)
            try Task.checkCancellation()
        } catch {
            if input.revision != baseline { unsettled = (ProcessInfo.processInfo.systemUptime, settle) }
            throw error
        }
        let sent = ProcessInfo.processInfo.systemUptime
        unsettled = (sent, settle)
        result["action_sent"] = true
        result["sent_at"] = sent
        result["revision"] = input.revision
        result["timing_ms"] = ["preflight": Int((inputStarted - checkStarted) * 1000),
                               "input": Int((sent - inputStarted) * 1000)]
        return result
    }
}
