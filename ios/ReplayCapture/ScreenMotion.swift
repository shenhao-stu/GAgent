import Foundation

/// A small RGB thumbnail distinguishes a page transition from cursor/clock animation. Compare against the
/// last substantial change, not the preceding sample, so a slow pan or fade cannot disappear between frames.
struct ScreenMotion {
    private var anchor: [UInt8] = []
    private var width = 0, height = 0
    private(set) var changedAt: Double?
    private(set) var changedFraction: Double = 0

    mutating func observe(_ rgba: [UInt8], width: Int, height: Int, at time: Double) {
        guard width > 0, height > 0, rgba.count == width * height * 4 else { return }
        if anchor.count != rgba.count || self.width != width || self.height != height {
            changedFraction = 1
        } else {
            var changed = 0
            for p in stride(from: 0, to: rgba.count, by: 4) {
                if (0..<3).contains(where: { abs(Int(rgba[p + $0]) - Int(anchor[p + $0])) >= 20 }) { changed += 1 }
            }
            changedFraction = Double(changed) / Double(width * height)
        }
        if changedFraction > 0.01 {
            anchor = rgba
            self.width = width; self.height = height
            changedAt = time
        }
    }
}
