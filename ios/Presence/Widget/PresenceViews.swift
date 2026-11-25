import AppIntents
import SwiftUI
import WidgetKit

private let dim = Color.white.opacity(0.56)

/// How a state looks: one symbol, one colour, a few words. Derived on every draw, never stored.
/// Colour says who has the phone: white the agent, orange your turn, grey you, green done, red not done.
struct PresenceLook {
    let state: PresenceState
    let copy: PresenceCopy
    /// The app claimed to be running and then stopped reporting; the card must not keep saying "operating".
    let stale: Bool

    init(_ state: PresenceState, stale: Bool) {
        self.state = state
        copy = PresenceCopy(english: state.english)
        self.stale = stale && state.running
    }

    var symbol: String {
        if stale { return "wifi.slash" }
        switch state.phase {
        case .thinking: return "sparkles"
        case .looking: return "eye.fill"
        case .acting: return "hand.tap.fill"
        case .working: return "gearshape.fill"
        case .asking: return "hand.raised.fill"
        case .paused: return "pause.fill"
        case .done: return "checkmark"
        case .failed: return "exclamationmark.triangle.fill"
        case .stopped: return "stop.fill"
        }
    }

    var tint: Color {
        if stale { return dim }
        switch state.phase {
        case .asking: return .orange
        case .paused, .stopped: return dim
        case .done: return .green
        case .failed: return .red
        default: return .white
        }
    }

    var wordTint: Color { state.phase == .asking || state.phase == .paused || stale ? tint : .white }
    var word: String { stale ? copy.staleWord : copy.word(state) }
    var status: String { stale ? copy.stale : copy.status(state) }
    var text: String { stale ? copy.staleHint : state.now }
    var agentHasPhone: Bool { state.running && !stale }

    static func span(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded()))
        return total >= 3600 ? String(format: "%d:%02d:%02d", total / 3600, total / 60 % 60, total % 60)
                             : String(format: "%d:%02d", total / 60, total % 60)
    }
}

struct PresenceGlyph: View {
    let look: PresenceLook
    var size: CGFloat = 15

    var body: some View {
        Image(systemName: look.symbol).font(.system(size: size, weight: .semibold)).foregroundStyle(look.tint)
            .contentTransition(.symbolEffect(.replace))
    }
}

/// The square at the head of the large presentations: the GA mark while the agent works, the state's symbol otherwise.
struct PresenceMark: View {
    let look: PresenceLook
    var side: CGFloat = 34

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: side * 0.3, style: .continuous)
                .fill(look.agentHasPhone ? Color.white.opacity(0.13) : look.tint.opacity(0.2))
            if look.agentHasPhone {
                Text("GA").font(.system(size: side * 0.38, weight: .heavy)).kerning(0.5).foregroundStyle(.white)
            } else {
                PresenceGlyph(look: look, size: side * 0.5)
            }
        }
        .frame(width: side, height: side)
    }
}

extension PresenceLook {
    /// Time is drawn by the system from a date, so it runs without any update from the app and shows a
    /// stall honestly. There is no progress bar: nobody knows how many steps a task will take.
    var clock: Text {
        switch state.phase {
        case .asking: return Text(copy.waited) + Text(state.phaseSince, style: .timer)
        case .paused: return Text(copy.pausedFor) + Text(state.phaseSince, style: .timer)
        case .done, .failed, .stopped:
            return Text(copy.took + PresenceLook.span(state.phaseSince.timeIntervalSince(state.startedAt)))
        default: return Text(state.startedAt, style: .timer)
        }
    }
}

struct PresenceMeter: View {
    let look: PresenceLook

    var body: some View {
        VStack(alignment: .trailing, spacing: 1) {
            Text(look.copy.stepLabel(look.state)).font(.system(size: 15, weight: .semibold)).lineLimit(1).fixedSize()
            look.clock.font(.system(size: 12.5)).foregroundStyle(dim)
                .multilineTextAlignment(.trailing).lineLimit(1).frame(maxWidth: 104, alignment: .trailing)
        }
        .monospacedDigit().foregroundStyle(.white)
    }
}

struct PresenceHeading: View {
    let look: PresenceLook
    var compact = false

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            if !compact { Text(look.state.title).font(.system(size: 12.5)).foregroundStyle(dim) }
            Text(look.status).font(.system(size: 15, weight: .semibold))
                .foregroundStyle(look.state.phase == .asking ? look.tint : .white)
        }
        .lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct PresenceBody: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let look: PresenceLook
    var compact = false
    /// False on a Lock Screen that must not show what the task is about.
    let detail: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 8 : 12) {
            if !(compact && typeSize.isAccessibilitySize) {
                if detail { words } else { Text(look.copy.hidden).font(.caption).foregroundStyle(dim).lineLimit(1) }
            }
            PresenceControls(look: look, compact: compact, detail: detail)
        }
        .foregroundStyle(.white)
    }

    @ViewBuilder private var words: some View {
        let state = look.state
        if look.agentHasPhone {
            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    PresenceGlyph(look: look).frame(width: 18)
                    Text(state.now).font(.system(size: 16.5, weight: .semibold)).lineLimit(compact || typeSize > .large ? 1 : 2)
                }
                if !compact && !state.trail.isEmpty {
                    Text(state.trail.map { "✓ " + $0 }.joined(separator: "　")).font(.system(size: 12.5))
                        .foregroundStyle(dim).lineLimit(1).padding(.leading, 26)
                }
            }
        } else {
            Text(look.text).font(typeSize.isAccessibilitySize ? .caption : .callout)
                .foregroundStyle(state.phase == .paused || look.stale ? dim : .white)
                .lineLimit(compact || typeSize > .large ? 1 : 2)
        }
    }
}

