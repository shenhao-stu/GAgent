#!/usr/bin/env python3
"""Collect license texts from the resolved mesh module sources for distribution."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def modules_in(aar):
    """Generated gobind code and Android build tags are part of the shipped graph."""
    paths = set()
    with zipfile.ZipFile(aar) as archive:
        libraries = [name for name in archive.namelist() if name.endswith('/libgojni.so')]
        if not libraries:
            raise ValueError('No Go native runtime in AAR')
        for name in libraries:
            with tempfile.TemporaryDirectory() as folder:
                # Windows: `go version -m` fails on a file still held open by Python,
                # so extract to a path that is closed before the subprocess reads it.
                library = Path(folder) / 'libgojni.so'
                library.write_bytes(archive.read(name))
                info = json.loads(subprocess.check_output(
                    ['go', 'version', '-m', '-json', str(library)], text=True, timeout=60))
                paths.update(module['Path'] for module in info['Deps'])
    modules = {}
    for path in sorted(paths):
        module = json.loads(subprocess.check_output(
            ['go', 'list', '-m', '-json', path], cwd=ROOT / 'tsbridge', text=True, timeout=60))
        if not module.get('Main'):
            module = module.get('Replace', module)
            modules[module['Path']] = module
    return modules


def main(aar):
    modules = modules_in(aar)
    output = ROOT / 'build/go-notices'
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, module in sorted(modules.items()):
        files = [p for p in Path(module['Dir']).iterdir()
                 if p.is_file() and re.match(r'^(licen[cs]e|copying|notice)', p.name, re.I)]
        if not files:
            raise ValueError('No license found for ' + name)
        for file in files:
            (output / (name.replace('/', '__') + '--' + file.name)).write_bytes(file.read_bytes())
        manifest.append({'module': name, 'version': module.get('Version'), 'licenses': [p.name for p in files]})
    goroot = Path(subprocess.check_output(['go', 'env', 'GOROOT'], text=True, timeout=30).strip())
    license_path = next(p for p in (goroot / 'LICENSE', goroot.parent / 'LICENSE') if p.is_file())
    (output / 'Go-LICENSE').write_bytes(license_path.read_bytes())
    (output / 'modules.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Go license modules:', len(manifest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--aar', type=Path, default=ROOT / 'app/libs/tsbridge.aar')
    main(parser.parse_args().aar)
