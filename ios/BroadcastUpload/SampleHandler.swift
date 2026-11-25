import CoreImage
import CoreMedia
import CryptoKit
import Darwin
import Foundation
import ImageIO
import ReplayKit

/// System picker approval starts this process; the app cannot start it on its own.
final class SampleHandler: RPBroadcastSampleHandler {
    private let frames = RequestedFrames()
    private var server: ReplayServer?

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        frames.activate()
        do { server = try ReplayServer(frames: frames) }
        catch { frames.invalidate(); finishBroadcastWithError(error) }
    }
    override func broadcastPaused() { frames.invalidate(); server?.interruptReaders() }
    override func broadcastResumed() { frames.activate() }
    override func broadcastFinished() {
        frames.invalidate()
        server?.stop()
        server = nil
    }
    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with sampleBufferType: RPSampleBufferType) {
        guard sampleBufferType == .video else { return }
        frames.observe(sampleBuffer)
    }
}

final class RequestedFrames {
    private struct Image {
        let data: Data
        let width, height: Int
        let uptime: Double
        let sequence: UInt64
    }
    /// Seconds one request may keep pictures coming without a frame request: encoding every sample costs power.
    private static let longestKeep = 3.0
    private let condition = NSCondition()
    private lazy var jpeg = CIContext(options: [.useSoftwareRenderer: true, .cacheIntermediates: false])
    private var session = UUID().uuidString
    private var active = false
    private var sequence: UInt64 = 0
    private var pending: [UUID: Double] = [:]
    private var captureUntil = 0.0
    private var last: Image?
    private var note: ReplayWire.Fault?
    private var diagnostics = ReplayWire.Diagnostics()
    private var motion = ScreenMotion()

    func activate() { change(active: true) }
    func invalidate() { change(active: false) }
    private func change(active: Bool) {
        condition.lock(); defer { condition.unlock() }
        self.active = active
        session = UUID().uuidString; sequence = 0; last = nil; note = nil; pending.removeAll()
        captureUntil = 0
        diagnostics = ReplayWire.Diagnostics()
        motion = ScreenMotion()
        condition.broadcast()
    }

    func answer(_ req: ReplayWire.Request) throws -> Data {
        condition.lock(); defer { condition.unlock() }
        let id = session
        var reply = ReplayWire.Reply(id: req.id, session: id, active: active)
        if active, let keep = req.keep, keep.isFinite, keep > 0 {
            if ReplayWire.now >= captureUntil {
                motion = ScreenMotion()
                diagnostics.contentUptime = nil
                diagnostics.changedFraction = nil
            }
            captureUntil = max(captureUntil, ReplayWire.now + min(keep, Self.longestKeep))
        }
        reply.diagnostics = diagnostics
        guard req.frame else { return try ReplayWire.pack(reply) }
        guard active, req.session == nil || req.session == id else {
            reply.error = (active ? ReplayWire.Fault.changed : .paused).rawValue
            return try ReplayWire.pack(reply)
        }
        let boundary = req.after ?? 0
        guard boundary.isFinite && boundary >= 0 && boundary <= ReplayWire.now else { throw ReplayWire.Fault.noFrame }
        pending[req.id] = boundary
        captureUntil = ReplayWire.now + 2
        defer { pending.removeValue(forKey: req.id) }
        let until = ReplayWire.now + 2.7
        while active && session == id {
            if let f = last, f.sequence == sequence, f.uptime >= boundary, ReplayWire.now - f.uptime <= 1 {
                reply.uptime = f.uptime; reply.width = f.width; reply.height = f.height; reply.sequence = f.sequence
                return try ReplayWire.pack(reply, jpeg: f.data)
            }
            let remaining = until - ReplayWire.now
            guard remaining > 0 else { break }
            _ = condition.wait(until: Date(timeIntervalSinceNow: remaining))
        }
        diagnostics.timeouts &+= 1
        reply.diagnostics = diagnostics
        reply.active = active
        reply.error = (session != id ? ReplayWire.Fault.changed : note ?? .noFrame).rawValue
        return try ReplayWire.pack(reply)
    }

