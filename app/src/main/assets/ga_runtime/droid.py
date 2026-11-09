# -*- coding: utf-8 -*-
"""droid: GA Android 能力正典壳 (files/ga/droid.py) — agent 操作手机/本地模型的唯一入口
背后是 APK 内 HTTP 总线(127.0.0.1, 默认 18765), 不要绕过本模块拼 HTTP。
服务状态唯一判据 = droid.ping()。bus_port.txt 是内部实现且 code_run cwd=temp 相对路径看不到它,
禁止用文件存在性判断服务状态; ping 不通=总线组件未监听(重启 App 恢复), 与 agent/会话是否运行无关。
红线四则(完整规程=../memory/phone_use.md, 操作手机前必读):
  ①坐标唯一来源=dump/ui_detect; VLM(视觉大模型)只用于语义理解/认第几个, 其返回的任何坐标一律禁用
    (VLM 认目标→ui_detect 定位 bbox→tap 中心; ui_detect 漏检时用 ocr 文字框定位, 再不行 ask_user, 禁用 VLM 坐标兜底)。
  ②paste 后看返回: hit=True=已确认上屏; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级;
    ime_label 仅为元数据, 只有 ime_hint 可点击; hit=False 且无 uncertain 才按 hint 递进。
  ③一步一验: 一个操作→短暂等待→dump/shot 验新状态; 无变化立即停下诊断, 禁盲目重试、禁把多步决策写进一个大脚本。
  ④顶部(状态栏下~400px)点击防劫持: 重新 dump/shot 后立即 tap; tap 后前台变成非预期 App→立即 back 撤出。
用法:
    import droid
    droid.ping()                    # {ver, a11y, rot:旋转0..3, w/h:物理屏宽高, loaded}; GA 状态浮窗触摸穿透, 不拦截点击
    els = droid.dump()              # 屏幕元素 [{t,d,x,y,click,edit,...}], full=True 含全部节点
    droid.find('好评优先')           # 按 t/d 子串找节点(exact=True 全等; clickable=True 只要可点), 每项带中心 x,y —— 别再手写列表推导
    droid.tap_text('好评优先')       # find→唯一命中→tap; 多命中抛 ValueError 列候选(用 exact/idx), 0 命中抛 LookupError(转 look())
    dets = droid.look()             # 视觉一步: shot+ui_detect, 每项带中心 x,y/label/cls; dump 为空(自绘/敏感)时用它, 不要 print 整个图像数组
    droid.look(roi='top')           # 只检测上 1/3 屏(排序条/搜索框在上面时): 耗时随面积降; roi 也可 'upper'|'middle'|'lower'|'bottom' 或 (x1,y1,x2,y2); 屏幕没变时自动返回缓存('cached':True)
    w, h = droid.screen()           # 当前朝向屏幕尺寸; 位置判断用比例(顶栏 <0.12h, 底栏 >0.9h), 绝不把绝对坐标写进记忆
    droid.tap(x, y); droid.swipe(x1,y1,x2,y2,dur=300)  # 长按=swipe同点dur>=800(已验:弹快捷菜单); swipe端点已自动夹进安全带避开系统手势区
    droid.scroll_view('down')       # 安全滚动, 参数=浏览方向('down' 看下方内容/'up' 看上方); 必须检查 scrolled/evidence/uncertain; uncertain=True=观察不可用/结论不确定, 不是已验证未滚动, 禁盲目重试 (旧 scroll() 参数是手指方向, 与此相反)
    droid.back(); droid.home()
    droid.panel('right')            # 物理下拉控制中心(录屏/手电等磁贴; left/center=通知栏)。droid.quick_settings()/notifications()=AOSP 语义全局动作(部分 OEM 够不到控制中心→用 panel)
    droid.dismiss_shade()           # 用完快捷设置/通知栏必调: 确定性收起面板(Android16 上 home() 可能留下透明面板层吃掉后续所有 tap)
    droid.paste('文本')             # 剪贴板输入; hit=True=已确认上屏; hit=False, uncertain=True 时禁止重复输入或盲目降级
    droid.key('ENTER')              # 对聚焦输入框触发IME动作(搜索/发送/换行); droid.launch('包名') 启动app
    img = droid.shot()              # BGR ndarray; droid.shot('/sdcard/a.png') 存文件
    els = droid.ui_detect(img)      # Android专调YOLO(21类)+OCR [{bbox,type:'icon'|'text',label,cls,confidence}]; cls=控件语义(Icon/Image/EditText/Switch/TextButton/Toolbar/Bottom_Navigation/Card...), 无文字图标的label回退为cls
    res = droid.ocr(img)            # [(box4x2, text, score), ...]
    droid.sensitive_status()        # 微信 act="gui": 截图/识别/手势，无固定次数预算；不得读节点、节点输入或快捷回复
    droid.sensitive_unlock(pkg, actions=20, reason="...")  # 仅兼容旧 locked 策略；微信 GUI 无需调用
    droid.sensitive_env_report()    # 只读环境自检: root/LSPosed/VPN 等会被微信计分的信号 + 用户侧建议; 用户问"为什么被风控/怎么防封"时先给这个
    droid.sensitive_risk_event(pkg, kind='verify|kicked|captcha', note='…')  # 屏幕上认出实名核验/账号状态异常/安全验证时**必调**再终止任务: 该 App 进入 7 天零注入冷却(unlock 也拒)
输入三则: ①任何输入一律 paste(剪贴板), 没有逐键打字 API。最优路径=tap聚焦→paste(text)→读返回:
  hit=True=已确认上屏, 无需再 dump/shot 验; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级;
  ime_label 仅为元数据, 只有 ime_hint 可点击; hit=False 且无 uncertain 才按 hint 递进(细则=phone_use.md §3)。
  ②替换/清空: 长按输入框(swipe同点dur>=800)→弹全选菜单→全选, 然后 paste 覆盖即替换; 清空则全选后 tap 软键盘退格键。
  ③软键盘按键靠 shot+ui_detect 找: 符号键 OCR 常误标(退格⌫可能标成'X', 回车/搜索🔍可能标成'O'), 勿信标签;
    按位置找: 退格在字母区右缘, 回车/搜索/发送在键盘右下角(图标随场景变), 各厂商键盘布局不同, 以当帧检测为准。
ONNX: 任意模型 -> droid.ort_shim() 后 import onnxruntime 照常写, 推理在 APK 内 ORT 执行。
ADB(本机自连无线调试, 补 A11y 外 shell 能力): 用户手动开无线调试后 → droid.adb_pair(code,port)(仅首次) → droid.adb_connect()(无参, 端口自动发现) → droid.adb_shell('input tap 500 800' | 'am start ...' | 'dumpsys ...')。
定时唤起 agent(非用户起床铃): droid.alarm_set(id, at_ms, every_ms=0, prompt) / alarm_list() / alarm_del(id)。
  仅当目标是「到点让 GA 后台跑一段任务/新会话」时用; 用户说「设个闹钟/几点叫我」→走系统时钟 App(GUI), 不要用本 API。
  at=下次 epoch ms; every=0 一次, >0 周期 ms; 到期 call_once(prompt) 新会话进抽屉。
  例: import time; droid.alarm_set('daily_brief', int(time.time()*1000)+3600_000, every=86400_000, prompt='汇总未读通知并简报')
"""
import json
import os
import re
import struct
import sys
import time
import requests
import bus_auth
import run_guard   # 僵尸线程护栏: code_run 超时/被停后, 后台线程每次操作手机在 _act/adb_shell 被拒, 不再驱动整机

_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.join(_DIR, "models", "ui_detect_v1")  # 管线py+onnx 捆绑目录
class _BusSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs['headers'] = {**kwargs.get('headers', {}), **bus_auth.headers(url)}
        kwargs['proxies'] = {'http': None, 'https': None}
        kwargs['allow_redirects'] = False
        return super().request(method, url, **kwargs)

_SESSION = _BusSession()
_SESSION.trust_env = False


def _is_pc():
    return os.name == "nt" or not _DIR.startswith("/data/")


def _remote_model_path(model_path):
    """PC 调试时把本机模型路径映射到当前 APK 默认私有目录；手机端保持原样。"""
    if not _is_pc():
        return str(model_path)
    name = os.path.basename(str(model_path).replace("\\", "/"))
    if not name:
        raise ValueError("empty model path")
    return "/data/user/0/" + os.environ.get("GA_PACKAGE", "io.github.shenhaostu.gagent") + "/files/ga/models/ui_detect_v1/models/" + name


_PORT_DEFAULT = "18765"   # BusServer.kt PORT 常量; bus_port.txt 只是它的落盘提示, ping 才是服务真值

def _base():
    """总线地址。bus_port.txt(Kotlin 绑定成功后写)缺失 ≠ 服务未启动(绑定失败静默/文件被清):
    回退默认端口并 ping 验活(校验 ver 字段防撞他人服务); 验活失败给精准诊断, 杜绝「核心服务未启动」误判。"""
    try:
        with open(os.path.join(_DIR, "bus_port.txt")) as f:
            port = f.read().strip()
    except OSError:
        port = ""
    if port.isdigit():
        return "http://127.0.0.1:" + port
    else:   # 缺失/空串/损坏(非原子写截断窗口)统一走回退+验活
        base = "http://127.0.0.1:" + _PORT_DEFAULT
        try:
            j = _SESSION.get(base + "/ping", timeout=3).json()
            if isinstance(j, dict) and "ver" in j:
                return base
        except Exception:
            pass
        raise RuntimeError("APK 内设备总线未监听(bus_port.txt 缺失且默认端口 " + _PORT_DEFAULT + " ping 不通): "
                           "进程内 HTTP 组件绑定失败, 重启 App 即恢复。这与 agent/会话是否运行无关, "
                           "不存在『启动核心服务』按钮, 勿引导用户寻找。")


def _check(r):
    if r.headers.get("content-type", "").startswith("application/json"):
        j = r.json()
        if isinstance(j, dict) and "error" in j:
            raise RuntimeError(j["error"])
        return j
    return r.content


