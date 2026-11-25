import SwiftUI
import UIKit

@MainActor enum BoardSetupPresenter {
    static func present() {
        guard DeviceScreen.foreground,
              var controller = DeviceScreen.scene?.windows.first(where: \.isKeyWindow)?.rootViewController else { return }
        while let presented = controller.presentedViewController { controller = presented }
        if controller is UIHostingController<BoardSetupView> { return }
        controller.present(UIHostingController(rootView: BoardSetupView()), animated: true)
    }
}

@MainActor struct BoardSetupView: View {
    @ObservedObject private var session = BoardSession.shared
    @ObservedObject private var board = BoardSession.shared.board
    @ObservedObject private var pointer = BoardSession.shared.pointer
    @ObservedObject private var calibrator = BoardSession.shared.calibrator
    @ObservedObject private var runActivity = PhoneRunActivity.shared
    @AppStorage("gagent.boardPreviewVisible") private var showPreview = false
    @AppStorage("gagent.boardProcessVisible") private var showProcess = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    @State private var expandedStep: Int?
    @State private var notice = ""
    @State private var inputNotice = ""
    @State private var changing = false
    @State private var previousIdleTimer = false

    private var screenReady: Bool { session.screenSharingActive }
    private var steps: [Bool] { [board.connected, session.inputAvailable, screenReady, session.calibrationReady] }
    private var nextStep: Int { (steps.firstIndex(of: false) ?? 4) + 1 }
    private var occupied: Bool { session.busy || session.testingLink || calibrator.busy || changing }
    private var nextAction: String {
        if !session.consent { return "请先开启操作授权" }
        if !board.connected { return "下一步：连接 ESP32" }
        if !session.hidReady { return "下一步：配对无线键鼠" }
        if !session.inputAvailable { return "下一步：开启辅助触控" }
        if !screenReady { return "下一步：共享 iPhone 屏幕" }
        if !session.calibrationReady { return "下一步：校准指针" }
        return session.ready ? "可以开始任务" : "正在等待画面更新"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    overview
                    connection
                    inputDevice
                    screenCapture
                    calibration
                    monitor
                    advanced
                    if !notice.isEmpty { BoardSetupHint(notice, symbol: "info.circle") }
                    if !session.lastError.isEmpty { BoardSetupHint(session.lastError, symbol: "exclamationmark.circle") }
                    Text("ESP32 需保持供电，手机无需 USB 数据线。")
                        .font(.footnote).foregroundStyle(.secondary)
                }.padding(16)
            }
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("iPhone 操作")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(session.ready ? "完成" : "关闭", action: returnToChat)
                        .accessibilityHint("关闭设置并返回对话")
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) { stopBar }
            .onChange(of: nextStep) { old, _ in
                if expandedStep == old { expandedStep = nil }
            }
            .onAppear {
                previousIdleTimer = UIApplication.shared.isIdleTimerDisabled
                UIApplication.shared.isIdleTimerDisabled = true
                session.probe.install(BoardCalibrationOverlay(calibrator: calibrator, probe: session.probe))
                if board.pairedID == nil { board.scan() }
            }
            .onDisappear {
                if calibrator.boardOpen { calibrator.cancel() }
                board.stopScan()
                UIApplication.shared.isIdleTimerDisabled = previousIdleTimer
                NativeKit.shared.webView?.evaluateJavaScript("window.GAIOS && window.GAIOS.refresh()")
            }
        }.tint(.blue)
    }

    private var overview: some View {
        Toggle(isOn: $session.consent) {
            VStack(alignment: .leading, spacing: 4) {
                Text("允许 GAgent 操作").font(.headline)
                Text("允许获取当前画面并使用键鼠。你可以随时停止。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.boardSetupCard()
    }

    private func expanded(_ step: Int) -> Binding<Bool> {
        Binding(get: { (expandedStep ?? nextStep) == step }, set: { expandedStep = $0 ? step : 0 })
    }

    private var connection: some View {
        BoardSetupStep(number: 1, title: "连接 ESP32", summary: board.connected ? board.name : "保持通电，靠近手机",
                       complete: board.connected, expanded: expanded(1)) {
            if board.connected {
                Label("蓝牙控制已连接", systemImage: "checkmark.circle.fill").foregroundStyle(.tint)
                Button("刷新状态") { run { try await board.refreshStatus(); _ = try await board.readNet(refresh: true) } }
                    .buttonStyle(.bordered).controlSize(.large).disabled(occupied)
            } else {
                ForEach(board.found) { found in
                    Button { board.pair(found.id) } label: {
                        HStack {
                            Label(found.name, systemImage: "cpu")
                            Spacer()
                            Image(systemName: "chevron.right")
                        }.frame(minHeight: 32)
                    }.buttonStyle(.bordered).disabled(board.connecting || board.linking)
                }
                Button { board.scan() } label: {
                    Label(board.scanning ? "正在寻找附近设备…" : "查找附近设备", systemImage: "dot.radiowaves.left.and.right")
                        .frame(maxWidth: .infinity, minHeight: 28)
                }.buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(board.scanning || board.connecting || board.linking)
                if board.connecting || board.linking { ProgressView("正在建立安全连接…") }
                BoardSetupHint("关闭其他正在连接板子的 App，再选择你的设备。", symbol: "info.circle")
            }
            if !board.lastError.isEmpty { BoardSetupHint(board.lastError, symbol: "exclamationmark.circle") }
        }
    }

    private var inputDevice: some View {
        BoardSetupStep(number: 2, title: "启用无线键鼠", summary: session.inputAvailable ? "键鼠已连接"
                       : session.hidReady ? "已配对 · 请开启辅助触控" : "在 iPhone 系统中配对一次",
                       complete: session.inputAvailable, expanded: expanded(2)) {
            if session.inputAvailable {
                Label("蓝牙键鼠已就绪", systemImage: "computermouse.fill")
                    .foregroundStyle(.tint)
                Text(session.calibrationReady ? "已保存指针校准，无需重复配对。"
                     : "请确认系统辅助触控已开启。稍后的指针校准会验证真实点击位置。")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else if session.hidReady {
                Label("蓝牙键鼠已配对", systemImage: "checkmark.circle").foregroundStyle(.tint)
                Text("打开系统设置 → 辅助功能 → 触控 → 辅助触控，开启辅助触控后返回。配对成功还不代表系统已允许鼠标点击。")
                    .font(.subheadline).foregroundStyle(.secondary)
                Button("打开系统设置") { openSystemSettings() }.buttonStyle(.bordered).controlSize(.large)
            } else {
                if board.status?.hid != "ble" {
                    Button("使用蓝牙键鼠") { selectInput("ble") }
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(!board.connected || occupied || board.status?.hid == nil)
                } else {
                    Label("板子已使用蓝牙模式", systemImage: "checkmark.circle").foregroundStyle(.tint)
                }
                Text("打开系统设置 → 辅助功能 → 触控 → 辅助触控，开启 AssistiveTouch。再进入「设备 → 蓝牙设备」配对 \(board.name.isEmpty ? "ESP32 Agent" : board.name)。")
                    .font(.subheadline).foregroundStyle(.secondary)
                Button("打开系统设置") { openSystemSettings() }.buttonStyle(.bordered).controlSize(.large)
                BoardSetupHint("这里切换的是板子模式。系统配对仍需在设置中完成，返回后会自动检查。", symbol: "hand.tap")
            }
            if !inputNotice.isEmpty { BoardSetupHint(inputNotice, symbol: "info.circle") }
        }
    }

    private var screenCapture: some View {
        BoardSetupStep(number: 3, title: "屏幕共享", summary: screenReady ? "正在共享 · 按需截图" : "共享此 iPhone 的屏幕",
                       complete: screenReady, expanded: expanded(3)) {
            ReplayBroadcastControl(active: screenReady)
        }
    }

    private var calibration: some View {
        BoardSetupStep(number: 4, title: "校准指针", summary: session.calibrationReady
                       ? String(format: "上次测量 · 偏差 ±%.1f%%", (pointer.quality ?? 0) * 100) : "自动对齐点击位置",
                       complete: session.calibrationReady, expanded: expanded(4)) {
            if !session.calibrationReady {
                BoardSetupHint("首次使用按需截图，请在这里验证蓝牙点击能落在目标位置。", symbol: "hand.tap")
            }
            Text("校准期间保持 GAgent 在前台，暂时不要触摸屏幕。改变鼠标速度、输入方式或屏幕方向后需要重新校准。")
                .font(.subheadline).foregroundStyle(.secondary)
            Button { calibrator.calibrate() } label: {
                Label(calibrator.busy ? "正在校准…" : session.calibrationReady ? "重新校准" : "开始自动校准", systemImage: "scope")
                    .frame(maxWidth: .infinity, minHeight: 28)
            }.buttonStyle(.borderedProminent).controlSize(.large)
                .disabled(!calibrator.boardReady || occupied)
            if !session.consent { BoardSetupHint("先开启顶部的操作授权。", symbol: "hand.raised") }
        }
    }

    private var monitor: some View {
        DisclosureGroup("运行与预览") {
            VStack(alignment: .leading, spacing: 16) {
                if #available(iOS 26.0, *) {
                    Toggle(isOn: Binding(get: { runActivity.enabled }, set: { runActivity.setEnabled($0) })) {
                        Label("切换 App 后继续", systemImage: "arrow.triangle.2.circlepath").font(.headline)
                    }
                    Text("由 iPhone 独立执行，无需连接电脑。任务开始时向系统申请持续运行；系统会显示进度和停止按钮，也可能因资源限制结束任务。")
                        .font(.footnote).foregroundStyle(.secondary)
                    if runActivity.state.hasPrefix("unavailable:") {
                        BoardSetupHint("系统暂未允许持续运行。请返回 GAgent 后重试。", symbol: "exclamationmark.circle")
                    } else if !runActivity.enabled {
                        BoardSetupHint("关闭后，切换到其他 App 可能中断任务。", symbol: "pause.circle")
                    }
                    Divider()
                }
                Toggle(isOn: $showPreview) {
                    Label("画面预览", systemImage: "play.rectangle").font(.headline)
                }
                if showPreview {
                    if screenReady, let data = session.previewFrame, let image = UIImage(data: data) {
                        Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 320)
                            .frame(maxWidth: .infinity).background(Color.black)
                            .clipShape(RoundedRectangle(cornerRadius: 16))
                            .accessibilityLabel("最近一次 iPhone 画面")
                    } else {
                        Label(screenReady ? "等待下一次取图" : "等待共享屏幕", systemImage: "rectangle.on.rectangle.slash")
                            .frame(maxWidth: .infinity, minHeight: 120).foregroundStyle(.secondary)
                            .background(Color(uiColor: .tertiarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16))
                    }
                }
                Divider()
                Toggle(isOn: $showProcess) {
                    Label("过程查看", systemImage: "list.bullet.rectangle").font(.headline)
                }
                if showProcess {
                    BoardProcessView(session: session, metrics: session.metrics, board: board, calibrator: calibrator,
                                     screenReady: screenReady, openChat: returnToChat)
                }
                Text("关闭本页后仍可继续任务。停止共享请使用系统广播控件。")
                    .font(.footnote).foregroundStyle(.secondary)
            }.padding(.top, 12)
        }.boardSetupCard()
    }

    private func returnToChat() {
        NativeKit.shared.webView?.evaluateJavaScript("window.GAIOS && window.GAIOS.navigate('assistant')")
        dismiss()
    }

    private var advanced: some View {
        VStack(alignment: .leading, spacing: 16) {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 12) {
                    Button("忘记此板子", role: .destructive) { session.stop(); board.forget() }
                        .disabled(occupied)
                    Link("Based on ESP32 iPhone Agent by Henry Yuan",
                         destination: URL(string: "https://github.com/onehumanbeing/esp32-iphone-agent")!)
                        .font(.footnote)
                    Text("MIT · GAgent 复用 GA 的模型配置。支付、密码和系统授权请亲自处理。")
                        .font(.footnote).foregroundStyle(.secondary)
                }.buttonStyle(.bordered).controlSize(.large).padding(.top, 12)
            } label: { Label("设备选项与关于", systemImage: "slider.horizontal.3").frame(minHeight: 44) }
        }.boardSetupCard()
    }

    private var stopBar: some View {
        let layout = typeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: 8)) : AnyLayout(HStackLayout(spacing: 16))
        return VStack(spacing: 12) {
            layout {
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.testingLink ? "正在测量蓝牙" : calibrator.busy ? "正在校准指针" : session.busy
                         ? "正在操作" : nextAction).font(.subheadline.bold())
                    if !typeSize.isAccessibilitySize {
                        Text(session.consent ? "操作授权已开启" : "操作授权已关闭")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
                Button(role: .destructive) {
                    PhoneRunActivity.shared.cancel()
                    notice = "已请求停止任务"
                } label: {
                    Label("停止任务", systemImage: "stop.fill")
                        .frame(maxWidth: typeSize.isAccessibilitySize ? .infinity : nil, minHeight: 28)
                }
                    .buttonStyle(.bordered).controlSize(.large).tint(.red)
                    .buttonBorderShape(.roundedRectangle(radius: 16))
            }
        }.padding(16).background(.regularMaterial)
    }

    private func openSystemSettings() {
        if let url = URL(string: "App-prefs:") { UIApplication.shared.open(url) }
    }

    private func run<T>(_ operation: @escaping () async throws -> T) {
        guard !changing else { return }
        changing = true
        Task {
            defer { changing = false }
            do { _ = try await operation(); notice = "设备状态已刷新。" }
            catch { notice = error.localizedDescription }
        }
    }

    private func selectInput(_ mode: String) {
        guard !occupied else { return }
        changing = true
        inputNotice = "正在切换输入方式…"
        Task {
            defer { changing = false }
            do {
                try await board.commands.send("hid \(mode)")
                try await board.refreshStatus()
                inputNotice = session.hidReady ? "输入设备已就绪。" : "已切换为蓝牙模式，请完成系统配对。"
            } catch { inputNotice = error.localizedDescription }
        }
    }
}

