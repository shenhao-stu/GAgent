import CoreBluetooth
import Foundation

/// CoreBluetooth central for the board: scan, connect (bonding happens on the first encrypted `net` read),
/// command writes, and status / reply notifies. Reconnects automatically and restores state across relaunches.
@MainActor final class BoardLink: NSObject, ObservableObject, BoardTransport {
    struct Found: Identifiable, Equatable {
        let id: UUID
        let name: String
        let rssi: Int
    }

    @Published private(set) var state: CBManagerState = .unknown
    @Published private(set) var found: [Found] = []
    @Published private(set) var scanning = false
    @Published private(set) var connected = false  // subscribed and ready for commands
    @Published private(set) var connecting = false
    @Published private(set) var linking = false    // connected over the air, pairing / subscribing
    @Published private(set) var pairedID: UUID?
    @Published private(set) var name = ""
    @Published private(set) var status: BoardStatus?
    @Published private(set) var net: NetConfig?
    @Published private(set) var lastError = ""
    @Published private(set) var signalStrength: Int?

    let commands = CommandChannel()
    var onStatus: ((BoardStatus) -> Void)?
    var onLinkUp: (() -> Void)?
    var onLinkDown: (() -> Void)?
    private var lastNotify = 0.0
    private var statusRevision = 0
    private var readySince = 0.0
    var log: (String) -> Void = { print($0) }

    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var chars: [CBUUID: CBCharacteristic] = [:]
    private var subscribed = Set<CBUUID>()
    private var netRevision = 0
    private var netReadError: Error?
    private static let pairedKey = "gagent.pairedBoard"
    private static let notifyUUIDs: Set<CBUUID> = [BoardUUID.reply, BoardUUID.status]
    private var statusReads: Task<Void, Never>?
    private var scanDeadline: Task<Void, Never>?
    private var connectionDeadline: Task<Void, Never>?
    private var retryTask: Task<Void, Never>?
    private var candidates: [UUID: CBPeripheral] = [:]
    let mock: Bool

    init(mock: Bool = false) {
        self.mock = mock
        super.init()
        pairedID = UserDefaults.standard.string(forKey: Self.pairedKey).flatMap(UUID.init)
        commands.transport = self
        if mock { return }
        central = CBCentralManager(delegate: self, queue: .main, options: [
            CBCentralManagerOptionRestoreIdentifierKey: "gagent-board-central",
            CBCentralManagerOptionShowPowerAlertKey: true,
        ])
    }

    var isConnected: Bool { connected }

    // MARK: - scan / pair

    func refreshStatus() async throws {
        if mock { return }
        guard state == .poweredOn else {
            throw DeviceError(message: String(localized: "Turn on Bluetooth to refresh the board status."))
        }
        if !connected {
            if pairedID != nil { reconnect() }
            else if !scanning { scan() }
            let deadline = now() + 8
            while !connected && now() < deadline && (connecting || linking || scanning) {
                try await Task.sleep(for: .milliseconds(200))
            }
        }
        guard connected, let peripheral, let characteristic = chars[BoardUUID.status] else {
            let message = !lastError.isEmpty ? lastError : pairedID == nil
                ? String(localized: "Tap Board to choose a device.")
                : String(localized: "Still reconnecting. Keep the board nearby.")
            throw DeviceError(message: message)
        }
        let revision = statusRevision
        peripheral.readValue(for: characteristic)
        peripheral.readRSSI()
        let deadline = now() + 3
        while connected && revision == statusRevision && now() < deadline {
            try await Task.sleep(for: .milliseconds(100))
        }
        guard connected, statusRevision != revision else {
            throw DeviceError(message: String(localized: "No fresh board status received. Try again."))
        }
    }

    func scan() {
        guard state == .poweredOn, !mock, !connected, !connecting, !linking else { return }
        found = []
        lastError = ""
        scanning = true
        central.scanForPeripherals(withServices: [BoardUUID.service], options: nil)
        log("BLE scanning for board service")
        scanDeadline?.cancel()
        scanDeadline = Task { [weak self] in
            guard (try? await Task.sleep(nanoseconds: 12_000_000_000)) != nil, let self, self.scanning else { return }
            self.stopScan()
            if self.found.isEmpty {
                self.lastError = String(localized: "No board found. Check its power, keep it nearby, and scan again.")
            }
        }
        for p in central.retrieveConnectedPeripherals(withServices: [BoardUUID.service]) {
            discovered(p, name: p.name ?? "ESP32 Agent", rssi: 0)
        }
    }