def _get(path, **params):
    run_guard.check()   # 只读入口(ping/dump/shot/onnx); 加检查点让僵尸线程的读屏循环也尽早自毁省资源(无副作用但止损)
    return _check(_SESSION.get(_base() + path, params=params, timeout=60))


def ping():
    """设备/服务状态；不提供前台应用身份。兼容旧 APK 时也丢弃旧包名字段。"""
    status = dict(_get("/ping"))
    status.pop("pkg", None)
    status.pop("fg", None)
    return status

_SELF_PKG = os.environ.get("GA_PACKAGE", "io.github.shenhaostu.gagent")

# Visual-only packages never expose UI trees. GUI tasks have no per-app action quota;
# cancellation and observed account/security challenges still stop execution.
SENSITIVE_APPS = {
    "com.tencent.mm": {"dump": "blank", "act": "gui"},
}
# 安全模式(暂无界面): 全局只走图像——不读控件树(dump/find 返回 [], paste 只放剪贴板走 GUI 粘贴,
# paste/scroll 只用截图验证), 不用节点动作键 key()。点击/滑动仍是坐标手势。运行时可直接 droid.SAFE_MODE = True。
SAFE_MODE = os.environ.get("GA_SAFE_MODE", "1").strip().lower() not in ("0", "false", "off", "no")   # 默认开启; 设置项关闭时宿主传 GA_SAFE_MODE=0
_SAFE_POLICY = {"dump": "blank", "act": "gui"}

def safe_mode():
    return bool(SAFE_MODE)

SENSITIVE_PKGS = frozenset(SENSITIVE_APPS)   # 派生兼容量(勿手编辑): 供按包名判定处使用, 清单只在 SENSITIVE_APPS 维护

_STRICTEST = {"dump": "blank"}   # fail-closed: 前台未解析按最严策略——漏判=读树=封号, 误判仅多走一次视觉路径
                                 # (只锁 dump 不锁 act: 刚 launch 后前台常短暂未解析, 若也锁注入会把所有 App 的首次 tap 打断)

# --- 零注入门禁(act="locked") ---
_INJECT_OPS = frozenset({"tap", "swipe", "paste", "key", "panel", "quicksettings", "notifications", "clipboard"})
_UNLOCK_FILE = os.path.join(_DIR, "temp", ".sensitive_unlock.json")
_UNLOCK_TTL = 1800  # 有限任务窗口；新任务不得复用先前授权，预算不是规避服务方风控的保证

