"""/session.<k>=<v> 与 ask_vision 的两组回归（2026-10-28 真机实证）。

真机上下文：用户切模型（step-5-preview → step-3.7-flash）时 vision 要跟着切；
`/session.` 是运行中改后端参数的唯一入口。这里锁住三个曾经真坏的点：
① `/session.model=` 在聚合后端上抛 AttributeError 且无保护 → 逃出
   `_handle_slash_cmd` → `GenericAgent.run()` 的 while True → **该会话 run 线程死掉**；
② 非广播属性只写到 MixinSession 壳上，把 `__getattr__` 永久遮蔽 → 成员仍是旧值，
   而界面还打"✅ 已生效"（`thinking_type` 恰不在广播集合里，而它正是 vision_llm
   每次都要临时改的那个）；
③ ask_vision 没有僵尸线程检查点：code_run 超时后视觉调用（15-46s）会继续拿旧后端打网络。
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))


class _Member:
    def __init__(self, name='m'):
        self.name = name
        self.thinking_type = 'adaptive'
        self.read_timeout = 40


class _Mixin:
    """镜像 llmcore.MixinSession 的关键面: __getattr__ 转发 + 只广播 _BROADCAST_ATTRS。"""

    _BROADCAST_ATTRS = frozenset({'system', 'tools', 'temperature', 'max_tokens',
                                  'reasoning_effort', 'history', 'stream', 'read_timeout'})

    def __init__(self, members):
        self._sessions = members
        self._retries = 3

    def __getattr__(self, name):
        return getattr(self._sessions[0], name)

    def __setattr__(self, name, value):
        if name in _Mixin._BROADCAST_ATTRS:
            for s in self._sessions:
                setattr(s, name, value)
        else:
            object.__setattr__(self, name, value)

    @property
    def model(self):
        return getattr(self._sessions[0], 'model', None)


class ApplySessionAttrTest(unittest.TestCase):
    def test_readonly_model_on_mixin_is_reported_not_raised(self):
        """回归①: 曾经裸 setattr → AttributeError → run 线程死掉, 该会话再也不响应。
        现在如实拒绝并指向 /llm, 且**不会**偷偷改写整个成员链。"""
        members = [_Member('a'), _Member('b')]
        m = _Mixin(members)
        ok, note = _apply(m, 'model', 'step-3.7-flash')
        self.assertFalse(ok)
        self.assertIn('只读', note)
        self.assertIn('/llm', note)
        for mem in members:                 # 成员链未被篡改
            self.assertFalse(hasattr(mem, 'model'))

    def test_non_broadcast_attr_reaches_the_members(self):
        """回归②: thinking_type 不在 _BROADCAST_ATTRS 里, 只写壳=成员仍是旧值。
        而它正是 vision_llm 每次都要临时改的字段——写不进去则主链路和视觉链路都失效。"""
        members = [_Member('a'), _Member('b')]
        m = _Mixin(members)
        ok, note = _apply(m, 'thinking_type', 'disabled')
        self.assertTrue(ok, note)
        for mem in members:
            self.assertEqual(mem.thinking_type, 'disabled')
        self.assertIn('2', note)            # 备注要说清同步到了几个成员

    def test_broadcast_attr_still_works(self):
        members = [_Member()]
        m = _Mixin(members)
        ok, _ = _apply(m, 'read_timeout', 90)
        self.assertTrue(ok)
        self.assertEqual(members[0].read_timeout, 90)

    def test_plain_backend_gets_the_value(self):
        b = _Member()
        ok, note = _apply(b, 'thinking_type', 'disabled')
        self.assertTrue(ok)
        self.assertEqual(b.thinking_type, 'disabled')
        self.assertEqual(note, '')

    def test_member_that_refuses_the_attr_is_reported(self):
        """成员本身拒写(如 __slots__)时要如实报失败, 不能打 ✅。"""
        class _Slotted:
            __slots__ = ('name',)

        ok, note = _apply(_Slotted(), 'thinking_type', 'disabled')
        self.assertFalse(ok)
        self.assertIn('thinking_type', note)


class VisionZombieCheckpointTest(unittest.TestCase):
    def test_ask_vision_checks_the_run_guard_token(self):
        """回归③: code_run 超时后视觉调用是最容易长时间挂住的副作用(一次 15-46s),
        不设卡则僵尸线程继续拿旧后端打网络, 反复烧预算。"""
        import droid
        calls = []
        orig = droid.run_guard.check

        def spy():
            calls.append(1)
            return orig()
        ctx = unittest.mock.patch.object(droid.run_guard, 'check', spy)
        with ctx:
            try:
                droid.ask_vision(None, 'x')
            except Exception:
                pass
        self.assertEqual(calls, [1], 'ask_vision 必须过僵尸线程检查点')


def _apply(backend, k, v):
    import agentmain
    return agentmain._apply_session_attr(backend, k, v)


import unittest.mock  # noqa: E402  (供上面的 patch 使用)

if __name__ == '__main__':
    unittest.main()