/// The buttons under the words. They act in place: the system runs their intents in GAgent's process
/// without bringing GAgent to the front, so the app the agent was working in stays where it is.
struct PresenceControls: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let look: PresenceLook
    var compact = false
    /// False where the choices of a question must not be readable; they are the question's content too.
    let detail: Bool

    private enum Kind { case neutral, primary, amber, danger }

    var body: some View {
        let state = look.state, copy = look.copy
        if look.stale || state.ended {
            open(state.phase == .done && !look.stale ? copy.details : copy.open)
        } else if state.phase == .paused {
            HStack(spacing: 9) {
                command(.resume, copy.handBack, "play.fill", .primary)
                stop(copy.end).frame(width: 96)
            }
        } else if let ask = state.ask, state.phase == .asking {
            if !detail || typeSize.isAccessibilitySize {
                HStack(spacing: 9) {
                    open(copy.answer)
                    stop(typeSize.isAccessibilitySize ? nil : copy.stop).frame(width: typeSize.isAccessibilitySize ? 44 : 96)
                }
            } else if ask.quick {
                HStack(spacing: 6) {
                    ForEach(ask.choices, id: \.self) { command(.answer, $0, nil, .primary, text: $0) }
                    stop(nil).frame(width: 44)
                }
            } else {
                HStack(spacing: 9) {
                    command(.answer, copy.doneContinue, "play.fill", .amber, text: copy.resumePrompt)
                    open(copy.answer).frame(width: 84)
                    stop(nil).frame(width: 46)
                }
            }
        } else {
            HStack(spacing: 9) {
                command(.pause, copy.takeOver, "pause.fill", .neutral)
                stop(copy.stop)
            }
        }
    }

    private func command(_ command: PresenceCommand, _ title: String, _ symbol: String?, _ kind: Kind,
                         text: String = "") -> some View {
        Button(intent: PresenceCommandIntent(command, cid: look.state.cid, text: text,
                                             replyToken: command == .answer ? look.state.ask?.replyToken : nil)) { pill(title, symbol, kind) }
            .buttonStyle(.plain).accessibilityLabel(title)
    }

    private func stop(_ title: String?) -> some View {
        Button(intent: PresenceStopIntent(cid: look.state.cid)) { pill(title, "stop.fill", .danger) }
            .buttonStyle(.plain).accessibilityLabel(look.copy.stop)
    }

    /// Opens GAgent on the task; a tap anywhere else on the card does the same.
    private func open(_ title: String) -> some View {
        Link(destination: PresenceLink.url(cid: look.state.cid)) { pill(title + " ›", nil, .neutral) }
    }

    private func pill(_ title: String?, _ symbol: String?, _ kind: Kind) -> some View {
        HStack(spacing: 6) {
            if let symbol { Image(systemName: symbol).font(.system(size: 12, weight: .bold)) }
            if let title, !(typeSize.isAccessibilitySize && symbol != nil) {
                Text(title).font(.callout.weight(.semibold)).lineLimit(1).minimumScaleFactor(0.75)
            }
        }
        .padding(.horizontal, 10).frame(maxWidth: .infinity, minHeight: 44)
        .foregroundStyle(kind == .primary || kind == .amber ? Color.black
                         : kind == .danger ? Color(red: 1, green: 0.41, blue: 0.38) : Color.white)
        .background(kind == .primary ? Color.white : kind == .amber ? Color.orange : Color.white.opacity(0.17), in: Capsule())
    }
}

/// The Lock Screen card, and the banner on phones without a Dynamic Island.
struct PresenceCard: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let look: PresenceLook
    let detail: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            if !typeSize.isAccessibilitySize {
                HStack(spacing: 9) {
                    PresenceMark(look: look, side: 24)
                    Text("GAgent · " + look.status).font(.system(size: 12.5, weight: asking ? .semibold : .regular))
                        .foregroundStyle(asking ? look.tint : dim).lineLimit(1).layoutPriority(1)
                    Spacer(minLength: 8)
                    (Text(look.copy.stepLabel(look.state) + " · ") + look.clock)
                        .font(.system(size: 12.5)).monospacedDigit().foregroundStyle(dim)
                        .multilineTextAlignment(.trailing).lineLimit(1).minimumScaleFactor(0.8)
                }
            }
            PresenceBody(look: look, detail: detail)
        }
    }

    private var asking: Bool { look.state.phase == .asking }
}
