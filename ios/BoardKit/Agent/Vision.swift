import Accelerate
import CoreGraphics
import Foundation
import ImageIO

/// Small image checks on screen frames: did the screen change, and where is the pointer. Port of vision.py.
enum Vision {
    /// Ignore the status bar and Dynamic Island when comparing content: the clock, system indicators and the system
    /// progress of a running task change independently of the page.
    static let topMask = 0.11
    static let pointerRadius = 0.05
    /// The status bar alone (clock, indicators, the compact Dynamic Island). Around a target only this strip is
    /// ignored: a banner that grows below it covers the page, and a tap there would land on the banner.
    static let statusBar = 0.07

    /// A grayscale bitmap (PIL "L" weights), row-major.
    struct Gray {
        let w: Int, h: Int
        let px: [UInt8]
    }

    static func image(_ jpeg: Data) -> CGImage? {
        guard let src = CGImageSourceCreateWithData(jpeg as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }

    /// The image drawn at w x h (bilinear-ish scaling), converted to gray like PIL's convert("L").
    static func gray(_ img: CGImage, _ w: Int, _ h: Int) -> Gray {
        var rgba = [UInt8](repeating: 0, count: w * h * 4)
        var px = [UInt8](repeating: 0, count: w * h)
        rgba.withUnsafeMutableBytes { buf in
            let ctx = CGContext(data: buf.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4,
                                space: CGColorSpaceCreateDeviceRGB(),
                                bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
            ctx.interpolationQuality = .medium
            ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
            px.withUnsafeMutableBytes { output in
                var source = vImage_Buffer(data: buf.baseAddress, height: vImagePixelCount(h),
                                          width: vImagePixelCount(w), rowBytes: w * 4)
                var destination = vImage_Buffer(data: output.baseAddress, height: vImagePixelCount(h),
                                               width: vImagePixelCount(w), rowBytes: w)
                // RGBX byte order; retain the exact integer weights and rounding of the frame checks.
                let status = vImageMatrixMultiply_ARGB8888ToPlanar8(&source, &destination,
                    [299, 587, 114, 0], 1000, nil, 500, vImage_Flags(kvImageNoFlags))
                precondition(status == kvImageNoError)
            }
        }
        return Gray(w: w, h: h, px: px)
    }

    /// True when the screen content changed, including small things such as a checkmark.
    ///
    /// `ignore` lists screen points (fractions) where the pointer was or went: those spots are masked, so pointer
    /// moves never count. The status bar (clock) is ignored too.
    static func changed(_ before: Data?, _ after: Data?, ignore: [CGPoint] = [], threshold: Double = 1.0) -> Bool {
        guard let before, let after, let a = image(before), let b = image(after) else { return true }
        return changed(a, b, ignore: ignore, threshold: threshold, topMask: topMask, scale: CGSize(width: 1, height: 1))
    }

    /// Whether the neighbourhood of `point` changed: what a tap or swipe there depends on, while other parts of the
    /// page (a chat receiving messages) may move. `ignore` points are screen fractions, as in `changed`.
    static func changed(_ before: Data, _ after: Data, near point: CGPoint, ignore: [CGPoint] = [],
                        half: CGSize = CGSize(width: 0.12, height: 0.06)) -> Bool {
        guard let a = image(before), let b = image(after), a.width == b.width, a.height == b.height else { return true }
        let w = Double(a.width), h = Double(a.height)
        let box = CGRect(x: (Double(point.x) - half.width) * w, y: (Double(point.y) - half.height) * h,
                         width: 2 * half.width * w, height: 2 * half.height * h)
            .integral.intersection(CGRect(x: 0, y: 0, width: w, height: h))
        guard box.width >= 8, box.height >= 8, let ca = a.cropping(to: box), let cb = b.cropping(to: box) else { return true }
        let local = ignore.map { CGPoint(x: ($0.x * w - box.minX) / box.width, y: ($0.y * h - box.minY) / box.height) }
        // Progress above an app target is irrelevant; when the target is the island/status bar itself,
        // those pixels are the control being checked and cannot be excluded.
        let bar = point.y < statusBar ? 0 : max(0, (statusBar * h - box.minY) / box.height)
        return changed(ca, cb, ignore: local, threshold: 1.0, topMask: bar,
                       scale: CGSize(width: box.width / w, height: box.height / h))
    }

    /// `scale`: the image size as a fraction of the screen, so the pointer mask and caret limits keep screen size.
    private static func changed(_ a: CGImage, _ b: CGImage, ignore: [CGPoint], threshold: Double, topMask: Double,
                                scale: CGSize) -> Bool {
        if a.width != b.width || a.height != b.height { return true }
        let w = a.width / 2, h = a.height / 2  // the fine pass works at half resolution; masks are in its pixels
        let masks = ignore.map { (Double($0.x) * Double(w), Double($0.y) * Double(h)) }
        let radius = pointerRadius / scale.width * Double(w), bar = topMask * Double(h)
        func clear(_ x: Double, _ y: Double, of reach: Double) -> Bool {
            masks.allSatisfy { pow(x - $0.0, 2) + pow(y - $0.1, 2) > reach * reach }
        }
        // A big change: new screen, scrolled list. The pointer is left out here too: around a target it is a
        // large part of the picture, and it rests on the target when the target is checked. A thumbnail cell
        // blends its neighbours, so its mask reaches one cell further.
        let sa = gray(a, 32, 64), sb = gray(b, 32, 64)
        let cell = (Double(w) / Double(sa.w), Double(h) / Double(sa.h)), reach = radius + max(cell.0, cell.1, 1)
        var total = 0
        for i in 0..<sa.px.count where Double(i / sa.w) * cell.1 >= bar
            && clear((Double(i % sa.w) + 0.5) * cell.0, (Double(i / sa.w) + 0.5) * cell.1, of: reach) {
            total += abs(Int(sa.px[i]) - Int(sb.px[i]))
        }
        if Double(total) / Double(sa.px.count) > threshold { return true }
        let fa = gray(a, w, h), fb = gray(b, w, h)  // small changes
        var hits = 0, left = w, right = 0, top = h, bottom = 0
        fa.px.withUnsafeBufferPointer { a in
            fb.px.withUnsafeBufferPointer { b in
                let pa = a.baseAddress!, pb = b.baseAddress!
                var i = 0
                while i < w * h {
                    let difference = Int(pa[i]) - Int(pb[i])
                    if difference > 25 || difference < -25 {
                        let x = i % w, y = i / w
                        if Double(y) > bar && clear(Double(x), Double(y), of: radius) {
                            hits += 1
                            (left, right, top, bottom) = (min(left, x), max(right, x), min(top, y), max(bottom, y))
                        }
                    }
                    i += 1
                }
            }
        }
        guard hits >= 6 else { return false }
        // A blinking text caret is one thin column changing in place, not a page change.
        let caret = Double(right - left + 1) <= max(2, 0.012 / scale.width * Double(w))
            && Double(bottom - top + 1) <= 0.06 / scale.height * Double(h)
        return !caret
    }

    /// Where the pointer is in `before`, given it moved right by `shift` (fraction of width) in `after`.
    ///
    /// Only the pointer moved between the two frames, so the changed pixels within `reach` of `near` are the
    /// pointer at both spots; their centroid sits shift/2 to the right of the first one. nil if unclear.
    static func pointer(_ before: Data, _ after: Data, near: CGPoint, shift: Double,
                        reach: CGPoint = CGPoint(x: 0.12, y: 0.08)) -> CGPoint? {
        guard let ia = image(before), let ib = image(after), ia.width == ib.width, ia.height == ib.height else {
            return nil
        }
        let w = ia.width, h = ia.height
        let a = gray(ia, w, h), b = gray(ib, w, h)
        let nx = Double(near.x), ny = Double(near.y), rx = Double(reach.x), ry = Double(reach.y)
        let left = max(0, Int((nx - rx) * Double(w)))
        let top = max(Int(0.05 * Double(h)), Int((ny - ry) * Double(h)))  // skip the status bar
        let right = min(w, Int((nx + rx) * Double(w))), bottom = min(h, Int((ny + ry) * Double(h)))
        guard right > left, bottom > top else { return nil }
        var hits: [(Int, Int)] = []
        for y in top..<bottom {
            for x in left..<right where abs(Int(a.px[y * w + x]) - Int(b.px[y * w + x])) > 30 {
                hits.append((x - left, y - top))
            }
        }
        let area = (right - left) * (bottom - top)
        guard hits.count >= 15, hits.count <= area / 4 else { return nil }  // nothing moved, or more than a pointer
        let xs = hits.map(\.0), ys = hits.map(\.1)
        if Double(xs.max()! - xs.min()!) > 0.15 * Double(w) || Double(ys.max()! - ys.min()!) > 0.07 * Double(h) {
            return nil  // not one compact spot
        }
        let cx = Double(xs.reduce(0, +)) / Double(hits.count) + Double(left)
        let cy = Double(ys.reduce(0, +)) / Double(hits.count) + Double(top)
        return CGPoint(x: cx / Double(w) - shift / 2, y: cy / Double(h))
    }
}
