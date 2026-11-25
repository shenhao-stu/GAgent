import Foundation
import CryptoKit

/// Restore shipped WebUI/resources, preserve user data, and migrate only known unmodified stock memory.
enum Assets {
    /// 覆盖豁免集(与 AssetUnpacker 的 preserve 对齐 + iOS 侧新增 kv/pclink_rooms/uploads)
    private static let preserve: Set<String> = ["memory", "temp", "kv", "uploads"]
    private static let preserveFiles: Set<String> = ["mykey.py", "mykey.json", "chat.json",
                                                     "pclink_rooms.json", "bus_port.txt"]
    /// 保留目录里也要补新文件的(temp/kv/uploads 是纯用户态, 官方包里本就没内容, 不需要)
    private static let fillMissing: Set<String> = ["memory"]

    /// 只补缺: 官方目录里有、本地没有的文件复制过去; 本地已有的(含用户改过的)一律保留。递归子目录。
    private static func copyMissing(from src: URL, to dst: URL, fm: FileManager) throws -> Int {
        var n = 0
        try fm.createDirectory(at: dst, withIntermediateDirectories: true)
        for item in try fm.contentsOfDirectory(at: src, includingPropertiesForKeys: [.isDirectoryKey]) {
            let d = dst.appendingPathComponent(item.lastPathComponent)
            let isDir = (try? item.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
            if isDir { n += try copyMissing(from: item, to: d, fm: fm); continue }
            if fm.fileExists(atPath: d.path) { continue }
            try fm.copyItem(at: item, to: d); n += 1
        }
        return n
    }

    // Users may upgrade from any supported stock revision. Never change an edited guide.
    static func refreshStockMemory(in workspace: URL, from bundle: URL) throws {
        let fm = FileManager.default
        let stock = try JSONDecoder().decode([String: [String]].self,
            from: Data(contentsOf: bundle.appendingPathComponent("stock-memory.json")))
        for (name, revisions) in stock where !name.contains("/") {
            let current = workspace.appendingPathComponent("memory").appendingPathComponent(name)
            guard let metadata = try? current.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
                  metadata.isRegularFile == true, metadata.isSymbolicLink != true,
                  let size = metadata.fileSize, size < 2_000_000 else { continue }
            let data = try Data(contentsOf: current)
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard revisions.contains(digest) else { continue }
            let replacement = bundle.appendingPathComponent("memory").appendingPathComponent(name)
            if fm.fileExists(atPath: replacement.path) {
                let updated = try Data(contentsOf: replacement)
                if updated != data { try updated.write(to: current, options: .atomic) }
            } else { try fm.removeItem(at: current) }
        }
    }

    static func extract() throws -> URL {
        let fm = FileManager.default
        let base = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask,
                              appropriateFor: nil, create: true)
        let gaDir = base.appendingPathComponent("ga")
        try fm.createDirectory(at: gaDir, withIntermediateDirectories: true)

        let stampFile = gaDir.appendingPathComponent(".ios_asset_stamp")
        let stamp = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
        // Every launch restores shipped UI/assets. Legacy writable Python remains data only;
        // the interpreter imports exclusively Bundle/gacore. Never trust a writable version stamp.
        for name in preserve {
            let p = gaDir.appendingPathComponent(name)
            if p.resolvingSymlinksInPath().standardizedFileURL != gaDir.resolvingSymlinksInPath().appendingPathComponent(name).standardizedFileURL {
                throw NSError(domain: "Assets", code: 2, userInfo: [NSLocalizedDescriptionKey: "工作区目录包含符号链接，请导出资料后重新安装应用"])
            }
        }

        guard let src = Bundle.main.url(forResource: "gacore", withExtension: nil) else {
            throw NSError(domain: "Assets", code: 1, userInfo: [NSLocalizedDescriptionKey: "bundle gacore missing"])
        }
        try refreshStockMemory(in: gaDir, from: src)
        let dataAssets: Set<String> = ["webui", "assets", "memory"]
        for item in try fm.contentsOfDirectory(at: src, includingPropertiesForKeys: nil) where dataAssets.contains(item.lastPathComponent) {
            let name = item.lastPathComponent
            let dst = gaDir.appendingPathComponent(name)
            let exists = fm.fileExists(atPath: dst.path)
            if exists && fillMissing.contains(name) { _ = try copyMissing(from: item, to: dst, fm: fm); continue }
            if exists && (preserve.contains(name) || preserveFiles.contains(name)) { continue }
            if exists { try fm.removeItem(at: dst) }
            try fm.copyItem(at: item, to: dst)
        }
        try stamp.write(to: stampFile, atomically: true, encoding: .utf8)
        return gaDir
    }
}
