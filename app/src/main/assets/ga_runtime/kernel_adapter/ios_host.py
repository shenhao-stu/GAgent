"""Signed iOS host for the shared agent loop. The writable workspace supplies data only."""
import functools
import hashlib
import json
import os
import re
import time
from pathlib import Path

import ga
import ios_policy as policy
from agent_loop import StepOutcome


def load_schema(suffix=''):
    path = policy.code_root() / 'assets' / ('tools_schema' + suffix + '.json')
    return policy.tool_schema(json.loads(path.read_text(encoding='utf-8')))


def seed_memory(directory):
    path = Path(directory) / 'global_mem_insight.txt'
    try:
        with path.open('x', encoding='utf-8') as output:
            output.write(policy.MEMORY_SEED)
    except FileExistsError:
        pass


def read_index():
    try:
        path = policy.data_root() / 'memory/global_mem_insight.txt'
        return Path(policy.checked_path(path)).read_text(encoding='utf-8')
    except (FileNotFoundError, ValueError):
        return ''


@functools.lru_cache(maxsize=1)
def retired_routes():
    return frozenset(json.loads((policy.code_root() / 'assets/legacy-route-hashes.json').read_text()))


def get_global_memory():
    root = policy.data_root()
    lines = (line for line in read_index().splitlines()
             if hashlib.sha256(line.encode()).hexdigest() not in retired_routes())
    insight = policy.project_memory('\n'.join(lines), ())
    return f'\ncwd = {root / "temp"}\n{policy.MEMORY_STRUCTURE}\n{insight}'


def get_system_prompt():
    language = 'English' if os.environ.get('GA_LANG') == 'en' else '简体中文'
    return policy.SYSTEM_PROMPT + time.strftime('\nToday: %Y-%m-%d %a\n') + get_global_memory() + f'\n[LANG] {language}\n'


class Unobserved(Exception):
    """A conversation that acts on what it sees has no current picture to act on."""


