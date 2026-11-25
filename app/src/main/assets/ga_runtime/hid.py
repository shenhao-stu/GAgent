"""Atomic tool: send keyboard and pointer input to the iPhone. It never reads the screen.

    import hid
    hid.tap(0.5, 0.8)                        # normalized 0..1 from top-left; count=2 double-taps in place
    hid.swipe(0.5, 0.7, 0.5, 0.3)            # drag up: shows lower content; flick=True flings it
    hid.stage_text('你好'); hid.type('你好')  # stage while GAgent is in front, paste into the focused field
    hid.key('enter'); hid.button('home')

Every input returns a delivery receipt only: {'ok', 'action_sent', 'sent_at', 'revision'}. Read the
result with screen. Pass frame_id (from a screen observation) to send only while the target still
looks like that frame; without it the input needs no shared screen at all, only the board and consent. Pointer actions additionally need AssistiveTouch and calibration. Which device delivers the input (ESP32 Bluetooth or USB) is a native choice.
"""
import re
import threading
import unicodedata
import weakref

import board_bridge

INPUTS = ('tap', 'long_press', 'swipe', 'type', 'key', 'button')
ACTIONS = (*INPUTS, 'stage_text', 'status', 'stop')
BUTTONS = ('home', 'back', 'search', 'control_center')
DESCRIPTION = (
    'Send input to the iPhone and return a delivery receipt (the host then attaches the resulting screen). '
    'tap {x,y} or {element}, with count:N for N clicks in place, nothing moving in between (2 a double tap, '
    '3 a triple tap, more to press one control several times; the buttons of a system alert ignore the first '
    'click after the pointer moved, so a tap that left the alert up is repeated with count:2); '
    'long_press {x,y|element, duration_ms?}; swipe {x,y,x2,y2,duration_ms?,hold_ms?,flick?} is one stroke of '
    'one finger: it moves evenly, stops at the end and lifts, so the content moves exactly that far (drag up to '
    'see lower content; without duration_ms it goes at about one screen height a second, which is also the '
    'fastest; hold_ms holds at the start before dragging); flick:true lifts while still moving, so the content '
    'keeps gliding, and duration_ms sets how fast; type {text, method?} pastes the staged text into the focused field of any '
    'app (iOS may first ask with an Allow Paste prompt; tap its allow button to let the paste through); '
    'method "keys" types printable ASCII keys instead, through the active input method (a pinyin keyboard '
    'composes them; key ctrl+space switches the input method); key {combo} such as enter or cmd+a (cmd+v is '
    "the system's own Paste of whatever was copied last); "
    'button {name} home, back, search (system Search from the Home screen) or control_center (opens Control '
    'Center on its first page); stage_text {text} puts the text '
    '(Chinese, newlines and tabs allowed) on the clipboard and works only while GAgent is in front; status {}; stop {}. '
    'Coordinates are normalized 0..1 from top-left. element is a number from the elements of the latest screen. '
    'A touch is bound to the latest screen frame_id and not sent when its target area changed; that refusal '
    'comes with the current screen. Pointer masks and changes after the check can still hide target changes; '
    'target_check reports a masked centre. button needs no frame. '
    'hid also works without screen: before the first screen call, inputs go by coordinates alone and '
    'no screen is attached. action_sent means input may have reached the phone; the receipt alone does not '
    'establish the UI outcome or whether repeating it is appropriate.')
PARAMETERS = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': list(ACTIONS)},
    'x': {'type': 'number'}, 'y': {'type': 'number'}, 'x2': {'type': 'number'}, 'y2': {'type': 'number'},
    'element': {'type': 'integer'}, 'count': {'type': 'integer', 'minimum': 1}, 'duration_ms': {'type': 'number'}, 'hold_ms': {'type': 'number'},
    'flick': {'type': 'boolean'}, 'text': {'type': 'string'}, 'method': {'type': 'string', 'enum': ['paste', 'keys']},
    'combo': {'type': 'string'}, 'name': {'type': 'string', 'enum': list(BUTTONS)},
    'frame_id': {'type': 'string'}}, 'required': ['action']}
