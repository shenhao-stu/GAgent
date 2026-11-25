import ReplayKit
import SwiftUI

struct ReplayBroadcastControl: View {
    let active: Bool

    var body: some View {
        VStack(spacing: 12) {
            BroadcastPicker().frame(width: 56, height: 56)
                .padding(8)
                .background((active ? Color.red : Color.accentColor).opacity(0.08), in: Circle())
            Text(active ? "屏幕正在共享" : "共享 iPhone 屏幕").font(.headline)
            Text(active ? "轻点上方按钮管理共享。停止后，GA 会停止操作。"
                        : "轻点上方按钮，选择 GAgent，再点“开始直播”。")
                .font(.subheadline).foregroundStyle(.secondary)
            Text("按需读取截图 · 蓝牙键鼠操作")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }
}

private struct BroadcastPicker: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = CenteredBroadcastPicker(frame: CGRect(x: 0, y: 0, width: 56, height: 56))
        picker.preferredExtension = Bundle.main.bundleIdentifier.map { $0 + ".broadcast" }
        picker.showsMicrophoneButton = false
        return picker
    }

    func updateUIView(_ view: RPSystemBroadcastPickerView, context: Context) {}
}

private final class CenteredBroadcastPicker: RPSystemBroadcastPickerView {
    override func layoutSubviews() {
        super.layoutSubviews()
        // Some system versions retain a 5pt origin for the button after resizing the picker.
        for case let button as UIButton in subviews {
            button.center = CGPoint(x: bounds.midX, y: bounds.midY)
            if button.image(for: .normal) == nil {
                let symbol = UIImage.SymbolConfiguration(pointSize: 24, weight: .semibold)
                button.setImage(UIImage(systemName: "record.circle", withConfiguration: symbol), for: .normal)
                button.tintColor = .label
            }
        }
    }
}
