"""Build-output exclusions cannot hide runtime assets or linked directories."""
import importlib.util
from pathlib import Path

PATH = Path(__file__).parents[1] / 'tools/audit_source.py'
spec = importlib.util.spec_from_file_location('source_audit', PATH)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_nested_runtime_build_folder_is_audited(tmp_path):
    path = tmp_path / 'app/src/main/assets/ga_runtime/build' / ('my' + 'key.json')
    path.parent.mkdir(parents=True)
    path.write_text('{}')
    ignored = tmp_path / 'app/build/output.bin'
    ignored.parent.mkdir(parents=True)
    ignored.write_bytes(b'output')
    count, findings = audit.audit_tree(tmp_path)
    assert count == 1
    assert findings == [{'path': path.relative_to(tmp_path).as_posix(),
                         'rule': 'credential-or-runtime-file', 'line': 0}]


def test_linked_runtime_directory_is_rejected(tmp_path):
    target = tmp_path / 'real'
    target.mkdir()
    (tmp_path / 'linked').symlink_to(target, target_is_directory=True)
    _, findings = audit.audit_tree(tmp_path)
    assert findings == [{'path': 'linked', 'rule': 'symlink', 'line': 0}]
