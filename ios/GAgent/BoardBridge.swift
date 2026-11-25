import Foundation

private final class BoardReplyBox: @unchecked Sendable {
    let signal = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var reply = "{\"ok\":false,\"error\":\"Board request timed out\"}"
    func complete(_ result: [String: Any]) {
        let data = (try? JSONSerialization.data(withJSONObject: result)) ?? Data()
        lock.lock()
        reply = String(data: data, encoding: .utf8) ?? "{\"ok\":false,\"error\":\"Invalid board reply\"}"
        lock.unlock()
        signal.signal()
    }
    func value() -> String { lock.lock(); defer { lock.unlock() }; return reply }
}

/// Called from CPython with the GIL released. The caller owns (and frees) the returned C string.
@_cdecl("ga_board_call")
func ga_board_call(_ input: UnsafePointer<CChar>?) -> UnsafeMutablePointer<CChar>? {
    guard !Thread.isMainThread else {
        return strdup("{\"ok\":false,\"error\":\"Board calls must run on the Python worker thread\"}")
    }
    guard let input, let data = String(cString: input).data(using: .utf8),
          let request = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return strdup("{\"ok\":false,\"error\":\"Expected a JSON object\"}")
    }
    // Stopping must answer quickly and is never abandoned: it is the request that makes the phone safe.
    let stopping = request["tool"] as? String == "hid"
        && (request["args"] as? [String: Any])?["action"] as? String == "stop"
    let box = BoardReplyBox()
    let task = Task { @MainActor in box.complete(await BoardSession.shared.tool(request)) }
    if box.signal.wait(timeout: .now() + (stopping ? 2 : 120)) == .timedOut {
        if stopping {
            return strdup("{\"ok\":false,\"stop_pending\":true,\"error\":\"Stop is queued on the device; acknowledgement timed out\"}")
        }
        task.cancel()
        Task { @MainActor in BoardSession.shared.stop() }
        return strdup("{\"ok\":false,\"error\":\"Board request timed out; stop requested; do not repeat the action until checking device status\"}")
    }
    return strdup(box.value())
}
