"""GAnet QR pairing protocol. Keep byte-for-byte behavior aligned with PC."""
import base64
import hashlib
import hmac
import json
import struct

PROTOCOL = "ganet-qr-pair-v1"
SUITE = "hkdf-sha256+hmac-sha256"
QR_SCHEME = "ganet://pair/v1#"
SECRET_BYTES = 32
NONCE_BYTES = 16
SESSION_BYTES = 24

_PC_FIELDS = ("protocol", "suite", "sessionId", "ownerId", "role", "computerDeviceId", "displayName", "platform", "model", "tailnetIp", "sshUsername", "sshPort", "sshHostKey", "pcNonce", "expiresAt")
_PHONE_FIELDS = ("protocol", "suite", "sessionId", "ownerId", "role", "pcHelloHash", "computerDeviceId", "pcNonce", "phoneDeviceId", "displayName", "platform", "model", "publicKey", "phoneNonce", "expiresAt")
_RESULT_FIELDS = ("protocol", "suite", "sessionId", "ownerId", "role", "phoneHelloHash", "computerDeviceId", "phoneDeviceId", "state", "expiresAt")


def b64u_encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64u_decode(value, size=None):
    if not isinstance(value, str) or not value or len(value) > 512 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value):
        raise ValueError("invalid base64url value")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if size is not None and len(raw) != size:
        raise ValueError("invalid decoded length")
    return raw


def _field_bytes(value):
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list, float)):
        raise ValueError("unsupported canonical value")
    if isinstance(value, int):
        if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
            raise ValueError("integer out of range")
        return b"i" + struct.pack(">Q", value)
    if isinstance(value, bytes):
        return b"b" + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("field too long")
        return b"s" + encoded
    raise ValueError("unsupported canonical value")


def canonical(message, fields):
    if set(message) != set(fields):
        raise ValueError("message fields do not match schema")
    out = bytearray(b"GANETPAIR\x01")
    for name in fields:
        key = name.encode("ascii")
        val = _field_bytes(message[name])
        out += struct.pack(">H", len(key)) + key + struct.pack(">I", len(val)) + val
    return bytes(out)


def _hkdf(secret, session_id, label):
    if len(secret) != SECRET_BYTES:
        raise ValueError("invalid QR secret length")
    session_raw = b64u_decode(session_id, SESSION_BYTES)
    salt = hashlib.sha256(PROTOCOL.encode("ascii") + b"\x00" + session_raw).digest()
    prk = hmac.new(salt, secret, hashlib.sha256).digest()
    info = (PROTOCOL + "/" + SUITE + "/" + label).encode("ascii")
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def _schema(kind):
    if kind == "pcHello": return _PC_FIELDS, "pc-to-phone/hello"
    if kind == "phoneHello": return _PHONE_FIELDS, "phone-to-pc/confirm"
    if kind == "result": return _RESULT_FIELDS, "pc-to-phone/result"
    raise ValueError("unknown envelope kind")


def envelope(kind, message, secret):
    fields, label = _schema(kind)
    raw = canonical(message, fields)
    mac = hmac.new(_hkdf(secret, message["sessionId"], label), raw, hashlib.sha256).digest()
    return {"kind": kind, "message": message, "mac": b64u_encode(mac)}


def verify_envelope(value, kind, secret):
    if not isinstance(value, dict) or set(value) != {"kind", "message", "mac"} or value.get("kind") != kind:
        raise ValueError("invalid envelope")
    message = value.get("message")
    expected = envelope(kind, message, secret)["mac"]
    if not isinstance(value.get("mac"), str) or not hmac.compare_digest(value["mac"], expected):
        raise ValueError("envelope authentication failed")
    validate_message(kind, message)
    return message


def validate_message(kind, message):
    fields, _ = _schema(kind)
    canonical(message, fields)
    if message["protocol"] != PROTOCOL or message["suite"] != SUITE or message["role"] != ("pc" if kind in ("pcHello", "result") else "phone"):
        raise ValueError("unsupported pairing protocol")
    b64u_decode(message["sessionId"], SESSION_BYTES)
    if kind in ("pcHello", "phoneHello"): b64u_decode(message["pcNonce"], NONCE_BYTES)
    if kind == "phoneHello":
        b64u_decode(message["phoneNonce"], NONCE_BYTES); b64u_decode(message["pcHelloHash"], 32)
    if kind == "result":
        b64u_decode(message["phoneHelloHash"], 32)
        if message["state"] not in ("approved", "cancelled", "rejected"): raise ValueError("invalid result state")
    if not str(message["ownerId"]).isdigit(): raise ValueError("invalid owner identity")
    for name in (("computerDeviceId", "phoneDeviceId") if kind != "pcHello" else ("computerDeviceId",)):
        if not isinstance(message[name], str) or not message[name].startswith("dev_") or len(message[name]) > 128: raise ValueError("invalid device identity")
    if not isinstance(message["expiresAt"], int) or message["expiresAt"] <= 0: raise ValueError("invalid expiry")


def envelope_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return b64u_encode(hashlib.sha256(raw).digest())


def make_qr_payload(session_id, secret, expires_at):
    binary = b"\x01" + b64u_decode(session_id, SESSION_BYTES) + secret + struct.pack(">Q", expires_at)
    if len(secret) != SECRET_BYTES: raise ValueError("invalid QR payload")
    return QR_SCHEME + b64u_encode(binary)


def parse_qr_payload(value):
    if not isinstance(value, str) or not value.startswith(QR_SCHEME) or len(value) > 256: raise ValueError("invalid pairing QR code")
    raw = b64u_decode(value[len(QR_SCHEME):])
    if len(raw) != 65 or raw[0] != 1: raise ValueError("invalid pairing QR code")
    return {"sessionId": b64u_encode(raw[1:25]), "secret": raw[25:57], "expiresAt": struct.unpack(">Q", raw[57:65])[0]}
