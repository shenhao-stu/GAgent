import Foundation

/// What every Presence surface draws: the island, the Lock Screen, the notification and the in-app strip.
/// Surfaces keep no state of their own, so they cannot disagree.
struct PresenceState: Codable, Hashable {
    enum Phase: String, Codable {
        case thinking, looking, acting, working     // the agent has the phone
        case asking                                 // it is the user's turn
        case paused                                 // the user has the phone
        case done, failed, stopped
    }

    struct Ask: Codable, Hashable {
        var question: String
        var choices: [String]
        var replyToken: String? = nil
        /// Few and short enough to be buttons in one row of the island; anything else needs typing.
        /// Width is counted in half-width units: a CJK character takes two, an ASCII one takes one.
        var quick: Bool {
            guard (1...3).contains(choices.count) else { return false }
            let room = [40, 20, 12][choices.count - 1]
            return choices.allSatisfy { $0.unicodeScalars.reduce(0) { $0 + ($1.isASCII ? 1 : 2) } <= room }
        }
    }

    var cid: String
    var phase: Phase
    var title: String           // the user's request, first line
    var step: Int               // turns so far; a question and its answer continue the count
    var now: String             // the action in flight, the question, or the outcome
    var trail: [String]         // the last finished steps, oldest first
    var ask: Ask?
    var startedAt: Date
    var phaseSince: Date
    var english: Bool

    var running: Bool { [.thinking, .looking, .acting, .working].contains(phase) }
    var ended: Bool { [.done, .failed, .stopped].contains(phase) }
}

enum PresenceAlert { case none, island, notification }

/// Card navigation carries only the conversation to open; it never resumes or sends input.
enum PresenceLink {
    static func url(cid: String) -> URL {
        var parts = URLComponents()
        parts.scheme = "gagent"; parts.host = "presence"
        parts.queryItems = [URLQueryItem(name: "cid", value: cid)]
        return parts.url!
    }

    static func conversation(_ url: URL) -> String? {
        guard url.scheme == "gagent", url.host == "presence",
              let cid = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?
                .first(where: { $0.name == "cid" })?.value, !cid.isEmpty else { return nil }
        return cid
    }
}

extension PresenceState {
    /// How to interrupt the user for the change from `old` to this state. Progress never interrupts.
    /// A question that one tap can answer rings on the island; one that needs typing arrives as a
    /// notification with a reply field, and the island only changes colour. Nothing rings while GAgent
    /// itself is in front: the chat already shows it.
    func alert(after old: PresenceState?, appActive: Bool, liveActivity: Bool) -> PresenceAlert {
        guard !appActive, old?.phase != phase || old?.ask != ask else { return .none }
        switch phase {
        case .asking: return liveActivity && ask?.quick == true ? .island : .notification
        case .done, .failed: return liveActivity ? .island : .notification
        default: return .none
        }
    }
}
