import XCTest
@testable import PresenceCore

private typealias Run = PresenceSnapshot.Run

private func sample(_ cid: String = "a", gen: Int = 1, running: Bool = true, tool: String? = nil, action: String = "",
                 desc: String = "", step: Int = 0, phone: Bool = true, stopping: Bool = false, paused: Bool = false,
                 ask: [String]? = nil, question: String = "选哪个？", result: String = "", failed: Bool = false,
                 title: String = "点一杯咖啡", trail: [String] = []) -> Run {
    Run(cid: cid, gen: gen, running: running, stopping: stopping, title: title, step: step,
        tool: tool.map { .init(name: $0, action: action, desc: desc) }, trail: trail,
        ask: ask.map { .init(question: question, candidates: $0) }, paused: paused, usedPhone: phone,
        result: result, failed: failed)
}

private func shot(_ runs: Run..., lang: String = "zh") -> PresenceSnapshot { PresenceSnapshot(lang: lang, runs: runs) }

final class PresenceTrackerTests: XCTestCase {
    func testCardLinkSelectsItsConversationWithoutEncodingAnAction() throws {
        for cid in ["a", "聊天 / ?&+#"] {
            let url = PresenceLink.url(cid: cid)
            XCTAssertEqual(PresenceLink.conversation(url), cid)
            XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.count, 1)
        }
        for raw in ["https://presence?cid=a", "gagent://elsewhere?cid=a", "gagent://presence", "gagent://presence?cid="] {
            XCTAssertNil(PresenceLink.conversation(try XCTUnwrap(URL(string: raw))))
        }
    }
    private var tracker = PresenceTracker()
    private var clock = Date(timeIntervalSince1970: 1_000)

    @discardableResult private func fold(_ runs: Run..., after seconds: TimeInterval = 1, phoneActive: Bool = false,
                                         lang: String = "zh") -> PresenceState? {
        clock += seconds
        return tracker.fold(PresenceSnapshot(lang: lang, runs: runs), now: clock, phoneActive: phoneActive)
    }

    func testATaskStartsOnlyOnceARunningConversationUsesThePhone() {
        XCTAssertNil(fold(sample(phone: false)), "a chat-only run is not followed")
        XCTAssertNil(fold(sample(running: false, phone: true)), "nor is one that already ended")
        XCTAssertEqual(fold(sample(tool: "screen"))?.phase, .looking)
        XCTAssertEqual(tracker.state?.title, "点一杯咖啡")
    }

    func testAScriptDrivingThePhoneIsAdoptedOnlyWhenItIsTheOnlyRun() {
        XCTAssertNil(fold(sample("a", phone: false), sample("b", phone: false), phoneActive: true))
        XCTAssertEqual(fold(sample("b", tool: "code_run", phone: false), phoneActive: true)?.cid, "b")
    }

    func testThePhaseFollowsTheCallInFlight() {
        let cases: [(String?, String, String, PresenceState.Phase, String)] = [
            (nil, "", "", .thinking, "思考下一步"),
            ("screen", "", "", .looking, "查看屏幕"),
            ("hid", "tap", "点击「去结算」", .acting, "点击「去结算」"),
            ("hid", "type", "", .acting, "输入文字"),
            ("hid", "pinch", "", .acting, "操作手机"),
            ("code_run", "", "", .working, "运行脚本"),
            ("web_scan", "", "", .working, "处理中"),
        ]
        for (tool, action, desc, phase, text) in cases {
            let state = fold(sample(tool: tool, action: action, desc: desc, step: 3))
            XCTAssertEqual(state?.phase, phase, "\(tool ?? "none")")
            XCTAssertEqual(state?.now, text)
            XCTAssertEqual(state?.step, 3)
        }
        XCTAssertEqual(fold(sample(step: 0))?.step, 1, "the first turn is step 1 even before it completes")
    }

    func testTheClockOfAPhaseRestartsOnlyWhenThePhaseChanges() {
        let began = fold(sample(tool: "hid"))!
        let same = fold(sample(tool: "hid", desc: "下一下"))!
        let next = fold(sample(tool: "screen"))!
        XCTAssertEqual(same.phaseSince, began.phaseSince)
        XCTAssertGreaterThan(next.phaseSince, began.phaseSince)
        XCTAssertEqual(next.startedAt, began.startedAt)
    }

    func testAQuestionAndItsAnswerAreOneTask() {
        fold(sample(tool: "hid", step: 4))
        let asking = fold(sample(running: false, step: 5, ask: ["科技园店", "大学城店"], question: "从哪一家下单？"))!
        XCTAssertEqual(asking.phase, .asking)
        XCTAssertEqual(asking.now, "从哪一家下单？")
        XCTAssertEqual(asking.ask?.choices, ["科技园店", "大学城店"])
        let resumed = fold(sample(gen: 2, tool: "screen", step: 1, phone: false, title: "科技园店"))!
        XCTAssertEqual(resumed.phase, .looking)
        XCTAssertEqual(resumed.step, 6, "steps continue across the answer")
        XCTAssertEqual(resumed.title, "点一杯咖啡", "the answer does not become the task's title")
        XCTAssertNil(resumed.ask)
        XCTAssertEqual(resumed.startedAt, asking.startedAt)
    }

    func testHandingBackDoesNotLookLikeAnEndedTask() {
        fold(sample(tool: "hid", step: 2))
        XCTAssertEqual(fold(sample(paused: true))?.phase, .paused, "paused wins while the aborted turn winds down")
        XCTAssertEqual(fold(sample(running: false, step: 2, paused: true))?.now.hasPrefix("GAgent 已松开键鼠"), true)
        XCTAssertEqual(fold(sample(running: false, step: 2), after: 0.5)?.phase, .paused, "ticket cleared, next turn not started yet")
        let resumed = fold(sample(gen: 2, step: 0, phone: false), after: 0.5)!
        XCTAssertEqual(resumed.phase, .thinking)
        XCTAssertEqual(resumed.step, 2)
    }

    func testAHandoffEndedWithoutANewTurnIsStopped() {
        fold(sample(tool: "hid", step: 2)); fold(sample(running: false, step: 2, paused: true))
        XCTAssertEqual(fold(sample(running: false, step: 2), after: 1)?.phase, .paused)
        let ended = fold(sample(running: false, step: 2), after: PresenceTracker.settle)!
        XCTAssertEqual(ended.phase, .stopped)
        XCTAssertEqual(ended.now, "已在第 2 步停止")
    }

    func testAStopIsToldFromFinishing() {
        fold(sample(tool: "hid", step: 3))
        tracker.stopRequested()
        XCTAssertEqual(fold(sample(tool: "hid", step: 3))?.phase, .acting, "still winding down")
        XCTAssertEqual(fold(sample(running: false, step: 3, result: "半截回复"))?.phase, .stopped)

        tracker = PresenceTracker()
        fold(sample(tool: "hid")); fold(sample(stopping: true))
        XCTAssertEqual(fold(sample(running: false))?.phase, .stopped, "a stop from the chat page is seen while it happens")

        tracker = PresenceTracker()
        fold(sample(tool: "hid")); fold(sample(running: false, ask: [], question: "电话用哪个？"))
        tracker.stopRequested()
        XCTAssertEqual(fold(sample(running: false, ask: [], question: "电话用哪个？"))?.phase, .stopped, "stopping instead of answering")
    }

    func testFinishingAndFailing() {
        fold(sample(tool: "hid", step: 11))
        let done = fold(sample(running: false, step: 12, result: "已下单，预计 14:35 送到。"))!
        XCTAssertEqual([done.phase.rawValue, done.now], ["done", "已下单，预计 14:35 送到。"])
        XCTAssertTrue(done.ended && !done.running)

        tracker = PresenceTracker()
        fold(sample(tool: "hid", step: 7))
        let failed = fold(sample(running: false, step: 8, result: "!!!Error: HTTP 429 too many requests", failed: true))!
        XCTAssertEqual([failed.phase.rawValue, failed.now], ["failed", "HTTP 429 too many requests"])
        XCTAssertEqual(PresenceTracker.reason("[Error: no provider]"), "no provider")

        tracker = PresenceTracker()
        fold(sample(tool: "hid")); XCTAssertEqual(fold(sample(running: false))?.now, "任务已完成")
    }

    func testAnEndedTaskStaysUntilTheNextOneStarts() {
        fold(sample(tool: "hid", step: 2))
        let done = fold(sample(running: false, step: 3, result: "好了"))!
        XCTAssertEqual(fold(sample(running: false, step: 3, result: "好了", failed: true)), done, "an ended task is not derived again")
        XCTAssertEqual(fold(sample(gen: 2, phone: false, title: "谢谢")), done, "a chat reply afterwards is not a phone task")
        let next = fold(sample(gen: 3, tool: "screen", step: 1, title: "再点一杯"))!
        XCTAssertEqual([next.title, "\(next.step)"], ["再点一杯", "1"])
        XCTAssertGreaterThan(next.startedAt, done.startedAt)
        tracker.dismiss()
        XCTAssertNil(tracker.state)
    }

    func testACardThatOutlivedTheProcessIsContinuedByTheNextTurn() {
        fold(sample(tool: "hid", step: 4))
        let waiting = fold(sample(running: false, step: 5, ask: [], question: "电话用哪个？"))!
        tracker = PresenceTracker()                                   // the process was recycled while waiting
        XCTAssertNil(fold(sample(gen: 1, phone: false, title: "尾号 2046")), "a restarted engine alone starts nothing")
        tracker.adopt(waiting)
        let resumed = fold(sample(gen: 1, tool: "screen", step: 1, phone: false, title: "尾号 2046"))!
        XCTAssertEqual([resumed.phase.rawValue, resumed.title, "\(resumed.step)"], ["looking", "点一杯咖啡", "6"])
    }

    func testADeletedConversationDropsItsTask() {
        fold(sample("a", tool: "hid"))
        XCTAssertNil(fold(sample("b", running: false)))
    }

    func testOtherConversationsDoNotDisturbTheFollowedOne() {
        fold(sample("a", tool: "hid", step: 2))
        XCTAssertEqual(fold(sample("b", tool: "screen", step: 9), sample("a", tool: "screen", step: 3))?.step, 3)
    }

    func testLanguageFollowsTheEngine() {
        let state = fold(sample(tool: "screen", step: 2), lang: "en")!
        XCTAssertTrue(state.english)
        XCTAssertEqual(state.now, "Reading the screen")
        XCTAssertEqual(PresenceCopy(english: true).word(state), "2")
        XCTAssertEqual(PresenceCopy(english: false).word(state), "2步")
    }
}