    func stopScan() {
        scanDeadline?.cancel()
        central?.stopScan()
        scanning = false
    }

    func pair(_ id: UUID) {
        if mock { return mockPair(id) }
        stopScan()
        pairedID = id
        lastError = ""
        if let previous = peripheral, previous.identifier != id {
            peripheral = nil
            central.cancelPeripheralConnection(previous)
            setDisconnected()
        }
        peripheral = candidates[id]
        reconnect()
    }

    func unpair() async {
        _ = try? await commands.send("unpair")
        forget()
    }

    func forget() {
        retryTask?.cancel()
        connectionDeadline?.cancel()
        let previous = peripheral
        peripheral = nil
        if let previous { central?.cancelPeripheralConnection(previous) }
        pairedID = nil
        signalStrength = nil
        UserDefaults.standard.removeObject(forKey: Self.pairedKey)
        setDisconnected()
    }

    func retryDiscovery() {
        forget()
        lastError = ""
        scan()
    }

    private func discovered(_ p: CBPeripheral, name: String, rssi: Int) {
        candidates[p.identifier] = p
        if rssi < 0 { signalStrength = rssi }
        let item = Found(id: p.identifier, name: name, rssi: rssi)
        if let i = found.firstIndex(where: { $0.id == item.id }) { found[i] = item } else { found.append(item) }
        log("BLE found \(name), RSSI \(rssi)")
        if p.identifier == pairedID && !connected && !linking && !connecting {
            stopScan()
            peripheral = p
            reconnect()
        }
    }

    private func failConnection(_ message: String) {
        retryTask?.cancel()
        lastError = message
        log("BLE setup failed: \(message)")
        let previous = peripheral
        peripheral = nil
        setDisconnected()
        stopScan()
        if let previous { central.cancelPeripheralConnection(previous) }
    }

    private func reconnect() {
        guard state == .poweredOn, !mock, !connected, !connecting, !linking, let id = pairedID else { return }
        if peripheral?.identifier != id {
            peripheral = central.retrievePeripherals(withIdentifiers: [id]).first
        }
        guard let peripheral else {
            lastError = "board not found; scanning"
            if !scanning { scan() }
            return
        }
        peripheral.delegate = self
        name = peripheral.name ?? name
        connecting = true
        log("BLE connecting to \(name)")
        connectionDeadline?.cancel()
        connectionDeadline = Task { [weak self] in
            guard (try? await Task.sleep(nanoseconds: 30_000_000_000)) != nil, let self, !self.connected else { return }
            self.failConnection(String(localized: "Connection timed out. Keep the board nearby and try again."))
        }
        if peripheral.state == .connected {
            connecting = false
            linking = true
            peripheral.discoverServices([BoardUUID.service])
        } else { central.connect(peripheral, options: nil) }
    }

    // MARK: - pairing / encrypted config read

    func readNet(refresh: Bool = false) async throws -> NetConfig {
        if connected, let net, !refresh || mock { return net }
        guard let peripheral, let c = chars[BoardUUID.net] else { throw DeviceError(message: "board not connected") }
        let revision = netRevision
        peripheral.readValue(for: c)
        let deadline = now() + 3
        while connected && self.peripheral === peripheral && revision == netRevision && now() < deadline {
            try await Task.sleep(for: .milliseconds(100))
        }
        try Task.checkCancellation()
        guard connected, self.peripheral === peripheral, revision != netRevision else {
            throw DeviceError(message: "未收到新的板子状态，请刷新连接状态。")
        }
        if let netReadError { throw netReadError }
        guard let net else { throw DeviceError(message: "bad board config") }
        return net
    }

    // MARK: - BoardTransport

