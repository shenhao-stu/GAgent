import CryptoKit
import Darwin
import Foundation
import Security

/// One short, authenticated exchange per check. The ephemeral port and session key are
/// discoverable only by these two signed targets through their private Keychain group.
enum ReplayWire {
    enum Fault: String, LocalizedError {
        case notSharing = "Screen broadcast is not running"
        case paused = "Screen broadcast is paused"
        case changed = "Screen broadcast session changed"
        case noFrame = "No fresh screen sample after the requested boundary"
        case invalidClock = "ReplayKit sample clock is not recent"
        case denied = "Screen broadcast authentication failed"
        case malformed = "Invalid screen broadcast response"
        case timeout = "Screen broadcast did not answer in time"
        case keychain = "Cannot access the shared broadcast Keychain"
        case encoding = "Unable to encode the screen sample"
        var errorDescription: String? { rawValue }
    }

    struct Endpoint: Codable {
        let port: UInt16
        let key: Data
    }
    struct Request: Codable {
        let id: UUID
        let frame: Bool
        let after: Double?
        let session: String?
        /// Seconds from now during which the newest sample is kept as a picture though no frame is asked for yet:
        /// the screen is expected to change (an input left), and the frame request comes once it rests.
        var keep: Double? = nil
    }
    struct Diagnostics: Codable {
        var samples: UInt64 = 0
        var callbackUptime: Double?
        var sampleUptime: Double?
        var encodedSequence: UInt64?
        var contentUptime: Double?
        var changedFraction: Double?
        var timeouts: UInt64 = 0
        var clockRejected: UInt64 = 0
    }
    struct Reply: Codable {
        let id: UUID
        let session: String
        var active: Bool
        var error: String?
        var uptime: Double?
        var width: Int?
        var height: Int?
        var sequence: UInt64?
        var diagnostics: Diagnostics?
    }

    static let maxBody = 3_000_000
    static var now: Double { ProcessInfo.processInfo.systemUptime }
    private static func query() throws -> [String: Any] {
        guard let group = Bundle.main.object(forInfoDictionaryKey: "GAReplayKeychainGroup") as? String,
              !group.isEmpty, !group.contains("$") else { throw Fault.keychain }
        return [kSecClass as String: kSecClassGenericPassword,
                kSecAttrAccessGroup as String: group,
                kSecAttrService as String: "gagent.replay.v1",
                kSecAttrAccount as String: "endpoint"]
    }
    static func publish(_ endpoint: Endpoint) throws {
        let query = try query()
        let values: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(endpoint),
                                     kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        var rc = SecItemUpdate(query as CFDictionary, values as CFDictionary)
        if rc == errSecItemNotFound {
            rc = SecItemAdd(query.merging(values) { _, v in v } as CFDictionary, nil)
        }
        guard rc == errSecSuccess else { throw Fault.keychain }
    }
    static func endpoint() throws -> Endpoint {
        var q = try query(); q[kSecReturnData as String] = true
        var item: CFTypeRef?
        let rc = SecItemCopyMatching(q as CFDictionary, &item)
        if rc == errSecItemNotFound { throw Fault.notSharing }
        guard rc == errSecSuccess, let item = item as? Data else { throw Fault.keychain }
        let result = try JSONDecoder().decode(Endpoint.self, from: item)
        guard result.port > 0, result.key.count == 32 else { throw Fault.denied }
        return result
    }
    static func seal(_ data: Data, key: Data, reply: Bool) throws -> Data {
        return try ChaChaPoly.seal(data, using: SymmetricKey(data: key),
                authenticating: Data((reply ? "GA/reply/1" : "GA/request/1").utf8)).combined
    }
    static func open(_ data: Data, key: Data, reply: Bool) throws -> Data {
        do {
            return try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: data), using: SymmetricKey(data: key),
                                       authenticating: Data((reply ? "GA/reply/1" : "GA/request/1").utf8))
        } catch { throw Fault.denied }
    }
    static func pack(_ reply: Reply, jpeg: Data = Data()) throws -> Data {
        let meta = try JSONEncoder().encode(reply)
        return prefix(meta.count) + meta + jpeg
    }
    static func unpack(_ bytes: Data) throws -> (Reply, Data) {
        guard bytes.count >= 4 else { throw Fault.malformed }
        let n = length(bytes.prefix(4))
        guard n > 0, n <= 4096, n <= bytes.count - 4 else { throw Fault.malformed }
        let meta = try JSONDecoder().decode(Reply.self, from: bytes.subdata(in: 4..<4+n))
        return (meta, bytes.subdata(in: 4+n..<bytes.count))
    }
    static func prefix(_ size: Int) -> Data {
        withUnsafeBytes(of: UInt32(size).bigEndian) { Data($0) }
    }
    static func length(_ bytes: Data) -> Int {
        bytes.reduce(0) { ($0 << 8) | Int($1) }
    }
}