    // ReplayKit's sample belongs to this callback. Never retain it (or a CIImage referring to it).
    // Convert only on demand, after mapping its capture timestamp onto this boot's monotonic clock.
    func observe(_ sample: CMSampleBuffer) {
        guard CMSampleBufferIsValid(sample), CMSampleBufferDataIsReady(sample) else { return }
        let age = CMClockGetTime(CMClockGetHostTimeClock()).seconds - CMSampleBufferGetPresentationTimeStamp(sample).seconds
        let time = ReplayWire.now - max(0, age)
        condition.lock()
        sequence &+= 1
        diagnostics.samples = sequence
        diagnostics.callbackUptime = ReplayWire.now
        if age.isFinite { diagnostics.sampleUptime = time }
        let n = sequence, id = session
        // Keep only the latest JPEG briefly after a request, so a gesture's final frame is not lost
        // between requests. No input request means no encoding after this bounded burst expires.
        guard active, !pending.isEmpty || ReplayWire.now < captureUntil else { condition.unlock(); return }
        let earliest = pending.values.min() ?? 0
        condition.unlock()

        guard age.isFinite && age >= -0.05 && age <= 1 else { record(.invalidClock, for: id); return }
        guard time >= earliest, let pixel = CMSampleBufferGetImageBuffer(sample) else { return }
        let orientation = (CMGetAttachment(sample, key: RPVideoSampleOrientationKey as CFString,
                                           attachmentModeOut: nil) as? NSNumber)?.int32Value ?? 1
        guard (1...8).contains(orientation) else { record(.encoding, for: id); return }
        autoreleasepool {
            var image = CIImage(cvPixelBuffer: pixel).oriented(forExifOrientation: orientation)
            let size = image.extent.size
            let scale = min(1, 1600 / max(size.width, size.height))
            image = image.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            guard let space = CGColorSpace(name: CGColorSpace.sRGB),
                  let data = jpeg.jpegRepresentation(of: image, colorSpace: space,
                      options: [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): 0.70]),
                  data.count + 8192 < ReplayWire.maxBody else { record(.encoding, for: id); return }
            let thumbHeight = 96, thumbWidth = max(1, Int(96 * size.width / size.height))
            let thumbnail = image.transformed(by: CGAffineTransform(translationX: -image.extent.minX, y: -image.extent.minY))
                .transformed(by: CGAffineTransform(scaleX: Double(thumbWidth) / image.extent.width,
                                                   y: Double(thumbHeight) / image.extent.height))
            var pixels = [UInt8](repeating: 0, count: thumbWidth * thumbHeight * 4)
            pixels.withUnsafeMutableBytes { bytes in
                jpeg.render(thumbnail, toBitmap: bytes.baseAddress!, rowBytes: thumbWidth * 4,
                            bounds: CGRect(x: 0, y: 0, width: thumbWidth, height: thumbHeight),
                            format: .RGBA8, colorSpace: space)
            }
            condition.lock(); defer { condition.unlock() }
            guard active, session == id, sequence == n else { return }
            motion.observe(pixels, width: thumbWidth, height: thumbHeight, at: time)
            diagnostics.contentUptime = motion.changedAt
            diagnostics.changedFraction = motion.changedFraction
            let extent = image.extent.integral
            last = Image(data: data, width: Int(extent.width), height: Int(extent.height), uptime: time, sequence: n)
            diagnostics.encodedSequence = n
            note = nil; condition.broadcast()
        }
    }
    private func record(_ error: ReplayWire.Fault, for id: String) {
        condition.lock(); defer { condition.unlock() }
        if session == id {
            if error == .invalidClock { diagnostics.clockRejected &+= 1 }
            note = error; condition.broadcast()
        }
    }
}

final class ReplayServer {
    private let queue = DispatchQueue(label: "ga.broadcast.listener")
    private let workers = DispatchQueue(label: "ga.broadcast.exchange", attributes: .concurrent)
    private var peers = Set<Int32>() // solely on queue
    private var stopped = false
    private let listener: DispatchSourceRead
    private let frames: RequestedFrames
    private let key: Data

    init(frames: RequestedFrames, publish: (ReplayWire.Endpoint) throws -> Void = ReplayWire.publish) throws {
        self.frames = frames
        self.key = SymmetricKey(size: .bits256).withUnsafeBytes { Data($0) }
        let socket = try ReplaySocket.create()
        do {
            guard ReplaySocket.withAddress(0, { Darwin.bind(socket, $0, $1) }) == 0, Darwin.listen(socket, 4) == 0 else {
                throw ReplayWire.Fault.notSharing
            }
            var addr = sockaddr_in(), len = socklen_t(MemoryLayout<sockaddr_in>.size)
            let rc = withUnsafeMutablePointer(to: &addr) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socket, $0, &len) }
            }
            guard rc == 0 else { throw ReplayWire.Fault.notSharing }
            try publish(.init(port: UInt16(bigEndian: addr.sin_port), key: key))
        } catch { Darwin.close(socket); throw error }
        listener = DispatchSource.makeReadSource(fileDescriptor: socket, queue: queue)
        listener.setCancelHandler { Darwin.close(socket) }
        listener.setEventHandler { [weak self] in self?.accept(socket) }
        listener.resume()
    }

    private func accept(_ listenerFD: Int32) {
        guard !stopped else { return }
        while true {
            let fd = Darwin.accept(listenerFD, nil, nil)
            guard fd >= 0 else { return }
            var one: Int32 = 1
            guard peers.count < 4, fcntl(fd, F_SETFL, O_NONBLOCK) == 0,
                  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout<Int32>.size)) == 0 else {
                Darwin.close(fd); continue
            }
            peers.insert(fd)
            workers.async { [self] in
                defer { queue.sync { _ = peers.remove(fd); Darwin.close(fd) } }
                do {
                    let bytes = try ReplaySocket.receive(fd, limit: 4096, deadline: ReplayWire.now + 0.75)
                    let req = try JSONDecoder().decode(ReplayWire.Request.self, from: ReplayWire.open(bytes, key: key, reply: false))
                    let response = try ReplayWire.seal(frames.answer(req), key: key, reply: true)
                    try ReplaySocket.send(fd, body: response, deadline: ReplayWire.now + 0.75)
                } catch { return } // No unsigned error or image is sent.
            }
        }
    }

    func interruptReaders() { queue.sync { for fd in peers { Darwin.shutdown(fd, SHUT_RDWR) } } }
    func stop() {
        queue.sync {
            stopped = true
            for fd in peers { Darwin.shutdown(fd, SHUT_RDWR) }
            listener.cancel()
        }
    }
}
