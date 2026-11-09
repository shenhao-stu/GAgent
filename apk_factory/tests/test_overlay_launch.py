"""Launch uses one overlay policy for all packages."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'app/src/main/assets/ga_runtime'


@pytest.mark.parametrize('pkg', ['com.tencent.mm', 'com.example.app'])
def test_launch_does_not_request_overlay_suppression(pkg):
    tree = ast.parse((RUNTIME / 'droid.py').read_text())
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name == 'launch' or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
             t.id == 'SENSITIVE_APPS' for t in node.targets)]
    calls = []
    def act(**kwargs):
        calls.append(kwargs)
        return {'ok': True}
    env = {'_act': act}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'droid-launch', 'exec'), env)
    result = env['launch'](pkg, wait=0)
    assert calls == [{'op': 'launch', 'pkg': pkg}]
    assert result['request_sent'] is True and result['opened'] is None
    assert 'fg' not in result
    if pkg == 'com.tencent.mm':
        assert result['policy'].startswith('sensitive: visual-only')
        assert env['SENSITIVE_APPS'][pkg] == {'dump': 'blank', 'act': 'gui'}
