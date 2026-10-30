"""tools_schema 的 gui_act 与实现的一致性(评审实证的三类静默漂移)。

漂移都不报错, 只会让动作静默失效:
① schema 的 enum 宣传了 droid 侧没有的动作(曾: longpress → do_gui_act 抛 AttributeError,
   被宽 except 吞成 [Error] gui_act failed, 整轮作废);
② schema 描述教的参数名与实现读的不一致(曾: key {name:ENTER} 而实现读 args['value'],
   只因默认值恰为 ENTER 才看起来正常; text {value, point?} 而 point 被完全忽略);
③ 描述把 code_run 限成"仅多步逻辑或非 GUI 工作", 与 dump()/look()/ask_vision()/
   recipe_list() 只能经 code_run 调用相冲——观察屏幕被排除在唯一可行通道之外。
"""
import json
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))


class GuiActSchemaContractTest(unittest.TestCase):
    """tools_schema 的 gui_act 与实现的一致性。"""

    ACTIONS_NEEDING_DROID_FN = {
        'tap': 'tap', 'longpress': 'longpress', 'swipe': 'swipe', 'text': 'paste',
        'key': 'key', 'launch': 'launch', 'back': 'back', 'home': 'home',
        'wait': 'wait_stable',
        'search_app': 'search_app',
        'close': 'close_dialog',
        'exit_miniapp': 'exit_miniapp',
    }

    def _schema(self, name):
        path = CORE / 'assets' / name
        for tool in json.loads(path.read_text(encoding='utf-8')):
            if tool.get('function', {}).get('name') == 'gui_act':
                return tool['function']
        raise AssertionError('gui_act not found in %s' % name)

    # 中英两份 schema 必须各自把同一件事讲明白; 关键短语按语言给, 免得断言只对英文生效
    PHRASES = {
        'tools_schema.json': {
            'pixels': 'PIXELS', 'norm': '0-1000', 'rel': 'rel',
            'silent': 'NO error', 'obs_empty': 'when obs is empty',
            'next_target': 'pick the next target straight from it',
        },
        'tools_schema_cn.json': {
            'pixels': '像素', 'norm': '0-1000', 'rel': 'rel',
            'silent': '不报错', 'obs_empty': 'obs 为空',
            'next_target': '选下一个目标',
        },
    }

    def _assert_phrases(self, name, *keys):
        desc = self._schema(name)['description']
        for k in keys:
            self.assertIn(self.PHRASES[name][k], desc, '%s missing %s' % (name, k))

    def test_every_advertised_action_has_a_droid_implementation(self):
        import droid
        fn = self._schema('tools_schema.json')
        for action in fn['parameters']['properties']['action']['enum']:
            self.assertIn(action, self.ACTIONS_NEEDING_DROID_FN, action)
            self.assertTrue(callable(getattr(droid, self.ACTIONS_NEEDING_DROID_FN[action], None)),
                            'gui_act 宣传了 %r 但 droid 侧没有实现' % action)

    def test_handler_accepts_exactly_the_advertised_actions(self):
        import ga_android
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            enum = set(self._schema(name)['parameters']['properties']['action']['enum'])
            self.assertEqual(enum, set(ga_android.GenericAgentHandler._GUI_ACTIONS), name)

    def test_both_language_schemas_agree_on_the_action_set(self):
        a = self._schema('tools_schema.json')['parameters']['properties']['action']['enum']
        b = self._schema('tools_schema_cn.json')['parameters']['properties']['action']['enum']
        self.assertEqual(a, b)

    def test_description_teaches_the_parameter_names_the_code_reads(self):
        # 实现读 args['value']; 描述教 name=/point? 会被静默忽略
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertNotIn('name:ENTER', desc, name)
            self.assertNotIn('point?', desc, name)
            self.assertIn('key {value:ENTER}', desc, name)

    def test_description_states_both_coordinate_spellings(self):
        """回归(真机 1200x2670 实测): 旧契约只认 0-1000, 又靠「任一轴 >1000 就当像素」
        兼容 dump/look 的像素值。在上方 37% 且左侧 83% 的区域内这句恒错且**不报错**——
        放大镜像素 (996,215) 被当成归一化点成 (1195,574)。修正方向是两种写法都显式命名:
        point=像素(照抄观测值), rel=0-1000(ask_vision 答案)。描述必须把两种写法、
        "只能给一种"、以及"不要自己换算"讲明白, 否则模型仍会混。"""
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self._assert_phrases(name, 'pixels', 'norm', 'rel')
            # 关键教训要写进去: 混用不报错, 只是点偏
            self._assert_phrases(name, 'silent')
            # 旧描述那句会把模型引回"自己换算"的话不许再出现
            self.assertNotIn('convert first', desc, name)
            self.assertNotIn('also works', desc, name)
            self.assertNotIn('1000/screen_w', desc.replace(' ', ''), name)
        # 参数表里必须真有 rel 字段, 否则描述教了也传不进去
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            props = self._schema(name)['parameters']['properties']
            self.assertIn('rel', props, name)
            self.assertIn('point', props, name)

    def test_description_promises_the_post_action_observation(self):
        """回归(真机实证): 39 轮任务里约 20 轮是纯观察(code_run + dump/look),
        在供应商 p50 延迟 5~10s 的现状下每轮都是 5~10s。gui_act 结果带紧凑 obs 后
        模型通常能直接选下一个目标。描述必须把这件事讲明白, 否则模型不知道有 obs,
        照样每动作花一轮去观察——功能就白加了。"""
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertIn('obs', desc, name)
            self._assert_phrases(name, 'next_target')
            # 也要说清 obs 为空时怎么办, 否则模型可能拿着空观测硬猜
            self._assert_phrases(name, 'obs_empty')

    def test_description_does_not_forbid_observing_the_screen(self):
        # 观察(dump/look)只有 code_run 一条路; 曾把"非 GUI 工作"当成唯一许可, 自相矛盾
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._schema(name)['description']
            self.assertIn('code_run', desc, name)
            self.assertNotIn('only for multi-step logic or non-GUI work', desc, name)


