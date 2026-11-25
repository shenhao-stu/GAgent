import Foundation

/// Only generated workspace files may cross into a system viewer or share sheet.
enum WorkspaceFile {
    static func resolve(_ relative: String, in workspace: URL) -> URL? {
        guard !relative.isEmpty, !relative.hasPrefix("/"), !relative.contains("\0"),
              !relative.split(separator: "/").contains("..") else { return nil }
        let root = workspace.resolvingSymlinksInPath().appendingPathComponent("temp").standardizedFileURL
        guard root.resolvingSymlinksInPath() == root else { return nil }
        let file = root.appendingPathComponent(relative).standardizedFileURL.resolvingSymlinksInPath()
        guard file.path.hasPrefix(root.path + "/"),
              (try? file.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true,
              FileManager.default.isReadableFile(atPath: file.path) else { return nil }
        return file
    }
}
