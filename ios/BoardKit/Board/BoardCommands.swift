import Foundation

/// The board did not answer in time; the link is still up (a disconnect throws DeviceError instead).
struct BoardTimeout: LocalizedError {
    let command: String
    let seconds: Double
    var errorDescription: String? { String(format: "the board did not answer '%@' within %.0f s", command, seconds) }
}

struct DeviceError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Where command lines go: the BLE link, or a fake board in tests.
@MainActor protocol BoardTransport: AnyObject {
    var isConnected: Bool { get }
    func write(_ line: String) throws
    /// Fire-and-forget: write only if the link can take it right now; false = dropped.
    func writeIfIdle(_ line: String) -> Bool
    /// Bytes one write can carry without a response.
    var maxWrite: Int { get }
}

extension BoardTransport {
    func writeIfIdle(_ line: String) -> Bool { (try? write(line)) != nil }
    var maxWrite: Int { 180 }
}

/// What gestures need from the board (CommandChannel, or a fake in tests).
@MainActor protocol HIDDevice: AnyObject {
    var links: Int { get }
    var connected: Bool { get }
    @discardableResult func send(_ command: String) async throws -> String
    /// A pointer move that changes no page state (returning a probe nudge): it needs no observation of its own.
    @discardableResult func sendUnobserved(_ command: String) async throws -> String
    /// Pointer moves the board runs back to back; whatever relies on where they end is sent after this returns.
    func sendAll(_ commands: [String]) async throws
    func waitConnected(_ timeout: TimeInterval) async -> Bool
}

extension HIDDevice {
    @discardableResult func sendUnobserved(_ command: String) async throws -> String { try await send(command) }
    func sendAll(_ commands: [String]) async throws { for command in commands { try await send(command) } }
}

