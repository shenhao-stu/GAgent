import Foundation

/// Every word the status UI shows, for both languages, in one place.
struct PresenceCopy {
    var english: Bool

    private func t(_ zh: String, _ en: String) -> String { english ? en : zh }

    func status(_ state: PresenceState) -> String {
        switch state.phase {
        case .thinking: return t("正在思考", "Thinking")
        case .looking: return t("正在看屏", "Reading the screen")
        case .acting: return t("正在操作", "Operating")
        case .working: return t("正在处理", "Working")
        case .asking: return state.ask?.quick == true ? t("需要你决定", "Needs your choice") : t("需要你回答", "Needs your answer")
        case .paused: return t("你在操作", "You are in control")
        case .done: return t("已完成", "Done")
        case .failed: return t("没有完成", "Not completed")
        case .stopped: return t("已停止", "Stopped")
        }
    }

    /// The one word beside the island's symbol.
    func word(_ state: PresenceState) -> String {
        switch state.phase {
        case .thinking, .looking, .acting, .working: return t("\(state.step)步", "\(state.step)")
        case .asking: return t("等你", "You")
        case .paused: return t("暂停", "Paused")
        case .done: return t("完成", "Done")
        case .failed: return t("出错", "Error")
        case .stopped: return t("已停", "Ended")
        }
    }

    func stepLabel(_ state: PresenceState) -> String {
        switch state.phase {
        case .done: return t("\(state.step) 步", "\(state.step) steps")
        case .failed, .stopped: return t("停在第 \(state.step) 步", "Stopped at step \(state.step)")
        default: return t("第 \(state.step) 步", "Step \(state.step)")
        }
    }

    /// What a tool call does, when the model wrote no caption for it.
    func action(_ tool: PresenceSnapshot.Tool) -> String {
        switch (tool.name, tool.action) {
        case ("screen", _): return t("查看屏幕", "Reading the screen")
        case ("hid", "tap"): return t("点击屏幕", "Tapping")
        case ("hid", "swipe"): return t("滑动屏幕", "Swiping")
        case ("hid", "type"), ("hid", "stage_text"): return t("输入文字", "Typing")
        case ("hid", "key"): return t("按键", "Pressing a key")
        case ("hid", "button"): return t("系统手势", "System gesture")
        case ("hid", _): return t("操作手机", "Operating the phone")
        case ("code_run", _): return t("运行脚本", "Running a script")
        case ("ask_user", _): return t("准备提问", "Preparing a question")
        default: return t("处理中", "Working")
        }
    }

    var thinking: String { t("思考下一步", "Thinking about the next step") }
    var chooseOne: String { t("请选择", "Please choose") }
    var pausedHint: String { t("GAgent 已松开键鼠，不会再点击。处理完后交还。", "GAgent has let go of the mouse and keyboard. Hand back when you are done.") }
    var finished: String { t("任务已完成", "The task is finished") }
    var unfinished: String { t("任务没有完成", "The task did not finish") }
    func stoppedAt(_ step: Int) -> String { t("已在第 \(step) 步停止", "Stopped at step \(step)") }
    var stale: String { t("连接中断", "Connection lost") }
    var staleWord: String { t("中断", "Lost") }
    var staleHint: String { t("很久没有收到进度。打开 GAgent 查看。", "No progress for a while. Open GAgent to check.") }
    var hidden: String { t("解锁后查看详情", "Unlock to see details") }

    var waited: String { t("等了 ", "Waiting ") }
    var pausedFor: String { t("已暂停 ", "Paused ") }
    var took: String { t("用时 ", "Took ") }
    var released: String { t("键鼠已松开", "input released") }

    var takeOver: String { t("我来操作", "Take over") }
    var stop: String { t("停止", "Stop") }
    var handBack: String { t("交还给 GAgent", "Hand back") }
    var handingBack: String { t("正在交还…", "Handing back…") }
    var end: String { t("结束", "End") }
    var doneContinue: String { t("我已完成，继续", "Done, continue") }
    var answer: String { t("去回答", "Answer") }
    var details: String { t("查看详情", "Details") }
    var open: String { t("打开 GAgent", "Open GAgent") }

    var needsYou: String { t("GAgent 需要你回答", "GAgent needs your answer") }
    var reply: String { t("回复…", "Reply…") }
    var send: String { t("发送", "Send") }
    var replyHint: String { t("输入你的回答", "Type your answer") }
    var stopTask: String { t("停止任务", "Stop the task") }
    var doneTitle: String { t("GAgent 已完成", "GAgent finished") }
    var failedTitle: String { t("GAgent 没有完成", "GAgent did not finish") }

    /// The settings page's two rows, under the keys they have in the page's word table.
    var settings: [String: String] {
        ["gaPresenceLive": t("灵动岛与锁屏显示进度", "Progress on Dynamic Island"),
         "gaPresenceLock": t("锁屏显示步骤内容", "Step details on Lock Screen")]
    }

    /// The turn sent when the user hands the phone back, from any Presence surface.
    var resumePrompt: String {
        t("我已完成接管，请从当前状态继续原任务，保留已完成的结果。",
          "I have finished taking over. Continue the original task from the current state, preserving completed work.")
    }
}
