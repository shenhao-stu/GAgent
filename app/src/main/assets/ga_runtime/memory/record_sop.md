# 录屏 SOP (record) — 系统录屏磁贴，记录 case/演示

> 触发见 `modes_index`。用系统自带录屏录下 GA 操作全过程——不自建录制，只驱动控制中心磁贴。

## 关键约束(实测)
- 录屏磁贴在控制中心，不在启动器 → 不能 `launch`；普通 `swipe` 顶部被安全带夹住够不到 → 用 `droid.panel('right')`(从屏幕最顶端物理下拉)；右半无磁贴改 `'left'`/`'center'`。
- 系统 UI 可 `shot`+`ui_detect`/`ocr` 定位，取 bbox 中心 tap。

## 开始/停止
```python
import droid, time
def center(b): return ((b[0]+b[2])//2, (b[1]+b[3])//2)
droid.panel('right'); time.sleep(1)
els = droid.ui_detect(droid.shot())
hit = next((e for e in els if any(k in (e.get('label') or '')
            for k in ('录屏','屏幕录制','录制','Screen'))), None)   # 磁贴文字随机型
print(droid.tap(*center(hit['bbox'])))
# 弹确认/权限框("开始录制"/"允许") → 再 ui_detect 找按钮 tap；部分机型 3s 倒计时自动开始
```
- 判成没成: 再 `panel('right')` 看磁贴态(录制中含"停止"、空闲含"开始")，或屏上出现红点/计时/悬浮球；确认后再开始演示。
- 停止: 同一磁贴再 tap(切换关闭)，或 `panel('left')` 通知栏点停止。录像入系统相册；极短(1-2s)录制部分机型不落盘，留足时长。

## 注意
- 录屏录全屏 → 开录前 `shot` 确认无敏感信息(验证码/密码/支付页)，有则先切走。
