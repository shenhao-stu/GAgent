import SwiftUI
import UIKit

/// Catches the board's clicks on this app's own screen during calibration. While `capturing`, the
/// calibration board (white, gridded, above sheets and covers too) swallows every touch except its Back
/// button, so a probe click never presses a control underneath; otherwise only the toast takes touches.
@MainActor final class TouchProbe: ObservableObject {
    @Published private(set) var capturing = false
    /// Recent hits (screen fractions) for the faint flash on the grid.
    @Published private(set) var flashes: [CGPoint] = []
    private(set) var releasedAt = 0.0
#if DEBUG
    private(set) var pressedAt = 0.0
    private(set) var firstMovedAt = 0.0
    /// Every position of the newest touch, from where it went down (time, screen fraction): how a stroke really moved.
    private(set) var trace: [(time: Double, at: CGPoint)] = []
#endif
    private var taps: [(time: Double, at: CGPoint)] = []
    private var window: OverlayWindow?

    /// Show the overlay window over this scene (once; a no-op until a scene exists).
    func install<Content: View>(_ content: Content) {
        guard window == nil, let scene = DeviceScreen.scene else { return }
        let w = OverlayWindow(windowScene: scene)
        w.windowLevel = .alert + 1
        let host = UIHostingController(rootView: content)
        host.view.backgroundColor = .clear
        w.rootViewController = host
        w.catcher.onTouch = { [weak self] p, size in self?.touched(p, in: size) }
#if DEBUG
        w.catcher.onMove = { [weak self] p, size in
            guard let self, self.capturing, size.width > 0, size.height > 0 else { return }
            if self.firstMovedAt == 0 { self.firstMovedAt = now() }
            self.trace.append((now(), CGPoint(x: p.x / size.width, y: p.y / size.height)))
        }
#endif
        w.catcher.onRelease = { [weak self] in self?.releasedAt = now() }
        w.isHidden = false
        window = w
    }

    /// Where the toast is (window coordinates); only that area takes touches when not capturing.
    func setInteractive(_ rect: CGRect) { window?.interactive = rect }
    /// The calibration board's buttons: the only places that take touches while capturing.
    func setButtonArea(_ id: String, _ rect: CGRect?) { window?.buttons[id] = rect }

    func begin() {
        taps = []
        releasedAt = 0
#if DEBUG
        pressedAt = 0; firstMovedAt = 0; trace = []
#endif
        flashes = []
        capturing = true
        window?.capturing = true
    }

    func end() {
        capturing = false
        window?.capturing = false
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 600_000_000)
            self?.flashes = []
        }
    }

    private func touched(_ p: CGPoint, in size: CGSize) {
        guard capturing, size.width > 0, size.height > 0 else { return }
        let f = CGPoint(x: p.x / size.width, y: p.y / size.height)
#if DEBUG
        pressedAt = now()
        trace = [(pressedAt, f)]
#endif
        taps.append((now(), f))
        flashes = Array((flashes + [f]).suffix(12))
    }

    /// The first tap after `since` (a click just sent), waiting up to `timeout` s.
    func tap(since: Double, timeout: Double = 3) async -> CGPoint? {
        let deadline = now() + timeout
        while now() < deadline && !Task.isCancelled {
            if let hit = taps.first(where: { $0.time >= since }) {
                taps.removeAll { $0.time <= hit.time }
                return hit.at
            }
            try? await Task.sleep(nanoseconds: 20_000_000)
        }
        return nil
    }
}

/// Passes touches through, except on the toast; while capturing, everything lands on the catcher.
final class OverlayWindow: UIWindow {
    let catcher = TouchCatcher()
    var capturing = false
    var interactive = CGRect.zero
    var buttons: [String: CGRect] = [:]

    override init(windowScene: UIWindowScene) {
        super.init(windowScene: windowScene)
        backgroundColor = .clear
        catcher.frame = bounds
        catcher.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        addSubview(catcher)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    override func hitTest(_ point: CGPoint, with event: UIEvent?) -> UIView? {
        if capturing {
            return buttons.values.contains { $0.contains(point) } ? super.hitTest(point, with: event) : catcher
        }
        guard interactive.contains(point) else { return nil }
        return super.hitTest(point, with: event)
    }
}

/// Reports where each touch begins, in screen points with the screen's size (an iPad app in Split View
/// is smaller than the screen the pointer moves on).
final class TouchCatcher: UIView {
    var onTouch: ((CGPoint, CGSize) -> Void)?
    var onRelease: (() -> Void)?
#if DEBUG
    var onMove: ((CGPoint, CGSize) -> Void)?
    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard let touch = touches.first else { return }
        if let screen = window?.windowScene?.screen {
            onMove?(convert(touch.location(in: self), to: screen.coordinateSpace), screen.bounds.size)
        } else { onMove?(touch.location(in: self), bounds.size) }
    }
#endif

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        for t in touches {
            let p = t.location(in: self)
            if let screen = window?.windowScene?.screen {
                let point = convert(p, to: screen.coordinateSpace)
#if DEBUG
                DebugLog.write("probe geometry: type=\(t.type.rawValue) local=\(p) screen=\(point) bounds=\(screen.bounds) scale=\(screen.scale) view=\(bounds)")
#endif
                onTouch?(point, screen.bounds.size)
            } else {
                onTouch?(p, bounds.size)
            }
        }
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
#if DEBUG
        touchesMoved(touches, with: event) // The lift position need not have had a separate moved event.
#endif
        onRelease?()
    }
    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) { onRelease?() }
}