/// A FIFO async mutex for main-actor code.
@MainActor final class AsyncLock {
    private var busy = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func lock() async {
        if !busy { busy = true; return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func unlock() {
        if waiters.isEmpty { busy = false } else { waiters.removeFirst().resume() }
    }
}

/// Sends the board commands one at a time and matches replies by request id. Port of device.py.
@MainActor final class CommandChannel: HIDDevice {
    weak var transport: BoardTransport?
    /// Called inside the FIFO immediately before each physical write. A rejected command never advances a boundary.
    typealias WritePermit = @MainActor () throws -> Void
    var beforeWrite: ((String) async throws -> WritePermit)?
    private struct Refused: Error { let cause: Error }
    static let inputCommands: Set<String> = ["move", "flick", "home", "click", "press", "release", "type", "key", "homescreen", "scroll"]
    private(set) var actionRevision = 0
    private(set) var observationAfterUptime: Double?
    /// No heartbeat, stop, or reconnect can observe input; a decoded frame must cross this boundary.
    private(set) var observationAfter: Double?
    private(set) var links = 0  // bumped on every (re)connect, so gestures know to release and re-home
    private let lock = AsyncLock()
    /// The board serves two centrals (this app and a Mac harness) and notifies replies to both: start our ids
    /// far from the harness's small ones, and drop replies to ids we did not send.
    private var nextID = Int.random(in: 100_000...800_000)
    private var logTimes: [Double] = []
    /// "app <command>" lines relayed from the Mac harness.
    var onAppCommand: ((String) -> Void)?
    private var pending: [Int: CheckedContinuation<BoardReply, Error>] = [:]
    private var batches: [Int: Batch] = [:]
    /// Commands the firmware queues behind the one it runs (`cmdQueue` in ble_link.cpp).
    static let queued = 6
    private var last = 0.0, beat = 0.0
    var onTiming: ((String, Double) -> Void)?  // command name, ms

    init(transport: BoardTransport? = nil) { self.transport = transport }

    var connected: Bool { transport?.isConnected ?? false }

    /// The transport (re)connected and subscribed.
    func linkUp() {
        links += 1
        last = now(); beat = last  // fresh link: nothing to keep awake yet
    }

    /// The link dropped: fail everything in flight.
    func linkDown() {
        let waiting = pending, open = batches.values
        pending = [:]
        batches = [:]
        waiting.values.forEach { $0.resume(throwing: DeviceError(message: "board disconnected")) }
        open.forEach { $0.fail(DeviceError(message: "board disconnected")) }  // a batch fails once; later calls do nothing
    }

    func handleReply(_ line: String) {
        let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("app ") { return onAppCommand?(String(text.dropFirst(4))) ?? () }
        if text.hasPrefix("log ") { return }  // our own log lines, relayed to the harness
        guard let reply = BoardReply.parse(line) else { return }
        if let c = pending.removeValue(forKey: reply.id) { c.resume(returning: reply) }
        else { batches.removeValue(forKey: reply.id)?.receive(reply) }
    }

    func waitConnected(_ timeout: TimeInterval) async -> Bool {
        let deadline = now() + timeout
        while !connected && now() < deadline { try? await Task.sleep(nanoseconds: 200_000_000) }
        return connected
    }

    /// Seconds the board may take: replies need up to ~2 s at p99, moves are paced (10 units per 8 ms),
    /// typing is per character.
    nonisolated static func timeout(_ command: String) -> Double {
        let parts = command.split(separator: " ", maxSplits: 1).map(String.init)
        let name = parts.first ?? "", arg = parts.count > 1 ? parts[1] : ""
        switch name {
        case "move", "flick": return 5 + Double(arg.split(separator: " ").compactMap { Int($0) }.map(abs).max() ?? 0) / 10 * 0.012
        case "type": return 5 + 0.1 * Double(arg.count)
        case "ping": return 8  // an idle check: tolerate a hiccup rather than drop a healthy board
        case "snap": return 15  // a whole GOP over BLE
        case "bench": return 5 + (Double(arg) ?? 0) / 10  // KB at >= 80 kbps
        default: return 5
        }
    }

    /// Send one command; returns the text after "ok" (e.g. bench's ms). Throws DeviceError on err/timeout.
    @discardableResult
    func send(_ command: String) async throws -> String {
        try await send(command, timeout: nil)
    }

    @discardableResult
    func sendUnobserved(_ command: String) async throws -> String {
        try await send(command, timeout: nil, observed: false)
    }

    /// A timeout is the board being slow (e.g. a snap while it also streams), not a lost link: it throws
    /// BoardTimeout and keeps the connection; only a real CoreBluetooth disconnect fails as link lost.
    @discardableResult
    func send(_ command: String, timeout custom: Double?, observed: Bool = true) async throws -> String {
        try await transmit(command, timeout: custom, observed: observed)
    }

    /// A bounded, button-free stimulus. The caller must authorize the live sharing session inside the FIFO.
    @discardableResult func refreshPointer(by step: Int,
        authorize: @escaping @MainActor () async throws -> WritePermit) async throws -> String {
        guard step == 12 || step == -12 else { throw DeviceError(message: "Invalid screen refresh movement") }
        return try await transmit("move \(step) 0", timeout: nil, observed: false, authorize: authorize)
    }

    private func transmit(_ command: String, timeout custom: Double?, observed: Bool,
                          authorize: (@MainActor () async throws -> WritePermit)? = nil) async throws -> String {
        try Task.checkCancellation()
        guard connected, let transport else { throw DeviceError(message: "board not connected") }
        let timeout = custom ?? Self.timeout(command)
        let name = String(command.split(separator: " ").first ?? "")
        let link = links
        await lock.lock()
        defer { lock.unlock() }
        try Task.checkCancellation()
        let validate: WritePermit?
        if let authorize { validate = try await authorize() }
        else { validate = try await beforeWrite?(command) }
        try Task.checkCancellation()
        guard connected, links == link else { throw DeviceError(message: "board link changed before write") }
        let started = now()
        let id = nextID
        nextID += 1
        let reply: BoardReply
        do {
            reply = try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { (c: CheckedContinuation<BoardReply, Error>) in
                    do {
                        try Task.checkCancellation()
                        try validate?()
                    } catch {
                        c.resume(throwing: Refused(cause: error))
                        return
                    }
                    pending[id] = c
                    do {
                        try transport.write("\(id) \(command)")
                        if Self.inputCommands.contains(name) { recordInput(observed: observed) }
                    } catch {
                        pending[id] = nil
                        c.resume(throwing: error)
                        return
                    }
                    Task { @MainActor [weak self] in
                        try? await Task.sleep(nanoseconds: UInt64(timeout * 1e9))
                        self?.fail(id, DeviceError(message: "timeout"))
                    }
                }
            } onCancel: {
                Task { @MainActor [weak self] in self?.fail(id, CancellationError()) }
            }
        } catch let denied as Refused {
            throw denied.cause
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            let ms = (now() - started) * 1000
            if (error as? DeviceError)?.message == "timeout" {
                if name != "ping" { DebugLog.write(String(format: "cmd #%d %@ → timeout after %.0f ms", id, name, ms)) }
                throw BoardTimeout(command: name, seconds: timeout)
            }
            DebugLog.write(String(format: "cmd #%d %@ → link lost after %.0f ms: %@", id, name, ms,
                                  error.localizedDescription))
            throw DeviceError(message: "board link lost during '\(name)': \(error.localizedDescription)")
        }
        beat = now()  // last reply of any kind
        if command != "ping" {
            last = beat  // last real command: the phone's idle time
            onTiming?(String(command.split(separator: " ").first ?? ""), (now() - started) * 1000)
        }
        if name != "ping" {
            DebugLog.write(String(format: "cmd #%d %@ → %@ %@ (%.0f ms)", id, name,
                                  reply.ok ? "ok" : "err", reply.ok ? "ack" : "rejected", (now() - started) * 1000))
        }
        guard reply.ok else { throw DeviceError(message: "err " + reply.text) }
        if observed, Self.inputCommands.contains(name) {
            observationAfterUptime = ProcessInfo.processInfo.systemUptime
        }
        return reply.text
    }

    /// Several pointer moves the board runs back to back. All are written at once (the firmware queues them) and
    /// their replies awaited together, so the link's round trip is paid once rather than once per move: a tap's
    /// up to six moves took about 0.1 s each to be answered on a slow link (2026-11-13). One failing does not stop
    /// the board running the rest, so this is for moves alone; a press or click that relies on where they end is
    /// sent after this returns.
    func sendAll(_ commands: [String]) async throws {
        if commands.count > Self.queued {
            try await sendAll(Array(commands.prefix(Self.queued)))
            return try await sendAll(Array(commands.dropFirst(Self.queued)))
        }
        guard commands.count > 1 else { for command in commands { try await send(command) }; return }
        try Task.checkCancellation()
        guard connected, let transport else { throw DeviceError(message: "board not connected") }
        let link = links
        await lock.lock()
        defer { lock.unlock() }
        var permits: [WritePermit?] = []
        for command in commands {
            try Task.checkCancellation()
            permits.append(try await beforeWrite?(command))
        }
        try Task.checkCancellation()
        guard connected, links == link else { throw DeviceError(message: "board link changed before write") }
        let started = now(), ids = Array(nextID..<nextID + commands.count)
        nextID += commands.count
        let batch = Batch(ids)
        let timeout = commands.map(Self.timeout).reduce(0, +)
        let replies: [BoardReply]
        do {
            replies = try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { (c: CheckedContinuation<[BoardReply], Error>) in
                    batch.continuation = c
                    for (index, command) in commands.enumerated() {
                        do {
                            try Task.checkCancellation()
                            try permits[index]?()
                            batches[ids[index]] = batch
                            try transport.write("\(ids[index]) \(command)")
                        } catch {
                            // What was written is the board's to run; nothing after it is sent.
                            ids[index...].forEach { batches[$0] = nil }
                            batch.cut(ids[index...], index == 0 ? Refused(cause: error) : error)
                            break
                        }
                        if Self.inputCommands.contains(String(command.split(separator: " ").first ?? "")) { recordInput() }
                    }
                    Task { @MainActor [weak self] in
                        try? await Task.sleep(nanoseconds: UInt64(timeout * 1e9))
                        self?.fail(batch, DeviceError(message: "timeout"))
                    }
                }
            } onCancel: {
                Task { @MainActor [weak self] in self?.fail(batch, CancellationError()) }
            }
        } catch let denied as Refused {
            throw denied.cause
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            let ms = (now() - started) * 1000
            if (error as? DeviceError)?.message == "timeout" {
                DebugLog.write(String(format: "cmd #%d-%d moves → timeout after %.0f ms", ids[0], ids[ids.count - 1], ms))
                throw BoardTimeout(command: "move", seconds: timeout)
            }
            if error is DeviceError, error.localizedDescription == "board disconnected" {
                DebugLog.write(String(format: "cmd #%d-%d moves → link lost after %.0f ms", ids[0], ids[ids.count - 1], ms))
                throw DeviceError(message: "board link lost during 'move': board disconnected")
            }
            throw error
        }
        beat = now()
        last = beat
        onTiming?("moves", (now() - started) * 1000)
        let refused = replies.first { !$0.ok }
        DebugLog.write(String(format: "cmd #%d-%d %d moves → %@ (%.0f ms)", ids[0], ids[ids.count - 1], commands.count,
                              refused == nil ? "ok" : "err", (now() - started) * 1000))
        if let refused { throw DeviceError(message: "err " + refused.text) }
        observationAfterUptime = ProcessInfo.processInfo.systemUptime
    }