final class PresenceStateTests: XCTestCase {
    private func state(_ phase: PresenceState.Phase, choices: [String]? = nil) -> PresenceState {
        PresenceState(cid: "a", phase: phase, title: "", step: 1, now: "", trail: [],
                      ask: choices.map { .init(question: "?", choices: $0) }, startedAt: .distantPast,
                      phaseSince: .distantPast, english: false)
    }

    func testOnlyAFewShortChoicesFitOnTheIsland() {
        func quick(_ choices: String...) -> Bool { PresenceState.Ask(question: "", choices: choices).quick }
        XCTAssertTrue(quick("是", "否"))
        XCTAssertTrue(quick("科技园店 · 1.2 km", "大学城店 · 2.0 km"), "two buttons share the row")
        XCTAssertTrue(quick("微信支付", "支付宝", "银行卡"))
        XCTAssertFalse(quick("科技园店 · 1.2 km", "大学城店", "其他"), "three buttons leave less room each")
        XCTAssertTrue(quick("我已经在另一台设备上确认过了"), "one button has the whole row")
        XCTAssertFalse(quick("这个候选项实在太长了一整行按钮也放不下它所以只能打字"))
        XCTAssertFalse(quick("a", "b", "c", "d"))
        XCTAssertFalse(quick())
    }

