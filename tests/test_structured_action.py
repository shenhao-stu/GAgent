"""F2: GUI 结构化动作协议(phone_use)——模型选动作而非写 Python 代码。

真机实证(对比方案): 自由写 Python 的 agent 在游戏段每轮花 1-3 个模型调用在
探索接口(inspect.signature、试参数、写 OpenCV 分析); 结构化动作协议的 agent
31 步几乎无空转。经实测对比选择此方案效果更佳: 9 个动作 + 参数硬校验。
"""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_loop import StepOutcome

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))
import recipe

ACTIONS = ('tap', 'swipe', 'longpress', 'text', 'key', 'launch', 'back', 'home', 'wait')


def _validate_action(obj):
    """与方案一致的动作校验(镜像自 phone_use 契约)。"""
    if not isinstance(obj, dict):
        raise recipe.RecipeError('action must be object')
    kind = obj.get('action')
    if kind not in ACTIONS:
        raise recipe.RecipeError('unknown action %r' % kind)
    p = obj.get('point')
    if kind in ('tap', 'longpress') and (not p or len(p) != 2):
        raise recipe.RecipeError('%s requires point [x,y]' % kind)
    if kind == 'swipe':
        if not obj.get('point1') or not obj.get('point2'):
            raise recipe.RecipeError('swipe requires point1+point2')
    if kind == 'text' and not obj.get('value'):
        raise recipe.RecipeError('text requires value')
    for k in ('point', 'point1', 'point2'):
        v = obj.get(k)
        if v is not None:
            if len(v) != 2 or not all(isinstance(c, (int, float)) and 0 <= c <= 1000 for c in v):
                raise recipe.RecipeError('%s must be 0-1000 normalized' % k)
    return obj


class StructuredActionTest(unittest.TestCase):
    def test_tap_ok(self):
        self.assertEqual(_validate_action({'action': 'tap', 'point': [500, 500]})['action'], 'tap')

    def test_tap_without_point_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'tap'})

    def test_swipe_requires_two_points(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'swipe', 'point1': [1, 2]})
        _validate_action({'action': 'swipe', 'point1': [1, 2], 'point2': [3, 4], 'ms': 300})

    def test_text_requires_value(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'text'})
        _validate_action({'action': 'text', 'value': '蓝牙'})

    def test_out_of_range_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'tap', 'point': [1200, 500]})

    def test_unknown_action_rejected(self):
        with self.assertRaises(recipe.RecipeError):
            _validate_action({'action': 'teleport'})

    def test_back_home_wait_need_no_params(self):
        for a in ('back', 'home'):
            _validate_action({'action': a})
        _validate_action({'action': 'wait', 'seconds': 2})


if __name__ == '__main__':
    unittest.main()


