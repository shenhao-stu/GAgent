"""设置项「结束任务后返回桌面」: 一行开关 + 一个原生桥 + 一个真结束挂点。

需求原文(m01481): 入口放 ga 设置-通用设置-悬浮窗常开下面, 结束任务后返回桌面。
三条契约:
  ① 开关真值在原生 SharedPreferences("ga").home_after_task, 读桥 homeAfterTask()(不让 kv 镜像分叉);
  ② UI 行必须紧跟「悬浮窗常开」之后(用户指定的位置), 中英双语标签齐全;
  ③ 只在**真结束**(onTaskDone, done/error)触发 goHome; ask_user 那种"等你回话"的停点不触发。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / 'app/src/main/assets/gacore/webui'
KT = ROOT / 'app/src/main/java/com/ljq/ga/MainActivity.kt'


class NativeBridgeTest(unittest.TestCase):
    def setUp(self):
        self.src = KT.read_text(encoding='utf-8')

    def test_pref_key_and_bridges(self):
        self.assertIn('"home_after_task"', self.src)
        self.assertIn('@JavascriptInterface fun setHomeAfterTask(on: Boolean): Boolean', self.src)
        self.assertIn('@JavascriptInterface fun homeAfterTask(): Boolean', self.src)

    def test_go_home_uses_home_intent_without_permission(self):
        i = self.src.find('@JavascriptInterface fun goHome()')
        self.assertGreater(i, 0)
        block = self.src[i:i + 700]
        self.assertIn('Intent.ACTION_MAIN', block)
        self.assertIn('Intent.CATEGORY_HOME', block)
        self.assertIn('FLAG_ACTIVITY_NEW_TASK', block)
        # HOME intent 不需要任何运行时权限: 出现 requestPermissions 就是走错了路
        self.assertNotIn('requestPermissions', block)


class SettingsRowTest(unittest.TestCase):
    def setUp(self):
        self.html = (WEBUI / 'index.html').read_text(encoding='utf-8')

    def test_row_sits_right_below_the_float_always_row(self):
        i_float = self.html.find('id="swFloatAlways"')
        i_home = self.html.find('id="swHomeAfterTask"')
        self.assertGreater(i_float, 0)
        self.assertGreater(i_home, i_float)
        between = self.html[i_float:i_home]
        self.assertEqual(between.count('class="row"'), 1)      # 中间只隔着一行的收尾, 没有别的设置项

    def test_row_is_a_switch_with_label(self):
        i = self.html.find('id="swHomeAfterTask"')
        seg = self.html[max(0, i - 800):i + 400]
        self.assertIn('role="switch"', seg)
        self.assertIn('data-i18n="homeAfterTask"', seg)
        self.assertIn('onclick="toggleHomeAfterTask(this)"', seg)


class I18nTest(unittest.TestCase):
    def test_both_languages_have_the_label(self):
        s = (WEBUI / 'assets/i18n.js').read_text(encoding='utf-8')
        self.assertIn("homeAfterTask:'结束任务后返回桌面'", s)
        self.assertIn("homeAfterTask:'Return to home screen when a task ends'", s)


class TaskEndHookTest(unittest.TestCase):
    def setUp(self):
        self.js = (WEBUI / 'app.js').read_text(encoding='utf-8')

    def test_state_refresh_and_toggle_exist(self):
        self.assertIn("let homeAfterTask=LS.get('homeAfterTask',false)", self.js)
        self.assertIn('GA.homeAfterTask()', self.js)               # 渲染时读原生真值
        i = self.js.find('function toggleHomeAfterTask(e)')
        self.assertGreater(i, 0)
        self.assertIn('GA.setHomeAfterTask(want)', self.js[i:i + 500])

    def _body(self, name):
        i = self.js.find('function %s(' % name)
        self.assertGreater(i, 0)
        depth, started = 0, False
        for k in range(i, len(self.js)):
            if self.js[k] == '{':
                depth += 1
                started = True
            elif self.js[k] == '}':
                depth -= 1
                if started and depth == 0:
                    return self.js[i:k + 1]
        self.fail('unbalanced %s' % name)

    def test_home_is_pressed_only_on_real_completion(self):
        done = self._body('onTaskDone')
        self.assertIn('GA.goHome()', done)
        self.assertIn('if(homeAfterTask&&show!==false)', done)     # 只在本会话在屏上时退回桌面
        need = self._body('onNeedInput')
        self.assertNotIn('goHome', need)                          # ask_user 不退回桌面

    def test_background_task_does_not_hijack_the_screen(self):
        done = self._body('onTaskDone')
        self.assertIn('show!==false', done)                       # 别会话/预览态不抢屏

    def test_switch_is_not_behind_a_permission(self):
        body = self._body('toggleHomeAfterTask')
        self.assertNotIn('requestOverlayPerm', body)              # 无权限门: 与悬浮窗开关不同
        self.assertNotIn('floatPermGuide', body)


if __name__ == '__main__':
    unittest.main()