class IOSHandler(ga.GenericAgentHandler):
    """Policy for the two atomic phone tools. Only this layer knows both screen and hid:
    it binds inputs to the observation the model received, resolves element numbers, and shows the model the
    screen after each input, or in place of one that had no current picture to go by.
    Each call sends at most one action; the model decides what to do with its result.

    That holds for a conversation that reads the screen. One that never has uses hid on its own:
    its inputs go by coordinates, bound to no image and followed by none."""
    KEPT_FRAMES = 3
    PAUSED = {'ok': False, 'error': '用户正在接管，请等待用户明确继续'}
    UNOBSERVED = {'ok': False, 'action_sent': False,
                  'error': '未发送：这次输入没有可依据的当前画面。按本轮返回的画面重新定位；没有返回画面时先用 screen 读屏'}

    def dispatch(self, tool_name, args, response, index=0, tool_num=1):
        if tool_name not in policy.LOCAL_TOOLS | policy.DEVICE_TOOLS | {'no_tool', 'bad_json'}:
            return StepOutcome({'status': 'error', 'msg': policy.UNSUPPORTED_TOOL}, next_prompt='\n')
        return (yield from super().dispatch(tool_name, args, response, index, tool_num))

    def invalidate_phone_observation(self):
        """The user had the phone: nothing the model saw before stands for the screen any more."""
        for key in ('_phone_frame', '_pending_phone_frame', '_image', '_detail_image', '_phone_elements'):
            vars(self).pop(key, None)

    def do_ask_user(self, args, response):
        if getattr(self, '_used_phone', False):
            release_input()
            self.invalidate_phone_observation()
        return (yield from super().do_ask_user(args, response))

    def do_code_run(self, args, response):
        import hid
        import threading
        driver = threading.current_thread()
        hid.DRIVERS.discard(driver)  # inline_eval must not inherit an earlier turn's HID use
        self._in_code_run = True
        try:
            return (yield from super().do_code_run(args, response))
        finally:
            if driver in hid.DRIVERS:
                self._used_phone = True  # this turn stays stoppable after inline HID returns
            self._in_code_run = False

    def _keep_screen(self, result):
        """Hold pixels and/or OCR until this turn delivers the observation."""
        image = result.pop('_model_image', None)
        detail = result.pop('_detail_model_image', None)
        if not result.get('ok') or not result.get('frame_id'):
            return
        self._image = image
        self._detail_image = detail
        self._pending_phone_frame = result.get('frame_id')
        self._phone_sees = True  # from now on this conversation acts on what it saw
        import screen
        known = dict(getattr(self, '_phone_elements', {}))
        if result.get('element_sources', {}).get('ocr') != 'skipped':
            known[result.get('frame_id')] = {e['number']: (e['x'], e['y']) for e in screen.elements(result)}
        self._phone_elements = dict(list(known.items())[-self.KEPT_FRAMES:])

    def _read_screen(self, args):
        import screen
        result = screen.call(args)
        if result.get('ok'):
            self._screen_options = {'image': bool(result.get('_model_image')), 'ocr': args.get('ocr', True)}
        self._keep_screen(result)
        return result

    def _drop_screen(self):
        self._phone_frame = None
        for key in ('_pending_phone_frame', '_image', '_detail_image'):
            vars(self).pop(key, None)

    def do_screen(self, args, response):
        if getattr(self, '_phone_pause_token', None):
            return StepOutcome(dict(self.PAUSED), next_prompt='\n')
        self._used_phone = True
        try:
            result = self._read_screen(_tool_arguments(args))
        except Exception as exc:
            result = {'status': 'error', 'msg': str(exc)}
        return StepOutcome(result, next_prompt=self._get_anchor_prompt())

    def _bound_input(self, clean):
        """Bind an input to the delivered frame and turn an element number into its coordinates.

        A conversation that has not read the screen sends its input as it is: hid needs no screen for that.
        """
        # The buttons are system gestures with no target on the page: they are not tied to what it showed.
        needs_frame = clean.get('action') != 'button'
        if needs_frame and 'frame_id' not in clean:
            if getattr(self, '_phone_frame', None):
                clean['frame_id'] = self._phone_frame
            elif getattr(self, '_phone_sees', False):
                raise Unobserved
        if 'element' in clean:
            number = clean.pop('element')
            if isinstance(number, str) and re.fullmatch(r'[1-9][0-9]{0,2}', number):
                number = int(number)
            if not isinstance(number, int) or isinstance(number, bool):
                raise ValueError('element must be an integer from the screen element list')
            if 'x' in clean or 'y' in clean:
                raise ValueError('Give either element or x,y, not both')
            centres = getattr(self, '_phone_elements', {}).get(clean.get('frame_id'))
            if centres is None or number not in centres:
                raise ValueError('That element number is not in the list returned with this frame_id. '
                                 'Pick a number from the latest returned list, or tap by x,y.')
            clean['x'], clean['y'] = centres[number]
        return clean

    def do_hid(self, args, response):
        import hid
        clean = _tool_arguments(args)
        action = clean.get('action')
        is_input = action in hid.INPUTS
        if action not in ('status', 'stop'):
            if getattr(self, '_phone_pause_token', None):
                return StepOutcome(dict(self.PAUSED), next_prompt='\n')
            self._used_phone = True
        # The picture the model acts on stays valid unless this input may have reached the phone.
        unsent = False
        try:
            result = hid.call(self._bound_input(clean) if is_input else clean)
            unsent = result.get('action_sent') is False
            if is_input and getattr(self, '_phone_sees', False):
                if result.get('ok'):
                    result = self._observed(result)
                elif unsent and result.get('error_code') == 'frame_changed':
                    result = self._shown(result)
        except Unobserved:
            result, unsent = self._shown(dict(self.UNOBSERVED)), True
        except ValueError as exc:  # raised by the checks before anything is sent
            result, unsent = {'status': 'error', 'msg': str(exc)}, True
        except Exception as exc:
            result = {'status': 'error', 'msg': str(exc)}
        if action == 'stop' or is_input and result.get('ok') is not True and not unsent:
            self._drop_screen()
        return StepOutcome(result, next_prompt=self._get_anchor_prompt())

    def _look(self):
        """Read once using the model's latest successful choice of outputs."""
        try:
            return self._read_screen(getattr(self, '_screen_options', {}))
        except Exception as exc:
            return {'ok': False, 'error': str(exc)}

    def _observed(self, receipt):
        """After a delivered input, read the screen once so the model judges the effect from it."""
        observation = self._look()
        if observation.get('ok'):
            result = {**receipt, **observation}
            if 'timing_ms' in receipt:
                result['timing_ms'] = {**receipt['timing_ms'], **observation.get('timing_ms', {})}
            return result
        reason = str(observation.get('error') or observation.get('message') or '')
        return {**receipt, 'ok': False, 'action_sent': True, 'safe_to_retry': False, 'observation_error': reason,
                'error': 'Action was sent, but its result could not be observed; '
                         'read a fresh screen before retrying. ' + reason}

    def _shown(self, refusal):
        """Nothing was sent because the picture the model went by no longer stands: answer with the current one,
        so finding the target again costs no extra step."""
        if getattr(self, '_pending_phone_frame', None):
            return refusal  # this turn already carries a newer picture
        observation = self._look()
        return {**observation, **refusal} if observation.get('ok') else refusal

    def do_pc_link(self, args, response):
        return self._fixed_tool(policy.pc_link, args)

    def _fixed_tool(self, tool, args):
        try:
            result = tool(_tool_arguments(args))
        except Exception as exc:
            result = {'status': 'error', 'msg': str(exc)}
        return StepOutcome(result, next_prompt=self._get_anchor_prompt())

    def turn_end_callback(self, *args):
        text = super().turn_end_callback(*args)
        image = vars(self).pop('_image', None)
        detail = vars(self).pop('_detail_image', None)
        pending = vars(self).pop('_pending_phone_frame', None)
        # Text-only models act on the delivered OCR coordinates of this same frame.
        if pending:
            self._phone_frame = pending
        return [{'type': 'text', 'text': text}, image] + ([detail] if detail else []) if image else text