def _unlock_read():
    try:
        with open(_UNLOCK_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _unlock_write(state):
    try:
        os.makedirs(os.path.dirname(_UNLOCK_FILE), exist_ok=True)
        with open(_UNLOCK_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception:
        pass

_RISK_FILE = os.path.join(_DIR, "temp", ".sensitive_risk.json")
_RISK_COOLDOWN_S = 7 * 86400   # 风控事件后的零注入冷却期(SOP §3.5「≥7 天」落代码)

def sensitive_risk_event(pkg, kind="verify", note=""):
    """记录一次风控事件(实名核验页 / 「账号状态异常」踢下线 / 安全验证)。记录后该 App 进入 7 天零注入冷却:
    sensitive_unlock 直接拒绝(即使用户同意也不放行——上一次同意的后果就是踢下线), 只能只读。
    agent 在屏幕上认出 §2.1 的风控信号时**必须**调本函数再终止任务; 用户重登不会清除冷却(重登本身也是计分项)。"""
    st = _risk_read()
    st[pkg] = {"kind": str(kind)[:32], "note": str(note)[:80], "ts": time.time()}
    try:
        os.makedirs(os.path.dirname(_RISK_FILE), exist_ok=True)
        with open(_RISK_FILE, "w", encoding="utf-8") as f: json.dump(st, f, ensure_ascii=False)
    except Exception: pass
    _unlock_write({k: v for k, v in _unlock_read().items() if k != pkg})   # 同时作废现有解锁
    _track("droid_sensitive_risk", {"kind": str(kind)[:32]})
    return {"pkg": pkg, "cooldown_until": st[pkg]["ts"] + _RISK_COOLDOWN_S}

def _risk_read():
    try:
        with open(_RISK_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def _risk_cooldown_left(pkg):
    t = (_risk_read().get(pkg) or {}).get("ts", 0)
    return max(0.0, t + _RISK_COOLDOWN_S - time.time()) if t else 0.0

def sensitive_unlock(pkg, actions=None, reason=""):
    """为用户明确要求的当前 GUI 任务授予有限动作预算；上限由策略表定义，有效 30 分钟。
    用户的明确任务指令允许导航，不要求先人工停在目标页。一个任务只解锁一次，用完即止，不续杯。
    这不授权发送、提交订单或支付；这些动作仍遵守任务授权边界。返回 {pkg, actions, until}。
    未入册或未上锁的 App 调本函数是 no-op(返回 {}), 勿把它当通用开关。该 App 处于风控冷却期(sensitive_risk_event 后 7 天)时抛错。"""
    pol = SENSITIVE_APPS.get(pkg, {})
    if pol.get("act") != "locked":
        return {}
    left = _risk_cooldown_left(pkg)
    if left > 0:
        raise RuntimeError(f"{pkg} 处于风控冷却期(上次风控事件后 7 天零注入, 还剩 {int(left // 3600)} 小时): 不放行任何注入, 即使用户同意。"
                           f"只能 shot()+ocr 只读; 需要操作请用户本人手动完成。")
    cap = int(pol.get("budget", 3))
    n = cap if actions is None else max(1, min(int(actions), cap))
    st = _unlock_read()
    st[pkg] = {"left": n, "until": time.time() + _UNLOCK_TTL, "last_ts": 0.0, "reason": str(reason)[:80]}
    _unlock_write(st)
    _track("droid_sensitive_unlock", {"actions": n})   # 只记数量, 不记包名/理由
    return {"pkg": pkg, "actions": n, "until": st[pkg]["until"]}

def sensitive_env_report():
    """只读的设备环境风控自检(给用户看, 不做任何修改): 列出微信这类 App 会计分的环境信号——root 管理器/LSPosed 类模块管理器是否在装,
    VPN 是否在跑, 无线调试是否开着, GA 悬浮窗权限。结论只描述事实 + 建议(排除微信走代理/对微信隐藏 root 模块 等), 由用户决定。
    实现只用 pkgs()(启动器列表)与 ping(), 不读任何第三方 App 数据。GA 端的视觉操作策略已在代码里, 本函数补的是「用户侧看得见」。"""
    try: apps = {a.get("pkg", "") for a in pkgs()}
    except Exception: apps = set()
    ROOT_MGRS = {"com.rifsxd.ksunext": "KernelSU Next", "me.weishu.kernelsu": "KernelSU", "com.topjohnwu.magisk": "Magisk", "io.github.a13e300.ksuwebui": "KSU WebUI"}
    HOOK_MGRS = {"org.lsposed.manager": "LSPosed", "org.frknkrc44.hma_oss": "HMA(隐藏应用列表)", "com.close.hook.ads": "AdClose", "de.robv.android.xposed.installer": "Xposed"}
    VPN_APPS = {"com.follow.clash": "FlClash", "com.github.kr328.clash": "Clash", "com.v2ray.ang": "v2rayNG", "com.wireguard.android": "WireGuard", "org.getlantern.lantern": "Lantern", "com.saily.android": "Saily(eSIM)"}
    found = lambda m: [v for k, v in m.items() if k in apps]
    report = {"root_managers": found(ROOT_MGRS), "hook_managers": found(HOOK_MGRS), "vpn_apps": found(VPN_APPS),
              "locked_apps": sorted(p for p, pol in SENSITIVE_APPS.items() if pol.get("act") == "locked")}
    advice = []
    if report["root_managers"]: advice.append("root 管理器在装: 对微信开「卸载模块/不授权」, 并在管理器里把微信加入排除列表")
    if report["hook_managers"]: advice.append("LSPosed/Xposed 类在装: 作用域移除微信; 用 HMA 对微信隐藏管理器本身")
    if report["vpn_apps"]: advice.append("VPN/代理在装: 分应用代理把 com.tencent.mm 排除(直连, 出口=SIM 归属地)")
    advice.append("风控事件(实名核验/账号状态异常)后 ≥7 天不对该 App 做任何注入; 重登后 ≥72h 只读")
    report["advice"] = advice
    report["note"] = "以上仅列已装 App 名(启动器可见), 不读取其数据; GA 侧对策(零注入门禁/不叠悬浮窗)已在代码内生效"
    return report


def sensitive_status(pkg=None):
    """查看零注入门禁状态: {pkg: {left, until_s}}; pkg=None 列全部已入册 locked App。"""
    st = _unlock_read(); now = time.time(); out = {}
    for p, pol in SENSITIVE_APPS.items():
        if pol.get("act") != "locked" or (pkg and p != pkg): continue
        t = st.get(p) or {}
        live = t and t.get("until", 0) > now and t.get("left", 0) > 0
        out[p] = {"locked": True, "left": int(t.get("left", 0)) if live else 0,
                  "until_s": int(t.get("until", 0) - now) if live else 0, "budget": pol.get("budget"), "min_gap": pol.get("min_gap"),
                  "risk_cooldown_h": int(_risk_cooldown_left(p) // 3600)}
    return out

def _gate_injection(op, pkg=None):
    """注入动作唯一门禁: 目标 App(默认=当前前台; 通知回复等旁路传入目标包名)是 act="locked" 时, 无解锁/超时/预算耗尽一律
    抛错(不重试、不降级); 放行时扣预算、补足 min_gap 间隔。返回 (pkg, policy); 非锁定目标返回 ("", {})。
    覆盖面 = a11y 注入(_act) + 通知 RemoteInput 回复(reply_notification) + shell input 注入(adb_shell): 三条能"替用户对该 App 说话/按键"
    的路径共用一道门, 否则门禁只堵 a11y 就是在鼓励绕道。"""
    if SAFE_MODE and op == "key":
        raise RuntimeError("安全模式只走图像：请截图定位并点击画面上的发送/搜索键，不使用节点动作键")
    if pkg is None:
        # No inferred app identity. A recorded security challenge blocks untargeted
        # injection rather than silently bypassing the affected app's cooldown.
        if any(_risk_cooldown_left(p) > 0 for p in _risk_read()):
            raise RuntimeError("已记录账号/安全验证，无法确认当前操作目标，请停止并由用户处理")
        if any(p.get("act") == "locked" for p in SENSITIVE_APPS.values()):
            raise RuntimeError("存在受保护应用，未确认操作目标，拒绝自动注入")
        pkg = ""
    pol = SENSITIVE_APPS.get(pkg, {}) if pkg else {}
    if pol.get("act") == "gui":
        if op in ("reply_notification", "key"):
            raise RuntimeError("纯 GUI 模式：请点击画面上的发送/搜索键，不调用节点或通知接口")
        if _risk_cooldown_left(pkg) > 0:
            raise RuntimeError("该 App 已记录账号/安全验证，请停止操作并由用户处理")
        return pkg, pol
    if pol.get("act") != "locked":
        return "", {}
    st = _unlock_read(); t = st.get(pkg) or {}
    now = time.time()
    if not t or t.get("until", 0) < now or t.get("left", 0) <= 0:
        why = "未解锁" if not t else ("解锁已过期" if t.get("until", 0) < now else "本次解锁预算已用完")
        _track("droid_sensitive_block", {"op": op})
        raise RuntimeError(
            f"{pkg} GUI任务预算不可用({why})，不能执行 {op}。只读请用 shot()+ocr。"
            f"若尚未授权且用户已明确要求当前任务，可调用 droid.sensitive_unlock('{pkg}', actions=20, reason='用户当前任务')，"
            f"上限 {pol.get('budget', 40)} 次/30分钟；已耗尽或过期则停止，不能续杯。每步截图确认新状态，"
            f"命中任何验证/实名/『账号状态异常』页立即终止整个任务并交人, 绝不填、绝不重试。")
    gap = float(pol.get("min_gap", 0) or 0)
    wait = gap - (now - float(t.get("last_ts", 0) or 0))
    if 0 < wait < gap:
        time.sleep(wait)
    t["left"] = int(t.get("left", 0)) - 1; t["last_ts"] = time.time(); st[pkg] = t
    _unlock_write(st)
    _track("droid_sensitive_act", {"op": op, "left": t["left"]})
    return pkg, pol

def _app_policy(pkg=None):
    """Explicit target policy, or a node-access permission (never an app identity)."""
    if SAFE_MODE:
        return _SAFE_POLICY
    if pkg is not None:
        return SENSITIVE_APPS.get(pkg, {}) if pkg else _STRICTEST
    try:
        policy = _get("/a11y/policy")
        if policy.get("visual_only") is False:
            return {}
    except Exception:
        pass
    return _STRICTEST


def _visual_only(pkg=None):
    return _app_policy(pkg).get("dump") == "blank"


def dump(full=False):
    if _visual_only():
        return []
    return _get("/a11y/dump", **({"full": 1} if full else {}))


def _record_path(kind):
    """任务级路径计数(挂 analytics_hook._STATE, 随 agent_task_end 扁平上报)。
    惰性 import + 全吞异常: PC 侧调试无 plugins 包也不报错。只报类别枚举, 不报包名/坐标。"""
    try:
        from plugins.analytics_hook import record_path
        record_path(kind)
    except Exception:
        pass


def _act(**body):
    run_guard.check()   # 操作手机(tap/swipe/paste/launch...)唯一入口 → 僵尸线程护栏检查点: 已取消则抛 RunCancelled 自毁
    op = body.get("op")
    if op in _INJECT_OPS:
        _gate_injection(op)                     # 零注入门禁(act="locked" 的敏感 App): 未解锁/超预算直接抛错, 放行则已扣预算+补足节奏下限
                                                # 不在这里改动作形态(不加抖动/不拟人化, phone_use §5): 防封靠"少做+先问+硬预算", 不靠伪装
    _record_path("launch" if op == "launch" else "a11y")   # 任务路径归属: 拉起 app vs 无障碍操作外部 app
    run_guard.check()   # 门禁可能等待；取消后不得再派发。
    return _check(_SESSION.post(_base() + "/a11y/act", json=body, timeout=30))


def _track(event, props=None):
    """埋点入 agent 事件队列(temp/.agent_events.jsonl), Kotlin Analytics 排空时统一补身份+脱敏上报。
    只记枚举/数值, 绝不写屏幕内容/坐标以外信息; 任何失败静默——埋点不允许影响操作本身。"""
    try:
        d = os.path.join(_DIR, "temp")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, ".agent_events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"event": event, "props": props or {}, "ts": int(time.time() * 1000)}) + "\n")
    except Exception:
        pass


def _diff_pct(a, b):
    import cv2
    if a is None or b is None or a.shape != b.shape: return 100.0
    d = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return float((d > 12).mean() * 100.0)


def _img_diff_str(before, after):
    import cv2, numpy as np
    if before is None or after is None or before.shape != after.shape: return "diff: n/a"
    d = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
    mask = d > 12; cnt = int(mask.sum()); pct = cnt * 100.0 / (int(mask.size) or 1)
    if not cnt: return "diff: 0.000%"
    ys, xs = np.where(mask); bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    return "diff: %.3f%% bbox=%s" % (pct, bbox)


def _screen_geometry(info):
    geometry = {key: int(info[key]) for key in ('w', 'h', 'rot')}
    if geometry['w'] <= 0 or geometry['h'] <= 0 or geometry['rot'] not in range(4):
        raise ValueError('invalid screen geometry')
    return geometry


def _gesture_screen(info, points, expected=None):
    current = _screen_geometry(info)
    if expected is not None and _screen_geometry(expected) != current:
        raise RuntimeError('screen geometry changed; capture and locate the target again')
    for x, y in points:
        if not (0 <= x < current['w'] and 0 <= y < current['h']):
            raise ValueError('coordinate outside the current screen')
    return current


def capture(q=None):
    """Explicit image + screen observation; pass its screen to tap/swipe after locating a target."""
    before = _screen_geometry(ping())
    img = shot(q=q)
    after = _screen_geometry(ping())
    if before != after:
        raise RuntimeError('screen geometry changed during capture; capture again')
    if img is None or img.shape[:2] != (before['h'], before['w']):
        raise RuntimeError('screenshot geometry does not match the display')
    return {'image': img, 'screen': before}


def tap(x, y, verify=True, wait=1.0, human=False, *, screen=None):
    """human=True only adds small motor-tolerance jitter; it is not an anti-abuse bypass.
    Sensitive apps must use state-driven waits and stop on security checks."""
    geometry = _gesture_screen(ping(), [(x, y)], screen)
    before = shot(q=60) if verify else None   # JPEG ~0.2s vs PNG ~0.4s; 同质量对比, diff 不受压缩影响
    ret = _act(op="tap", x=int(x), y=int(y), human=bool(human), expected_screen=geometry); ret.pop("ok", None)
    if not verify: return ret
    # 点中后动画~100ms内开始: 等0.3s截一帧, 有变化即返回; 无变化再补帧直到 wait(旧行为死等 wait)
    t0 = time.time(); time.sleep(min(0.3, wait))
    after = shot(q=60)
    while time.time() - t0 < wait and not _shape_changed(before, after) and _diff_pct(before, after) < 0.05:
        after = shot(q=60)
    ret["waited"] = round(time.time() - t0, 2)
    ret["note"] = "tap已内置等待画面变化, 直接look/下一步, 勿再sleep"
    diff = _img_diff_str(before, after); ret["diff"] = diff
    if _shape_changed(before, after):
        ret.update(verified=False, uncertain=True, hint='屏幕尺寸变化；重新截图定位，不复用旧坐标。')
        return ret
    try: pct = float(diff.split("%", 1)[0].split()[-1])
    except Exception: pct = 0.0
    if pct < 0.05:
        ret["hint"] = "tap后屏幕变化很小；可能点到非热区，或前台有弹窗/浮层导致后层页面不响应。请看截图/diff后再重试。"
        _track("droid_tap_miss", {"diff_pct": round(pct, 3)})   # 只在验证失败时上报(自限量): 手机操控版"中止率", 与 a11y_act_stats 的 tap 总数配对算命中率
    return ret


def swipe(x1, y1, x2, y2, dur=300, *, screen=None):
    geometry = _gesture_screen(ping(), [(x1, y1), (x2, y2)], screen)
    return _act(op="swipe", x1=int(x1), y1=int(y1), x2=int(x2), y2=int(y2), dur=int(dur), expected_screen=geometry)


# ---------------- 定位便捷层(v2.33): 把 agent 每轮手写的「dump→列表推导→取中心」收成三个纯函数, 少写代码=少报错少浪费轮 ----------------
def find(text="", exact=False, clickable=None, edit=None, nodes=None):
    """按文本找节点: 在 dump()(或传入 nodes)里匹配 t(文本)/d(描述), 子串匹配, exact=True 全等; clickable/edit=True|False 过滤.
    返回节点列表, 每项含中心 x,y 可直接 tap. 敏感 App 前台 dump 为 [] → 返回 [](走 look())."""
    ns = dump() if nodes is None else nodes
    out = []
    for n in ns:
        t, d = n.get("t") or "", n.get("d") or ""
        if text and not ((text == t or text == d) if exact else (text in t or text in d)): continue
        if clickable is not None and bool(n.get("click")) != bool(clickable): continue
        if edit is not None and bool(n.get("edit")) != bool(edit): continue
        out.append(n)
    return out


def tap_text(text, exact=False, idx=None, clickable=None, **tap_kw):
    """find(text) → tap 命中节点中心. 唯一性断言(phone_use #9): 多个命中且未给 idx → 抛 ValueError 并列出候选, 绝不点"大概是它";
    0 命中 → 抛 LookupError(提示改 look() 视觉路径). 返回 tap() 的结果(含 diff/fg)."""
    hits = find(text, exact=exact, clickable=clickable)
    if not hits:
        raise LookupError(f"tap_text: 没有节点匹配 {text!r}; 先 print(droid.find(''))看全表, 或前台是自绘/敏感 App → droid.look()")
    if idx is None and len(hits) > 1:
        cands = "; ".join(f"[{i}] t={h.get('t')!r} d={h.get('d')!r} @({h.get('x')},{h.get('y')})" for i, h in enumerate(hits[:8]))
        raise ValueError(f"tap_text: {len(hits)} 个节点匹配 {text!r}: {cands} → 用 exact=True 或 idx=")
    h = hits[idx or 0]
    return tap(h["x"], h["y"], **tap_kw)


_LOOK_CACHE = {"thumb": None, "roi": None, "dets": None}


class LookResult(list):
    """look() 返回值: 普通 list(元素同前) + .gone = 上次 look 有、这次没了的元素(弹窗关闭/按钮消失)."""
    gone = ()


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _diff_order(dets, prev, H, area=None, selfs=()):
    """与上次 look 对比: 同位置(IoU>=0.5)且同文字=未变, 否则 new=True. 新/变化的排前, 组内从上到下.
    area: 两次 roi 的重叠区(x1,y1,x2,y2); 只在重叠区内比较, 区外元素既不算新也不算消失(上次没看那里).
    selfs: GA 自己悬浮层矩形; 中心落入的元素标 self=True, 恒视为未变(胶囊文字每步都变, 不能挤到前面).
    状态栏(顶部 4%)恒视为未变, 避免时钟/图标 OCR 抖动挤到前面. 无基准(prev=None)→全部 new, 即纯从上到下."""
    sq = lambda s: "".join(str(s or "").split())
    bar = H * 0.04
    inside = lambda d, r: r[0] <= d["x"] < r[2] and r[1] <= d["y"] < r[3]
    def same(d, p): return sq(d["label"]) == sq(p["label"]) and _iou(d["bbox"], p["bbox"]) >= 0.5
    for d in dets:
        if any(inside(d, r) for r in selfs): d["self"] = True
    skip = lambda d: d["y"] < bar or d.get("self") or (area is not None and not inside(d, area))
    if prev is not None:
        prev = [p for p in prev if not skip(p) and not any(inside(p, r) for r in selfs)]
    for d in dets:
        d["new"] = False if (prev is not None and skip(d)) or d["y"] < bar or d.get("self") \
            else (prev is None or not any(same(d, p) for p in prev))
    gone = [] if prev is None else [dict(p, new=False) for p in prev if not any(same(d, p) for d in dets)]
    out = LookResult(sorted(dets, key=lambda d: (not d["new"], bool(d.get("self")), d["y"], d["x"])))
    out.gone = sorted(gone, key=lambda d: (d["y"], d["x"]))
    return out
_ROI_NAMES = {"top": (0, 0, 1, 0.34), "upper": (0, 0, 1, 0.5), "middle": (0, 0.25, 1, 0.75), "lower": (0, 0.5, 1, 1), "bottom": (0, 0.66, 1, 1)}


def _matching_labels(detections, label):
    return detections if not label else [d for d in detections if label in d["label"]]


def look(conf=0.25, path=None, roi=None, cache=True, *, label=None):
    """视觉路径一步到位: shot()+ui_detect(). 返回检测列表, 每项附中心 x,y(整屏坐标, 可直接 tap), label=OCR 文字, cls=控件语义.
    label: 可选 OCR 文字子串筛选，返回全部匹配项；多命中仍需消歧，不自动选择或点击。
    roi: 只检测屏幕的一部分 —— 'top'|'upper'|'middle'|'lower'|'bottom', 或 (x1,y1,x2,y2)(像素, 或 0~1 的比例). 知道目标在哪(排序条在上半屏/底栏在下方)
         就传 roi, 耗时按面积成比例下降(整屏 OCR 是主要成本, 自绘 App 整屏 look 约 6-8s).
    cache: 屏幕与上一次 look 几乎没变(缩略图差异 <0.3%) 且 roi 相同 → 直接返回上次结果(附 'cached': True), 不再跑模型. 刚做完动作想确认变化时它就是证据.
    排序: 与上一次 look 对比(roi 不同则只比重叠区), new=True(新出现/文字变了)的排最前, 其余在后, 组内从上到下; .gone=消失的元素. 动作后 look 首几项就是该动作的效果.
    self=True: 元素落在 GA 自己的悬浮窗/面板上(不是目标 App 的内容, 别点也别读).
    path 给出则同时把截图存文件(给用户看/复核). dump 为空(自绘/SurfaceView/敏感置空)时用这个, 不要先 print 整个 ndarray."""
    if label is not None and not isinstance(label, str):
        raise TypeError('look label must be a string or None')
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        raise ValueError('look(conf=0.25, ...) 返回检测框，不接受问题；看图问答请用 ask_vision(droid.shot(), "问题")') from None
    if not 0 <= conf <= 1:
        raise ValueError('look conf must be between 0 and 1')
    import cv2
    import numpy as np
    img = shot()
    H, W = img.shape[:2]
    if isinstance(roi, str):
        roi = _ROI_NAMES[roi]
    if roi:
        x1, y1, x2, y2 = roi
        if max(x1, y1, x2, y2) <= 1.0:           # 比例 → 像素
            x1, y1, x2, y2 = x1 * W, y1 * H, x2 * W, y2 * H
        x1, y1, x2, y2 = int(max(0, x1)), int(max(0, y1)), int(min(W, x2)), int(min(H, y2))
    else:
        x1, y1, x2, y2 = 0, 0, W, H
    thumb = cv2.resize(cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), (36, 80), interpolation=cv2.INTER_AREA)
    c = _LOOK_CACHE
    if cache and c["dets"] is not None and c["roi"] == (x1, y1, x2, y2) and c["thumb"] is not None:
        diff = float((cv2.absdiff(thumb, c["thumb"]) > 16).mean())
        if diff < 0.003:
            import copy
            dets = copy.deepcopy(c["dets"])
            for d in dets: d["cached"] = True; d["new"] = False
            return LookResult(sorted(_matching_labels(dets, label), key=lambda d: (d["y"], d["x"])))   # 屏幕没变: 全部未变, gone 为空
    dets = ui_detect(img[y1:y2, x1:x2], conf=conf)
    for d in dets:
        d["label"] = str(d.get("label") or "")
        bx1, by1, bx2, by2 = d["bbox"]
        d["bbox"] = [bx1 + x1, by1 + y1, bx2 + x1, by2 + y1]
        d["x"], d["y"] = int((bx1 + bx2) / 2 + x1), int((by1 + by2) / 2 + y1)
    prev = area = None
    if c["dets"] is not None and c["roi"] is not None:     # 不同 roi 也比: 只比两次的重叠区
        a = (max(x1, c["roi"][0]), max(y1, c["roi"][1]), min(x2, c["roi"][2]), min(y2, c["roi"][3]))
        if a[2] > a[0] and a[3] > a[1]:
            prev, area = c["dets"], a
    try:
        selfs = [tuple(r) for r in (ping().get("overlay") or [])]   # GA 自己的悬浮层(App 端上报, 旧 APK 无此字段)
    except Exception:
        selfs = []
    dets = _diff_order(dets, prev, H, area, selfs)
    c.update(thumb=thumb, roi=(x1, y1, x2, y2), dets=[dict(d) for d in dets])
    if path:
        cv2.imwrite(path, img)
    return _matching_labels(dets, label)


def ask_vision(image_input, prompt="描述当前界面", **options):
    """Use the configured vision adapter without eager imports for non-visual tasks."""
    from vision_api import ask_vision as invoke
    return invoke(image_input, prompt, **options)


def screen():
    """(w, h): 当前朝向的屏幕像素尺寸(来自 ping). 相对布局判断用: y < 0.12h 顶栏区, y > 0.9h 底栏区; 禁止把任何绝对坐标写进记忆.
    GA 自己的悬浮胶囊/回答面板在 shot() 里已按邻近像素抹平, 不会出现在 OCR/检测结果中; 点击该区域会穿透到下方 App."""
    p = ping()
    return int(p.get("w") or 0), int(p.get("h") or 0)
def _text_change_ratio(before, after):
    before = [x for x in (before or []) if x]
    after = [x for x in (after or []) if x]
    if len(before) < 4 or len(after) < 4:
        return None
    visible = set(after)
    return sum(1 for x in before if x not in visible) / float(len(before))
def _pixel_change_pct(before, after, roi):
    import cv2
    if before is None or after is None or before.shape != after.shape:
        return None
    x1, y1, x2, y2 = roi
    a, b = before[y1:y2, x1:x2], after[y1:y2, x1:x2]
    if not a.size or not b.size:
        return None
    diff = cv2.absdiff(
        cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(b, cv2.COLOR_BGR2GRAY),
    )
    return float((diff > 12).mean()) * 100.0
def _shape_changed(base, *others):
    """证据窗内截图宽高形态是否变化(旋转/折叠会改 shape); 缺帧(None)不参与判定。"""
    return base is not None and any(
        o is not None and o.shape != base.shape for o in others
    )
def _scroll_verdict(text_ratio, first_pixel_pct, stable_pixel_pct):
    if text_ratio is not None and text_ratio > .30:
        return "text"
    if first_pixel_pct is not None and first_pixel_pct > 1.5:
        if stable_pixel_pct is not None and stable_pixel_pct > 1.5:
            return "pixel"
    return "none"
def _scroll_error(stage, exc):
    kind = "".join(
        ch for ch in type(exc).__name__ if ch.isalnum() or ch in "_-"
    )[:48] or "Exception"
    return ("%s:%s" % (stage, kind))[:80]
def _scroll_shot():
    """Optional JPEG evidence; shot() owns capture throttling for every caller."""
    try:
        return shot(q=45)
    except Exception:
        return None


_OPPOSITE_DIRECTIONS = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _scroll_feedback(direction, result):
    """Expose gesture intent without changing the observation verdict."""
    return dict(result, finger_direction=direction, view_direction=_OPPOSITE_DIRECTIONS[direction])


def scroll_view(direction="down", **options):
    """Browse toward content: 'down' sees lower items, 'up' sees earlier items.
    Uses scroll's geometry, timing, verification and options; legacy scroll keeps finger directions.
    """
    if not isinstance(direction, str) or direction not in _OPPOSITE_DIRECTIONS:
        raise ValueError("scroll_view direction must be up/down/left/right")
    return scroll(_OPPOSITE_DIRECTIONS[direction], **options)


def scroll(direction="up", frac=0.35, dur=600, times=1, verify=True, settle=0.5):
    """安全滚动: 从本次屏幕尺寸推出居中坐标; 派发时尺寸/旋转必须仍一致, 朝 direction 滚一屏的 frac。
    direction = 手指移动方向: 'up'(看下面内容) | 'down'(看上面) | 'left' | 'right'。
    返回 finger_direction 与相反的 view_direction；它们描述本次意图，不替代 scrolled/evidence 核验。
    默认短距离、低速度，保留相邻观察的内容重叠；需要快速遍历时显式传 frac/dur。
    verify=True: 内容区像素稳态复核 + dump 文本对比(真机实测: Flyme设置/WebView 同窗滚动后 a11y 树会滞后);
    调用方必须检查 scrolled/evidence/uncertain; uncertain=True 表示观察不可用/结论不确定,
    不是已验证未滚动, 不得据此盲目重试。
    ⚠️scroll 只吃方向/比例, 不是 swipe(x1,y1,x2,y2,dur)——曾被误当 swipe 调 scroll(900,1850,900,650,700)
    致 times=650 全屏狂滑失控。下方夹取幅度/时长/次数, 任何误用都退化为少量有界滚动(要精细滑用 droid.swipe)。"""
    if direction not in ("up", "down", "left", "right"):   # 非法方向 fail-fast(误当 swipe 传坐标必命中): 不静默回退'up'再滚一堆
        raise ValueError("scroll 的 direction 必须是 'up'/'down'/'left'/'right'(看下方内容用 'up'), 收到 %r; "
                         "要按坐标精细滑请用 droid.swipe(x1,y1,x2,y2,dur)" % (direction,))
    frac = min(max(float(frac), 0.05), 1.0)      # 一屏内的滚动比例; >1 或负值(误传坐标)夹回
    dur = min(max(int(dur), 50), 3000)           # 单次滑动时长(ms)
    settle = min(max(float(settle), 0.0), 3.0)   # 每次滚动后的沉降等待(s)
    times = min(max(int(times), 1), 10)          # 单次 scroll 最多发 10 段滑动(不变量: 操作原语自我限次防失控)
    errors = []
    try:
        p = ping()
        w = int(p.get("w"))
        h = int(p.get("h"))
    except Exception as exc:
        raise RuntimeError(
            "scroll geometry precondition failed: positive ping w/h required"
        ) from exc
    if w <= 0 or h <= 0:
        raise RuntimeError(
            "scroll geometry precondition failed: positive ping w/h required"
        )
    sensitive = _visual_only()   # 统一策略漏斗(_app_policy): 敏感或前台未解析(fail-closed)→只用像素证据, 不读 a11y 树
    cx, cy = w // 2, h // 2; sv = int(h * frac) // 2; sh_ = int(w * frac) // 2
    seg = {"up": (cx, cy + sv, cx, cy - sv), "down": (cx, cy - sv, cx, cy + sv),
           "left": (cx + sh_, cy, cx - sh_, cy), "right": (cx - sh_, cy, cx + sh_, cy)}.get(direction, (cx, cy + sv, cx, cy - sv))
    seg = tuple(min(max(v, 0), (w if i % 2 == 0 else h) - 1) for i, v in enumerate(seg))
    before_txt, before_img = None, None
    if verify:
        if not sensitive:
            try:
                before_txt = [
                    n.get("t") or n.get("d") or "" for n in dump()
                ]
            except Exception as exc:
                errors.append(_scroll_error("dump_before", exc))
        before_img = _scroll_shot()
        if before_img is None:
            errors.append("shot_before:Unavailable")

    action = {}
    for _ in range(times):
        action = swipe(*seg, dur=dur, screen=p)
        # Native dispatch acknowledges acceptance before the gesture finishes.
        time.sleep(dur / 1000.0 + settle)
    if not verify:
        ret = dict(action or {})
        ret.update(performed=True, verified=False)
        return _scroll_feedback(direction, ret)

    after_txt, after_img = None, None
    if not sensitive:
        try:
            after_txt = [n.get("t") or n.get("d") or "" for n in dump()]
        except Exception as exc:
            errors.append(_scroll_error("dump_after", exc))
    after_img = _scroll_shot()
    if after_img is None:
        errors.append("shot_after:Unavailable")

    try:
        text_ratio = _text_change_ratio(before_txt, after_txt)
    except Exception as exc:
        errors.append(_scroll_error("text", exc))
        text_ratio = None
    first_pixel_pct, stable_pixel_pct, stable_img = None, None, None
    try:
        ih, iw = before_img.shape[:2]
        roi = (0, max(48, int(ih * .05)), iw,
               min(ih - 60, int(ih * .94)))
        first_pixel_pct = _pixel_change_pct(before_img, after_img, roi)
    except Exception as exc:
        errors.append(_scroll_error("pixel_first", exc))

    evidence = _scroll_verdict(text_ratio, first_pixel_pct, None)
    stable_unavailable = False
    if evidence == "none" and first_pixel_pct is not None and first_pixel_pct > 1.5:
        time.sleep(.4)
        stable_img = _scroll_shot()
        if stable_img is None:
            errors.append("shot_stable:Unavailable")
            stable_unavailable = True
        else:
            try:
                stable_pixel_pct = _pixel_change_pct(
                    before_img, stable_img, roi
                )
            except Exception as exc:
                errors.append(_scroll_error("pixel_stable", exc))
            if stable_pixel_pct is None:
                errors.append("pixel_stable:Unavailable")
                stable_unavailable = True
        evidence = _scroll_verdict(
            text_ratio, first_pixel_pct, stable_pixel_pct
        )

    if _shape_changed(before_img, after_img, stable_img):
        errors.append("evidence:ShapeChanged")
        return _scroll_feedback(direction, {
            "scrolled": False,
            "evidence": "none",
            "uncertain": True,
            "error": "; ".join(dict.fromkeys(errors))[:160],
            "hint": "截图形态在证据窗内变化(旋转/折叠?)，无法判定是否滚动，请重新读取当前页面。",
        })
    if stable_unavailable:
        return _scroll_feedback(direction, {
            "scrolled": False,
            "evidence": "none",
            "uncertain": True,
            "error": "; ".join(dict.fromkeys(errors))[:160],
            "hint": "滚动稳态截图观察失败，无法确认像素变化是滚动还是回弹。",
        })
    if text_ratio is None and first_pixel_pct is None:
        error = "; ".join(dict.fromkeys(errors))[:160]
        return _scroll_feedback(direction, {
            "scrolled": False,
            "evidence": "none",
            "uncertain": True,
            "error": error or "observation:Unavailable",
            "hint": "滚动观察失败，无法判断页面是否滚动；请重新读取当前页面后再试。",
        })
    moved = evidence != "none"
    return _scroll_feedback(direction, {
        "scrolled": moved,
        "evidence": evidence,
        "hint": None if moved else
                "内容区画面与可见文本均未稳定变化: 已到底/顶, 或该 App 对合成滚动不敏感。",
    })
def _boxes(nodes, key=None):
    """full dump 节点的 bbox [[l,t,r,b],...]; key 过滤(如 'edit' 只取可编辑框)。"""
    out = []
    for n in nodes:
        if n.get("b") and (key is None or n.get(key)):
            try: out.append([int(v) for v in str(n["b"]).split(",")])
            except Exception: pass
    return out
def _match(expected, observed):
    expected, observed = str(expected).strip(), str(observed).strip()
    if expected == observed:
        return True
    return min(len(expected), len(observed)) >= 4 and (
        expected in observed or observed in expected
    )
def _is_clipboard_label(text):
    normalized = "".join(str(text).split()).casefold()
    if normalized.endswith((":", "：")):
        normalized = normalized[:-1]
    return normalized in {"来自剪贴板", "fromclipboard"}
def _classify_paste_rows(text, rows, edits, screen_h):
    """Purely classify OCR rows as edit hits or IME clipboard evidence."""
    words, hit, hint, label = [], False, None, None
    clip_top = min(
        (min(p[1] for p in box) for box, s, _ in rows
         if _is_clipboard_label(s)
         and sum(p[1] for p in box) / len(box) > screen_h * .5),
        default=None,
    )
    for box, observed, score in rows:
        cx = sum(p[0] for p in box) / len(box)
        cy = sum(p[1] for p in box) / len(box)
        matched = _match(text, observed)
        item = {"box": box, "text": observed, "score": float(score), "hit": matched}
        words.append(item)
        is_label = (
            _is_clipboard_label(observed) and clip_top is not None
            and min(p[1] for p in box) >= clip_top - 2
        )
        if is_label:
            label = label or {**item, "hit": False}
        if not matched:
            continue
        if any(l - 8 <= cx <= r + 8 and t - 8 <= cy <= b + 8
               for l, t, r, b in edits):
            hit = True
        elif not is_label and clip_top is not None and cy >= clip_top:
            hint = hint or item
    out = {"ocr": words, "hit": hit}
    if hint:
        out["ime_hint"] = hint
    if label:
        out["ime_label"] = label
    return out
def _ocr_region(img, x1, y1, x2, y2):
    """OCR 图像子区域；padding/过滤由 PPOCR.region 统一处理，结果还原到整图坐标。"""
    h, w = img.shape[:2]
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(w, int(x2)), min(h, int(y2))
    if x2 - x1 < 12 or y2 - y1 < 12:
        return []
    rows = _ocr_engine().region(img[y1:y2, x1:x2])
    return [
        ([[int(px) + x1, int(py) + y1] for px, py in box], text, float(score))
        for box, text, score in rows
    ]
def _paste_error(stage, exc):
    """Return bounded, non-sensitive verification error metadata."""
    kind = "".join(
        ch for ch in type(exc).__name__ if ch.isalnum() or ch in "_-"
    )[:48] or "Exception"
    return ("%s:%s" % (stage, kind))[:80]
def _try_paste_verification(stage, operation, errors, fallback=None):
    try:
        return operation()
    except Exception as exc:
        errors.append(_paste_error(stage, exc))
        return fallback
def _paste_unavailable(ret, errors, hint=None):
    error = "; ".join(dict.fromkeys(errors))[:160] or "verification:Unavailable"
    ret.update(hit=False, uncertain=True, verify="unavailable", error=error)
    warning = "验证不可用，无法确认文本是否上屏；请核对当前帧输入框，或由用户接管。"
    ret["hint"] = (hint + " " + warning) if hint else warning
    return ret
def paste(text, verify=True, replace=False):
    """剪贴板注入后立即验证：单次 dump → 编辑框识别 → 必要时区域检测。
    replace=False(默认)=在光标处追加; replace=True=先全选框内旧文本再粘贴=覆盖(预填昵称/旧搜索词/改地址一律用它, 没有退格键可用),
    此时 dump 验证按「框内文本 == text」判 hit(追加模式是包含匹配)。框不支持选区时 a11y 侧抛错(不会静默变成追加)。
    hit=True=已确认上屏; hit=False, uncertain=True=验证不可用/结论不确定, 禁止重复输入或盲目降级。
    ime_label 仅为元数据; 只有 ime_hint 可点击。
    敏感 App 或前台未解析时只设置剪贴板，不调用节点输入；返回 needs_gui_paste=True 并输出提示。
    调用方须通过可见GUI粘贴，再用截图验证上屏；不能把剪贴板已设置当成输入成功。"""
    text = str(text)
    if not text:
        raise ValueError("paste text must not be empty")
    if _visual_only():
        _act(op="clipboard", text=text)
        hint = "文本已放入剪贴板，尚未输入。输入框需已聚焦且键盘弹出：数秒内截图找键盘正上方的剪贴板提示条并点击即上屏；无提示条再长按输入框点\"粘贴\"。粘贴为追加，替换先点清空键。"
        print("[GUI input] " + hint)
        return {"hit": False, "uncertain": True, "needs_gui_paste": True, "hint": hint}
    ret = _act(op="paste", text=text, replace=bool(replace)); ret.pop("ok", None)
    if not verify:
        return ret
    _squash = lambda s: "".join(str(s).split())                    # 输入框常做格式化回显(会议号「123 456 789」、卡号分组、NBSP): 比较时去掉全部空白
    matched = (lambda observed: _squash(observed) == _squash(text)) if replace else (lambda observed: _match(text, observed))

    errors = []
    error_count = len(errors)
    if _visual_only():
        nodes = []                                       # 敏感 App/前台未解析(fail-closed): 跳过 a11y 树, 走 shot()+OCR 视觉验证
    else:
        nodes = _try_paste_verification(
            "dump", lambda: dump(full=True), errors, []
        ) or []
    dump_error = len(errors) > error_count
    for node in nodes:
        observed = node.get("t") or ""
        if node.get("edit") and matched(observed):
            ret.update(hit=True, verify="dump", text=observed)
            return ret
    if replace and any(n.get("edit") and (n.get("t") or "").strip() for n in nodes):   # 框里有字但 ≠ text: 替换没生效, 明确报 miss(不退 OCR 兜底, 否则包含匹配会把「ozerGA测试」判成命中)
        observed = next(n.get("t") for n in nodes if n.get("edit") and (n.get("t") or "").strip())
        ret.update(hit=False, uncertain=False, verify="dump", text=observed, hint="replace 未生效: 框内仍为 %r; 点框内 ✕ 清除后重试, 或交用户处理" % observed[:40])
        return ret

    def _capture():
        image = shot()
        height, width = image.shape[:2]
        if int(height) <= 0 or int(width) <= 0:
            raise ValueError("invalid image")
        return image, int(height), int(width)
    capture = _try_paste_verification("shot", _capture, errors)
    if capture is None:
        return _paste_unavailable(ret, errors)
    img, h, w = capture

    edits = _boxes(nodes, "edit")
    for l, t, r, b in edits:
        x1, y1 = max(0, l), max(0, t)
        x2, y2 = min(w, r), min(h, b)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = img[y1:y2, x1:x2]
        def _recognize():
            observed, score = ocr_text(crop)
            return observed, float(score)
        recognized = _try_paste_verification(
            "ocr_text", _recognize, errors
        )
        if recognized is None:
            continue
        observed, score = recognized
        if _match(text, observed):
            item = {
                "box": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                "text": observed,
                "score": score,
                "hit": True,
            }
            if not errors:
                ret.update(
                    hit=True, verify="recognize", text=observed, ocr=[item]
                )
                return ret

    edit_bottom = max((b[3] for b in edits), default=0)
    if edit_bottom >= h - 8:
        edit_bottom = 0
    if edits:
        band_top = edit_bottom or int(h * 0.5)
        rows = _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, band_top - 24, w, h),
            errors,
            [],
        ) or []
    else:
        band_top = int(h * 0.5)
        rows = _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, band_top - 24, w, h),
            errors,
            [],
        ) or []
        rows += _try_paste_verification(
            "ocr_region",
            lambda: _ocr_region(img, 0, 0, w, band_top),
            errors,
            [],
        ) or []

    evidence = _try_paste_verification(
        "ocr_classify",
        lambda: _classify_paste_rows(text, rows, edits, h),
        errors,
        {"ocr": [], "hit": False},
    )
    ret.update(evidence, verify="ocr")
    if errors:
        ret["hit"] = False
        ret["uncertain"] = True
    elif not edits:
        ret["hit"] = False
        ret["uncertain"] = True

    if ret["hit"]:
        return ret
    if not edits:
        cause = (
            "a11y dump 读取失败，未定位到输入框"
            if dump_error else "未定位到输入框"
        )
        hint = (
            cause + "，当前帧无法确认文本是否上屏；请提供当前帧输入框位置后重试，"
            "或由用户接管。"
        )
        if ret.get("ime_hint"):
            hint += (
                " 若已确认输入框聚焦，可 tap ime_hint['box'] 的内容框中心，再重新验证。"
            )
        elif ret.get("ime_label"):
            hint += " 当前仅见剪贴板标签，不要把 ime_label 当作内容点击。"
    elif ret.get("ime_hint"):
        hint = (
            "未上屏，但已定位键盘剪贴板内容：tap ime_hint['box'] 中心后重新验证；"
            "不要点击 ime_label。"
        )
    elif ret.get("ime_label"):
        hint = (
            "未上屏，仅识别到键盘剪贴板标签，未定位到可点击的内容；"
            "不要把 ime_label 当作内容点击，请重新聚焦输入框后再 paste。"
        )
    else:
        hint = (
            "未上屏且未见剪贴板提示条: ①重新 tap 输入框聚焦(常可唤出提示条)后再 paste 看 ime_hint; "
            "②长按输入框粘贴(键盘/面板弹起时先收起让输入框裸露——文本在剪贴板不会丢; "
            "坐标取当帧输入框 bbox 中心, 禁按在键盘键位上); "
            "③纯 ASCII 逐键打字兜底(同帧定位全部键位后连续 tap)。递进细则见 phone_use.md §3。"
        )
    if errors:
        return _paste_unavailable(ret, errors, hint)
    ret["hint"] = hint
    return ret
