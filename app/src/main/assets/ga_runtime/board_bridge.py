"""The one door from signed Python to the native phone-control session.

screen.py and hid.py both pass through here and never import each other. Device safety (consent,
takeover, live sharing, calibration) is enforced natively on every request.
"""
import json
import math
import sys


def call(tool, args, *, consent=True):
    """Send one request to a native tool ('screen', 'hid' or 'takeover') and return its reply."""
    if sys.platform != 'ios':
        raise RuntimeError('phone tools are iOS only')
    if consent:
        from ios_policy import require_consent
        require_consent()
    try:
        import _gaboard
    except ImportError:
        return {'ok': False, 'error': 'board_unavailable', 'message': '当前 App 未包含 iPhone 操作模块'}
    request = json.dumps({'tool': tool, 'args': args}, ensure_ascii=False)
    try:
        reply = json.loads(_gaboard.call(request))
    except ValueError:
        reply = None
    if not isinstance(reply, dict) or not isinstance(reply.get('ok'), bool):
        # Not a ValueError: those mean a request was refused before it left, and this one reached the device.
        raise RuntimeError('Invalid Board response')
    return reply


def takeover(action, args):
    """User handoff (pause / resume). It must work without data consent, like stop."""
    return call('takeover', {'action': action, **args}, consent=False)


def number(args, key, low, high, default=None):
    """A finite number in [low, high]; bool is rejected because it is not a measurement."""
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number')
    if not low <= value <= high:
        raise ValueError(f'{key} must be in [{low}, {high}]')
    return value


def only(args, allowed, tool):
    """Reject misspelled arguments instead of silently ignoring them."""
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise ValueError('Unknown arguments for %s: %s' % (tool, ', '.join(unknown)))
