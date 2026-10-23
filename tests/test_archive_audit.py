import importlib.util
import io
from pathlib import Path
import zipfile
import pytest


spec = importlib.util.spec_from_file_location('audit_source', Path(__file__).parents[1] / 'tools/audit_source.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def packed(name, payload):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return output.getvalue()


def test_nested_chaquopy_payload_is_checked_without_disclosing_value():
    value = b'sk-' + b'x' * 24
    nested = packed('assets/app.imy', packed('module.pyc', value))
    findings = audit.audit_archive('candidate.apk', nested)
    assert any(f['rule'] == 'provider-token' and 'module.pyc' in f['path'] for f in findings)
    assert value.decode() not in str(findings)


def test_nested_runtime_credentials_and_traversal_are_rejected():
    assert audit.audit_archive('app.imy', packed('kv/.bus_token', b'example'))[0]['rule'] == 'credential-or-runtime-file'
    assert audit.audit_archive('app.imy', packed('../outside', b'example'))[0]['rule'] == 'unsafe-archive-member'


def test_key_format_marker_is_not_a_key_but_payload_is_rejected():
    marker = b'-----BEGIN ' + b'PRIVATE KEY-----'
    assert not audit.audit_blob('ssh.pyc', marker)
    assert audit.audit_blob('ssh.pyc', marker + b'\n' + b'A' * 80)[0]['rule'] == 'private-key'


def write_source(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.mark.parametrize('host,fragment', [
    ('gaagent.ai', ''), ('app.gaagent.ai', ''), ('apk.gaagent.ai', ''),
    ('androidbench.gaagent.ai', ''), ('androidbench.gaagent.ai', '#traces'),
    ('androidbench.gaagent.ai', '#method'), ('androidbench.gaagent.ai', '#jev-study'),
])
def test_reviewed_source_navigation_links_are_allowed(tmp_path, host, fragment):
    url = ('https://' + host + '/' + fragment).encode()
    write_source(tmp_path, 'README.md', b'<a href="' + url + b'">Public site</a>')
    write_source(tmp_path, 'docs/CASES.md', b'[Public site](' + url + b')')
    assert audit.audit_tree(tmp_path)[1] == []


@pytest.mark.parametrize('name', [
    'app/src/main/assets/README.md', 'app/src/main/assets/endpoint.py',
    'docs/unknown.md', 'docs/examples/config.json',
])
def test_navigation_exception_does_not_apply_to_runtime_or_unreviewed_files(tmp_path, name):
    url = b'https://' + b'gaagent.ai/'
    write_source(tmp_path, name, url)
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_tree(tmp_path)[1])


@pytest.mark.parametrize('scheme,authority,suffix', [
    ('http', 'gaagent.ai', '/'),
    ('https', 'api.gaagent.ai', '/'),
    ('https', 'gaagent.ai', '/v1/chat/completions'),
    ('https', 'gaagent.ai', '/?token=placeholder'),
    ('https', 'gaagent.ai', '/?next=https://example.invalid'),
    ('https', 'gaagent.ai', '/#unreviewed-fragment'),
    ('https', 'gaagent.ai:443', '/'),
    ('https', 'user:placeholder@gaagent.ai', '/'),
    ('https', 'gaagent.ai.evil.invalid', '/'),
    ('https', 'gaagent.ai@evil.invalid', '/'),
])
def test_source_documentation_still_rejects_non_navigation_addresses(tmp_path, scheme, authority, suffix):
    url = (scheme + '://' + authority + suffix).encode()
    write_source(tmp_path, 'README.md', b'[link](' + url + b')')
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_tree(tmp_path)[1])


def test_navigation_exception_preserves_secret_detection_and_redaction(tmp_path):
    value = b'sk-' + b'x' * 24
    write_source(tmp_path, 'README.md', b'https://' + b'gaagent.ai/\n' + value)
    findings = audit.audit_tree(tmp_path)[1]
    assert [f['rule'] for f in findings] == ['provider-token']
    assert value.decode() not in str(findings)


def test_adjacent_public_link_cannot_hide_a_runtime_endpoint(tmp_path):
    public = b'https://' + b'gaagent.ai/'
    runtime = b'https://' + b'api.gaagent.ai/v1'
    write_source(tmp_path, 'README.md', b'[site](' + public + b')[api](' + runtime + b')')
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_tree(tmp_path)[1])


def test_archives_and_apk_blobs_keep_endpoint_checks(tmp_path):
    url = b'https://' + b'gaagent.ai/'
    write_source(tmp_path, 'bundle.zip', packed('README.md', url))
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_tree(tmp_path)[1])
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_blob('README.md', url))
    assert any(f['rule'] == 'hosted-endpoint' for f in audit.audit_archive('README.md', url))