def key(name="ENTER"): return _act(op="key", name=name)  # IME动作键, 仅ENTER(=搜索/发送/换行, 视输入框而定)
def launch(pkg, wait=1.0):
    """请求启动应用。request_sent 仅表示启动请求已发出；opened=None 表示未验证页面是否打开。"""
    ack = _act(op="launch", pkg=pkg)
    if not isinstance(ack, dict) or ack.get("ok") not in (True, 1) or "error" in ack:
        raise RuntimeError("启动请求未获确认: %r" % (ack,))
    if wait > 0:
        time.sleep(wait)
    ret = {"request_sent": True, "opened": None,
           "hint": "启动请求已发出；是否打开尚未验证，请观察界面。"}
    if pkg in SENSITIVE_APPS:
        ret["policy"] = "sensitive: visual-only; overlay follows user preference" + (", act=locked(零注入, 见 droid.sensitive_status())" if SENSITIVE_APPS[pkg].get("act") == "locked" else "")
    return ret
def pkgs(filter=""): return _act(op="pkgs", filter=filter)["apps"]  # 列可启动app[{pkg,label}], filter模糊匹配包名/应用名如'美团'
def back(): return _act(op="back")
def home(): return _act(op="home")
def install_apk(path): return _act(op="install_apk", path=str(path))   # 装任意APK(APK工厂产物): 拉起系统安装器, 用户确认装机
def notifications(): return _act(op="notifications")    # 下拉通知栏(AOSP 语义全局动作)
def dismiss_shade(): return _act(op="dismiss_shade")    # 确定性收起通知栏/快捷设置(API31+ 全局动作; 低版本退化为 back)。用快捷设置(调亮度/开关)后必调:
                                                        # Pixel/Android16 上 home() 后面板会残留成透明层——dump 只剩状态栏、tap 全部无响应(diff 0%)