    func write(_ line: String) throws {
        if mock, connected { return mockReply(line) }
        guard let peripheral, let c = chars[BoardUUID.cmd], connected else {
            throw DeviceError(message: "board not connected")
        }
        let data = Data(line.utf8)
        let fast = data.count <= peripheral.maximumWriteValueLength(for: .withoutResponse)
            && c.properties.contains(.writeWithoutResponse) && peripheral.canSendWriteWithoutResponse
        peripheral.writeValue(data, for: c, type: fast ? .withoutResponse : .withResponse)
    }

    var maxWrite: Int { peripheral?.maximumWriteValueLength(for: .withoutResponse) ?? 20 }

    func writeIfIdle(_ line: String) -> Bool {
        guard !mock, let peripheral, let c = chars[BoardUUID.cmd], connected,
              c.properties.contains(.writeWithoutResponse), peripheral.canSendWriteWithoutResponse else { return false }
        let data = Data(line.utf8)
        guard data.count <= peripheral.maximumWriteValueLength(for: .withoutResponse) else { return false }
        peripheral.writeValue(data, for: c, type: .withoutResponse)
        return true
    }

    // MARK: - demo data

    func mockFound() {
        state = .poweredOn
        pairedID = nil
        found = [Found(id: UUID(), name: "ESP32 Agent 7C3E", rssi: -58)]
    }

    private func mockPair(_ id: UUID) {
        scanning = true
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            scanning = false
            mockConnect(name: "ESP32 Agent 7C3E", net: NetConfig(mode: "ble"))
        }
    }

    func mockConnect(name: String, net: NetConfig) {
        state = .poweredOn
        self.name = name
        self.net = net
        pairedID = pairedID ?? UUID()
        found = [Found(id: UUID(), name: "ESP32 Agent 7C3E", rssi: -71)]
        connected = true
        commands.linkUp()
        onLinkUp?()
    }

    func mockStatus(_ s: BoardStatus) {
        status = s
        onStatus?(s)
    }

    private func mockReply(_ line: String) {
        let parts = line.split(separator: " ").map(String.init)
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 40_000_000)
            commands.handleReply("\(parts[0]) ok")
        }
    }

    private func startFullStatusReads() {
        statusReads?.cancel()
        statusReads = Task { [weak self] in
            var tick = 0
            while !Task.isCancelled {
                guard let self, self.connected, let p = self.peripheral, let c = self.chars[BoardUUID.status] else { return }
                if tick % 5 == 0 { p.readValue(for: c); p.readRSSI() }
                tick += 1
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }
    }

    private func setDisconnected() {
        statusReads?.cancel()
        connectionDeadline?.cancel()
        connecting = false
        net = nil
        status = nil
        let was = connected
        connected = false
        linking = false
        chars = [:]
        subscribed = []
        commands.linkDown()
        netReadError = nil
        if was {
            log("board disconnected")
            onLinkDown?()
        }
    }
}

extension BoardLink: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        MainActor.assumeIsolated {
            state = central.state
            log("BLE state \(central.state.rawValue)")
            if central.state == .poweredOn { reconnect() } else { stopScan(); setDisconnected() }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        MainActor.assumeIsolated {
            if let restored = (dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral])?.first {
                peripheral = restored
                restored.delegate = self
                log("restored board link after relaunch")
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDiscover p: CBPeripheral,
                                    advertisementData: [String: Any], rssi: NSNumber) {
        MainActor.assumeIsolated {
            let name = advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? p.name ?? "ESP32 Agent"
            discovered(p, name: name, rssi: rssi.intValue)
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect p: CBPeripheral) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            connecting = false
            name = p.name ?? name
            linking = true
            log("board connected, discovering")
            p.discoverServices([BoardUUID.service])
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didFailToConnect p: CBPeripheral, error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            lastError = error?.localizedDescription ?? "connect failed"
            let e = error as NSError?
            DebugLog.write("BLE connect failed: \(e?.domain ?? "-") \(e?.code ?? 0): \(lastError)")
            if (error as? CBError)?.code == .peerRemovedPairingInformation {
                lastError = "板子的配对记录已更新。请在 iPhone「设置 → 蓝牙」忽略 ESP32 Agent，再重新配对。"
            }
            failConnection(lastError)
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDisconnectPeripheral p: CBPeripheral,
                                    error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            let e = error as NSError?
            DebugLog.write(String(format: "BLE disconnect: %@ %d: %@; last notification %.1f s ago; link up %.0f s",
                                  e?.domain ?? "no error", e?.code ?? 0, e?.localizedDescription ?? "-",
                                  lastNotify > 0 ? now() - lastNotify : -1, readySince > 0 ? now() - readySince : -1))
            setDisconnected()
            if let error { lastError = error.localizedDescription }
            retryTask?.cancel()
            retryTask = Task { [weak self] in
                guard (try? await Task.sleep(nanoseconds: 2_000_000_000)) != nil else { return }
                self?.reconnect()
            }
        }
    }
}

