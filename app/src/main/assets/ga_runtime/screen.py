"""Atomic tool: read the iPhone screen. It never clicks, types or sends keys.

    import screen
    shot = screen.capture()                 # {'frame_id', 'path', 'width', 'height', 'elements', ...}
    x, y = screen.point(shot, 7)            # centre of element 7, normalized 0..1 from top-left
    screen.find(shot, '发送')               # elements whose label contains the text

With image=True, the picture is saved to shot['path']; a requested region to shot['detail_path'].
The native ReplayKit capture source may briefly move the pointer to refresh a stale frame.
"""
import base64
import os
import re
import time
import uuid
from pathlib import Path

import board_bridge

DESCRIPTION = (
    'Read the iPhone screen. Choose image and OCR independently. By default returns text only: '
    'frame_id and numbered OCR elements '
    '("7 发送 @0.871,0.890": number, label, centre) from on-device recognition; not every icon is listed and OCR '
    'cannot prove a label is a button. marks:true draws the returned element numbers on the image. '
    'image:true includes the screenshot; ocr:false skips recognition and implies image:true if image is omitted. '
    'Use image:true,ocr:false for visual-only reading, image:true for both, or image:false for text only. '
    'Automatic post-input reads keep the last successful image/ocr choice. '
    'marks:true needs image and OCR. '
    'region {x,y,width,height} adds an enlargement of that '
    'part for reading small text; marks or region imply image:true if omitted. '
    'Coordinates always refer to the full screen, normalized 0..1 from top-left. '
    'same_as_previous is a visual page-similarity hint. This tool never clicks, types or sends '
    'keys; a stale capture may briefly move the pointer to prove freshness.')
PARAMETERS = {'type': 'object', 'properties': {
    'image': {'type': 'boolean'}, 'marks': {'type': 'boolean'}, 'ocr': {'type': 'boolean'},
    'region': {'type': 'object', 'properties': {key: {'type': 'number'} for key in ('x', 'y', 'width', 'height')},
               'required': ['x', 'y', 'width', 'height']}}}
SCREEN_FOLDER = 'temp/iphone_screens'
KEPT_SCREENS = 20
KEPT_SECONDS = 86400
ELEMENT = re.compile(r'(\d+) (.*) @([01]\.\d+),([01]\.\d+)', re.DOTALL)


def _arguments(args):
    board_bridge.only(args, ('image', 'marks', 'ocr', 'region'), 'screen')
    clean = {}
    for key in ('image', 'marks', 'ocr'):
        if key in args:
            if not isinstance(args[key], bool):
                raise ValueError(key + ' must be true or false')
            clean[key] = args[key]
    if clean.get('marks') is True and clean.get('ocr') is False:
        raise ValueError('marks:true requires OCR candidates; omit ocr:false')
    if 'region' in args:
        region = args['region']
        if not isinstance(region, dict) or set(region) != {'x', 'y', 'width', 'height'}:
            raise ValueError('region must contain x,y,width,height in full-screen coordinates')
        region = {key: board_bridge.number(region, key, 0, 1) for key in region}
        if region['width'] <= 0 or region['height'] <= 0:
            raise ValueError('region must have positive width and height')
        if region['x'] + region['width'] > 1 or region['y'] + region['height'] > 1:
            raise ValueError('region must be inside the full screen')
        clean['region'] = region
    clean.setdefault('image', bool(clean.get('marks') or 'region' in clean or clean.get('ocr') is False))
    clean.setdefault('ocr', True)
    if not clean['image']:
        if clean.get('marks') or 'region' in clean:
            raise ValueError('marks and region need image:true')
        if not clean['ocr']:
            raise ValueError('Choose at least one screen output: image or OCR')
    return clean


def _image_block(encoded, mime, limit):
    """Check the declared image header and wrap the bytes for the model."""
    if mime not in ('image/jpeg', 'image/png') or not isinstance(encoded, str):
        raise ValueError('Board screenshot is missing a supported image')
    if len(encoded) > limit:
        raise ValueError('Board screenshot is too large')
    pixels = base64.b64decode(encoded, validate=True)
    signature = b'\xff\xd8\xff' if mime == 'image/jpeg' else b'\x89PNG\r\n\x1a\n'
    if not pixels.startswith(signature):
        raise ValueError('Board screenshot bytes do not match MIME type')
    return pixels, {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': encoded}}


def _save(pixels, mime):
    """Screens are temporary data, bounded by age and count."""
    from ios_policy import checked_path, data_root
    directory = Path(checked_path(data_root() / SCREEN_FOLDER, write=True))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid.uuid4().hex + ('.jpg' if mime == 'image/jpeg' else '.png'))
    with path.open('xb') as file:
        os.chmod(path, 0o600)
        file.write(pixels)
    files = sorted(directory.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)
    for index, old in enumerate(files):
        if old.is_file() and (index >= KEPT_SCREENS or old.stat().st_mtime < time.time() - KEPT_SECONDS):
            old.unlink()
    return path


def _observe(args):
    """One native observation: (reply without pixels, image block, detail block)."""
    args = _arguments(args)
    reply = board_bridge.call('screen', args)
    if not reply.get('ok'):
        return reply, None, None
    for key in ('width', 'height'):
        board_bridge.number(reply, key, 1, 16384)
    if not args['image']:
        return reply, None, None
    pixels, image = _image_block(reply.pop('image_base64', None), reply.pop('mime_type', None), 16 * 1024 * 1024)
    detail = None
    if 'detail_image_base64' in reply:
        detail_pixels, detail = _image_block(reply.pop('detail_image_base64'), 'image/jpeg', 4 * 1024 * 1024)
        path = _save(detail_pixels, 'image/jpeg')
        reply.update(detail_path=str(path), detail_markdown=f'![iPhone screen detail]({path})')
    path = _save(pixels, image['source']['media_type'])
    reply.update(path=str(path), markdown=f'![iPhone screen]({path})')
    return reply, image, detail


def capture(marks=False, ocr=True, region=None, image=True):
    """Read from a script; image=True saves 'path' and, when requested, 'detail_path'."""
    args = {'image': image, 'marks': marks, 'ocr': ocr}
    if region is not None:
        args['region'] = region
    return _observe(args)[0]


def call(args):
    """Tool entry. The handler takes the image blocks out and attaches them to the model turn."""
    reply, image, detail = _observe(args)
    if image:
        reply['_model_image'] = image
    if detail:
        reply['_detail_model_image'] = detail
    return reply


def elements(observation):
    """Parsed elements of an observation: [{'number', 'label', 'x', 'y'}, ...]."""
    found = []
    for line in observation.get('elements', []):
        match = ELEMENT.fullmatch(line)
        if match:
            number, label, x, y = match.groups()
            found.append({'number': int(number), 'label': label, 'x': float(x), 'y': float(y)})
    return found


def point(observation, number):
    """Centre (x, y) of the numbered element. Numbers mean nothing on another frame."""
    for element in elements(observation):
        if element['number'] == number:
            return element['x'], element['y']
    raise ValueError('That element number is not in the list returned with this frame_id')


def find(observation, text):
    """Elements whose label contains the text."""
    return [element for element in elements(observation) if text in element['label']]
