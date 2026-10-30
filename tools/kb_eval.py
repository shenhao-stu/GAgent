#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kb_eval — 入口知识卡检索的离线验收(确定性, 不连设备、不调模型)。

为什么需要它: 知识卡是**注入**进锚点的(不是模型主动检索的工具), 所以"检索错了"在日志里表现为
"模型照着无关的卡走错路", 事后很难归因。这里用真机历史任务的原文当查询集, 直接量 recall 与
注入预算, 让语料/权重的每次改动都有数字可比。

指标(阈值即验收线):
  recall@1 ≥ 0.70    第一条命中就是该任务的入口卡
  recall@3 ≥ 0.90
  注入字符 ≤ 1200    单次注入预算(超过会挤掉 [GOAL] 等每轮必读内容)
  无关查询 → 0 注入   宁可没有, 不要用不相关的卡污染上下文
  pkg 加成生效        同一个查询换前台包名, 该包的卡排名要上升

用法: python tools/kb_eval.py [--verbose]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/src/main/assets/gacore'))

import kb  # noqa: E402

# (任务原文, 前台包名, 期望的第一张卡) —— 全部取自真机会话原文(temp/logpull/), 不是编的
CASES = [
    ('打开微信 搜三角洲 小程序 去看看今日密码 然后特勤处制作推荐', 'com.tencent.mm', 'delta_force'),
    ('打开微信 搜炉石传说小程序 去看看套牌里的传说榜前三组套牌分别是什么 并把代码复制给我',
     'com.tencent.mm', 'hearthstone'),
    ('在微信里发一条消息给张三 说晚上八点见', 'com.tencent.mm', 'wechat'),
    ('帮我打开支付宝的付款码', 'com.miui.home', 'alipay'),
    ('支付宝里扫一扫付款', 'com.eg.android.AlipayGphone', 'alipay'),
    ('去设置里把悬浮窗权限打开', 'com.miui.home', 'settings'),
    ('刷会儿抖音 看看关注的人发了什么', 'com.ss.android.ugc.aweme', 'douyin'),
    ('微信里朋友圈在哪', 'com.tencent.mm', 'wechat'),
    ('打开微信 用扫一扫', 'com.tencent.mm', 'wechat'),
    ('小程序里找不到入口了 返回上一级再找', 'com.tencent.mm', 'wechat_miniapp'),
]

# 应当**什么都不注入**的查询: 和已收录的 App 无关, 或太泛
NEGATIVES = ['今天天气怎么样', '把手机音量调大一点', '帮我算一下 12 乘以 37']

R1_MIN, R3_MIN, CHARS_MAX = 0.70, 0.90, 1200


def main():
    verbose = '--verbose' in sys.argv
    hits1 = hits3 = 0
    worst = []
    for q, pkg, want in CASES:
        res = kb.search(q, pkg=pkg, k=3)
        ids = [h['id'] for h in res['hits']]
        if ids[:1] == [want]:
            hits1 += 1
        if want in ids[:3]:
            hits3 += 1
        if verbose or want not in ids[:3]:
            print('[%s] %-34s pkg=%-24s → %s (%d 字符)' % (
                'OK ' if ids[:1] == [want] else ('~  ' if want in ids else 'MISS'),
                q[:34], pkg, ids, res['chars']))
        if res['chars'] > CHARS_MAX:
            worst.append((q, res['chars']))
    n = len(CASES)
    r1, r3 = hits1 / n, hits3 / n

    leaks = []
    for q in NEGATIVES:
        res = kb.search(q, pkg='com.miui.home', k=3)
        if res['chars']:
            leaks.append((q, [h['id'] for h in res['hits']]))

    # pkg 加成: 「扫一扫」在微信卡和支付宝卡里都有 —— 前台是哪个包, 谁就排第一
    probe = '扫一扫'
    in_ali = [h['id'] for h in kb.search(probe, pkg='com.eg.android.AlipayGphone', k=3)['hits']]
    in_wx = [h['id'] for h in kb.search(probe, pkg='com.tencent.mm', k=3)['hits']]
    pkg_bonus_ok = (in_ali[:1] == ['alipay']) and (in_wx[:1] == ['wechat'])

    print()
    print('recall@1 = %.2f (>= %.2f) %s' % (r1, R1_MIN, 'PASS' if r1 >= R1_MIN else 'FAIL'))
    print('recall@3 = %.2f (>= %.2f) %s' % (r3, R3_MIN, 'PASS' if r3 >= R3_MIN else 'FAIL'))
    print('注入预算 = %d 字符上限, 超标 %d 条 %s' % (CHARS_MAX, len(worst), 'PASS' if not worst else 'FAIL'))
    print('无关查询泄漏 = %d/%d %s' % (len(leaks), len(NEGATIVES), 'PASS' if not leaks else 'FAIL'))
    print('pkg 加成 = 支付宝内 %s / 微信内 %s %s' % (in_ali[:2], in_wx[:2], 'PASS' if pkg_bonus_ok else 'FAIL'))
    for q, chars in worst:
        print('  超预算: %s (%d)' % (q, chars))
    for q, ids in leaks:
        print('  泄漏: %s → %s' % (q, ids))

    ok = (r1 >= R1_MIN and r3 >= R3_MIN and not worst and not leaks and pkg_bonus_ok)
    print('\nRESULT', 'ALL_GREEN' if ok else 'NEEDS_WORK')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
