# 厂商助手 SOP (vendor_assistant) — 借手机自带 AI 助手提权/加速

> 触发见 `modes_index`。GA 权限不够、或走 droid 太绕的系统级动作(开设置/拨号/设闹钟/装 App 页/深链), 交给自带 AI 助手用**它自己的系统授权**办。机制对所有 OEM 同构, 助手包名由 `vendor_bridge.discover()` 现场探测, 不绑机型。
> 何时用: droid 做不了(需系统权限)或太绕(助手一句话=GA 多步 dump+tap)→优先助手; 助手办不到/需登录/被误解→回退 droid 自己点。

## 用法
```python
import vendor_bridge as v
v.discover()                    # 本机助手 → [{vendor,label,oem,pkg,verified}]; []=无
v.send_to_vendor('打开计算器')    # vendor 省略=自动选首个可用(verified 优先); 或指定 'xiaoai'
v.capability_probe()            # 只读探测当前助手能开哪些系统页
```
返回 `{ok, vendor, ui}`；`needs_gui=True` 时只请求打开了助手，尚未输入命令，需观察后继续。

## 判成没成: 看实际界面
- `ok` 不等于目标任务已完成；观察目标页面或状态确认结果。
- 不因页面未跳转自动重发，先确认是否仍在处理、需要补充信息或未发送。

## 每台机现场标定
各 OEM 助手能开的页面与措辞容忍度不同, 别照搬。首次跑一遍 `capability_probe`, 把「哪句命令真跳到哪个包」落成本机能力画像(每 vendor 一份, 如 Aicy→`aicy_profile.md`), 后续路由直接查。通用规律:
- 可靠: 打开某 App(计算器/相机/日历/时钟)、开顶层设置页。
- 不可靠: 蓝牙/WiFi/声音/定位等子设置常停在助手; 改系统状态命令易被误解(如被当成调音量)→别盲试, 先确认或改走 droid。
- 同一目标不同措辞成败不同, 失败换说法, 别死磕一句话。
- ⚠发送键坑: 部分助手发送是独立按钮非 IME 回车(send_to_vendor 已自动: ENTER 不跳走就 dump 找「发送/Send」tap); 仍不行→看 ui/截图**按位置找(输入框右侧/键盘右下角), 别信图标标签**。

## 适配新机型(三步)
1. `v.discover()`; 空则 `droid.pkgs('助手')`/`droid.pkgs('语音')` 找入口包名。
2. `vendor_bridge.VENDORS` 加 `{pkg, store, label, oem, "verified":False}`。
3. `v.capability_probe('<vendor>')` 真机回填能开的系统页, 端到端过了置 verified:True。

## 红线
- 微信 com.tencent.mm: 只走视觉, 禁 dump 整树(`gandroid-wechat-yolo`)。
- 凭证/隐私不进日志不外传; capability_probe 只发系统类只读命令。

## 机型表(与 `vendor_bridge.VENDORS` 同步)
| `aicy` Meizu/Flyme Aicy | ✅真机端到端验证(能力见本机 aicy_profile.md) |
|---|---|
| `xiaoai`小爱(Xiaomi) `xiaoyi`小艺(Huawei) `xiaobu`小布(OPPO) `jovi`(vivo) `bixby`(Samsung) | 包名入表, 流程通用, 待真机回填 |
