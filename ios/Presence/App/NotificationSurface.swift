import UserNotifications

/// Questions that need typing, and every interruption when there is no Live Activity to ring on.
/// The reply field and the buttons act in place: the app handles them in the background, so the app the
/// agent was working in stays in front.
///
/// The notification centre has one delegate and the app already set its own; this one stands in front of
/// it, answers for Presence's notifications and passes every other one through unchanged.
@MainActor final class NotificationSurface: NSObject, UNUserNotificationCenterDelegate {
    private weak var previous: UNUserNotificationCenterDelegate?
    private var asked: String?     // identifier of the question on screen

    private static let prefix = "ga.presence.", category = "ga.presence.ask"
    private var center: UNUserNotificationCenter { .current() }

    func install() {
        guard center.delegate !== self else { return }
        previous = center.delegate
        center.delegate = self
    }

    /// Asks for permission if it was never asked. Called only while GAgent is in front with no task running:
    /// a system prompt in the middle of a task would sit in front of the app the agent is working in.
    func prepare() { center.requestAuthorization(options: [.alert, .sound]) { _, _ in } }

    func show(_ state: PresenceState?, ring: Bool) {
        let identifier = state.flatMap { state -> String? in
            guard state.phase == .asking, let ask = state.ask else { return nil }
            return Self.prefix + "ask." + state.cid + "." + (ask.replyToken ?? "legacy")
        }
        if let asked, asked != identifier {
            center.removeDeliveredNotifications(withIdentifiers: [asked])
            center.removePendingNotificationRequests(withIdentifiers: [asked])
            self.asked = nil
        }
        guard ring, let state else { return }
        let copy = PresenceCopy(english: state.english), content = UNMutableNotificationContent()
        content.sound = .default
        content.threadIdentifier = Self.prefix + state.cid
        content.userInfo = ["cid": state.cid, "choices": state.ask?.choices ?? []]
        guard let ask = state.ask, let identifier else {
            content.title = state.phase == .done ? copy.doneTitle : copy.failedTitle
            content.body = state.now
            return post(content, Self.prefix + "end." + state.cid)
        }
        // Reaching here with choices means they did not fit on the island, or there is no island:
        // list them in the text and offer them as buttons when they are few.
        let listed = ask.choices.enumerated().map { "\(Self.letter($0)) \($1)" }.joined(separator: "\n")
        content.title = copy.needsYou
        content.body = [state.now, listed].filter { !$0.isEmpty }.joined(separator: "\n")
        content.categoryIdentifier = Self.category
        content.userInfo["reply_token"] = ask.replyToken
        content.userInfo["resume_prompt"] = copy.resumePrompt
        let locked: UNNotificationActionOptions = [.authenticationRequired]
        var actions = ask.choices.count <= 3 ? ask.choices.enumerated().map {
            UNNotificationAction(identifier: "choice.\($0)", title: $1, options: locked)
        } : []
        actions.append(UNTextInputNotificationAction(identifier: "reply", title: copy.reply, options: locked,
                                                     textInputButtonTitle: copy.send, textInputPlaceholder: copy.replyHint))
        actions.append(UNNotificationAction(identifier: "resume", title: copy.doneContinue, options: locked))
        actions.append(UNNotificationAction(identifier: "stop", title: copy.stopTask, options: [.destructive]))
        let category = UNNotificationCategory(identifier: Self.category, actions: actions, intentIdentifiers: [])
        asked = identifier
        center.getNotificationCategories { [center] others in
            Task { @MainActor in
                guard self.asked == identifier else { return }
                center.setNotificationCategories(others.filter { $0.identifier != Self.category }.union([category]))
                self.post(content, identifier)
            }
        }
    }

    private func post(_ content: UNNotificationContent, _ identifier: String) {
        center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: nil))
    }

    private static func letter(_ index: Int) -> String { String(UnicodeScalar(UInt8(65 + index % 26))) }

    private static func command(_ response: UNNotificationResponse) -> (PresenceCommand, String)? {
        let choices = response.notification.request.content.userInfo["choices"] as? [String] ?? []
        switch response.actionIdentifier {
        case "reply": return ((response as? UNTextInputNotificationResponse)?.userText).map { (.answer, $0) }
        case "resume": return (response.notification.request.content.userInfo["resume_prompt"] as? String).map { (.answer, $0) }
        case "stop": return (.stop, "")
        case let id where id.hasPrefix("choice."):
            return Int(id.dropFirst(7)).flatMap { choices.indices.contains($0) ? (.answer, choices[$0]) : nil }
        default: return nil     // the notification itself was tapped: the app opens on the chat
        }
    }

    // MARK: UNUserNotificationCenterDelegate

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        Task { @MainActor in
            if notification.request.identifier.hasPrefix(Self.prefix) { return done([.banner, .sound, .list]) }
            guard let previous, previous.responds(to: #selector(UNUserNotificationCenterDelegate.userNotificationCenter(_:willPresent:withCompletionHandler:)))
            else { return done([]) }
            previous.userNotificationCenter?(center, willPresent: notification, withCompletionHandler: done)
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler done: @escaping () -> Void) {
        Task { @MainActor in
            let request = response.notification.request
            guard request.identifier.hasPrefix(Self.prefix) else {
                guard let previous, previous.responds(to: #selector(UNUserNotificationCenterDelegate.userNotificationCenter(_:didReceive:withCompletionHandler:)))
                else { return done() }
                return previous.userNotificationCenter?(center, didReceive: response, withCompletionHandler: done) ?? done()
            }
            if let (command, text) = Self.command(response), let cid = request.content.userInfo["cid"] as? String {
                await PresenceActions.perform(command, cid: cid, text: text,
                                              replyToken: request.content.userInfo["reply_token"] as? String)
            }
            done()
        }
    }
}
