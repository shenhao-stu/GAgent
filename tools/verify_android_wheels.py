#!/usr/bin/env python3
"""Check Android wheel ELF headers and embedded-Python linkage without loading code."""
import argparse
from pathlib import Path
import struct
import zipfile


def verify_elf(data):
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Expected little-endian ELF64')
    if struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('Expected arm64 machine')
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if size != 56 or not count or offset + size * count > len(data):
        raise ValueError('Invalid program headers')
    segments = [struct.unpack_from('<IIQQQQQQ', data, offset + i * size) for i in range(count)]
    loads = [s for s in segments if s[0] == 1]
    if not loads or any(s[7] < 16384 for s in loads):
        raise ValueError('Expected at least 16KB load alignment')
    tags = []
    for segment in (s for s in segments if s[0] == 2):
        start, length = segment[2], segment[5]
        if start + length > len(data) or length % 16:
            raise ValueError('Invalid dynamic table')
        tags.extend(struct.unpack_from('<qQ', data, pos) for pos in range(start, start + length, 16))
    address = next((v for k, v in tags if k == 5), None)
    strings = next((s[2] + address - s[3] for s in loads
                    if address is not None and s[3] <= address < s[3] + s[5]), None)
    if strings is None:
        raise ValueError('Missing dynamic string table')
    needed = []
    for key, offset in tags:
        if key == 1:
            start = strings + offset
            end = data.index(b'\0', start)
            needed.append(data[start:end].decode('ascii'))
    if 'libpython3.13.so' not in needed:
        raise ValueError('Extension must link the embedded libpython3.13.so explicitly')
    if 'libc++_shared.so' in needed:
        raise ValueError('Unexpected unbundled C++ runtime dependency')


def verify(directory):
    wheels = sorted(directory.glob('*.whl'))
    if not wheels:
        raise ValueError('No native wheels found')
    count = 0
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.endswith('.so'):
                    try:
                        verify_elf(archive.read(name))
                    except (ValueError, struct.error) as error:
                        raise ValueError(f'{wheel.name}:{name}: {error}') from error
                    count += 1
    if not count:
        raise ValueError('No native extensions found')
    print(f'Verified {count} arm64 extensions: Python linkage and 16KB ELF alignment')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    verify(parser.parse_args().directory)
