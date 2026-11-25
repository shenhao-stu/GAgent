"""Exercise the staged core at the iOS image/text context boundary.

Frame binding, element numbers and takeover gating live in test_phone_tools.py."""
import copy
import types
from unittest.mock import patch

import pytest
import signed_runtime
import llmcore
import agentmain
from kernel_adapter.ios_host import IOSHandler


def test_screenshots_do_not_evict_a_short_user_task():
    task = '查看微信炉石传说小程序的热门卡组'
    history = [{'role': 'user', 'content': [{'type': 'text', 'text': task}]}]
    for i in range(7):
        history.append({'role': 'assistant', 'content': [{'type': 'text', 'text': f'observe {i}'}]})
        content = [{'type': 'text', 'text': f'result {i}'}]
        if i in (2, 5):
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': 'A' * 250_000}})
        history.append({'role': 'user', 'content': content})
    original = copy.deepcopy(history)
    session = types.SimpleNamespace(context_win=38_000, trim_keep_prefix=0, trim_keep_rate=0.6, cut_msg_interval=10000)
    llmcore.trim_messages_history(history, session)
    assert history == original, 'Image transport bytes must not consume the text context budget'


def test_phone_steps_retain_the_working_task():
    handler = IOSHandler(types.SimpleNamespace(verbose=False), last_history=['[USER]: 查询炉石热门卡组'])
    handler.current_turn = 3
    handler.working['key_info'] = '目标：微信小程序热门卡组；只读，不发送消息'
    with patch('hid.call', return_value={'ok': True}):
        result = handler.do_hid({'action': 'status'}, None)
    assert '查询炉石热门卡组' in result.next_prompt
    assert '只读，不发送消息' in result.next_prompt


def test_image_budget_is_independent_of_encoding_size_and_keeps_text_cost():
    from kernel_adapter.ios_transport import context_cost
    def image(n):
        return {'role': 'user', 'content': [{'type': 'image', 'source': {'type': 'base64', 'data': 'A' * n}}]}
    small, large = image(20), image(1_000_000)
    saved = copy.deepcopy(large)
    assert context_cost(small) == context_cost(large)
    assert context_cost(large) >= 12_000
    assert large == saved
    assert context_cost({'role': 'user', 'content': 'A' * 250_000}) > 250_000


def test_large_text_still_trims_with_the_same_core_policy():
    history = [{'role': 'user' if i % 2 == 0 else 'assistant', 'content': 'A' * 20_000} for i in range(20)]
    session = types.SimpleNamespace(context_win=38_000, trim_keep_prefix=0, trim_keep_rate=0.6, cut_msg_interval=10000)
    llmcore.trim_messages_history(history, session)
    assert len(history) < 20
    assert history[0]['role'] == 'user'


@pytest.mark.parametrize('kind', ['image', 'image_url', 'input_image'])
def test_nested_image_blocks_do_not_charge_transport_bytes(kind):
    from kernel_adapter.ios_transport import context_cost
    def message(size):
        encoded = 'data:image/jpeg;base64,' + 'A' * size
        block = {'type': kind, 'source': {'type': 'base64', 'data': encoded}} if kind == 'image' else {
            'type': kind, 'image_url': {'url': encoded} if kind == 'image_url' else encoded}
        return {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'shot',
                                           'content': [{'type': 'text', 'text': 'fresh screenshot'}, block]}]}
    assert context_cost(message(20)) == context_cost(message(1_000_000))


def test_trimmed_history_keeps_image_bytes_in_responses_payload():
    encoded = 'A' * 250_000
    image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': encoded}}
    session = llmcore.LLMSession({'name': 'fixture', 'apikey': 'test-only', 'model': 'fixture',
                                 'apibase': 'https://example.com', 'api_mode': 'responses'})
    session.history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'original task'}]}]
    captured = []
    def ask(messages):
        captured.extend(llmcore._to_responses_input(messages))
        yield 'done'
    with patch.object(session, 'raw_ask', side_effect=ask):
        list(session.ask([{'type': 'text', 'text': 'inspect'}, image]))
    blocks = [block for message in captured for block in message['content']]
    assert any(block.get('text') == 'original task' for block in blocks)
    assert any(block.get('type') == 'input_image' and
               block['image_url'] == 'data:image/jpeg;base64,' + encoded for block in blocks)


def test_asking_for_manual_help_releases_input_but_keeps_conversation():
    handler = IOSHandler(agentmain.GenericAgent(), last_history=['original task'])
    handler._used_phone = True
    handler._phone_frame = 'old'
    with patch('board_bridge.call', return_value={'ok': True}) as release:
        waiting = handler.do_ask_user({'question': '请处理系统权限提示后继续'}, None)
        next(waiting)
        release.assert_called_once_with('hid', {'action': 'stop', 'end_run': False}, consent=False)
        with pytest.raises(StopIteration) as done:
            next(waiting)
    assert done.value.value.should_exit
    assert handler.history_info == ['original task']
    assert not hasattr(handler, '_phone_frame')


def test_lease_retention_is_internal_and_explicit_stop_still_ends_run():
    import hid
    with patch('board_bridge.call', return_value={'ok': True}) as send:
        assert hid.stop() == {'ok': True}
        send.assert_called_once_with('hid', {'action': 'stop'}, consent=False)
    with pytest.raises(ValueError, match='Unknown arguments'):
        hid.call({'action': 'stop', 'end_run': False})