extension BoardLink: CBPeripheralDelegate {
    nonisolated func peripheral(_ p: CBPeripheral, didReadRSSI RSSI: NSNumber, error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral, error == nil else { return }
            signalStrength = RSSI.intValue
            log("BLE signal \(RSSI.intValue) dBm")
        }
    }

    nonisolated func peripheral(_ p: CBPeripheral, didDiscoverServices error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            if let error { failConnection(error.localizedDescription); return }
            guard let service = p.services?.first(where: { $0.uuid == BoardUUID.service }) else {
                failConnection(String(localized: "Board service missing. Check the board firmware."))
                return
            }
            p.discoverCharacteristics(BoardUUID.all, for: service)
        }
    }

    nonisolated func peripheral(_ p: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            if let error { failConnection(error.localizedDescription); return }
            let available = Set((service.characteristics ?? []).map(\.uuid))
            guard available.isSuperset(of: BoardUUID.required) else {
                failConnection(String(localized: "Board firmware is missing required features. Update the firmware.")); return
            }
            for c in service.characteristics ?? [] {
                chars[c.uuid] = c
                if Self.notifyUUIDs.contains(c.uuid) { p.setNotifyValue(true, for: c) }
            }
        }
    }

    nonisolated func peripheral(_ p: CBPeripheral, didUpdateNotificationStateFor c: CBCharacteristic, error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            if let error { failConnection("subscribe \(c.uuid): \(error.localizedDescription)"); return }
            guard c.isNotifying else { return }
            subscribed.insert(c.uuid)
            if !connected && subscribed.isSuperset(of: Self.notifyUUIDs) {
                if let netChar = chars[BoardUUID.net] { p.readValue(for: netChar) }
            }
        }
    }

    nonisolated func peripheral(_ p: CBPeripheral, didUpdateValueFor c: CBCharacteristic, error: Error?) {
        MainActor.assumeIsolated {
            guard p === peripheral else { return }
            lastNotify = now()
            if c.uuid == BoardUUID.net {
                netRevision += 1
                netReadError = error
                if let error {
                    if linking { failConnection(error.localizedDescription) }
                } else if let v = c.value, let config = try? JSONDecoder().decode(NetConfig.self, from: v) {
                    net = config
                    if linking && subscribed.isSuperset(of: Self.notifyUUIDs) {
                        connectionDeadline?.cancel()
                        stopScan()
                        connected = true
                        linking = false
                        lastError = ""
                        pairedID = p.identifier
                        UserDefaults.standard.set(p.identifier.uuidString, forKey: Self.pairedKey)
                        readySince = now()
                        commands.linkUp()
                        startFullStatusReads()
                        onLinkUp?()
                        log("board ready, encrypted configuration read (max write payload \(maxWrite) B)")
                    }
                } else {
                    netReadError = DeviceError(message: "bad board config")
                }
                return
            }
            guard error == nil, let v = c.value else { return }
            switch c.uuid {
            case BoardUUID.reply: commands.handleReply(String(decoding: v, as: UTF8.self))
            case BoardUUID.status:
                if let s = BoardStatus.decode(v) {
                    let merged = status?.merged(with: s) ?? s
                    statusRevision += 1
                    status = merged
                    onStatus?(merged)
                }
            default: break
            }
        }
    }
}