def quick_settings(): return _act(op="quicksettings")   # 展开快捷设置(AOSP 语义全局动作; 部分 OEM 只到通知栏够不到控制中心→改用 panel)
def panel(side="right"): return _act(op="panel", side=side)   # 物理下拉顶部面板: right=控制中心(录屏/手电/WiFi 磁贴)/left|center=通知栏(从屏幕最顶端下滑, 不受安全带夹制; 全局动作够不到控制中心时用它)


_BLACK_FRAME_GUARD = True          # FLAG_SECURE 窗口下 a11y takeScreenshot 不报错而返回纯黑位图 → 本漏斗把静默黑帧转为显式报错
_black_streak = {"n": 0}

def _black_check(img):
    """Repeated black frames are unavailable visual evidence, not proof of FLAG_SECURE."""
    g = img.mean(axis=2) if img.ndim == 3 else img
    if not (g.mean() < 8 and g.std() < 6 and (g < 16).mean() > 0.97):
        _black_streak["n"] = 0
        return
    _black_streak["n"] = min(_black_streak["n"] + 1, 2)
    if _black_streak["n"] >= 2:
        raise RuntimeError("连续黑帧，截图无法作为操作依据；原因未确认，请用户检查当前画面。")

_LAST_SHOT = 0.0


def shot(path=None, q=None):
    """截屏。path给出→写文件返回path(默认PNG, q=1~100则JPEG); 否则返回BGR ndarray。
    画面只描述被操作的 App: GA 自身悬浮窗区域已按邻近像素抹平(物理屏上仍可见), 其状态文字不会污染 OCR/ui_detect。
    前台为防截屏窗口时(连续黑帧)抛 RuntimeError 而非返回黑图, 错误信息含降级路径。"""
    global _LAST_SHOT
    gap = time.time() - _LAST_SHOT   # Android 无障碍截图最小间隔 ~333ms, 过快报 code=3
    if gap < 0.34: time.sleep(0.34 - gap)
    try:
        data = _get("/a11y/shot", **({"q": q} if q else {}))
    except RuntimeError as e:
        if str(e).removeprefix("java.lang.RuntimeException: ") != "takeScreenshot failed code=3": raise
        time.sleep(0.35); data = _get("/a11y/shot", **({"q": q} if q else {}))
    _LAST_SHOT = time.time()
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if _BLACK_FRAME_GUARD and img is not None:
        _black_check(img)
    if path:
        open(path, "wb").write(data)
        return path
    return img


