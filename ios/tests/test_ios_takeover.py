from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
import threading
import signed_runtime
import agentmain
from kernel_adapter.ios_host import IOSHandler
from kernel_adapter.ios_takeover import perform


def test_handoff_cannot_cross_conversations_or_resume_before_stop():
    h = IOSHandler(agentmain.GenericAgent()); h._used_phone = True; h._phone_frame = 'seen before the handoff'
    s = SimpleNamespace(agent=SimpleNamespace(handler=h, is_running=True))
    native = Mock(return_value={'ok': True, 'token': 'first'})
    abort = Mock()
    def call(action, token='', session=s):
        return perform(session, action, token, native=native, abort=abort)
    assert call('pause')['token'] == 'first'
    assert not hasattr(h, '_phone_frame')
    abort.assert_called_once()
    count = native.call_count
    assert not call('resume', 'first')['ok']
    s.agent.is_running = False
    assert not call('resume', 'stale')['ok']
    other = SimpleNamespace(agent=SimpleNamespace(handler=IOSHandler(agentmain.GenericAgent()), is_running=False))
    assert not call('resume', 'first', other)['ok']
    assert native.call_count == count
    # A user turn may recreate the handler; the original conversation still owns the pause.
    s.agent.handler = IOSHandler(agentmain.GenericAgent())
    s.agent.handler._phone_frame = 'seen while the user had the phone'
    assert call('status')['paused']
    assert call('resume', 'first')['ok']
    assert not hasattr(s.agent.handler, '_phone_frame')
    assert not call('resume', 'first')['ok'], 'resume is single-use'
    assert s.agent.handler.history_info == [], 'no synthetic replacement history'


def test_native_rejection_keeps_the_handoff_pending():
    h = IOSHandler(agentmain.GenericAgent()); h._used_phone = True
    s = SimpleNamespace(agent=SimpleNamespace(handler=h, is_running=False), _phone_pause_token='pending')
    result = perform(s, 'resume', 'pending', native=Mock(return_value={'ok': False}), abort=Mock())
    assert not result['ok'] and s._phone_pause_token == 'pending'


def test_cancel_ends_handoff_while_the_previous_model_call_is_still_running():
    h = IOSHandler(agentmain.GenericAgent()); h._used_phone = True
    h._phone_pause_token = 'pending'; h._phone_frame = 'old'
    s = SimpleNamespace(agent=SimpleNamespace(handler=h, is_running=True), _phone_pause_token='pending')
    native = Mock(return_value={'ok': True})
    def check_cleared():
        assert s._phone_pause_token is None and h._phone_pause_token is None
        assert not hasattr(h, '_phone_frame'), 'cancel state must clear before waiting for network teardown'
    abort = Mock(side_effect=check_cleared)
    result = perform(s, 'cancel', 'pending', native=native, abort=abort)
    assert result['ok'], 'ending a task must not wait for a model response to finish'
    native.assert_called_once_with('cancel', {'token': 'pending'})
    abort.assert_called_once()
    assert s._phone_pause_token is None and h._phone_pause_token is None
    assert not hasattr(h, '_phone_frame')


def test_cancel_with_stale_ticket_cannot_stop_another_handoff():
    h = IOSHandler(agentmain.GenericAgent()); h._used_phone = True
    s = SimpleNamespace(agent=SimpleNamespace(handler=h, is_running=True), _phone_pause_token='current')
    native, abort = Mock(), Mock()
    assert not perform(s, 'cancel', 'old', native=native, abort=abort)['ok']
    native.assert_not_called(); abort.assert_not_called()


def test_release_failure_still_aborts_the_model_and_ends_a_cancelled_native_handoff():
    h = IOSHandler(agentmain.GenericAgent()); h._used_phone = True
    s = SimpleNamespace(agent=SimpleNamespace(handler=h, is_running=True), _phone_pause_token='pending')
    native = Mock(return_value={'ok': False, 'stopped': True, 'error': 'release failed'})
    abort = Mock()
    result = perform(s, 'cancel', 'pending', native=native, abort=abort)
    assert not result['ok'] and result['error'] == 'release failed'
    abort.assert_called_once()
    assert s._phone_pause_token is None and h._phone_pause_token is None


def test_control_page_stop_ends_paused_handoffs_before_aborting_remaining_drivers():
    import ios_entry
    import android_entry as entry
    from kernel_adapter import ios_host
    session = SimpleNamespace(cid='phone', retired=False, _phone_pause_token='owned')
    ordinary = SimpleNamespace(cid='chat', retired=False)
    events = []
    with patch.object(entry, '_REG', {'phone': session, 'chat': ordinary}), \
         patch.object(entry, '_reg_lock', threading.RLock()), \
         patch.object(entry, '_pub_cid', lambda cid: cid), \
         patch.object(ios_entry, 'phone_takeover', side_effect=lambda *args: events.append(args)), \
         patch.object(ios_host, 'abort_drivers', side_effect=lambda: events.append(('drivers',))):
        ios_entry.iphone_abort()
    assert events == [('phone', 'cancel', 'owned'), ('drivers',)]
