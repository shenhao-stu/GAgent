import CoreGraphics
import XCTest
@testable import BoardKitHarness

final class VisionTests: XCTestCase {
    func testGrayPreservesIntegerWeightsRoundingAndResizePixels() throws {
        let width = 259, height = 257
        var bytes = [UInt8]()
        bytes.reserveCapacity(width * height * 4)
        for i in 0..<(width * height) {
            bytes.append(UInt8(truncatingIfNeeded: i))
            bytes.append(UInt8(truncatingIfNeeded: i >> 8))
            bytes.append(UInt8(truncatingIfNeeded: i * 73))
            bytes.append(255)
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        let image = try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
            bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
            provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        for (w, h) in [(1, 1), (7, 13), (32, 64), (130, 129), (width, height)] {
            var rgba = [UInt8](repeating: 0, count: w * h * 4)
            rgba.withUnsafeMutableBytes { buffer in
                let context = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8,
                    bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
                context.interpolationQuality = .medium
                context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
            }
            var expected = [UInt8]()
            expected.reserveCapacity(w * h)
            for i in 0..<(w * h) {
                let r = Int(rgba[4 * i]) * 299
                let g = Int(rgba[4 * i + 1]) * 587
                let b = Int(rgba[4 * i + 2]) * 114
                expected.append(UInt8((r + g + b + 500) / 1000))
            }
            let result = Vision.gray(image, w, h)
            XCTAssertEqual(result.w, w)
            XCTAssertEqual(result.h, h)
            XCTAssertEqual(result.px, expected, "\(w)×\(h) must preserve every comparison pixel")
        }
    }
}