def _tool_arguments(args):
    """The model's arguments without the loop's bookkeeping keys and the caption every tool call may carry.

    The shared desc_inject_hook plugin adds an optional `desc` to each tool's schema for the chat UI.
    """
    return {key: value for key, value in args.items() if not key.startswith('_') and key != 'desc'}


def abort_drivers():
    """The user cancelled the system progress for a phone run: stop every agent that drove the phone."""
    import android_entry
    import hid
    with android_entry._reg_lock:
        sessions = [s for s in android_entry._REG.values() if s.agent is not None]
    run_threads = {getattr(s, 'run_thread', None) for s in sessions}
    # Ordinary code_run uses a worker; inline_eval is checked on its session thread below.
    scripted = any(thread.is_alive() and thread not in run_threads for thread in hid.DRIVERS)
    affected = []
    for session in sessions:
        handler = getattr(session.agent, 'handler', None)
        used_phone = getattr(handler, '_used_phone', False)
        if not (used_phone or getattr(handler, '_in_code_run', False)
                and (scripted or getattr(session, 'run_thread', None) in hid.DRIVERS)):
            continue
        with session.lock:
            if session.agent.is_running or used_phone and android_entry._ios_question_token(session):
                session._ios_cancelled_question_gen = session.state['gen']
                affected.append(session.agent)
    for agent in affected:
        agent.abort()
    return len(affected)


def install(workspace):
    if Path(workspace).resolve() != policy.data_root():
        raise ValueError('iOS workspace mismatch')
    # ga.code_run is routed to kernel_adapter.ios_executor by the signed-host patch.
    # Never install the Android executor: it starts child processes, which iOS forbids.
    import agentmain
    ga.script_dir = str(policy.data_root())
    return agentmain


def release_input():
    import board_bridge
    try:
        # An unanswered turn must still resume from the island. Only this internal release retains its
        # background lease; the public hid.stop and user takeover continue to end the phone run.
        if board_bridge.call('hid', {'action': 'stop', 'end_run': False}, consent=False).get('ok'):
            return
    except Exception:
        pass
    print('[iOS] Board stop was not confirmed')
