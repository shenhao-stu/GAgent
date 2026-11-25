import Foundation

/// Touch-like gestures on the phone, built from relative mouse moves.
///
/// The pointer is relative: unknown positions and screen edges reanchor at the top-left corner; consecutive
/// interior targets move directly with the same report phase. Coordinates are screen fractions (0..1).
///
/// iOS moves the pointer further per mouse unit the larger a report is, and the board's `move` sends both axes
/// in one report until the shorter one is done. A two-axis move therefore makes each axis depend on the other:
/// with one move per axis, 100 consecutive taps stayed within 1.5 pt.
@MainActor final class Pointer: ObservableObject {
    static let calibrationMove = 200        // fallback probe distance per axis
    static let homeRest = 0.3               // s after `home`, on a board that does not wait by itself
    static let pressRest = 0.15             // s before a button goes down, on such a board
    static let hold = 0.25                  // s to rest before lifting, so iOS adds no momentum
    static let homeFlickStep = 30           // mouse units per 8 ms report while flicking Home (firmware allows 1-60)
    static let edgePush = 30                // mouse units moved left past the screen edge, which stops the pointer
    static let backStart = 100              // mouse units of a Back stroke's slow start (about 80 pt)
    static let backFlickStep = 30           // mouse units per 8 ms report of its fast end
    static let tapGap = 0.15                // s to stay still after a click, so iOS sees a finished tap
    nonisolated static let nudge = 12       // mouse units the pointer is wiggled by to refresh a static screen
    static let pace = 1250.0                // mouse units a second: the board's `move` sends 10 per 8 ms report
    static let roundTrip = 0.1              // s one more command costs over the link, the pointer standing still
    static let leg = 40                     // mouse units (about 32 pt) a diagonal stroke may stray from its line
    static let reportGain: [(step: Int, gain: Double)] = [(10, 1.0), (15, 1.08), (20, 1.1), (25, 1.15), (30, 1.4),
                                                          (40, 1.8), (50, 2.02), (60, 2.19)]

    struct Span: Codable, Equatable { var w: Int, h: Int }
    private struct Saved: Codable {
        var w: Int, h: Int, seen: [String: [[Double]]]?, quality: Double?, aspect: Double?, axes: Bool?
    }

    let device: HIDDevice
    private let file: URL
    @Published private(set) var span: Span?  // mouse units needed to cross the full screen width / height
    private var pos: (Int, Int)?  // pointer position in mouse units; nil = unknown
    private(set) var location: CGPoint?
    private var link = 0  // device.links when the pointer was last homed
    var boardSettles: () -> Bool = { false }
    var relativePositioning = true
    private(set) var seen: [String: [(Double, Double)]] = ["x": [], "y": []]
    @Published private(set) var quality: Double?  // pointer error at the last check, fraction of the screen
    private(set) var aspect: Double?  // frame width / height when calibrated
    var log: (String) -> Void = { print($0) }
    var screenAspect: () -> Double = { 9 / 19.5 }

    init(device: HIDDevice, calibrationFile: URL) {
        self.device = device
        self.file = calibrationFile
        if let data = try? Data(contentsOf: calibrationFile), let saved = try? JSONDecoder().decode(Saved.self, from: data),
           saved.axes == true {
            span = Span(w: saved.w, h: saved.h)
            (quality, aspect) = (saved.quality, saved.aspect)
            for axis in ["x", "y"] {
                seen[axis] = (saved.seen?[axis] ?? []).filter { $0.count == 2 }.map { ($0[0], $0[1]) }.suffix(12)
            }
        }
    }

    var calibrated: Bool { span != nil }

    private func remember(_ axis: String, _ sample: (Double, Double)) {
        seen[axis] = Array((seen[axis, default: []] + [sample]).suffix(12))
    }

    func finishCalibration(x: Double, y: Double) {
        (quality, aspect) = (nil, screenAspect())
        span = Span(w: Int((Double(Self.calibrationMove) / x).rounded(.toNearestOrEven)), h: Int((Double(Self.calibrationMove) / y).rounded(.toNearestOrEven)))
        seen = ["x": [], "y": []]
        save()
    }

