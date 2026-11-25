"""Conversation-scoped handoff at the iOS boundary. The shared agent history is never replaced."""
from kernel_adapter.ios_host import IOSHandler


def perform(session, action, token, *, native, abort):
    agent = session.agent if session else None
    handler = getattr(agent, 'handler', None)
    owned = getattr(session, '_phone_pause_token', None)
    if not isinstance(handler, IOSHandler) or not (getattr(handler, '_used_phone', False) or owned):
        return {'ok': False, 'error': '当前对话没有可接管的 iPhone 任务'}
    if action == 'status':
        return {'ok': True, 'paused': bool(owned), 'token': owned or '', 'running': bool(agent.is_running)}
    if action == 'pause':
        result = native('pause', {})
        if not result.get('ok'):
            return result
        session._phone_pause_token = handler._phone_pause_token = result['token']
        handler.invalidate_phone_observation()
        abort()
        return {'ok': True, 'token': result['token'], 'paused': True}
    if action in ('resume', 'cancel'):
        if not token or token != owned or action == 'resume' and agent.is_running:
            return {'ok': False, 'error': '请稍候任务停止；此接管操作可能已过期'}
        result = native(action, {'token': token})
        if result.get('ok') or action == 'cancel' and result.get('stopped'):
            session._phone_pause_token = handler._phone_pause_token = None
            handler.invalidate_phone_observation()
        if action == 'cancel':
            abort()
        return result
    return {'ok': False, 'error': '未知的接管操作'}
