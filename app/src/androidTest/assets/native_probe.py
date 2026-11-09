"""Harmless synthetic checks of actual Android extension modules and the OCR bridge."""
import os
import sys
sys.path.insert(0, GA_DIR)
os.environ['GA_DIR'] = GA_DIR
import ssl
import struct
import zlib
import numpy as np
import cv2
import cffi
import bcrypt
import nacl
from nacl.signing import SigningKey
import paramiko
import cryptography
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends.openssl.backend import backend

key = AESGCM.generate_key(bit_length=256)
cipher = AESGCM(key)
nonce = os.urandom(12)
assert cipher.decrypt(nonce, cipher.encrypt(nonce, b'Android round trip', None), None) == b'Android round trip'
a, b = X25519PrivateKey.generate(), X25519PrivateKey.generate()
assert a.exchange(b.public_key()) == b.exchange(a.public_key())
signer = SigningKey.generate()
assert signer.verify_key.verify(signer.sign(b'Native signature')) == b'Native signature'
assert bcrypt.checkpw(b'synthetic-password', bcrypt.hashpw(b'synthetic-password', bcrypt.gensalt(4)))
ssh_key = paramiko.RSAKey.generate(2048)
assert ssh_key.verify_ssh_sig(b'identity test', paramiko.Message(ssh_key.sign_ssh_data(b'identity test').asbytes()))
np.testing.assert_allclose(np.linalg.solve([[3., 1.], [1., 2.]], [9., 8.]), [2., 3.])
assert np.finfo(np.longdouble).bits == 128
img = np.full((160, 640, 3), 255, dtype=np.uint8)
cv2.putText(img, 'GAgent 123', (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3, cv2.LINE_AA)
ok, encoded = cv2.imencode('.png', img)
assert ok and np.array_equal(cv2.imdecode(encoded, cv2.IMREAD_COLOR), img)
build_info = cv2.getBuildInformation()
assert '1.6.59' in build_info and 'ver 1.4)' in build_info, build_info
# Malformed ancillary text must not poison the subsequent PNG image/end reader.
text_chunk = b'zTXt' + b'synthetic\0\0' + b'x\x9cBROKEN'
chunk = struct.pack('>I', len(text_chunk) - 4) + text_chunk + struct.pack('>I', zlib.crc32(text_chunk))
png = encoded.tobytes()
damaged_metadata = np.frombuffer(png[:33] + chunk + png[33:], np.uint8)
assert np.array_equal(cv2.imdecode(damaged_metadata, cv2.IMREAD_COLOR), img)
assert cv2.resize(img, (320, 80)).shape == (80, 320, 3)
import droid
droid.ort_shim()
sys.path.insert(0, os.path.join(GA_DIR, 'models/ui_detect_v1'))
from ppocr_engine import PPOCR
ocr = PPOCR()(img)
transcript = ' '.join(row[1] for row in ocr)
assert '123' in transcript and 'gagent' in transcript.lower().replace(' ', ''), transcript
result = {'python': sys.version.split()[0], 'ssl': ssl.OPENSSL_VERSION,
          'crypto_ssl': backend.openssl_version_text(),
          'versions': {m.__name__: m.__version__ for m in [np, cv2, cffi, bcrypt, nacl, paramiko, cryptography]},
          'ocr': transcript, 'crypto': 'round trips passed', 'numpy': 'solve/quad precision passed',
          'opencv': 'PNG/resize passed'}
result['opencv_codecs'] = {'libpng': '1.6.59', 'zlib': '1.4', 'malformed_metadata': 'rejected without losing image'}
result['python_zlib'] = zlib.ZLIB_RUNTIME_VERSION
