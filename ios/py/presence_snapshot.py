"""Read-only view of the agent sessions for the status UI (ios/Presence).

It observes and never drives: no engine state changes here. poll2 is not reused because a poll consumes the
pending question and the notification queue. Only the model's own captions (`desc`, `<summary>`) leave this
module; tool arguments, such as the text typed into the phone, do not.
"""
import json
import re
import sys

TITLE, NOW, STEP, QUESTION, CHOICE, FINAL = 40, 60, 40, 200, 24, 160
EMPTY = '{"v":1,"runs":[]}'
PHONE_TOOLS = ('screen', 'hid')
_ACTION = re.compile(r'"action"\s*:\s*"([a-z_]{1,24})"')
_FAILED = re.compile(r'^(?:!!!Error:|\[Error:)|(?:^|\n)(?:!!!Error:[^\n]*|\[!!! 流异常中断 [^\n]* !!!\])\s*$')
_FENCED = re.compile(r'```[\s\S]*?```')
_TURN = re.compile(r'^[ \t]*\**[ \t]*(?:LLM Running\s*\(Turn\s*\d+\)|Turn\s*\d+)\s*\.{0,3}[ \t]*\**[ \t]*$', re.M | re.I)
_TAGGED = re.compile(r'<(thinking|summary)>[\s\S]*?</\1>')


def _clip(value, limit):
    text = ' '.join(str(value or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _choices(candidates):
    # Native-card budget only: a whole group of exact answer values, or the chat's full picker.
    return candidates if len(candidates) <= 6 and all(len(c) <= CHOICE for c in candidates) else []


def _tool(events):
    """The call in flight: its name, its action and the model's caption for it."""
    for event in reversed(events):
        if event.get('status') == 'running':
            action = _ACTION.search(str(event.get('input_summary') or ''))
            return {'name': str(event.get('name') or ''), 'action': action.group(1) if action else '',
                    'desc': _clip(event.get('desc'), NOW)}
    return None


def _first_line(text):
    return next((line for line in _FENCED.sub('', str(text or '')).splitlines() if line.strip()), '')


def _closing(final):
    """The model's closing words: the first line of prose of the last turn, without the run's scaffolding."""
    text = str(final or '')
    turns = list(_TURN.finditer(text))
    return _first_line(_TAGGED.sub('', text[turns[-1].end():] if turns else text))


def _run(entry, session):
    state = session.state
    with session.lock:
        gen, running, steps = state.get('gen', 0), bool(state.get('running')), list(state.get('steps') or [])
        events = [e for e in state.get('tool_events') or [] if e.get('gen') == gen]
        prompt, final = state.get('prompt') or '', state.get('final') or ''
        reply_token = entry._ios_question_token(session)
    if not (running or prompt):
        return None
    ask = None if running or not steps else entry._extract_ask(steps[-1].get('text') or '')
    return {
        'cid': entry._pub_cid(session.cid) or '', 'gen': int(gen or 0), 'running': running,
        'stopping': bool(getattr(session.agent, 'stop_sig', False)),
        'title': _clip(_first_line(prompt), TITLE), 'step': len(steps),
        'tool': _tool(events) if running else None,
        'trail': [_clip(s.get('summary'), STEP) for s in steps if (s.get('summary') or '').strip()][-2:],
        'ask': ask and {'question': _clip(ask.get('question'), QUESTION),
                        'candidates': _choices(ask.get('candidates') or []),
                        **({'reply_token': reply_token} if reply_token else {})},
        'paused': bool(getattr(session, '_phone_pause_token', None)),
        'used_phone': any(e.get('name') in PHONE_TOOLS for e in events),
        'final': '' if running else _clip(_closing(final), FINAL),
        'failed': not running and bool(_FAILED.search(_FENCED.sub('', final).strip())),
    }


def snapshot():
    """Every live conversation that has run a task, as compact JSON. Empty until the engine has started."""
    entry = sys.modules.get('android_entry')
    if entry is None or not getattr(entry, '_INITED', False):
        return EMPTY
    with entry._reg_lock:
        sessions = [s for s in entry._REG.values() if not s.retired]
    runs = [run for run in (_run(entry, s) for s in sessions) if run]
    return json.dumps({'v': 1, 'lang': 'en' if entry._LANG == 'en' else 'zh', 'runs': runs}, ensure_ascii=False)
