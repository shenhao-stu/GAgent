import UIKit
import XCTest
@testable import BoardKitHarness

final class ScreenElementsTests: XCTestCase {
    private typealias Text = ScreenElements.Text

    func testDetailKeepsRequestedPixelRegionAndRejectsOutsideCoordinates() throws {
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let source = UIGraphicsImageRenderer(size: CGSize(width: 200, height: 400), format: format).image { context in
            UIColor.red.setFill(); context.fill(CGRect(x: 0, y: 0, width: 200, height: 200))
            UIColor.blue.setFill(); context.fill(CGRect(x: 0, y: 200, width: 200, height: 200))
        }
        let jpeg = try XCTUnwrap(source.jpegData(compressionQuality: 1))
        let detail = try ScreenElements.detail(jpeg, region: ["x": 0, "y": 0.5, "width": 1, "height": 0.5])
        let image = try XCTUnwrap(UIImage(data: detail)?.cgImage)
        XCTAssertEqual(image.width, 400)
        XCTAssertEqual(image.height, 400)
        var pixel = [UInt8](repeating: 0, count: 4)
        let context = try XCTUnwrap(CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8,
            bytesPerRow: 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        XCTAssertGreaterThan(pixel[2], 220)
        XCTAssertLessThan(pixel[0], 30)
        for invalid: [String: Any] in [
            ["x": 0.8, "y": 0, "width": 0.3, "height": 0.5],
            ["x": false, "y": 0, "width": 1, "height": 1],
            ["x": 0, "y": 0, "width": 0, "height": 1]] {
            XCTAssertThrowsError(try ScreenElements.detail(jpeg, region: invalid))
        }
        XCTAssertEqual(ScreenElements.Reading.skipped.sources, ["ocr": "skipped", "detector": "skipped"])
    }

    func testDetailAcceptsASinglePixelRegionAndRejectsNonfiniteSizes() throws {
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let source = UIGraphicsImageRenderer(size: CGSize(width: 200, height: 400), format: format).image { context in
            UIColor.blue.setFill(); context.fill(CGRect(x: 0, y: 0, width: 200, height: 400))
        }
        let jpeg = try XCTUnwrap(source.jpegData(compressionQuality: 1))
        let detail = try ScreenElements.detail(jpeg, region: ["x": 0.5, "y": 0.5, "width": 0.005, "height": 0.0025])
        let image = try XCTUnwrap(UIImage(data: detail)?.cgImage)
        XCTAssertEqual(image.width, 2)
        XCTAssertEqual(image.height, 2)
        for width in [0, -.infinity, .nan] as [Double] {
            XCTAssertThrowsError(try ScreenElements.detail(jpeg, region: ["x": 0, "y": 0, "width": width, "height": 1]))
        }
    }

    func testElementsKeepCompleteRecognizedTextWithAndWithoutAControl() {
        let label = String(repeating: "长", count: 60) + "完整结尾"
        let line = Text(box: CGRect(x: 0.12, y: 0.22, width: 0.65, height: 0.03), string: label)
        let control = CGRect(x: 0.1, y: 0.2, width: 0.7, height: 0.08)
        for controls in [[], [control]] {
            let elements = ScreenElements.merge(controls: controls, texts: [line])
            XCTAssertEqual(elements.first?.label, label)
            XCTAssertTrue(elements.first?.summary.contains("完整结尾") == true)
        }
    }

    func testRecognitionSourcesFailIndependentlyWithoutInventingElements() async throws {
        let line = Text(box: CGRect(x: 0.1, y: 0.2, width: 0.2, height: 0.03), string: "发送")
        let textOnly = try await ScreenElements.read(text: { [line] }, controls: nil)
        XCTAssertEqual(textOnly.elements.map(\.label), ["发送"])
        XCTAssertEqual(textOnly.sources, ["ocr": "ok", "detector": "unavailable"])
        let noControls = try await ScreenElements.read(text: { [line] }, controls: { throw DeviceError(message: "model") })
        XCTAssertEqual(noControls.elements, textOnly.elements)
        XCTAssertEqual(noControls.detector, .failed)
        let noText = try await ScreenElements.read(text: { throw DeviceError(message: "ocr") }, controls: { [line.box] })
        XCTAssertEqual(noText.elements.count, 1)
        XCTAssertNil(noText.elements[0].label)
        XCTAssertEqual(noText.ocr, .failed)
        let rawOnly = try await ScreenElements.read(text: { throw DeviceError(message: "ocr") }, controls: nil)
        XCTAssertTrue(rawOnly.elements.isEmpty)
        XCTAssertFalse(rawOnly.cacheable)
        do {
            _ = try await ScreenElements.read(text: { throw CancellationError() }, controls: nil)
            XCTFail("Cancellation must propagate")
        } catch { XCTAssertTrue(error is CancellationError) }
    }

    func testControlsTakeTheTextTheyContainAndLeftoverTextStandsAlone() {
        let send = CGRect(x: 0.82, y: 0.86, width: 0.1, height: 0.05)
        let plus = CGRect(x: 0.92, y: 0.58, width: 0.06, height: 0.03)
        let elements = ScreenElements.merge(
            controls: [send, plus],
            texts: [Text(box: CGRect(x: 0.84, y: 0.875, width: 0.06, height: 0.02), string: "发送"),
                    Text(box: CGRect(x: 0.3, y: 0.07, width: 0.4, height: 0.02), string: "项目讨论群 (119)")])
        XCTAssertEqual(elements.map(\.label), ["项目讨论群 (119)", nil, "发送"], "reading order: title, plus, send")
        XCTAssertEqual(elements.map(\.id), [1, 2, 3])
        XCTAssertEqual(elements[2].box, send, "the control keeps its own box, so its centre is the tap point")
        XCTAssertEqual(elements[1].summary, "2 [icon] @0.950,0.595")
    }

    func testDetectorFragmentsOfOneTextLineGiveWayToTheLine() {
        let line = Text(box: CGRect(x: 0.1, y: 0.2, width: 0.8, height: 0.03), string: "这就是我授权的最终文本")
        let word = CGRect(x: 0.3, y: 0.2, width: 0.1, height: 0.03)
        let elements = ScreenElements.merge(controls: [word], texts: [line])
        XCTAssertEqual(elements.count, 1)
        XCTAssertEqual(elements[0].label, line.string)
        XCTAssertEqual(elements[0].box, line.box)
    }

    func testContainersAndSpecksAreNotTapTargets() {
        let sheet = CGRect(x: 0, y: 0.4, width: 1, height: 0.6)
        let speck = CGRect(x: 0.5, y: 0.5, width: 0.002, height: 0.002)
        let key = CGRect(x: 0.03, y: 0.69, width: 0.08, height: 0.05)
        XCTAssertEqual(ScreenElements.merge(controls: [sheet, speck, key], texts: []).map(\.box), [key])
    }

    func testTextIsAssignedToTheSmallestControlThatHoldsIt() {
        let row = CGRect(x: 0.02, y: 0.45, width: 0.96, height: 0.07)
        let badge = CGRect(x: 0.6, y: 0.46, width: 0.2, height: 0.03)
        let elements = ScreenElements.merge(controls: [row, badge],
                                            texts: [Text(box: CGRect(x: 0.62, y: 0.465, width: 0.15, height: 0.02), string: "速度还快")])
        XCTAssertEqual(elements.first { $0.box == badge }?.label, "速度还快")
        XCTAssertNil(elements.first { $0.box == row }?.label)
    }

    func testMarkedFrameKeepsItsSizeAndChangesPixels() throws {
        let frame = try XCTUnwrap(UIGraphicsImageRenderer(size: CGSize(width: 360, height: 780)).image { context in
            UIColor.black.setFill(); context.fill(CGRect(x: 0, y: 0, width: 360, height: 780))
        }.jpegData(compressionQuality: 0.9))
        let element = ScreenElement(id: 12, box: CGRect(x: 0.4, y: 0.4, width: 0.2, height: 0.1), label: nil)
        let marked = try XCTUnwrap(ScreenElements.marked(frame, [element]))
        XCTAssertEqual(try XCTUnwrap(UIImage(data: marked)).size, try XCTUnwrap(UIImage(data: frame)).size)
        XCTAssertTrue(Vision.changed(frame, marked, near: element.center))
    }
}
