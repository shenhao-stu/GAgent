# -*- coding: utf-8 -*-
"""vendor_bridge — 通用厂商助手适配器 (VendorAssistantAdapter, OUTBOUND 前台驱动)

借手机厂商内置 AI 助手(各 OEM 自带)用它**自己的系统级授权**, 执行 GA 直接做不了的动作。
机制(全 OEM 通用, 与具体厂商无关): GA 用自身无障碍(droid) 打开助手 → 输入自然语言命令 → 发送
→ 读回控件摘要；执行结果由实际界面确认。**不绑定任何单一机型**: 助手包名由 discover() 在本机运行时探测。
合规红线: 合规的「前台 AI 助手控制」, 依赖助手自身授权; **不** root / 不破解 / 不绕过 Android 安全 / 不提权。
配套 SOP: memory/vendor_assistant_sop.md。

用法:
    import vendor_bridge as v
    v.discover()                      # 本机装了哪些厂商助手 → [{vendor,label,oem,pkg,verified}]
    v.send_to_vendor("打开系统设置")    # vendor 省略=自动选本机首个可用助手
    v.send_to_vendor("打开计算器", "xiaoai")
    v.capability_probe()              # 只读探测当前助手能开哪些系统页
"""
import time
import droid

# 厂商助手注册表(单一真相源)。每项只存「入口包名 + 智能体商店 + 展示名 + OEM + 是否真机验证」。
# 唤起/输入/读回逻辑全通用——加机型 = 加一行, 不写专用流程。包名为各 OEM 公开的助手入口包。
# verified=True 仅表示已在真机端到端验证; False = 包名已知、流程通用、待真机回填 profile。
VENDORS = {
    "aicy":   {"pkg": "com.meizu.voiceassistant",        "store": "com.meizu.flyme.agentstore", "label": "Aicy",   "oem": "Meizu/Flyme",      "verified": True},
    "xiaoai": {"pkg": "com.miui.voiceassist",            "store": "",                           "label": "小爱同学", "oem": "Xiaomi/HyperOS",   "verified": False},
    "xiaoyi": {"pkg": "com.huawei.vassistant",           "store": "",                           "label": "小艺",    "oem": "Huawei/HarmonyOS", "verified": False},
    "xiaobu": {"pkg": "com.heytap.speechassist",         "store": "",                           "label": "小布",    "oem": "OPPO/ColorOS",     "verified": False},
    "jovi":   {"pkg": "com.vivo.agent",                  "store": "",                           "label": "Jovi",   "oem": "vivo/OriginOS",    "verified": False},
    "bixby":  {"pkg": "com.samsung.android.bixby.agent", "store": "",                           "label": "Bixby",  "oem": "Samsung/OneUI",    "verified": False},
}


def discover():
    """扫描本机已装包, 返回存在的厂商助手 [{vendor,label,oem,pkg,verified}]; 无则 []。
    这是「适配任意机型」的入口: 不预设是哪家, 现场查 droid.pkgs() 决定。"""
    try:
        installed = {a.get("pkg") for a in droid.pkgs()}
    except Exception:
        installed = set()
    return [dict(vendor=k, label=v["label"], oem=v["oem"], pkg=v["pkg"], verified=v["verified"])
            for k, v in VENDORS.items() if v["pkg"] in installed]


def default_vendor():
    """本机可用的首个厂商助手 vendor key(discover 顺序, verified 优先); 无则 None。"""
    found = discover()
    if not found:
        return None
    found.sort(key=lambda x: not x["verified"])   # 已验证的排前
    return found[0]["vendor"]


def _find_editable():
    """当前屏第一个可编辑输入节点(droid.dump 的 edit 项, 含中心坐标); 无则 None。"""
    for el in droid.dump():                          # 非 full: edit/x/y 已无条件下发, 可编辑节点必在内
        if el.get("edit"):
            return el
    return None


def _input(text):
    """把 text 输入到当前可编辑节点: tap 聚焦该框 → 剪贴板 paste(droid 唯一文本输入原语, 原生/WebView 通用)。"""
    el = _find_editable()
    if el is not None:
        droid.tap(el["x"], el["y"], verify=False)   # paste 前先 tap 聚焦目标框(droid 输入约定)
    droid.paste(text, verify=False)                 # 回执由下游界面观察判, 免每次输入一次弃用的截图+OCR
    return True


