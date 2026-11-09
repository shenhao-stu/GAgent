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
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/android-wheels'
SOURCES = json.loads(Path(__file__).with_name('native-sources.json').read_text())


def run(args, cwd, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True, timeout=2400)


def patch(path, before, after):
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise ValueError('Native source layout changed: ' + str(path.relative_to(BUILD)))
    path.write_text(text.replace(before, after))


def source(name):
    spec = SOURCES[name]
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / spec['url'].rsplit('/', 1)[1]
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(spec['url'], timeout=60) as response:
                    data = response.read()
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
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
        # OpenSSL discovers the NDK's unprefixed clang through PATH.
        compiler = Path(env['CC'])
        env['ANDROID_NDK_ROOT'] = str(compiler.parents[5])
        env['PATH'] = str(compiler.parent) + os.pathsep + env['PATH']
        run(['perl', 'Configure', 'android-arm64', 'no-shared', 'no-tests',
             '--prefix=' + str(prefix), '--libdir=lib', '-D__ANDROID_API__=24'], root, env)
        run(['make', '-j2', 'build_sw'], root, env)
        run(['make', 'install_sw'], root, env)
    elif package == 'numpy':
        # Meson's configure probes also need the target Python library search path.
        flags = ['-L' + env['PYO3_CROSS_LIB_DIR'], '-lpython3.13']
        (BUILD / 'android-arm64.ini').write_text(
            "[properties]\nlongdouble_format = 'IEEE_QUAD_LE'\n"
            f"[built-in options]\nc_link_args = {flags!r}\ncpp_link_args = {flags!r}\n")
    elif package == 'opencv-python':
        # cibuildwheel configures C/C++ but CMake otherwise picks the host assembler.
        with Path(env['CMAKE_TOOLCHAIN_FILE']).open('a') as toolchain:
            toolchain.write('\nset(CMAKE_ASM_COMPILER "$ENV{CC}")\n')


