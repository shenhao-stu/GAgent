import ActivityKit
import SwiftUI
import WidgetKit

/// The Dynamic Island and the Lock Screen card. Both draw `PresenceState` and nothing else.
///
/// Compact and minimal change by one symbol and one word, well under the share of the screen that the
/// agent's own screen reading counts as motion. The large presentations appear on their own only when the
/// app rings for the user's turn or the outcome, which is when the agent is not reading the screen.
struct PresenceLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: PresenceAttributes.self) { context in
            PresenceCard(look: PresenceLook(context.state, stale: context.isStale), detail: context.attributes.lockDetail)
                .padding(.horizontal, 17).padding(.vertical, 12)
                .activityBackgroundTint(Color.black.opacity(0.74))
                .activitySystemActionForegroundColor(.white)
                .widgetURL(PresenceLink.url(cid: context.state.cid))
        } dynamicIsland: { context in
            let look = PresenceLook(context.state, stale: context.isStale)
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { PresenceMark(look: look).padding(.leading, 4) }
                DynamicIslandExpandedRegion(.trailing) { PresenceMeter(look: look).padding(.trailing, 4) }
                DynamicIslandExpandedRegion(.center) { PresenceHeading(look: look, compact: true) }
                DynamicIslandExpandedRegion(.bottom) {
                    PresenceBody(look: look, compact: true, detail: true).padding(.horizontal, 4).padding(.top, 4)
                }
            } compactLeading: {
                PresenceGlyph(look: look)
            } compactTrailing: {
                Text(look.word).font(.system(size: 14.5, weight: .semibold)).monospacedDigit()
                    .foregroundStyle(look.wordTint).frame(minWidth: 30, alignment: .trailing)
            } minimal: {
                PresenceGlyph(look: look)
            }
            .keylineTint(look.state.phase == .asking ? .orange : nil)
            .widgetURL(PresenceLink.url(cid: context.state.cid))
        }
    }
}
