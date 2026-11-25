import CoreGraphics
import Foundation

/// Model-visible observations. Time alone never invalidates a still screen; a new stream or changed pixels do.
/// The pointer is masked where it was and is: probes move it, and AssistiveTouch fades it, without changing the page.
struct ScreenObservation {
    private struct Seen {
        let id: String; let frame: Data; let generation: Int; let pointer: CGPoint?
    }
    /// Latest observations, newest last: the model acts on the one it was given, which may be a step behind.
    private var recent: [Seen] = []
    var frameID: String? { recent.last?.id }

    func isExact(_ frame: Data, generation: Int, id: String) -> Bool {
        recent.last.map { $0.id == id && $0.generation == generation && $0.frame == frame } ?? false
    }

    func samePage(_ frame: Data, generation: Int, pointer: CGPoint? = nil) -> Bool {
        guard let last = recent.last, last.generation == generation else { return false }
        return last.frame == frame || !Vision.changed(last.frame, frame, ignore: [last.pointer, pointer].compactMap { $0 })
    }

    /// IDs and element numbers refer to exact image bytes. Same-page comparison is only a display hint.
    mutating func capture(_ frame: Data, generation: Int, pointer: CGPoint? = nil) -> String {
        if let last = recent.last, last.generation == generation, last.frame == frame {
            return last.id
        }
        let id = UUID().uuidString
        recent = Array((recent + [Seen(id: id, frame: frame, generation: generation, pointer: pointer)]).suffix(6))
        return id
    }

    /// Re-evaluate access after suspending: a valid earlier frame grants no ongoing permission.
    static func requireAccess(consent: Bool, generation: Int, expected: Int? = nil) throws {
        try Task.checkCancellation()
        guard consent else { throw DeviceError(message: "Open iPhone control setup and enable device control consent") }
        if let expected, expected != generation { throw Failure.frameChanged }
    }

    static func requestedID(_ value: Any?) throws -> String? {
        guard let value else { return nil } // Native diagnostics predate observation-bound model actions.
        guard let id = value as? String, (1...128).contains(id.utf8.count),
              id.range(of: "^[A-Za-z0-9_:-]+$", options: .regularExpression) != nil else {
            throw Failure.invalidFrameID
        }
        return id
    }

    /// Observation `id` was published in sharing session `generation`, so the model may still refer to it. Typed
    /// text, keys and system gestures ask no more: they aim at no point of the page, so only the whole screen
    /// could be compared, and a live page is rarely the same picture twice (a loading bar, a clock, the
    /// AssistiveTouch button fading): that check refused every Back of a model run (2026-11-12). They are judged
    /// from the screen read after them.
    func requireKnown(_ id: String, generation: Int) throws {
        guard recent.contains(where: { $0.id == id && $0.generation == generation }) else { throw Failure.frameChanged }
    }

    /// Whether a touch at `target`, aimed on observation `expected`, is still valid on the `current` frame. It depends
    /// on its target's neighbourhood only, so a chat receiving messages elsewhere does not void it. Returns true
    /// when the page changed elsewhere. Without a target the whole page must be unchanged.
    @discardableResult
    func require(_ expected: String?, current: Data? = nil, generation: Int? = nil,
                 target: CGPoint? = nil, pointer: CGPoint? = nil) throws -> Bool {
        guard let expected else { return false }
        guard let seen = recent.first(where: { $0.id == expected }), generation.map({ $0 == seen.generation }) ?? true
        else { throw Failure.frameChanged }
        guard let current else {
            guard expected == frameID else { throw Failure.frameChanged }
            return false
        }
        if seen.frame == current { return false }
        let ignore = [seen.pointer, pointer].compactMap { $0 }
        if let target, Vision.changed(seen.frame, current, near: target, ignore: ignore) { throw Failure.frameChanged }
        let changed = Vision.changed(seen.frame, current, ignore: ignore)
        if changed && target == nil { throw Failure.frameChanged }
        return changed
    }

    /// A masked centre is unverified, not unchanged. This is evidence for the caller, never a refusal.
    func targetMasked(_ target: CGPoint, on id: String, pointer: CGPoint?) -> Bool {
        guard let seen = recent.last(where: { $0.id == id }), let image = Vision.image(seen.frame) else { return true }
        let aspect = Double(image.height) / Double(image.width)
        return [seen.pointer, pointer].compactMap { $0 }.contains {
            hypot(Double(target.x - $0.x), Double(target.y - $0.y) * aspect) <= Vision.pointerRadius
        }
    }

    enum Failure: String, LocalizedError {
        case invalidFrameID = "invalid_frame_id"
        case frameChanged = "frame_changed"
        case sourceStalled = "source_stalled"
        case catchingUp = "stream_catching_up"
        case sourcePaused = "source_paused"
        case textNotStaged = "text_not_staged"

        var errorDescription: String? {
            switch self {
            case .invalidFrameID: return "frame_id must be 1–128 ASCII letters, digits, _, - or :"
            case .frameChanged: return "The target area changed since that observation. Locate the target again in the newest returned image before acting."
            case .sourceStalled: return "Screen Mirroring is connected and not paused, but the iPhone sent no new frame after two pointer nudges. No current image was returned. This does not establish whether the phone is locked or asleep."
            case .catchingUp: return "The board is still sending older frames after a reconnect; the latest screen is not available yet. Wait for the reported time, then observe again."
            case .sourcePaused: return "The iPhone reported that Screen Mirroring is paused, so no live screen is available."
            case .textNotStaged: return "Text was not staged; nothing was typed. iOS allows clipboard writes only while GAgent is in front. Bring GAgent to the front (hid status shows gagent_foreground=true), then hid stage_text with the exact text before returning to the target field."
            }
        }
    }
}
