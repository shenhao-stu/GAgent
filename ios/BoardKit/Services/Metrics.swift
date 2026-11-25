import Foundation

/// Live numbers for the Diagnostics page; a snapshot goes into every trace (metrics.json).
@MainActor final class Metrics: ObservableObject {
    struct Step: Codable { var frameMs = 0.0, llmMs = 0.0, hidMs = 0.0 }

    // board, from status
    @Published var board: BoardStatus?
    @Published var statusAge = 0.0  // s since the last status notify
    // BLE, measured in the app
    @Published var bleKbps = 0.0
    @Published var videoKbps = 0.0
    @Published var mtu = 0
    @Published var drops = 0
    @Published var benchKbps: Double?
    // video
    @Published var fps = 0.0
    @Published var idrIntervalMs: Double?
    @Published var snapMs: Double?
    @Published var decodeMs = 0.0
    @Published var decodeErrors = 0
    @Published var backgroundDecodeErrors = 0
    @Published var videoDisconnects = 0
    @Published var sourceStalls = 0  // pointer nudges that produced no frame
    private(set) var probeDelays: [Double] = []  // s from a pointer nudge to its frame, latest 200

    func probeDelay(_ seconds: Double) { probeDelays = Array((probeDelays + [seconds]).suffix(200)) }

    private func percentile(_ values: [Double], _ p: Double) -> Double? {
        let sorted = values.sorted()
        return sorted.isEmpty ? nil : sorted[min(sorted.count - 1, Int(Double(sorted.count) * p))]
    }
    // agent
    @Published var steps: [Step] = []
    @Published var llmFirstMs: Double?
    @Published var llmTotalMs: Double?
    @Published var llmPingMs: Double?
    @Published var hidMs: [String: Double] = [:]  // last round trip per command
    // background
    @Published var backgroundSince: Double?
    @Published var backgroundAlive = 0.0  // s alive in background (current or last stint)
    @Published var suspensions = 0

    private var windowBytes = 0, windowBLEBytes = 0, windowFrames = 0
    private var windowStart = now()
    private var lastIDR: Double?
    private var lastTick = now()
    private var lastStatus: Double?

    func status(_ s: BoardStatus) {
        board = s
        mtu = s.ble?.vmtu ?? s.ble?.mtu ?? 0
        lastStatus = now()
    }

    func videoBytes(_ n: Int, wifi: Bool = false) { windowBytes += n; if !wifi { windowBLEBytes += n } }
    func videoDrops(_ n: Int) { drops += n }
    func frameDecoded(ms: Double) {
        windowFrames += 1
        decodeMs = ms
    }
    func decodeError(background: Bool) {
        decodeErrors += 1
        if background { backgroundDecodeErrors += 1 }
    }
    func idrSeen() {
        let t = now()
        if let lastIDR { idrIntervalMs = (t - lastIDR) * 1000 }
        lastIDR = t
    }
    func snapLatency(_ ms: Double) { snapMs = ms }
    func llm(first: Double?, total: Double) {
        llmFirstMs = first.map { $0 * 1000 }
        llmTotalMs = total * 1000
    }
    func step(_ s: Step) {
        steps = Array((steps + [s]).suffix(40))
        DebugLog.write(String(format: "step %d timing: frame %.0f ms, LLM %.0f ms, HID %.0f ms", steps.count, s.frameMs,
                              s.llmMs, s.hidMs))
    }

    /// Called every second by a timer; also detects suspension (a gap far longer than the tick).
    func tick() {
        let t = now()
        if t - lastTick > 5 { suspensions += 1 }
        lastTick = t
        let span = max(t - windowStart, 0.001)
        bleKbps = Double(windowBLEBytes) * 8 / 1000 / span
        videoKbps = Double(windowBytes) * 8 / 1000 / span
        fps = Double(windowFrames) / span
        windowBytes = 0; windowBLEBytes = 0; windowFrames = 0; windowStart = t
        statusAge = lastStatus.map { t - $0 } ?? 0
        if let since = backgroundSince { backgroundAlive = t - since }
    }

    func enteredBackground() { backgroundSince = now(); backgroundAlive = 0 }
    func enteredForeground() { backgroundSince = nil }

    /// Everything as JSON-ready values, for metrics.json.
    func snapshot() -> [String: Any] {
        var out: [String: Any] = [
            "ble_kbps_app": bleKbps, "video_kbps_app": videoKbps, "mtu": mtu, "drops": drops, "fps": fps, "decode_ms": decodeMs,
            "decode_errors": decodeErrors, "background_decode_errors": backgroundDecodeErrors,
            "video_disconnects": videoDisconnects, "source_stalls": sourceStalls,
            "background_alive_s": backgroundAlive, "suspensions": suspensions, "hid_ms": hidMs,
            "steps": steps.map { ["frame_ms": $0.frameMs, "llm_ms": $0.llmMs, "hid_ms": $0.hidMs] },
        ]
        out["bench_kbps"] = benchKbps
        out["probes"] = probeDelays.count
        out["probe_delay_p50_s"] = percentile(probeDelays, 0.5)
        out["probe_delay_p95_s"] = percentile(probeDelays, 0.95)
        out["idr_interval_ms"] = idrIntervalMs
        out["snap_ms"] = snapMs
        out["llm_first_ms"] = llmFirstMs
        out["llm_total_ms"] = llmTotalMs
        if let board, let data = try? JSONEncoder().encode(board) {
            out["board"] = try? JSONSerialization.jsonObject(with: data)
        }
        return out
    }
}