    private func fail(_ batch: Batch, _ error: Error) {
        for (id, owner) in batches where owner === batch { batches[id] = nil }
        batch.fail(error)
    }

    /// The replies of one `sendAll`, in the order the commands were written.
    private final class Batch {
        private var waiting: Set<Int>
        private var replies: [Int: BoardReply] = [:]
        private var error: Error?
        var continuation: CheckedContinuation<[BoardReply], Error>?

        init(_ ids: [Int]) { waiting = Set(ids) }

        func receive(_ reply: BoardReply) {
            guard waiting.remove(reply.id) != nil else { return }
            replies[reply.id] = reply
            finish()
        }

        /// These were never written: stop waiting for them, and end with `error` once the rest are in.
        func cut(_ ids: ArraySlice<Int>, _ error: Error) {
            waiting.subtract(ids)
            self.error = self.error ?? error
            finish()
        }

        func fail(_ error: Error) {
            continuation?.resume(throwing: error)
            continuation = nil
        }

        private func finish() {
            guard waiting.isEmpty, let continuation else { return }
            self.continuation = nil
            if let error { continuation.resume(throwing: error) }
            else { continuation.resume(returning: replies.keys.sorted().map { replies[$0]! }) }
        }
    }

    /// Relative to this process's monotonic clock, including a foreground URL-scheme action.
    func recordInput(observed: Bool = true) {
        actionRevision += 1
        if observed {
            observationAfter = max(observationAfter ?? 0, now())
            observationAfterUptime = ProcessInfo.processInfo.systemUptime
        }
    }

