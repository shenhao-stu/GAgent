#!/usr/bin/env python3
"""Build pinned CPython 3.13 Android dependencies with upstream cibuildwheel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/android-wheels'
SOURCES = json.loads(Path(__file__).with_name('native-sources.json').read_text())


def run(args, cwd, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=2400)


def source(name):
    spec = SOURCES[name]
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / spec['url'].rsplit('/', 1)[1]
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
        with urllib.request.urlopen(spec['url'], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != spec['sha256']:
            raise ValueError('Source digest mismatch: ' + name)
        archive.write_bytes(data)
    target = BUILD / name
    if not target.exists():
        target.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(target, filter='data')
    entries = list(target.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ValueError('Unexpected source layout: ' + name)
    return entries[0]


def prepare(package):
    """Called inside cibuildwheel's Android compiler environment."""
    prefix = BUILD / ('native-' + package)
    prefix.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['CFLAGS'] = env.get('CFLAGS', '') + ' -fPIC'
    env['LDFLAGS'] = env.get('LDFLAGS', '') + ' -Wl,-z,max-page-size=16384'
    if package == 'cffi':
        root = source('libffi')
        run(['./configure', '--host=aarch64-linux-android', '--disable-shared',
             '--with-pic', '--prefix=' + str(prefix)], root, env)
        run(['make', '-j2'], root, env)
        run(['make', 'install'], root, env)
    elif package == 'cryptography':
        root = source('openssl')
        run(['perl', 'Configure', 'android-arm64', 'no-shared', 'no-tests',
             '--prefix=' + str(prefix), '--libdir=lib', '-D__ANDROID_API__=24'], root, env)
        run(['make', '-j2', 'build_sw'], root, env)
        run(['make', 'install_sw'], root, env)


def build(package):
    root = source(package)
    output = ROOT / 'build/python-wheels'
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CIBW_PLATFORM='android', CIBW_BUILD='cp313-android_arm64_v8a',
               CIBW_ARCHS_ANDROID='arm64_v8a', CIBW_BUILD_FRONTEND='build',
               CIBW_TEST_SKIP='*', CIBW_BUILD_VERBOSITY='1')
    prefix = BUILD / ('native-' + package)
    values = {'ANDROID_API_LEVEL': '24', 'CMAKE_BUILD_PARALLEL_LEVEL': '2',
              'PIP_EXTRA_INDEX_URL': 'https://chaquo.com/pypi-13.1'}
    if package in ('cffi', 'cryptography'):
        env['CIBW_BEFORE_BUILD'] = shlex.join([sys.executable, str(Path(__file__).resolve()),
                                             '--prepare', package])
    if package == 'cffi':
        values['PKG_CONFIG_LIBDIR'] = str(prefix / 'lib/pkgconfig')
        values['PKG_CONFIG_PATH'] = str(prefix / 'lib/pkgconfig')
    elif package == 'cryptography':
        values.update(OPENSSL_DIR=str(prefix), OPENSSL_STATIC='1')
    elif package == 'pynacl':
        # Autoconf must not try to execute target binaries on the build host.
        setup = root / 'setup.py'
        text = setup.read_text()
        anchor = 'configure_flags = ['
        if '"--host=aarch64-linux-android"' not in text:
            if text.count(anchor) != 1:
                raise ValueError('PyNaCl configure layout changed')
            text = text.replace(anchor, anchor + '\n            "--host=aarch64-linux-android",')
            check = 'subprocess.check_call(\n            [make_command, "check"] + make_args, cwd=build_temp\n        )'
            if text.count(check) != 1:
                raise ValueError('PyNaCl native test layout changed')
            setup.write_text(text.replace(check, '# Native self-tests require an Android target.'))
        values['LIBSODIUM_MAKE_ARGS'] = '-j2'
    elif package == 'numpy':
        env['CIBW_CONFIG_SETTINGS'] = 'setup-args=-Dblas=none setup-args=-Dlapack=none'
    elif package == 'opencv-python':
        values.update(ENABLE_HEADLESS='1', CMAKE_ARGS=' '.join([
            '-DBUILD_LIST=core,imgproc,imgcodecs,python3', '-DBUILD_TESTS=OFF',
            '-DBUILD_PERF_TESTS=OFF', '-DBUILD_JAVA=OFF', '-DWITH_FFMPEG=OFF',
            '-DWITH_OPENEXR=OFF', '-DWITH_JASPER=OFF', '-DWITH_TIFF=OFF',
            '-DWITH_WEBP=OFF', '-DWITH_OPENCL=OFF']))
    env['CIBW_ENVIRONMENT'] = ' '.join(k + '=' + shlex.quote(v) for k, v in values.items())
    run([sys.executable, '-m', 'cibuildwheel', str(root), '--output-dir', str(output)], ROOT, env)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', nargs='?', choices=list(SOURCES))
    parser.add_argument('--prepare', choices=['cffi', 'cryptography'])
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
    elif args.package:
        build(args.package)
    else:
        parser.error('package is required')
