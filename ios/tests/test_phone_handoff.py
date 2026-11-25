"""Exercise the native handoff dispatcher with an input still unwinding."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_end_does_not_wait_for_input_completion(tmp_path):
    source = (ROOT / 'ios/BoardKit/BoardSession.swift').read_text()
    method = source[source.index('    private func handoff('):source.index('    private static let pausedReply')]
    fixture = '''
import Foundation
final class Session {
    var takeover = PhoneTakeover()
    var busy = true
    var stops = 0
    func stop() -> [String: Any] { stops += 1; return ["ok": true, "stopped": true] }
    METHOD
    func check() {
        let old = takeover.pause(), token = takeover.pause()
        precondition(handoff(["action": "cancel", "token": old])["ok"] as? Bool == false)
        precondition(stops == 0 && takeover.paused)
        precondition(handoff(["action": "resume", "token": token])["ok"] as? Bool == false)
        precondition(handoff(["action": "cancel", "token": token])["ok"] as? Bool == true)
        precondition(stops == 1 && !takeover.paused)
        precondition(handoff(["action": "resume", "token": token])["ok"] as? Bool == false)
        print("PASS: cancelled while busy, stale handoff refused")
    }
}
@main struct Checks { static func main() { Session().check() } }
'''.replace('    METHOD', method)
    file = tmp_path / 'Handoff.swift'; file.write_text(fixture)
    binary = tmp_path / 'check'
    built = subprocess.run(['xcrun', 'swiftc', str(ROOT / 'ios/BoardKit/Agent/PhoneTakeover.swift'), str(file), '-o', str(binary)],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'PASS:' in result.stdout