    /// Touch-probe result: per-axis lines landed = a * units + b fitted from taps the app caught itself.
    func applyProbe(x: ProbeFit.Line, y: ProbeFit.Line, samples: [(ux: Double, uy: Double, fx: Double, fy: Double)]) {
        let s = Span(w: Int((1 / x.a).rounded()), h: Int((1 / y.a).rounded()))
        span = s
        (quality, aspect) = (nil, screenAspect())
        seen = ["x": [], "y": []]
        for p in samples {
            remember("x", (p.ux / Double(s.w), p.fx))
            remember("y", (p.uy / Double(s.h), p.fy))
        }
        pos = nil
        save()
        log(String(format: "calibration: touch probe span %d x %d, offset %.3f / %.3f, residual %.2f%%",
                   s.w, s.h, x.b, y.b, max(x.rms, y.rms) * 100))
    }

    func setQuality(_ q: Double) {
        quality = q
        save()
    }

    private func save() {
        guard let span else { return }
        let saved = Saved(w: span.w, h: span.h, seen: seen.mapValues { $0.map { [$0.0, $0.1] } }, quality: quality,
                          aspect: aspect, axes: true)
        try? JSONEncoder().encode(saved).write(to: file)
    }

    func point(_ x: Double, _ y: Double) async throws {
        guard calibrated else { throw DeviceError(message: "pointer not calibrated") }
        try await moveTo(dx(x), dy(y))
    }

    private func line(_ axis: String) -> (a: Double, b: Double)? {
        let pts = seen[axis] ?? []
        guard pts.count >= 2 else { return nil }
        let n = Double(pts.count)
        let mc = pts.map(\.0).reduce(0, +) / n, mf = pts.map(\.1).reduce(0, +) / n
        let variance = pts.map { pow($0.0 - mc, 2) }.reduce(0, +)
        var a = variance > 1e-4 ? pts.map { ($0.0 - mc) * ($0.1 - mf) }.reduce(0, +) / variance : 1.0
        a = 0.85 < a && a < 1.15 ? a : 1.0
        let b = mf - a * mc
        return abs(b) < 0.1 ? (a, b) : nil
    }

    func fix(_ t: Double, _ axis: String) -> Double { line(axis).map { (t - $0.b) / $0.a } ?? t }

    private func landing(_ x: Int, _ y: Int) -> CGPoint? {
        guard let span else { return nil }
        func screen(_ units: Int, _ full: Int, _ axis: String) -> Double {
            let aimed = Double(units) / Double(full)
            return line(axis).map { $0.a * aimed + $0.b } ?? aimed
        }
        return CGPoint(x: screen(x, span.w, "x"), y: screen(y, span.h, "y"))
    }

    private func home() async throws {
        try await stayAfterClick()
        try await device.send("home")
        if !boardSettles() { try await Task.sleep(for: .seconds(Self.homeRest)) }
        (pos, location) = ((0, 0), landing(0, 0) ?? .zero)
    }

    private func walk(_ dx: Int, _ dy: Int) async throws {
        try await device.sendAll(Self.moves(x: dx == 0 ? [] : [dx], y: dy == 0 ? [] : [dy]))
    }

    static func moves(x: [Int], y: [Int]) -> [String] { x.map { "move \($0) 0" } + y.map { "move 0 \($0)" } }

    private func moveTo(_ tx: Int, _ ty: Int) async throws {
        if link != device.links {
            try await device.send("release")
            (pos, link) = (nil, device.links)
        }
        let direct = relativePositioning && pos != nil && interior(tx, ty) && interior(pos!.0, pos!.1)
        if !direct { try await home() }
        let (x, y) = pos!
        pos = nil
        if direct {
            try await stayAfterClick()
            try await device.sendAll(Self.moves(x: Self.relativeSteps(from: x, to: tx), y: Self.relativeSteps(from: y, to: ty)))
        } else {
            try await walk(tx - x, ty - y)
        }
        pos = (tx, ty)
        location = landing(tx, ty) ?? location
    }

    static func relativeSteps(from start: Int, to end: Int) -> [Int] {
        guard start != end else { return [] }
        return [-(start % 10), (end / 10 - start / 10) * 10, end % 10].filter { $0 != 0 }
    }