def send_to_vendor(nl_command, vendor=None, wait=2.0, settle=1.2):
    """打开厂商助手 → 输入命令 → 发送(IME ENTER) → 返回 {ok, ui}；安全模式下需视觉交互。
    vendor 省略 → 自动选本机首个可用助手(default_vendor)。
    ok=已驱动(打开+输入+触发发送), 非"已确认执行"; 是否生效须观察实际界面，不以切换应用推断成功。
    发送键若非 IME 动作(部分助手是独立发送按钮), ENTER 不生效时由 SOP 指导 agent 看 ui/截图后 tap 发送键(键盘右下角/输入框右侧)。"""
    vendor = vendor or default_vendor()
    if not vendor:
        return {"ok": False, "error": "本机未发现已知厂商助手(若助手确已装, 先确认无障碍已开/Bus 在线); 或在 VENDORS 加一行(pkg 用 droid.pkgs('助手名') 查)"}
    v = VENDORS.get(vendor)
    if not v:
        return {"ok": False, "error": "unknown vendor %s; known=%s" % (vendor, list(VENDORS))}
    try:
        r = droid.launch(v["pkg"], wait=wait)
    except Exception as e:                       # 助手未安装/无启动入口 → 结构化错误, 不让 capability_probe 首条就崩
        return {"ok": False, "error": "launch 失败(%s 未安装?): %s" % (v["pkg"], e)}
    if droid.safe_mode():
        return {"ok": False, "needs_gui": True, "vendor": vendor,
                "hint": "已请求打开助手；请观察界面后输入并发送，尚未输入命令。"}
    # Explicit-target snapshot validates the observed window server-side.
    try:
        from jev_ui import ui_snapshot
        ui_snapshot(v["pkg"])
    except Exception as e:
        return {"ok": False, "needs_gui": True, "error": "助手界面未确认: %s" % e}
    time.sleep(settle)
    try:
        _input(nl_command)                       # 无可编辑框时 paste 会抛 → 落此返回结构化错误(失败半径大者显式暴露)
    except Exception as e:
        return {"ok": False, "error": "输入失败(无可编辑框?): %s" % e, "ui": droid.dump()}
    time.sleep(0.4)
    try:
        ui_snapshot(v["pkg"])
        droid.key("ENTER")                      # 只发送一次，结果交由界面确认
    except Exception as e:
        return {"ok": False, "needs_gui": True, "error": "发送未确认: %s" % e,
                "hint": "不要自动重发；先观察当前输入框和助手回复。"}
    time.sleep(settle)
    return {"ok": True, "vendor": vendor, "verified": False, "ui": droid.dump()}


def send_to_aicy(cmd, **kw):
    """魅族 Aicy 便捷封装(真机已验证的样例机型)。其它机型用 send_to_vendor(cmd) 自动选或显式指定 vendor。"""
    return send_to_vendor(cmd, vendor="aicy", **kw)


def open_agent_store(vendor=None):
    """打开厂商智能体商店(如该 OEM 有), 用于浏览/创建可唤起技能。"""
    vendor = vendor or default_vendor()
    if vendor not in VENDORS:
        return {"ok": False, "error": "未知或本机无可用 vendor: %s" % vendor}
    store = VENDORS[vendor].get("store")
    if not store:
        return {"ok": False, "error": "vendor %s 无智能体商店" % vendor}
    droid.launch(store, wait=2.0)
    return {"ok": True, "ui": droid.dump()}


def capability_probe(vendor=None, commands=None):
    """只读探测: 逐条请求系统类命令，记录执行回执；结果需界面确认。不做支付/删除/发送等危险动作。
    返回 [{cmd, ok, needs_gui}], 供 onboarding 能力地图与 vendor profile 回填。vendor 省略=自动选。"""
    vendor = vendor or default_vendor()        # 一次解析: 整轮探针锁定同一助手, 避免每条命令重扫 pkgs + 跨行漂移
    commands = commands or ["打开系统设置", "打开计算器", "打开相机", "查看天气"]
    out = []
    for c in commands:
        r = send_to_vendor(c, vendor=vendor)
        out.append({"cmd": c, "ok": r.get("ok"), "needs_gui": r.get("needs_gui", False)})
        if not r.get("ok"):
            break
        time.sleep(0.6)
    return out