    /// Send a debug-log line to the Mac harness through the board (`log <text>`): fire-and-forget, at most
    /// 10 a second, truncated to one write, dropped when the link is busy.
    @discardableResult
    func relayLog(_ text: String) -> Bool {
        guard connected, let transport else { return false }
        let t = now()
        logTimes = logTimes.filter { t - $0 < 1 }
        guard logTimes.count < 10 else { return false }
        let prefix = "\(nextID) log "
        nextID += 1
        var body = text.replacingOccurrences(of: "\n", with: " ")
        while prefix.utf8.count + body.utf8.count > transport.maxWrite && !body.isEmpty { body.removeLast() }
        guard transport.writeIfIdle(prefix + body) else { return false }
        logTimes.append(t)
        return true
    }

    private func fail(_ id: Int, _ error: Error) {
        pending.removeValue(forKey: id)?.resume(throwing: error)
    }

    /// While idle: ping every few seconds, so a board that went away shows as gone within seconds, and nudge
    /// the pointer now and then so the phone does not auto-lock. Runs until cancelled.
    func keepAwake(idle: Double = 25, heartbeat: Double = 2, screenLive: @escaping () -> Bool) async {
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: UInt64(heartbeat * 1e9))
            if !connected || now() - beat < heartbeat { continue }
            do {
                // nudge only a phone that is awake and mirroring: there is nothing to keep awake otherwise
                if now() - last > idle && screenLive() {
                    try await send("move 1 0")
                    try await send("move -1 0")
                } else {
                    try await send("ping")
                }
            } catch {
                log("board gone: \(error.localizedDescription)")
            }
        }
    }

    var log: (String) -> Void = { print($0) }
}

func now() -> Double { Date().timeIntervalSince1970 }
