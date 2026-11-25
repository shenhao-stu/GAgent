import Foundation

/// The engine's sessions as `ios/py/presence_snapshot.py` reports them. Read-only on both sides.
struct PresenceSnapshot: Decodable {
    struct Tool: Decodable {
        var name: String
        var action: String
        var desc: String
    }

    struct Ask: Decodable {
        var question: String
        var candidates: [String]
        var replyToken: String? = nil

        enum CodingKeys: String, CodingKey {
            case question, candidates
            case replyToken = "reply_token"
        }
    }

    struct Run: Decodable {
        var cid: String
        var gen: Int
        var running: Bool
        var stopping: Bool
        var title: String
        var step: Int
        var tool: Tool?
        var trail: [String]
        var ask: Ask?
        var paused: Bool
        var usedPhone: Bool
        var result: String
        var failed: Bool

        enum CodingKeys: String, CodingKey {
            case cid, gen, running, stopping, title, step, tool, trail, ask, paused, failed
            case usedPhone = "used_phone", result = "final"
        }
    }

    var lang: String?
    var runs: [Run]

    /// A question can resume from the island, where a new foreground-only lease cannot be requested.
    var needsContinuation: Bool { runs.contains { $0.running || (!$0.paused && $0.ask != nil) } }

    static let empty = PresenceSnapshot(lang: nil, runs: [])

    /// An engine that is not ready, or a reply this build cannot read, is simply "nothing is running".
    static func decode(_ json: String?) -> PresenceSnapshot {
        guard let data = json?.data(using: .utf8) else { return .empty }
        return (try? JSONDecoder().decode(PresenceSnapshot.self, from: data)) ?? .empty
    }
}