    func testOnlyTheUsersTurnAndTheOutcomeInterrupt() {
        let running = state(.acting), quick = state(.asking, choices: ["是", "否"]), typed = state(.asking, choices: [])
        let table: [(PresenceState?, PresenceState, Bool, Bool, PresenceAlert, String)] = [
            (nil, running, false, true, .none, "starting"),
            (running, state(.looking), false, true, .none, "progress"),
            (running, quick, false, true, .island, "a tap answers it"),
            (running, typed, false, true, .notification, "typing needs the reply field"),
            (running, quick, false, false, .notification, "no Live Activity to ring on"),
            (running, quick, true, true, .none, "the chat is in front"),
            (quick, quick, false, true, .none, "nothing changed"),
            (quick, typed, false, true, .notification, "a new question while waiting"),
            (running, state(.paused), false, true, .none, "the user did that"),
            (running, state(.done), false, true, .island, "done"),
            (running, state(.failed), false, false, .notification, "failed, no island"),
            (running, state(.stopped), false, true, .none, "the user did that"),
        ]
        for (old, new, active, live, expected, why) in table {
            XCTAssertEqual(new.alert(after: old, appActive: active, liveActivity: live), expected, why)
        }
    }

    func testWordsForEveryPhase() {
        let copy = PresenceCopy(english: false)
        let expected: [(PresenceState.Phase, String, String)] = [
            (.thinking, "1步", "正在思考"), (.looking, "1步", "正在看屏"), (.acting, "1步", "正在操作"), (.working, "1步", "正在处理"),
            (.asking, "等你", "需要你回答"), (.paused, "暂停", "你在操作"), (.done, "完成", "已完成"),
            (.failed, "出错", "没有完成"), (.stopped, "已停", "已停止"),
        ]
        for (phase, word, status) in expected {
            XCTAssertEqual(copy.word(state(phase)), word)
            XCTAssertEqual(copy.status(state(phase)), status)
        }
        XCTAssertEqual(copy.status(state(.asking, choices: ["是", "否"])), "需要你决定")
        XCTAssertEqual(copy.stepLabel(state(.failed)), "停在第 1 步")
    }

