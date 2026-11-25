import UIKit
import XCTest
@testable import BoardKitHarness

final class ScreenRecognitionTests: XCTestCase {
    private let labels = ["保存草稿", "取消操作", "继续测试", "Upload", "蓝牙设置", "网络权限", "删除记录", "返回首页"]

    // These ReplayKit frames expose device-only Chinese omissions and pointer-over-English misreads.
    func testChineseButtonsInCapturedFramesKeepTheirCoordinates() async throws {
        try await checkCapturedButtons("chinese-buttons")
    }

    func testPointerOverEnglishButtonKeepsBothLanguagesAndCoordinates() async throws {
        try await checkCapturedButtons("pointer-upload")
    }

    private func checkCapturedButtons(_ prefix: String) async throws {
        for page in 0...1 {
            let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "\(prefix)-\(page)", withExtension: "jpg"))
            let reading = try await ScreenService.readElements(Data(contentsOf: url))
            XCTAssertEqual(reading.ocr, .ok)
            let slots = page == 0 ? [0, 1, 2, 3] : [1, 4, 3, 0]
            for (index, slot) in slots.enumerated() {
                let text = try XCTUnwrap(reading.texts.first { $0.string == labels[index] }, "\(prefix) page \(page): \(labels[index])")
                let button = CGRect(x: 0.065 + Double(slot % 2) * 0.48, y: 0.28 + Double(slot / 2) * 0.17,
                                    width: 0.39, height: 62.0 / 932)
                XCTAssertTrue(button.contains(CGPoint(x: text.box.midX, y: text.box.midY)), "wrong coordinates: \(text)")
                XCTAssertEqual(reading.texts.filter { $0.string == text.string }.count, 1)
            }
        }
    }

    func testColoredDarkAndLowContrastButtonsRemainReadable() async throws {
#if targetEnvironment(simulator)
        throw XCTSkip("Run on a physical iPhone: the simulator's Vision model has different dark-text failures.")
#else
        for variant in 0..<8 {
            let format = UIGraphicsImageRendererFormat(); format.scale = 1
            var buttons: [CGRect] = []
            let png = UIGraphicsImageRenderer(size: CGSize(width: 740, height: 1600), format: format).pngData { context in
                let dark = variant % 3 == 1
                (dark ? UIColor.black : UIColor.white).setFill()
                context.fill(CGRect(x: 0, y: 0, width: 740, height: 1600))
                for (index, label) in labels.enumerated() {
                    let box = CGRect(x: 30 + (index % 2) * 355 + variant * 2,
                                     y: 280 + (index / 2) * 220 + variant * 3, width: 295, height: 94)
                    buttons.append(CGRect(x: box.minX / 740, y: box.minY / 1600,
                                          width: box.width / 740, height: box.height / 1600))
                    let background = variant == 6 ? UIColor(red: 0.02, green: 0.66, blue: 0.02, alpha: 1)
                        : variant == 7 ? .white : dark ? UIColor(white: 0.15, alpha: 1)
                        : UIColor(red: 0.89, green: 0.94, blue: 1, alpha: 1)
                    background.setFill()
                    UIBezierPath(roundedRect: box, cornerRadius: 14).fill()
                    let paragraph = NSMutableParagraphStyle(); paragraph.alignment = .center
                    let color: UIColor = variant == 6 ? .red : variant == 7 ? UIColor(white: 0.72, alpha: 1)
                        : dark ? .white : variant % 3 == 2 ? .systemBlue : .black
                    (label as NSString).draw(in: box.insetBy(dx: 0, dy: 27), withAttributes: [
                        .font: UIFont.systemFont(ofSize: CGFloat(24 + variant * 2), weight: .medium),
                        .foregroundColor: color, .paragraphStyle: paragraph])
                }
            }
            let reading = try await ScreenService.readElements(png)
            XCTAssertEqual(reading.ocr, .ok)
            for (index, label) in labels.enumerated() {
                let text = try XCTUnwrap(reading.texts.first { $0.string == label }, "variant \(variant): \(label)")
                XCTAssertTrue(buttons[index].contains(CGPoint(x: text.box.midX, y: text.box.midY)))
            }
        }
#endif
    }
}