private struct BoardSetupStep<Content: View>: View {
    let number: Int
    let title: String
    let summary: String
    let complete: Bool
    @Binding var expanded: Bool
    @ViewBuilder let content: Content

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            VStack(alignment: .leading, spacing: 16) { Divider(); content }.padding(.top, 16)
        } label: {
            HStack(spacing: 12) {
                Image(systemName: complete ? "checkmark.circle.fill" : "\(number).circle.fill")
                    .font(.title2).foregroundStyle(complete || expanded ? Color.accentColor : .secondary)
                VStack(alignment: .leading, spacing: 4) {
                    Text(title).font(.headline).foregroundStyle(Color(uiColor: .label))
                    Text(summary).font(.caption).foregroundStyle(Color(uiColor: .secondaryLabel))
                }.frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            }.accessibilityElement(children: .combine)
        }.boardSetupCard()
    }
}

@MainActor private struct BoardProcessView: View {
    @ObservedObject var session: BoardSession
    @ObservedObject var metrics: Metrics
    @ObservedObject var board: BoardLink
    @ObservedObject var calibrator: AutoCalibrator
    let screenReady: Bool
    let openChat: () -> Void

    private var activity: (text: String, symbol: String) {
        if calibrator.busy { return ("正在校准指针", "scope") }
        if session.busy { return ("GA 正在操作手机", "hand.tap") }
        return session.ready ? ("空闲，等待 GA 的下一步", "pause.circle") : ("尚未就绪，完成上方步骤后可执行", "exclamationmark.circle")
    }
    private var picture: String {
        screenReady ? "本机按需截图" : "屏幕共享已关闭"
    }
    private var heartbeat: String {
        guard board.connected else { return "未连接" }
        return metrics.statusAge < 1.5 ? "刚刚" : "\(Int(metrics.statusAge)) 秒前"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            LabeledContent { Text(activity.text) } label: { Label("当前", systemImage: activity.symbol) }
            LabeledContent { Text(picture) } label: { Label("画面", systemImage: "rectangle.on.rectangle") }
            LabeledContent { Text(heartbeat) } label: { Label("板子状态", systemImage: "clock") }
            if !session.lastError.isEmpty { BoardSetupHint(session.lastError, symbol: "exclamationmark.circle") }
            Button("在对话中查看完整执行过程", action: openChat).buttonStyle(.bordered).controlSize(.large)
        }.font(.subheadline)
    }
}

