import Foundation

/// Follows one task across the engine's snapshots and turns each snapshot into the state to draw.
///
/// A task starts when a running conversation first uses the phone, and ends when it finishes, fails or is
/// stopped. A question and its answer, or a handoff and its return, are new generations for the engine but
/// the same task here: the step count goes on and the request shown stays the user's original one.
/// An ended task is kept until the next one starts or `dismiss()`, and is never derived again.
struct PresenceTracker {
    private(set) var state: PresenceState?
    private var gen = 0
    private var earlierSteps = 0, steps = 0
    private var stopped: Int?          // the generation a stop was requested or seen for
    private var releasedAt: Date?      // when a handoff was first found over with no new turn yet

    /// Handing back clears the handoff just before the next turn starts; that gap is not "ended".
    static let settle: TimeInterval = 2

    /// The engine keeps no trace of a stop, so whoever issues one says so here.
    mutating func stopRequested() { stopped = gen }

    mutating func dismiss() { state = nil }

    /// Take up a task whose card outlived the process. The engine's generation counter did not survive
    /// either, so whatever runs next in that conversation continues the task.
    mutating func adopt(_ leftover: PresenceState) {
        state = leftover; gen = .min; earlierSteps = leftover.step; steps = 0; stopped = nil; releasedAt = nil
    }

    /// `phoneActive`: the phone is being driven right now, by a tool call or by a script that leaves no tool event.
    mutating func fold(_ snapshot: PresenceSnapshot, now: Date, phoneActive: Bool = false) -> PresenceState? {
        let copy = PresenceCopy(english: snapshot.lang == "en")
        if let old = state, !old.ended {
            guard let run = snapshot.runs.first(where: { $0.cid == old.cid }) else { state = nil; return nil }
            state = advance(old, run, copy, now)
        } else if let run = newcomer(snapshot, phoneActive) {
            gen = run.gen; earlierSteps = 0; steps = 0; stopped = nil; releasedAt = nil
            let blank = PresenceState(cid: run.cid, phase: .thinking, title: run.title, step: 0, now: "", trail: [],
                                      ask: nil, startedAt: now, phaseSince: now, english: copy.english)
            state = advance(blank, run, copy, now)
        }
        return state
    }

    private func newcomer(_ snapshot: PresenceSnapshot, _ phoneActive: Bool) -> PresenceSnapshot.Run? {
        let running = snapshot.runs.filter(\.running)
        return running.first(where: \.usedPhone) ?? (phoneActive && running.count == 1 ? running[0] : nil)
    }

    private mutating func advance(_ old: PresenceState, _ run: PresenceSnapshot.Run, _ copy: PresenceCopy,
                                  _ now: Date) -> PresenceState {
        if run.gen != gen { earlierSteps += steps; gen = run.gen; stopped = nil }
        steps = run.step
        if run.stopping { stopped = run.gen }
        var new = old
        new.phase = phase(run, was: old.phase, now)
        new.step = max(earlierSteps + steps, 1)
        new.trail = run.trail
        new.ask = new.phase == .asking ? run.ask.map {
            .init(question: $0.question, choices: $0.candidates, replyToken: $0.replyToken)
        } : nil
        new.english = copy.english
        new.now = text(new, run, copy)
        if new.phase != old.phase { new.phaseSince = now }
        return new
    }

    private mutating func phase(_ run: PresenceSnapshot.Run, was: PresenceState.Phase, _ now: Date) -> PresenceState.Phase {
        if run.paused || run.running { releasedAt = nil }
        if run.paused { return .paused }
        if run.running {
            switch run.tool?.name {
            case nil: return .thinking
            case "screen": return .looking
            case "hid": return .acting
            default: return .working
            }
        }
        if stopped == run.gen { return .stopped }
        if was == .paused {
            releasedAt = releasedAt ?? now
            return now.timeIntervalSince(releasedAt!) < Self.settle ? .paused : .stopped
        }
        if run.ask != nil { return .asking }
        return run.failed ? .failed : .done
    }

    private func text(_ state: PresenceState, _ run: PresenceSnapshot.Run, _ copy: PresenceCopy) -> String {
        switch state.phase {
        case .thinking: return copy.thinking
        case .looking, .acting, .working: return run.tool.map { $0.desc.isEmpty ? copy.action($0) : $0.desc } ?? copy.thinking
        case .asking: return state.ask.map { $0.question.isEmpty ? copy.chooseOne : $0.question } ?? copy.chooseOne
        case .paused: return copy.pausedHint
        case .done: return run.result.isEmpty ? copy.finished : run.result
        case .failed: return Self.reason(run.result).isEmpty ? copy.unfinished : Self.reason(run.result)
        case .stopped: return copy.stoppedAt(state.step)
        }
    }

    /// The engine's error line without its sentinel.
    static func reason(_ text: String) -> String {
        var text = text
        for marker in ["!!!Error:", "[Error:"] where text.hasPrefix(marker) { text.removeFirst(marker.count) }
        return text.trimmingCharacters(in: CharacterSet(charactersIn: " ]"))
    }
}
