#!/usr/bin/env python3
"""Fail closed on credential files, known secret formats and old hosted endpoints.

Reports rule/path/line only, never matched values. This is a guardrail, not a proof
that arbitrary data is non-sensitive. Run it on the source tree and on APK assets.
"""
import argparse
import json
import re
import subprocess
import sys
import zipfile
import tarfile
import io
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.gradle', 'build', '.pytest_cache', '__pycache__', '.venv', 'dist', '.kotlin'}
FORBIDDEN_NAMES = {'local.properties', 'debug.keystore', 'mykey.py', 'mykey.json',
                   '.bus_token', 'keypatch.json', '_ga_voice_sig.py', 'gakey_gen.h', '.env',
                   'ga.integrations.json', 'pclink_rooms.json', 'devices.json'}
FORBIDDEN_SUFFIXES = {'.keystore', '.jks', '.p12', '.pfx', '.pem', '.key', '.db', '.sqlite', '.sqlite3'}
RULES = {
    'embedded-relay-authority': re.compile(rb'DEFAULT_ACCESS_KEY\s*=\s*[\x22\x27][^\x22\x27\r\n]+[\x22\x27]'),
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{64,}'),
    'provider-token': re.compile(rb'\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}'),
    'github-token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'aws-key': re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
    'jwt': re.compile(rb'\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{20,}'),
    'hosted-endpoint': re.compile(rb'(?:https?|wss?)://[^\s\x00\x22\x27<>]*\b(?:gaagent\.ai|getoken\.tech|k-on\.tech|ace-ozer\.[a-z]+)'),
    'personal-path': re.compile(rb'/Users/(?!user/|example/)[A-Za-z0-9_.-]+/'),
}

# Navigation in reviewed source documentation is not a runtime service default.
# Exact files, HTTPS origins, root paths and public anchors only; no credentials
# or queries. APKs and nested archives never receive this exception.
PUBLIC_LINK_DOCS = {'README.md', 'README.zh-CN.md', 'docs/CASES.md',
                    'docs/CONFIGURATION.md', 'docs/ECOSYSTEM.md'}
PUBLIC_SITE_ANCHORS = {
    'gaagent.ai': {''},
    'app.gaagent.ai': {''},
    'apk.gaagent.ai': {''},
    'androidbench.gaagent.ai': {'', 'traces', 'method', 'jev-study'},
}


def public_documentation_link(name, data, start, end):
    if name not in PUBLIC_LINK_DOCS:
        return False
    # The endpoint rule ends at the hostname. Inspect the entire URL so a path,
    # query, suffix domain or embedded credential cannot inherit the exception.
    token = re.match(rb'[^\s\x00\x22\x27<>`)\]]+', data[start:])
    if token is None or start + token.end() < end:
        return False
    try:
        url = urlsplit(token.group().decode('ascii'))
    except (UnicodeError, ValueError):
        return False
    return (url.scheme == 'https' and url.netloc in PUBLIC_SITE_ANCHORS
            and url.path in ('', '/') and not url.query
            and url.fragment in PUBLIC_SITE_ANCHORS[url.netloc])


def audit_blob(name, data, *, allow_public_docs=False):
    path = Path(name)
    findings = []
    public_ca = path.name == 'cacert.pem' and b'-----BEGIN CERTIFICATE-----' in data
    if path.name in FORBIDDEN_NAMES or (path.suffix.lower() in FORBIDDEN_SUFFIXES and not public_ca):
        findings.append({'path': name, 'rule': 'credential-or-runtime-file', 'line': 0})
    for rule, pattern in RULES.items():
        for match in pattern.finditer(data):
            if (rule == 'hosted-endpoint' and allow_public_docs
                    and public_documentation_link(name, data, match.start(), match.end())):
                continue
            findings.append({'path': name, 'rule': rule, 'line': data.count(b'\n', 0, match.start()) + 1})
    return findings


def audit_archive(name, data, depth=0, *, allow_public_docs=False):
    findings = audit_blob(name, data, allow_public_docs=allow_public_docs)
    if depth > 4:
        return findings + [{'path': name, 'rule': 'archive-depth-limit', 'line': 0}]
    if name.endswith(('.tgz', '.tar.gz')):
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            for member in archive.getmembers():
                nested = name + ':' + member.name
                if member.issym() or member.islnk() or '..' in Path(member.name).parts or member.name.startswith('/'):
                    findings.append({'path': nested, 'rule': 'unsafe-archive-member', 'line': 0})
                elif member.isfile():
                    if member.size > 128 * 1024 * 1024:
                        findings.append({'path': nested, 'rule': 'archive-member-limit', 'line': 0})
                    else:
                        findings.extend(audit_archive(nested, archive.extractfile(member).read(), depth + 1))
    elif data.startswith(b'PK\x03\x04'):
        # Chaquopy's .imy files are ZIPs too. Scanning only their compressed bytes
        # would miss strings and files inside the packaged Python environment.
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                nested = name + ':' + member.filename
                if ('..' in Path(member.filename).parts or member.filename.startswith('/')
                        or (member.external_attr >> 16) & 0o170000 == 0o120000):
                    findings.append({'path': nested, 'rule': 'unsafe-archive-member', 'line': 0})
                elif member.file_size > 128 * 1024 * 1024:
                    findings.append({'path': nested, 'rule': 'archive-member-limit', 'line': 0})
                else:
                    findings.extend(audit_archive(nested, archive.read(member), depth + 1))
    return findings


def source_files(root):
    # Include new untracked files too; an allowlisted clean export must be checked before its first commit.
    return sorted(p for p in root.rglob('*') if p.is_file() and not any(x in SKIP for x in p.relative_to(root).parts))


def audit_tree(root):
    findings, count = [], 0
    for path in source_files(root):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.append({'path': name, 'rule': 'symlink', 'line': 0})
            continue
        findings.extend(audit_archive(name, path.read_bytes(), allow_public_docs=True))
        count += 1
    return count, findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    if args.apk:
        with zipfile.ZipFile(args.apk) as archive:
            names = [n for n in archive.namelist() if not n.endswith('/')]
            findings = [issue for name in names for issue in audit_archive(name, archive.read(name))]
            count = len(names)
    else:
        count, findings = audit_tree(ROOT)
    print(json.dumps({'files': count, 'findings': findings}, indent=2))
    return bool(findings)


if __name__ == '__main__':
    sys.exit(main())