class GuiActHandlerTest(unittest.TestCase):
    """do_gui_act 的设备接线(打桩 droid, 不碰真机)。"""
    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)
        self.h.cwd = '.'
        self.h.working = {}
        self.h.history_info = []
        self.h.code_stop_signal = []
        self.h.current_turn = 1
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None

    def _run(self, args):
        ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
        if isinstance(ret, StepOutcome):
            return ret
        try:
            next(ret)
        except StopIteration as e:
            return e.value

    def test_tap_normalizes_and_calls_droid(self):
        import ga_android
        calls = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            tap=lambda x, y: calls.append(('tap', x, y)) or {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True, 'waited_s': 0.3, 'uncertain': False})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [996, 215]})
        self.assertEqual(calls, [('tap', 996, 215)])      # point 是像素, 原样落点
        self.assertIn('"action": "tap"', str(out.data))

    def test_rel_is_the_normalized_spelling(self):
        import ga_android
        calls = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            tap=lambda x, y: calls.append(('tap', x, y)) or {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True, 'waited_s': 0.3, 'uncertain': False})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'tap', 'rel': [831, 81]})
        self.assertEqual(calls, [('tap', 996, 216)])

    def test_out_of_range_is_a_soft_result_not_an_error(self):
        # 真机 2026-10-29~30 的 45 条 [Error] 里, 这类"坐标越界/单位用错"占 6 条, 而它本可
        # 当场给出正确写法。现在回 ok:false 的普通结果(soft), 把屏幕尺寸与 rel 建议一起带上,
        # 模型同一轮就能改对 —— 用户在界面上也不再看到一串红字。
        import ga_android
        fake = types.SimpleNamespace(screen=lambda: (1200, 2670))
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [1500, 250]})
        self.assertNotIn('[Error]', str(out.data))
        data = json.loads(out.data)
        self.assertFalse(data['ok'])
        self.assertTrue(data['soft'])
        self.assertEqual(data['screen'], [1200, 2670])
        self.assertIn('rel', data['hint'])

    def test_text_calls_paste(self):
        calls = []
        fake = types.SimpleNamespace(
            paste=lambda v: calls.append(v) or {'hit': True},
            wait_stable=lambda **kw: {'stable': True, 'waited_s': 0.1})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'text', 'value': '蓝牙'})
        self.assertEqual(calls, ['蓝牙'])

    def test_text_forwards_gui_paste_hint_for_sensitive_apps(self):
        """微信等敏感 App: paste 只入剪贴板; 结果必须带 needs_gui_paste+hint,
        否则模型只看到 hit=false/uncertain, 会误以为输入失败去重复点搜索框。"""
        fake = types.SimpleNamespace(
            paste=lambda v: {'hit': False, 'uncertain': True, 'needs_gui_paste': True,
                             'hint': '文本已放入剪贴板，尚未输入。', 'ime_hint': '粘贴'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'text', 'value': '元梦之星'})
        data = str(out.data)
        self.assertIn('needs_gui_paste', data)
        self.assertIn('剪贴板', data)

    def test_wait_uses_wait_stable(self):
        fake = types.SimpleNamespace(
            wait_stable=lambda **kw: {'stable': kw.get('max_wait') == 3, 'waited_s': 1.0})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'wait', 'seconds': 3})
        self.assertIn('"stable": true', str(out.data))


class GuiActOrientationTest(unittest.TestCase):
    """旋转后不要等稳定/取 obs: 动作已使屏幕变横屏, 再截图/OCR 只会白花十几秒。"""
    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)
        self.h.cwd = '.'
        self.h.working = {}
        self.h.history_info = []
        self.h.code_stop_signal = []
        self.h.current_turn = 1
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None

    def _run(self, args):
        ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
        if isinstance(ret, StepOutcome):
            return ret
        try:
            next(ret)
        except StopIteration as e:
            return e.value

    def test_orientation_change_skips_wait_but_keeps_obs(self):
        waited, observed = [], []   # observed 记 observe() 次数(_compact_obs 现在走它拿观测)
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            tap=lambda x, y: {'diff': 'n/a', 'verified': False, 'uncertain': True,
                              'orientation_changed': True, 'screen': (2670, 1200), 'rot': 1,
                              'orientation': 'landscape', 'hint': '屏幕方向已变化'},
            wait_stable=lambda **kw: waited.append(kw) or {'stable': True},
            dump=lambda: [{'t': '通行证', 'x': 210, 'y': 561}],
            dump_state=lambda: {'nodes': [{'t': '通行证', 'x': 210, 'y': 561}],
                                'degraded': None},
            screen_kind=lambda: 'ui',
            look=lambda *a, **k: [],
            observe=lambda **k: observed.append(1) or _fake_observe(
                nodes=[{'t': '通行证', 'x': 210, 'y': 561}], dets=[]))
        with patch.dict(sys.modules, {'droid': fake}):
            out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        self.assertEqual(out['screen'], [2670, 1200])
        self.assertEqual(out['rot'], 1)
        self.assertEqual(out['orientation'], 'landscape')
        self.assertEqual(waited, [])                  # 旋转时不等稳定
        self.assertEqual(len(observed), 1)            # 但仍取新画面观测
        self.assertEqual(out['obs'][0]['t'], '通行证')

    def test_launch_forwards_screen_and_orientation(self):
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            launch=lambda pkg: {'fg': pkg, 'screen': (2670, 1200), 'rot': 1,
                                'orientation': 'landscape'},
            wait_stable=lambda **kw: {'stable': True},
            dump=lambda: [],
            dump_state=lambda: {'nodes': [], 'degraded': {'reason': 'tree_empty'}},
            screen_kind=lambda: 'canvas',
            look=lambda *a, **k: [{'t': '开始游戏', 'x': 500, 'y': 600}],
            observe=lambda **k: _fake_observe(nodes=[], dets=[], kind='canvas'))
        with patch.dict(sys.modules, {'droid': fake}):
            out = json.loads(self._run({'action': 'launch', 'value': 'com.tencent.mm'}).data)
        self.assertEqual(out['screen'], [2670, 1200])
        self.assertEqual(out['orientation'], 'landscape')


