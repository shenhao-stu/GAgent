"""kb: 入口知识卡的检索(确定性, 无向量库)。

真机动机(m01306/m01608): 每个任务开头固定两次 file_read(phone_use.md 318 行只给 60 行 +
app_cards.md 133 行只给 60 行) ≈4s, 还常常只拿到无关段落; 而"微信里小程序/朋友圈在哪"这类
知识每次任务都要用。检索放在锚点里(模型说话之前), 不额外花一轮工具调用(每轮往返 5-6s)。
"""
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[1] / 'app/src/main/assets/gacore'
sys.path.insert(0, str(CORE))

import ga_android
import kb


def _card(**kw):
    base = dict(id='x', app='微信', pkg='com.tencent.mm', aliases=[], intent=[], verified=True,
                verified_at='', evidence='', body='- 正文一行\n- 正文两行\n', conf=1.0,
                tok_app=kb._tokens('微信'), tok_aliases=set(), tok_intent=set(),
                tok_body=kb._tokens('正文'), dl=4)
    base.update(kw)
    return base


class FrontMatterTest(unittest.TestCase):
    def test_list_and_bool_and_int(self):
        meta, body = kb._parse_front('---\napp: 微信\naliases: [a, b, 小程序]\n'
                                     'verified: true\nconfidence: 0.5\n---\n- 正文\n')
        self.assertEqual(meta['app'], '微信')
        self.assertEqual(meta['aliases'], ['a', 'b', '小程序'])
        self.assertEqual(meta['verified'], 'true')
        self.assertEqual(body.strip(), '- 正文')

    def test_no_front_matter_is_all_body(self):
        meta, body = kb._parse_front('- 只有正文\n')
        self.assertEqual(meta, {})
        self.assertEqual(body, '- 只有正文\n')


class TokenizeTest(unittest.TestCase):
    def test_chinese_bigrams(self):
        t = kb._tokens('打开微信')
        self.assertIn('打开', t)
        self.assertIn('微信', t)

    def test_ascii_and_pkg(self):
        t = kb._tokens('com.tencent.mm wechat')
        self.assertIn('com.tencent.mm', t)
        self.assertIn('wechat', t)

    def test_stopwords_dropped(self):
        self.assertNotIn('的', kb._tokens('的'))


class ScoreTest(unittest.TestCase):
    def test_pkg_bonus_breaks_a_tie(self):
        a = _card(id='a', app='甲', tok_app=kb._tokens('甲'), pkg='com.a')
        b = _card(id='b', app='乙', tok_app=kb._tokens('乙'), pkg='com.b',
                  tok_body=kb._tokens('查'))
        both = kb.score_cards('查', pkg='com.b', kb_cards=[a, b])
        self.assertEqual(both[0][1]['id'], 'b')

    def test_pending_card_scores_lower(self):
        on = _card(id='on', conf=kb.VERIFIED_CONF)
        pend = _card(id='pend', conf=kb.PENDING_CONF)
        out = kb.score_cards('微信', kb_cards=[on, pend])
        self.assertEqual([c['id'] for _s, c in out], ['on', 'pend'])
        self.assertGreater(out[0][0], out[1][0])


class RenderTest(unittest.TestCase):
    def test_pending_flag_and_id(self):
        text = kb.render(_card(id='delta', app='三角洲', verified=False))
        self.assertTrue(text.startswith('[KB:delta] 三角洲 [待核]'))

    def test_verified_has_no_flag(self):
        self.assertNotIn('[待核]', kb.render(_card(id='w', app='微信')))


class SearchTest(unittest.TestCase):
    def test_irrelevant_query_returns_nothing(self):
        res = kb.search('今天天气怎么样', pkg='com.miui.home')
        self.assertEqual(res['text'], '')
        self.assertEqual(res['hits'], [])

    def test_budget_and_tail(self):
        res = kb.search('打开微信 搜三角洲 小程序 去看看今日密码 然后特勤处制作推荐',
                        pkg='com.tencent.mm', k=3)
        self.assertLessEqual(res['chars'], kb.BUDGET + 120)
        self.assertIn('不覆盖工具协议', res['text'])
        self.assertEqual(res['hits'][0]['id'], 'delta_force')

    def test_relevance_floor_drops_noise(self):
        res = kb.search('帮我打开支付宝的付款码', pkg='com.miui.home', k=3)
        self.assertEqual([h['id'] for h in res['hits']], ['alipay'])

    def test_truncation_happens_on_a_line_boundary(self):
        # 单卡正文本来就被 CARD_MAX(600) 截过, 所以要靠「多卡 + 小预算」才触发块级截断
        body = ('\n'.join('- 第 %d 行内容说明文字再长一点' % i for i in range(60)))
        a = _card(id='a', app='微信甲', body=body)
        b = _card(id='b', app='微信乙', body=body)
        res = kb.search('微信', kb_cards=[a, b], k=2, budget=700)
        self.assertLessEqual(res['chars'], 700 + 120)
        self.assertIn('（略', res['text'])
        self.assertNotIn('第 59 行', res['text'])


class _Handler(object):
    """最小替身: 只放 _kb_block 需要的属性(不构造整个 GenericAgentHandler)。"""
    _KB_TURNS = 2
    _KB_MAX_LINES = 24
    _KB_MAX_INJECT = 3
    _kb_block = None
    _kb_cards = None


