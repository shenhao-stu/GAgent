#!/usr/bin/env python3
"""Fetch the upstream sherpa JNI archive, verify it, and keep the shipped ABI."""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/'
       'sherpa-onnx-static-link-onnxruntime-2.0.1.aar')
SHA256 = '07e042d97f3a6bd5b7fe74d4eef0513dc01a714b16c15a903250095aba43a575'
ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'build/downloads/sherpa-onnx-2.0.1.aar'
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != SHA256:
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise ValueError('sherpa-onnx source digest mismatch')
        source.write_bytes(data)
    target = ROOT / 'app/libs/sherpa-onnx-2.0.1-static-arm64.aar'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.part')
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as out:
        for entry in archive.infolist():
            if entry.is_dir() or (entry.filename.startswith('jni/') and not
                                  entry.filename.startswith('jni/arm64-v8a/')):
                continue
            info = zipfile.ZipInfo(entry.filename, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(info, archive.read(entry))
    temporary.replace(target)
    print('Verified sherpa-onnx 2.0.1 arm64 JNI archive')


if __name__ == '__main__':
    main()
