"""Fault containment using the real Android entry module in fresh, keyless processes."""
from pathlib import Path
import os
import subprocess
import sys

import pytest

RUNTIME = Path(__file__).resolve().parents[1] / 'app/src/main/assets/ga_runtime'


def run_case(tmp_path, script):
    env = os.environ.copy()
    env['GA_DIR'] = str(tmp_path)
    env['GA_LANG'] = 'zh'
    preamble = '''import sys, os, pathlib, threading
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import android_entry as ae
w = pathlib.Path(os.environ['GA_DIR'])
'''
    r = subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', preamble + script, str(RUNTIME)],
                       env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
    assert r.returncode == 0, r.stdout + r.stderr


def test_invalid_config_never_published(tmp_path):
    run_case(tmp_path, '''
p = w / 'fixture.py'; old = 'value = 1\\n'; p.write_text(old)
seen = []
write = ae._atomic_write
def spy(path, text):
    seen.append(text); write(path, text)
with patch.object(ae, '_atomic_write', spy), patch.object(ae, '_refresh_mykeys'):
    try: ae._write_mykey_file(str(p), old, ['value = ('])
    except Exception: pass
    else: raise AssertionError('invalid source accepted')
assert not seen, seen
assert p.read_text() == old
''')


def test_reload_failure_restores_disk_and_cache(tmp_path):
    run_case(tmp_path, '''
p = w / 'fixture.py'; old = 'value = 1\\n'; p.write_text(old)
cache = [old]; calls = []
def reload():
    cache[0] = p.read_text(); calls.append(cache[0])
    if 'value = 2' in cache[0]: raise RuntimeError('reload failed after cache mutation')
with patch.object(ae, '_refresh_mykeys', reload):
    try: ae._write_mykey_file(str(p), old, ['value = 2'])
    except RuntimeError: pass
    else: raise AssertionError('failed save reported success')
assert p.read_text() == old
assert cache[0] == old, calls
''')


@pytest.mark.parametrize('optional', ['patch_usage', 'patch_route_probe'])
def test_optional_startup_patch_failure_is_local(tmp_path, optional):
    run_case(tmp_path, '''
import kernel_adapter
seen = []
with patch.object(kernel_adapter, 'install'), patch.object(ae, '_apply_proxy'), \\
     patch.object(ae.patches, 'patch_abort', lambda: seen.append('abort')), \\
     patch.object(ae.patches, 'patch_usage'), patch.object(ae.patches, 'patch_route_probe'), \\
     patch.object(ae.patches, %r, side_effect=RuntimeError('optional unavailable')):
    assert ae.init(str(w)) == 'nokey'
assert seen == ['abort']
assert ae.send('/lang en') == 'lang=en'
''' % optional)


def test_required_core_failure_is_not_silenced(tmp_path):
    run_case(tmp_path, '''
import kernel_adapter
with patch.object(kernel_adapter, 'install', side_effect=RuntimeError('core missing')):
    try: ae.init(str(w))
    except RuntimeError: pass
    else: raise AssertionError('core failure reported ready')
''')


def test_atomic_write_failure_keeps_old_file_and_cleans_temp(tmp_path):
    run_case(tmp_path, '''
p = w / 'fixture.json'; p.write_text('old')
with patch.object(ae.os, 'replace', side_effect=OSError('disk unavailable')):
    try: ae._atomic_write(str(p), 'new')
    except OSError: pass
    else: raise AssertionError('failed replace reported success')
assert p.read_text() == 'old'
assert not list(w.glob('*.tmp')), list(w.glob('*.tmp'))
''')