class SeeSchemaContractTest(unittest.TestCase):
    """tools_schema 的 see 与 do_see 的一致性。

    同类漂移在 gui_act 上出过三次(见本文件 docstring), see 是新加的第一级工具, 照同一套锁:
    schema 宣传的参数实现必须真的读, 否则要么静默忽略, 要么整轮作废。"""

    def _see(self, name):
        path = CORE / 'assets' / name
        for tool in json.loads(path.read_text(encoding='utf-8')):
            if tool.get('function', {}).get('name') == 'see':
                return tool['function']
        raise AssertionError('see not found in %s' % name)

    def test_see_exists_in_both_schemas(self):
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            self.assertIn('see', [t['function']['name'] for t in
                                  json.loads((CORE / 'assets' / name).read_text(encoding='utf-8'))], name)

    def test_declared_params_are_all_read_by_the_implementation(self):
        """schema 里宣传的每个参数, do_see 必须真的从 args 里取。"""
        import inspect
        import ga_android
        src = inspect.getsource(ga_android.GenericAgentHandler.do_see)
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            params = self._see(name)['parameters']
            for prop in params['properties']:
                self.assertIn("'%s'" % prop, src,
                              '%s: schema 宣传了 %s 但 do_see 不读它' % (name, prop))
            self.assertEqual(params['required'], ['question'], name)

    def test_description_states_the_local_channels_come_first(self):
        """必须讲明"普通页用 obs, 别为图标打 see()"——否则每步都多付一次 15-46s。"""
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._see(name)['description']
            self.assertIn('obs', desc, name)

    def test_description_forbids_retrying_after_failure(self):
        for name in ('tools_schema.json', 'tools_schema_cn.json'):
            desc = self._see(name)['description']
            self.assertIn('retry' if name.endswith('tools_schema.json') else '重试', desc, name)


if __name__ == '__main__':
    unittest.main()