    func testQuestionTokenSurvivesSnapshotTrackerAndActivityEncoding() throws {
        let json = #"{"question":"选哪个？","candidates":["Red","Green"],"reply_token":"process:41"}"#
        let ask = try JSONDecoder().decode(PresenceSnapshot.Ask.self, from: Data(json.utf8))
        var tracker = PresenceTracker()
        let now = Date()
        _ = tracker.fold(shot(sample(tool: "screen")), now: now)
        var run = sample(running: false, ask: [])
        run.ask = ask
        let waiting = try XCTUnwrap(tracker.fold(shot(run), now: now.addingTimeInterval(1)))
        XCTAssertEqual(waiting.ask?.replyToken, "process:41")
        let restored = try JSONDecoder().decode(PresenceState.self, from: JSONEncoder().encode(waiting))
        XCTAssertEqual(restored.ask, waiting.ask)
        run.ask?.replyToken = "process:42"
        let next = try XCTUnwrap(tracker.fold(shot(run), now: now.addingTimeInterval(2)))
        XCTAssertEqual(next.alert(after: waiting, appActive: false, liveActivity: true), .island,
                       "the same wording in a new question is a new interruption")
    }

    func testOldQuestionsDecodeWithoutGrantingAReplyToken() throws {
        let snapshot = try JSONDecoder().decode(PresenceSnapshot.Ask.self,
            from: Data(#"{"question":"Old question","candidates":["Yes"]}"#.utf8))
        let activity = try JSONDecoder().decode(PresenceState.Ask.self,
            from: Data(#"{"question":"Old question","choices":["Yes"]}"#.utf8))
        XCTAssertNil(snapshot.replyToken)
        XCTAssertNil(activity.replyToken)
        XCTAssertEqual(activity.choices, ["Yes"], "old cards remain readable")
    }

    func testContinuationSurvivesQuestionsAndOtherRunningConversations() {
        XCTAssertFalse(shot().needsContinuation)
        XCTAssertFalse(shot(sample(running: false)).needsContinuation)
        XCTAssertTrue(shot(sample(tool: nil)).needsContinuation, "thinking still needs execution time")
        let question = sample("a", running: false, ask: ["是", "否"])
        XCTAssertTrue(shot(question).needsContinuation, "answering in the background must retain the lease")
        let paused = sample("a", running: false, paused: true, ask: ["是", "否"])
        XCTAssertFalse(shot(paused).needsContinuation, "explicit takeover yields execution")
        XCTAssertTrue(shot(paused, sample("b")).needsContinuation)
        XCTAssertTrue(shot(sample("a", running: false), question).needsContinuation)
        XCTAssertFalse(shot(paused, sample("b", running: false, failed: true)).needsContinuation)
    }

    func testTheEnginesReplyDecodesAndAnythingElseIsEmpty() {
        let json = #"{"v":1,"lang":"zh","runs":[{"cid":"c1","gen":7,"running":true,"stopping":false,"title":"点咖啡","step":2,"tool":{"name":"hid","action":"type","desc":"输入收货电话"},"trail":["打开外卖应用"],"ask":null,"paused":false,"used_phone":true,"final":"","failed":false}]}"#
        let run = PresenceSnapshot.decode(json).runs[0]
        XCTAssertEqual([run.cid, run.tool?.action, run.trail[0]], ["c1", "type", "打开外卖应用"])
        XCTAssertTrue(run.usedPhone)
        for junk in [nil, "", "引擎未就绪", #"{"error":"unknown_engine_fn"}"#, #"{"v":2,"runs":[{"cid":1}]}"#] {
            XCTAssertTrue(PresenceSnapshot.decode(junk).runs.isEmpty)
        }
    }
}
