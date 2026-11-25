"""Offline tests for the two atomic phone tools (screen, hid), the host policy that composes them,
and the multimodal messages the model actually receives."""
import base64
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import signed_runtime
import board_bridge
import hid
import screen
import ios_policy
import agentmain
from kernel_adapter import ios_host
from kernel_adapter.ios_host import IOSHandler
import llmcore
from agent_loop import exhaust

PNG = base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
IMAGE = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': PNG}}
RECEIPT = dict(ok=True, action_sent=True, sent_at=12.5, revision=3)


def abortable_agent():
    agent = agentmain.GenericAgent()
    agent.is_running = True
    agent.handler = types.SimpleNamespace(code_stop_signal=[])
    return agent


def picture(frame_id='frame-1', **fields):
    reply = dict(ok=True, image_base64=PNG, mime_type='image/png', width=480, height=1040, frame_id=frame_id,
                 same_as_previous=False, elements=['7 发送 @0.871,0.890', '8 [icon] @0.100,0.200'])
    reply.update(fields)
    return reply


class PhoneToolTests(unittest.TestCase):
    """The native session is replaced by a script: `self.screens` and `self.receipts` are its replies in order."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'temp').mkdir()
        self.calls = []
        self.screens = [picture()]
        self.receipts = [dict(RECEIPT)]

        def native(raw):
            request = json.loads(raw)
            self.calls.append(request)
            replies = self.screens if request['tool'] == 'screen' else self.receipts
            reply = dict(replies.pop(0) if len(replies) > 1 else replies[0])
            if request['tool'] == 'screen' and request['args'].get('image') is False:
                for key in ('image_base64', 'mime_type', 'detail_image_base64'):
                    reply.pop(key, None)
            return json.dumps(reply)
        self.contexts = [patch.object(sys, 'platform', 'ios'),
                         patch.dict(os.environ, {'GA_DIR': str(self.root)}),
                         patch.dict(sys.modules, {'_gaboard': types.SimpleNamespace(call=native)}),
                         patch.object(ios_policy, 'require_consent')]
        for context in self.contexts:
            context.start()

    def tearDown(self):
        for context in reversed(self.contexts):
            context.stop()
        self.temp.cleanup()

    def handler(self):
        return IOSHandler(agentmain.GenericAgent(), cwd=str(self.root / 'temp'))

    def deliver(self, handler, turn=1):
        """End the model turn: the held image is delivered and its frame becomes the bound one."""
        response = types.SimpleNamespace(content='<summary>observe</summary>')
        return handler.turn_end_callback(response, [], [], turn, '\n', {})

    def sent(self, tool):
        return [call['args'] for call in self.calls if call['tool'] == tool]

    # The two modules stand alone.

    def test_the_two_tools_do_not_import_each_other(self):
        root = Path(screen.__file__).parent
        self.assertNotIn('hid', (root / 'screen.py').read_text().replace('hidden', ''))
        self.assertNotIn('import screen', (root / 'hid.py').read_text())
        self.assertFalse(hasattr(screen, 'hid') or hasattr(hid, 'screen'))

    def test_non_ios_never_calls_native(self):
        with patch.object(sys, 'platform', 'darwin'):
            for use in (screen.capture, hid.status, lambda: hid.tap(.5, .5)):
                with self.assertRaisesRegex(RuntimeError, 'iOS only'):
                    use()
        self.assertEqual(self.calls, [])

    def test_missing_bridge_returns_explicit_unavailable(self):
        with patch.dict(sys.modules, {'_gaboard': None}):
            self.assertEqual(hid.status()['error'], 'board_unavailable')
            self.assertEqual(screen.capture()['error'], 'board_unavailable')

    def test_consent_is_checked_before_reading_or_sending_but_never_for_stop(self):
        with patch.object(ios_policy, 'require_consent', side_effect=PermissionError('consent')):
            for use in (screen.capture, lambda: hid.tap(.5, .5), lambda: hid.stage_text('x')):
                with self.assertRaises(PermissionError):
                    use()
            self.assertEqual(self.calls, [])
            self.assertTrue(hid.stop()['ok'])
            self.assertTrue(hid.status()['ok'])
            self.assertTrue(board_bridge.takeover('pause', {})['ok'])
        self.assertEqual([c['tool'] for c in self.calls], ['hid', 'hid', 'takeover'])
        self.assertEqual(self.calls[-1]['args'], {'action': 'pause'})

    # screen

    def test_screen_saves_the_picture_privately_and_keeps_pixels_out_of_the_reply(self):
        shot = screen.capture()
        self.assertNotIn(PNG, json.dumps(shot))
        self.assertEqual(shot['frame_id'], 'frame-1')
        path = Path(shot['path'])
        self.assertEqual(path.read_bytes(), base64.b64decode(PNG))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.sent('screen'), [{'image': True, 'marks': False, 'ocr': True}])

    def test_screen_tool_entry_hands_the_image_block_to_the_host(self):
        self.screens = [picture(detail_image_base64=base64.b64encode(b'\xff\xd8\xffdetail').decode())]
        reply = screen.call({'region': {'x': .1, 'y': .2, 'width': .5, 'height': .2}})
        self.assertEqual(reply.pop('_model_image'), IMAGE)
        self.assertEqual(reply.pop('_detail_model_image')['source']['media_type'], 'image/jpeg')
        self.assertNotIn('image_base64', json.dumps(reply))
        self.assertEqual(self.sent('screen'), [{'region': {'x': .1, 'y': .2, 'width': .5, 'height': .2}, 'image': True, 'ocr': True}])

    def test_screen_capture_keeps_the_requested_region_available_to_scripts(self):
        detail = b'\xff\xd8\xffdetail'
        self.screens = [picture(detail_image_base64=base64.b64encode(detail).decode())]
        shot = screen.capture(region={'x': .1, 'y': .2, 'width': .5, 'height': .2})
        path = Path(shot['detail_path'])
        self.assertEqual(path.read_bytes(), detail)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertIn(str(path), shot['detail_markdown'])
        self.assertNotEqual(path, Path(shot['path']))
        self.assertNotIn('image_base64', json.dumps(shot))

    def test_screen_options_are_validated_before_native(self):
        bad = [{'image': 'true'}, {'image': False, 'ocr': False}, {'image': False, 'marks': True},
               {'image': False, 'region': {'x': 0, 'y': 0, 'width': .5, 'height': .5}}, {'marks': 1}, {'ocr': 'no'}, {'marks': True, 'ocr': False}, {'zoom': 2},
               {'region': {'x': 0, 'y': 0, 'width': 0, 'height': .5}},
               {'region': {'x': 0, 'y': 0, 'width': float('nan'), 'height': .5}},
               {'region': {'x': 0, 'y': 0, 'width': .5, 'height': float('inf')}},
               {'region': {'x': .8, 'y': 0, 'width': .5, 'height': .5}}, {'region': {'x': 0, 'y': 0}}]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                screen.call(args)
        self.assertEqual(self.calls, [])

    def test_screen_accepts_a_small_positive_region(self):
        region = {'x': .5, 'y': .5, 'width': .005, 'height': .0025}
        screen.capture(region=region)
        self.assertEqual(self.sent('screen')[0]['region'], region)

    def test_screen_rejects_malformed_or_missing_pixels(self):
        for fields in [dict(image_base64='?', mime_type='image/png'),
                       dict(image_base64=PNG, mime_type='image/jpeg'),
                       dict(image_base64=PNG, mime_type='text/plain'), {}]:
            self.screens = [dict(ok=True, width=480, height=1040, **fields)]
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                screen.capture()

    def test_screen_storage_rejects_symlink_escape(self):
        outside = self.root / 'private'
        outside.mkdir()
        (self.root / 'temp/iphone_screens').symlink_to(outside)
        with self.assertRaises(ValueError):
            screen.capture()
        self.assertEqual(list(outside.iterdir()), [])

    def test_native_screen_errors_pass_through_without_an_image(self):
        self.screens = [dict(ok=False, error='source_stalled', error_code='source_stalled')]
        self.assertEqual(screen.call({}), self.screens[0])

    def test_elements_can_be_located_from_a_script(self):
        shot = screen.capture()
        self.assertEqual(screen.point(shot, 7), (.871, .89))
        self.assertEqual([e['number'] for e in screen.find(shot, '发送')], [7])
        self.assertEqual(screen.elements(shot)[1], {'number': 8, 'label': '[icon]', 'x': .1, 'y': .2})
        with self.assertRaisesRegex(ValueError, 'element number'):
            screen.point(shot, 9)

    # hid

    def test_each_input_reaches_native_with_checked_arguments_and_returns_only_a_receipt(self):
        cases = [
            (lambda: hid.tap(0, 1), {'action': 'tap', 'x': 0, 'y': 1}),
            (lambda: hid.tap(.2, .3, count=2), {'action': 'tap', 'x': .2, 'y': .3, 'count': 2}),
            (lambda: hid.tap(.2, .3, count=3), {'action': 'tap', 'x': .2, 'y': .3, 'count': 3}),
            (lambda: hid.stage_text('长' * 3000), {'action': 'stage_text', 'text': '长' * 3000}),
            (lambda: hid.long_press(.2, .3), {'action': 'long_press', 'x': .2, 'y': .3, 'duration_ms': 800}),
            (lambda: hid.swipe(.5, .7, .5, .3), {'action': 'swipe', 'x': .5, 'y': .7, 'x2': .5, 'y2': .3}),
            (lambda: hid.swipe(.5, .7, .5, .3, duration_ms=900), {'action': 'swipe', 'x': .5, 'y': .7, 'x2': .5, 'y2': .3, 'duration_ms': 900}),
            (lambda: hid.swipe(.5, .7, .5, .3, flick=True, duration_ms=120),
             {'action': 'swipe', 'x': .5, 'y': .7, 'x2': .5, 'y2': .3, 'duration_ms': 120, 'flick': True}),
            (lambda: hid.button('control_center'), {'action': 'button', 'name': 'control_center'}),
            (lambda: hid.type('你好'), {'action': 'type', 'text': '你好', 'method': 'paste'}),
            (lambda: hid.type('👨‍👩‍👧‍👦\u200f'), {'action': 'type', 'text': '👨‍👩‍👧‍👦\u200f', 'method': 'paste'}),
            (lambda: hid.type('abc', method='keys'), {'action': 'type', 'text': 'abc', 'method': 'keys'}),
            (lambda: hid.key('cmd+['), {'action': 'key', 'combo': 'cmd+['}),
            (lambda: hid.key('cmd+a'), {'action': 'key', 'combo': 'cmd+a'}),
            (lambda: hid.button('home'), {'action': 'button', 'name': 'home'}),
            (lambda: hid.tap(.2, .3, frame_id='seen:1'), {'action': 'tap', 'x': .2, 'y': .3, 'frame_id': 'seen:1'}),
            (lambda: hid.swipe(.5, .7, .5, .3, hold_ms=700), {'action': 'swipe', 'x': .5, 'y': .7, 'x2': .5, 'y2': .3, 'hold_ms': 700}),
            (lambda: hid.stage_text('段一\n段二\t末尾'), {'action': 'stage_text', 'text': '段一\n段二\t末尾'}),
            (lambda: hid.stage_text('你好'), {'action': 'stage_text', 'text': '你好'}),
        ]
        for use, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(use(), RECEIPT)
                self.assertEqual(self.calls[-1], {'tool': 'hid', 'args': expected})
        self.assertEqual(self.sent('screen'), [], 'hid never reads the screen')

    def test_valid_input_exceeds_old_budgets(self):
        for args in [dict(action='tap', x=.5, y=.5, count=11),
                     dict(action='long_press', x=.5, y=.5, duration_ms=6000),
                     dict(action='stage_text', text='中文' * 6000),
                     dict(action='type', text='a' * 601, method='keys')]:
            self.assertEqual(hid.call(args), RECEIPT)
            self.assertEqual(self.calls[-1]['args'], args)

    def test_bad_input_never_reaches_native(self):
        bad = [
            {'action': 'tap', 'x': 1.01, 'y': .5}, {'action': 'tap', 'x': True, 'y': .5}, {'action': 'tap', 'x': .5},
            {'action': 'tap', 'x': .5, 'y': .5, 'element': 3}, {'action': 'tap', 'x': .5, 'y': .5, 'frame_id': 'bad id'},
            {'action': 'tap', 'x': .5, 'y': .5, 'count': True},
            {'action': 'tap', 'x': .5, 'y': .5, 'count': 0}, {'action': 'tap', 'x': .5, 'y': .5, 'count': 2.5},
            {'action': 'long_press', 'x': .5, 'y': .5, 'count': 2},
            {'action': 'swipe', 'x': .5, 'y': .5, 'x2': .5, 'y2': .5, 'duration_ms': 20},
            {'action': 'long_press', 'x': .5, 'y': .5, 'duration_ms': 50},
            {'action': 'swipe', 'x': .5, 'y': .5, 'x2': .5, 'y2': .2, 'flick': 1}, {'action': 'tap', 'x': .5, 'y': .5, 'flick': True},
            {'action': 'type', 'text': ''}, {'action': 'type', 'text': 'a\x00b'},
            {'action': 'type', 'text': '中文', 'method': 'keys'}, {'action': 'type', 'text': 'a', 'method': 'voice'},
            {'action': 'key', 'combo': 'cmd v'}, {'action': 'button', 'name': 'power'},
            {'action': 'status', 'x': 1},
            {'action': 'open_app', 'name': 'WeChat'}, {'action': 'iphone_tap'}, {},
        ]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                hid.call(args)
        self.assertEqual(self.calls, [])

    def test_native_refusals_are_returned_as_they_are(self):
        self.receipts = [dict(ok=False, error='frame_changed', action_sent=False, safe_to_retry=True)]
        self.assertEqual(hid.tap(.2, .3, frame_id='old'), self.receipts[0])
        self.assertEqual(len(self.calls), 1, 'no retry')

    # The host policy composes the two tools.

    def test_schema_lists_flat_tools_with_their_own_arguments(self):
        names = [t['function']['name'] for t in ios_policy.tool_schema([])]
        self.assertEqual(names, ['screen', 'hid', 'pc_link'])
        tools = {t['function']['name']: t['function'] for t in ios_policy.tool_schema([])}
        self.assertEqual(tools['hid']['parameters']['properties']['action']['enum'], list(hid.ACTIONS))
        self.assertEqual(set(tools['screen']['parameters']['properties']), {'image', 'marks', 'ocr', 'region'})
        self.assertEqual(ios_policy.DEVICE_TOOLS, set(names))

    def test_retired_tool_names_are_refused_by_the_host(self):
        handler = self.handler()
        for name in ('device_tool', 'iphone_tap', 'web_read'):
            outcome = exhaust(handler.dispatch(name, {}, None))
            self.assertEqual(outcome.data['msg'], ios_policy.UNSUPPORTED_TOOL)
        self.assertEqual(self.calls, [])

    def test_default_text_observation_binds_coordinates_without_images_or_files(self):
        handler = self.handler()  # no model metadata is configured
        result = handler.do_screen({}, None).data
        self.assertTrue(result['ok'])
        self.assertEqual(self.sent('screen'), [{'image': False, 'ocr': True}])
        self.assertNotIn('path', result)
        self.assertIsInstance(self.deliver(handler), str)
        self.assertFalse((self.root / 'temp/iphone_screens').exists())
        handler.do_hid({'action': 'tap', 'element': 7}, None)
        self.assertEqual(self.sent('hid')[-1]['frame_id'], 'frame-1')
        self.assertEqual(self.sent('hid')[-1]['x'], .871)
        self.assertEqual(self.sent('screen')[-1], {'image': False, 'ocr': True})

    def test_post_input_read_preserves_the_chosen_outputs_but_not_crop_or_marks(self):
        for options, expected in [
            ({'ocr': False}, {'image': True, 'ocr': False}),
            ({'image': True}, {'image': True, 'ocr': True}),
            ({'marks': True, 'region': {'x': 0, 'y': 0, 'width': .5, 'height': .5}},
             {'image': True, 'ocr': True}),
        ]:
            with self.subTest(options=options):
                handler = self.handler()
                self.assertTrue(handler.do_screen(options, None).data['ok'])
                self.deliver(handler)
                self.assertTrue(handler.do_hid({'action': 'key', 'combo': 'enter'}, None).data['ok'])
                self.assertEqual(self.sent('screen')[-1], expected)
                self.assertEqual(self.deliver(handler, turn=2)[-1], IMAGE)

    def test_switching_to_text_clears_pending_images_and_failed_read_keeps_choice(self):
        handler = self.handler()
        handler.do_screen({'image': True}, None)
        handler.do_screen({'image': False}, None)
        self.assertIsInstance(self.deliver(handler), str)
        self.screens = [dict(ok=False, error='source_stalled')]
        self.assertFalse(handler.do_screen({'image': True, 'ocr': False}, None).data['ok'])
        self.screens = [picture('frame-2')]
        handler.do_hid({'action': 'key', 'combo': 'enter'}, None)
        self.assertEqual(self.sent('screen')[-1], {'image': False, 'ocr': True})
        self.assertIsInstance(self.deliver(handler, turn=2), str)
        self.assertEqual(handler._phone_frame, 'frame-2')

    def test_screen_image_reaches_the_model_once_and_binds_its_frame(self):
        handler = self.handler()
        outcome = handler.do_screen({'image': True, '_index': 0, '_tool_num': 1, 'desc': '看当前画面'}, None)
        self.assertNotIn(PNG, json.dumps(outcome.data))
        self.assertEqual(outcome.data['frame_id'], 'frame-1')
        self.assertEqual(self.sent('screen'), [{'image': True, 'ocr': True}], 'bookkeeping never reaches the tool')
        self.assertFalse(getattr(handler, '_phone_frame', None), 'a picture not yet delivered binds nothing')
        self.assertEqual(self.deliver(handler)[-1], IMAGE)
        self.assertEqual(handler._phone_frame, 'frame-1')
        self.assertNotIn(PNG, json.dumps(self.deliver(handler, turn=2)))

    def test_input_is_bound_to_the_delivered_frame_and_followed_by_one_screen(self):
        handler = self.handler()
        handler.do_screen({'image': True}, None)
        self.deliver(handler)
        self.screens = [picture('frame-2', same_as_previous=True)]
        outcome = handler.do_hid({'action': 'tap', 'x': .2, 'y': .3}, None)
        self.assertEqual(self.sent('hid'), [{'action': 'tap', 'x': .2, 'y': .3, 'frame_id': 'frame-1'}])
        self.assertEqual([c['tool'] for c in self.calls], ['screen', 'hid', 'screen'])
        self.assertTrue(outcome.data['ok'] and outcome.data['action_sent'])
        self.assertEqual(outcome.data['frame_id'], 'frame-2')
        self.assertIs(outcome.data['same_as_previous'], True)
        self.assertEqual(outcome.data['revision'], 3)
        self.assertNotIn(PNG, json.dumps(outcome.data))
        self.assertEqual(self.deliver(handler, turn=2)[-1], IMAGE)
        self.assertEqual(handler._phone_frame, 'frame-2')

    def test_a_back_that_left_the_page_unchanged_is_sent_once(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.screens = [picture('frame-2', same_as_previous=True), picture('frame-3', same_as_previous=True)]
        outcome = handler.do_hid({'action': 'button', 'name': 'back'}, None)
        self.assertEqual(self.sent('hid'), [{'action': 'button', 'name': 'back'}], 'one call sends one input')
        self.assertEqual([c['tool'] for c in self.calls], ['screen', 'hid', 'screen'], 'once only')
        self.assertNotIn('retried', outcome.data)
        self.assertEqual(outcome.data['frame_id'], 'frame-2')
        self.assertIs(outcome.data['same_as_previous'], True, 'the model still sees that nothing changed')

    def test_a_back_that_changed_the_page_or_any_other_input_is_never_repeated(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.screens = [picture('frame-2')]
        self.assertNotIn('retried', handler.do_hid({'action': 'button', 'name': 'back'}, None).data)
        self.deliver(handler, turn=2)
        self.screens = [picture('frame-3', same_as_previous=True)]
        for args in ({'action': 'tap', 'x': .5, 'y': .5}, {'action': 'button', 'name': 'home'},
                     {'action': 'swipe', 'x': .5, 'y': .7, 'x2': .5, 'y2': .3}):
            self.assertNotIn('retried', handler.do_hid(args, None).data)
        self.assertEqual(len(self.sent('hid')), 4)
        unseen = self.handler()  # a conversation that never read the screen cannot tell, so sends once
        unseen.do_hid({'action': 'button', 'name': 'back'}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'button', 'name': 'back'})
        self.assertEqual(len(self.sent('hid')), 5)

    def test_element_number_becomes_the_coordinates_of_that_frame(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.screens = [picture('frame-2', elements=['7 取消 @0.300,0.400'])]
        handler.do_hid({'action': 'tap', 'element': '7'}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'tap', 'x': .871, 'y': .89, 'frame_id': 'frame-1'})
        self.deliver(handler, turn=2)
        handler.do_hid({'action': 'tap', 'element': 7, 'count': 2}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'tap', 'x': .3, 'y': .4, 'count': 2, 'frame_id': 'frame-2'})
        self.deliver(handler, turn=3)
        handler.do_hid({'action': 'long_press', 'element': 7}, None)
        self.assertEqual(self.sent('hid')[-1],
                         {'action': 'long_press', 'x': .3, 'y': .4, 'duration_ms': 800, 'frame_id': 'frame-2'})

    def test_unknown_or_ambiguous_elements_send_nothing(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        for args in ({'element': 9}, {'element': '09'}, {'element': '发送'}, {'element': True},
                     {'element': 7, 'x': .5, 'y': .5}, {'element': 7, 'frame_id': 'another-frame'}):
            with self.subTest(args=args):
                outcome = handler.do_hid({'action': 'tap', **args}, None)
                self.assertEqual(outcome.data['status'], 'error')
        self.assertEqual(self.sent('hid'), [])

    def test_element_type_errors_do_not_match_integer_ids_or_discard_the_frame(self):
        handler = self.handler()
        self.screens = [picture(elements=['1 First @0.100,0.200', '7 Send @0.800,0.900'])]
        handler.do_screen({}, None)
        self.deliver(handler)
        for number in (True, 7.0, [], {}):
            with self.subTest(number=number):
                self.assertEqual(handler.do_hid({'action': 'tap', 'element': number}, None).data['status'], 'error')
                self.assertEqual(handler._phone_frame, 'frame-1')
        self.assertEqual(self.sent('hid'), [])

    def test_visual_only_read_keeps_numbers_only_for_the_same_exact_frame(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.screens = [picture(elements=[], element_sources={'ocr': 'skipped', 'detector': 'skipped'})]
        handler.do_screen({'ocr': False}, None)
        self.deliver(handler, turn=2)
        self.assertTrue(handler.do_hid({'action': 'tap', 'element': 7}, None).data['ok'])
        self.assertEqual(self.sent('hid')[-1]['x'], .871)
        self.screens = [picture('new-frame', elements=[], element_sources={'ocr': 'skipped'})]
        handler.do_screen({'ocr': False}, None)
        self.deliver(handler, turn=3)
        self.assertEqual(handler.do_hid({'action': 'tap', 'element': 7}, None).data['status'], 'error')
        self.assertEqual(len(self.sent('hid')), 1)

    def test_composed_input_keeps_input_and_screen_timings_without_inverse_change_flag(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.receipts = [{**RECEIPT, 'timing_ms': {'preflight': 20, 'input': 30}}]
        self.screens = [picture('frame-2', timing_ms={'capture': 1, 'recognition': 2})]
        result = handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None).data
        self.assertEqual(result['timing_ms'], {'preflight': 20, 'input': 30, 'capture': 1, 'recognition': 2})
        self.assertNotIn('changed', result)
        self.assertIn('same_as_previous', result)

    def test_a_conversation_that_never_read_the_screen_sends_input_by_coordinates_alone(self):
        handler = self.handler()
        outcome = handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None)
        self.assertEqual(outcome.data, RECEIPT)
        self.assertEqual(self.sent('hid'), [{'action': 'tap', 'x': .5, 'y': .5}], 'no frame is invented')
        handler.invalidate_phone_observation()  # after an interruption it has nothing to look at again
        self.assertTrue(handler.do_hid({'action': 'key', 'combo': 'enter'}, None).data['ok'])
        self.assertEqual([c['tool'] for c in self.calls], ['hid', 'hid'], 'hid alone never reads the screen')

    def test_once_it_has_read_the_screen_input_without_a_delivered_frame_is_refused_except_buttons(self):
        handler = self.handler()
        handler.do_screen({}, None)  # held, not delivered yet
        for args in ({'action': 'key', 'combo': 'enter'}, {'action': 'tap', 'x': .5, 'y': .5}):
            self.assertEqual(handler.do_hid(args, None).data, IOSHandler.UNOBSERVED)
        self.assertEqual(self.sent('hid'), [])
        self.assertEqual(self.sent('screen'), [{'image': False, 'ocr': True}], 'the observation already on its way is not read again')
        for name in hid.BUTTONS:
            self.assertTrue(handler.do_hid({'action': 'button', 'name': name}, None).data['ok'])
            self.assertEqual(self.sent('hid')[-1], {'action': 'button', 'name': name}, 'and no frame is attached')
        self.deliver(handler)
        handler.do_hid({'action': 'button', 'name': 'back'}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'button', 'name': 'back'}, 'nor once a frame was delivered')
        other = self.handler()
        other.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'tap', 'x': .5, 'y': .5},
                         'conversations cannot borrow an observation')

    def test_resumed_model_can_navigate_without_old_coordinates_but_cannot_bypass_pause(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        handler.invalidate_phone_observation()
        self.calls.clear()
        handler._phone_pause_token = 'user-owns-phone'
        self.assertFalse(handler.do_hid({'action': 'button', 'name': 'home'}, None).data['ok'])
        self.assertEqual(self.calls, [], 'pause blocks even navigation')
        handler._phone_pause_token = None  # explicit resume returned control
        self.assertTrue(handler.do_hid({'action': 'button', 'name': 'home'}, None).data['ok'])
        self.assertEqual([c['tool'] for c in self.calls], ['hid', 'screen'], 'navigate, then show its result')
        self.assertNotIn('frame_id', self.sent('hid')[0])
        self.assertFalse(handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None).data['ok'],
                         'a coordinate action still waits for the image to reach the model')
        self.deliver(handler, turn=2)
        self.assertTrue(handler.do_hid({'action': 'tap', 'element': 7}, None).data['ok'])

    def test_an_explicit_frame_id_is_kept(self):
        handler = self.handler()
        handler._phone_frame = 'owned'
        handler.do_hid({'action': 'key', 'combo': 'enter', 'frame_id': 'explicit'}, None)
        self.assertEqual(self.sent('hid'), [{'action': 'key', 'combo': 'enter', 'frame_id': 'explicit'}])

    def test_a_touch_refused_for_a_changed_target_comes_with_the_current_screen(self):
        handler = self.handler()
        handler.do_screen({'image': True}, None)
        self.deliver(handler)
        self.receipts = [dict(ok=False, error='changed', error_code='frame_changed', action_sent=False), dict(RECEIPT)]
        self.screens = [picture('frame-2', elements=['7 发送 @0.500,0.600'])]
        outcome = handler.do_hid({'action': 'tap', 'element': 7}, None)
        self.assertEqual([c['tool'] for c in self.calls], ['screen', 'hid', 'screen'], 'the refusal shows what is there now')
        self.assertEqual({key: outcome.data[key] for key in ('ok', 'error_code', 'action_sent', 'frame_id')},
                         dict(ok=False, error_code='frame_changed', action_sent=False, frame_id='frame-2'))
        self.assertNotIn(PNG, json.dumps(outcome.data))
        self.assertEqual(self.deliver(handler, turn=2)[-1], IMAGE)
        handler.do_hid({'action': 'tap', 'element': 7}, None)
        self.assertEqual(self.sent('hid')[-1], {'action': 'tap', 'x': .5, 'y': .6, 'frame_id': 'frame-2'},
                         'the target is found again without a separate screen call')

    def test_a_refusal_stands_alone_when_the_screen_cannot_be_read(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.receipts = [dict(ok=False, error='changed', error_code='frame_changed', action_sent=False)]
        self.screens = [dict(ok=False, error='source_stalled')]
        self.assertEqual(handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None).data, self.receipts[0])
        self.assertEqual(self.deliver(handler, turn=2).__class__, str, 'no stale image is delivered')

    def test_an_input_that_was_never_sent_keeps_the_observation(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.calls.clear()
        for args in ({'action': 'tap', 'element': 99}, {'action': 'tap', 'x': 2, 'y': .5},
                     {'action': 'tap', 'element': 7, 'count': 0}, {'action': 'swipe', 'x': .5, 'y': .5}):
            with self.subTest(args=args):
                self.assertEqual(handler.do_hid(args, None).data['status'], 'error')
        self.assertEqual(self.calls, [], 'a mistake in the arguments reaches nothing')
        self.receipts = [dict(ok=False, error='Board is busy', action_sent=False), dict(RECEIPT)]
        self.assertFalse(handler.do_hid({'action': 'tap', 'element': 7}, None).data['ok'])
        self.assertEqual(handler._phone_frame, 'frame-1', 'what the model saw is still what is there')
        self.assertTrue(handler.do_hid({'action': 'tap', 'element': 7}, None).data['ok'])
        self.assertEqual(self.sent('hid')[-1], {'action': 'tap', 'x': .871, 'y': .89, 'frame_id': 'frame-1'})

    def test_an_input_that_may_have_reached_the_phone_voids_the_observation(self):
        unknown = [dict(ok=False, error='link lost', action_sent=True, safe_to_retry=False),
                   dict(ok=False, error='Board request timed out'), 'not a reply']
        for reply in unknown:
            with self.subTest(reply=reply):
                handler = self.handler()
                handler.do_screen({}, None)
                self.deliver(handler)
                self.receipts = [reply]
                handler.do_hid({'action': 'tap', 'element': 7}, None)
                self.assertIsNone(handler._phone_frame)
                sent = len(self.sent('hid'))
                self.screens = [picture('frame-2')]
                refused = handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None)
                self.assertEqual(len(self.sent('hid')), sent, 'nothing goes by a picture that no longer stands')
                self.assertEqual((refused.data['ok'], refused.data['action_sent'], refused.data['frame_id']),
                                 (False, False, 'frame-2'), 'and the model is shown the screen as it is now')
                self.screens = [picture()]

    def test_delivered_input_whose_result_cannot_be_read_is_not_safe_to_retry(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.screens = [dict(ok=False, error='source_stalled')]
        outcome = handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None)
        self.assertFalse(outcome.data['ok'])
        self.assertTrue(outcome.data['action_sent'])
        self.assertFalse(outcome.data['safe_to_retry'])
        self.assertEqual(outcome.data['observation_error'], 'source_stalled')
        self.assertIsNone(handler._phone_frame)
        self.assertEqual(self.deliver(handler, turn=2).__class__, str, 'no stale image is delivered')

    def test_status_stop_and_staging_need_no_observation_and_attach_no_screen(self):
        handler = self.handler()
        for args in ({'action': 'status'}, {'action': 'stage_text', 'text': '你好'}, {'action': 'stop'}):
            # Every call may carry the caption the shared UI plugin adds to each schema.
            self.assertTrue(handler.do_hid(dict(args, desc='检查状态', _index=0), None).data['ok'])
        self.assertEqual(self.sent('screen'), [])
        self.assertEqual(self.sent('hid'), [{'action': 'status'}, {'action': 'stage_text', 'text': '你好'}, {'action': 'stop'}])

    def test_stop_discards_the_bound_frame(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        handler.do_hid({'action': 'stop'}, None)
        self.assertIsNone(handler._phone_frame)

    def test_takeover_blocks_both_tools_then_coordinates_need_a_delivered_image(self):
        handler = self.handler()
        handler.do_screen({}, None)
        self.deliver(handler)
        self.calls.clear()
        handler._phone_pause_token = 'handoff'
        self.assertFalse(handler.do_hid({'action': 'button', 'name': 'home'}, None).data['ok'])
        self.assertFalse(handler.do_screen({}, None).data['ok'])
        self.assertEqual(self.calls, [])
        self.assertTrue(handler.do_hid({'action': 'stop'}, None).data['ok'], 'stop always works')
        handler._phone_pause_token = None
        handler.invalidate_phone_observation()
        refused = handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None)
        self.assertEqual((refused.data['ok'], refused.data['frame_id']), (False, 'frame-1'), 'refused, with the screen')
        self.assertEqual(self.sent('hid'), [{'action': 'stop'}])
        handler.do_screen({}, None)
        self.assertFalse(handler.do_hid({'action': 'tap', 'x': .5, 'y': .5}, None).data['ok'])
        self.deliver(handler)
        handler.do_hid({'action': 'tap', 'element': 7}, None)
        self.assertEqual(self.sent('hid')[-1]['frame_id'], 'frame-1')

    def test_pc_tools_are_flat_and_need_consent(self):
        handler = self.handler()
        pclink = types.SimpleNamespace(ios_request=lambda method, path, body: {'method': method, 'path': path})
        with patch.dict(sys.modules, {'pclink': pclink}):
            self.assertEqual(handler.do_pc_link({'path': '/api/peers', '_index': 0}, None).data,
                             {'method': 'GET', 'path': '/api/peers'})
            with patch.object(ios_policy, 'require_consent', side_effect=PermissionError('consent')):
                self.assertEqual(handler.do_pc_link({'path': '/api/peers'}, None).data['status'], 'error')

    # Stopping

    def test_chat_abort_releases_board_while_an_action_is_waiting(self):
        started, stopped = threading.Event(), threading.Event()
        def native(raw):
            if json.loads(raw)['args'].get('action') == 'stop':
                stopped.set()
                return '{"ok":true,"stopped":true}'
            started.set()
            return json.dumps({'ok': not stopped.wait(2), 'error': 'cancelled'})
        agent = abortable_agent()
        results = []
        with patch.dict(sys.modules, {'_gaboard': types.SimpleNamespace(call=native)}):
            worker = threading.Thread(target=lambda: results.append(hid.button('home')))
            worker.start()
            self.assertTrue(started.wait(1))
            begin = time.monotonic()
            agent.abort()
            worker.join(.5)
        self.assertLess(time.monotonic() - begin, .5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(agent.stop_sig)
        self.assertEqual(agent.handler.code_stop_signal, [1])
        self.assertFalse(results[0]['ok'])

    def test_android_abort_does_not_call_board(self):
        agent = abortable_agent()
        with patch.object(sys, 'platform', 'linux'), patch.object(hid, 'stop') as stop:
            agent.abort()
        stop.assert_not_called()
        self.assertTrue(agent.stop_sig)

    def sessions(self, **threads):
        def session(thread, running=True, in_code_run=False):
            agent = types.SimpleNamespace(is_running=running, aborted=False,
                                          handler=types.SimpleNamespace(_in_code_run=in_code_run))
            agent.abort = lambda: setattr(agent, 'aborted', True)
            return types.SimpleNamespace(agent=agent, run_thread=thread, lock=threading.RLock(), state={'gen': 1})
        return {name: session(*spec) for name, spec in threads.items()}

    def test_system_cancel_aborts_only_running_current_phone_handlers(self):
        hid.DRIVERS.clear()
        driver = threading.Thread(target=lambda: hid.button('home'))
        driver.start(); driver.join()
        other = threading.Thread(target=lambda: None)
        sessions = self.sessions(a=(driver,), b=(other,), c=(driver, False))
        sessions['a'].agent.handler = self.handler()
        sessions['a'].agent.handler.do_hid({'action': 'button', 'name': 'home'}, None)
        registry = types.SimpleNamespace(_reg_lock=threading.Lock(), _REG=sessions, _ios_question_token=lambda _: None)
        with patch.dict(sys.modules, {'android_entry': registry}):
            self.assertEqual(ios_host.abort_drivers(), 1)
        self.assertEqual([k for k, s in sessions.items() if s.agent.aborted], ['a'])

    def test_system_cancel_also_aborts_the_agent_whose_script_drives_the_phone(self):
        hid.DRIVERS.clear()
        release = threading.Event()
        script = threading.Thread(target=lambda: (hid.tap(.5, .5), release.wait(2)), name='code_run')
        script.start()
        try:
            while not self.calls:
                time.sleep(.01)
            idle, busy = threading.Thread(target=lambda: None), threading.Thread(target=lambda: None)
            sessions = self.sessions(scripting=(busy, True, True), thinking=(idle, True, False))
            registry = types.SimpleNamespace(_reg_lock=threading.Lock(), _REG=sessions, _ios_question_token=lambda _: None)
            with patch.dict(sys.modules, {'android_entry': registry}):
                self.assertEqual(ios_host.abort_drivers(), 1)
            self.assertEqual([k for k, s in sessions.items() if s.agent.aborted], ['scripting'])
        finally:
            release.set()
            script.join()

    def test_system_cancel_covers_screen_only_work_and_revokes_waiting_question(self):
        import android_entry as entry
        hid.DRIVERS.clear()
        for running in (False, True):
            with self.subTest(running=running):
                phone, chat = entry._Sess('phone'), entry._Sess('chat')
                for session in (phone, chat):
                    session.agent = types.SimpleNamespace(is_running=running, aborted=False,
                        handler=types.SimpleNamespace(_used_phone=session is phone))
                    session.agent.abort = lambda s=session: setattr(s.agent, 'aborted', True)
                    session.state.update(gen=19, running=running,
                        steps=[{'text': 'Tool: ask_user args: {"question":"Choose","candidates":["Green"]}'}])
                with patch.object(entry, '_REG', {'phone': phone, 'chat': chat}):
                    self.assertEqual(ios_host.abort_drivers(), 1)
                    self.assertIsNone(entry._ios_question_token(phone))
                self.assertTrue(phone.agent.aborted)
                self.assertFalse(chat.agent.aborted)
                self.assertEqual(phone._ios_cancelled_question_gen, 19)

    def test_system_cancel_does_not_stop_text_work_after_an_earlier_phone_turn(self):
        import android_entry as entry
        hid.DRIVERS.clear()
        session = entry._Sess('previous-phone-user')
        session.run_thread = threading.current_thread()
        hid.DRIVERS.add(session.run_thread)
        session.agent = types.SimpleNamespace(is_running=False, aborted=False,
            handler=types.SimpleNamespace(_used_phone=False))
        session.agent.abort = lambda: setattr(session.agent, 'aborted', True)
        session.state.update(gen=20, running=False,
            steps=[{'text': 'Tool: ask_user args: {"question":"Choose","candidates":["Green"]}'}])
        with patch.object(entry, '_REG', {session.cid: session}):
            before = entry._ios_question_token(session)
            self.assertIsNotNone(before)
            self.assertEqual(ios_host.abort_drivers(), 0)
            self.assertEqual(entry._ios_question_token(session), before)
            session.agent.is_running = session.state['running'] = True
            self.assertEqual(ios_host.abort_drivers(), 0)
        self.assertFalse(session.agent.aborted)

    def inline_session(self):
        import android_entry as entry
        session = entry._Sess('inline')
        session.agent = agentmain.GenericAgent()
        session.agent.llmclient = types.SimpleNamespace(backend=types.SimpleNamespace(history=[]))
        session.agent.is_running = True
        session.state.update(gen=31, running=True, prompt='inline work')
        handler = IOSHandler(session.agent, cwd=str(self.root / 'temp'))
        session.agent.handler = handler
        session.run_thread = threading.current_thread()
        return session, handler

    def test_inline_hid_can_be_stopped_while_the_native_call_waits(self):
        import android_entry as entry
        hid.DRIVERS.clear()
        session, handler = self.inline_session()
        started, released = threading.Event(), threading.Event()
        def native(raw):
            if json.loads(raw)['args'].get('action') == 'stop':
                released.set()
                return '{"ok":true}'
            started.set()
            return json.dumps({'ok': not released.wait(2), 'action_sent': True})
        results = []
        session.run_thread = threading.Thread(target=lambda: results.append(exhaust(handler.do_code_run(
            {'script': "__import__('hid').tap(.5, .5)", 'inline_eval': True}, None))))
        with patch.object(entry, '_REG', {session.cid: session}), \
             patch.dict(sys.modules, {'_gaboard': types.SimpleNamespace(call=native)}):
            session.run_thread.start()
            try:
                self.assertTrue(started.wait(1))
                self.assertEqual(ios_host.abort_drivers(), 1)
                self.assertTrue(released.is_set())
            finally:
                released.set()
                session.run_thread.join(2)
        self.assertFalse(session.run_thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertTrue(session.agent.stop_sig)

    def test_finished_inline_hid_keeps_this_turn_stoppable_but_not_the_next_text_turn(self):
        import android_entry as entry
        hid.DRIVERS.clear()
        session, handler = self.inline_session()
        with patch.object(entry, '_REG', {session.cid: session}):
            exhaust(handler.do_code_run({'script': "__import__('hid').tap(.5, .5)", 'inline_eval': True}, None))
            self.assertEqual(ios_host.abort_drivers(), 1, 'the model can still be thinking after inline HID returns')
            session.agent.stop_sig = False
            session.agent.handler = IOSHandler(session.agent, cwd=str(self.root / 'temp'))
            session.state['gen'] += 1
            self.assertEqual(ios_host.abort_drivers(), 0, 'a new handler owns a new text-only turn')
            self.assertFalse(session.agent.stop_sig)

    def test_pure_inline_code_does_not_inherit_an_old_hid_thread_mark(self):
        import android_entry as entry
        hid.DRIVERS.clear()
        session, handler = self.inline_session()
        hid.DRIVERS.add(session.run_thread)
        script = "(__import__('kernel_adapter.ios_host', fromlist=['abort_drivers']).abort_drivers(), 1 + 1)"
        with patch.object(entry, '_REG', {session.cid: session}):
            outcome = exhaust(handler.do_code_run({'script': script, 'inline_eval': True}, None))
            self.assertEqual(outcome.data, '(0, 2)')
            self.assertEqual(ios_host.abort_drivers(), 0)
        self.assertFalse(session.agent.stop_sig)


class ModelImageTests(unittest.TestCase):
    def backend(self, native=False):
        class Backend:
            name = model = 'fixture'
            system = ''
            history = []
            def ask(self, value):
                self.received = value
                if not native:
                    yield 'done'
                return llmcore.MockResponse('', 'done', [], 'done') if native else None
        return Backend()

    def test_native_client_preserves_pixels_and_tool_result_order(self):
        backend = self.backend(native=True)
        client = llmcore.NativeToolClient(backend)
        with patch.object(llmcore, '_write_llm_log') as log:
            exhaust(client.chat([{'role': 'user', 'content': [{'type': 'text', 'text': '  '}, IMAGE],
                                  'tool_results': [{'tool_use_id': 'shot-1', 'content': '{"ok":true}'}]}]))
        self.assertNotIn(PNG, log.call_args_list[0].args[1])
        blocks = backend.received['content']
        self.assertEqual(blocks[0]['type'], 'tool_result')
        self.assertEqual(blocks[1], IMAGE)

    def test_protocol_client_sends_pixels_instead_of_stringifying_them(self):
        backend = self.backend()
        client = llmcore.ToolClient(backend)
        exhaust(client.chat([{'role': 'user', 'content': [{'type': 'text', 'text': 'inspect'}, IMAGE]}]))
        self.assertEqual(backend.received[-1], IMAGE)
        self.assertIn('inspect', backend.received[0]['text'])
        self.assertNotIn(PNG, backend.received[0]['text'])

    def test_text_only_protocol_and_native_paths_remain_text(self):
        backend = self.backend()
        exhaust(llmcore.ToolClient(backend).chat([{'role': 'user', 'content': 'plain'}]))
        self.assertIsInstance(backend.received, str)
        self.assertIn('plain', backend.received)
        backend = self.backend(native=True)
        exhaust(llmcore.NativeToolClient(backend).chat([{'role': 'user', 'content': 'plain'}]))
        self.assertEqual(backend.received['content'], [{'type': 'text', 'text': 'plain'}])

    def test_openai_and_responses_conversions_carry_same_pixels(self):
        converted = llmcore._msgs_claude2oai([{'role': 'user', 'content': [IMAGE]}])
        self.assertEqual(converted[0]['content'][0]['image_url']['url'], 'data:image/png;base64,' + PNG)
        responses = llmcore._to_responses_input(converted)
        self.assertEqual(responses[0]['content'][0]['type'], 'input_image')
        self.assertTrue(responses[0]['content'][0]['image_url'].endswith(PNG))

    def test_anthropic_adapter_preserves_canonical_image(self):
        session = llmcore.ClaudeSession({'name': 'fixture', 'apikey': 'test-only', 'model': 'fixture',
                                       'apibase': 'https://example.com'})
        prepared = session.make_messages([{'role': 'user', 'content': [IMAGE]}])
        self.assertEqual(prepared[0]['content'][0]['source'], IMAGE['source'])

    def test_base_session_passes_multimodal_content_through_real_adapter(self):
        session = llmcore.LLMSession({'name': 'fixture', 'apikey': 'test-only', 'model': 'fixture',
                                     'apibase': 'https://example.com'})
        captured = []
        def ask(messages):
            captured.extend(messages)
            yield 'done'
        with patch.object(session, 'raw_ask', side_effect=ask):
            exhaust(session.ask([{'type': 'text', 'text': 'inspect'}, IMAGE]))
        self.assertTrue(captured[0]['content'][1]['image_url']['url'].endswith(PNG))


if __name__ == '__main__':
    unittest.main()