# ---------------- onnxruntime shim: 把 ort 调用转发给 APK 总线 ----------------

class _NodeArg:
    def __init__(self, d):
        self.name, self.shape, self.type = d["name"], d["shape"], d["dtype"]


class _RemoteSession:
    """镜像 ort.InferenceSession 最小面: get_inputs/get_outputs/run"""

    def __init__(self, model_path, sess_options=None, providers=None, **kw):
        self._path = _remote_model_path(model_path)
        j = _check(_SESSION.get(_base() + "/onnx/info", params={"model": self._path}, timeout=120))
        self._inputs = [_NodeArg(d) for d in j["inputs"]]
        self._outputs = [_NodeArg(d) for d in j["outputs"]]

    def get_inputs(self): return self._inputs
    def get_outputs(self): return self._outputs

    def run(self, output_names, input_feed):
        import numpy as np
        metas, blobs = [], []
        for name, v in input_feed.items():
            v = np.ascontiguousarray(v)
            metas.append({"name": name, "dtype": str(v.dtype), "shape": list(v.shape)})
            blobs.append(v.tobytes())
        m = json.dumps({"inputs": metas}).encode()
        body = struct.pack("<I", len(m)) + m + b"".join(blobs)
        buf = _check(_SESSION.post(_base() + "/onnx/run", params={"model": self._path},
                                   data=body, timeout=300))
        (mlen,) = struct.unpack_from("<I", buf, 0)
        outs_meta = json.loads(buf[4:4 + mlen].decode())["outputs"]
        off, byname, outs = 4 + mlen, {}, []
        for o in outs_meta:
            n = int(np.prod(o["shape"])) if o["shape"] else 1
            a = np.frombuffer(buf, dtype=np.dtype(o["dtype"]), count=n, offset=off).reshape(o["shape"])
            off += a.nbytes
            outs.append(a)
            byname[o["name"]] = a
        return [byname[n] for n in output_names] if output_names else outs


