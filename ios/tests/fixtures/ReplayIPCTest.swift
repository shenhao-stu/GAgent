import Foundation
import CoreMedia
import CoreVideo
import ReplayKit

@main enum WireTest {
    struct Failed: Error { let message: String }
    static func check(_ ok: Bool, _ msg: String) throws { guard ok else { throw Failed(message: msg) } }

    static func sample(age: Double = 0, orientation: Int = 6) throws -> CMSampleBuffer {
        let attrs = [kCVPixelBufferIOSurfacePropertiesKey: [:] as [String: Any]] as CFDictionary
        var pixel: CVPixelBuffer?
        let rc = CVPixelBufferCreate(kCFAllocatorDefault, 160, 90, kCVPixelFormatType_32BGRA, attrs, &pixel)
        guard rc == kCVReturnSuccess, let pixel else { throw Failed(message: "buffer") }
        CVPixelBufferLockBaseAddress(pixel, [])
        memset(CVPixelBufferGetBaseAddress(pixel), 0xff, CVPixelBufferGetDataSize(pixel))
        CVPixelBufferUnlockBaseAddress(pixel, [])
        var format: CMVideoFormatDescription?, buffer: CMSampleBuffer?
        guard CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: pixel,
                formatDescriptionOut: &format) == noErr, let format else { throw Failed(message: "format") }
        let pts = CMClockGetTime(CMClockGetHostTimeClock()) - CMTime(seconds: age, preferredTimescale: 1_000_000)
        var timing = CMSampleTimingInfo(duration: .invalid, presentationTimeStamp: pts, decodeTimeStamp: .invalid)
        guard CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: pixel,
                formatDescription: format, sampleTiming: &timing, sampleBufferOut: &buffer) == noErr,
              let buffer else { throw Failed(message: "sample") }
        CMSetAttachment(buffer, key: RPVideoSampleOrientationKey as CFString, value: NSNumber(value: orientation),
                        attachmentMode: kCMAttachmentMode_ShouldPropagate)
        return buffer
    }

    @MainActor static func motionChecks() async throws {
        var motion = ScreenMotion()
        let white = [UInt8](repeating: 255, count: 48 * 96 * 4)
        motion.observe(white, width: 48, height: 96, at: 10)
        var cursor = white
        for p in 0..<20 { cursor[p * 4] = 0; cursor[p * 4 + 1] = 0; cursor[p * 4 + 2] = 0 }
        motion.observe(cursor, width: 48, height: 96, at: 10.2)
        try check(motion.changedAt == 10, "local cursor animation must not reset rest")
        for level in stride(from: 250, through: 225, by: -5) {
            motion.observe([UInt8](repeating: UInt8(level), count: white.count), width: 48, height: 96, at: 10.4)
        }
        try check(motion.changedAt == 10.4, "slow cumulative fade must reset rest")
        motion.observe(white, width: 96, height: 48, at: 10.5)
        try check(motion.changedAt == 10.5, "orientation change must reset rest")
        var clock = 10.0
        await ScreenRest.wait(from: clock, now: { clock }, newestSample: { 10 }, sleep: { clock += $0 })
        let contentWait = clock - 10
        clock = 10
        await ScreenRest.wait(from: clock, now: { clock }, newestSample: { clock }, sleep: { clock += $0 })
        try check(contentWait < 0.31 && clock - 10 >= 1, "continuous callback baseline vs stable content")
        print(String(format: "PASS content wait %.3f s vs sample-only %.3f s (virtual clock)", contentWait, clock - 10))
    }

    static func main() async throws {
        try await motionChecks()
        let frames = RequestedFrames(); frames.activate()
        var endpoint: ReplayWire.Endpoint?
        let server = try ReplayServer(frames: frames) { endpoint = $0 }
        guard let ep = endpoint else { throw Failed(message: "endpoint") }
        let client = ReplayCaptureClient { ep }
        let initial = try await client.status()
        try check(initial.active, "live session")
        let wrong = ReplayCaptureClient { ReplayWire.Endpoint(port: ep.port, key: Data(repeating: 0, count: 32)) }
        do { _ = try await wrong.status(); throw Failed(message: "untrusted client received a reply") }
        catch is ReplayWire.Fault { }
        let payload = try ReplayWire.seal(Data("request".utf8), key: ep.key, reply: false)
        do { _ = try ReplayWire.open(payload, key: ep.key, reply: true); throw Failed(message: "reflection") }
        catch is ReplayWire.Fault { }
        frames.observe(try sample())
        let idle = try await client.status()
        try check(idle.diagnostics?.samples == 1 && idle.diagnostics?.encodedSequence == nil, "idle sample observed without encoding")
        let after = ReplayWire.now
        async let picture = client.snapshot(afterUptime: after, expectedSession: initial.sessionID)
        try await Task.sleep(nanoseconds: 120_000_000)
        frames.observe(try sample(age: 5))
        frames.observe(try sample())
        let correct = try await picture
        try check(correct.uptime >= after && correct.width == 90 && correct.height == 160, "PTS/rotation")
        try check(correct.jpeg.starts(with: [0xff, 0xd8]), "real JPEG")
        let finalMovement = ReplayWire.now
        frames.observe(try sample()) // The move finished before the next request could be registered.
        let cached = try await client.snapshot(afterUptime: finalMovement, expectedSession: initial.sessionID)
        try check(cached.sequence == 4, "short capture burst must preserve the final movement frame")
        async let expired = client.snapshot(afterUptime: ReplayWire.now, expectedSession: initial.sessionID)
        try await Task.sleep(nanoseconds: 120_000_000)
        frames.observe(try sample(age: 9))
        do { _ = try await expired; throw Failed(message: "old frame accepted") }
        catch ReplayWire.Fault.invalidClock { }
        let timeout = try await client.status()
        try check(timeout.diagnostics?.samples == 5 && timeout.diagnostics?.clockRejected == 2
                  && timeout.diagnostics?.timeouts == 1 && timeout.diagnostics?.encodedSequence == 4, "capture timing diagnostics")
        frames.observe(try sample())
        let idleAgain = try await client.status()
        try check(idleAgain.diagnostics?.encodedSequence == 4, "capture burst must expire without more requests")
        // An input left: a status request has the extension keep what follows, and the picture the screen comes
        // to rest on is handed over at once, though no frame request was waiting when it was sampled.
        let input = ReplayWire.now
        _ = try await client.status(keep: 1)
        frames.observe(try sample())
        let rested = try await client.status()
        try check(rested.diagnostics?.samples == 7 && rested.diagnostics?.encodedSequence == 7, "a kept sample is encoded")
        let asked = ReplayWire.now
        let kept = try await client.snapshot(afterUptime: input, expectedSession: initial.sessionID)
        try check(kept.sequence == 7 && ReplayWire.now - asked < 0.5, "the kept picture is handed over at once")
        // Repeated identical callbacks are not a moving page. This is the old 1 s timeout path.
        let contentStart = try await client.status()
        for _ in 0..<8 {
            try await Task.sleep(nanoseconds: 50_000_000)
            frames.observe(try sample())
        }
        let steady = try await client.status()
        try check(steady.diagnostics?.contentUptime != nil
                  && steady.diagnostics?.contentUptime == contentStart.diagnostics?.contentUptime,
                  "identical samples must keep the content clock still")
        try check(ReplayWire.now - (steady.diagnostics?.sampleUptime ?? 0) < 0.1,
                  "content clock must not replace the real sample freshness clock")
        frames.invalidate(); server.interruptReaders()
        let paused = try await client.status()
        try check(!paused.active && paused.sessionID != initial.sessionID, "stop/epoch")
        try check(paused.diagnostics?.samples == 0, "stop clears diagnostics")
        do { _ = try await client.snapshot(afterUptime: nil); throw Failed(message:"paused accepted") }
        catch ReplayWire.Fault.paused { }
        frames.activate()
        do { _ = try await client.snapshot(afterUptime: nil, expectedSession: initial.sessionID); throw Failed(message:"resumed stale session") }
        catch ReplayWire.Fault.changed { }
        let resumed = try await client.status()
        let boundary = ReplayWire.now
        // Static source: no periodic producer. Only the bounded stimulus emits a new sample.
        let refreshed = try await client.snapshot(afterUptime: boundary, expectedSession: resumed.sessionID) {
            try await Task.sleep(nanoseconds: 100_000_000)
            frames.observe(try sample())
        }
        try check(refreshed.uptime >= boundary, "stimulated screenshot must cross the real boundary")
        let cancelled = Task {
            try await client.snapshot(afterUptime: ReplayWire.now, expectedSession: resumed.sessionID) {
                try await Task.sleep(nanoseconds: 500_000_000)
                frames.observe(try sample())
            }
        }
        try await Task.sleep(nanoseconds: 100_000_000)
        cancelled.cancel()
        do { _ = try await cancelled.value; throw Failed(message: "cancelled capture stimulated the source") }
        catch is CancellationError { }
        let afterCancel = try await client.status()
        try check(afterCancel.diagnostics?.samples == 1, "cancelled capture cannot execute a late stimulus")
        frames.invalidate(); server.stop()
        do { _ = try await client.status(); throw Failed(message:"dead process accepted") }
        catch is ReplayWire.Fault { }
        print("PASS live encrypted loopback, wrong key, direction, PTS boundary, rotated JPEG, kept picture, paused/restarted/dead session")
    }
}
