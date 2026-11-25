"""The system viewer must never read outside generated workspace files."""
import subprocess
from pathlib import Path


def test_workspace_file_boundary(tmp_path):
    source = Path(__file__).resolve().parents[1] / 'GAgent/WorkspaceFile.swift'
    (tmp_path / 'main.swift').write_text(r'''
import Foundation
let fm = FileManager.default, root = URL(fileURLWithPath: CommandLine.arguments[1])
try fm.createDirectory(at: root.appendingPathComponent("temp/sub"), withIntermediateDirectories: true)
try Data("safe".utf8).write(to: root.appendingPathComponent("temp/sub/deck.pptx"))
try Data("private".utf8).write(to: root.appendingPathComponent("private.txt"))
try fm.createSymbolicLink(atPath: root.appendingPathComponent("temp/escape").path, withDestinationPath: "../private.txt")
precondition(WorkspaceFile.resolve("sub/deck.pptx", in: root)?.lastPathComponent == "deck.pptx")
for name in ["", "/private.txt", "../private.txt", "sub/../../private.txt", "escape", "missing", "sub", "sub/\0"] {
    precondition(WorkspaceFile.resolve(name, in: root) == nil, name)
}
try fm.moveItem(at: root.appendingPathComponent("temp"), to: root.appendingPathComponent("actual"))
try fm.createSymbolicLink(atPath: root.appendingPathComponent("temp").path, withDestinationPath: "actual")
precondition(WorkspaceFile.resolve("sub/deck.pptx", in: root) == nil)
print("PASS: valid file, traversal, missing, directories and symlink escape")
''')
    binary = tmp_path / 'check'
    subprocess.run(['xcrun', 'swiftc', str(source), str(tmp_path/'main.swift'), '-o', str(binary)], check=True, capture_output=True, timeout=60)
    result = subprocess.run([str(binary), str(tmp_path/'workspace')], check=True, capture_output=True, text=True, timeout=10)
    assert 'PASS:' in result.stdout
