import Foundation

/// Identifies the expiring, device-local item GAgent wrote. Validate the revision without reading someone else's clipboard.
struct StagedPaste {
    let text: String
    let changeCount: Int
    let expires: Date

    func valid(changeCount: Int, now: Date) -> Bool { self.changeCount == changeCount && now < expires }
}
