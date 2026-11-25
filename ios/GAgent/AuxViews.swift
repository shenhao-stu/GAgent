import UIKit
import WebKit
import AVFoundation

/// 二维码扫描: AVCapture QR → window.gaQrResult('<text>') (契约同 Android)。
final class QrScan: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
    private let session = AVCaptureSession()
    private var onResult: ((String?) -> Void)?
    private var done = false

    static func present(over web: WKWebView?, prompt: String? = nil, onResult: @escaping (String?) -> Void) {
        guard let root = web?.window?.rootViewController else { onResult(nil); return }
        let vc = QrScan(); vc.onResult = onResult; vc.promptText = prompt; vc.modalPresentationStyle = .fullScreen
        root.present(vc, animated: true)
    }

    static func present(over web: WKWebView?) {
        present(over: web) { text in
            guard let t = text else { return }
            let esc = t.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "'", with: "\\'")
            web?.evaluateJavaScript("try{window.gaQrResult&&window.gaQrResult('\(esc)')}catch(e){}")
        }
    }

    private var promptText: String?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        AVCaptureDevice.requestAccess(for: .video) { [weak self] ok in
            DispatchQueue.main.async { ok ? self?.startScan() : self?.finish(nil) }
        }
        let close = UIButton(type: .close)
        close.frame = CGRect(x: 16, y: 56, width: 44, height: 44)
        close.addAction(UIAction { [weak self] _ in self?.finish(nil) }, for: .touchUpInside)
        view.addSubview(close)
        if let p = promptText {
            let l = UILabel(); l.text = p; l.textColor = .white; l.textAlignment = .center; l.numberOfLines = 2
            l.font = .systemFont(ofSize: 15); l.translatesAutoresizingMaskIntoConstraints = false
            view.addSubview(l)
            NSLayoutConstraint.activate([l.centerXAnchor.constraint(equalTo: view.centerXAnchor),
                                         l.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -40),
                                         l.leadingAnchor.constraint(greaterThanOrEqualTo: view.leadingAnchor, constant: 24),
                                         l.trailingAnchor.constraint(lessThanOrEqualTo: view.trailingAnchor, constant: -24)])
        }
    }

    private func startScan() {
        guard let dev = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: dev) else { return finish(nil) }
        session.addInput(input)
        let out = AVCaptureMetadataOutput()
        session.addOutput(out)
        out.setMetadataObjectsDelegate(self, queue: .main)
        out.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.frame = view.bounds; layer.videoGravity = .resizeAspectFill
        view.layer.insertSublayer(layer, at: 0)
        DispatchQueue.global().async { self.session.startRunning() }
    }

    func metadataOutput(_ o: AVCaptureMetadataOutput, didOutput objs: [AVMetadataObject], from c: AVCaptureConnection) {
        guard let qr = objs.compactMap({ $0 as? AVMetadataMachineReadableCodeObject }).first,
              let text = qr.stringValue else { return }
        finish(text)
    }

    private func finish(_ text: String?) {
        guard !done else { return }
        done = true
        session.stopRunning()
        let cb = onResult; onResult = nil
        dismiss(animated: true) { cb?(text) }
    }
}

/// HTML 预览 (GA.previewHtml 后端): 无桥隔离 WKWebView 模态, 镜像 Android HtmlPreviewActivity 的安全边界。
enum HtmlPreview {
    static func present(fileURL: URL) {
        guard let root = UIApplication.shared.connectedScenes
            .compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else { return }
        let vc = UIViewController()
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.loadFileURL(fileURL, allowingReadAccessTo: fileURL.deletingLastPathComponent())
        vc.view = web
        root.present(UINavigationController(rootViewController: vc), animated: true)
    }
}
