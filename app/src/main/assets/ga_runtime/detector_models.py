"""Install user-supplied UI detectors without bundling or downloading weights."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time

_LOCK = threading.Lock()


def root():
    return Path(os.environ.get('GA_DIR') or Path(__file__).resolve().parent)


def model_path():
    base = root()
    config = base / 'kv/ga.detector.json'
    if config.exists():
        name = json.loads(config.read_text())['file']
        path = (base / 'user_models' / name).resolve()
        if path.parent != (base / 'user_models').resolve() or not path.is_file():
            raise ValueError('Installed detector is missing or invalid; import it again')
        return path
    return base / 'models/ui_detect_v1/models/ui_detect_yolo.onnx'


def status():
    path = model_path()
    return {'ok': True, 'installed': path.is_file(), 'bytes': path.stat().st_size if path.is_file() else 0}


def validate_model(path):
    import droid
    import numpy as np
    droid.ort_shim()
    import onnxruntime as ort
    session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    inputs = session.get_inputs()
    if len(inputs) != 1 or len(inputs[0].shape) != 4 or inputs[0].shape[1] != 3:
        raise ValueError('Expected one RGB NCHW input')
    # Actual inference checks both square and rectangular screens, including NMS.
    for height in (640, 384):
        outputs = session.run(None, {inputs[0].name: np.zeros((1, 3, height, 640), dtype=np.float32)})
        if len(outputs) != 1 or outputs[0].shape != (1, 300, 6) or not np.isfinite(outputs[0]).all():
            raise ValueError('Expected finite NMS output [1,300,6]')
        rows = outputs[0][0]
        if ((rows[:, 4] < 0) | (rows[:, 4] > 1) | (rows[:, 5] < 0) | (rows[:, 5] > 20)).any():
            raise ValueError('Expected 21-class Android UI detector')


def install(upload):
    with _LOCK:
        base = root()
        src = Path(upload).resolve()
        if src.parent != (base / 'uploads').resolve() or not src.is_file():
            raise ValueError('Select an uploaded ONNX model')
        if not 0 < src.stat().st_size <= 32 * 1024 * 1024:
            raise ValueError('Model must be 1 byte..32 MiB')
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        folder = base / 'user_models'
        folder.mkdir(exist_ok=True)
        dst = folder / ('ui_detect_' + sha + '.onnx')
        created = not dst.exists()
        if created:
            shutil.copyfile(src, dst)
        try:
            validate_model(dst)
            config = base / 'kv/ga.detector.json'
            config.parent.mkdir(exist_ok=True)
            fd, pending = tempfile.mkstemp(dir=config.parent, prefix='.detector-')
            try:
                with os.fdopen(fd, 'w') as handle:
                    json.dump({'file': dst.name, 'sha256': sha}, handle)
                os.replace(pending, config)
            finally:
                if os.path.exists(pending): os.unlink(pending)
        except Exception:
            if created: dst.unlink(missing_ok=True)
            raise
        src.unlink()  # imports no longer need the duplicate upload
        return {**status(), 'sha256': sha}


def test_screen():
    import droid
    started = time.monotonic()
    image = droid.shot()
    elements = droid.ui_detect(image)
    return {**status(), 'icons': sum(e['type'] == 'icon' for e in elements),
            'text': sum(e['type'] == 'text' for e in elements),
            'width': int(image.shape[1]), 'height': int(image.shape[0]),
            'elapsed_ms': round((time.monotonic() - started) * 1000)}


def handle(command):
    try:
        if command == '/detector.status': result = status()
        elif command == '/detector.test': result = test_screen()
        elif command.startswith('/detector.install '): result = install(command.partition(' ')[2])
        else: raise ValueError('Unknown detector command')
        return json.dumps(result)
    except Exception as exc:
        return json.dumps({'ok': False, 'error': str(exc)[:200]})
