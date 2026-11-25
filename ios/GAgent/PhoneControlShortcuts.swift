import AppIntents


struct OpenPhoneControlIntent: AppIntent {
    static var title: LocalizedStringResource = "打开 iPhone 操作"
    static var openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult {
        BoardSetupPresenter.present()
        return .result()
    }
}

struct StopPhoneControlIntent: AppIntent {
    static var title: LocalizedStringResource = "停止 iPhone 操作"
    static var openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult {
        PhoneRunActivity.shared.cancel()
        return .result()
    }
}

struct PhoneControlShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: OpenPhoneControlIntent(), phrases: ["打开 \(.applicationName) 的 iPhone 操作"],
                    shortTitle: "iPhone 操作", systemImageName: "iphone")
        AppShortcut(intent: StopPhoneControlIntent(), phrases: ["停止 \(.applicationName) 操作"],
                    shortTitle: "停止操作", systemImageName: "stop.circle")
    }
}
