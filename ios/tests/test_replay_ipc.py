"""Execute the real socket transport, ReplayKit sample handler state and Core Image encoder."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != 'darwin', reason='Apple CoreMedia and Quartz required')
def test_broadcast_exchange(tmp_path):
    binary = tmp_path / 'replay-ipc'
    modules = [ROOT / 'ReplayCapture/ReplayWire.swift', ROOT / 'ReplayCapture/ScreenMotion.swift', ROOT / 'BoardKit/Video/ScreenRest.swift', ROOT / 'ReplayCaptureHost/ReplayCaptureClient.swift',
               ROOT / 'BroadcastUpload/SampleHandler.swift', ROOT / 'tests/fixtures/ReplayIPCTest.swift']
    subprocess.run(['xcrun', 'swiftc', *map(str, modules), '-o', str(binary)], check=True, timeout=60)
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS live encrypted loopback' in result.stdout
