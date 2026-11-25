import Foundation

/// Owns the user's pause. Observation validity belongs to ScreenService and the conversation's host.
struct PhoneTakeover {
    private(set) var token: String?
    var paused: Bool { token != nil }

    mutating func pause() -> String {
        let value = UUID().uuidString
        token = value
        return value
    }

    mutating func resume(_ value: String) -> Bool {
        guard let token, token == value else { return false }
        self.token = nil
        return true
    }

}
