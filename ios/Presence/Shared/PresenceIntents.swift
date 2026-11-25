import AppIntents

/// What a button on the island, the Lock Screen, a notification or the in-app strip asks GAgent to do.
enum PresenceCommand: String {
    case stop, pause, resume, answer
}

/// Set by the app when it starts. The widget extension needs the intent types only to draw its buttons:
/// the system runs `perform()` in the app's process, so the extension never has a handler.
enum PresenceIntentRouter {
    @MainActor static var perform: ((PresenceCommand, _ cid: String, _ text: String, _ replyToken: String?) async -> Void)?
}

/// Stopping is what makes the phone safe, so it works from a locked screen.
struct PresenceStopIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Stop the GAgent task"
    static var isDiscoverable = false
    static var authenticationPolicy = IntentAuthenticationPolicy.alwaysAllowed

    @Parameter(title: "Conversation") var cid: String

    init() {}
    init(cid: String) { self.cid = cid }

    func perform() async throws -> some IntentResult {
        await PresenceIntentRouter.perform?(.stop, cid, "", nil)
        return .result()
    }
}

/// Taking over, handing back and answering direct the agent, so they wait until the phone is unlocked.
struct PresenceCommandIntent: LiveActivityIntent {
    static var title: LocalizedStringResource = "Direct the GAgent task"
    static var isDiscoverable = false
    static var authenticationPolicy = IntentAuthenticationPolicy.requiresAuthentication

    @Parameter(title: "Command") var command: String
    @Parameter(title: "Conversation") var cid: String
    @Parameter(title: "Text") var text: String
    @Parameter(title: "Question token") var replyToken: String?

    init() {}
    init(_ command: PresenceCommand, cid: String, text: String = "", replyToken: String? = nil) {
        self.command = command.rawValue
        self.cid = cid
        self.text = text
        self.replyToken = replyToken
    }

    func perform() async throws -> some IntentResult {
        if let command = PresenceCommand(rawValue: command), command != .stop {
            await PresenceIntentRouter.perform?(command, cid, text, replyToken)
        }
        return .result()
    }
}
