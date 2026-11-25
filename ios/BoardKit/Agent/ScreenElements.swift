import Foundation
import UIKit
import Vision

/// One tappable thing on a screen: a detected control (with any text inside it) or a line of text that no control
/// contains. Boxes are normalized with a top-left origin; ids follow reading order and are valid only for their frame.
struct ScreenElement: Equatable {
    let id: Int
    let box: CGRect
    let label: String?

    var center: CGPoint { CGPoint(x: box.midX, y: box.midY) }

    /// Compact form for the model: `7 发送 @0.871,0.890` (an unlabeled control reads `7 [icon] @…`).
    var summary: String {
        String(format: "%d %@ @%.3f,%.3f", id, label ?? "[icon]", center.x, center.y)
    }
}

enum ScreenElements {
    struct Text: Equatable {
        let box: CGRect
        let string: String
        var confidence: Float = 0
    }

    enum Source: String { case ok, unavailable, skipped, failed, frameChanged = "frame_changed" }

    struct Reading {
        let texts: [Text]
        let controls: [CGRect]
        let ocr, detector: Source

        var elements: [ScreenElement] { merge(controls: controls, texts: texts) }
        var sources: [String: String] { ["ocr": ocr.rawValue, "detector": detector.rawValue] }
        var cacheable: Bool { ocr == .ok && (detector == .ok || detector == .unavailable) }
        static let frameChanged = Self(texts: [], controls: [], ocr: .frameChanged, detector: .frameChanged)
        static let skipped = Self(texts: [], controls: [], ocr: .skipped, detector: .skipped)
    }

    /// A disabled detector, no detections and a failed recognition are distinct outcomes.
    static func read(text: @escaping () async throws -> [Text], controls: (() async throws -> [CGRect])?) async throws -> Reading {
        func source<T>(_ action: (() async throws -> [T])?) async throws -> ([T], Source) {
            try Task.checkCancellation()
            guard let action else { return ([], .unavailable) }
            do { return (try await action(), .ok) }
            catch is CancellationError { throw CancellationError() }
            catch { return ([], .failed) }
        }
        let (texts, ocr) = try await source(text)
        let (boxes, detector) = try await source(controls)
        return Reading(texts: texts, controls: boxes, ocr: ocr, detector: detector)
    }

    /// Larger boxes are containers (a sheet, a whole list): tapping their centre says nothing about a target.
    static let largestControl = 0.1

    /// A read-only enlargement accompanies the full image; action coordinates always refer to the full screen.
    static func detail(_ jpeg: Data, region: [String: Any]) throws -> Data {
        guard Set(region.keys) == ["x", "y", "width", "height"] else {
            throw DeviceError(message: "region requires x,y,width,height")
        }
        func number(_ key: String) throws -> Double {
            guard let n = region[key] as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite,
                  (0...1).contains(n.doubleValue) else { throw DeviceError(message: "Invalid region coordinate") }
            return n.doubleValue
        }
        let box = try CGRect(x: number("x"), y: number("y"), width: number("width"), height: number("height"))
        guard box.width > 0, box.height > 0, box.maxX <= 1, box.maxY <= 1,
              let original = UIImage(data: jpeg)?.cgImage,
              let crop = original.cropping(to: CGRect(x: box.minX * Double(original.width), y: box.minY * Double(original.height),
                  width: box.width * Double(original.width), height: box.height * Double(original.height)).integral),
              crop.width > 0, crop.height > 0
        else { throw DeviceError(message: "Region must be inside the full screen") }
        let scale = min(2, 1600 / Double(max(crop.width, crop.height)))
        let size = CGSize(width: Double(crop.width) * scale, height: Double(crop.height) * scale)
        let format = UIGraphicsImageRendererFormat(); format.scale = 1
        let expanded = UIGraphicsImageRenderer(size: size, format: format).image { _ in
            UIImage(cgImage: crop).draw(in: CGRect(origin: .zero, size: size))
        }
        guard let data = expanded.jpegData(compressionQuality: 0.85) else { throw DeviceError(message: "Cannot encode region") }
        return data
    }

    /// Controls absorb the text lines they mostly contain; a detector box that is only a fragment of one text line is
    /// dropped in favour of that line; leftover lines become elements of their own. Reading order assigns ids from 1.
    static func merge(controls: [CGRect], texts: [Text]) -> [ScreenElement] {
        let kept = controls.filter { box in
            box.width * box.height < largestControl && box.width > 0.004 && box.height > 0.003
                && !texts.contains { covered(box, by: $0.box) > 0.7 && area($0.box) > area(box) * 1.5 }
        }
        var labels = [[Text]](repeating: [], count: kept.count)
        var loose: [Text] = []
        for text in texts {
            let owners = kept.indices.filter { covered(text.box, by: kept[$0]) > 0.6 }
            if let owner = owners.min(by: { area(kept[$0]) < area(kept[$1]) }) { labels[owner].append(text) }
            else { loose.append(text) }
        }
        let items: [(CGRect, String?)] = kept.indices.map { index in
            let words = labels[index].sorted(by: before).map(\.string).joined(separator: " ")
            return (kept[index], words.isEmpty ? nil : words)
        } + loose.map { ($0.box, $0.string) }
        return items.sorted { before($0.0, $1.0) }.enumerated().map { ScreenElement(id: $0 + 1, box: $1.0, label: $1.1) }
    }

    /// Rows top to bottom (centres within ~1% of the screen height share a row), then left to right.
    private static func before(_ a: CGRect, _ b: CGRect) -> Bool {
        let rowA = (a.midY * 80).rounded(), rowB = (b.midY * 80).rounded()
        return rowA != rowB ? rowA < rowB : a.midX < b.midX
    }

    private static func before(_ a: Text, _ b: Text) -> Bool { before(a.box, b.box) }

    private static func area(_ box: CGRect) -> CGFloat { box.width * box.height }

    /// The share of `box` that lies inside `other`.
    private static func covered(_ box: CGRect, by other: CGRect) -> CGFloat {
        let overlap = box.intersection(other)
        return overlap.isNull || area(box) == 0 ? 0 : area(overlap) / area(box)
    }

    /// The frame with each element outlined and numbered at its top-left corner (Set-of-Mark for the model).
    static func marked(_ jpeg: Data, _ elements: [ScreenElement]) -> Data? {
        guard let image = UIImage(data: jpeg) else { return nil }
        let size = image.size, format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let font = UIFont.monospacedDigitSystemFont(ofSize: max(11, size.width / 52), weight: .bold)
        let ink = UIColor(red: 1, green: 0.16, blue: 0.55, alpha: 1)
        return UIGraphicsImageRenderer(size: size, format: format).image { context in
            image.draw(at: .zero)
            context.cgContext.setLineWidth(max(1.5, size.width / 400))
            for element in elements {
                let box = CGRect(x: element.box.minX * size.width, y: element.box.minY * size.height,
                                 width: element.box.width * size.width, height: element.box.height * size.height)
                ink.setStroke()
                context.cgContext.stroke(box)
                let tag = NSAttributedString(string: "\(element.id)", attributes: [.font: font, .foregroundColor: UIColor.white])
                let plate = CGRect(origin: box.origin, size: CGSize(width: tag.size().width + 4, height: tag.size().height))
                ink.setFill()
                context.fill(plate)
                tag.draw(at: CGPoint(x: plate.minX + 2, y: plate.minY))
            }
        }.jpegData(compressionQuality: 0.85)
    }
}