    private func interior(_ x: Int, _ y: Int) -> Bool {
        guard let span else { return false }
        return (0.08...0.92).contains(Double(x) / Double(span.w))
            && (0.08...0.92).contains(Double(y) / Double(span.h))
    }

    func fromHome(_ ux: Int, _ uy: Int) async throws {
        try await home()
        pos = nil
        try await walk(ux, uy)
    }

    private func rest() async throws {
        if !boardSettles() { try await Task.sleep(for: .seconds(Self.pressRest)) }
    }

    func click() async throws {
        try await stayAfterClick()
        try await rest()
        try await device.send("click")
        stillUntil = ProcessInfo.processInfo.systemUptime + Self.tapGap
    }

    func press() async throws {
        try await stayAfterClick()
        try await rest()
        try await device.send("press")
    }

    private var stillUntil = 0.0
    func stayAfterClick() async throws {
        let left = stillUntil - ProcessInfo.processInfo.systemUptime
        if left > 0 { try await Task.sleep(for: .seconds(left)) }
    }

    func nudge(_ units: Int = Pointer.nudge) async throws -> Int {
        try await stayAfterClick()
        let step = (location?.x ?? 0.5) > 0.8 ? -units : units
        try await device.send("move \(step) 0")
        return step
    }

    func unnudge(_ step: Int) async throws { try await device.sendUnobserved("move \(-step) 0") }

    func invalidatePosition() { pos = nil; location = nil }

    func reset() async throws {
        pos = nil
        try await device.send("release")
        try await home()
    }

    func tap(_ x: Double, _ y: Double, count: Int = 1) async throws {
        try await point(x, y)
        for _ in 0..<count { try await click() }
    }

    private func touch(_ x: Double, _ y: Double, rest: Double, _ body: () async throws -> Void) async throws {
        try await point(x, y)
        do {
            try await press()
            if rest > 0 { try await Task.sleep(for: .seconds(rest)) }
            try await body()
            try await device.send("release")
        } catch {
            pos = nil
            await Task { @MainActor [device] in _ = try? await device.send("release") }.value
            throw error
        }
    }

    func longPress(_ x: Double, _ y: Double, seconds: Double) async throws {
        try await touch(x, y, rest: seconds) {}
    }

    func swipe(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, hold: Bool = true, duration: Double = 0, startHold: Double = 0) async throws {
        defer { pos = nil }
        try await touch(x1, y1, rest: startHold) {
            try await travel(dx(x2) - dx(x1), dy(y2) - dy(y1), in: duration)
            if hold { try await Task.sleep(nanoseconds: UInt64(Self.hold * 1e9)) }
        }
        location = CGPoint(x: x2, y: y2)
    }

    private func travel(_ dx: Int, _ dy: Int, in duration: Double) async throws {
        let wide = abs(dx) >= abs(dy), minor = min(abs(dx), abs(dy))
        let spare = duration - Double(abs(dx) + abs(dy)) / Self.pace
        let pieces = min(20, max(1 + Int(max(0, spare) / Self.roundTrip), 1 + minor / Self.leg))
        func reached(_ total: Int, _ piece: Int) -> Int {
            piece == pieces ? total : (total * piece / pieces + (total < 0 ? -5 : 5)) / 10 * 10
        }
        let started = now()
        for piece in 1...pieces {
            let x = reached(dx, piece) - reached(dx, piece - 1), y = reached(dy, piece) - reached(dy, piece - 1)
            if wide { try await walk(x, 0) }
            try await walk(0, y)
            if !wide { try await walk(x, 0) }
            let wait = duration * Double(piece) / Double(pieces) - (now() - started)
            if piece < pieces, wait > 0 { try await Task.sleep(for: .seconds(wait)) }
        }
    }

    func type(_ text: String) async throws {
        var start = text.startIndex
        while start < text.endIndex {
            try Task.checkCancellation()
            let end = text.index(start, offsetBy: 200, limitedBy: text.endIndex) ?? text.endIndex
            try await device.send("type \(text[start..<end])")
            start = end
        }
    }

