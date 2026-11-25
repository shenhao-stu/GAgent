import Darwin
import Foundation

struct ReplayCaptureStatus {
    let sessionID: String
    let active: Bool
    let diagnostics: ReplayWire.Diagnostics?
}
struct ReplayCaptureFrame {
    let jpeg: Data
    let uptime: Double
    let width, height: Int
    let sessionID: String
    let sequence: UInt64
}

/// Has no listener and keeps no ready bit: each ping challenges the running extension.
struct ReplayCaptureClient {
    let resolveEndpoint: () throws -> ReplayWire.Endpoint
    init(resolveEndpoint: @escaping () throws -> ReplayWire.Endpoint = ReplayWire.endpoint) {
        self.resolveEndpoint = resolveEndpoint
    }
    /// keep: seconds the extension keeps the newest sample as a picture from now on (ReplayWire.Request.keep).
    func status(keep: Double? = nil) async throws -> ReplayCaptureStatus {
        let (reply, _) = try await exchange(frame: false, after: nil, session: nil, keep: keep)
        return ReplayCaptureStatus(sessionID: reply.session, active: reply.active, diagnostics: reply.diagnostics)
    }
    func snapshot(afterUptime: Double?, expectedSession: String? = nil,
                  stimulus: (@MainActor () async throws -> Void)? = nil) async throws -> ReplayCaptureFrame {
        let (reply, bytes) = try await exchange(frame: true, after: afterUptime, session: expectedSession, stimulus: stimulus)
        guard reply.active, let t = reply.uptime, t.isFinite, let w = reply.width, w > 0,
              let h = reply.height, h > 0, let sequence = reply.sequence, bytes.starts(with: [0xff, 0xd8]),
              expectedSession == nil || expectedSession == reply.session,
              t >= (afterUptime ?? 0), ReplayWire.now - t < 2, t <= ReplayWire.now else { throw ReplayWire.Fault.noFrame }
        return ReplayCaptureFrame(jpeg: bytes, uptime: t, width: w, height: h, sessionID: reply.session, sequence: sequence)
    }
    private func exchange(frame: Bool, after: Double?, session: String?, keep: Double? = nil,
                          stimulus: (@MainActor () async throws -> Void)? = nil) async throws -> (ReplayWire.Reply, Data) {
        try Task.checkCancellation()
        let worker = Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            let ep = try resolveEndpoint()
            let deadline = ReplayWire.now + (frame ? 3.5 : 0.75)
            let fd = try ReplaySocket.connect(ep, deadline: deadline)
            defer { Darwin.close(fd) }
            let req = ReplayWire.Request(id: UUID(), frame: frame, after: after, session: session, keep: keep)
            let request = try ReplayWire.seal(JSONEncoder().encode(req), key: ep.key, reply: false)
            try ReplaySocket.send(fd, body: request, deadline: deadline)
            try Task.checkCancellation()
            try await stimulus?()
            let packet = try ReplaySocket.receive(fd, limit: ReplayWire.maxBody, deadline: deadline)
            let (reply, data) = try ReplayWire.unpack(ReplayWire.open(packet, key: ep.key, reply: true))
            guard reply.id == req.id else { throw ReplayWire.Fault.denied }
            if let error = reply.error { throw ReplayWire.Fault(rawValue: error) ?? .malformed }
            return (reply, data)
        }
        let result = try await withTaskCancellationHandler {
            try await worker.value
        } onCancel: { worker.cancel() }
        try Task.checkCancellation()
        return result
    }
}