class _SessOptions:
    pass


def ort_shim():
    """注册假 onnxruntime 模块(转发到总线)。在 import 任何用 ort 的管线前调用。"""
    import types
    cur = sys.modules.get("onnxruntime")
    if cur is not None and getattr(cur, "_droid_shim", False):
        return
    ort = types.ModuleType("onnxruntime")
    ort._droid_shim = True
    ort.InferenceSession = _RemoteSession
    ort.SessionOptions = _SessOptions
    ort.get_available_providers = lambda: ["CPUExecutionProvider"]
    sys.modules["onnxruntime"] = ort


def _bundle():
    ort_shim()
    if BUNDLE not in sys.path:
        sys.path.insert(0, BUNDLE)


def ui_detect(img, conf=0.25):
    """img: BGR ndarray 或 路径 → [{'bbox':[x1,y1,x2,y2],'type':'icon'|'text','label','cls','confidence'}]
    检测器=Android专调YOLOv8n(21类语义)+PP-OCR空间匹配。cls给出控件语义(即便纯图标无文字),
    label=框内OCR文字; 无文字时图标/控件回退为cls语义名, 文字类回退None。"""
    _bundle()
    import ui_detect_lite
    return ui_detect_lite.detect(img, conf=conf)


_ppocr = None


def _ocr_engine():
    global _ppocr
    _bundle()
    if _ppocr is None:
        from ppocr_engine import PPOCR
        _ppocr = PPOCR()
    return _ppocr


def ocr(img):
    """img: BGR ndarray → [(box 4x2 int, text, score), ...]"""
    return _ocr_engine()(img)


def ocr_text(img):
    """img: cropped BGR ndarray → (text, score), without text detection."""
    return _ocr_engine().recognize(img)


# ---------------- app 内自连无线 ADB (类 LADB, 纯 Kotlin libadb, 补 A11y 外 shell) ----------------
# 用户须先手动: 开发者选项 → 无线调试 → 打开。app 不能静默开, 全程手动授权。
# 配对只需一次(证书持久化, 6位码+配对端口来自系统弹窗); 之后 adb_connect() 无参即可(连接端口自动发现,
# 每次开关无线调试端口会变但无需手填)。本机 host 恒 127.0.0.1。

def adb_pair(code, port, host="127.0.0.1"):
    """SPAKE2 配对。code=「使用配对码配对设备」弹窗的6位码, port=该弹窗 IP:后的配对端口。
    ⚠️配对期间那个系统弹窗必须保持前台, 关掉即作废配对信息。成功后证书持久化, 后续不用再 pair。"""
    return _check(_SESSION.post(_base() + "/adb/pair",
                                json={"host": host, "port": int(port), "code": str(code)}, timeout=60))

def adb_connect(port=None, host="127.0.0.1"):
    """建立 ADB-over-TLS 传输。**无参即可**: 自动发现端口(复用上次成功端口 → 5555 → mDNS 通告的连接端口),
    故不用再手填/OCR「无线调试主页」那个每次都变的端口。仅当自动发现失败时才显式传 port。
    之后 adb_shell 断线会自愈重连, 一般不用手动重连。"""
    run_guard.check()   # 僵尸线程护栏: 已取消则不再改设备连接状态
    return _check(_SESSION.post(_base() + "/adb/connect",
                                json={"host": host, "port": int(port) if port else 0}, timeout=60))

def adb_shell(cmd, timeout_ms=30000, max_bytes=262144):
    """跑一条非交互 shell 命令, 收全部输出返回其 stdout(str)。未连接/断线会**自动重连**(先 adb_connect 一次更快)。
    补 A11y 够不到的能力: input tap/text, am start, pm list, dumpsys, wm size, screencap 等。
    ⚠️timeout_ms 必须 > 0(无 '0=无限' 语义); 勿传长驻命令(top / logcat -f / 无 -c 的持续输出) — 会超时, 用 adb_shell_detached。
    ⚠️别用 `| head`/`| head -n`(提前关管道, 命令端无 EOF 会拖到超时) — 要截断用 `head -c N` 或 `sed -n '1,Np'` 或重定向落文件后分段读。
    输出超 max_bytes(默认256KB)会**报错**(不静默截断, 防损坏), 按提示分页; 读大二进制(如截图 base64)显式调大 max_bytes。"""
    run_guard.check()   # adb input tap/swipe 也能驱动手机 → 僵尸线程护栏检查点: 已取消则抛 RunCancelled 自毁
    # shell 注入(input tap/swipe/text/keyevent, sendevent, monkey)对锁定 App 同样过零注入门禁: 这是 a11y 门禁最直接的绕道
    # (deviceId=-1 的 input 事件同样可辨), 前台是微信时一律拒, 不看命令是否"只是查看"——input/sendevent/monkey 本身就是注入。
    if re.match(r"\s*(input|sendevent|monkey)\b", str(cmd)):
        _gate_injection("adb_shell:" + str(cmd).split()[0])
    _record_path("adb")   # 任务路径归属: 无线 adb shell(只记类别, 不记命令内容)
    return _check(_SESSION.post(_base() + "/adb/shell",
                                json={"cmd": str(cmd), "timeout_ms": int(timeout_ms), "max_bytes": int(max_bytes)},
                                timeout=2 * timeout_ms / 1000 + 30))["out"]   # 覆盖 Kotlin 断线重连+重试的最坏时窗, 避免客户端先超时

def adb_shell_detached(tag, cmd):
    """起一条 held-stream 命令(流不关, 立即返回), 用于保活常驻子进程(如 VdHelper)。
    普通 adb_shell 读完 EOF 即关流, adbd 收割该 shell 的所有子进程(含 & 后台的); 唯有流保持开才存活。
    命令须自带 `1>_LOG 2>&1 3>&-`(重定向输出 + 切断 adbd 泄漏的 fd3 控制 socket, 否则常驻子进程持 fd3
    会令后续 adb_shell 读不到 EOF 超时)。回收: 因 3>&- 断 fd3, adb_shell_close 关流不收割进程, 须 kill pid。"""
    run_guard.check()   # 僵尸线程护栏: held-stream 会起常驻设备进程, 已取消则拒绝(防僵尸留后台驻留物)
    r = _SESSION.post(_base() + "/adb/shell_detached",
                      json={"tag": str(tag), "cmd": str(cmd)}, timeout=25)
    if r.status_code == 404:
        raise RuntimeError("GA APK 过旧: 无 /adb/shell_detached 端点, 请先升级 APK 再用虚拟屏"
                           "(部署顺序: APK 先于 python 资产热更新)")
    return _check(r)