/// Framed TCP over literal loopback. Deadlines cover the entire request, not each byte.
/// Each descriptor has exactly one owner; no SIGPIPE on stop, and no wildcard listener.
enum ReplaySocket {
    static func create() throws -> Int32 {
        let fd = Darwin.socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ReplayWire.Fault.notSharing }
        var one: Int32 = 1
        guard setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, socklen_t(MemoryLayout.size(ofValue: one))) == 0,
              fcntl(fd, F_SETFL, O_NONBLOCK) == 0 else { Darwin.close(fd); throw ReplayWire.Fault.notSharing }
        return fd
    }
    static func withAddress<T>(_ port: UInt16, _ f: (UnsafePointer<sockaddr>, socklen_t) -> T) -> T {
        var a = sockaddr_in()
        a.sin_len = UInt8(MemoryLayout<sockaddr_in>.size); a.sin_family = sa_family_t(AF_INET)
        a.sin_port = port.bigEndian; a.sin_addr.s_addr = inet_addr("127.0.0.1")
        return withUnsafePointer(to: &a) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { f($0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
    }
    static func wait(_ fd: Int32, _ events: Int16, _ deadline: Double) throws {
        while true {
            let ms = Int32(max(0, min(60_000, ceil((deadline - ReplayWire.now) * 1000))))
            guard ms > 0 else { throw ReplayWire.Fault.timeout }
            var p = pollfd(fd: fd, events: events, revents: 0)
            let rc = Darwin.poll(&p, 1, ms)
            if rc < 0 && errno == EINTR { continue }
            if rc == 0 { throw ReplayWire.Fault.timeout }
            guard rc > 0 && p.revents & events != 0 else { throw ReplayWire.Fault.notSharing }
            return
        }
    }
    static func connect(_ endpoint: ReplayWire.Endpoint, deadline: Double) throws -> Int32 {
        let fd = try create()
        do {
            let rc = withAddress(endpoint.port) { Darwin.connect(fd, $0, $1) }
            if rc != 0 {
                guard errno == EINPROGRESS else { throw ReplayWire.Fault.notSharing }
                try wait(fd, Int16(POLLOUT), deadline)
                var err: Int32 = 0, size = socklen_t(MemoryLayout<Int32>.size)
                guard getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &size) == 0, err == 0 else { throw ReplayWire.Fault.notSharing }
            }
            return fd
        } catch { Darwin.close(fd); throw error }
    }
    static func send(_ fd: Int32, body: Data, deadline: Double) throws {
        guard body.count > 0 && body.count <= ReplayWire.maxBody else { throw ReplayWire.Fault.malformed }
        let packet = ReplayWire.prefix(body.count) + body
        try packet.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                try wait(fd, Int16(POLLOUT), deadline)
                let n = Darwin.send(fd, raw.baseAddress!.advanced(by: offset), raw.count - offset, 0)
                if n < 0 && (errno == EAGAIN || errno == EINTR) { continue }
                guard n > 0 else { throw ReplayWire.Fault.notSharing }
                offset += n
            }
        }
    }
    static func receive(_ fd: Int32, limit: Int, deadline: Double) throws -> Data {
        func read(_ count: Int) throws -> Data {
            var data = Data(count: count)
            try data.withUnsafeMutableBytes { raw in
                var offset = 0
                while offset < count {
                    try wait(fd, Int16(POLLIN), deadline)
                    let n = Darwin.recv(fd, raw.baseAddress!.advanced(by: offset), count - offset, 0)
                    if n < 0 && (errno == EAGAIN || errno == EINTR) { continue }
                    guard n > 0 else { throw ReplayWire.Fault.notSharing }
                    offset += n
                }
            }
            return data
        }
        let n = ReplayWire.length(try read(4))
        guard n > 0 && n <= limit else { throw ReplayWire.Fault.malformed }
        return try read(n)
    }
}
