import QuickLook
import UIKit

/// System renderers own document/media decoding. No GA bridge or editable workspace access is injected.
@MainActor final class FilePreview: QLPreviewController, QLPreviewControllerDataSource {
    private var file: URL!

    static func present(_ relative: String, workspace: URL, shareUnsupported: Bool) -> String {
        guard let file = WorkspaceFile.resolve(relative, in: workspace) else { return "err:not-found" }
        guard var presenter = DeviceScreen.scene?.windows.first(where: \.isKeyWindow)?.rootViewController,
              DeviceScreen.foreground else { return "err:unavailable" }
        while let next = presenter.presentedViewController { presenter = next }
        guard !presenter.isBeingDismissed, !presenter.isBeingPresented else { return "err:unavailable" }
        if canPreview(file as NSURL) {
            let viewer = FilePreview()
            viewer.file = file
            viewer.dataSource = viewer
            presenter.present(viewer, animated: true)
        } else if shareUnsupported {
            let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
            share.popoverPresentationController?.sourceView = presenter.view
            share.popoverPresentationController?.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 1, height: 1)
            presenter.present(share, animated: true)
        } else { return "err:unsupported" }
        return "ok"
    }

    func numberOfPreviewItems(in controller: QLPreviewController) -> Int { 1 }
    func previewController(_ controller: QLPreviewController, previewItemAt index: Int) -> QLPreviewItem { file as NSURL }
}
