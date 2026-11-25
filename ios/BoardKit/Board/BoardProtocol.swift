import CoreBluetooth
import Foundation

/// GATT layout and message formats for the ESP32-S3 BLE HID bridge.
enum BoardUUID {
    static func make(_ suffix: String) -> CBUUID { CBUUID(string: "6e400001-a9e8-4b1b-9c39-6d6f8a3c" + suffix) }
    static let service = make("0000")
    static let cmd = make("0001")
    static let reply = make("0002")
    static let status = make("0003")
    static let video = make("0004")
    static let net = make("0005")
    static let required = [cmd, reply, status, net]
    static let all = [cmd, reply, status, video, net]
}

/// The 1 s JSON heartbeat on `status`.
struct BoardStatus: Codable, Equatable {
    struct BLE: Codable, Equatable {
        var mtu: Int?, phy: Int?, kbps: Double?, drop: Int?
        var vmtu: Int?, rdrop: Int?, n: Int?
    }
    var up: Int?
    var rst: String?
    var heap: Int?
    var psram: Int?
    var hid: String?, hid_ready: Bool?, ble_hid: String?, hid_caps: String?
    var usb: String?   // ok | asleep | off
    var net: String?
    var ip: String?
    var sta: Int?
    var ap: String?
    var w: Int?, h: Int?
    var kbps: Double?, fps: Double?, idr: Int?, gop: Int?
    var anc: Int?, ovf: Int?, trim: Int?
    var lag: Int?
    var vnet: Int?, vtransport: String?, vkbps: Double?
    var ble: BLE?

    var inputReady: Bool { hid == nil ? usb == "ok" : hid_ready == true }

    func needsMirrorRestart(frameUnavailable: Bool) -> Bool {
        ap == "failed" || (ap == "streaming" && anc == 0 && (frameUnavailable || lag == -1))
    }

    static func decode(_ data: Data) -> BoardStatus? { try? JSONDecoder().decode(BoardStatus.self, from: data) }

    func merged(with n: BoardStatus) -> BoardStatus {
        var m = n
        m.up = n.up ?? up; m.rst = n.rst ?? rst; m.heap = n.heap ?? heap; m.psram = n.psram ?? psram
        m.hid = n.hid ?? hid
        m.hid_ready = n.hid_ready ?? (n.hid == nil || n.hid == hid ? hid_ready : nil)
        m.ble_hid = n.ble_hid ?? ble_hid; m.hid_caps = n.hid_caps ?? hid_caps
        m.usb = n.usb ?? usb; m.net = n.net ?? net; m.ip = n.ip ?? ip; m.sta = n.sta ?? sta; m.ap = n.ap ?? ap
        m.w = n.w ?? w; m.h = n.h ?? h; m.kbps = n.kbps ?? kbps; m.fps = n.fps ?? fps; m.idr = n.idr ?? idr
        m.gop = n.gop ?? gop; m.lag = n.lag ?? lag
        m.vnet = n.vnet ?? vnet; m.vtransport = n.vtransport ?? vtransport; m.vkbps = n.vkbps ?? vkbps
        m.anc = n.anc ?? anc; m.ovf = n.ovf ?? ovf; m.trim = n.trim ?? trim
        let a = ble ?? BLE(), b = n.ble ?? BLE()
        m.ble = BLE(mtu: b.mtu ?? a.mtu, phy: b.phy ?? a.phy, kbps: b.kbps ?? a.kbps, drop: b.drop ?? a.drop,
                    vmtu: b.vmtu ?? a.vmtu, rdrop: b.rdrop ?? a.rdrop, n: b.n ?? a.n)
        return m
    }
}

/// Encrypted pairing/configuration characteristic (`0005`): reading triggers LE Secure Connections bonding.
struct NetConfig: Codable, Equatable {
    var mode: String
    var ssid: String?
    var pass: String?
    var ip: String?

    init(mode: String = "ble", ssid: String? = nil, pass: String? = nil, ip: String? = nil) {
        self.mode = mode
        self.ssid = ssid
        self.pass = pass
        self.ip = ip
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "ble"
        ssid = try c.decodeIfPresent(String.self, forKey: .ssid)
        pass = try c.decodeIfPresent(String.self, forKey: .pass)
        ip = try c.decodeIfPresent(String.self, forKey: .ip)
    }
}

/// A `reply` notify: `<id> ok [extra]` or `<id> err <reason>`.
struct BoardReply: Equatable {
    let id: Int
    let ok: Bool
    let text: String

    static func parse(_ line: String) -> BoardReply? {
        let parts = line.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: " ", maxSplits: 2)
            .map(String.init)
        guard parts.count >= 2, let id = Int(parts[0]), parts[1] == "ok" || parts[1] == "err" else { return nil }
        return BoardReply(id: id, ok: parts[1] == "ok", text: parts.count > 2 ? parts[2] : "")
    }
}