class KbBlockTest(unittest.TestCase):
    def _handler(self, turn, pkg='com.tencent.mm', goal='打开微信 搜三角洲 小程序 去看看今日密码'):
        h = _Handler()
        h.current_turn = turn
        h._goal_text = goal
        h._last_expect = None
        h._kb_text = None
        h._kb_injected = None
        h._kb_block = types.MethodType(ga_android.GenericAgentHandler._kb_block, h)
        h._kb_cards = types.MethodType(ga_android.GenericAgentHandler._kb_cards, h)
        self.pkg = pkg
        return h

    def setUp(self):
        # ga_android 刻意不 import droid(设备无关), `_kb_cards` 里是函数内 `import droid`,
        # 所以 patch sys.modules 才是生效的那条路。
        self.fake = types.SimpleNamespace(_fg=lambda: self.pkg,
                                          entry_hint=lambda p=None: '')
        self._saved = sys.modules.get('droid')
        sys.modules['droid'] = self.fake

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('droid', None)
        else:
            sys.modules['droid'] = self._saved

    def test_first_turn_gets_index_and_cards(self):
        out = self._handler(1)._kb_block()
        self.assertIn('### [KB] 常见入口索引', out)
        self.assertIn('[KB:delta_force', out)

    def test_later_turns_do_not_reinject_the_same_app(self):
        h = self._handler(1)
        h._kb_block()
        h.current_turn = 6
        self.assertEqual(h._kb_block(), '')          # 同一 App + 超过 _KB_TURNS → 不再注入

    def test_switching_app_reinjects(self):
        h = self._handler(1)
        h._kb_block()
        h.current_turn = 7
        self.pkg = 'com.eg.android.AlipayGphone'
        h._goal_text = '帮我打开支付宝的付款码'
        out = h._kb_block()
        self.assertIn('[KB:alipay]', out)

    def test_injection_count_is_capped(self):
        # 每次换 App 都配上「这个任务真的和它相关」的目标, 否则检索出的卡全是已注入过的,
        # 过滤后为空、不算一次注入(这是有意的: 没注入成功就不该吃掉配额)。
        h = self._handler(1)
        h._kb_block()
        for pkg, turn, goal in (('com.eg.android.AlipayGphone', 5, '帮我打开支付宝的付款码'),
                                ('com.android.settings', 9, '去设置里把悬浮窗权限打开'),
                                ('com.ss.android.ugc.aweme', 13, '刷会儿抖音'),
                                ('com.miui.home', 17, '再换个 App 看看')):
            self.pkg = pkg
            h.current_turn = turn
            h._goal_text = goal
            h._kb_block()
        self.assertEqual(h._kb_injected['n'], h._KB_MAX_INJECT)

    def test_same_card_never_repeats(self):
        h = self._handler(1)
        first = h._kb_block()
        self.pkg = 'com.miui.home'
        h._kb_block()
        self.pkg = 'com.tencent.mm'
        third = h._kb_block()
        self.assertNotIn('delta_force', third)
        self.assertIn('delta_force', first)

    def test_missing_kb_dir_degrades_to_empty(self):
        h = self._handler(1)
        saved = kb.cards
        try:
            kb.cards = lambda kb_dir=None: []
            self.assertEqual(h._kb_cards(), '')
        finally:
            kb.cards = saved


if __name__ == '__main__':
    unittest.main()


class KbModeSwitchTest(unittest.TestCase):
    """`/kv.set ga.kbmode off` 要能立刻关掉注入(不用重装 APK)。"""

    def setUp(self):
        import agent_settings
        self.settings = agent_settings
        self.root = tempfile.mkdtemp()
        self._saved = agent_settings.kv_get

    def tearDown(self):
        self.settings.kv_get = self._saved
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_is_lexical(self):
        self.assertEqual(self.settings.kb_mode(self.root), 'lexical')

    def test_off_and_bools(self):
        for raw, want in (('off', 'off'), ('0', 'off'), ('false', 'off'),
                          ('on', 'lexical'), ('lexical', 'lexical'),
                          ('recall', 'recall'), ('both', 'both'), ('??', 'lexical')):
            self.settings.kv_set(self.settings.KEY_KB_MODE, raw, self.root)
            self.assertEqual(self.settings.kb_mode(self.root), want, raw)

    def test_off_silences_the_block(self):
        import ga_android
        h = _Handler()
        h.current_turn = 1
        h._goal_text = '打开微信 搜三角洲 小程序 去看看今日密码'
        h._last_expect = None
        h._kb_text = None
        h._kb_injected = None
        h._kb_block = types.MethodType(ga_android.GenericAgentHandler._kb_block, h)
        h._kb_cards = types.MethodType(ga_android.GenericAgentHandler._kb_cards, h)
        saved = self.settings.kv_get
        try:
            self.settings.kv_get = lambda key, default='', root=None: (
                'off' if key == self.settings.KEY_KB_MODE else saved(key, default, root))
            self.assertEqual(h._kb_block(), '')
            self.settings.kv_get = lambda key, default='', root=None: (
                '' if key == self.settings.KEY_KB_MODE else saved(key, default, root))
            self.assertIn('[KB:delta_force', h._kb_block())
        finally:
            self.settings.kv_get = saved
