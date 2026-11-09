#!/usr/bin/env python3
"""Remove upstream build-user paths and replace Chaquopy's public CA bundle.

Runs on generated assets before Chaquopy calculates build.json hashes and before
APK signing. Equal-length replacements preserve bytecode/ELF string offsets.
"""
import argparse
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD_USER = re.compile(rb'/Users/[A-Za-z0-9_.-]+/')


def clean_paths(data):
    return BUILD_USER.sub(lambda m: b'/build/' + b'x' * (len(m[0]) - 8) + b'/', data)


def prepare(directory):
    changed = 0
    for path in sorted(directory.rglob('*')):
        if not path.is_file():
            continue
        if path.suffix == '.imy':
            with zipfile.ZipFile(path) as source:
                entries = [(info, source.read(info)) for info in source.infolist()]
            if not any(BUILD_USER.search(data) for _, data in entries):
                continue
            temporary = path.with_suffix('.imy.new')
            with zipfile.ZipFile(temporary, 'w') as target:
                for info, data in entries:
                    target.writestr(info, clean_paths(data))
            temporary.replace(path)
            changed += 1
        elif path.name != 'cacert.pem':
            original = path.read_bytes()
            cleaned = clean_paths(original)
            if cleaned != original:
                path.write_bytes(cleaned)
                changed += 1
    ca = directory / 'cacert.pem'
    if ca.exists():
        bundle = ROOT / 'app/src/main/assets/ga_runtime/fsbot/deps/site_packages.tgz'
        with tarfile.open(bundle) as archive:
            members = [m for m in archive.getmembers() if m.name.endswith('certifi/cacert.pem')]
            if len(members) != 1:
                raise ValueError('Expected one pinned public CA bundle')
            ca.write_bytes(archive.extractfile(members[0]).read())
    print('Prepared Python assets:', changed, 'archives/files; public CA updated:', ca.exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    prepare(parser.parse_args().directory)