struct BoardSetupHint: View {
    let text: String
    let symbol: String
    init(_ text: String, symbol: String) { self.text = text; self.symbol = symbol }
    var body: some View {
        Label(text, systemImage: symbol).font(.footnote).foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private extension View {
    func boardSetupCard() -> some View {
        padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 24))
    }
}

@MainActor private struct BoardCalibrationOverlay: View {
    @ObservedObject var calibrator: AutoCalibrator
    @ObservedObject var probe: TouchProbe
    var body: some View {
        if calibrator.boardOpen {
            ZStack {
                Canvas { context, size in
                    context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white))
                    for i in 1..<10 {
                        var line = Path()
                        let x = size.width * Double(i) / 10, y = size.height * Double(i) / 10
                        line.move(to: CGPoint(x: x, y: 0)); line.addLine(to: CGPoint(x: x, y: size.height))
                        line.move(to: CGPoint(x: 0, y: y)); line.addLine(to: CGPoint(x: size.width, y: y))
                        context.stroke(line, with: .color(.gray.opacity(0.4)))
                    }
                }.ignoresSafeArea()
                VStack {
                    HStack {
                        Spacer()
                        Button("停止校准") { calibrator.cancel() }
                            .buttonStyle(.borderedProminent).boardProbeArea("cancel", probe)
                    }
                    Spacer()
                    VStack(spacing: 8) {
                        Text(calibrator.phase == .failed ? "校准未通过" : "正在校准，请勿触摸屏幕").font(.headline)
                        if let p = calibrator.progress { Text("\(p.done) / \(p.total)") }
                        if let problem = calibrator.problem { Text(problem).font(.footnote) }
                        if calibrator.phase == .failed {
                            Button("重新校准") { calibrator.calibrate() }
                                .buttonStyle(.borderedProminent).boardProbeArea("retry", probe)
                        }
                    }.padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                }.padding()
            }.environment(\.colorScheme, .light)
        }
    }
}

private extension View {
    func boardProbeArea(_ id: String, _ probe: TouchProbe) -> some View {
        onGeometryChange(for: CGRect.self) { $0.frame(in: .global) } action: { probe.setButtonArea(id, $0) }
            .onDisappear { probe.setButtonArea(id, nil) }
    }
}
