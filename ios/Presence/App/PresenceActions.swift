import Foundation

/// The only things the status UI asks of the engine, all through entry points the chat page already uses:
/// stop a run (`abort2`), start or end a handoff (`phone_takeover`) and send the user's next turn (`send2`).
/// What those do, and how the engine goes on after a handoff, is the engine's business and is not changed here.
@MainActor enum PresenceActions {
    /// One pending hand-back per conversation. Stop retires it so a late reply cannot send another turn.
    private static var returning: [String: UUID] = [:]
    /// Sends a turn on the chat page, when the command was given there, so that the page draws it as its own:
    /// true = sent, false = rejected/cancelled, nil = this page cannot handle the conversation.
    typealias Page = (_ cid: String, _ text: String) async -> Bool?

    static func perform(_ command: PresenceCommand, cid: String, text: String, replyToken: String? = nil, page: Page? = nil) async {
        let returningID = command == .resume ? UUID() : nil
        if let returningID {
            guard returning[cid] == nil else { return }
            returning[cid] = returningID
        }
        defer {
            if let returningID, returning[cid] == returningID { returning[cid] = nil }
        }
        if command == .stop {
            returning[cid] = nil
            PresenceCoordinator.shared.stopRequested()
            PhoneRunActivity.shared.cancel()
        }
        guard await engineReady() else { return DebugLog.write("presence: engine not ready, \(command.rawValue) dropped") }
        if command == .resume, returning[cid] != returningID { return }
        let coordinator = PresenceCoordinator.shared
        switch command {
        case .stop:
            if let ticket = await handoff(cid) {
                _ = await engine("phone_takeover", cid, "cancel", ticket)
            } else {
                _ = await engine("abort2", cid)
            }
        case .pause:
            // The engine returns once it has also stopped the run, which can wait for the model call in flight.
            let asked = Date()
            let answer = await reply("phone_takeover", cid, "pause")
            if answer["ok"] as? Bool == true {
                DebugLog.write(String(format: "presence: takeover returned after %.1f s", Date().timeIntervalSince(asked)))
            } else {
                DebugLog.write("presence: takeover not started: \(answer["error"] as? String ?? "no reply")")
            }
        case .resume:
            guard let ticket = await handoff(cid), returning[cid] == returningID else {
                DebugLog.write("presence: hand-back rejected, no current handoff")
                break
            }
            guard let returningID, await handBack(cid, ticket, returningID), returning[cid] == returningID else { break }
            // On the chat page the turn is the page's to send; anywhere else it goes to the engine directly.
            let prompt = coordinator.copy.resumePrompt
            let sent = await page?(cid, prompt)
            guard returning[cid] == returningID else { break }
            if sent == false { break }
            if sent == nil, !(await send(cid, prompt)) { break }
            DebugLog.write("presence: handed back; the turn was sent by the \(sent == true ? "page" : "engine")")
        case .answer:
            guard let replyToken, !replyToken.isEmpty else {
                DebugLog.write("presence: answer rejected, missing question token")
                break
            }
            _ = await send(cid, text, replyToken: replyToken)
        }
        coordinator.wake()
    }

    private static func send(_ cid: String, _ text: String, replyToken: String? = nil) async -> Bool {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        let result: String?
        if let replyToken { result = await engine("send2", cid, text, replyToken) }
        else { result = await engine("send2", cid, text) }
        guard result == "" else {
            DebugLog.write("presence: send rejected: \(result ?? "no reply")")
            return false
        }
        PresenceCoordinator.shared.adopt(cid)
        return true
    }

    /// The ticket of the handoff this conversation is in, if it is in one.
    private static func handoff(_ cid: String) async -> String? {
        let status = await reply("phone_takeover", cid, "status")
        return status["paused"] as? Bool == true ? status["token"] as? String : nil
    }

    /// The engine refuses to resume while the paused turn is still winding down (the chat page disables its own
    /// Resume for that time). On the phone a tap some 20 s after the pause was refused, and given up on after
    /// 1.5 s it did nothing at all; a minute later the same tap worked (2026-11-13). So the tap is kept for as
    /// long as this handoff is still the conversation's, and what the engine answered is logged.
    private static func handBack(_ cid: String, _ ticket: String, _ request: UUID) async -> Bool {
        let began = Date()
        for attempt in 0..<180 {
            guard returning[cid] == request else { return false }
            let answer = await reply("phone_takeover", cid, "resume", ticket)
            guard returning[cid] == request else { return false }
            if answer["ok"] as? Bool == true {
                if attempt > 0 { DebugLog.write(String(format: "presence: handed back after waiting %.1f s", Date().timeIntervalSince(began))) }
                return true
            }
            if attempt == 0 { DebugLog.write("presence: hand-back waits: \(answer["error"] as? String ?? "no reply")") }
            let status = await reply("phone_takeover", cid, "status")
            guard status["paused"] as? Bool == true, status["token"] as? String == ticket else { return false }
            try? await Task.sleep(for: .seconds(0.5))
        }
        return false
    }

    private static func reply(_ fn: String, _ args: String...) async -> [String: Any] {
        let text = await Task.detached { PyRuntime.shared.call(fn: fn, args: args) }.value
        return text?.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
    }

    private static func engine(_ fn: String, _ args: String...) async -> String? {
        await Task.detached { PyRuntime.shared.call(fn: fn, args: args) }.value
    }

    /// A button can start the process in the background; the Python engine takes a few seconds to come up.
    private static func engineReady() async -> Bool {
        for _ in 0..<40 where !PyRuntime.shared.ready { try? await Task.sleep(for: .seconds(0.25)) }
        return PyRuntime.shared.ready
    }
}