    func key(_ combo: String) async throws { try await device.send("key \(combo)") }

    func flick(_ x1: Double, _ y1: Double, _ x2: Double, _ y2: Double, duration: Double? = nil, step: Int? = nil,
               startHold: Double = 0, aimed: Bool = false) async throws {
        defer { pos = nil }
        let dx = self.dx(x2) - self.dx(x1), dy = self.dy(y2) - self.dy(y1)
        let major = Double(max(abs(dx), abs(dy)))
        func gain(_ step: Int) -> Double { aimed ? Self.gain(step) : 1 }
        var step = step
        if step == nil, let duration {
            let wanted = major * 0.008 / duration
            func off(_ s: Int) -> Double { abs(Double(s) * gain(s) - wanted) }
            step = (1...60).min { off($0) < off($1) }
        }
        try await point(x1, y1)
        do {
            if startHold > 0 {
                try await press()
                try await Task.sleep(for: .seconds(startHold))
            }
            do { try await stroke(dx, dy, step: step, aimed: aimed) }
            catch let error as DeviceError where error.message.contains("unknown command") {
                if startHold == 0 { try await press() }
                try await travel(dx, dy, in: 0)
                try await device.send("release")
            }
        } catch {
            await Task { @MainActor [device] in _ = try? await device.send("release") }.value
            throw error
        }
        location = CGPoint(x: x2, y: y2)
    }

    static func gain(_ step: Int) -> Double {
        let table = reportGain
        guard step > table[0].step else { return 1 }
        guard let upper = table.firstIndex(where: { $0.step >= step }) else { return table[table.count - 1].gain }
        let (a, b) = (table[upper - 1], table[upper])
        return a.gain + (b.gain - a.gain) * Double(step - a.step) / Double(b.step - a.step)
    }

    private func stroke(_ dx: Int, _ dy: Int, step: Int?, aimed: Bool = false) async throws {
        let command = "flick \(dx) \(dy)"
        let gain = aimed ? Self.gain(step ?? 10) : 1
        let paced = "flick \(Int((Double(dx) / gain).rounded())) \(Int((Double(dy) / gain).rounded()))"
        do { try await device.send(paced + (step.map { " \($0)" } ?? "")) }
        catch let error as DeviceError where step != nil && error.message.contains("invalid movement") {
            try await device.send(command)
        }
    }

    func goHome() async throws { try await flick(0.5, 0.995, 0.5, 0.74, step: Self.homeFlickStep) }

    func goBack() async throws {
        defer { pos = nil }
        try await point(0.005, 0.45)
        try await device.send("move -\(Self.edgePush) 0")
        let fast = dx(0.7) - Self.backStart
        do {
            try await press()
            try await device.send("move \(Self.backStart) 0")
            do { try await stroke(fast, 0, step: Self.backFlickStep) }
            catch let error as DeviceError where error.message.contains("unknown command") {
                try await device.send("move \(fast) 0")
                try await device.send("release")
            }
        } catch {
            await Task { @MainActor [device] in _ = try? await device.send("release") }.value
            throw error
        }
        location = CGPoint(x: 0.8, y: 0.45)
    }

    func openSearch() async throws { try await flick(0.04, 0.42, 0.04, 0.66) }

    func openControlCenter() async throws {
        defer { pos = nil }
        try await point(0.8, 0)
        try await device.send("move 0 -\(Self.edgePush)")
        let distance = dy(0.2) - dy(0)
        do {
            do { try await stroke(0, distance, step: nil) }
            catch let error as DeviceError where error.message.contains("unknown command") {
                try await press()
                try await device.send("move 0 \(distance)")
                try await device.send("release")
            }
        } catch {
            await Task { @MainActor [device] in _ = try? await device.send("release") }.value
            throw error
        }
        location = CGPoint(x: 0.8, y: 0.2)
    }

    private func dx(_ x: Double) -> Int { Int((min(max(fix(x, "x"), 0), 1) * Double(span!.w)).rounded(.toNearestOrEven)) }
    private func dy(_ y: Double) -> Int { Int((min(max(fix(y, "y"), 0), 1) * Double(span!.h)).rounded(.toNearestOrEven)) }
}