ALLOWED = {
    'tap': ('x', 'y', 'count'), 'long_press': ('x', 'y', 'duration_ms'),
    'swipe': ('x', 'y', 'x2', 'y2', 'duration_ms', 'hold_ms', 'flick'),
    'type': ('text', 'method'), 'key': ('combo',), 'button': ('name',), 'stage_text': ('text',),
    'status': (), 'stop': (),
}
OPTIONAL = ('method', 'frame_id', 'count', 'hold_ms', 'flick')
# Threads that sent input. The host uses it to find the agents to stop when the user cancels a phone run.
DRIVERS = weakref.WeakSet()


def _text(value, keys):
    if not isinstance(value, str) or not value or any(unicodedata.category(c) == 'Cc' and c not in '\n\r\t' for c in value):
        raise ValueError('text must be nonempty; only newline and tab control characters are allowed')
    if keys and any(not 32 <= ord(c) <= 126 for c in value):
        raise ValueError('method "keys" accepts printable ASCII; use paste for other text')
    return value


def _checked(action, key, args):
    value = args.get(key)
    if key == 'frame_id':
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_:-]{1,128}', value):
            return value
        raise ValueError('frame_id must be the opaque identifier returned by screen')
    if key == 'method':
        if value in ('paste', 'keys'):
            return value
        raise ValueError('method must be "paste" or "keys"')
    if key == 'count':
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value < 2**63:
            return value
        raise ValueError('count must be a positive 64-bit whole number')
    if key == 'text':
        return _text(value, keys=args.get('method') == 'keys')
    if key == 'combo':
        if isinstance(value, str) and re.fullmatch(r'[!-~]{1,40}', value):
            return value
        raise ValueError('combo must be a keyboard shortcut such as cmd+a')
    if key == 'name':
        if value in BUTTONS:
            return value
        raise ValueError('name must be one of: ' + ', '.join(BUTTONS))
    if key == 'flick':
        if isinstance(value, bool):
            return value
        raise ValueError('flick must be true or false')
    if key == 'hold_ms':
        return board_bridge.number(args, key, 0, 120000)
    if key == 'duration_ms':
        return board_bridge.number(args, key, 100, 120000, 800) if action == 'long_press' else board_bridge.number(args, key, 50, 120000)
    return board_bridge.number(args, key, 0, 1)


def _arguments(action, args):
    if action not in ACTIONS:
        raise ValueError('Unknown hid action; use one of: ' + ', '.join(ACTIONS))
    allowed = ALLOWED[action] + (('frame_id',) if action in INPUTS else ())
    board_bridge.only(args, allowed, 'hid ' + action)
    # A swipe without a duration goes at the device's own pace: one even motion.
    optional = OPTIONAL + (('duration_ms',) if action == 'swipe' else ())
    return {key: _checked(action, key, args) for key in allowed if key in args or key not in optional}


def send(action, **args):
    """Validate and deliver one action. Arguments left as None are omitted."""
    clean = _arguments(action, {key: value for key, value in args.items() if value is not None})
    if action in INPUTS:
        DRIVERS.add(threading.current_thread())
    # Status and stop must always work: stopping needs no consent.
    return board_bridge.call('hid', {'action': action, **clean}, consent=action not in ('status', 'stop'))


def call(args):
    """Tool entry: {'action': ..., and that action's arguments}."""
    if not isinstance(args, dict):
        raise ValueError('arguments must be an object')
    return send(args.get('action'), **{key: value for key, value in args.items() if key != 'action'})


def tap(x, y, frame_id=None, count=None):
    """count clicks that many times in place: 2 is a double tap, and what the buttons of a system alert need."""
    return send('tap', x=x, y=y, count=count, frame_id=frame_id)


def long_press(x, y, duration_ms=800, frame_id=None):
    return send('long_press', x=x, y=y, duration_ms=duration_ms, frame_id=frame_id)


def swipe(x, y, x2, y2, duration_ms=None, frame_id=None, hold_ms=None, flick=None):
    """One stroke that stops at the end and lifts; flick=True lifts while still moving, so the content glides on."""
    return send('swipe', x=x, y=y, x2=x2, y2=y2, duration_ms=duration_ms, hold_ms=hold_ms, flick=flick, frame_id=frame_id)


def type(text, method='paste', frame_id=None):
    return send('type', text=text, method=method, frame_id=frame_id)


def key(combo, frame_id=None):
    return send('key', combo=combo, frame_id=frame_id)


def button(name, frame_id=None):
    return send('button', name=name, frame_id=frame_id)


def stage_text(text):
    return send('stage_text', text=text)


def status():
    return send('status')


def stop():
    return send('stop')