class ResolvePointTest(unittest.TestCase):
    """gui_act 坐标: point=像素, rel=0-1000。两个具名字段二选一, 不猜单位。

    回归来源(真机 1200x2670, 2026-10-27 实测): 旧 _norm_pt 用「任一轴 >1000 就当
    像素」区分两种单位, 对 y<=1000(屏幕上方 37%)且 x<=1000(宽 83%)的区域恒错且
    **不报错**——放大镜像素 (996,215) 被当成归一化点成 (1195,574), 偏 199px 右、
    359px 下; 搜索框 (635,245) → (762,654), 偏 409px 下。模型只看到 diff=0, 于是
    反复重点。而搜索框/放大镜/标题行全在这片区域, 「点不到搜索框」因此是必然。
    """

    def _resolve(self, args, key='point', rel_key='rel'):
        import ga_android
        h = object.__new__(ga_android.GenericAgentHandler)
        fake = types.SimpleNamespace(screen=lambda: (1200, 2670))
        with patch.dict(sys.modules, {'droid': fake}):
            return h._resolve_point(args, key, rel_key)

    def test_pixels_pass_through_unchanged(self):
        """point 就是像素: 与 look()/dump()/find()/tap() 同一单位, 原样传原样落。"""
        # (0,0) 是状态栏里的退化点, 由专门的用例覆盖(见 status bar 那条)
        for px, py in [(996, 215), (635, 245), (1115, 217), (1199, 2669), (600, 2670 - 1)]:
            self.assertEqual(self._resolve({'point': [px, py]}), (px, py))

    def test_real_device_failures_now_land_on_target(self):
        """这 6 个值是真机上让轮次作废/点偏的实参, 现在必须落在目标像素上。"""
        self.assertEqual(self._resolve({'point': [996, 215]}), (996, 215))
        self.assertEqual(self._resolve({'point': [635, 245]}), (635, 245))
        self.assertEqual(self._resolve({'rel': [831, 81]}), (996, 216))
        self.assertEqual(self._resolve({'rel': [530, 92]}), (635, 246))

    def test_rel_is_converted_exactly(self):
        self.assertEqual(self._resolve({'rel': [0, 0]}), (0, 0))
        self.assertEqual(self._resolve({'rel': [1000, 1000]}), (1199, 2669))
        self.assertEqual(self._resolve({'rel': [500, 500]}), (600, 1334))

    def test_pixels_outside_the_screen_are_rejected_loudly(self):
        """越界必须报错而不是夹取: 夹取会把"单位选错"变成一个看似合理的落点,
        那正是要消掉的静默失败。报错要带上屏幕尺寸和 rel 写法。"""
        with self.assertRaises(ValueError) as cm:
            self._resolve({'point': [2512, 752]})
        msg = str(cm.exception)
        self.assertIn('1200x2670', msg)
        self.assertIn('rel', msg)

    def test_giving_both_units_is_rejected(self):
        for args in ({'point': [996, 215], 'rel': [830, 81]},):
            with self.assertRaises(ValueError) as cm:
                self._resolve(args)
            self.assertIn('only one', str(cm.exception))

    def test_giving_neither_names_both_options(self):
        with self.assertRaises(ValueError) as cm:
            self._resolve({})
        msg = str(cm.exception)
        self.assertIn('point', msg)
        self.assertIn('rel', msg)
        self.assertIn('1200x2670', msg)

    def test_pixel_point_in_the_status_bar_is_rejected_loudly(self):
        """回归(真机 1200x2670, 17:48): ask_vision 回百分数(85%), 模型乘 10 得 850 又猜
        y=45, 当 point 传进去 → 实际点 (1020,120) 状态栏, 搜索页从未打开, 而模型只看到
        diff 29% 以为成功。状态栏没有可点目标, 踩进去几乎只能是"把 0-1000 当成了像素"。"""
        with self.assertRaises(ValueError) as cm:
            self._resolve({'point': [850, 45]})
        msg = str(cm.exception)
        self.assertIn('status bar', msg)
        self.assertIn('rel', msg)                    # 告诉它正确写法
        self.assertIn('droid.tap', msg)              # 以及确需时的逃生门

    def test_real_targets_in_the_title_row_still_pass(self):
        """同一道门不能误伤真目标: 标题行的放大镜/搜索框都在 status 锚带下方。"""
        for px, py in [(996, 215), (635, 245), (1115, 217), (602, 212)]:
            self.assertEqual(self._resolve({'point': [px, py]}), (px, py))

    def test_malformed_values_rejected(self):
        for bad in (['a', 'b'], [None, 5], 'nope', [1, 2, 3]):
            with self.assertRaises(ValueError):
                self._resolve({'point': bad})
            with self.assertRaises(ValueError):
                self._resolve({'rel': bad})

    def test_swipe_uses_its_own_key_pairs(self):
        self.assertEqual(self._resolve({'point1': [100, 200], 'point2': [300, 400]},
                                       'point1', 'rel1'), (100, 200))
        self.assertEqual(self._resolve({'rel1': [100, 200], 'rel2': [300, 400]},
                                       'point1', 'rel1'), (120, 534))