def build(package):
    root = source(package)
    output = ROOT / 'build/python-wheels'
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CIBW_PLATFORM='android', CIBW_BUILD='cp313-android_arm64_v8a',
               CIBW_ARCHS_ANDROID='arm64_v8a', CIBW_BUILD_FRONTEND='build',
               CIBW_TEST_SKIP='*', CIBW_BUILD_VERBOSITY='1',
               CIBW_BEFORE_BUILD='', CIBW_REPAIR_WHEEL_COMMAND='')
    prefix = BUILD / ('native-' + package)
    values = {'ANDROID_API_LEVEL': '24', 'CMAKE_BUILD_PARALLEL_LEVEL': '2',
              'PIP_EXTRA_INDEX_URL': 'https://chaquo.com/pypi-13.1',
              'PIP_FIND_LINKS': str(output)}
    if package in ('bcrypt', 'cryptography'):
        values['CARGO_TARGET_AARCH64_LINUX_ANDROID_RUSTFLAGS'] = '-C link-arg=-Wl,-z,max-page-size=16384'
    if package in ('cffi', 'cryptography', 'numpy', 'opencv-python'):
        env['CIBW_BEFORE_BUILD'] = shlex.join([sys.executable, str(Path(__file__).resolve()),
                                             '--prepare', package])
    if package == 'cffi':
        values['PKG_CONFIG_LIBDIR'] = str(prefix / 'lib/pkgconfig')
        values['PKG_CONFIG_PATH'] = str(prefix / 'lib/pkgconfig')
    elif package == 'cryptography':
        values.update(OPENSSL_DIR=str(prefix), OPENSSL_STATIC='1')
        # cibuildwheel uses <prefix>/lib, whereas this release assumes lib/pythonX.Y.
        build_rs = root / 'src/rust/cryptography-cffi/build.rs'
        text = build_rs.read_text()
        if '        let py_ver = lib' in text:
            start = text.index('        let py_ver = lib')
            end = text.index('        prefix\n', start)
            text = text[:start] + ('        let py_ver = "python3.13";\n'
                    '        let prefix = lib.parent().expect("missing Python prefix");\n') + text[end:]
            build_rs.write_text(text)
        elif 'missing Python prefix' not in text:
            raise ValueError('cryptography include layout changed')
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
            text = text.replace(check, '# Native self-tests require an Android target.')
            # Let setuptools derive the shared linker from the active cross CC.
            text = text.replace('"CCSHARED", "LDSHARED"', '"CCSHARED"')
            setup.write_text(text)
        values['LIBSODIUM_MAKE_ARGS'] = '-j2'
    elif package == 'numpy':
        cross = BUILD / 'android-arm64.ini'
        cross.write_text("[properties]\nlongdouble_format = 'IEEE_QUAD_LE'\n")
        env['CIBW_CONFIG_SETTINGS'] = ('setup-args=-Dblas=none setup-args=-Dlapack=none '
            'setup-args=--cross-file=' + str(cross) + ' compile-args=-j2')
    elif package == 'opencv-python':
        project = root / 'pyproject.toml'
        project.write_text(project.read_text().replace('numpy==2.1.3', 'numpy==2.5.4'))
        # Upstream disables Android Python bindings. cibuildwheel supplies the
        # target Python library and NumPy wheel; enable discovery of those files.
        patch(root / 'opencv/modules/python/CMakeLists.txt',
              'if(ANDROID OR APPLE_FRAMEWORK OR WINRT)',
              'if(APPLE_FRAMEWORK OR WINRT)')
        detect = root / 'opencv/cmake/OpenCVDetectPython.cmake'
        patch(detect, 'if(NOT ANDROID AND NOT APPLE_FRAMEWORK)',
              'if(NOT APPLE_FRAMEWORK)')
        patch(detect, '\n    if(NOT ANDROID AND NOT IOS AND NOT XROS)',
              '\n    if(NOT IOS AND NOT XROS)')
        patch(detect, 'endif(NOT ANDROID AND NOT IOS AND NOT XROS)',
              'endif(NOT IOS AND NOT XROS)')
        patch(detect, '# Find specified Python version',
              'set(PYTHON3_NUMPY_INCLUDE_DIRS "$ENV{VIRTUAL_ENV}/../xbuild_files/numpy/_core/include")\n'
              'if(NOT EXISTS "${PYTHON3_NUMPY_INCLUDE_DIRS}/numpy/arrayobject.h")\n'
              '  message(FATAL_ERROR "Target NumPy headers are missing")\n'
              'endif()\n# Find specified Python version')
        values.update(ENABLE_HEADLESS='1', CMAKE_ARGS=' '.join([
            '-DBUILD_LIST=core,imgproc,imgcodecs,python3', '-DBUILD_TESTS=OFF',
            '-DOPENCV_FORCE_PYTHON_LIBS=ON', '-DCMAKE_MODULE_LINKER_FLAGS=-static-libstdc++',
            '-DPYTHON3_NUMPY_VERSION=2.5.4',
            '-DBUILD_EXAMPLES=OFF', '-DBUILD_ANDROID_EXAMPLES=OFF',
            '-DBUILD_ANDROID_PROJECTS=OFF', '-DINSTALL_ANDROID_EXAMPLES=OFF',
            '-DWITH_UNIFONT=OFF', '-DWITH_AVIF=OFF', '-DWITH_OPENJPEG=OFF',
            '-DBUILD_PERF_TESTS=OFF', '-DBUILD_JAVA=OFF', '-DWITH_FFMPEG=OFF',
            '-DWITH_OPENEXR=OFF', '-DWITH_JASPER=OFF', '-DWITH_TIFF=OFF',
            '-DWITH_WEBP=OFF', '-DWITH_OPENCL=OFF']))
    env['CIBW_ENVIRONMENT'] = ' '.join(k + '=' + shlex.quote(v) for k, v in values.items())
    run([sys.executable, '-m', 'cibuildwheel', str(root), '--output-dir', str(output)], ROOT, env)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package', nargs='?', choices=list(SOURCES))
    parser.add_argument('--prepare', choices=['cffi', 'cryptography', 'numpy', 'opencv-python'])
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare)
    elif args.package:
        build(args.package)
    else:
        parser.error('package is required')