def adb_shell_close(tag):
    """清该 tag 的 GA 侧 held 流引用(幂等)。注: 因 3>&- 断 fd3, 关流不 kill 进程, 真 kill 靠调用方 kill pid。
    旧 APK 无端点时返回 False。"""
    r = _SESSION.post(_base() + "/adb/shell_close", json={"tag": str(tag)}, timeout=25)
    return bool(_check(r).get("closed")) if r.status_code != 404 else False

def adb_status():
    """{connected:bool(libadb 派生真值,不再有假态), paired:bool(证书是否已持久化), error:上次错误, port:上次成功连接端口}"""
    return _get("/adb/status")


# ====== 通知读取/回复/控制 ======
# 用户须先手动: 设置 → 通知 → 通知使用权限 → Generic Agent → 允许。
# 否则 is_notification_service_enabled() 返回 False, 其他函数返回空/错误。

def get_notifications():
    """获取当前所有系统通知列表。
    返回: [{"key": "0|com.tencent.mm|...", "pkg": "com.tencent.mm", "title": "...", 
            "text": "...", "time": 1234567890, "canReply": true}, ...]
    未授权通知监听权限时抛 RuntimeError(含授权路径提示), 先用 is_notification_service_enabled() 探测。"""
    return _get("/notifications")

def reply_notification(key, text):
    """回复通知 (仅对支持 RemoteInput 的通知有效，如微信/Telegram 等)。
    Args:
        key: 通知唯一标识 (从 get_notifications 返回的 "key" 字段, 形如 "0|com.tencent.mm|…", 第二段=包名)
        text: 回复内容
    Returns: 成功返回 "ok", 失败返回 "err:..."
    敏感 App(SENSITIVE_APPS act="locked", 如微信)的通知回复走同一道零注入门禁: 未 sensitive_unlock 直接抛错——
    通知栏直回等于替用户发消息, 与 a11y paste+发送是同一风控面(甚至更显眼: 非前台就在发), 不能成为绕门禁的旁路。"""
    run_guard.check()   # 回复通知属操作外界 → 僵尸线程护栏检查点
    parts = str(key).split("|")
    _gate_injection("reply_notification", pkg=parts[1] if len(parts) > 1 else "")
    resp = _check(_SESSION.post(_base() + "/notifications/reply",
                                json={"key": str(key), "text": str(text)}, timeout=30))
    if isinstance(resp, dict):
        return resp.get("ok", "err:bad_response")
    return resp

def dismiss_notification(key):
    """取消/清除单个通知。
    Args:
        key: 通知唯一标识
    Returns: 成功返回 "ok", 失败返回 "err:..."
    """
    run_guard.check()
    resp = _check(_SESSION.post(_base() + "/notifications/dismiss",
                                json={"key": str(key)}, timeout=30))
    if isinstance(resp, dict):
        return resp.get("ok", "err:bad_response")
    return resp

def dismiss_notifications_by_package(pkg):
    """清除指定应用的所有通知。
    Args:
        pkg: 应用包名 (如 "com.tencent.mm")
    Returns: 清除数量 (int)
    """
    run_guard.check()
    resp = _check(_SESSION.post(_base() + "/notifications/dismiss_pkg",
                                json={"pkg": str(pkg)}, timeout=30))
    # 返回可能是 {"count": N} 或直接字符串 "N"
    if isinstance(resp, dict):
        return resp.get("count", 0)
    return int(resp) if str(resp).isdigit() else 0

def is_notification_service_enabled():
    """检查通知监听服务是否已授权并连接。
    Returns: True/False
    """
    resp = _get("/notifications/status")
    # 返回可能是 {"enabled": true} 或直接字符串 "true"/"false"
    if isinstance(resp, dict):
        return bool(resp.get("enabled", False))
    return str(resp).lower() == "true"


def _notif_trigger_contract(resp):
    """Require the fixed native-trigger lifecycle response shape."""
    if not isinstance(resp, dict):
        raise RuntimeError("invalid native notification-trigger response")
    required = {"ok", "running", "listener_enabled", "rule_count", "error"}
    missing = required.difference(resp)
    if missing:
        raise RuntimeError("invalid native notification-trigger response: missing " + ", ".join(sorted(missing)))
    if not isinstance(resp["ok"], bool) or not isinstance(resp["running"], bool):
        raise RuntimeError("invalid native notification-trigger response: bad lifecycle flags")
    if (not isinstance(resp["listener_enabled"], bool)
            or not isinstance(resp["rule_count"], int)
            or isinstance(resp["rule_count"], bool)):
        raise RuntimeError("invalid native notification-trigger response: bad listener state")
    if not isinstance(resp["error"], str):
        raise RuntimeError("invalid native notification-trigger response: bad error")
    return resp


def _notif_trigger_rules_contract(resp):
    """Require lifecycle state plus the complete canonical stored rule list."""
    result = _notif_trigger_contract(resp)
    rules = result.get("rules")
    if not isinstance(rules, list) or len(rules) != result["rule_count"]:
        raise RuntimeError("invalid native notification-trigger response: bad rules")
    fields = {"id", "pkg", "keywords", "task", "enabled", "cooldown_ms"}
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != fields:
            raise RuntimeError(
                "invalid native notification-trigger response: bad rule %d" % index)
        cooldown = rule["cooldown_ms"]
        if (not isinstance(rule["id"], str)
                or not isinstance(rule["pkg"], str)
                or not isinstance(rule["task"], str)
                or not isinstance(rule["enabled"], bool)
                or not isinstance(rule["keywords"], list)
                or any(not isinstance(keyword, str) for keyword in rule["keywords"])
                or not isinstance(cooldown, int)
                or isinstance(cooldown, bool)
                or cooldown < 0):
            raise RuntimeError(
                "invalid native notification-trigger response: bad rule %d" % index)
    return result


def _notif_trigger_response(response):
    try:
        result = _notif_trigger_contract(response.json())
    except ValueError as e:
        raise RuntimeError("invalid native notification-trigger response") from e
    return result


def _notif_trigger_request(response):
    result = _notif_trigger_response(response)
    if not result["ok"]:
        raise RuntimeError(result["error"] or "native notification trigger request failed")
    return result


def _notif_trigger_rules_request(response):
    try:
        result = _notif_trigger_rules_contract(response.json())
    except ValueError as e:
        raise RuntimeError("invalid native notification-trigger response") from e
    if not result["ok"]:
        raise RuntimeError(result["error"] or "native notification trigger request failed")
    return result


def notif_trigger_start(rules):
    """Persist and enable native notification-trigger rules.

    ``rules`` is a JSON list validated by Android. Rule notification fields are
    selectors only; each rule's fixed ``task`` is the sole task payload. A
    disconnected notification listener raises RuntimeError with the Android
    permission path instead of silently enabling a non-working trigger.

    Returns the fixed lifecycle object:
    ``{ok, running, listener_enabled, rule_count, error}``.
    """
    run_guard.check()
    return _notif_trigger_request(_SESSION.post(
        _base() + "/notif-trigger/start", json={"rules": rules}, timeout=30))


def notif_trigger_status():
    """Return ``{ok, running, listener_enabled, rule_count, error}``.

    Status remains readable when notification-listener permission is absent;
    ``listener_enabled`` and ``error`` make that state explicit.
    """
    return _notif_trigger_response(_SESSION.get(
        _base() + "/notif-trigger/status", timeout=60))


def notif_trigger_rules_get():
    """Return lifecycle state plus the complete persisted native rule list."""
    return _notif_trigger_rules_request(_SESSION.get(
        _base() + "/notif-trigger/rules", timeout=60))


def notif_trigger_rules_add(rule):
    """Validate and append one rule, returning the complete resulting list."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/add", json={"rule": rule}, timeout=30))


def notif_trigger_rule_set_enabled(id, enabled):
    """Enable or disable one stored rule without replacing the other rules."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/set-enabled",
        json={"id": id, "enabled": enabled}, timeout=30))


def notif_trigger_rule_delete(id):
    """Delete one stored rule and cancel only that rule's pending work."""
    run_guard.check()
    return _notif_trigger_rules_request(_SESSION.post(
        _base() + "/notif-trigger/rules/delete", json={"id": id}, timeout=30))


def notif_trigger_stop():
    """Disable native notification-trigger rules and cancel only its queued work.

    This is idempotent and returns ``{ok, running, listener_enabled,
    rule_count, error}``; it does not require a currently connected listener.
    """
    run_guard.check()
    return _notif_trigger_request(_SESSION.post(
        _base() + "/notif-trigger/stop", timeout=30))


def alarm_set(id, at, every=0, prompt=""):
    """注册到点唤起 agent 的任务(非系统起床铃)。id 唯一键(同 id 再 set=改期);
    at=下次 epoch ms; every=0 一次, >0 周期 ms; prompt=到期后台新会话指令(call_once)。
    用户要「几点叫我/设闹钟」请开系统时钟 App, 勿用本函数。
    返回 True/False。进程被杀仍可唤醒; 前台任务 running 时当次可能 busy 跳过。"""
    resp = _check(_SESSION.post(_base() + "/alarm/set",
                                json={"id": str(id), "at": int(at),
                                      "every": int(every), "prompt": str(prompt)},
                                timeout=30))
    return bool(resp.get("ok", 0)) if isinstance(resp, dict) else True

def alarm_del(id):
    """删除闹钟 id; 不存在也返回 True。"""
    resp = _check(_SESSION.post(_base() + "/alarm/del",
                                json={"id": str(id)}, timeout=30))
    return bool(resp.get("ok", 0)) if isinstance(resp, dict) else True

def alarm_list():
    """列出已注册闹钟: [{id, at, every, prompt}, ...]。"""
    resp = _get("/alarm/list")
    if isinstance(resp, dict):
        return resp.get("alarms", [])
    return resp or []