class ActProvedChangeTest(unittest.TestCase):
    """_act_proved_change: 决定 gui_act 要不要再付一次 wait_stable。

    判错的代价是双向的——把"没变化"判成变了会漏等加载页(点到未完成的界面),
    把"变了"判成没变会让动画/canvas 页每步白睡满 max_wait。
    """
    def setUp(self):
        import ga_android
        self.f = ga_android.GenericAgentHandler._act_proved_change

    def test_big_diff_skips_the_extra_wait(self):
        self.assertTrue(self.f('tap', {'diff': 'diff: 12.5% bbox=[1,2,3,4]'}))

    def test_small_diff_still_waits(self):
        # 页面几乎没变(可能在加载): 必须等, 否则下一步点到未完成的界面
        self.assertFalse(self.f('tap', {'diff': 'diff: 0.02% bbox=[1,2,3,4]'}))
        self.assertFalse(self.f('swipe', {'diff': 'diff: n/a'}))

    def test_foreground_pkg_alone_is_not_evidence_of_change(self):
        # 回归: tap()/swipe() 恒设 fg=当前前台包名。拿它当变化证据会让 tap 永远跳过等待。
        self.assertFalse(self.f('tap', {'diff': 'diff: 0.01%', 'fg': 'com.example.app'}))
        self.assertFalse(self.f('swipe', {'fg': 'com.example.app'}))

    def test_launch_foreground_is_evidence(self):
        self.assertTrue(self.f('launch', {'fg': 'com.example.app'}))

    def test_paste_hit_is_evidence(self):
        self.assertTrue(self.f('text', {'hit': True}))
        self.assertFalse(self.f('text', {'hit': False, 'uncertain': True}))

    def test_no_verdict_keys_means_wait(self):
        for act in ('back', 'home', 'key'):
            self.assertFalse(self.f(act, {'action': act}))


class GuiActSkipsRedundantWaitTest(unittest.TestCase):
    """动作自带后验已证明页面变化时, gui_act 不得再调 wait_stable(每步白睡 3s)。"""
    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)
        self.h.cwd = '.'
        self.h.working = {}
        self.h.history_info = []
        self.h.code_stop_signal = []
        self.h.current_turn = 1
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None

    def _run(self, args):
        ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
        if isinstance(ret, StepOutcome):
            return ret
        try:
            next(ret)
        except StopIteration as e:
            return e.value

    def test_tap_with_real_change_skips_wait_stable(self):
        waited = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: 42.0%'},
            wait_stable=lambda **kw: waited.append(kw) or {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertEqual(waited, [])
        self.assertNotIn('stable', str(out.data))

    def test_tap_without_change_still_waits(self):
        waited = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: waited.append(kw) or {'stable': True, 'uncertain': False})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertEqual(len(waited), 1)
        self.assertIn('"stable": true', str(out.data))

    def test_tap_forwards_verdict_fields(self):
        # 坐标失效/点到非热区/验证不可用在模型眼里要能区分, 不能只给一个 diff
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            tap=lambda x, y: {'diff': 'diff: n/a', 'verified': False, 'uncertain': True,
                              'hint': '屏幕尺寸变化；重新截图定位，不复用旧坐标。', 'fg': 'com.a'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        data = str(out.data)
        self.assertIn('"uncertain": true', data)
        self.assertIn('重新截图定位', data)

    def test_longpress_is_dispatched_to_droid(self):
        calls = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: [],
            longpress=lambda x, y, ms: calls.append((x, y, ms)) or {'diff': 'diff: 3.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'longpress', 'point': [635, 245], 'ms': 900})
        self.assertEqual(calls, [(635, 245, 900)])
        self.assertNotIn('[Error]', str(out.data))

    def test_point_actions_observe_before_acting(self):
        # 预观测是 recipe locator 的唯一来源: 不喂它, gui_act 录出的配方 locator 全是 any。
        # 走 ensure_fresh_obs 而不是裸 dump: 模型刚 dump()/look() 过时观测仍有效, 不再重复取。
        obs = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: obs.append(1) or {'nodes': []},
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            swipe=lambda *a, **k: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'tap', 'point': [500, 250]})
            self._run({'action': 'swipe', 'point1': [500, 800], 'point2': [500, 200]})
        self.assertEqual(len(obs), 2)

    def test_point_actions_fall_back_to_dump_when_helper_missing(self):
        # 兼容: 打桩只提供 dump(旧行为)时也不能炸, 更不能不观测
        dumps = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            dump=lambda: dumps.append(1) or [],
            tap=lambda x, y: {'diff': 'diff: 0.01%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            out = self._run({'action': 'tap', 'point': [500, 250]})
        self.assertNotIn('[Error]', str(out.data))

    def test_non_point_actions_do_not_pay_for_an_observation(self):
        obs = []
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: obs.append(1) or {'nodes': []},
            back=lambda: None, home=lambda: None,
            key=lambda name: None, wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            self._run({'action': 'back'})
            self._run({'action': 'home'})
            self._run({'action': 'key', 'value': 'ENTER'})
        self.assertEqual(obs, [])      # back/home/key 没有可定位的目标


NODES = [
    {'t': '搜索', 'cls': 'EditText', 'x': 645, 'y': 598, 'b': '182,527,1109,670'},
    {'t': '取消', 'cls': 'TextButton', 'x': 100, 'y': 200},
    {'t': '', 'cls': 'Image', 'x': 300, 'y': 300},          # 无文字 → 应被丢掉
    {'t': 'x' * 80, 'cls': 'Text', 'x': 10, 'y': 20},        # 超长标签 → 应截断
]
# look() 形态的检测框走 observe() 的 yolo 通道(与 dump 节点分开), 不再是塞进 nodes 里
DETS = [{'label': '发送', 'cls': 'TextButton', 'bbox': [900, 2400, 1100, 2500]}]


def _fake_observe(nodes=NODES, dets=DETS, kind='tree'):
    """droid.observe() 的替身: 按真实契约分 tree/yolo 两个来源产出观测项。

    适配而非弱化: _compact_obs 从"自己分 dump/look 两路"改成"只调 observe()", 于是替身
    要提供 observe。下游断言(标签/单位/截断/封顶)一字未改。
    契约: t=显示文本, desc=contentDescription, type='icon'|'text'(仅 yolo)。"""
    import geom
    items = []
    if kind in ('tree', 'unknown'):
        for n in nodes:
            bx = n.get('b') or n.get('bbox')
            x, y = n.get('x'), n.get('y')
            if x is None or y is None:
                if isinstance(bx, (list, tuple)) and len(bx) >= 4:
                    x, y = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
                else:
                    continue
            rx, ry = geom.to_norm(x, y, 1200, 2670)
            items.append({'src': 'tree', 't': n.get('t') or n.get('label') or '',
                          'desc': n.get('d') or '', 'cls': n.get('cls') or '',
                          'x': x, 'y': y, 'rx': rx, 'ry': ry, 'click': bool(n.get('click')),
                          'type': ''})
    if kind in ('tree', 'blanked', 'unknown'):
        for d in dets:
            if isinstance(d.get('bbox'), (list, tuple)) and len(d['bbox']) >= 4:
                bx1, by1, bx2, by2 = d['bbox']
                cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
            else:                      # look() 形态: 直接给中心点
                cx, cy = d.get('x', 0), d.get('y', 0)
            rx, ry = geom.to_norm(cx, cy, 1200, 2670)
            items.append({'src': 'yolo', 't': d.get('label') or '', 'desc': '',
                          'cls': d.get('cls') or '', 'x': cx, 'y': cy, 'rx': rx, 'ry': ry,
                          'click': None, 'type': 'icon'})
    return {'kind': kind, 'items': items, 'channels': ['tree', 'yolo'], 'notes': [],
            'needs_vision': not items, 'ms': 1.0}


class PostActionObsTest(unittest.TestCase):
    """gui_act 结果必须带动作后的紧凑观测, 否则每个动作都要多花一整轮去观察。

    真机实证: 39 轮任务里约 20 轮是纯观察(code_run + dump/look); 供应商 p50 延迟
    5~10s 的现状下, 省一轮就是省 5~10s。"""

    def setUp(self):
        import ga_android
        self.h = object.__new__(ga_android.GenericAgentHandler)
        self.h.cwd = '.'
        self.h.working = {}
        self.h.history_info = []
        self.h.code_stop_signal = []
        self.h.current_turn = 1
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None

    def _run(self, args, nodes=NODES, dets=None, kind='tree'):
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: list(nodes),
            dump_state=lambda: {'nodes': list(nodes),
                                'degraded': None if nodes else {'reason': 'tree_empty'}},
            screen_kind=lambda: kind,
            look=lambda *a, **k: list(dets or []),
            observe=lambda **k: _fake_observe(nodes, dets if dets is not None else DETS, kind),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            ret = self.h.do_gui_act(args, types.SimpleNamespace(content=''))
            if isinstance(ret, StepOutcome):
                return ret
            try:
                next(ret)
            except StopIteration as e:
                return e.value

    def test_tap_result_carries_obs(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        self.assertIn('obs', out)
        self.assertTrue(out['obs'])
        first = out['obs'][0]
        # x/y=像素(与 look/dump/find 同单位, 可直接当 point); rx/ry=0-1000(可直接当 rel)
        self.assertEqual((first['t'], first['cls']), ('搜索', 'EditText'))
        self.assertEqual((first['x'], first['y']), (645, 598))
        self.assertEqual((first['rx'], first['ry']), (538, 224))

    def test_canvas_skips_the_useless_look_for_obs(self):
        """回归: 游戏/canvas 段每个 gui_act 都白付一次全屏 look()(0.5-0.9s)且返回 []。
        observe() 在 canvas 页直接不跑本地定位通道, 让模型照 SOP 去问 see()。
        真机 20 步累计省 10-18s。"""
        looks = []
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: [],
            dump_state=lambda: {'nodes': [], 'degraded': {'reason': 'tree_empty'}},
            screen_kind=lambda: 'canvas',
            look=lambda *a, **k: looks.append(1) or [{'t': 'x', 'x': 1, 'y': 1}],
            observe=lambda **k: _fake_observe(nodes=[], dets=[], kind='canvas'),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None
        with patch.dict(sys.modules, {'droid': fake}):
            out = json.loads(self.h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                                               types.SimpleNamespace(content='')).data)
        self.assertEqual(out['obs'], [])
        self.assertEqual(looks, [], 'canvas 上不该为 obs 跑 look()')

    def test_sensitive_blank_still_falls_back_to_look(self):
        """对照: 微信这类敏感 App 树被置空但屏幕有大量文字, 必须仍跑 YOLO(OCR 贴 label)。"""
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: [],
            dump_state=lambda: {'nodes': [], 'degraded': {'reason': 'sensitive_blank'}},
            screen_kind=lambda: 'blanked',
            look=lambda *a, **k: [{'t': '搜索框', 'cls': 'EditText', 'x': 635, 'y': 245}],
            observe=lambda **k: _fake_observe(
                nodes=[], dets=[{'label': '搜索框', 'cls': 'EditText',
                                 'bbox': [625, 235, 645, 255]}], kind='blanked'),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        self.h.parent = types.SimpleNamespace(task_dir=None, verbose=False, _turn_end_hooks={})
        self.h.print = lambda *a, **k: None
        with patch.dict(sys.modules, {'droid': fake}):
            out = json.loads(self.h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                                               types.SimpleNamespace(content='')).data)
        self.assertEqual([i['t'] for i in out['obs']], ['搜索框'])

    def test_obs_drops_textless_items_and_truncates_labels(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        labels = [i['t'] for i in out['obs']]
        self.assertNotIn('', labels)                    # 无文字项丢掉
        self.assertTrue(all(len(l) <= 24 for l in labels))
        self.assertIn('发送', labels)                    # look() 形态(bbox)也收

    def test_obs_is_capped(self):
        many = [{'t': 'item%d' % i, 'x': i, 'y': i} for i in range(40)]
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}, nodes=many).data)
        self.assertEqual(len(out['obs']), 12)

    def test_empty_tree_falls_back_to_look(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]},
                                   nodes=[], dets=[{'label': '确定', 'x': 600, 'y': 1200}]).data)
        self.assertEqual([i['t'] for i in out['obs']], ['确定'])

    def test_both_channels_empty_yields_empty_obs(self):
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]},
                                   nodes=[], dets=[]).data)
        self.assertEqual(out['obs'], [])          # 不炸, 模型照旧走 code_run 观察

    def test_obs_does_not_pollute_the_verdict(self):
        """指标口径不能被观测字段污染: extract_verdict 只认白名单键。"""
        import run_metrics
        out = json.loads(self._run({'action': 'tap', 'point': [500, 250]}).data)
        v = run_metrics.extract_verdict(json.dumps(out, ensure_ascii=False))
        self.assertNotIn('obs', v)
        self.assertEqual(set(v), {'diff_pct'})
        self.assertEqual(v['diff_pct'], 8.0)

    def test_obs_survives_a_failing_observation(self):
        """观测取不到不能把动作结果一起毁掉; 键仍在但为空, 模型知道要另行观察。"""
        import ga_android
        fake = types.SimpleNamespace(
            screen=lambda: (1200, 2670),
            ensure_fresh_obs=lambda: {'nodes': []},
            dump=lambda: (_ for _ in ()).throw(RuntimeError('bus down')),
            look=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('bus down')),
            tap=lambda x, y: {'diff': 'diff: 8.0%'},
            wait_stable=lambda **kw: {'stable': True})
        with patch.dict(sys.modules, {'droid': fake}):
            ret = self.h.do_gui_act({'action': 'tap', 'point': [500, 250]},
                                    types.SimpleNamespace(content=''))
            out = json.loads(ret.data)
        self.assertEqual(out['diff'], 'diff: 8.0%')     # 动作结果完好
        self.assertEqual(out['obs'], [])                # 观测缺失给空列表, 不给假数据
